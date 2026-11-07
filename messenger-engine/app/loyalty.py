"""Mr.Buk VIP LINE OA Loyalty & Point Accumulation Engine (@misterbuk / @305lhvvt).

Features:
1. Connects customer orders from Facebook Messenger (`chatbot.db`) AND JST ERP (`check_duplicate_order` / `search_jst_orders_by_receiver_name`)
   to LINE OA `@misterbuk` (`@305lhvvt`).
2. Verifies customer identity via 10-digit Thai phone number (`08x-xxx-xxxx`) OR recipient name (`ชื่อผู้รับ`).
3. Calculates loyalty points according to official Mr.Buk VIP rules:
   - Every 500 THB = 1 point (`int(amount // 500)`)
   - Special allowance: 1kg large bag (`490.-` or VIP 5% `465.-`) = 1 point
   - 5 points  = Free 60g mini pouches x 3 (worth 132 THB) — shipped with next order
   - 10 points = Free 500g medium bag x 1 (worth 249 THB) — shipped with next order
4. Prevents duplicate bill claiming via `LoyaltyClaimedOrder` (`loyalty_claimed_orders` table) with cross-source
   de-duplication between `chatbot.db` and `JST ERP`.
5. Automatically selects and sends the official non-expiring LINE OA Point QR Code image(s):
   `MrBuk_QR_Give_1pt.png`, `MrBuk_QR_Give_2pt.png`, `MrBuk_QR_Give_4pt.png`.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from . import database, jst_erp, media_generator
from .database import LoyaltyClaimedOrder, LoyaltyMember, MessageLog, SessionLocal, UserSession, utcnow

logger = logging.getLogger(__name__)

REWARD_CARD_URL = "https://u.lin.ee/P44JSey"
LINE_OA_HANDLE = "@misterbuk"
VIP_COUPON_CODE = "MRBUKVIP5"

REWARD_TIERS = {
    5: {
        "points_required": 5,
        "reward_code": "FREE_60G_3",
        "reward_name": "ข้าวบุกหอมมะลิซองเล็ก 60 กรัม จำนวน 3 ซอง (มูลค่า 132.-)",
        "short_name": "ฟรี! ซองเล็ก 60g 3 ซอง",
        "value_thb": 132,
    },
    10: {
        "points_required": 10,
        "reward_code": "FREE_500G_1",
        "reward_name": "ข้าวบุกหอมมะลิถุงกลาง 500 กรัม จำนวน 1 ถุง (มูลค่า 249.-)",
        "short_name": "ฟรี! ถุงกลาง 500g 1 ถุง",
        "value_thb": 249,
    },
}

LOYALTY_TRIGGER_KEYWORDS = (
    "สะสมแต้ม",
    "รับแต้ม",
    "เช็กแต้ม",
    "เช็คแต้ม",
    "แต้มสะสม",
    "บัตรสะสมแต้ม",
    "แลกแต้ม",
    "แลกของแถม",
    "ขอแต้ม",
    "เคลมแต้ม",
)

REDEEM_TRIGGER_KEYWORDS = (
    "แลกแต้ม",
    "แลกของแถม",
    "ขอแลกแต้ม",
    "ใช้แต้ม",
    "แลก 5 แต้ม",
    "แลก 10 แต้ม",
    "แลก5แต้ม",
    "แลก10แต้ม",
    "แลกรางวัล",
)


def _polite_name(name: str) -> str:
    n = re.sub(r"^(?:คุณ|พี่|น้อง)\s*", "", (name or "").strip()).strip()
    return f"คุณ{n}" if n else "คุณลูกค้า"


# Known gross totals (product + shipping/COD fee) -> (net_product_thb, shipping_fee_thb)
_GROSS_TO_NET_PRODUCT_MAP: dict[int, tuple[int, int]] = {
    # 60g mini pouch (44.-) + transfer shipping 30.- / COD 70.-
    74: (44, 30),
    114: (44, 70),
    # 500g medium bag (249.-) + transfer shipping 30.- / COD 70.-
    279: (249, 30),
    319: (249, 70),
    # 1kg large bag (490.- or VIP 5% 465.-) + COD 40.-
    505: (465, 40),
    530: (490, 40),
    # 15-pouch set (599.- or VIP 5% 569.-) + COD 40.-
    609: (569, 40),
    639: (599, 40),
    # Duo 2x1kg set (950.- or VIP 5% 902.-) + COD 40.-
    942: (902, 40),
    990: (950, 40),
    # 30-pouch set (1,190.- or VIP 5% 1,130.-) + COD 40.-
    1170: (1130, 40),
    1230: (1190, 40),
    # Common multi-item combinations + COD 40.-
    574: (534, 40),    # 1kg (490) + 60g (44) + COD 40
    779: (739, 40),    # 1kg (490) + 500g (249) + COD 40
    1020: (980, 40),   # 1kg x 2 (490*2=980) + COD 40
    1034: (994, 40),   # Duo (950) + 60g (44) + COD 40
    1239: (1199, 40),  # Duo (950) + 500g (249) + COD 40
    1480: (1440, 40),  # Duo (950) + 1kg (490) + COD 40
}

_PURE_PRODUCT_PRICES: set[int] = {
    44, 88, 132, 176, 220,
    249, 465, 490, 498, 534, 569, 599, 739,
    902, 950, 980, 994, 1130, 1190, 1199, 1440,
    1900, 2270, 2390,
}


def extract_net_product_amount_thb(
    gross_amount_thb: float | int,
    payment_method: str = "",
    freight_thb: float | int = 0,
    raw_text: str = "",
) -> tuple[int, int]:
    """Return `(net_product_thb, shipping_fee_deducted_thb)` by stripping out shipping and COD fees (`30`, `40`, `70` THB).

    Strict rule:
    - Shipping / COD fees NEVER count toward loyalty points or carryover!
    - E.g. 1kg COD `530.-` (`490.-` product + `40.-` COD fee) -> `(490, 40)`.
    - Duo set COD `990.-` (`950.-` product + `40.-` COD fee) -> `(950, 40)`.
    """
    gross = int(round(float(gross_amount_thb or 0)))
    if gross <= 0:
        return 0, 0

    # 1. Exact match in known gross-with-shipping map
    if gross in _GROSS_TO_NET_PRODUCT_MAP:
        return _GROSS_TO_NET_PRODUCT_MAP[gross]

    # 2. If explicit freight is recorded in JST ERP and gross is not already a pure product price
    freight = int(round(float(freight_thb or 0)))
    if freight > 0 and gross > freight and gross not in _PURE_PRODUCT_PRICES:
        return gross - freight, freight

    # 3. Check if payment_method or raw_text indicates COD / shipping fee included
    pay_low = f"{payment_method or ''} {raw_text or ''}".lower()
    is_cod = any(k in pay_low for k in ("cod", "ปลายทาง", "เก็บเงินปลายทาง"))
    if gross not in _PURE_PRODUCT_PRICES:
        if (gross - 40) in _PURE_PRODUCT_PRICES:
            return gross - 40, 40
        if (gross - 30) in _PURE_PRODUCT_PRICES:
            return gross - 30, 30
        if (gross - 70) in _PURE_PRODUCT_PRICES:
            return gross - 70, 70
        if is_cod and 500 <= gross < 2200:
            return gross - 40, 40
        if is_cod and 100 <= gross < 400:
            return gross - 70, 70

    return gross, 0


def calculate_mrbuk_points(order_amount_thb: float | int, allow_1kg_490: bool = False) -> int:
    """Calculate whole Mr.Buk VIP points from a net product amount in THB.

    Strict Rule:
    - Every 500 THB of net product spend (excluding shipping) = 1 point (`int(net_amount // 500)`).
    - 490 THB does NOT get 1 point on its own (`allow_1kg_490=False`); instead, the 490 THB is saved in
      `carryover_thb` by the bot to be combined with the customer's next order!
    """
    net_amt, _ = extract_net_product_amount_thb(order_amount_thb)
    if net_amt <= 0:
        return 0
    if net_amt >= 500:
        return int(net_amt // 500)
    if allow_1kg_490 and net_amt >= 465:
        return 1
    return 0


def calculate_points_and_carryover(
    net_product_thb: int,
    previous_carryover_thb: int = 0,
) -> tuple[int, int]:
    """Calculate `(points_earned_now, new_carryover_thb)` by combining `previous_carryover_thb + net_product_thb`.

    Examples:
    - Order 1: Set 950.- (`prev=0`) -> `pool=950` -> `1 point` + `carryover=450 THB`
    - Order 2: 1kg 490.- (`prev=450`) -> `pool=940` -> `1 point` + `carryover=440 THB`
    - Order 1: 1kg 490.- (`prev=0`) -> `pool=490` -> `0 points` + `carryover=490 THB` (needs 10 THB more on next order)
    """
    pool = max(0, int(previous_carryover_thb or 0)) + max(0, int(net_product_thb or 0))
    return int(pool // 500), int(pool % 500)


def format_facebook_post_purchase_loyalty_invite(order_amount_thb: int, points: int = 0) -> str:
    """Build the post-purchase LINE OA @misterbuk loyalty invitation bubble for Facebook Messenger buyers."""
    net_amt, _ = extract_net_product_amount_thb(order_amount_thb)
    pts, carryover = calculate_points_and_carryover(net_amt, 0)
    if pts > 0 and carryover > 0:
        benefit_txt = (
            f"ออเดอร์นี้ยอดค่าสินค้า {net_amt:,} บาท ได้รับสิทธิ์สะสมแต้ม มิสเตอร์บุก VIP ทันที +{pts} แต้ม "
            f"(พร้อมเก็บเศษสะสมอีก {carryover:,} บาท ไว้ทบรับแต้มในรอบถัดไปค่ะ) 💚"
        )
    elif pts > 0:
        benefit_txt = f"ออเดอร์นี้ยอดค่าสินค้า {net_amt:,} บาท ได้รับสิทธิ์สะสมแต้ม มิสเตอร์บุก VIP จำนวน +{pts} แต้มค่ะ 💚"
    else:
        need = 500 - carryover
        benefit_txt = (
            f"ออเดอร์นี้มียอดค่าสินค้าสะสม {net_amt:,} บาท (ขาดอีกเพียง {need:,} บาท ครบ 500 บาท รับทันที 1 แต้มในออเดอร์ถัดไปค่ะ) 💚"
        )

    return (
        f"🎁 สิทธิ์พิเศษสำหรับคุณลูกค้า! {benefit_txt}\n\n"
        f"📲 แอด LINE Official: {LINE_OA_HANDLE} หรือกดลิงก์บัตรสะสมแต้ม {REWARD_CARD_URL} "
        f"แล้วแจ้งเบอร์โทรศัพท์ 10 หลัก (หรือชื่อผู้รับ) ในแชท LINE เพื่อบันทึกยอดสะสมและรับ QR Code แต้มได้เลยนะคะ\n"
        f"(ทุกยอดสินค้าสุทธิ 500 บาท = 1 แต้ม เก็บเศษทบรอบหน้าได้ / ครบ 5 แต้ม แลกฟรีซอง 60g 3 ซอง / ครบ 10 แต้ม แลกฟรีถุง 500g 1 ถุง รับพร้อมออเดอร์ถัดไปค่ะ 😊)"
    )


def extract_phone_or_name_from_text(text: str) -> tuple[str, str]:
    """Extract a 10-digit normalized Thai phone number and/or clean recipient name candidate from user text."""
    raw = (text or "").strip()
    if not raw:
        return "", ""

    # 1. Check for 10-digit Thai mobile number (06x, 08x, 09x or +66...)
    phone_pattern = r"(?:\+66\s*0?|\b0)[689]\d[\s\-]?\d{3}[\s\-]?\d{4}"
    m_ph = re.search(phone_pattern, raw)
    phone = ""
    if m_ph:
        phone = jst_erp.normalize_thai_phone(m_ph.group(0))
    else:
        digits_only = re.sub(r"\D", "", raw)
        if len(digits_only) == 10 and digits_only.startswith(("06", "08", "09")):
            phone = digits_only

    # 2. Extract name candidate by stripping loyalty keywords and phone numbers
    cleaned = re.sub(phone_pattern, " ", raw)
    for kw in (
        "สะสมแต้ม",
        "รับแต้ม",
        "เช็กแต้ม",
        "เช็คแต้ม",
        "แต้มสะสม",
        "บัตรสะสมแต้ม",
        "แลกแต้ม",
        "แลกของแถม",
        "ขอแต้ม",
        "เคลมแต้ม",
        "เบอร์โทร",
        "เบอร์",
        "ชื่อผู้รับ",
        "ชื่อ",
        "ผู้รับ",
        "ค่ะ",
        "คะ",
        "นะคะ",
        "ค่า",
        "ครับ",
        "จ้า",
    ):
        cleaned = re.sub(rf"{re.escape(kw)}", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^(?:คุณ|นาย|นาง|นางสาว|น\.ส\.|พี่|น้อง)\s*", "", cleaned.strip())
    cleaned = re.sub(r"[\s,.:;\-|/\\📞📱🎁💚✨🍚]+", " ", cleaned).strip()

    # Ignore pure numbers or very short noise
    if len(cleaned) < 2 or cleaned.isdigit():
        cleaned = ""
    return phone, cleaned


def _extract_verified_orders_from_chatbot_db(
    phone: str = "",
    customer_name: str = "",
    brand_id: str = "mrbuk",
    line_user_id: str = "",
) -> tuple[list[dict[str, Any]], str, str]:
    """Search `chatbot.db` (`user_sessions` & `message_log`) for confirmed orders matching `line_user_id`, `phone`, or `customer_name`.

    Returns:
        (orders_list, resolved_phone, resolved_customer_name)
    """
    clean_phone = jst_erp.normalize_thai_phone(phone) if phone else ""
    clean_name = re.sub(r"^(?:คุณ|นาย|นาง|นางสาว|น\.ส\.|พี่|น้อง)\s*", "", (customer_name or "").strip()).strip()
    name_parts = [p.lower() for p in clean_name.split() if len(p) >= 2]
    clean_line_uid = (line_user_id or "").strip()

    found_orders: list[dict[str, Any]] = []
    resolved_phone = clean_phone
    resolved_name = clean_name

    with SessionLocal() as db:
        sessions = db.execute(
            select(UserSession).where(UserSession.brand_id.in_([brand_id, "buksukjai"]))
        ).scalars().all()

        # Prioritize matching brand_id first, then fallback to any session in chatbot.db with matching line_user_id/phone/name
        sessions_sorted = sorted(sessions, key=lambda s: (0 if s.brand_id == brand_id else 1))

        for sess in sessions_sorted:
            if sess.platform == "line_group":
                continue
            msgs = db.execute(
                select(MessageLog)
                .where(MessageLog.psid == sess.psid)
                .order_by(MessageLog.id.asc())
            ).scalars().all()
            if not msgs and not sess.notes:
                continue

            full_chat_text = "\n".join(m.content for m in msgs if m.content)
            notes_text = sess.notes or ""
            combined_text = f"{ sess.customer_name or '' }\n{notes_text}\n{full_chat_text}"

            # Extract all phones present in this session
            raw_phones = re.findall(r"(?:\+66\s*0?|\b0)[689]\d[\s\-]?\d{3}[\s\-]?\d{4}", combined_text)
            sess_phones = [jst_erp.normalize_thai_phone(p) for p in raw_phones if jst_erp.normalize_thai_phone(p)]

            line_matched = bool(
                clean_line_uid
                and (
                    (sess.external_user_id or "").strip() == clean_line_uid
                    or sess.psid == f"{brand_id}:line:{clean_line_uid}"
                    or sess.psid.endswith(f":{clean_line_uid}")
                )
            )
            phone_matched = bool(clean_phone and clean_phone in sess_phones)
            name_matched = False
            if clean_name and not phone_matched and not line_matched:
                target_low = combined_text.lower()
                if clean_name.lower() in target_low or (name_parts and all(p in target_low for p in name_parts)):
                    name_matched = True

            if not line_matched and not phone_matched and not name_matched:
                continue

            if not resolved_phone and sess_phones:
                resolved_phone = sess_phones[-1]

            # Extract recipient name if available
            sess_cust_name = (sess.customer_name or "").strip()
            if sess_cust_name and not sess_cust_name.startswith("ลูกค้า "):
                if not resolved_name:
                    resolved_name = sess_cust_name

            # Check for explicit JST ERP order tag in session notes: `[JST ERP: ... #233281 ...]`
            jst_oids_in_notes = re.findall(r"#(\d{5,10})", notes_text)
            linked_jst_oid = jst_oids_in_notes[-1] if jst_oids_in_notes else ""

            # Find all #BUY<amount> tags in message_log
            buy_events: list[tuple[int, int, str]] = []
            for m in msgs:
                if m.role != "user" and m.content:
                    for bm in re.findall(r"#\s*BUY\s*([\d,]+)", m.content, flags=re.IGNORECASE):
                        digits = bm.replace(",", "").strip()
                        if digits.isdigit() and int(digits) >= 39:
                            dt_str = m.created_at.strftime("%Y-%m-%d %H:%M:%S") if m.created_at else ""
                            buy_events.append((m.id, int(digits), dt_str))

            # Also check `[ROAS: บันทึกยอดซื้อ X บาท ...]` in notes
            roas_amounts = [
                int(x.replace(",", ""))
                for x in re.findall(r"\[ROAS:\s*บันทึกยอดซื้อ\s*([\d,]+)\s*บาท", notes_text)
                if x.replace(",", "").isdigit()
            ]

            if buy_events:
                # Deduplicate consecutive identical #BUY amounts in the same inquiry within the same day
                seen_day_amt: set[tuple[str, int]] = set()
                for msg_id, amt, dt_str in buy_events:
                    day_key = (dt_str[:10], amt)
                    if day_key in seen_day_amt:
                        continue
                    seen_day_amt.add(day_key)
                    net_amt, ship_fee = extract_net_product_amount_thb(amt, raw_text=combined_text)
                    order_ref = f"JST:{linked_jst_oid}" if (linked_jst_oid and len(buy_events) == 1) else f"CHAT:{sess.psid}:{msg_id}"
                    found_orders.append(
                        {
                            "order_ref": order_ref,
                            "chat_alias_ref": f"CHAT:{sess.psid}:{msg_id}",
                            "jst_order_id": linked_jst_oid if len(buy_events) == 1 else "",
                            "source": "chatbot_db",
                            "psid": sess.psid,
                            "platform": sess.platform,
                            "phone": resolved_phone or (sess_phones[-1] if sess_phones else ""),
                            "customer_name": resolved_name or sess_cust_name,
                            "gross_amount_thb": amt,
                            "shipping_fee_thb": ship_fee,
                            "order_amount_thb": net_amt,
                            "points": calculate_mrbuk_points(net_amt),
                            "order_date": dt_str or (sess.purchased_at.strftime("%Y-%m-%d %H:%M:%S") if sess.purchased_at else ""),
                            "status": "ชำระเงิน/ยืนยันออเดอร์แล้ว (Facebook/Chat)",
                        }
                    )
            elif sess.state == "completed" or sess.is_starred or roas_amounts:
                amt = roas_amounts[-1] if roas_amounts else 0
                if not amt:
                    try:
                        ext = jst_erp.extract_order_from_session(sess.psid)
                        amt = int(round(float(ext.get("total_amount") or 0)))
                        if not resolved_name and (ext.get("parsed_address") or {}).get("receiver_name"):
                            resolved_name = ext["parsed_address"]["receiver_name"]
                    except Exception:
                        amt = 0
                if amt >= 39:
                    net_amt, ship_fee = extract_net_product_amount_thb(amt, raw_text=combined_text)
                    dt_obj = sess.purchased_at or sess.last_interaction_time or sess.created_at
                    dt_str = dt_obj.strftime("%Y-%m-%d %H:%M:%S") if dt_obj else ""
                    order_ref = f"JST:{linked_jst_oid}" if linked_jst_oid else f"CHAT:{sess.psid}:COMPLETED"
                    found_orders.append(
                        {
                            "order_ref": order_ref,
                            "chat_alias_ref": f"CHAT:{sess.psid}:COMPLETED",
                            "jst_order_id": linked_jst_oid,
                            "source": "chatbot_db",
                            "psid": sess.psid,
                            "platform": sess.platform,
                            "phone": resolved_phone or (sess_phones[-1] if sess_phones else ""),
                            "customer_name": resolved_name or sess_cust_name,
                            "gross_amount_thb": amt,
                            "shipping_fee_thb": ship_fee,
                            "order_amount_thb": net_amt,
                            "points": calculate_mrbuk_points(net_amt),
                            "order_date": dt_str,
                            "status": "ยืนยันคำสั่งซื้อแล้ว (Chat DB)",
                        }
                    )

    return found_orders, resolved_phone, resolved_name


def find_verifiable_orders(
    phone: str = "",
    customer_name: str = "",
    brand_id: str = "mrbuk",
    line_user_id: str = "",
) -> dict[str, Any]:
    """Query `chatbot.db` (by `line_user_id`, `phone`, or `customer_name`) and `jst_erp.check_duplicate_order` (JST ERP)
    and merge/de-duplicate orders.
    """
    chat_orders, resolved_phone, resolved_name = _extract_verified_orders_from_chatbot_db(
        phone=phone,
        customer_name=customer_name,
        brand_id=brand_id,
        line_user_id=line_user_id,
    )

    jst_orders_raw: list[dict[str, Any]] = []
    if resolved_phone:
        try:
            jst_res = jst_erp.check_duplicate_order(resolved_phone, within_days=365)
            jst_orders_raw = list(jst_res.get("historical_orders") or [])
        except Exception as exc:
            logger.warning("JST ERP order lookup for phone %s failed: %s", resolved_phone, exc)
    elif resolved_name:
        try:
            jst_orders_raw = jst_erp.search_jst_orders_by_receiver_name(resolved_name, limit=100)
            for jo in jst_orders_raw:
                if jo.get("receiver_mobile") and not resolved_phone:
                    resolved_phone = jst_erp.normalize_thai_phone(str(jo["receiver_mobile"]))
        except Exception as exc:
            logger.warning("JST ERP order lookup for name %s failed: %s", resolved_name, exc)

    # Convert JST ERP raw orders into standardized order dicts (stripping shipping/COD fees)
    jst_orders: list[dict[str, Any]] = []
    for jo in jst_orders_raw:
        oid = str(jo.get("order_id") or "").strip()
        if not oid:
            continue
        gross_amt = int(round(float(jo.get("pay_amount") or 0.0)))
        if gross_amt <= 0:
            continue
        net_amt, ship_fee = extract_net_product_amount_thb(
            gross_amt,
            payment_method=str(jo.get("payment") or ""),
            freight_thb=float(jo.get("freight") or 0.0),
        )
        r_name = str(jo.get("receiver_name") or "").strip()
        if r_name and not resolved_name:
            resolved_name = r_name
        r_phone = jst_erp.normalize_thai_phone(str(jo.get("receiver_mobile") or resolved_phone or ""))
        if r_phone and not resolved_phone:
            resolved_phone = r_phone
        jst_orders.append(
            {
                "order_ref": f"JST:{oid}",
                "chat_alias_ref": "",
                "jst_order_id": oid,
                "source": "jst_erp",
                "psid": "",
                "platform": "jst_erp",
                "phone": r_phone or resolved_phone,
                "customer_name": r_name or resolved_name,
                "gross_amount_thb": gross_amt,
                "shipping_fee_thb": ship_fee,
                "order_amount_thb": net_amt,
                "points": calculate_mrbuk_points(net_amt),
                "order_date": str(jo.get("order_time") or ""),
                "status": str(jo.get("status") or "ในระบบคลัง JST ERP"),
            }
        )

    # Merge & De-duplicate between `chatbot.db` and `jst_erp`
    merged_orders: list[dict[str, Any]] = list(jst_orders)
    for co in chat_orders:
        matched_jst = None
        co_oid = co.get("jst_order_id") or ""
        co_amt = int(co.get("order_amount_thb") or 0)
        co_day = (co.get("order_date") or "")[:10]

        for jo in merged_orders:
            if jo["source"] != "jst_erp":
                continue
            if co_oid and jo.get("jst_order_id") == co_oid:
                matched_jst = jo
                break
            jo_amt = int(jo.get("order_amount_thb") or 0)
            jo_day = (jo.get("order_date") or "")[:10]
            if abs(co_amt - jo_amt) <= 40:
                if not co_day or not jo_day or co_day == jo_day:
                    matched_jst = jo
                    break
                try:
                    d1 = datetime.strptime(co_day, "%Y-%m-%d")
                    d2 = datetime.strptime(jo_day, "%Y-%m-%d")
                    if abs((d1 - d2).days) <= 3:
                        matched_jst = jo
                        break
                except Exception:
                    pass

        if matched_jst is not None:
            if co.get("chat_alias_ref"):
                matched_jst["chat_alias_ref"] = co["chat_alias_ref"]
            if co.get("psid") and not matched_jst.get("psid"):
                matched_jst["psid"] = co["psid"]
        else:
            merged_orders.append(co)

    # Sort chronologically (oldest first) so cumulative carryover math is always deterministic
    merged_orders.sort(key=lambda o: str(o.get("order_date") or ""))

    return {
        "phone": resolved_phone,
        "customer_name": resolved_name,
        "orders": merged_orders,
    }


def get_member_summary(phone: str = "", line_user_id: str = "", brand_id: str = "mrbuk") -> dict[str, Any] | None:
    """Return current loyalty member record and claimed order history."""
    clean_phone = jst_erp.normalize_thai_phone(phone) if phone else ""
    with SessionLocal() as db:
        member = None
        if clean_phone:
            member = db.get(LoyaltyMember, clean_phone)
        if member is None and line_user_id:
            member = db.execute(
                select(LoyaltyMember).where(
                    LoyaltyMember.line_user_id == line_user_id,
                    LoyaltyMember.brand_id == brand_id,
                )
            ).scalars().first()
        if member is None:
            return None

        claimed_rows = db.execute(
            select(LoyaltyClaimedOrder)
            .where(LoyaltyClaimedOrder.phone == member.phone)
            .order_by(LoyaltyClaimedOrder.claimed_at.desc())
        ).scalars().all()

        return {
            "phone": member.phone,
            "brand_id": member.brand_id,
            "customer_name": member.customer_name,
            "line_user_id": member.line_user_id,
            "fb_psid": member.fb_psid,
            "total_points": member.total_points or 0,
            "lifetime_points": member.lifetime_points or 0,
            "lifetime_spend_thb": member.lifetime_spend_thb or 0,
            "carryover_thb": member.carryover_thb or 0,
            "pending_reward": member.pending_reward or "",
            "redeemed_history": member.redeemed_history or "",
            "claimed_orders": [
                {
                    "order_ref": r.order_ref,
                    "source": r.source,
                    "order_amount_thb": r.order_amount_thb,
                    "points_awarded": r.points_awarded,
                    "qr_images_sent": r.qr_images_sent,
                    "order_date": r.order_date,
                    "claimed_at": r.claimed_at.isoformat() if r.claimed_at else None,
                }
                for r in claimed_rows
                if not r.order_ref.startswith("ALIAS:")
            ],
        }


def _format_carryover_line(carryover_thb: int) -> str:
    """Format the Thai status line for the customer's carryover cash remainder (`carryover_thb`)."""
    c = int(carryover_thb or 0)
    if c <= 0:
        return "💰 ยอดเงินสะสมยกไปรอบหน้า: 0 บาท (ทุกยอดค่าสินค้าสุทธิ 500 บาท = รับ 1 แต้มค่ะ)"
    need = 500 - c
    return (
        f"💰 ยอดเงินสะสมยกไปรอบหน้า: {c:,} บาท "
        f"(สั่งซื้อรอบถัดไปเพิ่มยอดค่าสินค้าอีกเพียง {need:,} บาท ก็จะครบ 500 บาทและรับเพิ่มอีก +1 แต้มทันทีค่ะ)"
    )


