"""Two-Layer Automated Accuracy & Compliance Audit Engine (ระบบ Audit ตรวจสอบความถูกต้อง 2 ชั้น).

Layer 1 — Pre-Send Chat Audit (`audit_outgoing_reply`):
  Runs automatically BEFORE any AI message or image is sent to a customer on LINE OA / Facebook / IG:
  1. Bank Account Integrity: Blocks any hallucinated bank or account number; enforces official SCB 304-407545-5 (Buk Sukjai) or KBank 989-2-13624-3 (Mr.Buk).
  2. All-Promotions Completeness: When a customer asks about price/promotions/sizes/'สนใจ', guarantees ALL 4 official promo images (`promo_all`) AND all 7 promo price tiers are sent at once.
  3. Synthetic Image Ban: Blocks any banned synthetic table PNGs (`promo_catalog.png`, etc.); only allows authentic brand promo JPGs.
  4. Starred / Paid Customer Protection: Prevents sending new-customer promo tables or resetting state for starred (`⭐`) / completed buyers.
  5. Ad-Safe & Brand Compliance: Strips banned medical/disease/body-shaming terms, asterisks (`*`), and male particles (`ครับ`/`นะครับ`).
  6. VIP 5% Discount Guardrail: Blocks offering the 5% box-insert QR discount to new customers unless they explicitly mention scanning the QR code from a box.
  7. Order Confirmation Gate: Prevents jumping to `completed` before the customer confirms their address or sends a real payment slip.

Layer 2 — Pre-JST ERP Order Audit (`audit_session_for_jst`):
  Runs automatically BEFORE any order is pushed to JST ERP:
  1. Slip vs Promo Image Audit: Verifies that `slip_url` comes strictly from `role == 'user'` and is not a Facebook sticker or admin promo image.
  2. Transfer vs COD Audit: Ensures Transfer orders have a real customer slip, and COD orders have explicit COD confirmation.
  3. Address & Phone Audit: Verifies 10-digit Thai phone number + parsed province/district/subdistrict.
"""

from __future__ import annotations

import logging
import re
from collections import deque
from datetime import datetime, timezone
from typing import Any

from . import database, media_generator
from .llm import (
    FULL_PROMO_SUMMARY_BUBBLE,
    clean_chat_text,
    enforce_all_promotions_when_asked,
    enforce_authentic_bank_account,
)

logger = logging.getLogger(__name__)

# Keep the last 100 audit events in memory for instant inspection in the Admin Dashboard
_AUDIT_HISTORY: deque[dict[str, Any]] = deque(maxlen=100)

