"""2-Stage Automated Parcel Tracking Notification Engine (แจ้งเลขพัสดุ & แจ้งเมื่อพัสดุส่งถึงมือลูกค้าอัตโนมัติ 2 ระยะ).

Workflow:
- Stage 1 (ขนส่งเข้ารับพัสดุแล้ว — Picked Up / Collected):
  Triggered when an order in JST ERP gets a tracking number (`LogisticsTrackingNumber`) AND the courier
  has scanned/picked up the parcel (`รับพัสดุ` / `Collected`).
  Sends a caring message to the customer informing them that the courier has picked up the parcel,
  along with the courier name (e.g. J&T Express) and tracking number.
- Stage 2 (พัสดุจัดส่งถึงเรียบร้อยแล้ว — Delivered / Signed):
  Continuously monitors the live courier trajectory via JST ERP (`/OMS/OrderLogistics/UpdateLogisticsTrajectory`
  & `/OMS/OrderLogistics/GetLogisticsTrajectory`). As soon as the parcel is delivered (`เซ็นรับพัสดุ`),
  automatically notifies the customer that the parcel has arrived along with the exact delivery time (`เวลา XX:XX น.`).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from . import database, jst_erp, messenger
from .llm import split_into_bubbles

logger = logging.getLogger(__name__)

TRACKING_STATE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "parcel_tracking_state.json",
)

DEFAULT_TRACKING_STATE: dict[str, Any] = {
    "auto_enabled": True,
    "min_order_date": "2026-10-29",
    "last_scan_at": "",
    "orders": {},
}


def get_tracking_state() -> dict[str, Any]:
    st = {
        "auto_enabled": DEFAULT_TRACKING_STATE["auto_enabled"],
        "min_order_date": DEFAULT_TRACKING_STATE["min_order_date"],
        "last_scan_at": "",
        "orders": {},
    }
    if os.path.exists(TRACKING_STATE_PATH):
        try:
            with open(TRACKING_STATE_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                st.update(saved)
                if not isinstance(st.get("orders"), dict):
                    st["orders"] = {}
        except Exception as exc:
            logger.warning("Failed to load parcel_tracking_state.json: %s", exc)
    return st


def save_tracking_state(state: dict[str, Any]) -> dict[str, Any]:
    try:
        with open(TRACKING_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.warning("Failed to save parcel_tracking_state.json: %s", exc)
    return state


def _norm_name(s: str) -> str:
    s = re.sub(r"\s*\(#.*\)$", "", s or "")
    return re.sub(r"\s+", " ", s).strip().lower()


def _extract_hhmm(dt_str: str) -> str:
    """Extract HH:MM from 'YYYY-MM-DD HH:MM:SS'."""
    m = re.search(r"\b(\d{2}:\d{2})(?::\d{2})?\b", str(dt_str or ""))
    return m.group(1) if m else ""


def build_stage1_pickup_message(courier_name: str, tracking_no: str) -> str:
    """Stage 1: Notify customer that the courier has picked up the parcel + tracking number."""
    clean_courier = (courier_name or "J&T Express").strip()
    return (
        "แจ้งอัปเดตสถานะจัดส่งค่ะคุณลูกค้า 🚚📦 ตอนนี้สินค้ามีขนส่งเข้ามารับเรียบร้อยแล้วนะคะ|||"
        f"🚚 ขนส่ง: {clean_courier}\n"
        f"🔖 เลขพัสดุ: {tracking_no}\n\n"
        "ทางร้านจะคอยตรวจสอบสถานะพัสดุให้ตลอดระยะเวลาจัดส่ง และพอพัสดุส่งถึงเรียบร้อยแล้วจะรีบแจ้งให้คุณลูกค้าทราบอีกครั้งนะคะ ขอบพระคุณมากค่ะ 💚🙏"
    )


def build_stage2_delivered_message(courier_name: str, tracking_no: str, delivered_hhmm: str) -> str:
    """Stage 2: Notify customer that the parcel has been delivered + exact time."""
    clean_courier = (courier_name or "J&T Express").strip()
    time_part = f"เมื่อเวลา {delivered_hhmm} น. " if delivered_hhmm else ""
    return (
        f"แจ้งอัปเดตพัสดุค่ะคุณลูกค้า 🎉📦 ตอนนี้พัสดุจัดส่งถึงเรียบร้อยแล้ว{time_part}นะคะ|||"
        f"🚚 ขนส่ง: {clean_courier}\n"
        f"🔖 เลขพัสดุ: {tracking_no}\n\n"
        "ขอบพระคุณที่ไว้วางใจให้ข้าวบุกสุขใจดูแลมื้อสุขภาพนะคะ ทานให้อร่อยและสุขภาพดีนะคะ หากมีข้อสงสัยเรื่องวิธีทำทักหาทางร้านได้ตลอดเลยนะคะ 💚🍚🙏"
    )


def _fetch_trajectory_for_order(order_id: int | str) -> list[dict[str, Any]]:
    """Trigger JST ERP trajectory refresh and return sorted scan events (newest first)."""
    try:
        oid_int = int(str(order_id).strip())
    except Exception:
        return []

    h = jst_erp._headers(json_body=True)
    h["Origin"] = "https://asia.jsterp.com"
    h["Referer"] = "https://asia.jsterp.com/OMS/Order/OrderManage"

    try:
        httpx.post(
            "https://asia.jsterp.com/OMS/OrderLogistics/UpdateLogisticsTrajectory",
            headers=h,
            json=[{"ShopId": jst_erp.JST_SHOP_ID, "OrderId": oid_int}],
            timeout=12.0,
        )
    except Exception as exc:
        logger.debug("UpdateLogisticsTrajectory warning for %s: %s", oid_int, exc)

    try:
        r_get = httpx.post(
            "https://asia.jsterp.com/OMS/OrderLogistics/GetLogisticsTrajectory",
            headers=h,
            json={"OrderId": oid_int, "InoutId": 0},
            timeout=12.0,
        )
        r_get.raise_for_status()
        data = (r_get.json() or {}).get("Data") or []
        return data if isinstance(data, list) else []
    except Exception as exc:
        logger.warning("GetLogisticsTrajectory failed for %s: %s", oid_int, exc)
        return []


def inspect_order_tracking_status(order_row: dict[str, Any]) -> dict[str, Any]:
    """Inspect a JST ERP order row + live courier trajectory to determine Stage 1 (picked up) & Stage 2 (delivered)."""
    order_id = str(order_row.get("OrderId") or "").strip()
    tracking_no = str(order_row.get("LogisticsTrackingNumber") or "").strip()
    courier_name = str(order_row.get("LogisticsCompanyName") or "J&T Express").strip()
    logistics_status = str(order_row.get("LogisticsStatus") or "").strip()
    sign_time = str(order_row.get("SignTime") or "").strip()

    raw_events = _fetch_trajectory_for_order(order_id) if order_id and tracking_no else []
    events = [
        ev
        for ev in raw_events
        if str(ev.get("OperationTime") or "").strip()
        or str(ev.get("LogisticsStatus") or "").strip()
        or str(ev.get("Description") or "").strip()
    ]

    is_picked_up = logistics_status in ("Collected", "Delivered", "Signed") or len(events) > 0
    is_delivered = False
    pickup_op_time = ""
    delivered_op_time = ""

    for ev in events:
        st_txt = str(ev.get("LogisticsStatus") or "").strip()
        desc_txt = str(ev.get("Description") or "").strip()
        op_time = str(ev.get("OperationTime") or "").strip()

        if "รับพัสดุ" == st_txt or "รับพัสดุแล้ว" in desc_txt:
            pickup_op_time = op_time
            is_picked_up = True

        if (
            "เซ็นรับ" in st_txt
            or "เซ็นรับแล้ว" in desc_txt
            or st_txt.lower() in ("delivered", "signed")
        ):
            is_delivered = True
            is_picked_up = True
            if not delivered_op_time:
                delivered_op_time = op_time

    if not is_delivered and logistics_status in ("Delivered", "Signed") and sign_time:
        is_delivered = True
        delivered_op_time = sign_time

    if is_picked_up and not pickup_op_time and events:
        pickup_op_time = str(events[-1].get("OperationTime") or "").strip()

    return {
        "order_id": order_id,
        "tracking_no": tracking_no,
        "courier_name": courier_name,
        "is_picked_up": is_picked_up,
        "pickup_time": pickup_op_time,
        "pickup_hhmm": _extract_hhmm(pickup_op_time),
        "is_delivered": is_delivered,
        "delivered_time": delivered_op_time,
        "delivered_hhmm": _extract_hhmm(delivered_op_time),
        "events_count": len(events),
        "latest_event": events[0] if events else None,
    }


def _build_session_lookup_maps() -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Return (order_id_to_psid, phone_to_psid, norm_name_to_psid) from SQLite `chatbot.db`."""
    all_sessions = database.list_all_sessions()
    order_id_to_psid: dict[str, str] = {}
    phone_to_psid: dict[str, str] = {}
    name_to_psid: dict[str, str] = {}

    phone_pat = re.compile(r"(?:\+66\s*0?|0)[689]\d(?:[\s\-]*\d){7}")

    for s in all_sessions:
        psid = s["psid"]
        cname = _norm_name(s.get("customer_name") or "")
        notes = (s.get("notes") or "").strip()
        if cname and cname not in name_to_psid:
            name_to_psid[cname] = psid

        for m_oid in re.findall(r"#JST_ORDER:(\d+)", notes):
            order_id_to_psid[m_oid] = psid

        for m_ph in phone_pat.findall(notes):
            clean_p = jst_erp.normalize_thai_phone(m_ph)
            if clean_p and clean_p not in phone_to_psid:
                phone_to_psid[clean_p] = psid

        msgs = database.get_full_messages(psid, limit=60)
        for msg in msgs:
            txt = msg.get("content") or ""
            for m_ph in phone_pat.findall(txt):
                clean_p = jst_erp.normalize_thai_phone(m_ph)
                if clean_p and clean_p not in phone_to_psid:
                    phone_to_psid[clean_p] = psid

    return order_id_to_psid, phone_to_psid, name_to_psid