def _format_order_amount_detail(order: dict[str, Any]) -> str:
    """Format an order's net product price (showing shipping deduction if shipping/COD fee was stripped)."""
    net_amt = int(order.get("order_amount_thb") or 0)
    gross_amt = int(order.get("gross_amount_thb") or net_amt)
    ship_fee = int(order.get("shipping_fee_thb") or 0)
    if ship_fee > 0 and gross_amt > net_amt:
        return f"ยอดค่าสินค้าสุทธิ {net_amt:,} บาท (จากยอดรวม {gross_amt:,} บาท หักค่าจัดส่ง {ship_fee:,} บาท)"
    return f"ยอดค่าสินค้าสุทธิ {net_amt:,} บาท"


def claim_points_for_customer(
    phone: str = "",
    customer_name: str = "",
    line_user_id: str = "",
    brand_id: str = "mrbuk",
) -> dict[str, Any]:
    """Verify orders from `chatbot.db` + `jst_erp.check_duplicate_order`, exclude shipping/COD fees,
    prevent duplicate bill claims, accumulate carryover remainder (`carryover_thb`) across orders,
    credit whole points (every 500 THB = 1 point; 490 THB is not rounded up, but carried forward),
    and return QR Code media items (`1pt`, `2pt`, `4pt`) + Thai reply bubbles.
    """
    database.init_db()
    lookup = find_verifiable_orders(
        phone=phone,
        customer_name=customer_name,
        brand_id=brand_id,
        line_user_id=line_user_id,
    )
    resolved_phone = lookup["phone"]
    resolved_name = lookup["customer_name"]
    all_orders = lookup["orders"]

    if not all_orders:
        existing_mem = get_member_summary(phone=resolved_phone, line_user_id=line_user_id, brand_id=brand_id)
        if existing_mem:
            pts = existing_mem["total_points"]
            carry = existing_mem.get("carryover_thb", 0)
            reward_status = _format_reward_eligibility_line(pts, existing_mem.get("pending_reward", ""))
            carry_line = _format_carryover_line(carry)
            bubbles = [
                f"ข้อมูลบัตรสะสมแต้ม มิสเตอร์บุก VIP ของ{_polite_name(existing_mem['customer_name'])} ค่ะ 🍚💚\n\n"
                f"• แต้มสะสมคงเหลือปัจจุบัน: {pts} แต้ม\n"
                f"• {carry_line}\n"
                f"• ยอดค่าสินค้าสะสมรวมทั้งหมด: {existing_mem['lifetime_spend_thb']:,} บาท (รับแต้มสะสมรวม {existing_mem['lifetime_points']} แต้ม)\n\n"
                f"{reward_status}",
                f"สามารถเปิดดูบัตรสะสมแต้มและคูปองใน LINE ได้ที่ {REWARD_CARD_URL} เลยนะคะ 😊🙏",
            ]
            return {
                "status": "existing_member_no_new_orders",
                "phone": existing_mem["phone"],
                "customer_name": existing_mem["customer_name"],
                "newly_claimed_points": 0,
                "total_points": pts,
                "carryover_thb": carry,
                "newly_claimed_orders": [],
                "already_claimed_orders": existing_mem["claimed_orders"],
                "qr_media_items": [],
                "bubbles": bubbles,
            }

        target_label = f"เบอร์โทร {resolved_phone}" if resolved_phone else (f"ชื่อผู้รับ \"{resolved_name}\"" if resolved_name else "บัญชี LINE นี้")
        bubbles = [
            f"น้องบุกตรวจสอบในระบบจาก{target_label}แล้ว ยังไม่พบรายการคำสั่งซื้อใน LINE OA ที่ยืนยันแล้วเลยค่ะ 🙏💚",
            f"สำหรับการสะสมแต้มและรับคูปองของแถม จะคำนวณจากยอดสั่งซื้อผ่าน LINE OA (@misterbuk) เท่านั้นนะคะ "
            f"(เพื่อนใน LINE รับสิทธิ์คูปองส่วนลด 5% รหัส {VIP_COUPON_CODE} ได้ทันทีค่ะ) สนใจรับโปรโมชั่นเซ็ตไหนแจ้งน้องบุกในแชทนี้ได้เลยนะคะ 😊🍚",
        ]
        return {
            "status": "not_found",
            "phone": resolved_phone,
            "customer_name": resolved_name,
            "newly_claimed_points": 0,
            "total_points": 0,
            "carryover_thb": 0,
            "newly_claimed_orders": [],
            "already_claimed_orders": [],
            "qr_media_items": [],
            "bubbles": bubbles,
        }

    newly_claimed: list[dict[str, Any]] = []
    already_claimed: list[dict[str, Any]] = []

    member_phone_key = resolved_phone or (f"LINE:{line_user_id[:20]}" if line_user_id else f"NAME:{resolved_name[:12]}")

    with SessionLocal() as db:
        # Upsert LoyaltyMember first so we have their current `carryover_thb` before processing new orders
        member = db.get(LoyaltyMember, member_phone_key)
        if member is None:
            member = LoyaltyMember(
                phone=member_phone_key,
                brand_id=brand_id,
                customer_name=resolved_name or "คุณลูกค้า VIP",
                line_user_id=line_user_id or "",
                fb_psid=next((o["psid"] for o in all_orders if o.get("psid")), ""),
                total_points=0,
                lifetime_points=0,
                lifetime_spend_thb=0,
                carryover_thb=0,
                pending_reward="",
                redeemed_history="",
            )
            db.add(member)

        if resolved_name and (not member.customer_name or member.customer_name == "คุณลูกค้า VIP"):
            member.customer_name = resolved_name
        if line_user_id:
            member.line_user_id = line_user_id
        for o in all_orders:
            if o.get("psid") and not member.fb_psid:
                member.fb_psid = o["psid"]

        running_carryover = int(member.carryover_thb or 0)
        initial_carryover = running_carryover

        # Load all existing claimed orders for this phone
        existing_claims_by_phone = db.execute(
            select(LoyaltyClaimedOrder).where(LoyaltyClaimedOrder.phone == member_phone_key)
        ).scalars().all()

        for order in all_orders:
            o_ref = order["order_ref"]
            alias_ref = order.get("chat_alias_ref") or ""
            o_amt = int(order.get("order_amount_thb") or 0)
            o_date = str(order.get("order_date") or "")

            if o_amt <= 0:
                continue

            # Check 1: Direct primary key match on `order_ref` or `alias_ref`
            claimed_rec = db.get(LoyaltyClaimedOrder, o_ref)
            if claimed_rec is None and alias_ref:
                claimed_rec = db.get(LoyaltyClaimedOrder, f"ALIAS:{alias_ref}") or db.get(LoyaltyClaimedOrder, alias_ref)

            # Check 2: Cross-source duplicate guard (same phone + same net amount within ±40 THB on same/adjacent date already claimed)
            if claimed_rec is None:
                for ec in existing_claims_by_phone:
                    if ec.order_ref.startswith("ALIAS:"):
                        continue
                    if abs((ec.order_amount_thb or 0) - o_amt) <= 40:
                        ec_day = (ec.order_date or "")[:10]
                        o_day = o_date[:10]
                        if ec_day and o_day and ec_day == o_day and ec.order_ref != o_ref:
                            if (ec.source == "chatbot_db" and order["source"] == "jst_erp") or (
                                ec.source == "jst_erp" and order["source"] == "chatbot_db"
                            ):
                                claimed_rec = ec
                                break

            if claimed_rec is not None:
                already_claimed.append(
                    {
                        **order,
                        "claimed_at": claimed_rec.claimed_at.isoformat() if claimed_rec.claimed_at else "",
                        "points_awarded": claimed_rec.points_awarded,
                    }
                )
                continue

            # Not yet claimed! Combine `running_carryover + o_amt` -> `(o_pts, running_carryover)`
            prev_c = running_carryover
            o_pts, running_carryover = calculate_points_and_carryover(o_amt, running_carryover)
            qr_items_for_order = media_generator.get_mrbuk_qr_media_for_points(o_pts) if o_pts > 0 else []
            qr_filenames = ",".join(it["filename"] for it in qr_items_for_order)

            new_claim = LoyaltyClaimedOrder(
                order_ref=o_ref,
                brand_id=brand_id,
                phone=member_phone_key,
                customer_name=order.get("customer_name") or resolved_name,
                claimed_by_line_user_id=line_user_id or "",
                source=order["source"],
                order_amount_thb=o_amt,
                points_awarded=o_pts,
                qr_images_sent=qr_filenames,
                order_date=o_date,
                claimed_at=utcnow(),
            )
            db.add(new_claim)
            existing_claims_by_phone.append(new_claim)

            # Lock the alias_ref if present so neither CHAT: nor JST: can be claimed again
            if alias_ref and alias_ref != o_ref and db.get(LoyaltyClaimedOrder, f"ALIAS:{alias_ref}") is None:
                db.add(
                    LoyaltyClaimedOrder(
                        order_ref=f"ALIAS:{alias_ref}",
                        brand_id=brand_id,
                        phone=member_phone_key,
                        customer_name=order.get("customer_name") or resolved_name,
                        claimed_by_line_user_id=line_user_id or "",
                        source=order["source"],
                        order_amount_thb=o_amt,
                        points_awarded=0,
                        qr_images_sent="",
                        order_date=o_date,
                        claimed_at=utcnow(),
                    )
                )

            newly_claimed.append(
                {
                    **order,
                    "points": o_pts,
                    "points_awarded": o_pts,
                    "carryover_before_thb": prev_c,
                    "carryover_after_thb": running_carryover,
                    "qr_filenames": qr_filenames,
                }
            )

        new_pts_total = sum(int(o["points_awarded"]) for o in newly_claimed)
        new_spend_total = sum(int(o["order_amount_thb"]) for o in newly_claimed)

        if newly_claimed:
            member.total_points = (member.total_points or 0) + new_pts_total
            member.lifetime_points = (member.lifetime_points or 0) + new_pts_total
            member.lifetime_spend_thb = (member.lifetime_spend_thb or 0) + new_spend_total
            member.carryover_thb = running_carryover
            member.updated_at = utcnow()

        current_total_points = member.total_points or 0
        current_carryover_thb = member.carryover_thb or 0
        current_pending_reward = member.pending_reward or ""
        cust_display_name = member.customer_name or resolved_name or "คุณลูกค้า"
        db.commit()

    # Sync backup snapshot (`reports/mrbuk_loyalty_ledger.json` & `.csv`) for offline/mobile inspection
    _sync_loyalty_ledger_snapshot(brand_id=brand_id)

    # Also tag the LINE session in `user_sessions` if `line_user_id` is provided
    if line_user_id:
        line_psid = database.make_session_key(brand_id, "line", line_user_id)
        sess = database.get_or_create_session(
            psid=line_psid,
            brand_id=brand_id,
            platform="line",
            external_user_id=line_user_id,
            customer_name=cust_display_name,
        )
        new_tags = database._add_tag_str(
            sess.broadcast_tags or "",
            f"VIP แต้มสะสม ({current_total_points} แต้ม | เศษสะสม {current_carryover_thb} บ.)",
        )
        note_line = (
            f"[LOYALTY VIP: เบอร์ {member_phone_key} | แต้มคงเหลือ {current_total_points} แต้ม "
            f"| ยอดสะสมยกไป {current_carryover_thb} บาท]"
        )
        updated_notes = sess.notes or ""
        if f"เบอร์ {member_phone_key}" not in updated_notes:
            updated_notes = f"{updated_notes}\n{note_line}".strip() if updated_notes else note_line
        database.update_session_meta(
            psid=line_psid,
            customer_name=cust_display_name if sess.customer_name.startswith("ลูกค้า ") else None,
            broadcast_tags=new_tags,
            notes=updated_notes,
        )

    carry_line = _format_carryover_line(current_carryover_thb)
    reward_line = _format_reward_eligibility_line(current_total_points, current_pending_reward)

    # Case A: Newly claimed orders yielded >= 1 whole point -> Send QR Code image(s) + carryover summary!
    if new_pts_total > 0:
        qr_media_items = media_generator.get_mrbuk_qr_media_for_points(new_pts_total)
        order_lines = []
        for o in newly_claimed:
            ref_short = f"#{o['jst_order_id']}" if o.get("jst_order_id") else "ออเดอร์หน้าเพจ"
            amt_detail = _format_order_amount_detail(o)
            if o.get("carryover_before_thb", 0) > 0:
                order_lines.append(
                    f"• บิล {ref_short} {amt_detail} (+ ทบยอดสะสมเดิม {o['carryover_before_thb']:,} บาท) "
                    f"= รับ +{o['points_awarded']} แต้ม (เหลือเศษสะสม {o['carryover_after_thb']:,} บาท)"
                )
            else:
                order_lines.append(
                    f"• บิล {ref_short} {amt_detail} = รับ +{o['points_awarded']} แต้ม "
                    f"(เหลือเศษสะสม {o['carryover_after_thb']:,} บาท)"
                )
        orders_block = "\n".join(order_lines)

        bubbles = [
            f"เย้! 🎉 ยืนยันตัวตนสำเร็จค่ะ{_polite_name(cust_display_name)} (เบอร์ {member_phone_key}) 🍚💚\n\n"
            f"📋 รายการออเดอร์ที่คำนวณแต้มในครั้งนี้ (คิดจากยอดค่าสินค้าสุทธิ ไม่รวมค่าจัดส่ง):\n"
            f"{orders_block}\n\n"
            f"⭐ ได้รับแต้มเพิ่มในครั้งนี้: +{new_pts_total} แต้ม\n"
            f"🏆 แต้มสะสมรวมปัจจุบัน: {current_total_points} แต้ม\n"
            f"{carry_line}",
            f"📲 น้องบุกส่งรูป QR Code สำหรับกดติ๊กรับ +{new_pts_total} แต้ม เข้าบัตรสะสมแต้ม มิสเตอร์บุก VIP ให้ด้านบนนี้แล้วนะคะ\n\n"
            f"• กดสแกนรูป QR Code ด้านบนเพื่อติ๊กแต้มในบัตร LINE ได้เลยค่ะ ส่วนเศษยอดเงินสะสม ({current_carryover_thb:,} บาท) "
            f"ระบบของน้องบุกบันทึกผูกกับเบอร์โทร {member_phone_key} ไว้ทบกับออเดอร์ถัดไปให้อัตโนมัติเรียบร้อยแล้วค่ะ 😊\n\n"
            f"{reward_line}",
        ]
        return {
            "status": "claimed",
            "phone": member_phone_key,
            "customer_name": cust_display_name,
            "newly_claimed_points": new_pts_total,
            "total_points": current_total_points,
            "carryover_thb": current_carryover_thb,
            "newly_claimed_orders": newly_claimed,
            "already_claimed_orders": already_claimed,
            "qr_media_items": qr_media_items,
            "bubbles": bubbles,
        }

    # Case B: Newly claimed order(s) were under 500 THB even after carryover (e.g., first order 1kg 490.-)
    # -> Saved into `carryover_thb` for the next order! No QR code sent yet.
    if newly_claimed:
        order_lines = []
        for o in newly_claimed:
            ref_short = f"#{o['jst_order_id']}" if o.get("jst_order_id") else "ออเดอร์หน้าเพจ"
            amt_detail = _format_order_amount_detail(o)
            order_lines.append(f"• บิล {ref_short} {amt_detail}")
        orders_block = "\n".join(order_lines)
        need_more = 500 - current_carryover_thb

        bubbles = [
            f"น้องบุกบันทึกยอดสะสมของ{_polite_name(cust_display_name)} (เบอร์ {member_phone_key}) เข้าสมุดสะสมแต้มเรียบร้อยแล้วค่ะ 🍚💚\n\n"
            f"📋 รายการออเดอร์ที่บันทึกยอดสะสม (คิดจากยอดค่าสินค้าสุทธิ ไม่รวมค่าจัดส่ง):\n"
            f"{orders_block}\n\n"
            f"💰 ยอดเงินสะสมยกไปรอบหน้าปัจจุบัน: {current_carryover_thb:,} บาท\n"
            f"🏆 แต้มสะสมปัจจุบัน: {current_total_points} แต้ม ค่ะ",
            f"สำหรับกติกาบัตรสะสมแต้ม มิสเตอร์บุก VIP จะได้รับ 1 แต้มทุกยอดค่าสินค้าสุทธิครบ 500 บาทค่ะ "
            f"ตอนนี้คุณลูกค้ามียอดสะสมฝากไว้กับน้องบุกแล้ว {current_carryover_thb:,} บาท (ขาดอีกเพียง {need_more:,} บาทจะครบ 500 บาทค่ะ) "
            f"เมื่อสั่งซื้อรอบถัดไป ระบบจะนำยอด {current_carryover_thb:,} บาทนี้ไปทบให้อัตโนมัติและส่งรูป QR Code แต้มสะสมให้ทันทีเลยนะคะ 😊🙏",
        ]
        return {
            "status": "accumulated_carryover",
            "phone": member_phone_key,
            "customer_name": cust_display_name,
            "newly_claimed_points": 0,
            "total_points": current_total_points,
            "carryover_thb": current_carryover_thb,
            "newly_claimed_orders": newly_claimed,
            "already_claimed_orders": already_claimed,
            "qr_media_items": [],
            "bubbles": bubbles,
        }

    # Case C: All orders were ALREADY claimed previously (Duplicate Claim Prevention!)
    claimed_lines = []
    for o in already_claimed[:3]:
        ref_short = f"#{o['jst_order_id']}" if o.get("jst_order_id") else "ออเดอร์หน้าเพจ"
        amt_detail = _format_order_amount_detail(o)
        pts_aw = int(o.get("points_awarded") or 0)
        pts_txt = f"รับไปแล้ว +{pts_aw} แต้ม" if pts_aw > 0 else "บันทึกทบยอดสะสมแล้ว"
        claimed_lines.append(f"• บิล {ref_short} {amt_detail} ({pts_txt})")
    claimed_block = "\n".join(claimed_lines)

    bubbles = [
        f"น้องบุกตรวจสอบข้อมูลของ{_polite_name(cust_display_name)} (เบอร์ {member_phone_key}) ให้เรียบร้อยแล้วค่ะ 🍚💚\n\n"
        f"รายการคำสั่งซื้อล่าสุดได้ถูกบันทึกสะสมแต้มและยอดสะสมไปเรียบร้อยแล้วนะคะ:\n"
        f"{claimed_block}\n\n"
        f"🏆 แต้มสะสมคงเหลือปัจจุบัน: {current_total_points} แต้ม\n"
        f"{carry_line}",
        f"{reward_line}\n\n"
        f"สามารถเช็กบัตรสะสมแต้มได้ที่ {REWARD_CARD_URL} หรือหากต้องการสั่งซื้อรอบถัดไปเพื่อทบยอดรับแต้ม/รับของแถม ทักบอกน้องบุกในแชทนี้ได้เลยนะคะ 😊🙏",
    ]
    return {
        "status": "already_claimed",
        "phone": member_phone_key,
        "customer_name": cust_display_name,
        "newly_claimed_points": 0,
        "total_points": current_total_points,
        "carryover_thb": current_carryover_thb,
        "newly_claimed_orders": [],
        "already_claimed_orders": already_claimed,
        "qr_media_items": [],
        "bubbles": bubbles,
    }


