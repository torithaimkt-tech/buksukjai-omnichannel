"""Omnichannel Follow-Up & Post-Purchase After-Sales Retention Engine.

Handles two automated workflows:
1. Pending-Payment Follow-up: Nudges customers stuck in `pending_payment` after N hours.
2. Post-Purchase After-Sales Care (for `completed` / paid customers with Broadcast Tags):
   - Stage 1 (Day 3 after purchase): Check if the customer received the parcel ("ได้รับสินค้าหรือยังคะ").
   - Stage 2 (Day 5 after purchase): Ask if the customer has tasted the rice ("ได้ลองชิมสินค้าหรือยังคะ").
   - Stage 3 (Smart Depletion Day based on SKU & Quantity bought): Ask how the taste is, whether any rice is left, and offer the Exclusive 5% Returning Customer (VIP) Promotion!
"""

import asyncio
import importlib
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

from . import database, jst_erp, media_generator, messenger

logger = logging.getLogger(__name__)

DEFAULT_FOLLOWUP_MESSAGE = (
    "สวัสดีค่ะคุณลูกค้า 🍚 ออเดอร์ข้าวบุกสุขใจยังค้างอยู่ในระบบนะคะ "
    "สะดวกแจ้งชื่อ-ที่อยู่-เบอร์โทรเพื่อจัดส่งได้เลยนะคะ 🙏💚"
)

SKU_CONSUMPTION_RULES = {
    "BSJ60G1": {
        "label": "ซองเล็ก 60 กรัม",
        "meals_per_unit": 1,
        "days_per_unit": 1,
    },
    "BSJ500G1": {
        "label": "ถุงกลาง 500 กรัม",
        "meals_per_unit": 8,
        "days_per_unit": 8,
    },
    "BSJ1KG1": {
        "label": "ถุงใหญ่ 1 กก.",
        "meals_per_unit": 16,
        "days_per_unit": 14,
    },
    "BSJ_SET15": {
        "label": "เซ็ตพกพา 15 ซอง",
        "meals_per_unit": 15,
        "days_per_unit": 14,
    },
    "BSJ_SET20": {
        "label": "เซ็ตพกพา 20 ซอง",
        "meals_per_unit": 20,
        "days_per_unit": 18,
    },
    "BSJ_FAM2": {
        "label": "โปรตุน 2 แถม 2 (1 กก. 2 ถุง + 60g 2 ซอง)",
        "meals_per_unit": 34,
        "days_per_unit": 27,
    },
    "BSJ_BIG3": {
        "label": "โปรตุน 3 แถม 3 (1 กก. 3 ถุง + 60g 3 ซอง)",
        "meals_per_unit": 51,
        "days_per_unit": 42,
    },
}


def calculate_depletion_schedule(sku: str, qty: int) -> dict:
    """Calculate exact post-purchase follow-up days based on SKU & quantity purchased."""
    clean_qty = max(1, int(qty or 1))
    info = SKU_CONSUMPTION_RULES.get(sku) or SKU_CONSUMPTION_RULES["BSJ1KG1"]
    total_meals = info["meals_per_unit"] * clean_qty
    # 3 days shipping + consumption days (minimum Day 7 so it always comes after Day 5 taste check)
    depletion_day = max(7, 3 + (info["days_per_unit"] * clean_qty))
    return {
        "sku": sku if sku in SKU_CONSUMPTION_RULES else "BSJ1KG1",
        "label": info["label"],
        "quantity": clean_qty,
        "total_meals": total_meals,
        "day_delivery_check": 3,
        "day_taste_check": 5,
        "day_depletion_reorder": depletion_day,
    }


