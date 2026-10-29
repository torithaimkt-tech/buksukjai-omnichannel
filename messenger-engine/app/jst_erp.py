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

from app.config_loader import get_page_by_brand_id
from app.database import SessionLocal, UserSession, get_full_messages

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

DEFAULT_JST_COOKIE = os.getenv("JST_ERP_COOKIE", "")

_RUNTIME_COOKIE: str = os.getenv("JST_ERP_COOKIE", DEFAULT_JST_COOKIE)
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
}


def get_jst_cookie() -> str:
    return _RUNTIME_COOKIE


def set_jst_cookie(cookie: str) -> None:
    global _RUNTIME_COOKIE
    _RUNTIME_COOKIE = cookie.strip()


def is_auto_sync_enabled() -> bool:
    return AUTO_SYNC_ENABLED


def set_auto_sync_enabled(enabled: bool) -> None:
    global AUTO_SYNC_ENABLED
    AUTO_SYNC_ENABLED = bool(enabled)


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


def recognize_and_clean_address(
    raw_address: str,
    explicit_name: str = "",
    explicit_phone: str = "",
) -> dict[str, str]:
    """Use JST ERP's `AddresseeRecognition` API and clean up Thai name vs street address."""
    resp = httpx.post(
        "https://asia-web.jsterp.com/MiniShop/Recipient/Address/AddresseeRecognition",
        headers=_headers(json_body=True),
        json={"addressTxt": raw_address},
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

    rec_detail = re.sub(r"\b(แขวง|เขต|ตำบล|อำเภอ|จังหวัด|ต\.|อ\.|จ\.|รหัส|เบอร์|โทร)\s*(?=\s|$)", "", rec_detail).strip()
    rec_detail = re.sub(r"\s{2,}", " ", rec_detail).strip()

    addr_markers = r"(หมู่บ้าน|มบ\.|อาคาร|คอนโด|บริษัท|ร้าน|บ้านเลขที่|\d+/\d+|ซ\.|ซอย|ถ\.|ถนน|ม\.\d+|หมู่\s*\d+)"
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


def _fetch_fb_thread_messages_and_slip(external_user_id: str, brand_id: str = "buksukjai") -> tuple[list[dict[str, str]], str]:
    """Query Facebook Graph API for a specific customer's thread messages and latest verified slip image URL."""
    fb_msgs: list[dict[str, str]] = []
    latest_slip = ""
    try:
        page = get_page_by_brand_id(brand_id)
        if not page:
            return fb_msgs, latest_slip
        token = page.get("channels", {}).get("fb_page_access_token", "")
        page_id = str(page.get("channels", {}).get("fb_page_id", "806129109240845"))
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
        raw_messages = list(reversed(data[0].get("messages", {}).get("data", [])))
        seen_payment_context = False
        total_msgs = len(raw_messages)
        for idx, m in enumerate(raw_messages):
            sender_id = str((m.get("from") or {}).get("id") or "")
            role = "user" if sender_id == external_user_id else "admin"
            txt = str(m.get("message") or "").strip()
            if txt:
                fb_msgs.append({"role": role, "content": txt})
                if role != "user" and re.search(r"(304-407545-5|3044075455|ดิจิสท์|เลขบัญชี|ยอดชำระ|ยอดรวมทั้งหมด|โอนแล้วแจ้งสลิป)", txt):
                    seen_payment_context = True
            if role == "user":
                # Ignore any image sent at the very beginning before bank/payment context (e.g. ad/promo screenshots)
                if not seen_payment_context and idx < max(1, total_msgs - 6):
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
    except Exception as exc:
        logger.warning("Failed to fetch FB thread for %s: %s", external_user_id, exc)
    return fb_msgs, latest_slip


def extract_order_from_session(psid: str) -> dict[str, Any]:
    """Automatically extract SKU, price, shipping, COD/Transfer, recipient address, and slip URL from session history."""
    with SessionLocal() as db:
        session = db.get(UserSession, psid)
        if not session:
            return {"valid": False, "reason": "ไม่พบข้อมูลเซสชันลูกค้าค่ะ"}
        customer_name = session.customer_name
        external_user_id = session.external_user_id
        brand_id = session.brand_id
        platform = session.platform
        purchased_sku = session.purchased_sku or "BSJ1KG1"
        purchased_qty = session.purchased_qty or 1
        notes = session.notes or ""

    msgs = get_full_messages(psid, limit=40)
    fb_slip_url = ""
    if platform == "facebook" and external_user_id and not external_user_id.startswith("FB_"):
        fb_msgs, fb_slip_url = _fetch_fb_thread_messages_and_slip(external_user_id, brand_id=brand_id)
        if fb_msgs:
            existing_set = {m["content"].strip() for m in msgs if m.get("content")}
            for fm in fb_msgs:
                if fm["content"] not in existing_set:
                    msgs.append(fm)

    full_text = "\n".join(m["content"] for m in msgs if m.get("content"))

    # 1. Check if there is an explicit Admin Order Summary block ("เพจ : ข้าวบุก สุขใจ ... จัดส่ง : ...")
    admin_summaries = [
        m["content"]
        for m in msgs
        if ("เพจ :" in m["content"] or "เพจ:" in m["content"]) and "จัดส่ง" in m["content"]
    ]
    latest_summary = admin_summaries[-1] if admin_summaries else ""

    # 2. Extract phone number (supports 08xxxxxxxx, 08x-xxx-xxxx, and +66936179424)
    phone = ""
    phone_pattern = r"(?:\+66\s*0?|\b0)[689]\d[\s\-]?\d{3}[\s\-]?\d{4}"
    phone_search_target = latest_summary if latest_summary else full_text
    phone_matches = re.findall(phone_pattern, phone_search_target)
    if not phone_matches and latest_summary:
        phone_matches = re.findall(phone_pattern, full_text)
    if phone_matches:
        phone = normalize_thai_phone(phone_matches[-1])

    if not phone:
        return {"valid": False, "reason": "ยังไม่พบเบอร์โทรศัพท์ 10 หลักของลูกค้าในแชทค่ะ"}

    # 3. Determine COD vs Transfer with strict confirmation check
    is_cod: bool | None = None
    cod_confirmed = False
    transfer_confirmed = False

    if latest_summary:
        pay_m = re.search(r"ชำระเงิน\s*:\s*([^\n|]+)", latest_summary)
        if pay_m:
            pay_txt = pay_m.group(1)
            if "ปลายทาง" in pay_txt or "COD" in pay_txt.upper():
                is_cod = True
                cod_confirmed = True
            elif "โอน" in pay_txt:
                is_cod = False
                transfer_confirmed = True

    recent_tail = "\n".join(m["content"] for m in msgs[-15:])
    if is_cod is None:
        has_cod_choice = bool(
            re.search(r"(เก็บเงินปลายทาง|เก็บปลายทาง|ชำระปลายทาง|ยอดชำระเก็บปลายทาง|ค่าส่งเก็บปลายทาง|ปลายทางค่ะ|ปลายทางครับ)", recent_tail)
            and not re.search(r"(โอนค่ะ|โอนครับ|โอนเงิน|โอนนะ|ยอดชำระโอน)", recent_tail.split("ปลายทาง")[-1])
        )
        has_transfer_choice = bool(
            re.search(r"(โอนค่ะ|โอนครับ|แบบโอน|โอนเงิน|ยอดชำระโอนเงิน|แจ้งสลิป|ส่งการชำระเงินจำนวน|transfer request)", full_text, re.I)
        )
        if has_cod_choice:
            is_cod = True
            # Require explicit confirmation from customer or admin summary for COD
            user_tail = "\n".join(m["content"] for m in msgs[-8:] if m["role"] == "user")
            if re.search(r"(ยืนยัน|ตกลง|โอเค|ok|ค่ะ|ครับ|ตามนี้|ส่งได้เลย)", user_tail, re.I) or "#BUY" in full_text:
                cod_confirmed = True
        elif has_transfer_choice:
            is_cod = False
            transfer_confirmed = True

    if is_cod is None:
        return {
            "valid": False,
            "reason": "ยังไม่ชัดเจนว่าเป็นออเดอร์โอนเงินหรือเก็บเงินปลายทาง (COD) ต้องคอนเฟิร์มกับลูกค้าก่อนค่ะ",
        }

    # 4. Determine SKU, unit_price, freight
    sku_id = purchased_sku
    qty = purchased_qty
    unit_price: float | None = None
    freight = 0.0

    buy_tags = re.findall(r"#BUY(\d+)", full_text)
    total_hint = int(buy_tags[-1]) if buy_tags else 0
    if not total_hint and latest_summary:
        pm = re.search(r"ราคา\s*:\s*(?:\d+\+\d+=)?(\d+)", latest_summary)
        if pm:
            total_hint = int(pm.group(1))
    if not total_hint:
        ym = re.findall(r"ยอด(?:รวมทั้งหมด|ชำระ(?:โอนเงิน|โอน)?)\s*:?\s*(\d+)\s*บาท", full_text)
        if ym:
            total_hint = int(ym[-1])

    if total_hint == 309:
        sku_id, qty, unit_price, freight, is_cod, cod_confirmed = "BSJ500G1", 1, 239.0, 70.0, True, True
    elif total_hint == 239:
        sku_id, qty, unit_price, freight = "BSJ500G1", 1, 239.0, 0.0
    elif total_hint == 269:
        sku_id, qty, unit_price, freight = "BSJ500G1", 1, 269.0, 0.0
    elif total_hint == 459:
        sku_id, qty, unit_price, freight, is_cod = "BSJ1KG1", 1, 459.0, 0.0, False
    elif total_hint == 499:
        sku_id, qty, unit_price, freight, is_cod, cod_confirmed = "BSJ1KG1", 1, 459.0, 40.0, True, True
    elif total_hint == 529:
        sku_id, qty, unit_price, freight, is_cod, cod_confirmed = "BSJ1KG1", 1, 459.0, 70.0, True, True
    elif total_hint == 555:
        sku_id, qty, unit_price, freight = "BSJ60G15", 1, 555.0, 0.0
    elif total_hint in (720, 580):
        sku_id, qty, unit_price, freight = "BSJ60G20", 1, float(total_hint), 0.0
    elif total_hint == 899:
        sku_id, qty, unit_price, freight = "BSJ1KG2_60G2", 1, 899.0, 0.0
    elif total_hint in (939, 969):
        sku_id, qty, unit_price, freight, is_cod, cod_confirmed = "BSJ1KG2_60G2", 1, 899.0, float(total_hint - 899), True, True

    # 5. Extract raw_address
    raw_address = ""
    if latest_summary:
        am = re.search(r"จัดส่ง\s*:\s*(.+)", latest_summary, flags=re.DOTALL)
        if am:
            raw_address = am.group(1).strip()
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

    if not raw_address:
        return {"valid": False, "reason": "ยังไม่พบที่อยู่จัดส่งของลูกค้าในแชทค่ะ"}

    # 6. Extract & strictly verify slip image URL if Transfer, or verify COD confirmation
    slip_image_url = ""
    if is_cod:
        if not cod_confirmed:
            return {
                "valid": False,
                "reason": "ออเดอร์เก็บเงินปลายทาง (COD) ยังไม่ได้รับการคอนเฟิร์มขั้นสุดท้ายจากลูกค้าค่ะ",
            }
    else:
        if fb_slip_url:
            slip_image_url = fb_slip_url
        else:
            # Find the first message index where bank account or payment summary was given
            pay_ctx_idx = -1
            for idx, m in enumerate(msgs):
                if m["role"] != "user" and re.search(
                    r"(304-407545-5|3044075455|ดิจิสท์|เลขบัญชี|ยอดชำระ|โอนแล้วแจ้งสลิป)", m["content"]
                ):
                    pay_ctx_idx = idx
                    break
            for idx in range(len(msgs) - 1, -1, -1):
                m = msgs[idx]
                if m["role"] == "user" and "[IMAGE:" in m["content"]:
                    # Never grab an ad/promo screenshot sent at the beginning of the conversation before payment context
                    if pay_ctx_idx != -1 and idx < pay_ctx_idx and idx < max(1, len(msgs) - 6):
                        continue
                    im = re.search(r"\[IMAGE:(https?://[^\]]+)\]", m["content"])
                    if im:
                        candidate_url = im.group(1)
                        ok, _ = verify_image_is_payment_slip(image_url=candidate_url)
                        if ok:
                            slip_image_url = candidate_url
                            break

        if not slip_image_url:
            return {
                "valid": False,
                "reason": "ออเดอร์โอนเงินแต่ยังไม่มีสลิปโอนเงินจริงที่ตรวจสอบแล้วค่ะ (ห้ามส่งเข้า JST ERP จนกว่าลูกค้าจะส่งสลิปจริง)",
            }

    return {
        "valid": True,
        "psid": psid,
        "customer_name": customer_name,
        "phone": phone,
        "raw_address": raw_address,
        "sku_id": sku_id,
        "qty": qty,
        "unit_price": unit_price,
        "freight": freight,
        "is_cod": bool(is_cod),
        "slip_image_url": slip_image_url,
        "seller_remark": f"FB: {customer_name}",
        "already_tagged_in_notes": "[JST ERP:" in notes,
    }


def sync_session_to_jst(
    psid: str,
    overrides: dict[str, Any] | None = None,
    force_create: bool = False,
) -> dict[str, Any]:
    """Extract order from session (with optional UI overrides), check duplicate in JST, and create order."""
    extracted = extract_order_from_session(psid)
    if not extracted.get("valid") and not overrides:
        return {"status": "error", "message": extracted.get("reason", "ข้อมูลออเดอร์ไม่ครบถ้วนค่ะ")}

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


def sync_all_confirmed_orders_to_jst(days_lookback: int = 2) -> dict[str, Any]:
    """Scan all completed orders from the last `days_lookback` days, check JST ERP for duplicates, and push missing ones."""
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

    return results