def _format_reward_eligibility_line(total_points: int, pending_reward: str = "") -> str:
    """Format a clear Thai message explaining the customer's current reward tier progress."""
    lines = []
    if pending_reward:
        lines.append(f"🎁 สิทธิ์ของแถมที่แลกไว้แล้ว (รอจัดส่งพร้อมออเดอร์ถัดไป): {pending_reward}")

    if total_points >= 10:
        lines.append(
            "🎉 ยินดีด้วยค่า! คุณลูกค้าสะสมครบ 10 แต้มแล้ว สามารถแลกรับฟรี! "
            "ข้าวบุกหอมมะลิถุงกลาง 500 กรัม จำนวน 1 ถุง (มูลค่า 249.-) หรือแลก 5 แต้ม รับฟรีซองเล็ก 60g จำนวน 3 ซอง (มูลค่า 132.-) "
            "ไปพร้อมกับการสั่งซื้อครั้งถัดไปได้เลยค่ะ (พิมพ์ว่า \"แลก 10 แต้ม\" หรือ \"แลก 5 แต้ม\" แจ้งน้องบุกได้เลยนะคะ)"
        )
    elif total_points >= 5:
        need_for_10 = 10 - total_points
        lines.append(
            f"🎉 ยินดีด้วยค่า! คุณลูกค้าสะสมครบ {total_points} แต้มแล้ว สามารถใช้ 5 แต้ม แลกรับฟรี! "
            f"ข้าวบุกหอมมะลิซองเล็ก 60 กรัม จำนวน 3 ซอง (มูลค่า 132.-) ไปพร้อมกับการสั่งซื้อครั้งถัดไปได้เลยค่ะ "
            f"(หรือสะสมเพิ่มอีกเพียง {need_for_10} แต้ม เพื่อแลกรับฟรีถุงกลาง 500 กรัม 1 ถุง มูลค่า 249.- ค่ะ)"
        )
    else:
        need_for_5 = max(1, 5 - total_points)
        lines.append(
            f"💡 สะสมเพิ่มอีกเพียง {need_for_5} แต้ม (ครบ 5 แต้ม) รับฟรี! ข้าวบุกหอมมะลิซองเล็ก 60 กรัม จำนวน 3 ซอง (มูลค่า 132.-) "
            f"หรือสะสมครบ 10 แต้ม รับฟรี! ถุงกลาง 500 กรัม จำนวน 1 ถุง (มูลค่า 249.-) ไปพร้อมกับออเดอร์ถัดไปได้เลยค่ะ"
        )
    return "\n".join(lines)