BANNED_MEDICAL_OR_BODY_TERMS: dict[str, str] = {
    "ลดความอ้วน": "ดูแลรูปร่าง",
    "ลดน้ำหนัก": "ดูแลรูปร่าง",
    "โรคอ้วน": "การดูแลรูปร่าง",
    "พุงป่อง": "อึดอัดแน่นท้อง",
    "อ้วนลงพุง": "ต้องการดูแลรูปร่าง",
    "ผอมไว": "ตัวเบาสบายท้อง",
    "โยโย่": "หิวจุกจิก",
    "เบาหวาน": "การคุมน้ำตาลและคาร์บ",
    "ความดัน": "การดูแลสุขภาพ",
    "ไขมันพอกตับ": "การดูแลสุขภาพ",
    "คอเลสเตอรอล": "การคุมแคลอรี",
    "ไตรกลีเซอไรด์": "การคุมแคลอรี",
    "กรดไหลย้อน": "ความสบายท้อง",
    "ดีท็อกซ์": "สบายท้อง",
    "เนื้อเยลลี่": "เนื้อนุ่มหนึบเหมือนข้าวสวย",
    "บุกก้อน": "ข้าวบุกเมล็ดเรียวยาว",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_audit_event(
    psid: str,
    layer: str,
    passed: bool,
    checks: list[dict[str, Any]],
    auto_fixes: list[str],
) -> dict[str, Any]:
    event = {
        "timestamp": _now_iso(),
        "psid": psid,
        "layer": layer,
        "passed": passed,
        "auto_fixed": len(auto_fixes) > 0,
        "auto_fixes": auto_fixes,
        "checks": checks,
    }
    _AUDIT_HISTORY.appendleft(event)
    if auto_fixes:
        logger.info("🛡️ [AUDIT AUTO-FIX | %s | %s] %s", layer, psid, " ; ".join(auto_fixes))
    return event


def get_recent_audit_events(limit: int = 50) -> list[dict[str, Any]]:
    return list(_AUDIT_HISTORY)[:limit]


def audit_outgoing_reply(
    psid: str,
    brand_id: str,
    user_session: Any,
    history: list[dict[str, Any]],
    raw_reply: str,
    proposed_state: str,
    proposed_image_key: str,
    config: dict[str, Any] | None = None,
) -> tuple[list[str], str, list[dict[str, Any]], dict[str, Any]]:
    """Run Layer-1 Pre-Send Audit on AI output.

    Returns:
      (audited_bubbles, audited_state, audited_media_items, audit_report)
    """
    from .llm import split_into_bubbles

    checks: list[dict[str, Any]] = []
    auto_fixes: list[str] = []

    user_text = (history[-1].get("content") or "").strip() if history else ""
    u_low = user_text.lower()

    is_paid_or_starred = (
        bool(getattr(user_session, "is_starred", False))
        or (getattr(user_session, "state", "") == "completed")
        or ("ชำระเงินแล้ว" in (getattr(user_session, "broadcast_tags", "") or ""))
        or ("ติดดาว" in (getattr(user_session, "broadcast_tags", "") or ""))
    )
    wants_to_reorder = any(
        w in u_low for w in ("สั่งเพิ่ม", "ซื้อเพิ่ม", "สั่งอีก", "เอาอีก", "โปรลูกค้าเก่า", "สั่งซื้อเพิ่ม")
    )

    # 1. Split & Clean Polite Particles + Markdown
    bubbles = split_into_bubbles(raw_reply)
    if ("ครับ" in raw_reply) or ("*" in raw_reply):
        auto_fixes.append("ปรับคำลงท้ายเป็นผู้หญิง (ค่ะ/คะ) และลบเครื่องหมายดอกจัน (*)")
    checks.append({
        "name": "ตรวจคำลงท้ายผู้หญิง (ค่ะ/คะ) & ลบดอกจัน (*)",
        "status": "ok",
    })

    # 2. Ad-Safe & Medical/Body Claim Filter
    sanitized_bubbles: list[str] = []
    medical_fixed = False
    for b in bubbles:
        clean_b = b
        for bad_word, safe_word in BANNED_MEDICAL_OR_BODY_TERMS.items():
            if bad_word in clean_b:
                clean_b = clean_b.replace(bad_word, safe_word)
                medical_fixed = True
        sanitized_bubbles.append(clean_chat_text(clean_b))
    bubbles = sanitized_bubbles
    if medical_fixed:
        auto_fixes.append("กรองคำต้องห้ามด้านสุขภาพ/รูปร่างให้เป็นคำที่ปลอดภัยตามกฎแบรนด์")
    checks.append({
        "name": "ตรวจกฎเหล็ก Ad-Safe (ห้ามเคลมโรค/ทักปมรูปร่าง)",
        "status": "fixed" if medical_fixed else "ok",
    })

    # 3. Bank Account Integrity Audit
    cfg_with_brand = dict(config or {})
    cfg_with_brand["brand_id"] = brand_id
    before_bank = list(bubbles)
    bubbles = enforce_authentic_bank_account(bubbles, history, cfg_with_brand)
    if bubbles != before_bank:
        auto_fixes.append("บังคับใช้เลขบัญชีจริงของบริษัท (SCB 304-407545-5) พร้อมบล็อกเลขบัญชีสมมติ")
    checks.append({
        "name": "ตรวจความถูกต้องเลขบัญชีธนาคารจริง (SCB 304-407545-5)",
        "status": "fixed" if bubbles != before_bank else "ok",
    })

    # 4. VIP 5% Box-Insert Discount Guardrail
    mentioned_qr = any(w in u_low for w in ("qr", "คิวอาร์", "ใบแนบ", "ในกล่อง", "ลูกค้าเก่า", "ลด 5%"))
    if not mentioned_qr and not is_paid_or_starred:
        filtered_vip: list[str] = []
        vip_removed = False
        for b in bubbles:
            if any(v in b for v in ("436", "854", "684", "1,234", "ลด 5%")):
                vip_removed = True
                continue
            filtered_vip.append(b)
        if vip_removed:
            bubbles = filtered_vip or [FULL_PROMO_SUMMARY_BUBBLE]
            auto_fixes.append("บล็อกการเสนอโปรลด 5% (ใบแนบในกล่อง) ให้ลูกค้าใหม่ที่ไม่ได้สแกน QR")
    checks.append({
        "name": "ตรวจกติกาโปรลับ 5% (ห้ามเสนอให้ลูกค้าใหม่ทั่วไป)",
        "status": "ok",
    })

    # 5. All-Promotions Completeness Audit (ส่งทีเดียวครบทุกโปร + ครบ 4 รูป)
    audited_image_key = proposed_image_key or "none"
    if is_paid_or_starred and not wants_to_reorder:
        audited_image_key = "none"
        audited_state = "completed"
        checks.append({
            "name": "ตรวจสถานะลูกค้าติดดาว ⭐ (ซื้อแล้วห้ามส่งตารางโปรซ้ำ)",
            "status": "ok",
        })
    else:
        before_promo_bubbles = list(bubbles)
        before_img = audited_image_key
        bubbles, audited_image_key = enforce_all_promotions_when_asked(bubbles, history, audited_image_key)
        if bubbles != before_promo_bubbles or audited_image_key != before_img:
            auto_fixes.append("ปรับให้ส่งครบทุกโปรโมชั่น (7 รายการ) และส่งรูปโปรครบทั้ง 4 รูปในครั้งเดียว")
        checks.append({
            "name": "ตรวจการส่งโปรโมชั่นครบทุกชุด & รูปครบ 4 ภาพในครั้งเดียว",
            "status": "fixed" if (bubbles != before_promo_bubbles or audited_image_key != before_img) else "ok",
        })
        audited_state = proposed_state

    # 5.5 No-Assumed-COD Guardrail & Complaint/Tracking Shield
    all_user_text = "\n".join(str(m.get("content") or "") for m in history if m.get("role") == "user").lower()
    user_ever_said_cod = any(w in all_user_text for w in ("ปลายทาง", "cod", "เก็บเงินปลายทาง"))
    user_ever_said_transfer = any(w in all_user_text for w in ("โอน", "สลิป", "เลขบัญชี", "บช"))
    reply_joined = "\n".join(bubbles)
    if (
        not user_ever_said_cod
        and not user_ever_said_transfer
        and any(k in reply_joined for k in ("ยอดชำระปลายทาง", "ชำระเงิน : ปลายทาง", "ค่าส่งเก็บปลายทาง ="))
    ):
        bubbles = [
            "น้องบุกบันทึกชื่อ-ที่อยู่และเบอร์โทรจัดส่งไว้ให้เรียบร้อยแล้วค่ะ 📝\n\n"
            "คุณลูกค้าสะดวกชำระแบบ โอนเงิน (บัญชีไทยพาณิชย์ SCB 304-407545-5 ชื่อบัญชี บริษัท ดิจิสท์ ฮับ จำกัด) "
            "หรือรับเป็น เก็บเงินปลายทาง (COD) ดีคะ แจ้งน้องบุกได้เลยนะคะ 😊🙏",
            "3044075455",
        ]
        audited_state = "pending_payment"
        audited_image_key = "none"
        auto_fixes.append("ป้องกันการสรุปเป็น COD ไปเองโดยที่ลูกค้ายังไม่เลือกวิธีชำระเงิน (ถามลูกค้าพร้อมแนบเลขบัญชีเผื่อลูกค้าโอนตามมา)")

    is_tracking_complaint = any(
        w in u_low for w in ("ยังไม่ได้รับของ", "โอนเงินไปแล้วตั้งแต่", "ช่วยเช็คการส่ง", "เช็คการส่ง", "ตามของ", "ส่งของหรือยัง")
    )
    if is_tracking_complaint:
        audited_image_key = "none"
        audited_state = "pending_payment"
        auto_fixes.append("ตรวจพบข้อความติดตามพัสดุ/ทวงของ — บล็อกการส่งโปรโมชั่นและไม่สรุปเป็นออเดอร์ใหม่")

    # 6. Order Confirmation Gate Audit (ห้ามข้ามเป็น completed ถ้าลูกค้ายังไม่ยืนยันหรือยังไม่มีสลิป)
    if not is_paid_or_starred and audited_state == "completed":
        has_user_slip = any(
            m.get("role") == "user"
            and str(m.get("content", "")).startswith("[IMAGE:")
            and "39178562_1505197616293642" not in str(m.get("content", ""))
            for m in history
        )
        explicitly_confirmed = any(
            w in u_low
            for w in ("ยืนยัน", "คอนเฟิร์ม", "confirm", "ถูกต้อง", "ตามนี้", "ตกลงค่ะ", "โอเคค่ะ", "โอนแล้ว", "ส่งสลิป", "แนบสลิป")
        )
        if not has_user_slip and not explicitly_confirmed:
            audited_state = "pending_payment"
            auto_fixes.append("ชะลอสถานะไว้ที่ 'รอโอน/ทวนที่อยู่ (pending_payment)' เพื่อรอให้ลูกค้าคอนเฟิร์มก่อนส่งเข้า JST")
            checks.append({
                "name": "ตรวจการคอนเฟิร์มที่อยู่/สลิปก่อนปิดการขาย (Confirmation Gate)",
                "status": "fixed",
            })
        else:
            checks.append({
                "name": "ตรวจการคอนเฟิร์มที่อยู่/สลิปก่อนปิดการขาย (Confirmation Gate)",
                "status": "ok",
            })

    # 7. Official Media Resolution Audit (ห้ามใช้รูปตารางที่สร้างเองเด็ดขาด)
    selected_media_items: list[dict[str, Any]] = []
    if audited_image_key and audited_image_key != "none":
        candidates = media_generator.resolve_media_items(audited_image_key)
        recent_assistant_msgs = [
            m.get("content", "") for m in history[-10:] if m.get("role") == "assistant"
        ]
        explicitly_asked_pic = any(
            w in u_low for w in ("รูป", "ภาพ", "โปร", "ราคา", "สนใจ", "กี่บาท", "เท่าไหร่", "ขนาด", "ไซส์")
        )
        for item in candidates:
            fname = item.get("filename", "")
            if fname in media_generator.BANNED_GENERATED_FILES:
                auto_fixes.append(f"บล็อกรูปภาพที่สร้างเอง ({fname})")
                continue
            marker = f"[IMAGE:{item['relative_url']}]"
            if explicitly_asked_pic or marker not in recent_assistant_msgs:
                selected_media_items.append(item)

    checks.append({
        "name": f"ตรวจรูปภาพโปรโมชั่นจริงจากแบรนด์ ({len(selected_media_items)} รูป)",
        "status": "ok",
    })

    report = record_audit_event(
        psid=psid,
        layer="pre_send_chat",
        passed=True,
        checks=checks,
        auto_fixes=auto_fixes,
    )
    return bubbles, audited_state, selected_media_items, report


def audit_session_for_jst(psid: str) -> dict[str, Any]:
    """Run Layer-2 Pre-JST Order Audit on a customer session before pushing to JST ERP."""
    from . import jst_erp

    user = database.get_or_create_session(psid)
    extracted = jst_erp.extract_order_from_session(psid)
    checks: list[dict[str, Any]] = []
    issues: list[str] = []

    # 0. Dialogue Completion Audit ("ตรวจว่าลูกค้าตอบประโยคคำถามของเราจนครบแล้วจริง ๆ")
    dialogue_ok = bool(extracted.get("dialogue_complete"))
    dialogue_reason = extracted.get("dialogue_reason") or "ยังสนทนาไม่จบขั้นตอนค่ะ"
    checks.append({
        "name": "ตรวจว่าลูกค้าตอบประโยคคำถามของร้านจนครบแล้วจริง ๆ (Dialogue Completion)",
        "value": dialogue_reason,
        "status": "ok" if dialogue_ok else "fail",
    })
    if not dialogue_ok:
        issues.append(dialogue_reason)

    # 1. Exact SKU & Quantity Match Audit
    sku_id = extracted.get("sku_id", "")
    qty = int(extracted.get("qty") or 1)
    total_amt = float(extracted.get("total_amount") or 0)
    sku_matches_chat = bool(extracted.get("sku_matches_chat", True))
    sku_mismatch_reason = extracted.get("sku_mismatch_reason") or ""
    sku_ok = bool(sku_id and total_amt >= 39 and sku_matches_chat)
    checks.append({
        "name": "ตรวจสอบรหัสสินค้า (SKU), จำนวนถุง และยอดเงินให้ตรงกับที่ลูกค้าสั่งจริง",
        "value": (
            f"{sku_id} x {qty} ({extracted.get('item_name', '')}) = {total_amt:.0f} บาท ({extracted.get('payment_label', '')})"
            if sku_ok
            else (sku_mismatch_reason or "ยังไม่พบสรุปยอดสินค้าและราคาที่ยืนยันแล้วในรอบปัจจุบันค่ะ")
        ),
        "status": "ok" if sku_ok else "fail",
    })
    if not sku_ok:
        issues.append(sku_mismatch_reason or "รหัสสินค้า/จำนวน หรือยอดเงินในรอบปัจจุบันยังไม่ชัดเจนค่ะ")

    # 2. Phone check
    phone = extracted.get("phone", "")
    phone_ok = bool(re.fullmatch(r"0[689]\d{8}", phone))
    checks.append({
        "name": "เบอร์โทรศัพท์มือถือ 10 หลัก",
        "value": phone or "ไม่พบเบอร์โทร",
        "status": "ok" if phone_ok else "fail",
    })
    if not phone_ok:
        issues.append("ยังไม่มีเบอร์โทรศัพท์มือถือ 10 หลักที่ถูกต้อง")

    # 3. Address & Recipient Name check
    addr = extracted.get("parsed_address") or {}
    rec_name = (addr.get("receiver_name") or "").strip()
    addr_ok = bool(rec_name and addr.get("state") and addr.get("city") and addr.get("district"))
    checks.append({
        "name": "ชื่อผู้รับ & ที่อยู่จัดส่ง (ตำบล / อำเภอ / จังหวัด / รหัสไปรษณีย์)",
        "value": (
            f"ผู้รับ: {rec_name or 'ไม่ระบุ'} | ต.{addr.get('district', '-')} อ.{addr.get('city', '-')} จ.{addr.get('state', '-')} {addr.get('post_code', '')}".strip()
            if addr
            else "ไม่สมบูรณ์"
        ),
        "status": "ok" if addr_ok else "fail",
    })
    if not addr_ok:
        issues.append("ชื่อผู้รับหรือที่อยู่ยังไม่ครบถ้วน (ต้องมี ชื่อผู้รับ, ตำบล/แขวง, อำเภอ/เขต และจังหวัด)")

    # 4. Payment Method & Slip Integrity Check
    is_cod = bool(extracted.get("is_cod"))
    slip_url = extracted.get("slip_url") or ""
    has_slip = bool(extracted.get("has_slip") and slip_url)
    has_admin_buy_tag = bool(extracted.get("has_admin_buy_summary"))
    cod_confirmed = bool(extracted.get("customer_confirmed_cod"))

    if not is_cod:
        slip_is_authentic = (
            has_slip
            and "/static/media/promo_" not in slip_url
            and "39178562_1505197616293642" not in slip_url
        ) or has_admin_buy_tag
        checks.append({
            "name": "ตรวจสอบสลิปโอนเงินจริงของลูกค้า (ห้ามใช้รูปโปรโมชั่นแทนสลิป)",
            "value": (
                "พบสลิปจริงจากฝั่งลูกค้า"
                if (has_slip and "/static/media/promo_" not in slip_url)
                else ("แอดมินตรวจรับสลิปและปิดแท็ก #BUY แล้ว" if has_admin_buy_tag else "ไม่พบสลิปโอนเงิน")
            ),
            "status": "ok" if slip_is_authentic else "fail",
        })
        if not slip_is_authentic:
            issues.append("ออเดอร์โอนเงินต้องมีรูปสลิปโอนเงินจริงจากลูกค้าเท่านั้น")
    else:
        checks.append({
            "name": "ตรวจสอบการคอนเฟิร์มเก็บเงินปลายทาง (COD) กับลูกค้า",
            "value": "ลูกค้ายืนยัน COD ชัดเจนแล้ว" if cod_confirmed else "ลูกค้าระบุ COD แต่ยังไม่ครบเงื่อนไขยืนยัน",
            "status": "ok" if cod_confirmed else "fail",
        })
        if not cod_confirmed:
            issues.append("ออเดอร์ COD ต้องได้รับการคอนเฟิร์มยอดปลายทางจากลูกค้าก่อนส่งเข้าคลัง")

    # 5. Star Status Check
    is_starred = bool(getattr(user, "is_starred", False) or user.state == "completed")
    checks.append({
        "name": "สถานะติดดาว ⭐ (ลูกค้าซื้อจริง)",
        "value": "★ ติดดาวแล้ว" if is_starred else "☆ ยังไม่ติดดาว",
        "status": "ok" if is_starred else "warn",
    })

    passed = len(issues) == 0 and bool(extracted.get("valid"))
    record_audit_event(
        psid=psid,
        layer="pre_jst_order",
        passed=passed,
        checks=checks,
        auto_fixes=[],
    )
    return {
        "psid": psid,
        "customer_name": user.customer_name,
        "passed": passed,
        "ready_for_jst": passed,
        "issues": issues,
        "checks": checks,
        "extracted": extracted,
    }


def audit_jst_orders_against_chat(days_lookback: int = 1, auto_clean: bool = False) -> dict[str, Any]:
    """Run Post-Keying Audit (Audit ชั้นที่ 2 สำหรับออเดอร์):
    Pulls active manual orders from JST ERP (`NewQueryOrders`) and cross-checks them against:
      1. Duplicate Active Orders per Customer Phone / Name
      2. Actual Facebook Chat Confirmation & Dialogue Completion
      3. Exact SKU, Quantity & Total Pay Amount Match between Chat and JST ERP
      4. Complete Address (Province / District) & Slip Audit Status
    """
    from datetime import timedelta
    import httpx
    from . import jst_erp

    bkk_tz = timezone(timedelta(hours=7))
    now_bkk = datetime.now(bkk_tz)
    start_str = (now_bkk - timedelta(days=max(0, days_lookback))).strftime("%Y-%m-%d 00:00:00")
    end_str = now_bkk.strftime("%Y-%m-%d 23:59:59")

    payload = {
        "RequestModel": {
            "SendFrom": "NewQueryOrders",
            "OrderTimeStart": start_str,
            "OrderTimeEnd": end_str,
        },
        "DataPage": {"pageSize": 100, "pageIndex": 1, "total": 0, "sizes": [50, 100, 200, 500]},
    }
    resp = httpx.post(
        "https://asia.jsterp.com/OMS/MiniShopOrder/NewQueryOrders",
        headers=jst_erp._headers(json_body=True),
        json=payload,
        timeout=20.0,
    )
    resp.raise_for_status()
    rows_obj = (resp.json() or {}).get("Rows") or {}
    cols = rows_obj.get("cols") or []
    raw_rows = rows_obj.get("rows") or []

    active_manual_orders: list[dict[str, Any]] = []
    for row in raw_rows:
        d = dict(zip(cols, row))
        st = str(d.get("StatusDisplay") or d.get("SocialStatusDisplay") or "")
        if "ยกเลิก" in st or "Cancel" in str(d.get("Status") or ""):
            continue
        if str(d.get("SaveType") or "") != "ManualOrder" and str(d.get("CreatorName") or "") != "buksukjai":
            continue
        skus_raw = d.get("MergeSkus") or d.get("Skus") or []
        sku_code = ""
        sku_qty = 1
        if isinstance(skus_raw, list) and skus_raw and isinstance(skus_raw[0], list) and len(skus_raw[0]) >= 9:
            sku_code = str(skus_raw[0][1] or "")
            sku_qty = int(skus_raw[0][8] or 1)
        active_manual_orders.append({
            "order_id": str(d.get("OrderId") or ""),
            "order_time": str(d.get("OrderTime") or ""),
            "status": st,
            "receiver_name": str(d.get("ReceiverName") or "").strip(),
            "phone": jst_erp.normalize_thai_phone(str(d.get("ReceiverMobileEn") or d.get("ReceiverMobile") or "")),
            "province": str(d.get("ReceiverProvince") or "").strip(),
            "city": str(d.get("ReceiverCity") or "").strip(),
            "address": str(d.get("ReceiverAddress") or "").strip(),
            "sku_id": sku_code,
            "qty": sku_qty,
            "pay_amount": float(d.get("PayAmount") or 0.0),
            "is_cod": bool(d.get("IsCod")),
            "seller_remark": str(d.get("SellerRemark") or "").strip(),
            "tracking_no": str(d.get("LogisticsTrackingNumber") or "").strip(),
            "machine_audit": str(d.get("MachineAuditMessage") or "").strip(),
        })

    # Group by phone / receiver_name to detect duplicate active orders
    by_phone: dict[str, list[dict[str, Any]]] = {}
    for o in active_manual_orders:
        key = o["phone"] or o["receiver_name"]
        if key:
            by_phone.setdefault(key, []).append(o)

    duplicates: list[dict[str, Any]] = []
    for key, orders_list in by_phone.items():
        if len(orders_list) > 1:
            duplicates.append({
                "customer_key": key,
                "count": len(orders_list),
                "order_ids": [x["order_id"] for x in orders_list],
                "orders": orders_list,
            })

    # Cross-check against local sessions
    sessions = database.list_all_sessions(brand_id="buksukjai", platform="facebook")
    mismatches: list[dict[str, Any]] = []
    verified_orders: list[dict[str, Any]] = []
    auto_cancelled_ids: list[str] = []

    for o in active_manual_orders:
        order_issues: list[str] = []
        unconfirmed_in_chat = False
        if not o["province"] or not o["city"]:
            order_issues.append("ที่อยู่ใน JST ขาดข้อมูลจังหวัดหรือเขต/อำเภอ")
        if "ใบสั่งซื้อถูกใช้ไปแล้ว" in o["machine_audit"]:
            order_issues.append(f"แจ้งเตือนสลิปซ้ำใน JST: {o['machine_audit']}")

        # Match session by FB remark or customer name
        matched_psid = ""
        for s in sessions:
            cname = (s.get("customer_name") or "").strip()
            if cname and (cname in o["seller_remark"] or cname == o["receiver_name"]):
                matched_psid = s["psid"]
                break

        if matched_psid:
            chat_audit = audit_session_for_jst(matched_psid)
            ext = chat_audit["extracted"]
            if not ext.get("dialogue_complete"):
                unconfirmed_in_chat = True
                order_issues.append(f"ในแชทลูกค้ายังยืนยันไม่ครบ: {ext.get('dialogue_reason')}")
            chat_amt = float(ext.get("total_amount") or 0.0)
            if chat_amt > 0 and abs(chat_amt - o["pay_amount"]) > 1.0:
                order_issues.append(f"ยอดเงินใน JST ({o['pay_amount']:.0f}฿) ไม่ตรงกับยอดในแชท ({chat_amt:.0f}฿)")
            chat_sku = str(ext.get("sku_id") or "")
            if chat_sku and o["sku_id"] and chat_sku != o["sku_id"]:
                order_issues.append(f"รหัสสินค้าใน JST ({o['sku_id']}) ไม่ตรงกับในแชท ({chat_sku})")

        if auto_clean and unconfirmed_in_chat and not o["tracking_no"] and "จัดส่งแล้ว" not in o["status"]:
            try:
                jst_erp.cancel_orders_in_jst([o["order_id"]], "Audit ชั้นที่ 2 ยกเลิกอัตโนมัติ: ลูกค้ายังยืนยันไม่ครบในแชทค่ะ")
                auto_cancelled_ids.append(o["order_id"])
            except Exception as exc:
                logger.warning("Auto-cancel unconfirmed order %s failed: %s", o["order_id"], exc)

        if order_issues:
            mismatches.append({**o, "issues": order_issues})
        else:
            verified_orders.append(o)

    if auto_clean and duplicates:
        for grp in duplicates:
            orders_list = grp["orders"]
            # If one order is manual/admin (empty remark or has tracking) and another is an unshipped FB bot duplicate, cancel the bot duplicate
            has_primary = any((not x["seller_remark"].startswith("FB:")) or bool(x["tracking_no"]) for x in orders_list)
            if has_primary:
                for x in orders_list:
                    if x["seller_remark"].startswith("FB:") and not x["tracking_no"] and "จัดส่งแล้ว" not in x["status"]:
                        if x["order_id"] not in auto_cancelled_ids:
                            try:
                                jst_erp.cancel_orders_in_jst([x["order_id"]], "Audit ชั้นที่ 2 ยกเลิกอัตโนมัติ: ออเดอร์ซ้ำกับใบหลักของแอดมินค่ะ")
                                auto_cancelled_ids.append(x["order_id"])
                            except Exception as exc:
                                logger.warning("Auto-cancel duplicate order %s failed: %s", x["order_id"], exc)

    return {
        "passed": len(duplicates) == 0 and len(mismatches) == 0,
        "window": f"{start_str} -> {end_str}",
        "total_active_manual_orders": len(active_manual_orders),
        "duplicate_groups_count": len(duplicates),
        "duplicates": duplicates,
        "mismatch_orders_count": len(mismatches),
        "mismatches": mismatches,
        "verified_orders_count": len(verified_orders),
        "verified_orders": verified_orders,
        "auto_cancelled_order_ids": auto_cancelled_ids,
    }
