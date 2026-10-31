"""AI Process 1 — Daily Sales & Warehouse Stock Reconciliation Report (สรุปยอดขายรายวันเวลา 01:00 น.).

Generates the daily sales & SKU unit breakdown for the previous day (or any target date YYYY-MM-DD)
from JST ERP (`NewQueryOrders`), separating:
- Product quantities by physical size (`1 กิโลกรัม`, `500 กรัม`, `60 กรัม`) for warehouse stock reconciliation
- Payment totals into separate cells (`โอน` vs `COD` vs `รวมทั้งสิ้น`)
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from . import jst_erp

logger = logging.getLogger(__name__)

_LATEST_JST_COOKIE = (
    "client_id=8c55bf3e7cb90f3ba27a22ddfdcc3762_91cdae39f749baaed0f1c166d97c4583; "
    "u_login_id=buksukjai%40gmail.com; VID_bcbff8986118=22755436; VP_bcbff8986118=1; "
    "AVID_147792=22755436; _ati=3616590229392; Notice-22755436-176=True; LanguageId=TH; "
    "Notice-22755436-177=True; u_cid=ffab80a5bac245c79a723ced80a396a2-22755436-49ce2350e1bfc8869835b061ea8b901d; "
    "u_id=22755436; u_name=buksukjai; u_co_id=15749167; u_co_name=Buksukjai; ClientTimeZone=7; "
    ".AspNetCore.GlobalAuthCookie=CfDJ8NUvc5HFTn9EnG_IMr2hg1SHradvjDPVgyUrg9Ex_iD1PHJg9502Q5QjCgRXYpZOnAYsZw7p7V7bU7l1Xyogh-o0XA35sjy4W1Jo_gW3IaxJlFcwJeGig0S8IC60NqfB1Pit2_L7-DV-3G-usY0bEW8eBvdi166HTeMg2o2AmEknpwu9Czp-iBq2duFcNRJWlrKdbPYG2x-z2U4KLbxg-dZy7teE26pZZzIFbcDUbcLjZkDmRVXZ_HCQ9wDb2MthYpWqpyryy6UmU1s99EF0E2A492-ZcV5uYEwiZd9pQs24hJDerLu_ttYz__Wp3JcUjwteQ3RfZ67ioPl8vJ2q10787nDdcnOboKNkoElrOx_3w4kJy851X5Pu8YX6rN7GkFtj270lMwnWO7r6j1AsrS1cdSfB4GDQjHhXqED5vNo30nQQHdwS85hiSl5wJEKTxXlPy6SMaFQDp7ULIauZ0pSZ5ueNz9fTk8XViLaQftV_; "
    "VT_bcbff8986118=14; SID_bcbff8986118=5596075514064757280"
)
if not jst_erp.get_jst_cookie() or "8925a23804b941b49f52f1c79c1c3b93" in jst_erp.get_jst_cookie():
    jst_erp.set_jst_cookie(_LATEST_JST_COOKIE)

BKK_TZ = timezone(timedelta(hours=7))
DAILY_REPORT_HOUR_BKK = 1  # 01:00 AM Bangkok time (สรุปยอดของเมื่อวานทั้งหมด)
REPORT_STATE_FILE = Path(__file__).resolve().parent.parent / "daily_report_state.json"


def parse_sku_physical_counts(skus_list: list[Any]) -> tuple[str, int, int, int, int]:
    """Return `(sku_code_str, total_pieces, count_1kg, count_500g, count_60g)`."""
    c1kg, c500g, c60g = 0, 0, 0
    sku_codes: list[str] = []
    total_qty = 0
    for s in skus_list or []:
        code = str(s[1] if len(s) > 1 else "").strip()
        qty = int(s[8] if (len(s) > 8 and s[8]) else 1)
        if not code:
            continue
        if code not in sku_codes:
            sku_codes.append(code)
        if code == "BSJ1KG1":
            c1kg += 1 * qty
            total_qty += 1 * qty
        elif code == "BSJ1KG2":
            c1kg += 2 * qty
            total_qty += 2 * qty
        elif code == "BSJ1KG3":
            c1kg += 3 * qty
            total_qty += 3 * qty
        elif code == "BSJ1KG2_60G2":
            c1kg += 2 * qty
            c60g += 2 * qty
            total_qty += 4 * qty
        elif code == "BSJ1KG3_60G3":
            c1kg += 3 * qty
            c60g += 3 * qty
            total_qty += 6 * qty
        elif code == "BSJ500G1":
            c500g += 1 * qty
            total_qty += 1 * qty
        elif code.startswith("BSJ60G"):
            m = re.search(r"BSJ60G(\d+)", code)
            n = int(m.group(1)) if m else 1
            c60g += n * qty
            total_qty += n * qty
        else:
            total_qty += qty
    return ", ".join(sku_codes), total_qty, c1kg, c500g, c60g


def build_daily_sales_sheet_rows(target_date: str) -> dict[str, Any]:
    """Fetch all non-cancelled orders for `target_date` (`YYYY-MM-DD`) and build table rows + summary cells."""
    resp = httpx.post(
        "https://asia.jsterp.com/OMS/MiniShopOrder/NewQueryOrders",
        headers=jst_erp._headers(True),
        json={
            "RequestModel": {"SendFrom": "NewQueryOrders"},
            "DataPage": {"pageSize": 200, "pageIndex": 1, "total": 0, "sizes": [50, 100, 200]},
        },
        timeout=20.0,
    )
    resp.raise_for_status()
    rows_obj = resp.json().get("Rows") or {}
    cols = rows_obj.get("cols") or []
    raw_rows = [dict(zip(cols, r)) for r in (rows_obj.get("rows") or [])]

    day_orders = [
        x
        for x in raw_rows
        if str(x.get("OrderTime") or "").startswith(target_date)
        and "ยกเลิก" not in str(x.get("StatusDisplay") or "")
        and "Cancel" not in str(x.get("Status") or "")
    ]
    day_orders.sort(key=lambda x: str(x.get("OrderTime") or ""))

    header = [
        "ลำดับ",
        "วันที่สั่งซื้อ",
        "ช่องทาง",
        "ชื่อลูกค้า",
        "ที่อยู่จัดส่ง",
        "เบอร์โทรศัพท์",
        "รหัส SKU",
        "จำนวนสินค้า",
        "จำนวนเงิน (บาท)",
        "รูปแบบการชำระเงิน",
        "เลขออเดอร์ JST / เลขพัสดุ",
    ]
    table_rows: list[list[Any]] = [header]

    tot_transfer = 0.0
    tot_cod = 0.0
    tot_facebook = 0.0
    tot_tiktok = 0.0
    tot_shopee = 0.0
    tot_1kg = 0
    tot_500g = 0
    tot_60g = 0
    order_items_out: list[dict[str, Any]] = []

    for idx, o in enumerate(day_orders, 1):
        sku_str, pieces, k1, g500, g60 = parse_sku_physical_counts(o.get("Skus") or [])
        tot_1kg += k1
        tot_500g += g500
        tot_60g += g60

        amt = round(float(o.get("PayAmount") or 0.0), 2)
        is_cod = bool(o.get("IsCod"))
        if is_cod:
            tot_cod += amt
        else:
            tot_transfer += amt

        save_type = str(o.get("SaveType") or "")
        plat_id = str(o.get("PlatformId") or "")
        channel = "Facebook" if save_type == "ManualOrder" else (plat_id or "TikTok")
        if channel.lower() == "facebook":
            tot_facebook += amt
        elif channel.lower() == "shopee":
            tot_shopee += amt
        else:
            tot_tiktok += amt

        first_en = str(o.get("ReceiverFirstNameEn") or "").strip()
        last_en = str(o.get("ReceiverLastNameEn") or "").strip()
        cust_name = f"{first_en} {last_en}".strip() or str(o.get("ReceiverName") or "").strip()

        phone = str(o.get("ReceiverMobileEn") or o.get("ReceiverPhoneEn") or "").strip()
        addr = re.sub(r"\s+", " ", str(o.get("ReceiverAddress") or o.get("Address") or "").strip())

        pay_label = "COD" if is_cod else "โอน"
        order_id = str(o.get("OrderId") or "")
        tracking = str(o.get("LogisticsTrackingNumber") or "").strip()
        status_disp = str(o.get("StatusDisplay") or "").strip()
        jst_col = f"#{order_id} ({status_disp} {tracking})".strip()

        phone_cell = f"'{phone}" if phone.startswith("0") else phone

        row = [
            idx,
            target_date,
            channel,
            cust_name,
            addr,
            phone_cell,
            sku_str,
            pieces,
            amt,
            pay_label,
            jst_col,
        ]
        table_rows.append(row)
        order_items_out.append(
            {
                "seq": idx,
                "date": target_date,
                "channel": channel,
                "customer_name": cust_name,
                "address": addr,
                "phone": phone,
                "sku": sku_str,
                "qty_pieces": pieces,
                "qty_1kg": k1,
                "qty_500g": g500,
                "qty_60g": g60,
                "amount": amt,
                "payment_method": pay_label,
                "order_id": order_id,
                "tracking": tracking,
                "status": status_disp,
            }
        )

    tot_pieces = tot_1kg + tot_500g + tot_60g
    grand_total = round(tot_transfer + tot_cod, 2)

    # Blank separator row
    table_rows.append(["", "", "", "", "", "", "", "", "", "", ""])

    # Warehouse Stock Summary by size (Label in Col G, Quantity in Col H under จำนวนสินค้า)
    table_rows.append(["", "", "", "", "", "", "1 กิโลกรัม", tot_1kg, "", "", ""])
    table_rows.append(["", "", "", "", "", "", "500 กรัม", tot_500g, "", "", ""])
    table_rows.append(["", "", "", "", "", "", "60 กรัม", tot_60g, "", "", ""])
    table_rows.append(["", "", "", "", "", "", "รวมจำนวนสินค้าทั้งหมด", tot_pieces, "", "", ""])

    # Blank separator row
    table_rows.append(["", "", "", "", "", "", "", "", "", "", ""])

    # Channel Sales Summary in separate cells (Label in Col H, Amount in Col I under จำนวนเงิน)
    table_rows.append(["", "", "", "", "", "", "", "Facebook", round(tot_facebook, 2), "", ""])
    table_rows.append(["", "", "", "", "", "", "", "TikTok", round(tot_tiktok, 2), "", ""])
    if tot_shopee > 0:
        table_rows.append(["", "", "", "", "", "", "", "Shopee", round(tot_shopee, 2), "", ""])

    # Blank separator row
    table_rows.append(["", "", "", "", "", "", "", "", "", "", ""])

    # Payment Summary in separate cells (Label in Col H, Amount in Col I under จำนวนเงิน)
    table_rows.append(["", "", "", "", "", "", "", "โอน", round(tot_transfer, 2), "", ""])
    table_rows.append(["", "", "", "", "", "", "", "COD", round(tot_cod, 2), "", ""])
    table_rows.append(["", "", "", "", "", "", "", "รวมทั้งสิ้น", grand_total, "", ""])

    return {
        "target_date": target_date,
        "order_count": len(order_items_out),
        "tot_1kg": tot_1kg,
        "tot_500g": tot_500g,
        "tot_60g": tot_60g,
        "tot_pieces": tot_pieces,
        "tot_facebook": round(tot_facebook, 2),
        "tot_tiktok": round(tot_tiktok, 2),
        "tot_shopee": round(tot_shopee, 2),
        "tot_transfer": round(tot_transfer, 2),
        "tot_cod": round(tot_cod, 2),
        "grand_total": grand_total,
        "orders": order_items_out,
        "sheet_rows": table_rows,
    }


def should_run_daily_1am_report() -> tuple[bool, str]:
    """Return `(True, yesterday_str)` if current Bangkok hour is >= 01:00 and yesterday's report hasn't been generated yet."""
    now_bkk = datetime.now(BKK_TZ)
    yesterday_str = (now_bkk - timedelta(days=1)).strftime("%Y-%m-%d")
    if now_bkk.hour < DAILY_REPORT_HOUR_BKK:
        return False, yesterday_str
    state: dict[str, Any] = {}
    if REPORT_STATE_FILE.exists():
        try:
            state = json.loads(REPORT_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            state = {}
    return state.get("last_report_date") != yesterday_str, yesterday_str


GOOGLE_SHEET_FILE_ID = "1mMO_aZnaCaDskrJMreJiaonFqna-WNKBhOoozAWxIhE"
GOOGLE_SHEET_URL = f"https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_FILE_ID}/edit?gid=0#gid=0"
DAILY_LINE_GROUP_HOUR_BKK = 7  # 07:00 AM Bangkok time (แจ้งสรุปยอดในกลุ่มไลน์งานหลังคีย์ออเดอร์ 06:00 น. เสร็จ)
LINE_GROUP_CONFIG_FILE = Path(__file__).resolve().parent.parent / "line_group_config.json"
DEFAULT_LINE_WORK_GROUPS = ["C814be1f1cc536059190b79ac21d4e562"]  # กลุ่มไลน์งาน แอม+นัด


def load_line_group_config() -> dict[str, Any]:
    """Load registered LINE work group IDs and 07:00 AM broadcast state."""
    import os

    cfg: dict[str, Any] = {
        "groups": list(DEFAULT_LINE_WORK_GROUPS),
        "group_meta": {
            "C814be1f1cc536059190b79ac21d4e562": {
                "group_id": "C814be1f1cc536059190b79ac21d4e562",
                "brand_id": "workbot",
                "group_type": "group",
                "name": "แอม+นัด",
            }
        },
        "last_7am_report_date": "2026-10-30",
        "last_7am_sent_at": "2026-10-31T12:48:50+07:00",
    }
    if LINE_GROUP_CONFIG_FILE.exists():
        try:
            loaded = json.loads(LINE_GROUP_CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                cfg.update(loaded)
        except Exception:
            pass

    # Merge default & any group IDs from environment variable LINE_WORK_GROUP_IDS (comma-separated)
    env_groups = [g.strip() for g in os.getenv("LINE_WORK_GROUP_IDS", "").split(",") if g.strip()]
    groups_list: list[str] = list(cfg.get("groups") or [])
    for g in list(DEFAULT_LINE_WORK_GROUPS) + env_groups:
        if g not in groups_list:
            groups_list.append(g)

    # Also check SQLite sessions for any recorded `:line_group:` session keys
    try:
        from . import database

        for s in database.list_all_sessions(brand_id="all", platform="line_group", state="all"):
            ext_id = str(s.get("external_user_id") or "").strip()
            if ext_id and ext_id not in groups_list:
                groups_list.append(ext_id)
    except Exception:
        pass

    cfg["groups"] = groups_list
    return cfg


def save_line_group_config(cfg: dict[str, Any]) -> None:
    """Persist registered LINE work group IDs and broadcast state."""
    try:
        LINE_GROUP_CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("Failed to write line_group_config.json: %s", exc)


def register_line_group(group_id: str, brand_id: str = "buksukjai", group_type: str = "group") -> bool:
    """Register a LINE Group (`C...`) or Room (`R...`) to receive the daily 07:00 AM sales & stock summary.
    Returns True if this is a newly registered group.
    """
    group_id = (group_id or "").strip()
    if not group_id:
        return False
    cfg = load_line_group_config()
    groups: list[str] = list(cfg.get("groups") or [])
    is_new = group_id not in groups
    if is_new:
        groups.append(group_id)
    cfg["groups"] = groups
    meta = dict(cfg.get("group_meta") or {})
    now_iso = datetime.now(BKK_TZ).isoformat()
    if group_id not in meta:
        meta[group_id] = {
            "group_id": group_id,
            "brand_id": brand_id,
            "group_type": group_type,
            "joined_at": now_iso,
            "last_active_at": now_iso,
        }
    else:
        meta[group_id]["last_active_at"] = now_iso
        meta[group_id]["brand_id"] = brand_id
    cfg["group_meta"] = meta
    save_line_group_config(cfg)

    try:
        from . import database

        psid = database.make_session_key(brand_id, "line_group", group_id)
        database.get_or_create_session(
            psid=psid,
            brand_id=brand_id,
            platform="line_group",
            external_user_id=group_id,
            customer_name=f"กลุ่มไลน์งาน ({group_id[:8]}...)",
        )
        database.update_session_meta(psid=psid, bot_enabled=False, notes="Registered LINE Work Group for 07:00 AM Daily Report")
    except Exception as exc:
        logger.warning("SQLite line_group session save warning: %s", exc)

    return is_new


def unregister_line_group(group_id: str) -> None:
    """Remove a LINE Group when the bot leaves the group."""
    group_id = (group_id or "").strip()
    if not group_id:
        return
    cfg = load_line_group_config()
    cfg["groups"] = [g for g in (cfg.get("groups") or []) if g != group_id]
    save_line_group_config(cfg)


def fetch_facebook_buy_audit(target_date: str) -> dict[str, Any]:
    """Query Facebook Graph API for `#BUY` tags and `เพจ : ข้าวบุก สุขใจ` order summaries on `target_date` (BKK time).
    Returns both raw `#BUY` tag count/amount (matching Meta ROI Tracking) and deduplicated customer order count/amount
    (when an admin tags `#BUY` twice in the same chat because a customer switched from COD to Transfer).
    """
    import os
    from .config_loader import get_page_by_brand_id

    page = get_page_by_brand_id("buksukjai") or {}
    channels = page.get("channels") or {}
    token = os.getenv("PAGE_ACCESS_TOKEN") or channels.get("fb_page_access_token") or ""
    if not token:
        return {"raw_buy_count": 0, "raw_buy_total": 0.0, "dedup_count": 0, "dedup_total": 0.0, "duplicates": [], "orders": []}

    try:
        resp = httpx.get(
            "https://graph.facebook.com/v21.0/me/conversations",
            params={
                "fields": "participants,updated_time,messages.limit(35){message,created_time,from}",
                "limit": 80,
                "access_token": token,
            },
            timeout=20.0,
        )
        if resp.status_code != 200:
            return {"raw_buy_count": 0, "raw_buy_total": 0.0, "dedup_count": 0, "dedup_total": 0.0, "duplicates": [], "orders": []}
        convs = resp.json().get("data") or []
    except Exception as exc:
        logger.warning("Facebook #BUY audit query warning: %s", exc)
        return {"raw_buy_count": 0, "raw_buy_total": 0.0, "dedup_count": 0, "dedup_total": 0.0, "duplicates": [], "orders": []}

    raw_buy_count = 0
    raw_buy_total = 0.0
    dedup_orders: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []

    for c in convs:
        parts = [
            str(p.get("name") or "").strip()
            for p in ((c.get("participants") or {}).get("data") or [])
            if "ข้าวบุก" not in str(p.get("name") or "")
        ]
        fb_name = parts[0] if parts else "ลูกค้า Facebook"
        msgs = list(reversed((c.get("messages") or {}).get("data") or []))

        day_buys: list[dict[str, Any]] = []
        last_summary_text = ""
        for m in msgs:
            created_str = str(m.get("created_time") or "")
            if not created_str:
                continue
            try:
                dt_bkk = datetime.strptime(created_str, "%Y-%m-%dT%H:%M:%S%z").astimezone(BKK_TZ)
            except Exception:
                continue
            if dt_bkk.strftime("%Y-%m-%d") != target_date:
                continue

            txt = str(m.get("message") or "").strip()
            if "เพจ :" in txt and "สินค้า :" in txt:
                last_summary_text = txt

            m_buy = re.search(r"#BUY\s*(\d+(?:\.\d+)?)", txt, re.IGNORECASE)
            if m_buy:
                amt = float(m_buy.group(1))
                raw_buy_count += 1
                raw_buy_total += amt
                day_buys.append(
                    {
                        "fb_name": fb_name,
                        "amount": amt,
                        "time_bkk": dt_bkk.strftime("%H:%M:%S"),
                        "summary_text": last_summary_text,
                    }
                )

        if day_buys:
            latest = day_buys[-1]
            dedup_orders.append(latest)
            if len(day_buys) > 1:
                earlier_tags = [f"#BUY{int(x['amount'])}" for x in day_buys[:-1]]
                latest_tag = f"#BUY{int(latest['amount'])}"
                dup_amt = sum(x["amount"] for x in day_buys[:-1])
                duplicates.append(
                    {
                        "fb_name": fb_name,
                        "earlier_tags": earlier_tags,
                        "latest_tag": latest_tag,
                        "duplicate_amount": round(dup_amt, 2),
                    }
                )

    dedup_total = round(sum(x["amount"] for x in dedup_orders), 2)
    return {
        "raw_buy_count": raw_buy_count,
        "raw_buy_total": round(raw_buy_total, 2),
        "dedup_count": len(dedup_orders),
        "dedup_total": dedup_total,
        "duplicates": duplicates,
        "orders": dedup_orders,
    }


def build_daily_sales_from_facebook_graph(target_date: str) -> dict[str, Any] | None:
    """Fallback builder when JST ERP session cookie is unreachable: constructs the daily sales & SKU report
    from deduplicated Facebook `#BUY` orders on `target_date`.
    """
    audit_info = fetch_facebook_buy_audit(target_date)
    orders_in = audit_info.get("orders") or []
    if not orders_in:
        return None

    tot_transfer = 0.0
    tot_cod = 0.0
    tot_1kg = 0
    tot_500g = 0
    tot_60g = 0
    header = [
        "ลำดับ",
        "วันที่สั่งซื้อ",
        "ช่องทาง",
        "ชื่อลูกค้า",
        "ที่อยู่จัดส่ง",
        "เบอร์โทรศัพท์",
        "รหัส SKU",
        "จำนวนสินค้า",
        "จำนวนเงิน (บาท)",
        "รูปแบบการชำระเงิน",
        "เลขออเดอร์ JST / เลขพัสดุ",
    ]
    table_rows: list[list[Any]] = [header]

    for idx, item in enumerate(orders_in, 1):
        amt = float(item.get("amount") or 0.0)
        summary = str(item.get("summary_text") or "")
        is_cod = ("ปลายทาง" in summary) or ("COD" in summary.upper())
        if is_cod:
            tot_cod += amt
        else:
            tot_transfer += amt

        # Parse SKU sizes from summary text
        k1, g500, g60 = 0, 0, 0
        sku_code = "BSJ"
        low_s = summary.lower().replace(" ", "")
        if "3kgแถม60g3" in low_s:
            k1, g60, sku_code = 3, 3, "BSJ1KG3_60G3"
        elif "2kgแถม60g2" in low_s:
            k1, g60, sku_code = 2, 2, "BSJ1KG2_60G2"
        elif "1kg" in low_s:
            k1, sku_code = 1, "BSJ1KG1"
        elif "500g" in low_s or "500" in low_s:
            g500, sku_code = 1, "BSJ500G1"
        elif "60g" in low_s:
            m_q = re.search(r"60g(\d+)", low_s)
            g60 = int(m_q.group(1)) if m_q else 10
            sku_code = f"BSJ60G{g60}"

        tot_1kg += k1
        tot_500g += g500
        tot_60g += g60
        pieces = k1 + g500 + g60
        pay_label = "COD" if is_cod else "โอน"
        table_rows.append([idx, target_date, "Facebook", item.get("fb_name", ""), summary, "", sku_code, pieces, amt, pay_label, ""])

    tot_pieces = tot_1kg + tot_500g + tot_60g
    grand_total = round(tot_transfer + tot_cod, 2)
    return {
        "target_date": target_date,
        "order_count": len(orders_in),
        "tot_1kg": tot_1kg,
        "tot_500g": tot_500g,
        "tot_60g": tot_60g,
        "tot_pieces": tot_pieces,
        "tot_facebook": grand_total,
        "tot_tiktok": 0.0,
        "tot_shopee": 0.0,
        "tot_transfer": round(tot_transfer, 2),
        "tot_cod": round(tot_cod, 2),
        "grand_total": grand_total,
        "orders": orders_in,
        "sheet_rows": table_rows,
        "fb_buy_audit": audit_info,
        "source": "facebook_graph_fallback",
    }


def format_line_group_daily_summary(report: dict[str, Any]) -> str:
    """Format the daily sales & warehouse stock reconciliation summary for the LINE Work Group."""
    t_date = report.get("target_date", "")
    order_count = int(report.get("order_count") or 0)
    fb_amt = float(report.get("tot_facebook") or 0.0)
    tt_amt = float(report.get("tot_tiktok") or 0.0)
    sp_amt = float(report.get("tot_shopee") or 0.0)
    tr_amt = float(report.get("tot_transfer") or 0.0)
    cod_amt = float(report.get("tot_cod") or 0.0)
    grand_amt = float(report.get("grand_total") or 0.0)

    qty_60g = int(report.get("tot_60g") or 0)
    qty_500g = int(report.get("tot_500g") or 0)
    qty_1kg = int(report.get("tot_1kg") or 0)
    qty_total = int(report.get("tot_pieces") or (qty_60g + qty_500g + qty_1kg))

    fb_audit = report.get("fb_buy_audit") or {}
    dups = fb_audit.get("duplicates") or []
    raw_buy_cnt = int(fb_audit.get("raw_buy_count") or 0)
    raw_buy_tot = float(fb_audit.get("raw_buy_total") or 0.0)
    dedup_cnt = int(fb_audit.get("dedup_count") or 0)

    fb_line = f"• Facebook : {fb_amt:,.2f} บาท"
    if dedup_cnt > 0:
        fb_line = f"• Facebook : {fb_amt:,.2f} บาท ({dedup_cnt} ออเดอร์จัดส่งจริง)"

    lines = [
        f"📊 สรุปยอดขายและตัดสต็อกประจำวันที่ {t_date}",
        "(รายงานอัตโนมัติหลังคีย์ออเดอร์เสร็จ 07:00 น. ค่ะ)",
        "━━━━━━━━━━━━━━━",
        f"🛒 ยอดขายแยกตามช่องทาง (รวมจัดส่งจริง {order_count} ออเดอร์)",
        fb_line,
    ]
    if dups and raw_buy_cnt > dedup_cnt:
        dup_desc = ", ".join(
            f"{d['fb_name']} ({'/'.join(d['earlier_tags'])} เปลี่ยนเป็น {d['latest_tag']})" for d in dups
        )
        lines.append(
            f"  ↳ 💡 เทียบ ROI Tracking เพจ: แอดมินติดแท็ก #BUY {raw_buy_cnt} ครั้ง ({raw_buy_tot:,.2f} บาท) "
            f"เนื่องจากติดแท็กซ้ำในแชทเดิม ({dup_desc}) จึงตัดบิลซ้ำออกให้ตรงกับที่จัดส่งจริงค่ะ"
        )

    lines.extend(
        [
            f"• TikTok : {tt_amt:,.2f} บาท",
            f"• Shopee : {sp_amt:,.2f} บาท",
            "",
            "💰 ยอดขายแยกตามวิธีชำระเงิน",
            f"• ยอดโอน : {tr_amt:,.2f} บาท",
            f"• ยอด COD : {cod_amt:,.2f} บาท",
            f"✨ รวมยอดขายสุทธิทั้งสิ้น : {grand_amt:,.2f} บาท",
            "━━━━━━━━━━━━━━━",
            "📦 จำนวนสินค้าที่หมดไป (สำหรับตัดสต็อกโกดัง)",
            f"• ขนาด 60 กรัม หมดไป : {qty_60g:,} ซอง",
            f"• ขนาด 500 กรัม หมดไป : {qty_500g:,} ถุง",
            f"• ขนาด 1 กิโลกรัม หมดไป : {qty_1kg:,} ถุง",
            f"✅ รวมจำนวนสินค้าที่หมดไปทั้งหมด : {qty_total:,} ชิ้น",
            "━━━━━━━━━━━━━━━",
            "🔗 ดูตารางรายชื่อและรายละเอียดใน Google Sheets:",
            GOOGLE_SHEET_URL,
        ]
    )
    return "\n".join(lines)


def should_run_daily_7am_line_report() -> tuple[bool, str]:
    """Return `(True, yesterday_str)` if current Bangkok hour is >= 07:00, groups are registered,
    and yesterday's 07:00 AM LINE group report hasn't been sent yet.
    """
    now_bkk = datetime.now(BKK_TZ)
    yesterday_str = (now_bkk - timedelta(days=1)).strftime("%Y-%m-%d")
    if now_bkk.hour < DAILY_LINE_GROUP_HOUR_BKK:
        return False, yesterday_str
    cfg = load_line_group_config()
    if not cfg.get("groups"):
        return False, yesterday_str
    return cfg.get("last_7am_report_date") != yesterday_str, yesterday_str


def fetch_report_from_google_sheet(target_date: str | None = None) -> dict[str, Any] | None:
    """Pull and parse the daily sales & warehouse stock summary directly from the connected Google Sheet
    (`https://docs.google.com/spreadsheets/d/1mMO_aZnaCaDskrJMreJiaonFqna-WNKBhOoozAWxIhE/export?format=csv`).
    """
    import csv
    import io

    export_url = f"https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_FILE_ID}/export?format=csv"
    try:
        resp = httpx.get(export_url, follow_redirects=True, timeout=15.0)
        if resp.status_code != 200 or not resp.text.strip():
            return None
        raw_csv = resp.content.decode("utf-8", errors="replace")
    except Exception as exc:
        logger.warning("Google Sheet CSV fetch warning: %s", exc)
        return None

    rows = list(csv.reader(io.StringIO(raw_csv)))
    if len(rows) < 2:
        return None

    sheet_dates: list[str] = []
    order_rows: list[list[str]] = []
    for r in rows[1:]:
        if len(r) >= 10 and str(r[0]).strip().isdigit() and re.match(r"^\d{4}-\d{2}-\d{2}$", str(r[1]).strip()):
            d_str = str(r[1]).strip()
            sheet_dates.append(d_str)
            if not target_date or d_str == target_date:
                order_rows.append(r)

    if not order_rows:
        return None

    effective_date = target_date or sheet_dates[0]
    tot_transfer = 0.0
    tot_cod = 0.0
    tot_facebook = 0.0
    tot_tiktok = 0.0
    tot_shopee = 0.0
    tot_1kg = 0
    tot_500g = 0
    tot_60g = 0

    for r in order_rows:
        channel = str(r[2]).strip()
        sku_str = str(r[6]).strip()
        try:
            amt = float(str(r[8]).replace(",", "").strip() or 0.0)
        except ValueError:
            amt = 0.0
        pay_label = str(r[9]).strip().upper()
        if "COD" in pay_label:
            tot_cod += amt
        else:
            tot_transfer += amt

        ch_low = channel.lower()
        if "facebook" in ch_low:
            tot_facebook += amt
        elif "shopee" in ch_low:
            tot_shopee += amt
        else:
            tot_tiktok += amt

        # Parse SKU counts from SKU column & qty column
        try:
            row_qty = int(float(str(r[7]).replace(",", "").strip() or 1))
        except ValueError:
            row_qty = 1
        codes = [c.strip() for c in sku_str.split(",") if c.strip()]
        for code in codes:
            if code == "BSJ1KG1":
                tot_1kg += row_qty
            elif code == "BSJ1KG2":
                tot_1kg += 2
            elif code == "BSJ1KG3":
                tot_1kg += 3
            elif code == "BSJ1KG2_60G2":
                tot_1kg += 2
                tot_60g += 2
            elif code == "BSJ1KG3_60G3":
                tot_1kg += 3
                tot_60g += 3
            elif code == "BSJ500G1":
                tot_500g += row_qty
            elif code.startswith("BSJ60G"):
                tot_60g += row_qty

    # Also check explicit summary rows at bottom of Google Sheet if all rows in the sheet belong to effective_date
    if len(set(sheet_dates)) == 1 and sheet_dates[0] == effective_date:
        for r in rows[1:]:
            col_g = str(r[6]).strip() if len(r) > 6 else ""
            col_h = str(r[7]).strip() if len(r) > 7 else ""
            col_i = str(r[8]).strip() if len(r) > 8 else ""
            try:
                if col_g == "1 กิโลกรัม" and col_h:
                    tot_1kg = int(float(col_h.replace(",", "")))
                elif col_g == "500 กรัม" and col_h:
                    tot_500g = int(float(col_h.replace(",", "")))
                elif col_g == "60 กรัม" and col_h:
                    tot_60g = int(float(col_h.replace(",", "")))
                elif col_h == "Facebook" and col_i:
                    tot_facebook = float(col_i.replace(",", ""))
                elif col_h == "TikTok" and col_i:
                    tot_tiktok = float(col_i.replace(",", ""))
                elif col_h == "Shopee" and col_i:
                    tot_shopee = float(col_i.replace(",", ""))
                elif col_h == "โอน" and col_i:
                    tot_transfer = float(col_i.replace(",", ""))
                elif col_h == "COD" and col_i:
                    tot_cod = float(col_i.replace(",", ""))
            except ValueError:
                pass

    tot_pieces = tot_1kg + tot_500g + tot_60g
    grand_total = round(tot_transfer + tot_cod, 2)
    return {
        "target_date": effective_date,
        "order_count": len(order_rows),
        "tot_1kg": tot_1kg,
        "tot_500g": tot_500g,
        "tot_60g": tot_60g,
        "tot_pieces": tot_pieces,
        "tot_facebook": round(tot_facebook, 2),
        "tot_tiktok": round(tot_tiktok, 2),
        "tot_shopee": round(tot_shopee, 2),
        "tot_transfer": round(tot_transfer, 2),
        "tot_cod": round(tot_cod, 2),
        "grand_total": grand_total,
        "orders": [],
        "sheet_rows": rows,
        "source": "google_sheet",
    }


def load_or_build_daily_report(target_date: str) -> dict[str, Any]:
    """Pull the daily report from Google Sheets (`1mMO_aZnaCaDskrJMreJiaonFqna-WNKBhOoozAWxIhE`) and/or JST ERP.
    1. First attempts to refresh from JST ERP (`build_daily_sales_sheet_rows`) and sync to Google Sheets if JST session is active.
    2. Then reads from the live Google Sheet (`fetch_report_from_google_sheet`) so any manual edits in Google Sheets are respected.
    3. Falls back to local cached JSON snapshot (`reports/daily_sales_{target_date}.json`) or Facebook Graph API (`#BUY` tags) if offline.
    """
    jst_report: dict[str, Any] | None = None
    try:
        jst_report = build_daily_sales_sheet_rows(target_date)
        if jst_report and jst_report.get("order_count", 0) > 0:
            save_daily_report_snapshot(jst_report, sync_google_sheet=True)
    except Exception as exc:
        logger.info("JST live query skipped/fallback to Google Sheet for %s: %s", target_date, exc)

    sheet_report = fetch_report_from_google_sheet(target_date)

    cached_report: dict[str, Any] | None = None
    json_path = Path(__file__).resolve().parent.parent / "reports" / f"daily_sales_{target_date}.json"
    if json_path.exists():
        try:
            cached_report = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            cached_report = None

    chosen: dict[str, Any] | None = None
    candidates = [c for c in (sheet_report, jst_report, cached_report) if c and int(c.get("order_count") or 0) > 0]
    if candidates:
        chosen = max(candidates, key=lambda x: int(x.get("order_count") or 0))
    else:
        fb_fallback = build_daily_sales_from_facebook_graph(target_date)
        if fb_fallback and int(fb_fallback.get("order_count") or 0) > 0:
            chosen = fb_fallback

    if not chosen:
        chosen = jst_report or sheet_report or cached_report or {
            "target_date": target_date,
            "order_count": 0,
            "tot_1kg": 0,
            "tot_500g": 0,
            "tot_60g": 0,
            "tot_pieces": 0,
            "tot_facebook": 0.0,
            "tot_tiktok": 0.0,
            "tot_shopee": 0.0,
            "tot_transfer": 0.0,
            "tot_cod": 0.0,
            "grand_total": 0.0,
            "orders": [],
            "sheet_rows": [],
        }

    if "fb_buy_audit" not in chosen:
        try:
            chosen["fb_buy_audit"] = fetch_facebook_buy_audit(target_date)
        except Exception:
            pass

    return chosen


def send_daily_summary_to_line_groups(
    target_date: str | None = None,
    brand_id: str = "workbot",
    target_group_id: str | None = None,
    reply_token: str | None = None,
    mark_7am_done: bool = False,
) -> dict[str, Any]:
    """Pull the daily sales & stock report from Google Sheets / JST ERP for `target_date` (defaults to yesterday)
    and send the formatted summary to the specified `target_group_id` or all registered LINE work groups.
    """
    from .messenger import LINE_PUSH_URL, LINE_REPLY_URL, _get_channel_token

    now_bkk = datetime.now(BKK_TZ)
    if not target_date:
        target_date = (now_bkk - timedelta(days=1)).strftime("%Y-%m-%d")

    report = load_or_build_daily_report(target_date)
    summary_text = format_line_group_daily_summary(report)

    token = _get_channel_token(brand_id, "line")
    if not token:
        return {
            "status": "error",
            "reason": "missing_line_channel_access_token",
            "target_date": target_date,
            "summary_text": summary_text,
        }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    msg_payload = [{"type": "text", "text": summary_text}]

    cfg = load_line_group_config()
    groups_to_send = [target_group_id] if target_group_id else list(cfg.get("groups") or [])
    sent_groups: list[str] = []
    errors: list[dict[str, Any]] = []

    with httpx.Client(timeout=15.0) as client:
        # If reply_token is provided (e.g. someone typed "สรุปยอด" inside the LINE group), try replyToken first
        replied_ok = False
        if reply_token and target_group_id and not reply_token.startswith("sim_"):
            resp = client.post(
                LINE_REPLY_URL,
                headers=headers,
                json={"replyToken": reply_token, "messages": msg_payload},
            )
            if resp.status_code == 200:
                replied_ok = True
                sent_groups.append(target_group_id)

        if not replied_ok:
            for gid in groups_to_send:
                if not gid:
                    continue
                resp = client.post(
                    LINE_PUSH_URL,
                    headers=headers,
                    json={"to": gid, "messages": msg_payload},
                )
                if resp.status_code == 200:
                    sent_groups.append(gid)
                else:
                    errors.append({"group_id": gid, "status_code": resp.status_code, "body": resp.text})

    if mark_7am_done and sent_groups:
        cfg["last_7am_report_date"] = target_date
        cfg["last_7am_sent_at"] = now_bkk.isoformat()
        save_line_group_config(cfg)

    return {
        "status": "ok" if sent_groups else ("no_groups_registered" if not groups_to_send else "error"),
        "target_date": target_date,
        "sent_groups": sent_groups,
        "errors": errors,
        "summary_text": summary_text,
        "report": {
            "order_count": report["order_count"],
            "tot_facebook": report["tot_facebook"],
            "tot_tiktok": report["tot_tiktok"],
            "tot_shopee": report["tot_shopee"],
            "tot_transfer": report["tot_transfer"],
            "tot_cod": report["tot_cod"],
            "grand_total": report["grand_total"],
            "tot_60g": report["tot_60g"],
            "tot_500g": report["tot_500g"],
            "tot_1kg": report["tot_1kg"],
            "tot_pieces": report["tot_pieces"],
        },
    }


def save_daily_report_snapshot(report: dict[str, Any], sync_google_sheet: bool = True) -> Path:
    """Save the daily report JSON, TSV & CSV snapshot, and auto-update the connected Google Sheet via gdrive CLI."""
    import csv
    import shutil
    import subprocess

    out_dir = Path(__file__).resolve().parent.parent / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    target_date = report["target_date"]
    json_path = out_dir / f"daily_sales_{target_date}.json"
    tsv_path = out_dir / f"daily_sales_{target_date}.tsv"
    csv_path = out_dir / f"daily_sales_{target_date}.csv"

    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    tsv_lines = ["\t".join(str(c) for c in r) for r in report["sheet_rows"]]
    tsv_path.write_text("\n".join(tsv_lines), encoding="utf-8")

    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        for row in report["sheet_rows"]:
            writer.writerow(row)

    gdrive_bin = shutil.which("gdrive")
    if sync_google_sheet and gdrive_bin:
        try:
            subprocess.run(
                [
                    gdrive_bin,
                    "mutate",
                    "update",
                    GOOGLE_SHEET_FILE_ID,
                    str(csv_path),
                    "--mime-type",
                    "application/vnd.google-apps.spreadsheet",
                ],
                check=False,
                timeout=30,
            )
        except Exception as exc:
            logger.warning("gdrive sheet update warning: %s", exc)

    REPORT_STATE_FILE.write_text(
        json.dumps(
            {
                "last_report_date": target_date,
                "generated_at": datetime.now(BKK_TZ).isoformat(),
                "order_count": report["order_count"],
                "grand_total": report["grand_total"],
                "google_sheet_id": GOOGLE_SHEET_FILE_ID,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return csv_path