def redeem_loyalty_points(
    phone: str = "",
    line_user_id: str = "",
    requested_tier: int | None = None,
    brand_id: str = "mrbuk",
) -> dict[str, Any]:
    """Redeem 5 points (free 60g x 3 pouches) or 10 points (free 500g x 1 bag) to be shipped with the customer's next order."""
    database.init_db()
    clean_phone = jst_erp.normalize_thai_phone(phone) if phone else ""

    with SessionLocal() as db:
        member = None
        if clean_phone:
            member = db.get(LoyaltyMember, clean_phone)
        if member is None and line_user_id:
            member = db.execute(
                select(LoyaltyMember).where(
                    LoyaltyMember.line_user_id == line_user_id,
                    LoyaltyMember.brand_id == brand_id,
                )
            ).scalars().first()

        if member is None:
            return {
                "status": "member_not_found",
                "bubbles": [
                    "น้องบุกยังไม่พบข้อมูลเบอร์โทรศัพท์ที่ผูกกับบัตรสะสมแต้มของคุณลูกค้าในระบบเลยค่ะ 🙏💚",
                    "รบกวนคุณลูกค้าพิมพ์แจ้ง เบอร์โทรศัพท์ 10 หลัก (หรือชื่อผู้รับที่ใช้สั่งซื้อ) ให้น้องบุกตรวจสอบแต้มสะสมก่อนแลกของแถมได้เลยนะคะ 😊🍚",
                ],
            }

        pts = member.total_points or 0
        if requested_tier in (5, 10):
            tier_to_use = requested_tier
        else:
            tier_to_use = 10 if pts >= 10 else (5 if pts >= 5 else 0)

        if tier_to_use == 0 or pts < tier_to_use:
            need = (requested_tier or 5) - pts
            return {
                "status": "insufficient_points",
                "phone": member.phone,
                "total_points": pts,
                "bubbles": [
                    f"ตอนนี้{_polite_name(member.customer_name)} มีแต้มสะสมคงเหลือ {pts} แต้มค่ะ (ยังขาดอีก {need} แต้มสำหรับการแลกรางวัลระดับ {requested_tier or 5} แต้มนะคะ) 🍚💚",
                    "• สะสมครบ 5 แต้ม: แลกรับฟรี! ซองเล็ก 60 กรัม จำนวน 3 ซอง (มูลค่า 132.-)\n"
                    "• สะสมครบ 10 แต้ม: แลกรับฟรี! ถุงกลาง 500 กรัม จำนวน 1 ถุง (มูลค่า 249.-)\n"
                    "หากมีคำสั่งซื้อใหม่ แจ้งเบอร์โทรให้น้องบุกเพิ่มแต้มได้เลยนะคะ 😊🙏",
                ],
            }

        reward_info = REWARD_TIERS[tier_to_use]
        member.total_points = pts - tier_to_use
        remaining_pts = member.total_points
        bkk_now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        reward_label = f"{reward_info['short_name']} (แลก {tier_to_use} แต้ม เมื่อ {bkk_now_str})"
        member.pending_reward = (
            f"{member.pending_reward} + {reward_label}".strip(" +") if member.pending_reward else reward_label
        )
        member.redeemed_history = (
            f"{member.redeemed_history}\n{reward_label}".strip() if member.redeemed_history else reward_label
        )
        member.updated_at = utcnow()
        cust_name = member.customer_name or "คุณลูกค้า"
        mem_phone = member.phone
        pending_str = member.pending_reward
        db.commit()

    _sync_loyalty_ledger_snapshot(brand_id=brand_id)

    if line_user_id:
        line_psid = database.make_session_key(brand_id, "line", line_user_id)
        sess = database.get_or_create_session(psid=line_psid, brand_id=brand_id, platform="line", external_user_id=line_user_id)
        new_tags = database._add_tag_str(sess.broadcast_tags or "", f"🎁 แลกของแถม ({reward_info['short_name']})")
        note_line = f"[LOYALTY REWARD: ใช้ {tier_to_use} แต้ม แลก {reward_info['reward_name']} — จัดส่งพร้อมออเดอร์ถัดไป]"
        updated_notes = f"{sess.notes}\n{note_line}".strip() if sess.notes else note_line
        database.update_session_meta(psid=line_psid, broadcast_tags=new_tags, notes=updated_notes)

    bubbles = [
        f"🎉 แลกแต้มสำเร็จเรียบร้อยแล้วค่า{_polite_name(cust_name)} (เบอร์ {mem_phone})! 🎁💚\n\n"
        f"• รางวัลที่แลก: ฟรี! {reward_info['reward_name']}\n"
        f"• แต้มที่ใช้: {tier_to_use} แต้ม\n"
        f"• แต้มสะสมคงเหลือ: {remaining_pts} แต้ม\n"
        f"• เงื่อนไขการรับรางวัล: รับของแถมฟรีไปพร้อมกับการสั่งซื้อครั้งถัดไปค่ะ",
        "น้องบุกบันทึกสิทธิ์ของแถมไว้ในระบบให้เรียบร้อยแล้วนะคะ 🍚✨ คุณลูกค้าสนใจสั่งซื้อโปรโมชั่นไหนในรอบนี้เพื่อรับของแถมส่งไปพร้อมกันเลยดีคะ 😊🙏",
    ]
    return {
        "status": "redeemed",
        "phone": mem_phone,
        "customer_name": cust_name,
        "redeemed_tier": tier_to_use,
        "reward_name": reward_info["reward_name"],
        "remaining_points": remaining_pts,
        "pending_reward": pending_str,
        "bubbles": bubbles,
    }


