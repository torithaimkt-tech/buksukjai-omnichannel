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
JST_SHOP_ID_SHOPEE = 21406080
JST_SHOP_ID_MRBUK = int(os.getenv("JST_SHOP_ID_MRBUK", "0") or 0)
JST_WAREHOUSE_ID = 20421
JST_SALESMAN_ID = "22755436"
JST_LOGISTICS_ID = "59"
JST_LOGISTICS_CODE = "J&T Express TH"
JST_LOGISTICS_NAME = "J&T Express"
JST_SCB_ACCOUNT = "3044075455"
JST_KBANK_MRBUK_ACCOUNT = "9892136243"


def get_shop_id_for_brand(brand_id: str = "buksukjai") -> int:
    """Return the JST ERP ShopId for the given brand_id."""
    if (brand_id or "").strip().lower() == "mrbuk" and JST_SHOP_ID_MRBUK > 0:
        return JST_SHOP_ID_MRBUK
    return JST_SHOP_ID

FRESH_JST_COOKIE = (
    "client_id=8c55bf3e7cb90f3ba27a22ddfdcc3762_91cdae39f749baaed0f1c166d97c4583; "
    "u_login_id=buksukjai%40gmail.com; VID_bcbff8986118=22755436; VP_bcbff8986118=1; "
    "AVID_147792=22755436; _ati=3616590229392; Notice-22755436-176=True; LanguageId=TH; "
    "Notice-22755436-177=True; u_cid=48259fda08a245d3bdee668206972fd0-22755436-9d5a61e0c4e148ddf561a3e4c286ebca; "
    "u_id=22755436; u_name=buksukjai; u_co_id=15749167; u_co_name=Buksukjai; ClientTimeZone=7; "
    ".AspNetCore.GlobalAuthCookie=CfDJ8NUvc5HFTn9EnG_IMr2hg1QbScA67aC19EuEL5g7p0b5o3Z77WhGqyNhCRGy2x5cIemLnSwCLkE9Ni3wXb5fH6zX2-2YneaFuCJ8xN86Noe5nKWgv5OBNBpsnKjgcNcBC4nXsLCIB8LA6KEuVMiSLaxZuSqqcJ3XrpSpcnP2z9vxNeOw6mRa03t4ygcMoQWdK6x3FFQQLNSDhbdFlP9Dt29D-yyuuSaNUx2xJL4s901oXJyCSxg8WuJUDt1KUO_Ouzi3ReFuEV9yUcDOHvgcJetL7tM7fxjrtYbMqLSixOKRzvDsq4xa6me0wZebPHGJoiHkuyUBcDp0dQhXgL9bmEB_Mmte3mckKSZYjmzLdQHEZU5xGOZPoYD74vMGemVyfvy0xE9kb3nEkW-vs3UuSyiDFR5fQv4ENsc0DtglQuwwnz0jZQOsUy6YxDeumf_aXCeBYONN5OLaT0VT40tnFatYtkKQTHHUaKvAWyuybRmG; "
    "VT_bcbff8986118=17; SID_bcbff8986118=4915081157153753597"
)

_EXPIRED_UCIDS = (
    "8925a23804b941b49f52f1c79c1c3b93",
    "ffab80a5bac245c79a723ced80a396a2",
)

_env_jst_cookie = os.getenv("JST_ERP_COOKIE", "").strip()
# Prefer FRESH_JST_COOKIE if env cookie is empty or still holds an expired u_cid
DEFAULT_JST_COOKIE = (
    FRESH_JST_COOKIE
    if (not _env_jst_cookie or any(old_id in _env_jst_cookie for old_id in _EXPIRED_UCIDS))
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
    # Mister Buk (Mr.Buk ข้าวบุกหอมมะลิ) Official SKU Catalog
    "MRBUK60G1": {
        "itemId": "MRBUK60G1",
        "skuId": "MRBUK60G1",
        "name": "มิสเตอร์บุก ข้าวบุกหอมมะลิ ซองพกพา 60 กรัม (1 ซอง)",
        "pic": "",
        "price": 44.0,
        "originPrice": 44.0,
        "propertyShortName": "60 กรัม 1 ซอง",
        "isCombined": False,
        "skuType": "Normal",
    },
    "MRBUK500G1": {
        "itemId": "MRBUK500G1",
        "skuId": "MRBUK500G1",
        "name": "มิสเตอร์บุก ข้าวบุกหอมมะลิ ถุงกลาง 500 กรัม (1 ถุง)",
        "pic": "",
        "price": 249.0,
        "originPrice": 249.0,
        "propertyShortName": "500 กรัม 1 ถุง",
        "isCombined": False,
        "skuType": "Normal",
    },
    "MRBUK1KG1": {
        "itemId": "MRBUK1KG1",
        "skuId": "MRBUK1KG1",
        "name": "มิสเตอร์บุก ข้าวบุกหอมมะลิ ถุงใหญ่ 1 กิโลกรัม (1 ถุง)",
        "pic": "",
        "price": 490.0,
        "originPrice": 490.0,
        "propertyShortName": "1 กิโลกรัม 1 ถุง",
        "isCombined": False,
        "skuType": "Normal",
    },
    "MRBUK60G15": {
        "itemId": "MRBUK60G15",
        "skuId": "MRBUK60G15",
        "name": "มิสเตอร์บุก เซ็ตพกพา 15 มื้อ (60g 15 ซอง)",
        "pic": "",
        "price": 599.0,
        "originPrice": 599.0,
        "propertyShortName": "60 กรัม 15 ซอง",
        "isCombined": True,
        "skuType": "Combine",
    },
    "MRBUK60G30": {
        "itemId": "MRBUK60G30",
        "skuId": "MRBUK60G30",
        "name": "มิสเตอร์บุก เซ็ตพกพา 30 มื้อ (60g 30 ซอง)",
        "pic": "",
        "price": 1190.0,
        "originPrice": 1190.0,
        "propertyShortName": "60 กรัม 30 ซอง",
        "isCombined": True,
        "skuType": "Combine",
    },
    "MRBUK1KG2_60G1": {
        "itemId": "MRBUK1KG2_60G1",
        "skuId": "MRBUK1KG2_60G1",
        "name": "มิสเตอร์บุก เซ็ตคู่ขายดี 41 มื้อ (1kg 2 ถุง + แถมฟรี 60g 1 ซอง)",
        "pic": "",
        "price": 950.0,
        "originPrice": 950.0,
        "propertyShortName": "1kg 2 ถุง + 60g 1 ซอง",
        "isCombined": True,
        "skuType": "Combine",
    },
    "MRBUK1KG5": {
        "itemId": "MRBUK1KG5",
        "skuId": "MRBUK1KG5",
        "name": "มิสเตอร์บุก เซ็ตครอบครัวสุดคุ้ม 5 กก. (1kg 5 ถุง)",
        "pic": "",
        "price": 2390.0,
        "originPrice": 2390.0,
        "propertyShortName": "1 กิโลกรัม 5 ถุง",
        "isCombined": True,
        "skuType": "Combine",
    },
}


def update_cookie_from_response(resp: httpx.Response) -> bool:
    """Capture any Set-Cookie headers returned by JST ERP (such as sliding-expiration
    renewals of `.AspNetCore.GlobalAuthCookie` or `u_cid`) and merge them into `_RUNTIME_COOKIE`.
    """
    global _RUNTIME_COOKIE
    try:
        set_cookies = resp.headers.get_list("set-cookie")
    except Exception:
        set_cookies = []
    if not set_cookies:
        return False

    cookie_map: dict[str, str] = {}
    for part in (_RUNTIME_COOKIE or "").split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            cookie_map[k.strip()] = v.strip()

    updated = False
    for sc in set_cookies:
        first_pair = sc.split(";", 1)[0].strip()
        if "=" in first_pair:
            k, v = first_pair.split("=", 1)
            k, v = k.strip(), v.strip()
            if v and v.lower() != "deleted" and cookie_map.get(k) != v:
                cookie_map[k] = v
                updated = True

    if updated:
        new_cookie_str = "; ".join(f"{k}={v}" for k, v in cookie_map.items())
        _RUNTIME_COOKIE = new_cookie_str
        try:
            save_daily_sync_state({"persisted_cookie": new_cookie_str, "cookie_refreshed_at": datetime.now(timezone(timedelta(hours=7))).isoformat()})
        except Exception:
            pass
    return updated


