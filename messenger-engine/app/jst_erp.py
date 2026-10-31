"""JST ERP Automated Order Sync & One-Click Fulfillment Integration.

Provides:
1. Pre-save duplicate checking against JST ERP (`/OMS/MiniShopOrder/NewQueryOrders`)
   by phone number (`ReceiverMobile`) within the last N days (default 3 days),
   preventing duplicate orders when a human admin has already entered an order,
   while still allowing repeat customers from weeks/months ago.
2. Thai recipient address recognition (`/MiniShop/Recipient/Address/AddresseeRecognition`)
   with smart name vs. street/village separation.
3. Payment slip image upload (`/MiniShop/Oms/Order/ErpUploadAttachement`) for
   Bank Transfer (`SCB 3044075455`) orders so JST ERP's built-in Slip OCR works automatically.
4. Direct order creation (`/MiniShop/OMS/Order/Save`) for both COD and Bank Transfer.
5. Automatic extraction of confirmed order details & slip URLs from `chatbot.db` / Facebook Graph API,
   plus one-click per-session push and batch auto-sync.
"""

from __future__ import annotations

import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from dotenv import load_dotenv

from pathlib import Path

from app.config_loader import get_page_by_brand_id
from app.database import SessionLocal, UserSession, get_full_messages

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
load_dotenv()
logger = logging.getLogger(__name__)


def _append_session_note(psid: str, note_line: str) -> None:
    with SessionLocal() as db:
        u = db.get(UserSession, psid)
        if u is not None:
            existing = (u.notes or "").strip()
            if note_line not in existing:
                u.notes = f"{existing}\n{note_line}".strip() if existing else note_line
                db.commit()

JST_SHOP_ID = 20759963
JST_WAREHOUSE_ID = 20421
JST_SALESMAN_ID = "22755436"
JST_LOGISTICS_ID = "59"
JST_LOGISTICS_CODE = "J&T Express TH"
JST_LOGISTICS_NAME = "J&T Express"
JST_SCB_ACCOUNT = "3044075455"

FRESH_JST_COOKIE = (
    "client_id=8c55bf3e7cb90f3ba27a22ddfdcc3762_91cdae39f749baaed0f1c166d97c4583; "
    "u_login_id=buksukjai%40gmail.com; VID_bcbff8986118=22755436; VP_bcbff8986118=1; "
    "AVID_147792=22755436; _ati=3616590229392; Notice-22755436-176=True; LanguageId=TH; "
    "Notice-22755436-177=True; u_cid=ffab80a5bac245c79a723ced80a396a2-22755436-49ce2350e1bfc8869835b061ea8b901d; "
    "u_id=22755436; u_name=buksukjai; u_co_id=15749167; u_co_name=Buksukjai; ClientTimeZone=7; "
    ".AspNetCore.GlobalAuthCookie=CfDJ8NUvc5HFTn9EnG_IMr2hg1SHradvjDPVgyUrg9Ex_iD1PHJg9502Q5QjCgRXYpZOnAYsZw7p7V7bU7l1Xyogh-o0XA35sjy4W1Jo_gW3IaxJlFcwJeGig0S8IC60NqfB1Pit2_L7-DV-3G-usY0bEW8eBvdi166HTeMg2o2AmEknpwu9Czp-iBq2duFcNRJWlrKdbPYG2x-z2U4KLbxg-dZy7teE26pZZzIFbcDUbcLjZkDmRVXZ_HCQ9wDb2MthYpWqpyryy6UmU1s99EF0E2A492-ZcV5uYEwiZd9pQs24hJDerLu_ttYz__Wp3JcUjwteQ3RfZ67ioPl8vJ2q10787nDdcnOboKNkoElrOx_3w4kJy851X5Pu8YX6rN7GkFtj270lMwnWO7r6j1AsrS1cdSfB4GDQjHhXqED5vNo30nQQHdwS85hiSl5wJEKTxXlPy6SMaFQDp7ULIauZ0pSZ5ueNz9fTk8XViLaQftV_; "
    "VT_bcbff8986118=14; SID_bcbff8986118=5596075514064757280"
)

_env_jst_cookie = os.getenv("JST_ERP_COOKIE", "").strip()
# Prefer FRESH_JST_COOKIE if env cookie is empty or still holds the expired 8925a238... u_cid
DEFAULT_JST_COOKIE = (
    FRESH_JST_COOKIE
    if (not _env_jst_cookie or "8925a23804b941b49f52f1c79c1c3b93" in _env_jst_cookie)
    else _env_jst_cookie
)

_RUNTIME_COOKIE: str = DEFAULT_JST_COOKIE
AUTO_SYNC_ENABLED: bool = True

# Verified JST ERP SKU Catalog for Shop 20759963 (ข้าวบุกสุขใจ)
KNOWN_SKUS: dict[str, dict[str, Any]] = {
    "BSJ60G1": {
        "itemId": "1735239403258939297",
        "skuId": "BSJ60G1",
        "name": "[ครบทุกไซซ์] ข้าวบุกสุขใจ ข้าวบุกหอมมะลิ แคลต่ำ คาร์บต่ำ มี 3 ขนาด 60g / 500g / 1kg เติมน้ำร้อนพร้อมทาน",
        "pic": "https://p16-oec-sg.ibyteimg.com/tos-alisg-i-aphluv4xwc-sg/062085de638b49b49a4f5d72da3d7a23~tplv-aphluv4xwc-origin-jpeg.jpeg?dr=15568&from=520841845&idc=my2&ps=933b5bde&shcp=2c1af732&shp=1f0b6a75&t=555f072d",
        "price": 39.0,
        "originPrice": 39.0,
        "propertyShortName": "60 กรัม 1 ถุง",
        "isCombined": False,
        "skuType": "Normal",
    },
    "BSJ500G1": {
        "itemId": "1735239403258939297",
        "skuId": "BSJ500G1",
        "name": "[ครบทุกไซซ์] ข้าวบุกสุขใจ ข้าวบุกหอมมะลิ แคลต่ำ คาร์บต่ำ มี 3 ขนาด 60g / 500g / 1kg เติมน้ำร้อนพร้อมทาน",
        "pic": "https://p16-oec-sg.ibyteimg.com/tos-alisg-i-aphluv4xwc-sg/07efec3e840a4a68b6046552b5be99b5~tplv-aphluv4xwc-origin-jpeg.jpeg?dr=15568&from=520841845&idc=my2&ps=933b5bde&shcp=2c1af732&shp=1f0b6a75&t=555f072d",
        "price": 239.0,
        "originPrice": 239.0,
        "propertyShortName": "500 กรัม 1 ถุง",
        "isCombined": False,
        "skuType": "Normal",
    },
    "BSJ1KG1": {
        "itemId": "1735239403258939297",
        "skuId": "BSJ1KG1",
        "name": "[ครบทุกไซซ์] ข้าวบุกสุขใจ ข้าวบุกหอมมะลิ แคลต่ำ คาร์บต่ำ มี 3 ขนาด 60g / 500g / 1kg เติมน้ำร้อนพร้อมทาน",
        "pic": "https://p16-oec-sg.ibyteimg.com/tos-alisg-i-aphluv4xwc-sg/42c0234cf2e647c38332990959587dce~tplv-aphluv4xwc-origin-jpeg.jpeg?dr=15568&from=520841845&idc=my2&ps=933b5bde&shcp=2c1af732&shp=1f0b6a75&t=555f072d",
        "price": 459.0,
        "originPrice": 459.0,
        "propertyShortName": "1 กิโลกรัม 1 ถุง",
        "isCombined": False,
        "skuType": "Normal",
    },
    "BSJ60G3": {
        "itemId": "BSJ60G3",
        "skuId": "BSJ60G3",
        "name": "โปร 60g 3ถุง",
        "pic": "",
        "price": 140.0,
        "originPrice": 140.0,
        "propertyShortName": "",
        "isCombined": True,
        "skuType": "Combine",
    },
    "BSJ60G5": {
        "itemId": "BSJ60G5",
        "skuId": "BSJ60G5",
        "name": "โปร 60g 5ถุง",
        "pic": "",
        "price": 199.0,
        "originPrice": 199.0,
        "propertyShortName": "",
        "isCombined": True,
        "skuType": "Combine",
    },
    "BSJ60G10": {
        "itemId": "BSJ60G10",
        "skuId": "BSJ60G10",
        "name": "โปร 60g 10ถุง",
        "pic": "",
        "price": 390.0,
        "originPrice": 390.0,
        "propertyShortName": "",
        "isCombined": True,
        "skuType": "Combine",
    },
    "BSJ60G15": {
        "itemId": "BSJ60G15",
        "skuId": "BSJ60G15",
        "name": "โปร 60g 15ถุง",
        "pic": "",
        "price": 555.0,
        "originPrice": 555.0,
        "propertyShortName": "",
        "isCombined": True,
        "skuType": "Combine",
    },
    "BSJ60G20": {
        "itemId": "BSJ60G20",
        "skuId": "BSJ60G20",
        "name": "โปร 60g 20ถุง",
        "pic": "",
        "price": 720.0,
        "originPrice": 580.0,
        "propertyShortName": "",
        "isCombined": True,
        "skuType": "Combine",
    },
    "BSJ1KG3": {
        "itemId": "BSJ1KG3",
        "skuId": "BSJ1KG3",
        "name": "โปร 1kg 3ถุง",
        "pic": "",
        "price": 1299.0,
        "originPrice": 1299.0,
        "propertyShortName": "",
        "isCombined": True,
        "skuType": "Combine",
    },
    "BSJ1KG2_60G2": {
        "itemId": "BSJ1KG2_60G2",
        "skuId": "BSJ1KG2_60G2",
        "name": "โปร 1kg 2ถุง + 60g 2ถุง",
        "pic": "",
        "price": 899.0,
        "originPrice": 899.0,
        "propertyShortName": "",
        "isCombined": True,
        "skuType": "Combine",
    },
    "BSJ1KG3_60G3": {
        "itemId": "BSJ1KG3_60G3",
        "skuId": "BSJ1KG3_60G3",
        "name": "โปร 1kg 3ถุง + 60g 3ถุง",
        "pic": "",
        "price": 1299.0,
        "originPrice": 1299.0,
        "propertyShortName": "",
        "isCombined": True,
        "skuType": "Combine",
    },
}