def is_loyalty_intent(text: str, history: list[dict[str, Any]] | None = None) -> bool:
    """Detect whether a LINE OA message in `@misterbuk` is a loyalty point check, point claim, or reward redemption."""
    clean_t = (text or "").strip()
    if not clean_t or clean_t.startswith("[ลูกค้า"):
        return False
    low = clean_t.lower()

    # Do not hijack active product purchase orders (e.g. "สั่ง 1 กก. ส่งคุณสมหญิง 123 ถ.สุขุมวิท โทร 0812345678 เก็บปลายทาง")
    order_action_markers = (
        "เก็บปลายทาง",
        "ปลายทาง",
        "โอนเงิน",
        "ส่งที่",
        "จัดส่ง",
        "ตำบล",
        "อำเภอ",
        "จังหวัด",
        "แขวง",
        "เขต",
        "ต.",
        "อ.",
        "จ.",
        "สั่งซื้อ",
        "เอา 1",
        "รับ 1",
        "รับเซ็ต",
        "เอาเซ็ต",
    )
    if any(m in low for m in order_action_markers) and not any(k in low for k in LOYALTY_TRIGGER_KEYWORDS):
        return False

    # 1. Explicit loyalty keywords ("สะสมแต้ม", "รับแต้ม", "เช็กแต้ม", "แลกแต้ม", etc.)
    if any(k in low for k in LOYALTY_TRIGGER_KEYWORDS):
        return True

    # 2. Standalone 10-digit phone number sent in LINE OA (e.g. "0812345678" or "081-234-5678" or "เบอร์ 0812345678 ค่ะ")
    phone, name_cand = extract_phone_or_name_from_text(clean_t)
    stripped_non_phone = re.sub(r"[\d\s\-+()เบอร์โทรค่ะคะนะคะค่าครับจ้า:.,]", "", clean_t)
    if phone and len(stripped_non_phone) <= 10:
        return True

    # 3. If the bot's previous message in history asked the customer for their 10-digit phone number or recipient name to check points
    if history:
        recent_bot_msgs = [
            str(m.get("content") or "")
            for m in history[-4:]
            if m.get("role") in ("assistant", "admin", "bot")
        ]
        bot_asked_for_loyalty_id = any(
            ("สะสมแต้ม" in bm or "เช็กแต้ม" in bm or "รับแต้ม" in bm or "QR Code แต้ม" in bm or "บันทึกยอดสะสม" in bm)
            and ("เบอร์โทร" in bm or "ชื่อผู้รับ" in bm or "ชื่อ-นามสกุล" in bm)
            for bm in recent_bot_msgs
        )
        if bot_asked_for_loyalty_id and (phone or (name_cand and len(name_cand) >= 2 and len(clean_t) <= 60)):
            return True

    return False