def _has_already_sent_in_chat(psid: str, tracking_no: str, stage: int) -> bool:
    """Check UserSession.notes and MessageLog to guarantee we never send duplicate notifications."""
    user = database.get_or_create_session(psid)
    notes = user.notes or ""
    if stage == 1 and (
        f"#TRACK_PICKUP_SENT:{tracking_no}" in notes
        or f"#TRACK_DELIVERED_SENT:{tracking_no}" in notes
    ):
        return True
    if stage == 2 and f"#TRACK_DELIVERED_SENT:{tracking_no}" in notes:
        return True

    msgs = database.get_full_messages(psid, limit=60)
    assistant_texts = [
        str(m.get("content") or "")
        for m in msgs
        if m.get("role") != "user"
    ]
    joined_assistant = "\n".join(assistant_texts)
    if tracking_no not in joined_assistant:
        return False

    for m in msgs:
        if m.get("role") == "user":
            continue
        content = str(m.get("content") or "")
        s_label = str(m.get("sender_label") or "")
        if stage == 1:
            if "ระยะที่ 1" in s_label or "ขนส่งเข้ามารับเรียบร้อยแล้ว" in content:
                return True
            if tracking_no in content and "เลขพัสดุ" in content and "จัดส่งถึงเรียบร้อยแล้ว" not in content:
                return True
        if stage == 2:
            if "ระยะที่ 2" in s_label or "ตอนนี้พัสดุจัดส่งถึงเรียบร้อยแล้ว" in content or "แจ้งอัปเดตพัสดุค่ะคุณลูกค้า 🎉📦" in content:
                return True
    return False