def get_jst_cookie() -> str:
    global _RUNTIME_COOKIE
    if not _RUNTIME_COOKIE:
        _RUNTIME_COOKIE = os.getenv("JST_ERP_COOKIE", "").strip()
    return _RUNTIME_COOKIE


def set_jst_cookie(cookie: str) -> None:
    global _RUNTIME_COOKIE
    _RUNTIME_COOKIE = cookie.strip()


def is_auto_sync_enabled() -> bool:
    return AUTO_SYNC_ENABLED


def set_auto_sync_enabled(enabled: bool) -> None:
    global AUTO_SYNC_ENABLED
    AUTO_SYNC_ENABLED = bool(enabled)


DAILY_BATCH_HOUR_BKK: int = 6
JST_SYNC_STATE_PATH: str = os.path.join(os.path.dirname(os.path.dirname(__file__)), "jst_sync_state.json")


def get_daily_sync_state() -> dict[str, Any]:
    import json
    default_state = {
        "sync_mode": "daily_6am",
        "daily_hour_bkk": DAILY_BATCH_HOUR_BKK,
        "schedule_description": "คีย์ข้อมูลวันละ 1 ครั้ง ตอน 06:00 น. (รวบรวมออเดอร์ของเมื่อวาน)",
        "last_daily_sync_date": "",
        "last_daily_sync_at": "",
        "last_created_count": 0,
        "last_duplicate_skipped_count": 0,
    }
    if os.path.exists(JST_SYNC_STATE_PATH):
        try:
            with open(JST_SYNC_STATE_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
            default_state.update(saved)
        except Exception:
            pass
    return default_state


def save_daily_sync_state(updates: dict[str, Any]) -> dict[str, Any]:
    import json
    st = get_daily_sync_state()
    st.update(updates)
    try:
        with open(JST_SYNC_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.warning("Failed to save JST daily sync state: %s", exc)
    return st


def should_run_daily_6am_sync() -> bool:
    """Return True when Thailand time (UTC+7) has reached >= 06:00 AM
    and today's daily batch has not yet run.
    """
    if not AUTO_SYNC_ENABLED:
        return False
    bkk_tz = timezone(timedelta(hours=7))
    now_bkk = datetime.now(bkk_tz)
    if now_bkk.hour < DAILY_BATCH_HOUR_BKK:
        return False
    today_str = now_bkk.strftime("%Y-%m-%d")
    st = get_daily_sync_state()
    return st.get("last_daily_sync_date") != today_str


def _headers(json_body: bool = True) -> dict[str, str]:
    h = {
        "Cookie": get_jst_cookie(),
        "X-Requested-With": "XMLHttpRequest",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36"
        ),
        "Origin": "https://asia-web.jsterp.com",
        "Referer": "https://asia-web.jsterp.com/minishop/oms/order/details?tabname=goods&createfrom=erp&isReadOnly=0&isUpsell=false",
    }
    if json_body:
        h["Content-Type"] = "application/json;charset=UTF-8"
    return h


def normalize_thai_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("66") and len(digits) == 11:
        digits = "0" + digits[2:]
    if len(digits) == 10 and digits.startswith("0"):
        return digits
    m = re.search(r"(0[689]\d{8})", digits)
    return m.group(1) if m else digits


def check_duplicate_order(phone: str, within_days: int = 3) -> dict[str, Any]:
    """Check JST ERP (`NewQueryOrders`) for any order matching `phone`."""
    clean_phone = normalize_thai_phone(phone)
    if not clean_phone:
        return {"phone": "", "exists_recently": False, "recent_orders": [], "historical_orders": []}

    payload = {
        "RequestModel": {
            "SendFrom": "NewQueryOrders",
            "ReceiverMobile": [clean_phone],
        },
        "DataPage": {
            "pageSize": 50,
            "pageIndex": 1,
            "total": 0,
            "sizes": [50, 100, 200, 500],
        },
    }
    resp = httpx.post(
        "https://asia.jsterp.com/OMS/MiniShopOrder/NewQueryOrders",
        headers=_headers(json_body=True),
        json=payload,
        timeout=15.0,
    )
    resp.raise_for_status()
    data = resp.json()
    rows_obj = data.get("Rows") or {}
    cols = rows_obj.get("cols") or []
    raw_rows = rows_obj.get("rows") or []

    bkk_tz = timezone(timedelta(hours=7))
    cutoff = datetime.now(bkk_tz) - timedelta(days=within_days)

    recent_orders: list[dict[str, Any]] = []
    historical_orders: list[dict[str, Any]] = []

    for r in raw_rows:
        row_dict = dict(zip(cols, r))
        order_id = str(row_dict.get("OrderId") or "")
        order_time_str = str(row_dict.get("OrderTime") or "")
        status_display = str(row_dict.get("StatusDisplay") or row_dict.get("SocialStatusDisplay") or "")
        pay_amount = row_dict.get("PayAmount")
        payment_name = str(row_dict.get("Payment") or row_dict.get("SettlementMethodDisplay") or "")

        if "ยกเลิก" in status_display or "Cancel" in str(row_dict.get("Status") or ""):
            continue

        summary = {
            "order_id": order_id,
            "order_time": order_time_str,
            "status": status_display,
            "pay_amount": pay_amount,
            "payment": payment_name,
        }
        historical_orders.append(summary)

        try:
            dt = datetime.strptime(order_time_str[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=bkk_tz)
            if dt >= cutoff:
                recent_orders.append(summary)
        except Exception:
            pass

    return {
        "phone": clean_phone,
        "exists_recently": len(recent_orders) > 0,
        "recent_orders": recent_orders,
        "historical_orders": historical_orders,
    }


def cancel_orders_in_jst(
    order_ids: list[int | str],
    cancel_reason: str = "คีย์ออเดอร์ซ้ำหรือลูกค้ายังยืนยันไม่ครบค่ะ",
) -> dict[str, Any]:
    """Cancel one or more orders in JST ERP (`/OMS/Order/CancelOrders`)."""
    clean_ids = [int(x) for x in order_ids if str(x).strip().isdigit()]
    if not clean_ids:
        return {"status": "error", "message": "ไม่พบ OrderId ที่ต้องการยกเลิกค่ะ"}
    h = _headers(json_body=True)
    h["Origin"] = "https://asia.jsterp.com"
    h["Referer"] = "https://asia.jsterp.com/OMS/Order/OrderManage"
    resp = httpx.post(
        "https://asia.jsterp.com/OMS/Order/CancelOrders",
        headers=h,
        json={"OrderIds": clean_ids, "CancelReason": cancel_reason},
        timeout=20.0,
    )
    resp.raise_for_status()
    return {"status": "ok", "order_ids": clean_ids, "response": resp.json()}


def confirm_orders_in_jst(order_ids: list[int | str]) -> dict[str, Any]:
    """Approve/confirm payment (`ตรวจสอบการชำระเงินแล้ว` -> `/OMS/MiniShopOrder/ConfirmOrder`) for verified bank-transfer orders in JST ERP."""
    clean_ids = [str(x).strip() for x in order_ids if str(x).strip().isdigit()]
    if not clean_ids:
        return {"status": "error", "message": "ไม่พบ OrderId ที่ต้องการยืนยันการชำระเงินค่ะ"}
    h = _headers(json_body=True)
    h["Origin"] = "https://asia.jsterp.com"
    h["Referer"] = "https://asia.jsterp.com/OMS/MiniShopOrder/Index"
    resp = httpx.post(
        "https://asia.jsterp.com/OMS/MiniShopOrder/ConfirmOrder",
        headers=h,
        json={"OrderIds": clean_ids},
        timeout=20.0,
    )
    resp.raise_for_status()
    return {"status": "ok", "order_ids": clean_ids, "response": resp.json()}


def verify_and_auto_confirm_jst_slips(limit: int = 50) -> dict[str, Any]:
    """Inspect recent bank-transfer orders in JST ERP where MachineAuditStatus is 'Fail' (or status is WaitConfirm).

    Why JST ERP's built-in MachineAudit fails on valid chat slips:
    1. 'เวลาชำระเงินไม่ตรงกัน' (Payment Time Mismatch): In Facebook/LINE chat commerce, customers always transfer money
       in chat BEFORE the order is keyed into JST ERP (`payTime < OrderTime`), whereas JST ERP's MachineAudit rule
       requires `payTime >= OrderTime`.
    2. 'ใบสั่งซื้อถูกใช้ไปแล้ว <OrderId>' (Duplicate Slip Ref): Occurs when an earlier order was cancelled and re-keyed
       with the same slip.

    This verifier checks JST ERP's decoded Bank QR result (`platformPayId` & `qrCodeAmount`) + active order status:
    - Must have a genuine Bank QR transaction reference (`platformPayId` non-empty)
    - Scanned QR amount (`qrCodeAmount`) must match the order's `PayAmount`
    - If flagged as duplicate (`ใบสั่งซื้อถูกใช้ไปแล้ว X`), order `X` must be Cancelled (`ยกเลิก`)
    When all checks pass, automatically calls `confirm_orders_in_jst` so the slip turns Pass (`ตรวจสอบการชำระเงินแล้ว`).
    """
    h = _headers(json_body=True)
    h["Origin"] = "https://asia.jsterp.com"
    h["Referer"] = "https://asia.jsterp.com/OMS/MiniShopOrder/Index"

    resp = httpx.post(
        "https://asia.jsterp.com/OMS/MiniShopOrder/NewQueryOrders",
        headers=h,
        json={
            "RequestModel": {"SendFrom": "NewQueryOrders"},
            "DataPage": {"pageSize": limit, "pageIndex": 1, "total": 0, "sizes": [50, 100]},
        },
        timeout=20.0,
    )
    resp.raise_for_status()
    rows_obj = (resp.json() or {}).get("Rows") or {}
    cols = rows_obj.get("cols") or []
    raw_rows = rows_obj.get("rows") or []

    all_rows = [dict(zip(cols, r)) for r in raw_rows]
    cancelled_oids = {
        str(d.get("OrderId") or "")
        for d in all_rows
        if "ยกเลิก" in str(d.get("StatusDisplay") or "") or "Cancel" in str(d.get("Status") or "")
    }

    auto_confirmed: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for d in all_rows:
        oid = str(d.get("OrderId") or "").strip()
        if not oid or oid in cancelled_oids or d.get("IsCod"):
            continue
        status_disp = str(d.get("StatusDisplay") or "")
        mach_status = str(d.get("MachineAuditStatus") or "")
        mach_msg = str(d.get("MachineAuditMessage") or "")

        # Check orders that failed MachineAudit or are waiting for payment confirmation
        if mach_status != "Fail" and "รอตรวจสอบ" not in status_disp and "WaitConfirm" not in str(d.get("StatusCode") or ""):
            continue

        r_det = httpx.post(
            "https://asia-web.jsterp.com/MiniShop/OMS/Order/GetOrderDetail",
            headers=_headers(json_body=True),
            json={"orderId": oid},
            timeout=15.0,
        )
        det = (r_det.json() or {}).get("data") or {}
        pays = det.get("pays") or []
        if not pays:
            rejected.append({"order_id": oid, "reason": "ไม่มีข้อมูลสลิปในระบบ (pays ว่าง)"})
            continue

        latest_pay = pays[0]
        ref_id = str(latest_pay.get("platformPayId") or "").strip()
        qr_amt = float(latest_pay.get("qrCodeAmount") or 0.0)
        order_amt = float(d.get("PayAmount") or latest_pay.get("amount") or 0.0)
        audit_msg = str(latest_pay.get("auditMessage") or mach_msg or "").strip()

        if not ref_id:
            rejected.append({"order_id": oid, "reason": "ไม่พบรหัสอ้างอิง QR Code ธนาคารบนสลิป (platformPayId ว่าง)"})
            continue

        if abs(qr_amt - order_amt) > 0.5:
            rejected.append(
                {
                    "order_id": oid,
                    "reason": f"ยอดเงินใน QR สลิป ({qr_amt:.2f}) ไม่ตรงกับยอดออเดอร์ ({order_amt:.2f})",
                    "platformPayId": ref_id,
                }
            )
            continue

        # If flagged as 'ใบสั่งซื้อถูกใช้ไปแล้ว <dup_oid>', verify whether <dup_oid> is cancelled
        m_dup = re.search(r"ใบสั่งซื้อถูกใช้ไปแล้ว\s*(\d+)", audit_msg)
        if m_dup:
            dup_oid = m_dup.group(1)
            if dup_oid not in cancelled_oids and dup_oid != oid:
                # Query dup_oid directly in case it wasn't in the first 50 rows
                r_dup = httpx.post(
                    "https://asia-web.jsterp.com/MiniShop/OMS/Order/GetOrderDetail",
                    headers=_headers(json_body=True),
                    json={"orderId": dup_oid},
                    timeout=10.0,
                )
                dup_det = (r_dup.json() or {}).get("data") or {}
                dup_status = str(dup_det.get("statusDisplay") or dup_det.get("statusCode") or "")
                if "ยกเลิก" not in dup_status and "Cancel" not in dup_status:
                    rejected.append(
                        {
                            "order_id": oid,
                            "reason": f"สลิปซ้ำกับออเดอร์ #{dup_oid} ที่ยังไม่ได้ยกเลิก ({dup_status})",
                            "platformPayId": ref_id,
                        }
                    )
                    continue

        # Passed all genuine slip checks! Auto-confirm in JST ERP
        confirm_orders_in_jst([oid])
        auto_confirmed.append(
            {
                "order_id": oid,
                "amount": order_amt,
                "qr_amount": qr_amt,
                "platformPayId": ref_id,
                "overridden_jst_audit_message": audit_msg,
            }
        )

    return {
        "status": "ok",
        "auto_confirmed_count": len(auto_confirmed),
        "auto_confirmed": auto_confirmed,
        "rejected_count": len(rejected),
        "rejected": rejected,
    }


def recognize_and_clean_address(
    raw_address: str,
    explicit_name: str = "",
    explicit_phone: str = "",
) -> dict[str, str]:
    """Use JST ERP's `AddresseeRecognition` API and clean up Thai name vs street address."""
    cleaned_input = (raw_address or "").strip()
    # Normalize common Thai typos and strip conversational prefixes before recognition
    cleaned_input = cleaned_input.replace("แขลง", "แขวง")
    cleaned_input = re.sub(
        r"(?:^|\n|\|)\s*(?:จัดส่งที่นี่นะครับ|จัดส่งที่นี่นะคะ|จัดส่งที่นี่|ที่อยู่จัดส่ง|ส่งที่|ชื่อ-ที่อยู่|ชื่อผู้รับ|ผู้รับ|ชื่อ|ที่อยู่|เบอร์โทรศัพท์|เบอร์โทร|เบอร์|โทร\.?|มือถือ)\s*[:：]?\s*",
        " ",
        cleaned_input,
    )
    cleaned_input = re.sub(r"\b(?:โทร\.?|เบอร์โทร|เบอร์|มือถือ)\s*[:：]?\s*(?=0|\+66)", " ", cleaned_input)
    # If customer wrote แขวง/เขต + 10xxx postal code without mentioning กรุงเทพ, append กรุงเทพมหานคร so JST recognizes it
    if ("เขต" in cleaned_input or "แขวง" in cleaned_input) and re.search(r"\b10\d{3}\b", cleaned_input):
        if "กรุงเทพ" not in cleaned_input and "กทม" not in cleaned_input:
            cleaned_input = f"{cleaned_input} กรุงเทพมหานคร"

    # Extract trailing recipient name after phone number if present (e.g., "... 12130 0909187907 วรรณา")
    trailing_name_hint = ""
    m_trail = re.search(
        r"(?:\+66\s*0?|0)[689]\d[\s\-]?\d{3}[\s\-]?\d{4}\s+([ก-๙a-zA-Z][ก-๙a-zA-Z\s\.]{1,35})$",
        cleaned_input.strip(),
    )
    if m_trail:
        cand = m_trail.group(1).strip()
        if not re.search(r"(ตำบล|อำเภอ|จังหวัด|แขวง|เขต|ถนน|ซอย|หมู่)", cand):
            trailing_name_hint = cand

    resp = httpx.post(
        "https://asia-web.jsterp.com/MiniShop/Recipient/Address/AddresseeRecognition",
        headers=_headers(json_body=True),
        json={"addressTxt": cleaned_input},
        timeout=15.0,
    )
    resp.raise_for_status()
    rec = (resp.json() or {}).get("data") or {}

    province = (rec.get("receiverProvince") or "").strip()
    city = (rec.get("receiverCity") or "").strip()
    district = (rec.get("receiverDistrict") or "").strip()
    zip_code = (rec.get("receiverZip") or "").strip()
    mobile = normalize_thai_phone(explicit_phone or rec.get("receiverMobile") or "")

    rec_name = (rec.get("receiverFirstName") or "").strip()
    rec_detail = (rec.get("receiverAddress") or "").strip()

    # Fallback subdistrict extraction if AddresseeRecognition missed ตำบล/ต./แขวง
    if not district:
        m_sub = re.search(r"(?:ตำบล|ต\.|แขวง)\s*([ก-๙]{2,25})", cleaned_input)
        if m_sub:
            district = m_sub.group(1).strip()
        elif "คูบางหลวง" in cleaned_input:
            district = "คูบางหลวง"

    rec_detail = re.sub(
        r"\b(จัดส่งที่นี่นะครับ|จัดส่งที่นี่นะคะ|ที่อยู่จัดส่ง|แขวง|เขต|ตำบล|อำเภอ|จังหวัด|ต\.|อ\.|จ\.|รหัส|เบอร์|โทร|ชื่อ)\s*(?=\s|$)",
        "",
        rec_detail,
    ).strip()
    rec_detail = re.sub(r"\s{2,}", " ", rec_detail).strip()

    addr_markers = r"(หมู่บ้าน|มบ\.|อาคาร|คอนโด|บริษัท|ร้าน|บ้านเลขที่|\d+/\d+|\b\d+\s+ม\.|ซ\.|ซอย|ถ\.|ถนน|ม\.\d+|หมู่\s*\d+)"
    if explicit_name.strip():
        first_name = explicit_name.strip()
    elif re.search(addr_markers, rec_name):
        m = re.search(addr_markers, rec_name)
        if m and m.start() > 0:
            first_name = rec_name[: m.start()].strip()
            overflow_addr = rec_name[m.start() :].strip()
            rec_detail = f"{overflow_addr} {rec_detail}".strip()
        else:
            first_name = rec_name
    else:
        first_name = rec_name

    first_name = re.sub(r"^(?:ชื่อผู้รับ|ผู้รับ|ชื่อ|จัดส่งที่นี่นะครับ|จัดส่งที่นี่นะคะ)\s*[:：]?\s*", "", first_name).strip()
    if not first_name and trailing_name_hint:
        first_name = trailing_name_hint
        rec_detail = re.sub(re.escape(trailing_name_hint) + r"\s*$", "", rec_detail).strip()

    return {
        "receiverFirstName": first_name,
        "receiverMobile": mobile,
        "receiverProvince": province,
        "receiverCity": city,
        "receiverDistrict": district,
        "receiverZip": zip_code,
        "receiverAddress": rec_detail,
    }


def verify_image_is_payment_slip(
    image_bytes: bytes | None = None,
    image_url: str = "",
    width_hint: int = 0,
    height_hint: int = 0,
) -> tuple[bool, str]:
    """Verify that an image is a real portrait bank transfer slip and NEVER a square/landscape promotion poster."""
    if image_url:
        if image_url.startswith("/static/") or "39178562_1505197616293642" in image_url:
            return False, "เป็นรูปสินค้าของร้านหรือสติกเกอร์ ไม่ใช่สลิปโอนเงินค่ะ"

    w, h = int(width_hint or 0), int(height_hint or 0)
    if (w <= 0 or h <= 0) and (image_bytes is not None or image_url):
        try:
            import io
            from PIL import Image

            raw = image_bytes
            if raw is None and image_url:
                r = httpx.get(image_url, timeout=15.0, follow_redirects=True)
                r.raise_for_status()
                raw = r.content
            if raw:
                with Image.open(io.BytesIO(raw)) as im:
                    w, h = im.size
        except Exception as exc:
            logger.warning("Failed to inspect slip image dimensions for %s: %s", image_url, exc)

    if w > 0 and h > 0:
        ratio = h / float(w)
        # All brand promotion posters are square 1:1 (ratio ~1.00) or 4:5 (<=1.10) or landscape (<1.0).
        # All Thai mobile banking slips (K+, SCB, ttb, Krungthai, BBL, MyMo) are portrait rectangles (ratio >= 1.12).
        if ratio < 1.12:
            return (
                False,
                f"รูปภาพมีสัดส่วน {w}x{h} (h/w={ratio:.2f}) ซึ่งเป็นรูปโปรโมชั่นสินค้าหรือภาพจัตุรัส/แนวนอน ไม่ใช่สลิปโอนเงินค่ะ",
            )
    return True, "ok"


def upload_payment_slip(image_url: str) -> dict[str, str]:
    """Download payment slip image from URL, verify it is NOT a promotion poster, and upload to JST ERP (`ErpUploadAttachement`)."""
    img_resp = httpx.get(image_url, timeout=20.0, follow_redirects=True)
    img_resp.raise_for_status()
    img_bytes = img_resp.content

    is_slip, reason = verify_image_is_payment_slip(image_bytes=img_bytes, image_url=image_url)
    if not is_slip:
        raise ValueError(f"ปฏิเสธการอัปโหลดรูปภาพ: {reason}")

    up_headers = {
        "Cookie": get_jst_cookie(),
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://asia-web.jsterp.com",
        "Referer": "https://asia-web.jsterp.com/minishop/oms/order/details?tabname=goods&createfrom=erp&isReadOnly=0&isUpsell=false",
    }
    resp = httpx.post(
        "https://asia-web.jsterp.com/MiniShop/Oms/Order/ErpUploadAttachement",
        headers=up_headers,
        data={"BizType": "PayReceipt"},
        files={"file": (f"slip_{int(time.time())}.jpg", img_bytes, "image/jpeg")},
        timeout=25.0,
    )
    resp.raise_for_status()
    res_json = resp.json()
    if not res_json.get("success") or not res_json.get("data"):
        raise RuntimeError(f"JST slip upload failed: {res_json}")
    return {
        "voucherId": res_json["data"]["id"],
        "uri": res_json["data"].get("uri", ""),
    }


def attach_or_replace_slip_on_jst_order(
    order_id: int | str,
    slip_image_url: str,
    amount: float,
    invalidate_fio_ids: list[int] | None = None,
) -> dict[str, Any]:
    """Upload a verified bank slip and attach it to an existing `WaitPay` order in JST ERP (`/OMS/MiniShopOrder/UploadReceipt`)."""
    img_resp = httpx.get(slip_image_url, timeout=20.0, follow_redirects=True)
    img_resp.raise_for_status()
    img_bytes = img_resp.content

    is_slip, reason = verify_image_is_payment_slip(image_bytes=img_bytes, image_url=slip_image_url)
    if not is_slip:
        return {"status": "error", "message": reason}

    if invalidate_fio_ids:
        httpx.post(
            "https://asia-web.jsterp.com/MiniShop/OMS/Order/OperationFInOut",
            headers=_headers(json_body=True),
            json={"fioIds": invalidate_fio_ids, "operationType": "Invalid"},
            timeout=15.0,
        )

    up_headers = {
        "Cookie": get_jst_cookie(),
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://asia.jsterp.com",
        "Referer": "https://asia.jsterp.com/OMS/Order/OrderManage?type=WaitPay",
    }
    r_up = httpx.post(
        "https://asia.jsterp.com/Intergration/Upload/UploadAttachement",
        headers=up_headers,
        data={"BizType": "PayReceipt"},
        files={"file": (f"slip_{order_id}_{int(time.time())}.jpg", img_bytes, "image/jpeg")},
        timeout=25.0,
    )
    r_up.raise_for_status()
    up_json = r_up.json()
    voucher_id = (up_json.get("Data") or up_json.get("data") or {}).get("Id")
    if not voucher_id:
        return {"status": "error", "message": f"UploadAttachement failed: {up_json}"}

    req = {
        "OrderId": int(order_id),
        "AccountId": JST_SCB_ACCOUNT,
        "Payment": "SCB",
        "ServiceProviderId": "SCB",
        "PayChannelAccount": JST_SCB_ACCOUNT,
        "LanguageId": "zh-cn",
        "VoucherId": voucher_id,
        "Amount": float(amount),
    }
    r_rec = httpx.post(
        "https://asia.jsterp.com/OMS/MiniShopOrder/UploadReceipt",
        headers=_headers(json_body=True),
        json=req,
        timeout=20.0,
    )
    r_rec.raise_for_status()
    return {"status": "ok", "voucher_id": voucher_id, "response": r_rec.json()}


def create_order_in_jst(
    *,
    raw_address: str,
    sku_id: str,
    qty: int = 1,
    custom_unit_price: float | None = None,
    freight: float = 0.0,
    is_cod: bool = False,
    slip_image_url: str = "",
    explicit_name: str = "",
    explicit_phone: str = "",
    explicit_address_fields: dict[str, str] | None = None,
    seller_remark: str = "",
    within_days_Check: int = 3,
    force_create: bool = False,
) -> dict[str, Any]:
    """Check JST ERP for duplicates and create the manual order in JST ERP."""
    addr = recognize_and_clean_address(raw_address, explicit_name=explicit_name, explicit_phone=explicit_phone)
    if explicit_address_fields:
        for k, v in explicit_address_fields.items():
            if v:
                addr[k] = v

    phone = normalize_thai_phone(addr.get("receiverMobile") or explicit_phone)
    if not phone:
        return {"status": "error", "message": "ไม่พบเบอร์โทรศัพท์ของผู้รับค่ะ"}

    # Mandatory pre-save duplicate check in JST ERP
    dup_info = check_duplicate_order(phone, within_days=within_days_Check)
    if dup_info["exists_recently"] and not force_create:
        return {
            "status": "duplicate_skipped",
            "message": f"พบออเดอร์ของเบอร์ {phone} ในระบบ JST ERP แล้ว (#{dup_info['recent_orders'][0]['order_id']} เมื่อ {dup_info['recent_orders'][0]['order_time']}) ข้ามการบันทึกซ้ำค่ะ",
            "existing_orders": dup_info["recent_orders"],
            "address": addr,
        }

    sku_meta = KNOWN_SKUS.get(sku_id)
    if not sku_meta:
        q_resp = httpx.post(
            f"https://asia-web.jsterp.com/MiniShop/Component/Goods/QueryBySkuOrKeyword?shopId={JST_SHOP_ID}",
            headers=_headers(json_body=True),
            json={"DataPage": {"PageIndex": 1, "PageSize": 5}, "Keyword": sku_id},
            timeout=15.0,
        )
        q_data = (q_resp.json() or {}).get("data") or []
        if not q_data:
            return {"status": "error", "message": f"ไม่พบรหัสสินค้า {sku_id} ในระบบ JST ERP ค่ะ"}
        first = q_data[0]
        sku_meta = {
            "itemId": first.get("itemId", sku_id),
            "skuId": first.get("skuId", sku_id),
            "name": first.get("name", sku_id),
            "pic": first.get("pic", ""),
            "price": float(first.get("price") or 0),
            "originPrice": float(first.get("price") or 0),
            "propertyShortName": first.get("propertyShortName", ""),
            "isCombined": bool(first.get("isCombined")),
            "skuType": first.get("skuType", "Normal"),
        }

    unit_price = float(custom_unit_price if custom_unit_price is not None else sku_meta["price"])
    origin_price = float(sku_meta.get("originPrice", unit_price))
    is_manual_modify_price = abs(unit_price - origin_price) > 0.01
    goods_amount = round(unit_price * int(qty), 2)
    freight_val = round(float(freight), 2)
    total_pay = round(goods_amount + freight_val, 2)

    voucher_id = ""
    voucher_uri = ""
    pay_way_amount: dict[str, float] = {}

    if is_cod:
        pay_way = "COD"
        pay_way_amount = {"COD": total_pay}
        payment_title = ""
        service_provider_id = ""
        pay_channel_account = ""
        account_id = ""
    elif slip_image_url:
        try:
            slip_res = upload_payment_slip(slip_image_url)
        except ValueError as ve:
            return {"status": "error", "message": str(ve)}
        voucher_id = slip_res["voucherId"]
        voucher_uri = slip_res["uri"]
        pay_way = "BankPay"
        pay_way_amount = {"BankPay": total_pay}
        payment_title = "SCB"
        service_provider_id = "SCB"
        pay_channel_account = JST_SCB_ACCOUNT
        account_id = JST_SCB_ACCOUNT
    else:
        return {
            "status": "error",
            "message": "ออเดอร์แบบโอนเงินต้องมีรูปสลิปโอนเงินจริงที่ตรวจสอบแล้วเท่านั้นค่ะ (ห้ามส่งเข้า JST ERP หากยังไม่มีสลิปโอนเงิน)",
        }

    ts_ms = int(time.time() * 1000)
    order_item = [
        {
            "innerOrderItemId": "",
            "orderItemId": "",
            "skuId": sku_meta["skuId"],
            "itemId": sku_meta["itemId"],
            "pic": sku_meta["pic"],
            "name": sku_meta["name"],
            "propertiesValue": sku_meta["propertyShortName"],
            "qty": int(qty),
            "price": unit_price,
            "basePrice": origin_price,
            "amount": goods_amount,
            "isGift": False,
            "weight": 0,
            "size": 0,
            "isDeleted": False,
            "skuType": sku_meta["skuType"],
            "keyword": "",
            "isOversold": False,
            "liveLimitQty": 0,
            "isNotNeedDelivery": False,
            "itemType": "",
            "isUpsell": False,
            "isCombined": bool(sku_meta["isCombined"]),
            "isManualModifyPrice": is_manual_modify_price,
            "platformOrderItemId": f"{sku_meta['skuId']}_{ts_ms}",
            "remark": "",
        }
    ]

    order_payload = {
        "Order": {
            "freight": freight_val,
            "payAmount": total_pay,
            "amount": goods_amount,
            "shopFreeAmount": 0,
            "platformFreeAmount": 0,
            "isInvoice": False,
            "logisticsCompanyId": JST_LOGISTICS_ID,
            "logisticsCompanyCode": JST_LOGISTICS_CODE,
            "logisticsCompanyName": JST_LOGISTICS_NAME,
            "addressId": "0",
            "receiverFirstName": addr["receiverFirstName"],
            "receiverLastName": "",
            "receiverCountryCode": "TH",
            "receiverCountry": "",
            "receiverProvince": addr["receiverProvince"],
            "receiverCity": addr["receiverCity"],
            "receiverTown": "",
            "receiverDistrict": addr["receiverDistrict"],
            "receiverAddress": addr["receiverAddress"],
            "receiverStreetNumber": "",
            "receiverMobile": phone,
            "receiverPhone": "",
            "platformBuyerEmail": "",
            "receiverZip": addr["receiverZip"],
            "sellerRemark": seller_remark,
            "buyerId": "",
            "orderFrom": "",
            "shopId": JST_SHOP_ID,
            "platformOrderType": "ManualOrder",
            "autoId": "0",
            "isCopyOrder": False,
            "copyOrderId": 0,
            "platformOrderId": "",
            "warehouseId": JST_WAREHOUSE_ID,
            "salesman": JST_SALESMAN_ID,
            "orderNumber": "",
            "trackingNumber": "",
            "isCod": bool(is_cod),
            "buyerNickName": "",
            "status": "",
            "orderTimeT": None,
            "planDeliveryDateT": None,
            "orderId": "",
            "profileId": "",
            "profileName": "",
            "mainAccountId": "",
            "mainAccountName": "",
            "isPushToSocialBuyer": False,
            "contactsId": 0,
            "buyerMessage": "",
            "deliveryWay": "DeliveryHome",
            "invoiceTitle": "",
            "invoiceTaxNo": "",
            "isUseBrInvoice": False,
            "invoiceIE": "",
            "invoicePhone": "",
            "invoiceAddress": "",
            "invoiceProvince": "",
            "invoiceCity": "",
            "invoiceDistrict": "",
            "invoiceEmail": "",
            "invoiceCompanyType": "",
            "invoiceType": "",
            "invoiceBranch": "",
            "isStillCreated": False,
            "accountId": account_id,
            "payment": payment_title,
            "serviceProviderId": service_provider_id,
            "payChannelAccount": pay_channel_account,
            "voucherId": voucher_id,
            "payWay": pay_way,
            "payWayAmount": pay_way_amount,
            "buyerPlatformId": "",
            "receiverBranchId": "",
            "receiverBranchName": "",
            "mopId": 0,
            "waitPayAmount": f"{total_pay:.2f}",
            "fundPayAmount": 0,
            "codCharge": 0,
            "taxAmount": 0,
            "isManualPromotion": False,
            "invoiceData": "{}",
            "isInsured": False,
            "insuredAmount": "",
            "isPriceIncludingTax": True,
            "taxRate": 7,
        },
        "OrderItem": order_item,
        "isFundPay": False,
        "isPlatformDownload": False,
        "isOpenNewManualMsgOrder": True,
        "addLabels": [],
        "isSendMessage": False,
        "isArchival": False,
        "IsUpsell": False,
    }

    save_resp = httpx.post(
        "https://asia-web.jsterp.com/MiniShop/OMS/Order/Save",
        headers=_headers(json_body=True),
        json=order_payload,
        timeout=25.0,
    )
    save_resp.raise_for_status()
    save_json = save_resp.json()
    if not save_json.get("success"):
        return {
            "status": "error",
            "message": save_json.get("message") or f"JST Save failed: {save_json}",
            "raw_response": save_json,
        }

    verify_info = check_duplicate_order(phone, within_days=1)
    created_order = verify_info["recent_orders"][0] if verify_info["recent_orders"] else None

    if not is_cod and voucher_id and created_order and created_order.get("order_id"):
        try:
            # Wait briefly for JST ERP's async pay-ocr worker to finish scanning the slip, then verify & confirm
            time.sleep(4.0)
            verify_and_auto_confirm_jst_slips(limit=25)
        except Exception as exc:
            logger.warning("Auto ConfirmOrder warning for %s: %s", created_order.get("order_id"), exc)

    return {
        "status": "created",
        "message": "สร้างคำสั่งซื้อในระบบ JST ERP สำเร็จค่ะ",
        "created_order": created_order,
        "save_response": save_json,
        "address": addr,
        "sku_id": sku_id,
        "qty": qty,
        "total_pay": total_pay,
        "pay_way": pay_way,
        "voucher_id": voucher_id,
        "voucher_uri": voucher_uri,
    }


def _slice_to_current_inquiry_fb(raw_messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Slice chronological FB Graph API messages to the current active inquiry (after latest ad click or >72h gap)."""
    current_start_idx = 0
    prev_dt = None
    boundary_markers = ("ตอบกลับโฆษณา", "กำลังตอบกลับความคิดเห็น", "เริ่มต้นใช้งาน")
    for idx, m in enumerate(raw_messages):
        txt = str(m.get("message") or "")
        created_str = m.get("created_time") or ""
        msg_dt = None
        if created_str:
            try:
                msg_dt = datetime.fromisoformat(created_str.replace("+0000", "+00:00"))
            except Exception:
                msg_dt = None
        if prev_dt and msg_dt and (msg_dt - prev_dt).total_seconds() > 72 * 3600:
            current_start_idx = idx
        elif idx > 0 and any(bm in txt for bm in boundary_markers):
            # If the message immediately preceding 'ตอบกลับโฆษณา' was sent within 120 seconds, include it too
            if prev_dt and msg_dt and abs((msg_dt - prev_dt).total_seconds()) <= 120:
                current_start_idx = max(0, idx - 1)
            else:
                current_start_idx = idx
        if msg_dt:
            prev_dt = msg_dt
    return raw_messages[current_start_idx:]


def _fetch_fb_thread_messages_and_slip(external_user_id: str, brand_id: str = "buksukjai") -> tuple[list[dict[str, str]], str]:
    """Query Facebook Graph API for a specific customer's CURRENT inquiry messages and verified slip image URL."""
    fb_msgs: list[dict[str, str]] = []
    latest_slip = ""
    try:
        page = get_page_by_brand_id(brand_id)
        if not page:
            return fb_msgs, latest_slip
        token = page.get("channels", {}).get("fb_page_access_token") or os.getenv("PAGE_ACCESS_TOKEN", "")
        page_id = str(page.get("channels", {}).get("fb_page_id") or "806129109240845")
        if not token or not external_user_id:
            return fb_msgs, latest_slip
        r = httpx.get(
            f"https://graph.facebook.com/v21.0/{page_id}/conversations",
            params={
                "user_id": external_user_id,
                "fields": "participants,messages.limit(25){from,message,created_time,attachments{image_data}}",
                "access_token": token,
            },
            timeout=12.0,
        )
        data = (r.json() or {}).get("data") or []
        if not data:
            return fb_msgs, latest_slip
        all_chron_messages = list(reversed(data[0].get("messages", {}).get("data", [])))
        raw_messages = _slice_to_current_inquiry_fb(all_chron_messages)
        seen_payment_context = any(
            re.search(r"(#BUY|ชำระเงิน\s*:\s*โอน|โอนเงิน|โอนแล้ว|แจ้งสลิป|304-407545-5|3044075455)", str(m.get("message") or ""))
            for m in raw_messages
        )
        total_msgs = len(raw_messages)
        for idx, m in enumerate(raw_messages):
            sender_id = str((m.get("from") or {}).get("id") or "")
            role = "user" if sender_id == external_user_id else "admin"
            txt = str(m.get("message") or "").strip()
            if txt:
                fb_msgs.append({"role": role, "content": txt})
                if re.search(
                    r"(304-407545-5|3044075455|ดิจิสท์|เลขบัญชี|ยอดชำระ|ยอดรวมทั้งหมด|โอนแล้วแจ้งสลิป|ยอดโอน|โอนเงิน)",
                    txt,
                ):
                    seen_payment_context = True
            if role == "user":
                # Ignore ad/promo screenshots attached to the very first ad-click message unless payment context exists
                if not seen_payment_context and idx == 0 and total_msgs > 2:
                    continue
                for att in m.get("attachments", {}).get("data", []):
                    img_data = att.get("image_data") or {}
                    url = img_data.get("url")
                    w = int(img_data.get("width") or 0)
                    h = int(img_data.get("height") or 0)
                    if url:
                        ok, _ = verify_image_is_payment_slip(image_url=url, width_hint=w, height_hint=h)
                        if ok:
                            latest_slip = url
                            fb_msgs.append({"role": "user", "content": f"[IMAGE:{url}]"})
    except Exception as exc:
        logger.warning("Failed to fetch FB thread for %s: %s", external_user_id, exc)
    return fb_msgs, latest_slip


def check_dialogue_completion(msgs: list[dict[str, str]], has_verified_slip: bool = False) -> tuple[bool, str]:
    """Audit whether the customer has actually finished answering all questions from the shop in the current inquiry."""
    if not msgs:
        return False, "ไม่มีข้อความสนทนาในรอบปัจจุบันค่ะ"

    user_msgs = [m["content"].strip() for m in msgs if m.get("role") == "user" and m.get("content", "").strip()]
    if not user_msgs:
        return False, "ลูกค้ายังไม่ได้ส่งข้อความตอบกลับในรอบปัจจุบันค่ะ"

    # Check if customer explicitly cancelled the order or stated this is an exchange/return in recent messages
    recent_user_tail = "\n".join(user_msgs[-3:]).lower()
    if "ไม่ยกเลิก" not in recent_user_tail and any(
        w in recent_user_tail
        for w in (
            "ขอยกเลิก",
            "ยกเลิกก่อน",
            "ยกเลิกค่ะ",
            "ยกเลิกคะ",
            "ยกเลิกครับ",
            "ยกเลิกนะ",
            "ไม่เอาแล้ว",
            "ไม่รับแล้ว",
            "ยังไม่รับค่ะ",
            "ยังไม่รับนะคะ",
            "ถ้าบวกเพิ่มไม่รับ",
            "แพงไปเรายกเลิก",
            "ส่งสินค้าไปเปลี่ยน",
            "ส่งสินึ้าไปเปลี่ยน",
            "ไม่ได้สั่งสินค้าใหม่",
            "แคนเซิล",
        )
    ):
        return False, "ลูกค้าแจ้งขอยกเลิกคำสั่งซื้อหรือเป็นเคสส่งเปลี่ยนสินค้าในแชทค่ะ"

    # Find the index of the latest official Admin Order Summary ("เพจ : ข้าวบุก สุขใจ ... จัดส่ง : ...")
    last_summary_idx = -1
    for i, m in enumerate(msgs):
        c = m.get("content") or ""
        if ("เพจ :" in c or "เพจ:" in c) and "จัดส่ง" in c:
            last_summary_idx = i

    question_rules = [
        (
            "payment_method",
            r"(สะดวกชำระแบบโอนเงินหรือแบบเก็บปลายทาง|สะดวกแบบโอนหรือเก็บปลายทาง|สะดวกโอนหรือปลายทาง|รับแบบโอนหรือปลายทาง|สะดวกชำระแบบไหน|สะดวกชำระช่องทางไหน)",
            "ร้านถามวิธีชำระเงิน (โอน/ปลายทาง) แต่ลูกค้ายังไม่ได้ตอบยืนยันค่ะ",
        ),
        (
            "product_choice",
            r"(สนใจรับขนาดไหน|สนใจโปรไหน|รับชุดไหนดีคะ|รับขนาดไหนดีคะ|รับกี่ถุงดีคะ|รับกี่ซองดีคะ)",
            "ร้านถามขนาด/โปรโมชั่นที่ต้องการ แต่ลูกค้ายังไม่ได้ตอบเลือกสินค้าค่ะ",
        ),
        (
            "address_request",
            r"(ขอทราบชื่อ.*ที่อยู่|แจ้งชื่อ.*ที่อยู่|รบกวนขอชื่อ.*ที่อยู่|รบกวนขอรหัสไปรษณีย์|ขอเบอร์โทร)",
            "ร้านขอชื่อ-ที่อยู่หรือเบอร์โทรเพิ่มเติม แต่ลูกค้ายังไม่ได้ตอบกลับค่ะ",
        ),
        (
            "final_confirm",
            r"(พิมพ์คำว่า\s*[\"']?ยืนยัน|รบกวนคอนเฟิร์ม|ยืนยันรับยอดปลายทาง)",
            "ร้านขอให้ลูกค้าคอนเฟิร์มคำสั่งซื้อ แต่ลูกค้ายังไม่ได้ตอบยืนยันค่ะ",
        ),
    ]

    for i in range(len(msgs) - 1, last_summary_idx, -1):
        m = msgs[i]
        if m.get("role") == "user":
            continue
        admin_txt = m.get("content") or ""
        for q_type, pat, fail_msg in question_rules:
            if re.search(pat, admin_txt):
                # Check customer replies after this question
                replies_after = [
                    r.get("content", "").strip()
                    for r in msgs[i + 1 :]
                    if r.get("role") == "user" and r.get("content", "").strip()
                ]
                if not replies_after and not (q_type == "payment_method" and has_verified_slip):
                    snippet = re.sub(r"\s+", " ", admin_txt).strip()[:80]
                    return False, f"{fail_msg} (คำถามล่าสุด: \"{snippet}\")"
                joined_replies = "\n".join(replies_after)
                if q_type == "payment_method" and not has_verified_slip:
                    if not re.search(
                        r"(โอน|ปลายทาง|cod|เก็บเงิน|สลิป|\[IMAGE:|\b0[689]\d{8}\b)",
                        joined_replies,
                        re.I,
                    ):
                        return False, fail_msg
                elif q_type == "final_confirm" and not has_verified_slip:
                    if not re.search(
                        r"(ยืนยัน|คอนเฟิร์ม|confirm|ตกลง|โอเค|ok|ถูกต้อง|ตามนี้|ค่ะ|ครับ|ส่งเลย|รับค่ะ)",
                        joined_replies,
                        re.I,
                    ):
                        return False, fail_msg
                break

    return True, "ลูกค้าตอบคำถามและยืนยันข้อมูลครบถ้วนแล้วค่ะ"


def extract_order_from_session(psid: str) -> dict[str, Any]:
    """Automatically extract SKU, price, shipping, COD/Transfer, recipient address, slip URL, and dialogue audit from session history."""
    with SessionLocal() as db:
        session = db.get(UserSession, psid)
        if not session:
            return {"valid": False, "reason": "ไม่พบข้อมูลเซสชันลูกค้าค่ะ"}
        customer_name = session.customer_name
        external_user_id = session.external_user_id
        brand_id = session.brand_id
        platform = session.platform
        notes = session.notes or ""

    local_msgs = get_full_messages(psid, limit=40)
    fb_slip_url = ""
    msgs: list[dict[str, str]] = []

    if platform == "facebook" and external_user_id and not external_user_id.startswith("FB_"):
        fb_msgs, fb_slip_url = _fetch_fb_thread_messages_and_slip(external_user_id, brand_id=brand_id)
        if fb_msgs:
            # Use the current-inquiry-sliced FB thread as authoritative so old orders from weeks ago never leak in
            msgs = list(fb_msgs)

    if not msgs:
        # Slice local_msgs to the latest inquiry boundary marker
        start_idx = 0
        boundary_markers = ("ตอบกลับโฆษณา", "กำลังตอบกลับความคิดเห็น", "เริ่มต้นใช้งาน")
        for idx, m in enumerate(local_msgs):
            if idx > 0 and any(bm in (m.get("content") or "") for bm in boundary_markers):
                start_idx = idx
        msgs = local_msgs[start_idx:]

    full_text = "\n".join(m["content"] for m in msgs if m.get("content"))
    user_only_text = "\n".join(m["content"] for m in msgs if m.get("role") == "user" and m.get("content"))

    # 1. Check if there is an explicit Admin Order Summary block in the current inquiry
    admin_summaries = [
        (idx, m["content"])
        for idx, m in enumerate(msgs)
        if ("เพจ :" in m["content"] or "เพจ:" in m["content"]) and "จัดส่ง" in m["content"]
    ]
    last_summary_idx = admin_summaries[-1][0] if admin_summaries else -1
    latest_summary = admin_summaries[-1][1] if admin_summaries else ""

    # 2. Extract phone number (supports 08xxxxxxxx, 08x-xxx-xxxx, and +66936179424)
    phone = ""
    phone_pattern = r"(?:\+66\s*0?|\b0)[689]\d[\s\-]?\d{3}[\s\-]?\d{4}"
    phone_search_target = latest_summary if latest_summary else full_text
    phone_matches = re.findall(phone_pattern, phone_search_target)
    if not phone_matches and latest_summary:
        phone_matches = re.findall(phone_pattern, full_text)
    if phone_matches:
        phone = normalize_thai_phone(phone_matches[-1])

    # 3. Extract raw_address and run recognition for preview/audit
    raw_address = ""
    if latest_summary:
        am = re.search(r"จัดส่ง\s*:\s*(.+)", latest_summary, flags=re.DOTALL)
        if am:
            raw_address = am.group(1).strip()
            raw_address = re.sub(r"#BUY\d+.*$", "", raw_address, flags=re.DOTALL).strip()
    if not raw_address:
        for m in reversed(msgs):
            if m["role"] == "user":
                c = m["content"]
                if re.search(r"\b\d{5}\b", c) or re.search(r"0[689]\d{8}", re.sub(r"\D", "", c)):
                    raw_address = c.strip()
                    break
    if not raw_address:
        rec_m = re.findall(r"ผู้รับ:\s*([^\n]+)\n+•\s*ที่อยู่:\s*([^\n]+)", full_text)
        if rec_m:
            raw_address = f"{rec_m[-1][0]} {rec_m[-1][1]}"

    parsed_address: dict[str, str] = {}
    if raw_address:
        try:
            rec_addr = recognize_and_clean_address(raw_address, explicit_phone=phone)
            parsed_address = {
                "receiver_name": rec_addr.get("receiverFirstName", ""),
                "mobile": rec_addr.get("receiverMobile", ""),
                "state": rec_addr.get("receiverProvince", ""),
                "city": rec_addr.get("receiverCity", ""),
                "district": rec_addr.get("receiverDistrict", ""),
                "post_code": rec_addr.get("receiverZip", ""),
                "detail": rec_addr.get("receiverAddress", ""),
            }
        except Exception as exc:
            logger.warning("Address recognition preview failed for %s: %s", psid, exc)

    # 4. Extract & verify slip image URL
    slip_image_url = fb_slip_url
    last_slip_idx = -1
    for idx in range(len(msgs) - 1, -1, -1):
        if msgs[idx]["role"] == "user" and "[IMAGE:" in msgs[idx]["content"]:
            last_slip_idx = idx
            break
    if not slip_image_url:
        pay_ctx_idx = -1
        for idx, m in enumerate(msgs):
            if m["role"] != "user" and re.search(
                r"(304-407545-5|3044075455|ดิจิสท์|เลขบัญชี|ยอดชำระ|โอนแล้วแจ้งสลิป|ยอดโอน)", m["content"]
            ):
                pay_ctx_idx = idx
                break
        for idx in range(len(msgs) - 1, -1, -1):
            m = msgs[idx]
            if m["role"] == "user" and "[IMAGE:" in m["content"]:
                if pay_ctx_idx != -1 and idx < pay_ctx_idx and idx < max(1, len(msgs) - 6):
                    continue
                im = re.search(r"\[IMAGE:(https?://[^\]]+)\]", m["content"])
                if im:
                    candidate_url = im.group(1)
                    ok, _ = verify_image_is_payment_slip(image_url=candidate_url)
                    if ok:
                        slip_image_url = candidate_url
                        last_slip_idx = idx
                        break

    # If the admin's final summary AFTER the customer's image explicitly states "ชำระเงิน : ปลายทาง"
    # and the customer never claimed to transfer money, that earlier image was a promo/chat screenshot, not a slip!
    if (
        slip_image_url
        and latest_summary
        and last_summary_idx > last_slip_idx
        and re.search(r"ชำระเงิน\s*:\s*ปลายทาง", latest_summary)
        and not re.search(r"(โอนแล้ว|สลิป|ส่งการชำระเงินจำนวน)", user_only_text, re.I)
    ):
        slip_image_url = ""

    # 5. Audit Dialogue Completion ("ตรวจว่าลูกค้าตอบประโยคคำถามของเราจนครบแล้วจริง ๆ")
    dialogue_complete, dialogue_reason = check_dialogue_completion(msgs, has_verified_slip=bool(slip_image_url))

    # 6. Determine COD vs Transfer with strict confirmation check
    # CRITICAL RULE: If a verified payment slip (`slip_image_url`) exists in the current inquiry,
    # ALWAYS treat the order as Bank Transfer (`is_cod = False`), even if an earlier message/summary assumed COD!
    is_cod: bool | None = None
    cod_confirmed = False
    transfer_confirmed = False

    if slip_image_url or "ส่งการชำระเงินจำนวน" in full_text:
        is_cod = False
        transfer_confirmed = True
    elif latest_summary:
        pay_m = re.search(r"ชำระเงิน\s*:\s*([^\n|]+)", latest_summary)
        if pay_m:
            pay_txt = pay_m.group(1)
            if "ปลายทาง" in pay_txt or "COD" in pay_txt.upper():
                is_cod = True
                cod_confirmed = True
            elif "โอน" in pay_txt:
                is_cod = False
                transfer_confirmed = True

    if is_cod is None:
        # Check if customer explicitly chose COD or Transfer in their messages (NEVER assume COD from address alone!)
        if re.search(r"(โอนค่ะ|โอนครับ|แบบโอน|โอนเงิน|โอนแล้ว|ส่งการชำระเงินจำนวน)", user_only_text, re.I):
            is_cod = False
            transfer_confirmed = True
        elif re.search(r"(เก็บเงินปลายทาง|เก็บปลายทาง|ชำระปลายทาง|ปลายทางค่ะ|ปลายทางครับ|ปลายทางจ้า|แบบปลายทาง|cod)", user_only_text, re.I):
            is_cod = True
            user_tail = "\n".join(m["content"] for m in msgs[-8:] if m["role"] == "user")
            if (
                dialogue_complete
                and (
                    re.search(r"(ยืนยัน|ตกลง|โอเค|ok|ค่ะ|ครับ|ตามนี้|ส่งได้เลย|เก็บปลายทาง|ปลายทาง)", user_tail, re.I)
                    or "#BUY" in full_text
                )
            ):
                cod_confirmed = True

    # 7. Determine SKU, qty, unit_price, freight from current inquiry ONLY (never default to old session SKU)
    sku_id = ""
    qty = 1
    unit_price: float | None = None
    freight = 0.0

    buy_tags = re.findall(r"#BUY(\d+)", full_text)
    total_hint = int(buy_tags[-1]) if buy_tags else 0
    if not total_hint and latest_summary:
        pm = re.search(r"ราคา\s*:\s*(?:[\d\+\s]+=)?\s*(\d+)", latest_summary)
        if pm:
            total_hint = int(pm.group(1))
    if not total_hint and dialogue_complete:
        ym = re.findall(r"ยอด(?:รวมทั้งหมด|ชำระ(?:โอนเงิน|โอน|เก็บปลายทาง)?)\s*:?\s*(?:[\d\+\s]+=)?\s*(\d+)\s*(?:บาท|฿)", full_text)
        if ym:
            total_hint = int(ym[-1])

    # Parse explicit size from latest_summary if available
    if latest_summary:
        size_m = re.search(r"ขนาด\s*:\s*([^\n|]+)", latest_summary, re.I)
        if size_m:
            sz = re.sub(r"\s+", "", size_m.group(1).lower())
            if "3kg" in sz or "3แถม3" in sz:
                sku_id, qty, unit_price = "BSJ1KG3_60G3", 1, 1299.0
                freight = float(max(0, total_hint - 1299)) if total_hint >= 1299 else 0.0
            elif "2kg" in sz or "2แถม2" in sz:
                sku_id, qty, unit_price = "BSJ1KG2_60G2", 1, 899.0
                freight = float(max(0, total_hint - 899)) if total_hint >= 899 else 0.0
            elif re.search(r"60g(\d+)(?:ถุง|ซอง|ชอง)", sz):
                n_bags = int(re.search(r"60g(\d+)(?:ถุง|ซอง|ชอง)", sz).group(1))
                if n_bags == 20:
                    sku_id, qty, unit_price = "BSJ60G20", 1, 720.0
                    freight = float(max(0, total_hint - 720)) if total_hint >= 720 else 0.0
                elif n_bags == 15:
                    sku_id, qty, unit_price = "BSJ60G15", 1, 555.0
                    freight = float(max(0, total_hint - 555)) if total_hint >= 555 else 0.0
                elif n_bags == 10:
                    sku_id, qty, unit_price = "BSJ60G10", 1, 390.0
                    freight = float(max(0, total_hint - 390)) if total_hint >= 390 else 0.0
                elif n_bags == 30:
                    sku_id, qty, unit_price = "BSJ60G10", 3, 370.0
                    freight = float(max(0, total_hint - 1110)) if total_hint >= 1110 else 0.0
                elif n_bags == 5:
                    sku_id, qty, unit_price = "BSJ60G5", 1, (195.0 if total_hint in (195, 225) else 199.0)
                    freight = 30.0 if total_hint == 225 else 0.0
                elif n_bags == 3:
                    sku_id, qty, unit_price, freight = "BSJ60G3", 1, float(total_hint or 140), 0.0
                else:
                    sku_id, qty, unit_price = "BSJ60G1", n_bags, 39.0
                    freight = float(max(0, total_hint - 39 * n_bags)) if total_hint >= 39 * n_bags else 0.0
            elif "1kg" in sz:
                m1k = re.search(r"1kg(\d+)(?:ถุง|ซอง)", sz)
                n1k = int(m1k.group(1)) if m1k else 1
                sku_id, qty, unit_price = "BSJ1KG1", n1k, 459.0
                freight = float(max(0, total_hint - 459 * n1k)) if total_hint >= 459 * n1k else 0.0
            elif "500g" in sz:
                m500 = re.search(r"500g(\d+)(?:ถุง|ซอง)", sz)
                n500 = int(m500.group(1)) if m500 else 1
                sku_id, qty, unit_price = "BSJ500G1", n500, 239.0
                freight = float(max(0, total_hint - 239 * n500)) if total_hint >= 239 * n500 else 0.0

    if not sku_id and total_hint:
        if total_hint == 225:
            sku_id, qty, unit_price, freight = "BSJ60G5", 1, 195.0, 30.0
        elif total_hint in (195, 199):
            sku_id, qty, unit_price, freight = "BSJ60G5", 1, float(total_hint), 0.0
        elif total_hint == 239:
            sku_id, qty, unit_price, freight = "BSJ500G1", 1, 239.0, 0.0
        elif total_hint == 269:
            sku_id, qty, unit_price, freight = "BSJ500G1", 1, 239.0, 30.0
        elif total_hint == 309:
            sku_id, qty, unit_price, freight, is_cod, cod_confirmed = "BSJ500G1", 1, 239.0, 70.0, True, True
        elif total_hint == 390:
            sku_id, qty, unit_price, freight = "BSJ60G10", 1, 390.0, 0.0
        elif total_hint == 420:
            sku_id, qty, unit_price, freight = "BSJ60G10", 1, 390.0, 30.0
        elif total_hint == 459:
            sku_id, qty, unit_price, freight = "BSJ1KG1", 1, 459.0, 0.0
        elif total_hint == 499:
            sku_id, qty, unit_price, freight, is_cod, cod_confirmed = "BSJ1KG1", 1, 459.0, 40.0, True, True
        elif total_hint == 529:
            sku_id, qty, unit_price, freight, is_cod, cod_confirmed = "BSJ1KG1", 1, 459.0, 70.0, True, True
        elif total_hint == 555:
            sku_id, qty, unit_price, freight = "BSJ60G15", 1, 555.0, 0.0
        elif total_hint == 595:
            sku_id, qty, unit_price, freight, is_cod, cod_confirmed = "BSJ60G15", 1, 555.0, 40.0, True, True
        elif total_hint in (720, 580):
            sku_id, qty, unit_price, freight = "BSJ60G20", 1, float(total_hint), 0.0
        elif total_hint == 760:
            sku_id, qty, unit_price, freight, is_cod, cod_confirmed = "BSJ60G20", 1, 720.0, 40.0, True, True
        elif total_hint == 899:
            sku_id, qty, unit_price, freight = "BSJ1KG2_60G2", 1, 899.0, 0.0
        elif total_hint in (939, 969):
            sku_id, qty, unit_price, freight, is_cod, cod_confirmed = "BSJ1KG2_60G2", 1, 899.0, float(total_hint - 899), True, True
        elif total_hint == 1110:
            sku_id, qty, unit_price, freight = "BSJ60G10", 3, 370.0, 0.0
        elif total_hint == 1150:
            sku_id, qty, unit_price, freight, is_cod, cod_confirmed = "BSJ60G10", 3, 370.0, 40.0, True, True
        elif total_hint == 1299:
            sku_id, qty, unit_price, freight = "BSJ1KG3_60G3", 1, 1299.0, 0.0
        elif total_hint in (1339, 1369):
            sku_id, qty, unit_price, freight, is_cod, cod_confirmed = "BSJ1KG3_60G3", 1, 1299.0, float(total_hint - 1299), True, True

    # 8. Cross-check customer's requested bag quantity against extracted SKU
    sku_matches_chat = True
    sku_mismatch_reason = ""
    if not latest_summary:
        # Check if customer asked for a specific number of small bags (e.g., 30ชอง, 32ซอง, 10ถุง)
        req_bag_matches = re.findall(r"\b(\d{1,2})\s*(?:ซอง|ชอง|ถุง)\b", user_only_text.lower())
        if req_bag_matches and "1 ก" not in user_only_text.lower() and "1kg" not in user_only_text.lower():
            req_bags = int(req_bag_matches[-1])
            bag_mult = {"BSJ60G20": 20, "BSJ60G15": 15, "BSJ60G10": 10, "BSJ60G5": 5, "BSJ60G3": 3, "BSJ60G1": 1}.get(sku_id, 0)
            eff_bags = bag_mult * int(qty)
            if req_bags >= 3 and eff_bags != req_bags:
                sku_matches_chat = False
                sku_mismatch_reason = f"ลูกค้าสั่ง {req_bags} ซอง/ถุง แต่ยังไม่มีสรุปยอดที่ตรงกันในแชท (SKU ปัจจุบัน: {sku_id or 'ไม่ระบุ'})"

    sku_meta = KNOWN_SKUS.get(sku_id, {})
    effective_unit_price = float(unit_price if unit_price is not None else sku_meta.get("price", 0.0))
    total_amount = round(effective_unit_price * int(qty) + float(freight), 2) if sku_id else 0.0
    item_name = sku_meta.get("propertyShortName") or sku_meta.get("name") or sku_id or "ยังไม่ระบุสินค้า"
    payment_label = (
        "เก็บเงินปลายทาง (COD)"
        if is_cod is True
        else ("โอนเงิน (SCB 304-407545-5)" if is_cod is False else "ยังไม่ระบุวิธีชำระเงิน")
    )
    remark_tag = f" (#BUY{int(total_amount)})" if total_amount > 0 else ""

    has_fb_payment_record = ("ส่งการชำระเงินจำนวน" in full_text) or ("ทำเครื่องหมายคำสั่งซื้อว่าชำระเงินแล้ว" in full_text)
    base_info: dict[str, Any] = {
        "psid": psid,
        "customer_name": customer_name,
        "phone": phone,
        "raw_address": raw_address,
        "parsed_address": parsed_address,
        "sku_id": sku_id,
        "item_name": item_name,
        "qty": qty,
        "unit_price": unit_price,
        "freight": freight,
        "total_amount": total_amount,
        "is_cod": bool(is_cod),
        "payment_label": payment_label,
        "customer_confirmed_cod": cod_confirmed,
        "has_slip": bool(slip_image_url),
        "has_admin_buy_summary": bool(has_fb_payment_record),
        "slip_url": slip_image_url,
        "slip_image_url": slip_image_url,
        "dialogue_complete": dialogue_complete,
        "dialogue_reason": dialogue_reason,
        "sku_matches_chat": sku_matches_chat,
        "sku_mismatch_reason": sku_mismatch_reason,
        "seller_remark": f"FB: {customer_name}{remark_tag}",
        "already_tagged_in_notes": "[JST ERP:" in notes,
    }

    if not dialogue_complete:
        return {**base_info, "valid": False, "reason": dialogue_reason}
    if not sku_matches_chat:
        return {**base_info, "valid": False, "reason": sku_mismatch_reason}
    if not sku_id or total_amount <= 0:
        return {**base_info, "valid": False, "reason": "ยังไม่พบสรุปยอดสินค้าและราคาที่ยืนยันแล้วในรอบการสนทนาปัจจุบันค่ะ"}
    if not phone:
        return {**base_info, "valid": False, "reason": "ยังไม่พบเบอร์โทรศัพท์ 10 หลักของลูกค้าในแชทปัจจุบันค่ะ"}
    if is_cod is None:
        return {
            **base_info,
            "valid": False,
            "reason": "ยังไม่ชัดเจนว่าเป็นออเดอร์โอนเงินหรือเก็บเงินปลายทาง (COD) ต้องคอนเฟิร์มกับลูกค้าก่อนค่ะ",
        }
    if not raw_address:
        return {**base_info, "valid": False, "reason": "ยังไม่พบที่อยู่จัดส่งของลูกค้าในแชทปัจจุบันค่ะ"}
    if is_cod and not cod_confirmed:
        return {
            **base_info,
            "valid": False,
            "reason": "ออเดอร์เก็บเงินปลายทาง (COD) ยังไม่ได้รับการคอนเฟิร์มขั้นสุดท้ายจากลูกค้าค่ะ",
        }
    has_fb_payment_record = ("ส่งการชำระเงินจำนวน" in full_text) or ("ทำเครื่องหมายคำสั่งซื้อว่าชำระเงินแล้ว" in full_text)
    if not is_cod and not slip_image_url and not has_fb_payment_record:
        return {
            **base_info,
            "valid": False,
            "reason": "ออเดอร์โอนเงินแต่ยังไม่มีสลิปโอนเงินจริงที่ตรวจสอบแล้วค่ะ (ห้ามส่งเข้า JST ERP จนกว่าลูกค้าจะส่งสลิปจริง)",
        }

    return {**base_info, "valid": True, "reason": "ok"}


def sync_session_to_jst(
    psid: str,
    overrides: dict[str, Any] | None = None,
    force_create: bool = False,
) -> dict[str, Any]:
    """Run Layer-2 Pre-JST Audit, extract order from session (with optional UI overrides), check duplicate in JST, and create order."""
    from . import audit as _audit_mod
    audit_res = _audit_mod.audit_session_for_jst(psid)
    if not audit_res.get("ready_for_jst") and not overrides:
        issues_str = " / ".join(audit_res.get("issues") or [])
        return {
            "status": "error",
            "message": issues_str or "ข้อมูลออเดอร์ยังไม่ผ่านการตรวจสอบ Audit ก่อนส่งเข้า JST ERP ค่ะ",
            "audit": audit_res,
        }

    extracted = extract_order_from_session(psid)
    if not extracted.get("valid") and not overrides:
        return {"status": "error", "message": extracted.get("reason", "ข้อมูลออเดอร์ไม่ครบถ้วนค่ะ"), "audit": audit_res}

    data = {**extracted, **(overrides or {})}
    res = create_order_in_jst(
        raw_address=data.get("raw_address", ""),
        sku_id=data.get("sku_id", "BSJ1KG1"),
        qty=int(data.get("qty") or 1),
        custom_unit_price=data.get("unit_price"),
        freight=float(data.get("freight") or 0.0),
        is_cod=bool(data.get("is_cod")),
        slip_image_url=data.get("slip_image_url", ""),
        explicit_name=data.get("explicit_name", ""),
        explicit_phone=data.get("phone", ""),
        explicit_address_fields=data.get("explicit_address_fields"),
        seller_remark=data.get("seller_remark", f"FB: {data.get('customer_name', '')}"),
        force_create=force_create,
    )

    if res.get("status") == "created":
        oid = (res.get("created_order") or {}).get("order_id") or (res.get("save_response", {}).get("data") or {}).get("orderId") or ""
        _append_session_note(
            psid,
            f"[JST ERP: สร้างคำสั่งซื้อสำเร็จ #{oid} ({data.get('sku_id')} ยอด {res.get('total_pay')}฿)]",
        )
        from . import database as _db_mod
        _db_mod.update_session_meta(psid, state="completed", is_starred=True)
    elif res.get("status") == "duplicate_skipped":
        existing = (res.get("existing_orders") or [{}])[0]
        oid = existing.get("order_id", "")
        with SessionLocal() as db:
            s = db.get(UserSession, psid)
            if s and f"#{oid}" not in (s.notes or ""):
                _append_session_note(
                    psid,
                    f"[JST ERP: มีในระบบแล้ว #{oid} ({existing.get('order_time', '')})]",
                )
        from . import database as _db_mod
        _db_mod.update_session_meta(psid, state="completed", is_starred=True)

    return res


def sync_all_confirmed_orders_to_jst(days_lookback: int = 2, mark_daily_batch: bool = False) -> dict[str, Any]:
    """Scan all completed orders from the last `days_lookback` days (yesterday's confirmed orders),
    run Layer-1 Pre-Keying Chat Audit & duplicate check against JST ERP, push missing ones,
    and run Layer-2 Post-Keying JST Reconciliation Audit.
    """
    bkk_tz = timezone(timedelta(hours=7))
    now_bkk = datetime.now(bkk_tz)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_lookback)
    with SessionLocal() as db:
        sessions = (
            db.query(UserSession)
            .filter(UserSession.state == "completed", UserSession.last_interaction_time >= cutoff)
            .order_by(UserSession.last_interaction_time.desc())
            .all()
        )
        psids = [s.psid for s in sessions]

    results = {
        "scanned": len(psids),
        "batch_time_bkk": now_bkk.strftime("%Y-%m-%d %H:%M:%S"),
        "created": [],
        "duplicate_skipped": [],
        "incomplete_skipped": [],
        "errors": [],
    }

    for psid in psids:
        try:
            ext = extract_order_from_session(psid)
            if not ext.get("valid"):
                results["incomplete_skipped"].append({"psid": psid, "reason": ext.get("reason")})
                continue
            res = sync_session_to_jst(psid)
            st = res.get("status")
            item_summary = {
                "psid": psid,
                "customer_name": ext.get("customer_name"),
                "phone": ext.get("phone"),
                "sku_id": ext.get("sku_id"),
                "result": res,
            }
            if st == "created":
                results["created"].append(item_summary)
            elif st == "duplicate_skipped":
                results["duplicate_skipped"].append(item_summary)
            else:
                results["errors"].append(item_summary)
        except Exception as exc:
            logger.error("Error syncing session %s to JST: %s", psid, exc)
            results["errors"].append({"psid": psid, "error": str(exc)})

    try:
        from . import audit as _audit_mod
        results["post_keying_reconcile"] = _audit_mod.audit_jst_orders_against_chat(days_lookback=1, auto_clean=True)
    except Exception as exc:
        logger.warning("Post-keying reconcile audit failed: %s", exc)

    if mark_daily_batch:
        save_daily_sync_state({
            "last_daily_sync_date": now_bkk.strftime("%Y-%m-%d"),
            "last_daily_sync_at": now_bkk.strftime("%Y-%m-%d %H:%M:%S"),
            "last_created_count": len(results["created"]),
            "last_duplicate_skipped_count": len(results["duplicate_skipped"]),
        })

    return results