def handle_line_loyalty_message(
    text: str,
    line_user_id: str,
    history: list[dict[str, Any]] | None = None,
    brand_id: str = "mrbuk",
) -> dict[str, Any] | None:
    """Process a loyalty message on LINE OA `@misterbuk`.

    Returns `None` if not a loyalty message, or a dict with:
      `bubbles`: list[str]
      `media_items`: list[dict] (QR Code images `MrBuk_QR_Give_1pt.png`, `2pt`, `4pt`)
      `status`: str
    """
    if not is_loyalty_intent(text, history=history):
        return None

    clean_t = (text or "").strip()
    low = clean_t.lower()
    phone, name_cand = extract_phone_or_name_from_text(clean_t)

    # Check if customer wants to redeem points ("แลกแต้ม", "แลก 5 แต้ม", "แลก 10 แต้ม")
    if any(k in low for k in REDEEM_TRIGGER_KEYWORDS):
        req_tier = 10 if "10" in low else (5 if "5" in low else None)
        res = redeem_loyalty_points(
            phone=phone,
            line_user_id=line_user_id,
            requested_tier=req_tier,
            brand_id=brand_id,
        )
        return {
            "status": res["status"],
            "bubbles": res["bubbles"],
            "media_items": [],
            "details": res,
        }

    # If customer has provided a 10-digit phone number or recipient name, verify & claim points!
    if phone or name_cand:
        res = claim_points_for_customer(
            phone=phone,
            customer_name=name_cand,
            line_user_id=line_user_id,
            brand_id=brand_id,
        )
        return {
            "status": res["status"],
            "bubbles": res["bubbles"],
            "media_items": res.get("qr_media_items") or [],
            "details": res,
        }

    # Otherwise, customer just typed "สะสมแต้ม" / "รับแต้ม" / "เช็กแต้ม" in LINE OA.
    # Look up their LINE OA orders and member record directly by `line_user_id` (NO phone number required!)
    existing = get_member_summary(line_user_id=line_user_id, brand_id=brand_id)
    direct_res = claim_points_for_customer(
        phone=existing["phone"] if existing else "",
        customer_name=existing["customer_name"] if existing else "",
        line_user_id=line_user_id,
        brand_id=brand_id,
    )
    if direct_res["status"] != "not_found":
        return {
            "status": direct_res["status"],
            "bubbles": direct_res["bubbles"],
            "media_items": direct_res.get("qr_media_items") or [],
            "details": direct_res,
        }

    # Customer has not placed an order in LINE OA yet -> Show LINE OA-only VIP Loyalty Card & 5% Coupon guide
    bubbles = [
        "ยินดีต้อนรับสู่บัตรสะสมแต้มและคูปอง มิสเตอร์บุก VIP (เฉพาะสมาชิกใน LINE OA) ค่า 🍚🎁💚\n\n"
        "📌 กติกาการรับแต้มและคูปองของแถมใน LINE OA:\n"
        "• สมาชิกใน LINE รับสิทธิ์คูปองส่วนลดพิเศษ 5% (รหัส MRBUKVIP5)\n"
        "• สะสมแต้มเฉพาะยอดที่สั่งซื้อผ่านแชท LINE OA นี้เท่านั้นค่ะ (ทุกยอดค่าสินค้าสุทธิ 500 บาท ไม่รวมค่าส่ง = รับ 1 แต้ม)\n"
        "• เศษยอดเงินที่เกิน 500 บาท (เช่น สั่งเซ็ตคู่ 950.- รับทันที 1 แต้ม + เก็บเศษ 450.-) หรือถุง 1 กก. (490.-) ระบบบอทจะบันทึกผูกกับบัญชี LINE ของคุณลูกค้าไว้ทบกับบิลถัดไปให้อัตโนมัติค่ะ\n"
        "• สะสมครบ 5 แต้ม: รับคูปองแลกฟรี! ซองเล็ก 60 กรัม จำนวน 3 ซอง (มูลค่า 132.-)\n"
        "• สะสมครบ 10 แต้ม: รับคูปองแลกฟรี! ถุงกลาง 500 กรัม จำนวน 1 ถุง (มูลค่า 249.-) จัดส่งพร้อมออเดอร์ถัดไปค่ะ",
        f"📲 สามารถกดเปิดดูบัตรสะสมแต้มและคูปองใน LINE ของคุณลูกค้าได้ที่ {REWARD_CARD_URL} "
        f"หรือหากต้องการสั่งซื้อสินค้าใน LINE เพื่อเริ่มสะสมแต้มและใช้สิทธิ์ลด 5% ทักบอกน้องบุกในแชทนี้ได้เลยนะคะ 😊🙏",
    ]
    return {
        "status": "line_only_loyalty_guide",
        "bubbles": bubbles,
        "media_items": [],
        "details": {},
    }