def build_after_sales_message(stage: int, sku: str, qty: int) -> tuple[str, str, str | None]:
    """Return (message_text, broadcast_tag_to_add, optional_image_key) for Stage 1, 2, or 3."""
    sched = calculate_depletion_schedule(sku, qty)
    item_desc = f"{sched['label']} จำนวน {sched['quantity']} ชุด (ประมาณ {sched['total_meals']} มื้อ)"

    if stage == 1:
        return (
            "สวัสดีค่าคุณลูกค้า 🍚✨ น้องบุกแวะมาดูแลหลังการขายค่ะ อยากสอบถามว่าคุณลูกค้าได้รับพัสดุข้าวบุกสุขใจเรียบร้อยหรือยังคะ|||"
            "หากได้รับแล้วติดขัดตรงไหน หรืออยากสอบถามวิธีทำ ทักหาน้องบุกได้ตลอดเลยนะคะ 😊💚",
            "เช็กพัสดุ_3วัน",
            None,
        )
    if stage == 2:
        return (
            "สวัสดีค่าคุณลูกค้า 😊 ช่วงนี้ได้ลองชิมข้าวบุกสุขใจหรือยังคะ|||"
            "แค่ตักใส่ชาม เติมน้ำร้อนจัด ปิดฝารอ 10–15 นาที ข้าวพองนุ่มอร่อยถูกใจไหมคะ แวะมาเล่าให้น้องบุกฟังได้นะคะ 🍚💚",
            "ถามรสชาติ_5วัน",
            None,
        )
    return (
        f"สวัสดีค่าคุณลูกค้า 🍚✨ ข้าวบุกสุขใจ ({item_desc}) ที่รับไป ทานแล้วรสชาติเป็นยังไงบ้างคะ ตอนนี้ยังเหลืออยู่ไหมเอ่ย 😊|||"
        "ถ้าใกล้หมดแล้วและจะสั่งซื้อเพิ่มเติม บอกแอดมินได้เลยนะคะ เรามีโปรโมชั่นพิเศษลด 5% สำหรับลูกค้าเก่าโดยเฉพาะเลยค่า\n\n"
        "• ถุงใหญ่ 1 กก. = เหลือ 436 บาท (โอนส่งฟรี!)\n\n"
        "• เซ็ตพกพา 20 ซอง = เหลือ 684 บาท (ส่งฟรี!)\n\n"
        "• โปรตุน 2 แถม 2 = เหลือ 854 บาท (ส่งฟรี!)\n\n"
        "• โปรตุน 3 แถม 3 = เหลือ 1,234 บาท (ส่งฟรี!)|||"
        "คุณลูกค้าสนใจรับชุดไหนไปทานต่อเนื่อง แจ้งน้องบุกได้เลยนะคะ 💚🙏",
        "ลูกค้าเก่า_VIP",
        "promo_vip",
    )


async def send_after_sales_stage(
    psid: str,
    stage: int,
    public_base_url: str = "",
) -> dict:
    """Trigger Stage 1 (Day 3), Stage 2 (Day 5), or Stage 3 (Depletion + VIP Promo) for a session."""
    user = database.get_or_create_session(psid)
    msg_text, new_tag, img_key = build_after_sales_message(stage, user.purchased_sku, user.purchased_qty)

    media_items = []
    if img_key:
        vip_item = media_generator.get_media_item(img_key)
        if vip_item:
            media_items = [vip_item]

    for it in media_items:
        database.log_message(psid, "assistant", f"[IMAGE:{it['relative_url']}]", sender_label="AI บริการหลังการขาย")

    from .llm import split_into_bubbles

    bubbles = split_into_bubbles(msg_text)
    for b in bubbles:
        database.log_message(psid, "assistant", b, sender_label="AI บริการหลังการขาย")

    updated_tags = database._add_tag_str(user.broadcast_tags or "", "ชำระเงินแล้ว")
    updated_tags = database._add_tag_str(updated_tags, new_tag)
    database.update_session_meta(
        psid=psid,
        broadcast_tags=updated_tags,
        after_sales_stage=max(user.after_sales_stage or 0, stage),
    )

    await messenger.send_omnichannel_text(
        platform=user.platform,
        external_user_id=user.external_user_id,
        text=msg_text,
        brand_id=user.brand_id,
        media_items=media_items,
        public_base_url=public_base_url,
    )
    return {
        "status": "ok",
        "psid": psid,
        "stage": stage,
        "added_tag": new_tag,
        "broadcast_tags": updated_tags,
        "bubbles": bubbles,
    }