def check_jst_cookie_health(alert_line_on_expired: bool = True) -> dict[str, Any]:
    """Verify whether the current JST ERP session cookie is still active and valid,
    and automatically capture any sliding-session `Set-Cookie` renewal headers.
    If expired/unauthorized and `alert_line_on_expired` is True, sends an immediate alert
    to the LINE Summary Work Group (with a 6-hour cooldown so it does not spam).
    """
    h = _headers(json_body=True)
    h["Origin"] = "https://asia.jsterp.com"
    h["Referer"] = "https://asia.jsterp.com/Wms/Inventory/SkuInventory"
    try:
        # 1. Sliding session keep-alive ping on Account endpoint AND asia-web Order endpoint
        try:
            auth_resp = httpx.get(
                "https://asia.jsterp.com/Account/Shop/GetAuthorizeData",
                headers=h,
                timeout=10.0,
                follow_redirects=False,
            )
            update_cookie_from_response(auth_resp)
            h["Cookie"] = get_jst_cookie()
            web_h = _headers(json_body=True)
            web_resp = httpx.post(
                "https://asia-web.jsterp.com/MiniShop/Recipient/Address/AddresseeRecognition",
                headers=web_h,
                json={"addressTxt": "กรุงเทพ 10110"},
                timeout=10.0,
                follow_redirects=False,
            )
            update_cookie_from_response(web_resp)
            h["Cookie"] = get_jst_cookie()
            if web_resp.status_code in (301, 302, 401, 403):
                reason = f"HTTP {web_resp.status_code} on asia-web.jsterp.com (u_cid expired)"
                if alert_line_on_expired:
                    from . import daily_sheet_report
                    daily_sheet_report.send_jst_cookie_expired_alert_to_line_groups(reason)
                return {"status": "expired", "reason": reason}
        except Exception:
            pass

        resp = httpx.post(
            "https://asia.jsterp.com/wms/Inventory/GetSkuInventorys",
            headers=h,
            json={
                "RequestModel": {},
                "DataPage": {"pageSize": 10, "pageIndex": 1, "total": 0, "sizes": [10, 50]},
            },
            timeout=12.0,
            follow_redirects=False,
        )
        update_cookie_from_response(resp)
        if resp.status_code in (301, 302, 401, 403):
            reason = f"HTTP {resp.status_code} (Session Redirect/Unauthorized)"
            if alert_line_on_expired:
                from . import daily_sheet_report
                daily_sheet_report.send_jst_cookie_expired_alert_to_line_groups(reason)
            return {"status": "expired", "reason": reason}
        resp.raise_for_status()
        payload = resp.json() or {}
        if payload.get("Success") is False or (payload.get("Code") and int(payload.get("Code") or 0) in (401, 403)):
            reason = str(payload.get("Message") or "JST ERP Session Expired")
            if alert_line_on_expired:
                from . import daily_sheet_report
                daily_sheet_report.send_jst_cookie_expired_alert_to_line_groups(reason)
            return {"status": "expired", "reason": reason}
        return {"status": "ok", "sku_count": len(payload.get("Data") or [])}
    except Exception as exc:
        err_str = str(exc)
        if any(k in err_str.lower() for k in ("401", "403", "login", "unauthorized", "expecting value")):
            if alert_line_on_expired:
                from . import daily_sheet_report
                daily_sheet_report.send_jst_cookie_expired_alert_to_line_groups(err_str)
            return {"status": "expired", "reason": err_str}
        return {"status": "network_warning", "reason": err_str}


def get_jst_cookie() -> str:
    global _RUNTIME_COOKIE
    try:
        st = get_daily_sync_state()
        persisted = str(st.get("persisted_cookie") or "").strip()
        if persisted and not any(old_id in persisted for old_id in _EXPIRED_UCIDS):
            _RUNTIME_COOKIE = persisted
            return _RUNTIME_COOKIE
    except Exception:
        pass
    if not _RUNTIME_COOKIE:
        _RUNTIME_COOKIE = os.getenv("JST_ERP_COOKIE", "").strip()
    return _RUNTIME_COOKIE


def set_jst_cookie(cookie: str) -> None:
    global _RUNTIME_COOKIE
    clean_c = cookie.strip()
    _RUNTIME_COOKIE = clean_c
    try:
        save_daily_sync_state({
            "persisted_cookie": clean_c,
            "cookie_refreshed_at": datetime.now(timezone(timedelta(hours=7))).isoformat(),
        })
    except Exception:
        pass


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
    """Return True only during the 06:00 AM Bangkok hour (06:00–06:59)
    when AUTO_SYNC_ENABLED is True and today's daily batch has not yet run.
    Never fire in the afternoon/evening on server restarts.
    """
    if not AUTO_SYNC_ENABLED:
        return False
    bkk_tz = timezone(timedelta(hours=7))
    now_bkk = datetime.now(bkk_tz)
    if now_bkk.hour != DAILY_BATCH_HOUR_BKK:
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


def check_duplicate_order(phone: str, within_days: int = 7) -> dict[str, Any]:
    """Check JST ERP (`NewQueryOrders`) for any active unshipped order or recently created order matching `phone`."""
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
    update_cookie_from_response(resp)
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
        row_ph = normalize_thai_phone(str(row_dict.get("ReceiverMobileEn") or row_dict.get("ReceiverPhoneEn") or ""))
        if row_ph and len(row_ph) == 10 and row_ph != clean_phone:
            continue
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
            "is_cod": bool(row_dict.get("IsCod")),
            "freight": row_dict.get("Freight") or row_dict.get("PostFee") or 0,
            "skus": row_dict.get("Skus") or [],
            "payment": payment_name,
            "receiver_name": str(row_dict.get("ReceiverName") or "").strip(),
            "receiver_mobile": row_ph or clean_phone,
            "shop_name": str(row_dict.get("ShopName") or "").strip(),
        }
        historical_orders.append(summary)

        # Any unshipped active order is ALWAYS considered an active duplicate;
        # shipped orders within `within_days` (default 3 days) are also treated as recent duplicates.
        if "จัดส่งแล้ว" not in status_display:
            recent_orders.append(summary)
        else:
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