def list_all_loyalty_members(brand_id: str = "mrbuk") -> list[dict[str, Any]]:
    """Return all registered loyalty members and their claimed orders for the Admin Dashboard / API."""
    database.init_db()
    with SessionLocal() as db:
        rows = db.execute(
            select(LoyaltyMember)
            .where(LoyaltyMember.brand_id == brand_id)
            .order_by(LoyaltyMember.updated_at.desc())
        ).scalars().all()
        result = []
        for m in rows:
            claims = db.execute(
                select(LoyaltyClaimedOrder)
                .where(LoyaltyClaimedOrder.phone == m.phone)
                .order_by(LoyaltyClaimedOrder.claimed_at.desc())
            ).scalars().all()
            result.append(
                {
                    "phone": m.phone,
                    "brand_id": m.brand_id,
                    "customer_name": m.customer_name,
                    "line_user_id": m.line_user_id,
                    "fb_psid": m.fb_psid,
                    "total_points": m.total_points or 0,
                    "lifetime_points": m.lifetime_points or 0,
                    "lifetime_spend_thb": m.lifetime_spend_thb or 0,
                    "carryover_thb": m.carryover_thb or 0,
                    "pending_reward": m.pending_reward or "",
                    "redeemed_history": m.redeemed_history or "",
                    "updated_at": m.updated_at.isoformat() if m.updated_at else None,
                    "claimed_orders": [
                        {
                            "order_ref": c.order_ref,
                            "source": c.source,
                            "order_amount_thb": c.order_amount_thb,
                            "points_awarded": c.points_awarded,
                            "qr_images_sent": c.qr_images_sent,
                            "order_date": c.order_date,
                            "claimed_at": c.claimed_at.isoformat() if c.claimed_at else None,
                        }
                        for c in claims
                        if not c.order_ref.startswith("ALIAS:")
                    ],
                }
            )
        return result