def _config_followup_message(config: dict) -> str:
    return config.get("followup_strategy", {}).get("message", DEFAULT_FOLLOWUP_MESSAGE)


# ==============================================================================
# 3. Ghost / Silent Lead Re-engagement Bot ("บอทขุดสำหรับลูกค้าที่เงียบหายไป")
# ==============================================================================

REENGAGE_CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reengage_config.json")

DEFAULT_REENGAGE_CONFIG = {
    "auto_enabled": True,
    "stage1_hours": 1.0,
    "stage2_hours": 6.0,
    "stage3_hours": 20.0,
    "max_window_hours": 23.5,
}


def get_reengage_config() -> dict:
    import json

    cfg = dict(DEFAULT_REENGAGE_CONFIG)
    if os.path.exists(REENGAGE_CONFIG_PATH):
        try:
            with open(REENGAGE_CONFIG_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
            cfg.update(saved)
        except Exception:
            pass
    return cfg


def save_reengage_config(updates: dict) -> dict:
    import json

    cfg = get_reengage_config()
    for k in ("auto_enabled", "stage1_hours", "stage2_hours", "stage3_hours", "max_window_hours"):
        if k in updates and updates[k] is not None:
            cfg[k] = updates[k]
    with open(REENGAGE_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    return cfg


def build_reengage_message(stage: int, state: str) -> tuple[str, str, str | None]:
    """Build (message_text, broadcast_tag, optional_image_key) for Ghost Re-engagement Stage 1, 2, or 3."""
    is_pending = state == "pending_payment"

    if stage == 1:
        if is_pending:
            return (
                "คุณลูกค้าคะ 😊 สำหรับออเดอร์ข้าวบุกสุขใจที่เลือกไว้ "
                "หากสะดวกแล้วสามารถแจ้ง ชื่อ-ที่อยู่-เบอร์โทร (หรือส่งสลิปโอนเงิน) "
                "ให้น้องบุกจัดเตรียมพัสดุได้เลยนะคะ 🍚💚",
                "ตามที่อยู่_1ชม",
                None,
            )
        return (
            "คุณลูกค้าดูโปรโมชั่นไว้ พอจะมีขนาดไหนที่สนใจเป็นพิเศษไหมคะ 😊🍚|||"
            "ถ้าเพิ่งเริ่มลองทาน ลูกค้าส่วนใหญ่จะนิยม ถุงใหญ่ 1 กก. (459.- โอนส่งฟรี ทานได้ 16–20 มื้อ) "
            "หรือแบบซองพกพา 60g ค่ะ สงสัยตรงไหนถามน้องบุกได้เลยนะคะ 💚",
            "ขุดแชท_1ชม",
            None,
        )

    if stage == 2:
        if is_pending:
            return (
                "สวัสดีค่ะคุณลูกค้า 🍚 ออเดอร์ข้าวบุกสุขใจยังค้างอยู่ในระบบนะคะ|||"
                "หากยังไม่สะดวกโอนเงิน สามารถแจ้งเปลี่ยนเป็นบริการเก็บเงินปลายทาง (COD) ได้เลยนะคะ "
                "สะดวกแบบไหนแจ้งน้องบุกได้เลยค่า 😊🙏",
                "ตามที่อยู่_6ชม",
                None,
            )
        return (
            "แวะมาแจ้งเพิ่มเติมเผื่อคุณลูกค้ากำลังตัดสินใจอยู่ค่า 🍚✨ "
            "ข้าวบุกสุขใจไม่มีกลิ่นหัวบุกเลยนะคะ หอมนุ่มเหมือนข้าวหอมมะลิแท้ "
            "แค่ตักเติมน้ำร้อนปิดฝา 10 นาทีก็ทานได้เลยค่ะ|||"
            "มีทั้งแบบโอนเงินส่งฟรี (ตั้งแต่ 1 กก.) และบริการเก็บเงินปลายทาง "
            "สนใจรับขนาดไหนแจ้งน้องบุกได้เลยนะคะ 😊🙏",
            "ขุดแชท_6ชม",
            None,
        )

    # Stage 3 (20 hours — Final nudge inside Facebook 24h window)
    if is_pending:
        return (
            "แจ้งเตือนรอบจัดส่งวันนี้ค่า 🚚✨ น้องบุกยังเก็บสิทธิ์โปรโมชั่นข้าวบุกสุขใจไว้ให้คุณลูกค้านะคะ|||"
            "หากต้องการให้จัดส่งรอบวันนี้ แจ้งชื่อ-ที่อยู่-เบอร์โทรคอนเฟิร์มกับน้องบุกได้เลยนะคะ 💚🙏",
            "ตามที่อยู่_20ชม",
            None,
        )
    return (
        "สวัสดีค่าคุณลูกค้า 🍚💚 วันนี้สิทธิ์โปรโมชั่นส่งฟรีสำหรับถุงใหญ่ 1 กก. (459.-) "
        "และโปรตุน 2 แถม 2 (899.-) ยังใช้ได้อยู่นะคะ|||"
        "ถ้าคุณลูกค้าสะดวกสั่งซื้อเมื่อไหร่ ทักแจ้งชื่อ-ที่อยู่-เบอร์โทร "
        "หรือเลือกเก็บปลายทางกับน้องบุกไว้ได้เลยนะคะ 😊🙏",
        "ขุดแชท_20ชม",
        "promo_3sizes",
    )


def get_session_reengage_status(psid: str) -> dict:
    """Inspect a session's message history and tags to determine its Ghost Re-engagement stage and eligibility."""
    user = database.get_or_create_session(psid)
    msgs = database.get_full_messages(psid, limit=80)
    now = datetime.now(timezone.utc)

    tags_str = user.broadcast_tags or ""
    notes_str = user.notes or ""
    if (
        getattr(user, "is_starred", False)
        or user.state == "completed"
        or "ชำระเงินแล้ว" in tags_str
        or "ติดดาว" in tags_str
        or "สั่งซื้อสำเร็จ" in tags_str
        or "#JST_ORDER:" in notes_str
    ):
        return {
            "psid": psid,
            "eligible": False,
            "reason": "ลูกค้าติดดาว ⭐ (สั่งซื้อ/ชำระเงินเรียบร้อยแล้ว — ห้ามขุดซ้ำ)",
            "state": user.state,
            "current_stage": 0,
            "hours_silent": 0.0,
        }

    # Find last customer message and any re-engage messages sent AFTER it
    last_user_dt: datetime | None = None
    last_any_dt: datetime | None = None
    current_stage = 0

    for m in msgs:
        dt_str = m.get("created_at")
        dt = None
        if dt_str:
            try:
                dt = datetime.fromisoformat(dt_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
            except Exception:
                dt = None
        if dt:
            last_any_dt = dt
        if m.get("role") == "user":
            if dt:
                last_user_dt = dt
            current_stage = 0  # Customer replied! Reset re-engagement stage
        else:
            lbl = m.get("sender_label") or ""
            if "AI บอทขุดแชท (รอบ 1)" in lbl:
                current_stage = max(current_stage, 1)
            elif "AI บอทขุดแชท (รอบ 2)" in lbl:
                current_stage = max(current_stage, 2)
            elif "AI บอทขุดแชท (รอบ 3)" in lbl:
                current_stage = max(current_stage, 3)

    if not last_user_dt:
        return {
            "psid": psid,
            "eligible": False,
            "reason": "ยังไม่มีข้อความจากลูกค้า",
            "state": user.state,
            "current_stage": 0,
            "hours_silent": 0.0,
        }

    hours_since_user = round((now - last_user_dt).total_seconds() / 3600.0, 2)
    hours_since_any = round((now - (last_any_dt or last_user_dt)).total_seconds() / 3600.0, 2)
    cfg = get_reengage_config()

    # Determine next stage to trigger automatically
    next_auto_stage = None
    if hours_since_user <= cfg["max_window_hours"] and hours_since_any >= 0.5:
        if current_stage == 0 and hours_since_user >= cfg["stage1_hours"]:
            next_auto_stage = 1
        elif current_stage == 1 and hours_since_user >= cfg["stage2_hours"]:
            next_auto_stage = 2
        elif current_stage == 2 and hours_since_user >= cfg["stage3_hours"]:
            next_auto_stage = 3

    return {
        "psid": psid,
        "eligible": True,
        "bot_enabled": bool(user.bot_enabled),
        "state": user.state,
        "current_stage": current_stage,
        "next_auto_stage": next_auto_stage,
        "hours_since_user_msg": hours_since_user,
        "hours_silent": hours_since_any,
        "within_24h_window": hours_since_user <= cfg["max_window_hours"],
        "broadcast_tags": tags_str,
    }


async def send_reengage_stage(
    psid: str,
    stage: int,
    public_base_url: str = "",
    force_manual: bool = False,
) -> dict:
    """Send Ghost Re-engagement Stage 1 (1h), Stage 2 (6h), or Stage 3 (20h) after verifying customer hasn't bought."""
    user = database.get_or_create_session(psid)

    # 1. Live Facebook Graph API sync before sending to ensure customer didn't already buy/pay!
    if user.platform == "facebook" and user.external_user_id:
        await messenger.sync_facebook_user_thread(user.external_user_id, brand_id=user.brand_id)
        user = database.get_or_create_session(psid)

    status_info = get_session_reengage_status(psid)
    if not status_info.get("eligible") and not force_manual:
        return {
            "status": "skipped",
            "psid": psid,
            "reason": status_info.get("reason", "ไม่เข้าเงื่อนไขการขุดแชท"),
        }
    if (
        getattr(user, "is_starred", False)
        or user.state == "completed"
        or "ชำระเงินแล้ว" in (user.broadcast_tags or "")
        or "ติดดาว" in (user.broadcast_tags or "")
        or "#JST_ORDER:" in (user.notes or "")
    ):
        return {
            "status": "skipped",
            "psid": psid,
            "reason": "ลูกค้าติดดาว ⭐ (ชำระเงิน/สั่งซื้อสำเร็จแล้ว) ระบบป้องกันไม่ให้ทักขุดซ้ำค่ะ",
        }

    msg_text, new_tag, img_key = build_reengage_message(stage, user.state)
    sender_label = f"AI บอทขุดแชท (รอบ {stage})"

    media_items = []
    if img_key:
        item = media_generator.get_media_item(img_key)
        if item:
            media_items = [item]

    for it in media_items:
        database.log_message(psid, "assistant", f"[IMAGE:{it['relative_url']}]", sender_label=sender_label)

    from .llm import split_into_bubbles

    bubbles = split_into_bubbles(msg_text)
    for b in bubbles:
        database.log_message(psid, "assistant", b, sender_label=sender_label)

    updated_tags = database._add_tag_str(user.broadcast_tags or "", new_tag)
    if stage == 3:
        updated_tags = database._add_tag_str(updated_tags, "ลูกค้าเงียบ")
    database.update_session_meta(psid=psid, broadcast_tags=updated_tags)
    database.mark_followup_sent(psid)

    await messenger.send_omnichannel_text(
        platform=user.platform,
        external_user_id=user.external_user_id,
        text=msg_text,
        brand_id=user.brand_id,
        media_items=media_items,
        public_base_url=public_base_url,
    )
    return {
        "status": "sent",
        "psid": psid,
        "customer_name": user.customer_name,
        "stage": stage,
        "added_tag": new_tag,
        "broadcast_tags": updated_tags,
        "bubbles": bubbles,
    }


async def run_auto_reengage_scan(public_base_url: str = "") -> dict:
    """Scan all active browsing/pending_payment sessions and trigger Stage 1/2/3 Ghost Re-engagement."""
    all_sessions = database.list_all_sessions()
    triggered = []
    skipped = 0

    for s in all_sessions:
        psid = s["psid"]
        if s.get("state") == "completed" or not s.get("bot_enabled", True):
            skipped += 1
            continue
        st = get_session_reengage_status(psid)
        next_stage = st.get("next_auto_stage")
        if st.get("eligible") and next_stage in (1, 2, 3):
            res = await send_reengage_stage(psid, next_stage, public_base_url=public_base_url, force_manual=False)
            if res.get("status") == "sent":
                triggered.append(
                    {
                        "psid": psid,
                        "customer_name": s.get("customer_name"),
                        "stage": next_stage,
                        "added_tag": res.get("added_tag"),
                    }
                )
            else:
                skipped += 1
        else:
            skipped += 1

    return {
        "status": "ok",
        "triggered_count": len(triggered),
        "triggered": triggered,
        "skipped_count": skipped,
    }


async def followup_loop(config: dict, public_base_url_getter=None) -> None:
    check_minutes = float(os.getenv("FOLLOWUP_CHECK_MINUTES", "15"))

    logger.info(
        "Follow-up, Ghost Re-engagement & After-Sales scheduler running: checking every %s min",
        check_minutes,
    )
    while True:
        try:
            pub_url = public_base_url_getter() if public_base_url_getter else os.getenv("PUBLIC_BASE_URL", "")

            # 0. Sync real Facebook conversation history & paid order status first!
            await messenger.sync_recent_facebook_conversations("buksukjai", limit=35)

            # 0.5 Auto-push newly confirmed orders into JST ERP (checks duplicates before saving!)
            importlib.reload(jst_erp)
            if jst_erp.is_auto_sync_enabled():
                await asyncio.to_thread(jst_erp.sync_all_confirmed_orders_to_jst, 2)

            # 1. Ghost / Silent Lead Re-engagement Bot (Stage 1: 1h, Stage 2: 6h, Stage 3: 20h)
            re_cfg = get_reengage_config()
            if re_cfg.get("auto_enabled", True):
                await run_auto_reengage_scan(public_base_url=pub_url)

            # 2. Post-Purchase After-Sales Care (Day 3, Day 5, Smart Depletion Day)
            now = datetime.now(timezone.utc)
            completed_users = database.get_completed_sessions_for_after_sales()
            for u in completed_users:
                paid_at = u.purchased_at or u.last_interaction_time
                if not paid_at:
                    continue
                if paid_at.tzinfo is None:
                    paid_at = paid_at.replace(tzinfo=timezone.utc)
                days_elapsed = (now - paid_at).total_seconds() / 86400.0
                sched = calculate_depletion_schedule(u.purchased_sku, u.purchased_qty)
                cur_stage = u.after_sales_stage or 0

                if cur_stage < 1 and days_elapsed >= sched["day_delivery_check"]:
                    await send_after_sales_stage(u.psid, 1, public_base_url=pub_url)
                elif cur_stage == 1 and days_elapsed >= sched["day_taste_check"]:
                    await send_after_sales_stage(u.psid, 2, public_base_url=pub_url)
                elif cur_stage == 2 and days_elapsed >= sched["day_depletion_reorder"]:
                    await send_after_sales_stage(u.psid, 3, public_base_url=pub_url)
        except Exception:
            logger.exception("Follow-up / Re-engagement / After-Sales scan failed; will retry next cycle")
        await asyncio.sleep(check_minutes * 60)


class PushJstRequest(BaseModel):
    sku_id: str | None = None
    qty: int | None = None
    unit_price: float | None = None
    freight: float | None = None
    is_cod: bool | None = None
    raw_address: str | None = None
    explicit_name: str | None = None
    phone: str | None = None
    slip_image_url: str | None = None
    force_create: bool = False


class JstConfigRequest(BaseModel):
    auto_sync_enabled: bool | None = None
    cookie: str | None = None


class ReengageConfigRequest(BaseModel):
    auto_enabled: bool | None = None
    stage1_hours: float | None = None
    stage2_hours: float | None = None
    stage3_hours: float | None = None


class TriggerReengageRequest(BaseModel):
    stage: int = 1
    force_manual: bool = True


def _register_jst_routes() -> None:
    """Dynamically attach JST ERP & Ghost Re-engagement endpoints onto the running FastAPI app instance on reload."""
    importlib.reload(jst_erp)
    main_mod = sys.modules.get("app.main")
    if not main_mod or not hasattr(main_mod, "app"):
        return
    fastapi_app = main_mod.app
    existing_paths = {getattr(r, "path", "") for r in fastapi_app.router.routes}

    if "/api/jst/sync-all" not in existing_paths:
        @fastapi_app.get("/api/sessions/{psid:path}/jst-preview")
        async def api_jst_preview(psid: str):
            ext = await asyncio.to_thread(jst_erp.extract_order_from_session, psid)
            if not ext.get("valid"):
                return {"valid": False, "reason": ext.get("reason")}
            dup = await asyncio.to_thread(jst_erp.check_duplicate_order, ext["phone"], 3)
            addr = await asyncio.to_thread(
                jst_erp.recognize_and_clean_address,
                ext["raw_address"],
                "",
                ext["phone"],
            )
            return {
                "valid": True,
                "extracted": ext,
                "duplicate_check": dup,
                "parsed_address": addr,
            }

        @fastapi_app.post("/api/sessions/{psid:path}/push-jst")
        async def api_push_session_to_jst(psid: str, body: PushJstRequest | None = None):
            overrides: dict[str, Any] = {}
            force = False
            if body:
                force = bool(body.force_create)
                for k in ("sku_id", "qty", "unit_price", "freight", "is_cod", "raw_address", "explicit_name", "phone", "slip_image_url"):
                    val = getattr(body, k, None)
                    if val is not None:
                        overrides[k] = val
            return await asyncio.to_thread(jst_erp.sync_session_to_jst, psid, overrides or None, force)

        @fastapi_app.post("/api/jst/sync-all")
        async def api_jst_sync_all(days_lookback: int = 2):
            await messenger.sync_recent_facebook_conversations("buksukjai", limit=40)
            res = await asyncio.to_thread(jst_erp.sync_all_confirmed_orders_to_jst, days_lookback)
            return {"status": "ok", **res}

        @fastapi_app.get("/api/jst/config")
        async def api_get_jst_config():
            return {
                "auto_sync_enabled": jst_erp.is_auto_sync_enabled(),
                "has_cookie": bool(jst_erp.get_jst_cookie()),
                "shop_id": jst_erp.JST_SHOP_ID,
                "warehouse_id": jst_erp.JST_WAREHOUSE_ID,
            }

        @fastapi_app.post("/api/jst/config")
        async def api_set_jst_config(body: JstConfigRequest):
            if body.auto_sync_enabled is not None:
                jst_erp.set_auto_sync_enabled(body.auto_sync_enabled)
            if body.cookie:
                jst_erp.set_jst_cookie(body.cookie)
            return {
                "status": "ok",
                "auto_sync_enabled": jst_erp.is_auto_sync_enabled(),
                "has_cookie": bool(jst_erp.get_jst_cookie()),
            }

    if "/api/reengage/config" not in existing_paths:
        @fastapi_app.get("/api/reengage/config")
        async def api_get_reengage_config():
            return get_reengage_config()

        @fastapi_app.post("/api/reengage/config")
        async def api_set_reengage_config(body: ReengageConfigRequest):
            updated = save_reengage_config(body.model_dump(exclude_none=True))
            return {"status": "ok", **updated}

        @fastapi_app.get("/api/sessions/{psid:path}/reengage-status")
        async def api_session_reengage_status(psid: str):
            return get_session_reengage_status(psid)

        @fastapi_app.post("/api/sessions/{psid:path}/reengage")
        async def api_trigger_session_reengage(psid: str, body: TriggerReengageRequest | None = None):
            stage = body.stage if body and body.stage in (1, 2, 3) else 1
            force_manual = body.force_manual if body else True
            pub_url = getattr(main_mod, "PUBLIC_BASE_URL", "")
            return await send_reengage_stage(psid, stage, public_base_url=pub_url, force_manual=force_manual)

        @fastapi_app.post("/api/reengage/scan-now")
        async def api_reengage_scan_now():
            await messenger.sync_recent_facebook_conversations("buksukjai", limit=40)
            pub_url = getattr(main_mod, "PUBLIC_BASE_URL", "")
            return await run_auto_reengage_scan(public_base_url=pub_url)


_register_jst_routes()