async def _send_tracking_notification(
    psid: str,
    stage: int,
    order_id: str,
    courier_name: str,
    tracking_no: str,
    delivered_hhmm: str = "",
    public_base_url: str = "",
) -> dict[str, Any]:
    """Send Stage 1 (Pickup) or Stage 2 (Delivered) message to customer on Facebook/LINE and record tags."""
    user = database.get_or_create_session(psid)
    if stage == 1:
        msg_text = build_stage1_pickup_message(courier_name, tracking_no)
        sender_label = "AI แจ้งเลขพัสดุ (ระยะที่ 1)"
        tag_to_add = "แจ้งเลขพัสดุแล้ว"
        note_marker = f"#TRACK_PICKUP_SENT:{tracking_no}"
    else:
        msg_text = build_stage2_delivered_message(courier_name, tracking_no, delivered_hhmm)
        sender_label = "AI แจ้งพัสดุถึงแล้ว (ระยะที่ 2)"
        tag_to_add = "พัสดุส่งถึงแล้ว"
        note_marker = f"#TRACK_DELIVERED_SENT:{tracking_no}"

    bubbles = split_into_bubbles(msg_text)
    for b in bubbles:
        database.log_message(psid, "assistant", b, sender_label=sender_label)

    jst_erp._append_session_note(psid, f"#JST_ORDER:{order_id}")
    jst_erp._append_session_note(psid, note_marker)
    if stage == 2:
        jst_erp._append_session_note(psid, f"#TRACK_PICKUP_SENT:{tracking_no}")

    updated_tags = database._add_tag_str(user.broadcast_tags or "", tag_to_add)
    meta_kwargs: dict[str, Any] = {
        "psid": psid,
        "broadcast_tags": updated_tags,
    }
    if stage == 2:
        # Mark after_sales_stage >= 1 so the generic Day-3 "ได้รับพัสดุหรือยังคะ" check is skipped
        meta_kwargs["after_sales_stage"] = max(user.after_sales_stage or 0, 1)

    database.update_session_meta(**meta_kwargs)

    await messenger.send_omnichannel_text(
        platform=user.platform,
        external_user_id=user.external_user_id,
        text=msg_text,
        brand_id=user.brand_id,
        public_base_url=public_base_url,
    )

    return {
        "psid": psid,
        "customer_name": user.customer_name,
        "order_id": order_id,
        "tracking_no": tracking_no,
        "courier_name": courier_name,
        "stage": stage,
        "delivered_hhmm": delivered_hhmm,
        "bubbles": bubbles,
    }