def _sync_loyalty_ledger_snapshot(brand_id: str = "mrbuk") -> None:
    """Save a JSON & CSV snapshot of all loyalty members (`total_points`, `carryover_thb`, `pending_reward`)
    into `reports/mrbuk_loyalty_ledger.json` and `.csv` automatically.
    """
    import csv
    import json
    from pathlib import Path

    try:
        members = list_all_loyalty_members(brand_id=brand_id)
        out_dir = Path(__file__).resolve().parent.parent / "reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        json_path = out_dir / f"{brand_id}_loyalty_ledger.json"
        csv_path = out_dir / f"{brand_id}_loyalty_ledger.csv"

        json_path.write_text(json.dumps(members, ensure_ascii=False, indent=2), encoding="utf-8")
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "เบอร์โทรศัพท์",
                    "ชื่อลูกค้า",
                    "แต้มสะสมคงเหลือ",
                    "เศษยอดสะสมยกไป (บาท)",
                    "ยอดค่าสินค้าสะสมรวม (บาท)",
                    "แต้มรวมตลอดชีพ",
                    "รางวัลรอจัดส่งพร้อมออเดอร์ถัดไป",
                    "ประวัติการแลกรางวัล",
                    "อัปเดตล่าสุด",
                ]
            )
            for m in members:
                writer.writerow(
                    [
                        m["phone"],
                        m["customer_name"],
                        m["total_points"],
                        m["carryover_thb"],
                        m["lifetime_spend_thb"],
                        m["lifetime_points"],
                        m["pending_reward"],
                        m["redeemed_history"],
                        m["updated_at"] or "",
                    ]
                )
    except Exception as exc:
        logger.warning("Failed to write loyalty ledger snapshot: %s", exc)