def search_jst_orders_by_receiver_name(receiver_name: str, limit: int = 100) -> list[dict[str, Any]]:
    """Search JST ERP (`NewQueryOrders`) for active/historical orders matching `receiver_name`."""
    clean_name = re.sub(r"^(?:คุณ|นาย|นาง|นางสาว|น\.ส\.|พี่|น้อง)\s*", "", (receiver_name or "").strip()).strip()
    if len(clean_name) < 2:
        return []

    payload = {
        "RequestModel": {
            "SendFrom": "NewQueryOrders",
            "ReceiverName": clean_name,
        },
        "DataPage": {
            "pageSize": limit,
            "pageIndex": 1,
            "total": 0,
            "sizes": [50, 100, 200],
        },
    }
    try:
        resp = httpx.post(
            "https://asia.jsterp.com/OMS/MiniShopOrder/NewQueryOrders",
            headers=_headers(json_body=True),
            json=payload,
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("JST search by receiver_name '%s' failed: %s", clean_name, exc)
        return []

    rows_obj = data.get("Rows") or {}
    cols = rows_obj.get("cols") or []
    raw_rows = rows_obj.get("rows") or []

    matched: list[dict[str, Any]] = []
    name_parts = [p for p in clean_name.lower().split() if len(p) >= 2]

    for r in raw_rows:
        row_dict = dict(zip(cols, r))
        status_display = str(row_dict.get("StatusDisplay") or row_dict.get("SocialStatusDisplay") or "")
        if "ยกเลิก" in status_display or "Cancel" in str(row_dict.get("Status") or ""):
            continue
        r_name = str(row_dict.get("ReceiverName") or "").strip()
        r_name_low = r_name.lower()
        if clean_name.lower() not in r_name_low and not (name_parts and all(p in r_name_low for p in name_parts)):
            continue
        row_ph = normalize_thai_phone(str(row_dict.get("ReceiverMobileEn") or row_dict.get("ReceiverPhoneEn") or ""))
        matched.append(
            {
                "order_id": str(row_dict.get("OrderId") or ""),
                "order_time": str(row_dict.get("OrderTime") or ""),
                "status": status_display,
                "pay_amount": row_dict.get("PayAmount"),
                "freight": row_dict.get("Freight") or row_dict.get("PostFee") or 0,
                "skus": row_dict.get("Skus") or [],
                "payment": str(row_dict.get("Payment") or row_dict.get("SettlementMethodDisplay") or ""),
                "receiver_name": r_name,
                "receiver_mobile": row_ph,
                "shop_name": str(row_dict.get("ShopName") or "").strip(),
            }
        )
    return matched


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
                    if "จัดส่งแล้ว" not in status_disp:
                        try:
                            cancel_orders_in_jst(
                                [oid],
                                f"ยกเลิกอัตโนมัติ: สลิปและออเดอร์ซ้ำกับใบสั่งซื้อ #{dup_oid} ({dup_status}) ค่ะ",
                            )
                            cancelled_oids.add(oid)
                        except Exception as exc:
                            logger.warning("Auto-cancel duplicate slip order %s failed: %s", oid, exc)
                    rejected.append(
                        {
                            "order_id": oid,
                            "reason": f"สลิปซ้ำกับออเดอร์ #{dup_oid} ที่ยังไม่ได้ยกเลิก ({dup_status}) — ยกเลิกใบซ้ำให้อัตโนมัติแล้วค่ะ",
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

    express_fixed = auto_fix_missing_express_orders(all_rows=all_rows)

    return {
        "status": "ok",
        "auto_confirmed_count": len(auto_confirmed),
        "auto_confirmed": auto_confirmed,
        "express_fixed_count": len(express_fixed),
        "express_fixed": express_fixed,
        "rejected_count": len(rejected),
        "rejected": rejected,
    }


JST_EXPRESS_AUTO_ID = "219956"  # J&T Express AutoId in /OMS/Order/GetExpress


def assign_express_and_audit_orders(
    order_ids: list[int | str],
    express_auto_id: str = JST_EXPRESS_AUTO_ID,
    run_audit: bool = True,
) -> dict[str, Any]:
    """Assign courier (default: J&T Express `219956`) via `/OMS/MiniShopOrder/SaveOrderExpress`,
    clear any `ผิดปกติ (ยังไม่ตั้งค่าการขนส่ง)` status, and run `/OMS/Order/Audit` to generate tracking numbers."""
    clean_ids = [str(x).strip() for x in order_ids if str(x).strip().isdigit()]
    if not clean_ids:
        return {"status": "empty", "order_ids": []}

    h = _headers(json_body=True)
    h["Origin"] = "https://asia.jsterp.com"
    h["Referer"] = "https://asia.jsterp.com/OMS/Order/OrderManage"

    exp_res = {}
    norm_res = {}
    aud_res = {}
    try:
        r_exp = httpx.post(
            "https://asia.jsterp.com/OMS/MiniShopOrder/SaveOrderExpress",
            headers=h,
            json={
                "OrderIds": clean_ids,
                "ExpressId": express_auto_id,
                "Calculation": "page",
                "Method": "",
            },
            timeout=20.0,
        )
        exp_res = r_exp.json()
    except Exception as exc:
        logger.warning("SaveOrderExpress warning for %s: %s", clean_ids, exc)

    try:
        r_norm = httpx.post(
            "https://asia.jsterp.com/OMS/Order/ChangeNormal",
            headers=h,
            json={"OrderIds": clean_ids, "QueryRequest": {}},
            timeout=15.0,
        )
        norm_res = r_norm.json()
    except Exception as exc:
        logger.debug("ChangeNormal info for %s: %s", clean_ids, exc)

    if run_audit:
        try:
            r_aud = httpx.post(
                "https://asia.jsterp.com/OMS/Order/Audit",
                headers=h,
                json={"AuditType": "manual", "OrderIds": clean_ids},
                timeout=20.0,
            )
            aud_res = r_aud.json()
        except Exception as exc:
            logger.warning("Order Audit warning for %s: %s", clean_ids, exc)

    return {
        "status": "ok",
        "order_ids": clean_ids,
        "save_express": exp_res,
        "change_normal": norm_res,
        "audit": aud_res,
    }


def auto_fix_missing_express_orders(
    limit: int = 50,
    all_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Find any non-cancelled, non-duplicate ManualOrder stuck in `ยังไม่ตั้งค่าการขนส่ง` (or missing courier)
    and automatically set `J&T Express` + approve it so it moves to `รอตัวแทน / จัดส่งออกจากคลังสินค้า`."""
    if all_rows is None:
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

    # Collect phone numbers that ALREADY have an active shipped or ready-to-ship order in the current list
    # so we NEVER auto-approve a 2nd duplicate order for the same phone!
    active_phones: dict[str, list[dict[str, Any]]] = {}
    for d in all_rows:
        st_disp = str(d.get("StatusDisplay") or "")
        if "ยกเลิก" in st_disp or "Cancel" in str(d.get("Status") or ""):
            continue
        ph = normalize_thai_phone(str(d.get("ReceiverMobileEn") or ""))
        if ph and len(ph) == 10:
            active_phones.setdefault(ph, []).append(d)

    # Auto-cancel unshipped duplicates where the same 10-digit phone already has a shipped order with the same amount
    cancelled_dup_ids: set[str] = set()
    for ph, ph_orders in active_phones.items():
        if len(ph_orders) <= 1:
            continue
        shipped_list = [x for x in ph_orders if "จัดส่งแล้ว" in str(x.get("StatusDisplay") or "")]
        unshipped_list = [
            x
            for x in ph_orders
            if "จัดส่งแล้ว" not in str(x.get("StatusDisplay") or "")
            and str(x.get("SaveType") or "") == "ManualOrder"
        ]
        if shipped_list and unshipped_list:
            shipped_amts = {float(x.get("PayAmount") or 0.0) for x in shipped_list}
            for u_ord in unshipped_list:
                u_oid = str(u_ord.get("OrderId") or "").strip()
                u_amt = float(u_ord.get("PayAmount") or 0.0)
                if u_oid and any(abs(u_amt - s_amt) < 1.0 for s_amt in shipped_amts):
                    try:
                        cancel_orders_in_jst(
                            [u_oid],
                            f"ป้องกันการส่งซ้ำอัตโนมัติ: เบอร์ {ph} มีออเดอร์ยอด {u_amt:.0f}฿ ที่จัดส่งไปแล้วค่ะ",
                        )
                        cancelled_dup_ids.add(u_oid)
                    except Exception as exc:
                        logger.warning("Failed to auto-cancel unshipped duplicate %s: %s", u_oid, exc)

    fixed_list: list[dict[str, Any]] = []
    approved_phones_in_pass: set[str] = {
        ph
        for ph, ph_orders in active_phones.items()
        if any(
            "จัดส่งแล้ว" in str(x.get("StatusDisplay") or "")
            or str(x.get("LogisticsTrackingNumber") or "").strip()
            for x in ph_orders
        )
    }

    for d in all_rows:
        oid = str(d.get("OrderId") or "").strip()
        if not oid or oid in cancelled_dup_ids or d.get("SaveType") != "ManualOrder":
            continue
        st_disp = str(d.get("StatusDisplay") or "")
        if "ยกเลิก" in st_disp or "Cancel" in str(d.get("Status") or "") or "จัดส่งแล้ว" in st_disp:
            continue

        st_obj = d.get("Status") if isinstance(d.get("Status"), dict) else {}
        q_status = str((st_obj or {}).get("QuestionStatus") or "")
        co_code = str(d.get("LogisticsCompanyCode") or "").strip()
        prov = str(d.get("LogisticProvider") or "").strip()

        needs_express = (
            "ยังไม่ตั้งค่าการขนส่ง" in q_status
            or not co_code
            or prov == "NotNeed"
        )
        if not needs_express:
            continue

        ph = normalize_thai_phone(str(d.get("ReceiverMobileEn") or ""))
        if ph and ph in approved_phones_in_pass:
            # Skip duplicate of an already-shipped or already-assigned order so warehouse doesn't ship twice!
            continue
        if ph:
            approved_phones_in_pass.add(ph)

        # Ironclad Anti-Free-Shipping Check (Round 2):
        # 1) PayAmount must ALWAYS be > 0
        # 2) If IsCod is False (Bank Transfer, so courier collects 0 THB at door), NEVER run_audit unless payment is 100% confirmed
        pay_amt_val = float(d.get("PayAmount") or 0.0)
        st_code = str(d.get("StatusCode") or "")
        mach_audit = str(d.get("MachineAuditStatus") or "")
        is_unconfirmed_transfer = (not bool(d.get("IsCod"))) and (
            "รอการชำระเงิน" in st_disp
            or "รอชำระเงิน" in st_disp
            or "รอตรวจสอบ" in st_disp
            or "WaitPay" in st_code
            or "WaitConfirm" in st_code
            or mach_audit == "Fail"
        )
        can_audit = (pay_amt_val > 0) and (not is_unconfirmed_transfer)
        res = assign_express_and_audit_orders([oid], run_audit=can_audit)
        fixed_list.append(
            {
                "order_id": oid,
                "receiver_name": d.get("ReceiverName"),
                "phone": ph,
                "audited": can_audit,
                "result": res,
            }
        )

    return fixed_list


def recognize_and_clean_address(
    raw_address: str,
    explicit_name: str = "",
    explicit_phone: str = "",
) -> dict[str, str]:
    """Use JST ERP's `AddresseeRecognition` API and clean up Thai name vs street address."""
    cleaned_input = (raw_address or "").strip()
    # Normalize common Thai typos and strip conversational prefixes before recognition
    cleaned_input = (
        cleaned_input.replace("แขลง", "แขวง")
        .replace("สุราษธานี", "สุราษฎร์ธานี")
        .replace("ศรีษะเกษ", "ศรีสะเกษ")
    )
    cleaned_input = re.sub(
        r"(?:^|\n|\|)\s*(?:จัดส่งที่นี่นะครับ|จัดส่งที่นี่นะคะ|จัดส่งที่นี่|ที่อยู่จัดส่ง|ส่งที่|ชื่อ-ที่อยู่|ชื่อผู้รับ|ผู้รับ|ชื่อ|ที่อยู่|เบอร์โทรศัพท์|เบอร์โทร|เบอร์|โทร\.?|มือถือ|t\.|tel\.?)\s*[:：]?\s*",
        " ",
        cleaned_input,
        flags=re.I,
    )
    cleaned_input = re.sub(r"\b(?:โทร\.?|เบอร์โทร|เบอร์|มือถือ|t\.|tel\.?)\s*[:：]?\s*(?=0|\+66)", " ", cleaned_input, flags=re.I)

    # Insert spaces around unspaced Thai administrative markers (e.g. "39หมู่6ตำบลสมอทองอำเภอท่าชนะจังหวัดสุราษฎร์ธานี84170")
    cleaned_input = re.sub(r"(?<=[ก-๙\d])(?=(?:ตำบล|อำเภอ|จังหวัด|แขวง|เขต|หมู่ที่|หมู่\s*\d))", " ", cleaned_input)
    cleaned_input = re.sub(r"(?<=[ก-๙])(?=\d{5}\b)", " ", cleaned_input)
    cleaned_input = re.sub(r"(?<=[ก-๙])(?=\d+/\d+|\b\d+\s*หมู่)", " ", cleaned_input)

    # Extract leading recipient name if phone number appears at the very start before the name (e.g. "0807669580\nนายเชาวลิต มะหะมะ\n...")
    leading_name_hint = ""
    m_lead_ph = re.match(
        r"^\s*((?:\+66\s*0?|0)[689]\d[\s\-]?\d{3}[\s\-]?\d{4})\s+([ก-๙a-zA-Z][ก-๙a-zA-Z\s\.]{2,35}?)(?=\n|\s+(?:โครงการ|หมู่บ้าน|อาคาร|คอนโด|บริษัท|ร้าน|บ้านเลขที่|ตู้\s*ปณ|\d+))",
        cleaned_input,
    )
    if m_lead_ph:
        leading_name_hint = m_lead_ph.group(2).strip()
        # Move leading phone after the address so AddresseeRecognition parses the name cleanly
        cleaned_input = f"{leading_name_hint} {cleaned_input[m_lead_ph.end():].strip()} {m_lead_ph.group(1)}"

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

    rec: dict[str, Any] = {}
    try:
        resp = httpx.post(
            "https://asia-web.jsterp.com/MiniShop/Recipient/Address/AddresseeRecognition",
            headers=_headers(json_body=True),
            json={"addressTxt": cleaned_input},
            timeout=15.0,
        )
        if resp.status_code == 200:
            rec = (resp.json() or {}).get("data") or {}
    except Exception as exc:
        logger.warning("AddresseeRecognition fallback to local regex parser: %s", exc)

    province = (rec.get("receiverProvince") or "").strip()
    city = (rec.get("receiverCity") or "").strip()
    district = (rec.get("receiverDistrict") or "").strip()
    zip_code = (rec.get("receiverZip") or "").strip()
    mobile = normalize_thai_phone(explicit_phone or rec.get("receiverMobile") or "")

    rec_name = (rec.get("receiverFirstName") or "").strip()
    rec_detail = (rec.get("receiverAddress") or "").strip()
    if not rec_name and not rec_detail:
        lines_in = [ln.strip() for ln in (raw_address or "").splitlines() if ln.strip()]
        if lines_in and not re.search(r"\d", lines_in[0]):
            rec_name = lines_in[0]
            rec_detail = " ".join(lines_in[1:])
        else:
            rec_detail = cleaned_input
    if not province and ("กรุงเทพ" in cleaned_input or "กทม" in cleaned_input):
        province = "กรุงเทพ"

    # Fallback subdistrict/city/province extraction if AddresseeRecognition missed them
    if not district:
        m_sub = re.search(r"(?:ตำบล|ต\.|แขวง)\s*([ก-๙]{2,25})", cleaned_input)
        if m_sub:
            district = m_sub.group(1).strip()
        elif "คูบางหลวง" in cleaned_input:
            district = "คูบางหลวง"
    if not city:
        m_city = re.search(r"(?:อำเภอ|อ\.|เขต)\s*([ก-๙]{2,25})", cleaned_input)
        if m_city:
            city = m_city.group(1).strip()
    if not province:
        m_prov = re.search(r"(?:จังหวัด|จ\.)\s*([ก-๙]{2,25})", cleaned_input)
        if m_prov:
            province = m_prov.group(1).strip()
    if not zip_code:
        m_zip = re.search(r"\b(\d{5})\b", cleaned_input)
        if m_zip:
            zip_code = m_zip.group(1)

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
    if not first_name and leading_name_hint:
        first_name = leading_name_hint
    if not first_name and trailing_name_hint:
        first_name = trailing_name_hint
        rec_detail = re.sub(re.escape(trailing_name_hint) + r"\s*$", "", rec_detail).strip()
    if not first_name:
        m_title = re.search(r"((?:นาย|นางสาว|นาง|น\.ส\.|คุณ|ครู|หมอ)\s*[ก-๙]+\s+[ก-๙]+)", rec_detail)
        if m_title:
            first_name = m_title.group(1).strip()

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
    within_days_Check: int = 7,
    force_create: bool = False,
    extra_items: list[dict[str, Any]] | None = None,
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
    primary_item_amount = round(unit_price * int(qty), 2)

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
            "amount": primary_item_amount,
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
    goods_amount = primary_item_amount
    for idx_ex, ex in enumerate(extra_items or [], start=1):
        ex_sku_id = str(ex.get("sku_id") or "").strip()
        ex_meta = KNOWN_SKUS.get(ex_sku_id)
        if not ex_meta:
            continue
        ex_qty = int(ex.get("qty") or 1)
        ex_unit = float(ex.get("unit_price") if ex.get("unit_price") is not None else ex_meta["price"])
        ex_orig = float(ex_meta.get("originPrice", ex_unit))
        ex_amt = round(ex_unit * ex_qty, 2)
        goods_amount = round(goods_amount + ex_amt, 2)
        order_item.append(
            {
                "innerOrderItemId": "",
                "orderItemId": "",
                "skuId": ex_meta["skuId"],
                "itemId": ex_meta["itemId"],
                "pic": ex_meta["pic"],
                "name": ex_meta["name"],
                "propertiesValue": ex_meta["propertyShortName"],
                "qty": ex_qty,
                "price": ex_unit,
                "basePrice": ex_orig,
                "amount": ex_amt,
                "isGift": False,
                "weight": 0,
                "size": 0,
                "isDeleted": False,
                "skuType": ex_meta["skuType"],
                "keyword": "",
                "isOversold": False,
                "liveLimitQty": 0,
                "isNotNeedDelivery": False,
                "itemType": "",
                "isUpsell": False,
                "isCombined": bool(ex_meta["isCombined"]),
                "isManualModifyPrice": abs(ex_unit - ex_orig) > 0.01,
                "platformOrderItemId": f"{ex_meta['skuId']}_{ts_ms + idx_ex}",
                "remark": "",
            }
        )

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

    if created_order and created_order.get("order_id"):
        oid_created = str(created_order["order_id"])
        saved_pay_amt = float(created_order.get("pay_amount") or 0.0)
        saved_is_cod = bool(created_order.get("is_cod"))

        # Round-2 Check A: Verify saved payment type (COD vs Transfer) and exact amount (> 0) match 100%
        if saved_pay_amt <= 0 or abs(saved_pay_amt - total_pay) > 0.5 or saved_is_cod != bool(is_cod):
            cancel_orders_in_jst(
                [oid_created],
                f"Audit รอบที่ 2 ยกเลิกอัตโนมัติ: ยอดเงิน ({saved_pay_amt} vs {total_pay}) หรือวิธีชำระเงิน (IsCod={saved_is_cod} vs {bool(is_cod)}) ไม่ตรงกัน ป้องกันการส่งของฟรีค่ะ",
            )
            return {
                "status": "error",
                "message": "ระบบทวนสอบรอบที่ 2 พบความผิดปกติของยอดชำระ/ประเภท COD จึงยกเลิกบิลอัตโนมัติเพื่อป้องกันการส่งของฟรีค่ะ",
            }

        slip_qr_verified = False
        if not is_cod and voucher_id:
            try:
                # Wait briefly for JST ERP's async pay-ocr worker to finish scanning the slip, then verify QR & amount
                time.sleep(4.0)
                slip_audit_res = verify_and_auto_confirm_jst_slips(limit=25)
                confirmed_ids = {
                    str(x.get("order_id")) for x in (slip_audit_res.get("auto_confirmed") or [])
                }
                rejected_ids = {
                    str(x.get("order_id")) for x in (slip_audit_res.get("rejected") or [])
                }
                if oid_created in confirmed_ids:
                    slip_qr_verified = True
                elif oid_created not in rejected_ids:
                    # Re-check live status in case JST ERP's built-in MachineAudit already passed it automatically
                    recheck = check_duplicate_order(phone, within_days=1)
                    latest_st = str((recheck["recent_orders"][0] if recheck["recent_orders"] else {}).get("status") or "")
                    if latest_st and "รอการชำระเงิน" not in latest_st and "รอตรวจสอบ" not in latest_st:
                        slip_qr_verified = True
            except Exception as exc:
                logger.warning("Auto ConfirmOrder warning for %s: %s", oid_created, exc)

        # Round-2 Check B: Only push to warehouse (`run_audit=True`) if COD is verified OR Transfer Slip QR is verified
        allow_warehouse_audit = bool(is_cod) or slip_qr_verified
        try:
            assign_express_and_audit_orders([oid_created], run_audit=allow_warehouse_audit)
        except Exception as exc:
            logger.warning("Auto assign_express_and_audit_orders warning for %s: %s", oid_created, exc)

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
            tail_txt = "\n".join(str(x.get("message") or "") for x in raw_messages[idx:])
            if (
                any(k in tail_txt for k in ("จัดส่ง :", "จัดส่ง:", "#BUY", "ตอบกลับโฆษณา"))
                or re.search(r"0[689]\d{8}", re.sub(r"\D", "", tail_txt))
            ):
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


MBS_SLIPS_CACHE_PATH: str = os.path.join(os.path.dirname(os.path.dirname(__file__)), "mbs_bank_slips_cache.json")


def fetch_mbs_bank_slip_for_customer(customer_name: str, page_id: str = "806129109240845") -> str:
    """Retrieve hidden Facebook Transfer Request (`SELLER_BANK_ACCOUNT_VERIFIED_APP_SWITCH` / `Is App Switch: Yes`)
    bank slip image URL from Meta Business Suite `สลิปธนาคาร` (`BizWebCometBankSlipTableContainerQuery`
    doc_id=24173238945617358 + `BizWebCometBankSlipDetailsViewContainerQuery` doc_id=30122875277303462)
    or synced `mbs_bank_slips_cache.json`.
    """
    import json

    clean_target = (customer_name or "").strip().lower()
    if not clean_target:
        return ""

    # 1. Live MBS GraphQL query if MBS_COOKIE and MBS_FB_DTSG are configured
    mbs_cookie = os.getenv("MBS_COOKIE", "").strip()
    mbs_dtsg = os.getenv("MBS_FB_DTSG", "").strip()
    if mbs_cookie and mbs_dtsg:
        try:
            now_ts = int(time.time())
            vars_table = {
                "endTime": now_ts + 3600,
                "first": 50,
                "pageID": page_id,
                "searchTerm": customer_name.strip(),
                "selectedFilter": "ALL",
                "sortDirection": "DESC",
                "sortField": "CREATION_TIME",
                "startTime": now_ts - 14 * 86400,
                "after": None,
            }
            r_tab = httpx.post(
                "https://business.facebook.com/api/graphql/",
                headers={
                    "Cookie": mbs_cookie,
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Origin": "https://business.facebook.com",
                    "Referer": f"https://business.facebook.com/latest/orders/bank_slips?asset_id={page_id}",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                },
                data={
                    "fb_dtsg": mbs_dtsg,
                    "fb_api_req_friendly_name": "BizWebCometBankSlipTableContainerQuery",
                    "variables": json.dumps(vars_table),
                    "doc_id": "24173238945617358",
                },
                timeout=12.0,
            )
            edges = (
                ((r_tab.json() or {}).get("data") or {})
                .get("page", {})
                .get("payment_hub_items", {})
                .get("edges")
                or []
            )
            for edge in edges:
                node = edge.get("node") or {}
                c_name = str((node.get("customer") or {}).get("name") or "").strip()
                item_id = str(node.get("id") or "").strip()
                if item_id and c_name.lower() == clean_target:
                    r_det = httpx.post(
                        "https://business.facebook.com/api/graphql/",
                        headers={
                            "Cookie": mbs_cookie,
                            "Content-Type": "application/x-www-form-urlencoded",
                            "Origin": "https://business.facebook.com",
                        },
                        data={
                            "fb_dtsg": mbs_dtsg,
                            "fb_api_req_friendly_name": "BizWebCometBankSlipDetailsViewContainerQuery",
                            "variables": json.dumps({"pageID": page_id, "paymentHubItemID": item_id}),
                            "doc_id": "30122875277303462",
                        },
                        timeout=12.0,
                    )
                    det_item = (((r_det.json() or {}).get("data") or {}).get("page") or {}).get("payment_hub_item") or {}
                    slip_url = str(det_item.get("bank_slip_image_url") or "").strip()
                    if slip_url:
                        ok, _ = verify_image_is_payment_slip(image_url=slip_url)
                        if ok:
                            return slip_url
        except Exception as exc:
            logger.warning("Live MBS bank_slips GraphQL lookup warning for %s: %s", customer_name, exc)

    # 2. Check synced MBS bank_slips cache (`mbs_bank_slips_cache.json`)
    if os.path.exists(MBS_SLIPS_CACHE_PATH):
        try:
            with open(MBS_SLIPS_CACHE_PATH, "r", encoding="utf-8") as f:
                cache_data = json.load(f)
            items = cache_data.get("items") or []
            for item in items:
                c_name = str(item.get("customer_name") or "").strip().lower()
                slip_url = str(item.get("bank_slip_image_url") or "").strip()
                if c_name == clean_target and slip_url:
                    ok, _ = verify_image_is_payment_slip(image_url=slip_url)
                    if ok:
                        return slip_url
        except Exception as exc:
            logger.warning("Failed reading MBS slips cache for %s: %s", customer_name, exc)

    return ""


def _fetch_fb_thread_messages_and_slip(
    external_user_id: str,
    brand_id: str = "buksukjai",
    customer_name: str = "",
) -> tuple[list[dict[str, str]], str]:
    """Query Facebook Graph API for a specific customer's CURRENT inquiry messages and verified slip image URL,
    with automatic fallback to Meta Business Suite `สลิปธนาคาร` (`bank_slips`) when Facebook hides Transfer Request slips.
    """
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
        if not customer_name:
            for p in (data[0].get("participants") or {}).get("data") or []:
                if str(p.get("id") or "") == str(external_user_id):
                    customer_name = str(p.get("name") or "").strip()
                    break
        all_chron_messages = list(reversed(data[0].get("messages", {}).get("data", [])))
        raw_messages = _slice_to_current_inquiry_fb(all_chron_messages)
        seen_payment_context = any(
            re.search(
                r"(#BUY|ชำระเงิน\s*:\s*โอน|โอนเงิน|โอนแล้ว|แจ้งสลิป|304-407545-5|3044075455|transfer request|ส่งการชำระเงิน)",
                str(m.get("message") or ""),
                re.I,
            )
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
                    r"(304-407545-5|3044075455|ดิจิสท์|เลขบัญชี|ยอดชำระ|ยอดรวมทั้งหมด|โอนแล้วแจ้งสลิป|ยอดโอน|โอนเงิน|transfer request)",
                    txt,
                    re.I,
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
        # Auto-recover hidden slip from MBS `สลิปธนาคาร` (`bank_slips`) when attached via Messenger Transfer Request
        if not latest_slip and seen_payment_context and customer_name:
            mbs_slip = fetch_mbs_bank_slip_for_customer(customer_name, page_id=page_id)
            if mbs_slip:
                latest_slip = mbs_slip
                fb_msgs.append({"role": "user", "content": f"[IMAGE:{mbs_slip}]"})
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
        fb_msgs, fb_slip_url = _fetch_fb_thread_messages_and_slip(
            external_user_id,
            brand_id=brand_id,
            customer_name=customer_name,
        )
        if fb_msgs:
            # Use the current-inquiry-sliced FB thread as authoritative so old orders from weeks ago never leak in
            msgs = list(fb_msgs)
            # Also preserve any verified slip [IMAGE:...] logged locally (e.g. from webhook or MBS bank_slips)
            # that Facebook Graph API /conversations hides when attached via Transfer Request (Is App Switch: Yes)
            if not fb_slip_url:
                for lm in reversed(local_msgs[-10:]):
                    if lm.get("role") == "user" and "[IMAGE:" in (lm.get("content") or ""):
                        im_local = re.search(r"\[IMAGE:(https?://[^\]]+)\]", lm.get("content") or "")
                        if im_local:
                            cand_local = im_local.group(1)
                            ok_local, _ = verify_image_is_payment_slip(image_url=cand_local)
                            if ok_local:
                                fb_slip_url = cand_local
                                msgs.append({"role": "user", "content": lm["content"]})
                                break

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

    # 2. Extract phone number (supports 08xxxxxxxx, 08x-xxx-xxxx, 0640-497-947-, โทร084-8607585, and +66936179424)
    phone = ""
    phone_pattern = r"(?:\+66\s*0?|0)[689]\d(?:[\s\-]*\d){7}"
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
            raw_address = re.sub(r"[()（）]", " ", raw_address)
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
    if latest_summary and "เคลม" in latest_summary:
        dialogue_complete = False
        dialogue_reason = "เป็นรายการเคลมสินค้า (⭕เคลม⭕) ไม่ใช่ออเดอร์ขายปกติค่ะ"

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

    # 7. Determine SKU, qty, unit_price, freight, extra_items from current inquiry ONLY (never default to old session SKU)
    sku_id = ""
    qty = 1
    unit_price: float | None = None
    freight = 0.0
    extra_items: list[dict[str, Any]] = []

    buy_tags = re.findall(r"#\s*BUY\s*(\d+)", full_text, re.I)
    total_hint = int(buy_tags[-1]) if buy_tags else 0
    if not total_hint and latest_summary:
        pm = re.search(r"ราคา\s*:\s*(?:[\d\+\s]+=)?\s*(\d+)", latest_summary)
        if pm:
            total_hint = int(pm.group(1))
    if not total_hint and dialogue_complete:
        ym = re.findall(r"ยอด(?:รวมทั้งหมด|ชำระ(?:โอนเงิน|โอน|เก็บปลายทาง)?)\s*:?\s*(?:[\d\+\s]+=)?\s*(\d+)\s*(?:บาท|฿)", full_text)
        if ym:
            total_hint = int(ym[-1])

    def _parse_single_size_token(token_str: str) -> tuple[str, int, float]:
        s = re.sub(r"\s+", "", token_str.lower())
        if "3kg" in s or "3แถม3" in s:
            return "BSJ1KG3_60G3", 1, 1299.0
        if "2kg" in s or "2แถม2" in s:
            return "BSJ1KG2_60G2", 1, 899.0
        m60 = re.search(r"60g(?:\*|x|×)?(\d+)(?:ถุง|ซอง|ชอง|ชุด)?", s)
        if m60:
            nb = int(m60.group(1))
            if nb == 20:
                return "BSJ60G20", 1, 720.0
            if nb == 15:
                return "BSJ60G15", 1, 555.0
            if nb == 10:
                return "BSJ60G10", 1, 390.0
            if nb == 30:
                return "BSJ60G10", 3, 370.0
            if nb == 5:
                return "BSJ60G5", 1, (195.0 if total_hint in (195, 225, 265) else 199.0)
            if nb == 3:
                return "BSJ60G3", 1, float(total_hint or 140)
            return "BSJ60G1", nb, 39.0
        if "1kg" in s:
            m1k = re.search(r"1kg(?:\*|x|×)?(\d+)(?:ถุง|ซอง|ชุด)?", s)
            n1k = int(m1k.group(1)) if m1k else 1
            return "BSJ1KG1", n1k, 459.0
        if "500g" in s:
            m500 = re.search(r"500g(?:\*|x|×)?(\d+)(?:ถุง|ซอง|ชุด)?", s)
            n500 = int(m500.group(1)) if m500 else 1
            return "BSJ500G1", n500, 239.0
        return "", 1, 0.0

    # Parse explicit size from latest_summary if available (supports multi-SKU comma-separated sizes like '1kg,60g20ถุง')
    if latest_summary:
        size_m = re.search(r"ขนาด\s*:\s*([^\n|]+)", latest_summary, re.I)
        if size_m:
            raw_size_line = size_m.group(1).strip()
            parts = [p.strip() for p in re.split(r"[,+]", raw_size_line) if p.strip()]
            parsed_parts: list[tuple[str, int, float]] = []
            for pt in parts:
                p_sku, p_qty, p_unit = _parse_single_size_token(pt)
                if p_sku:
                    parsed_parts.append((p_sku, p_qty, p_unit))
            if parsed_parts:
                sku_id, qty, unit_price = parsed_parts[0]
                for ex_sku, ex_qty, ex_unit in parsed_parts[1:]:
                    extra_items.append({"sku_id": ex_sku, "qty": ex_qty, "unit_price": ex_unit})
                items_sum = sum(q * u for _, q, u in parsed_parts)
                freight = float(max(0.0, total_hint - items_sum)) if total_hint >= items_sum else 0.0

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
        # Mr.Buk (มิสเตอร์บุก) Promo Totals
        elif total_hint == 44:
            sku_id, qty, unit_price, freight = "MRBUK60G1", 1, 44.0, 0.0
        elif total_hint == 74:
            sku_id, qty, unit_price, freight = "MRBUK60G1", 1, 44.0, 30.0
        elif total_hint == 114:
            sku_id, qty, unit_price, freight, is_cod, cod_confirmed = "MRBUK60G1", 1, 44.0, 70.0, True, True
        elif total_hint == 249:
            sku_id, qty, unit_price, freight = "MRBUK500G1", 1, 249.0, 0.0
        elif total_hint == 279:
            sku_id, qty, unit_price, freight = "MRBUK500G1", 1, 249.0, 30.0
        elif total_hint == 319:
            sku_id, qty, unit_price, freight, is_cod, cod_confirmed = "MRBUK500G1", 1, 249.0, 70.0, True, True
        elif total_hint in (465, 490):
            sku_id, qty, unit_price, freight = "MRBUK1KG1", 1, float(total_hint), 0.0
        elif total_hint == 530:
            sku_id, qty, unit_price, freight, is_cod, cod_confirmed = "MRBUK1KG1", 1, 490.0, 40.0, True, True
        elif total_hint == 599:
            sku_id, qty, unit_price, freight = "MRBUK60G15", 1, 599.0, 0.0
        elif total_hint == 639:
            sku_id, qty, unit_price, freight, is_cod, cod_confirmed = "MRBUK60G15", 1, 599.0, 40.0, True, True
        elif total_hint in (902, 950):
            sku_id, qty, unit_price, freight = "MRBUK1KG2_60G1", 1, float(total_hint), 0.0
        elif total_hint == 990:
            sku_id, qty, unit_price, freight, is_cod, cod_confirmed = "MRBUK1KG2_60G1", 1, 950.0, 40.0, True, True
        elif total_hint in (1130, 1190):
            sku_id, qty, unit_price, freight = "MRBUK60G30", 1, float(total_hint), 0.0
        elif total_hint == 1230:
            sku_id, qty, unit_price, freight, is_cod, cod_confirmed = "MRBUK60G30", 1, 1190.0, 40.0, True, True
        elif total_hint in (2270, 2390):
            sku_id, qty, unit_price, freight = "MRBUK1KG5", 1, float(total_hint), 0.0

    # 8. Cross-check customer's requested bag quantity against extracted SKU
    sku_matches_chat = True
    sku_mismatch_reason = ""
    if not latest_summary:
        # Check if customer asked for a specific number of small bags (e.g., 30ชอง, 32ซอง, 10ถุง)
        req_bag_matches = re.findall(r"\b(\d{1,2})\s*(?:ซอง|ชอง|ถุง)\b", user_only_text.lower())
        if req_bag_matches and "1 ก" not in user_only_text.lower() and "1kg" not in user_only_text.lower():
            req_bags = int(req_bag_matches[-1])
            bag_mult = {
                "BSJ60G20": 20, "BSJ60G15": 15, "BSJ60G10": 10, "BSJ60G5": 5, "BSJ60G3": 3, "BSJ60G1": 1,
                "MRBUK60G30": 30, "MRBUK60G15": 15, "MRBUK60G1": 1,
            }.get(sku_id, 0)
            eff_bags = bag_mult * int(qty)
            if req_bags >= 3 and eff_bags != req_bags:
                sku_matches_chat = False
                sku_mismatch_reason = f"ลูกค้าสั่ง {req_bags} ซอง/ถุง แต่ยังไม่มีสรุปยอดที่ตรงกันในแชท (SKU ปัจจุบัน: {sku_id or 'ไม่ระบุ'})"

    sku_meta = KNOWN_SKUS.get(sku_id, {})
    effective_unit_price = float(unit_price if unit_price is not None else sku_meta.get("price", 0.0))
    extra_amount = sum(
        float(ex.get("unit_price") or KNOWN_SKUS.get(ex.get("sku_id", ""), {}).get("price", 0.0)) * int(ex.get("qty") or 1)
        for ex in extra_items
    )
    total_amount = round(effective_unit_price * int(qty) + extra_amount + float(freight), 2) if sku_id else 0.0
    item_name = sku_meta.get("propertyShortName") or sku_meta.get("name") or sku_id or "ยังไม่ระบุสินค้า"
    if extra_items:
        ex_labels = [
            KNOWN_SKUS.get(ex.get("sku_id", ""), {}).get("propertyShortName") or str(ex.get("sku_id"))
            for ex in extra_items
        ]
        item_name = f"{item_name} + {' + '.join(ex_labels)}"
    transfer_bank_label = "โอนเงิน (กสิกรไทย 989-2-13624-3)" if brand_id == "mrbuk" else "โอนเงิน (SCB 304-407545-5)"
    payment_label = (
        "เก็บเงินปลายทาง (COD)"
        if is_cod is True
        else (transfer_bank_label if is_cod is False else "ยังไม่ระบุวิธีชำระเงิน")
    )
    remark_tag = f" (#BUY{int(total_amount)})" if total_amount > 0 else ""

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
        "extra_items": extra_items,
        "freight": freight,
        "total_amount": total_amount,
        "is_cod": bool(is_cod),
        "payment_label": payment_label,
        "customer_confirmed_cod": cod_confirmed,
        "has_slip": bool(slip_image_url),
        "has_admin_buy_summary": bool(slip_image_url),
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
    if not is_cod and not slip_image_url:
        return {
            **base_info,
            "valid": False,
            "reason": "ออเดอร์โอนเงินแต่ยังไม่มีสลิปโอนเงินจริงที่ตรวจสอบแล้วค่ะ (ห้ามส่งเข้า JST ERP เด็ดขาดจนกว่าลูกค้าจะส่งสลิปจริง เพื่อป้องกันการส่งของฟรี)",
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
        extra_items=data.get("extra_items"),
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


def get_warehouse_stock_summary() -> dict[str, Any]:
    """Query live warehouse stock from JST ERP (`/wms/Inventory/GetSkuInventorys`) for 60g, 500g, and 1kg."""
    h = _headers(json_body=True)
    h["Origin"] = "https://asia.jsterp.com"
    h["Referer"] = "https://asia.jsterp.com/Wms/Inventory/SkuInventory"

    try:
        resp = httpx.post(
            "https://asia.jsterp.com/wms/Inventory/GetSkuInventorys",
            headers=h,
            json={
                "RequestModel": {},
                "DataPage": {"pageSize": 50, "pageIndex": 1, "total": 0, "sizes": [50, 100]},
            },
            timeout=15.0,
        )
        update_cookie_from_response(resp)
        resp.raise_for_status()
        data = (resp.json() or {}).get("Data") or []
    except Exception as exc:
        logger.warning("Failed to fetch live warehouse stock from JST ERP: %s", exc)
        err_s = str(exc).lower()
        if any(k in err_s for k in ("401", "403", "login", "unauthorized", "expecting value")):
            try:
                from . import daily_sheet_report
                daily_sheet_report.send_jst_cookie_expired_alert_to_line_groups(str(exc))
            except Exception:
                pass
        return {"status": "error", "message": str(exc), "skus": {}}

    skus_map: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    label_map = {
        "BSJ60G1": ("ขนาด 60 กรัม", "ซอง", 100),
        "BSJ500G1": ("ขนาด 500 กรัม", "ถุง", 30),
        "BSJ1KG1": ("ขนาด 1 กิโลกรัม", "ถุง", 30),
    }

    for item in data:
        sku_id = str(item.get("SkuId") or "").strip()
        if not sku_id:
            continue
        phys_qty = int(item.get("Qty") or 0)
        order_lock = int(item.get("OrderLock") or 0)
        avail_qty = int(item.get("AvailableQty") if item.get("AvailableQty") is not None else max(0, phys_qty - order_lock))
        can_sell_days = int(item.get("CanSellDays") or 0)

        skus_map[sku_id] = {
            "sku_id": sku_id,
            "physical_qty": phys_qty,
            "order_lock": order_lock,
            "available_qty": avail_qty,
            "can_sell_days": can_sell_days,
            "modified": str(item.get("Modified") or ""),
        }
        if sku_id in label_map:
            lbl, unit_name, min_thresh = label_map[sku_id]
            if avail_qty <= min_thresh or (0 < can_sell_days <= 5):
                warnings.append(
                    f"{lbl} เหลือพร้อมขาย {avail_qty:,} {unit_name} (พอขายได้อีกประมาณ {can_sell_days} วัน)"
                )

    if not skus_map:
        return {"status": "empty", "skus": {}}

    s60 = skus_map.get("BSJ60G1", {})
    s500 = skus_map.get("BSJ500G1", {})
    s1k = skus_map.get("BSJ1KG1", {})

    return {
        "status": "ok",
        "available_60g": int(s60.get("available_qty", 0)),
        "physical_60g": int(s60.get("physical_qty", 0)),
        "lock_60g": int(s60.get("order_lock", 0)),
        "days_60g": int(s60.get("can_sell_days", 0)),
        "available_500g": int(s500.get("available_qty", 0)),
        "physical_500g": int(s500.get("physical_qty", 0)),
        "lock_500g": int(s500.get("order_lock", 0)),
        "days_500g": int(s500.get("can_sell_days", 0)),
        "available_1kg": int(s1k.get("available_qty", 0)),
        "physical_1kg": int(s1k.get("physical_qty", 0)),
        "lock_1kg": int(s1k.get("order_lock", 0)),
        "days_1kg": int(s1k.get("can_sell_days", 0)),
        "warnings": warnings,
        "skus": skus_map,
    }


def build_pre_keying_jst_checklist(days_lookback: int = 2) -> dict[str, Any]:
    """Compare recent confirmed chat orders (#BUY / 'เพจ : ข้าวบุก สุขใจ') against live JST ERP orders
    so admins can check BEFORE keying which orders are already in JST ERP vs which ones still need keying.
    """
    bkk_tz = timezone(timedelta(hours=7))
    now_bkk = datetime.now(bkk_tz)
    cutoff_utc = datetime.now(timezone.utc) - timedelta(days=max(1, days_lookback))
    cutoff_jst_str = (now_bkk - timedelta(days=max(3, days_lookback + 2))).strftime("%Y-%m-%d 00:00:00")

    # 1. Fetch recent active ManualOrders from JST ERP
    h = _headers(json_body=True)
    h["Origin"] = "https://asia.jsterp.com"
    h["Referer"] = "https://asia.jsterp.com/OMS/MiniShopOrder/Index"
    resp = httpx.post(
        "https://asia.jsterp.com/OMS/MiniShopOrder/NewQueryOrders",
        headers=h,
        json={
            "RequestModel": {"SendFrom": "NewQueryOrders"},
            "DataPage": {"pageSize": 200, "pageIndex": 1, "total": 0, "sizes": [50, 100, 200]},
        },
        timeout=25.0,
    )
    resp.raise_for_status()
    rows_obj = (resp.json() or {}).get("Rows") or {}
    cols = rows_obj.get("cols") or []
    raw_rows = rows_obj.get("rows") or []
    all_rows = [dict(zip(cols, r)) for r in raw_rows]

    jst_by_phone: dict[str, list[dict[str, Any]]] = {}
    for d in all_rows:
        st_disp = str(d.get("StatusDisplay") or "")
        if "ยกเลิก" in st_disp or "Cancel" in str(d.get("Status") or ""):
            continue
        if str(d.get("SaveType") or "") != "ManualOrder" and str(d.get("CreatorName") or "") != "buksukjai":
            continue
        ot = str(d.get("OrderTime") or "")
        if ot < cutoff_jst_str:
            continue
        ph = normalize_thai_phone(str(d.get("ReceiverMobileEn") or d.get("ReceiverMobile") or ""))
        item = {
            "order_id": str(d.get("OrderId") or ""),
            "order_time": ot,
            "status": st_disp,
            "receiver_name": str(d.get("ReceiverName") or "").strip(),
            "phone": ph,
            "pay_amount": float(d.get("PayAmount") or 0.0),
            "is_cod": bool(d.get("IsCod")),
            "tracking_no": str(d.get("LogisticsTrackingNumber") or "").strip(),
            "remark": str(d.get("SellerRemark") or "").strip(),
        }
        if ph and len(ph) == 10:
            jst_by_phone.setdefault(ph, []).append(item)

    # 2. Query live Facebook Graph API for #BUY / 'เพจ : ข้าวบุก สุขใจ' orders over the last `days_lookback` days
    from . import daily_sheet_report

    already_keyed: list[dict[str, Any]] = []
    pending_to_key: list[dict[str, Any]] = []
    seen_fb_keys: set[tuple[str, str]] = set()

    for d_offset in range(max(1, days_lookback)):
        t_date = (now_bkk - timedelta(days=d_offset)).strftime("%Y-%m-%d")
        fb_audit = daily_sheet_report.fetch_facebook_buy_audit(t_date)
        for ord_item in fb_audit.get("orders") or []:
            fb_name = str(ord_item.get("fb_name") or "").strip()
            amt = float(ord_item.get("amount") or 0.0)
            sum_txt = str(ord_item.get("summary_text") or "")
            time_bkk = str(ord_item.get("time_bkk") or "")

            ph_matches = re.findall(r"(?:\+66\s*0?|\b0)[689]\d[\s\-]?\d{3}[\s\-]?\d{4}", sum_txt)
            ph = normalize_thai_phone(ph_matches[-1]) if ph_matches else str(ord_item.get("phone") or "").strip()

            dedup_k = (ph or fb_name.lower(), t_date)
            if dedup_k in seen_fb_keys:
                continue
            seen_fb_keys.add(dedup_k)

            sz_m = re.search(r"ขนาด\s*:\s*([^\n]+)", sum_txt)
            size_label = sz_m.group(1).strip() if sz_m else f"ยอด {amt:.0f}฿"
            pay_m = re.search(r"ชำระเงิน\s*:\s*([^\n]+)", sum_txt)
            pay_label = pay_m.group(1).strip() if pay_m else ("ปลายทาง" if amt in (309, 499, 595, 760, 939, 1339) else "โอน/ปลายทาง")

            matched_jst = jst_by_phone.get(ph, []) if ph else []
            if not matched_jst and fb_name:
                # Fallback match by FB name in SellerRemark or ReceiverName
                for _, j_list in jst_by_phone.items():
                    for j_ord in j_list:
                        if fb_name.lower() in j_ord["remark"].lower() or fb_name.lower() == j_ord["receiver_name"].lower():
                            matched_jst = [j_ord]
                            break
                    if matched_jst:
                        break

            order_summary = {
                "order_date": t_date,
                "time_bkk": time_bkk,
                "customer_name": fb_name,
                "phone": ph or "ไม่ระบุเบอร์ในสรุป",
                "sku_id": size_label,
                "total_amount": amt,
                "payment_label": pay_label,
            }
            if matched_jst:
                latest_jst = matched_jst[0]
                already_keyed.append({
                    **order_summary,
                    "jst_order_id": latest_jst["order_id"],
                    "jst_order_time": latest_jst["order_time"],
                    "jst_status": latest_jst["status"],
                    "jst_tracking_no": latest_jst["tracking_no"],
                    "jst_active_count": len(matched_jst),
                })
            else:
                # Check if a transfer order is waiting for a verified slip image in chat
                slip_note = ""
                if "โอน" in pay_label and "ปลายทาง" not in pay_label:
                    try:
                        with SessionLocal() as _db:
                            _cand = (
                                _db.query(UserSession)
                                .filter(UserSession.customer_name == fb_name)
                                .first()
                            )
                        if _cand:
                            _ext = extract_order_from_session(_cand.psid)
                            if not _ext.get("has_slip"):
                                slip_note = " ⏳ (รอรูปสลิปโอนเงินในแชท)"
                    except Exception:
                        pass
                pending_to_key.append({**order_summary, "slip_note": slip_note})

    # Format human-readable summary for LINE Work Group / Admin
    lines = [
        f"📋 รายงานตรวจสอบออเดอร์ก่อนคีย์ลงระบบ JST ERP",
        f"🕒 ข้อมูล ณ {now_bkk.strftime('%d/%m/%Y %H:%M')} น. (ย้อนหลัง {days_lookback} วัน)",
        "━━━━━━━━━━━━━━━",
        f"📝 1. ออเดอร์ในแชทที่ 【ยังไม่ได้คีย์ลง JST】 ({len(pending_to_key)} รายการ):",
    ]
    if pending_to_key:
        for idx, p in enumerate(pending_to_key, 1):
            d_short = f"{p['order_date'][8:10]}/{p['order_date'][5:7]}" if len(p.get("order_date", "")) >= 10 else ""
            t_short = p.get("time_bkk", "")[:5]
            dt_tag = f"[{d_short} {t_short}] ".strip() if d_short else ""
            s_note = p.get("slip_note") or ""
            lines.append(
                f"  {idx}) {dt_tag}FB: {p['customer_name']} | เบอร์ {p['phone']} | "
                f"{p['sku_id']} ยอด {p['total_amount']:.0f}฿ ({p['payment_label']}){s_note}"
            )
    else:
        lines.append("  ✅ ไม่มีออเดอร์ค้างคีย์ค่ะ (คีย์ครบหมดแล้ว)")

    lines.append("━━━━━━━━━━━━━━━")
    lines.append(f"✅ 2. ออเดอร์ที่ 【คีย์ลง JST ไปแล้ว — ห้ามคีย์ซ้ำ!】 ({len(already_keyed)} รายการ):")
    if already_keyed:
        for idx, a in enumerate(already_keyed, 1):
            d_short = f"{a['order_date'][8:10]}/{a['order_date'][5:7]}" if len(a.get("order_date", "")) >= 10 else ""
            dt_tag = f"[{d_short}] " if d_short else ""
            trk_txt = f" | เลขพัสดุ {a['jst_tracking_no']}" if a.get("jst_tracking_no") else ""
            lines.append(
                f"  {idx}) {dt_tag}FB: {a['customer_name']} ({a['phone']}) ➡️ ใบสั่งซื้อ #{a['jst_order_id']} "
                f"ยอด {a['total_amount']:.0f}฿ [{a['jst_status']}{trk_txt}]"
            )
    else:
        lines.append("  • ยังไม่มีรายการที่คีย์ในรอบนี้ค่ะ")

    return {
        "status": "ok",
        "checked_at_bkk": now_bkk.strftime("%Y-%m-%d %H:%M:%S"),
        "days_lookback": days_lookback,
        "pending_to_key_count": len(pending_to_key),
        "pending_to_key": pending_to_key,
        "already_keyed_count": len(already_keyed),
        "already_keyed": already_keyed,
        "summary_text": "\n".join(lines),
    }