async def check_and_send_parcel_tracking_updates(
    public_base_url: str = "",
    min_order_date: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Scan recent JST ERP orders, check live courier pickup & delivery status, and notify customers."""
    state = get_tracking_state()
    if not state.get("auto_enabled", True) and not dry_run:
        return {"status": "disabled", "sent_stage1": [], "sent_stage2": []}

    cutoff_date = (min_order_date or state.get("min_order_date") or "2026-10-29").strip()

    # Fetch recent orders from JST ERP
    def _query_recent_jst_orders() -> list[dict[str, Any]]:
        h = jst_erp._headers(json_body=True)
        resp = httpx.post(
            "https://asia.jsterp.com/OMS/MiniShopOrder/NewQueryOrders",
            headers=h,
            json={
                "RequestModel": {"SendFrom": "NewQueryOrders"},
                "DataPage": {"pageSize": 100, "pageIndex": 1, "total": 0, "sizes": [50, 100, 200]},
            },
            timeout=20.0,
        )
        resp.raise_for_status()
        rows_obj = (resp.json() or {}).get("Rows") or {}
        cols = rows_obj.get("cols") or []
        raw_rows = rows_obj.get("rows") or []
        return [dict(zip(cols, r)) for r in raw_rows]

    try:
        order_rows = await asyncio.to_thread(_query_recent_jst_orders)
    except Exception as exc:
        logger.warning("Failed to query JST ERP orders for parcel tracking: %s", exc)
        return {"status": "error", "message": str(exc), "sent_stage1": [], "sent_stage2": []}

    order_id_to_psid, phone_to_psid, name_to_psid = await asyncio.to_thread(_build_session_lookup_maps)

    sent_stage1: list[dict[str, Any]] = []
    sent_stage2: list[dict[str, Any]] = []
    checked_orders: list[dict[str, Any]] = []
    orders_state: dict[str, Any] = state.setdefault("orders", {})
    seen_psid_date: set[tuple[str, str]] = set()

    bkk_tz = timezone(timedelta(hours=7))
    now_bkk_str = datetime.now(bkk_tz).strftime("%Y-%m-%d %H:%M:%S")

    for row in order_rows:
        order_id = str(row.get("OrderId") or "").strip()
        order_time = str(row.get("OrderTime") or "").strip()
        if not order_id or order_time < cutoff_date:
            continue

        status_disp = str(row.get("StatusDisplay") or "")
        if "ยกเลิก" in status_disp or "Cancel" in str(row.get("Status") or ""):
            continue

        tracking_no = str(row.get("LogisticsTrackingNumber") or "").strip()
        if not tracking_no:
            continue

        phone = jst_erp.normalize_thai_phone(str(row.get("ReceiverMobileEn") or ""))
        remark = str(row.get("SellerRemark") or "").strip()
        rec_name = str(row.get("ReceiverName") or "").strip()

        # Skip marketplace orders with masked phones that aren't Facebook/LINE chat customers
        if (not phone or phone.startswith("*")) and not remark.startswith("FB:"):
            continue

        psid = order_id_to_psid.get(order_id) or (phone_to_psid.get(phone) if phone else None)
        if not psid and remark.startswith("FB:"):
            psid = name_to_psid.get(_norm_name(remark[3:]))
        if not psid and rec_name:
            psid = name_to_psid.get(_norm_name(rec_name))

        if not psid:
            continue

        psid_date_key = (psid, order_time[:10])
        if psid_date_key in seen_psid_date:
            continue
        seen_psid_date.add(psid_date_key)

        saved_ord = orders_state.get(order_id) or {}
        if saved_ord.get("stage2_delivered_sent_at") and saved_ord.get("tracking_no") == tracking_no:
            continue

        info = await asyncio.to_thread(inspect_order_tracking_status, row)
        courier_name = info["courier_name"]
        is_picked_up = info["is_picked_up"]
        is_delivered = info["is_delivered"]
        delivered_hhmm = info["delivered_hhmm"]

        user_obj = database.get_or_create_session(psid)
        ord_record = {
            "order_id": order_id,
            "order_time": order_time,
            "tracking_no": tracking_no,
            "courier_name": courier_name,
            "psid": psid,
            "customer_name": user_obj.customer_name,
            "is_picked_up": is_picked_up,
            "pickup_time": info["pickup_time"],
            "is_delivered": is_delivered,
            "delivered_time": info["delivered_time"],
            "delivered_hhmm": delivered_hhmm,
            "stage1_pickup_sent_at": saved_ord.get("stage1_pickup_sent_at", ""),
            "stage2_delivered_sent_at": saved_ord.get("stage2_delivered_sent_at", ""),
        }
        checked_orders.append(ord_record)

        if is_delivered:
            already_s2 = bool(ord_record["stage2_delivered_sent_at"]) or _has_already_sent_in_chat(
                psid, tracking_no, 2
            )
            if not already_s2:
                if dry_run:
                    sent_stage2.append({**ord_record, "dry_run": True})
                else:
                    res2 = await _send_tracking_notification(
                        psid=psid,
                        stage=2,
                        order_id=order_id,
                        courier_name=courier_name,
                        tracking_no=tracking_no,
                        delivered_hhmm=delivered_hhmm,
                        public_base_url=public_base_url,
                    )
                    ord_record["stage2_delivered_sent_at"] = now_bkk_str
                    if not ord_record["stage1_pickup_sent_at"]:
                        ord_record["stage1_pickup_sent_at"] = now_bkk_str
                    sent_stage2.append(res2)
        elif is_picked_up:
            already_s1 = bool(ord_record["stage1_pickup_sent_at"]) or _has_already_sent_in_chat(
                psid, tracking_no, 1
            )
            if not already_s1:
                if dry_run:
                    sent_stage1.append({**ord_record, "dry_run": True})
                else:
                    res1 = await _send_tracking_notification(
                        psid=psid,
                        stage=1,
                        order_id=order_id,
                        courier_name=courier_name,
                        tracking_no=tracking_no,
                        public_base_url=public_base_url,
                    )
                    ord_record["stage1_pickup_sent_at"] = now_bkk_str
                    sent_stage1.append(res1)

        orders_state[order_id] = ord_record

    if not dry_run:
        state["last_scan_at"] = now_bkk_str
        save_tracking_state(state)

    return {
        "status": "ok",
        "dry_run": dry_run,
        "checked_count": len(checked_orders),
        "sent_stage1_count": len(sent_stage1),
        "sent_stage2_count": len(sent_stage2),
        "sent_stage1": sent_stage1,
        "sent_stage2": sent_stage2,
        "checked_orders": checked_orders,
    }
