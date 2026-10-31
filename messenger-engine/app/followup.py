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
        "ถ้าใกล้หมดแล้วและสนใจสั่งไปทานต่อเนื่อง ตอนนี้มีโปรโมชั่นชุดคุ้มส่งฟรีตามนี้เลยนะคะ\n\n"
        "• ถุงใหญ่ 1 กก. = โปร 459 บาท (โอนส่งฟรี!)\n\n"
        "• เซ็ตพกพา 20 ซอง = โปร 720 บาท (ส่งฟรี!)\n\n"
        "• โปรตุน 2 แถม 2 (1 กก. 2 ถุง + แถม 60g 2 ซอง) = โปร 899 บาท (ส่งฟรี!)\n\n"
        "• โปรตุน 3 แถม 3 (1 กก. 3 ถุง + แถม 60g 3 ซอง) = โปร 1,299 บาท (ส่งฟรี!)|||"
        "คุณลูกค้าสนใจรับชุดไหนไปทานต่อเนื่อง แจ้งน้องบุกได้เลยนะคะ 💚🙏",
        "ดูแลหลังการขาย_ครบกำหนด",
        None,
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

# Randomized multi-pattern message pools (Short 1-bubble / Medium 1-bubble / Long 2-bubble `|||`)
# 100% Ad-Safe & feminine polite particles (ค่ะ/คะ/นะคะ/ค่า)
REENGAGE_STAGE1_BROWSING_POOL: list[str] = [
    # 1. Short 1-bubble (Casual size check-in)
    "แอบแวะมาถามไถ่ค่า 😊 คุณลูกค้าดูข้าวบุกสุขใจไว้ เล็งเป็นขนาดทดลองหรือถุงใหญ่ทานคุ้มดีคะ?",
    # 2. Short 1-bubble (Easy 10-min preparation highlight)
    "เผื่อคุณลูกค้ายังลังเลเรื่องวิธีหุง 🍚 ข้าวบุกสุขใจแค่ตักใส่ถ้วย เติมน้ำร้อน ปิดฝา 10 นาทีก็นุ่มพร้อมทานเลยนะคะ ไม่ต้องซาวน้ำเลยค่า 💚",
    # 3. Medium 1-bubble (Texture & aroma reassurance)
    "ทักมาให้ข้อมูลเพิ่มเติมนิดนึงนะคะ 😊 ข้าวบุกสุขใจผสมข้าวหอมมะลิแท้ เนื้อสัมผัสนุ่มหนึบ หอมเหมือนข้าวสวยปกติเลยค่ะ มีทั้งแบบซองพกพา 60g และถุงใหญ่ 500g / 1 กก. เลือกตามมื้อที่ทานได้เลยนะคะ",
    # 4. Medium 1-bubble (Per-meal value breakdown)
    "คุณลูกค้าสนใจรับไปลองทานกี่มื้อดีคะ 🍚 ถ้าเน้นทานประจำที่บ้าน ถุงใหญ่ 1 กก. (459.- โอนส่งฟรี) จะเฉลี่ยตกมื้อละประมาณ 25 บาทเองค่ะ ประหยัดและอิ่มอยู่ท้องนานมากเลยนะคะ 💚",
    # 5. Long 2-bubble (Beginner popular choice)
    "คุณลูกค้าดูโปรโมชั่นไว้ พอจะมีขนาดไหนที่สนใจเป็นพิเศษไหมคะ 😊🍚|||"
    "ถ้าเพิ่งเริ่มลองทาน ลูกค้าส่วนใหญ่จะนิยม ถุงใหญ่ 1 กก. (459.- โอนส่งฟรี ทานได้ 16–20 มื้อ) "
    "หรือแบบซองพกพา 60g ค่ะ สงสัยตรงไหนถามน้องบุกได้เลยนะคะ 💚",
    # 6. Long 2-bubble (Everyday carb balance lifestyle)
    "สำหรับคุณลูกค้าที่อยากจัดสมดุลคาร์บแบบไม่ต้องอดข้าว 🌾 ข้าวบุกสุขใจช่วยให้มื้ออาหารอิ่มสบายท้องขึ้นเยอะเลยค่ะ|||"
    "ชอบแบบพกไปทานที่ทำงาน (ซอง 60g) หรือแบบตักแบ่งทานที่บ้าน (ถุง 500g / 1 กก.) แจ้งน้องบุกแนะนำโปรที่คุ้มที่สุดให้ได้เลยนะคะ 😊",
    # 7. Short 1-bubble (Open Q&A helper)
    "ติดขัดหรืออยากสอบถามรายละเอียดตรงไหนเพิ่มเติม พิมพ์ทิ้งไว้ให้น้องบุกได้เลยนะคะ ยินดีช่วยดูเซ็ตที่เหมาะกับมื้ออาหารให้ค่า 🙏💚",
    # 8. Medium 1-bubble (Dry storage & convenience)
    "แวะมาบอกเคล็ดลับความสะดวกค่า ✨ ข้าวบุกสุขใจเป็นแบบแห้ง เก็บในอุณหภูมิห้องได้นาน ไม่ต้องแช่เย็น จะตักชงน้ำร้อนมื้อไหนก็กะปริมาณง่ายมากค่ะ สนใจรับขนาดไหนทักน้องบุกได้ตลอดนะคะ 😊",
]

REENGAGE_STAGE1_PENDING_POOL: list[str] = [
    # 1. Short 1-bubble
    "คุณลูกค้าคะ 😊 หากสะดวกแล้ว แจ้งชื่อ-ที่อยู่-เบอร์โทร (หรือแนบสลิป) ให้น้องบุกจัดเตรียมพัสดุไว้ให้ได้เลยนะคะ 🚚💚",
    # 2. Short 1-bubble
    "น้องบุกจดรายการที่เลือกไว้ให้เรียบร้อยแล้วค่า 🍚 พิมพ์ชื่อ-ที่อยู่และเบอร์ติดต่อทิ้งไว้ในแชทได้เลยนะคะ",
    # 3. Medium 1-bubble
    "สำหรับออเดอร์ข้าวบุกสุขใจที่คุณลูกค้าเลือกไว้ ถ้าสะดวกจัดส่งที่ไหน แจ้งชื่อ ที่อยู่ และเบอร์โทรไว้ได้เลยนะคะ เดี๋ยวน้องบุกล็อกคิวแพ็คของให้เลยค่า 😊📦",
    # 4. Long 2-bubble
    "คุณลูกค้าคะ 😊 สำหรับออเดอร์ข้าวบุกสุขใจที่เลือกไว้|||"
    "หากสะดวกแล้วสามารถแจ้ง ชื่อ-ที่อยู่-เบอร์โทร (หรือส่งสลิปโอนเงิน) "
    "ให้น้องบุกจัดเตรียมพัสดุได้เลยนะคะ 🍚💚",
    # 5. Medium 1-bubble
    "แวะมาเช็กข้อมูลจัดส่งค่า 🚚 คุณลูกค้าสามารถพิมพ์ ชื่อ-ที่อยู่-เบอร์โทร บรรทัดเดียวกันส่งมาได้เลยนะคะ น้องบุกจัดการแยกข้อมูลเข้าระบบให้เองค่ะ 💚",
    # 6. Long 2-bubble
    "รายการข้าวบุกสุขใจที่คุณลูกค้าดูไว้พร้อมจัดส่งนะคะ 🌾✨|||"
    "สะดวกชำระแบบโอนเงินส่งฟรี (เมื่อครบโปร) หรือรับเป็นเก็บเงินปลายทาง แจ้งที่อยู่และเบอร์โทรให้น้องบุกได้เลยค่า 😊",
]

REENGAGE_STAGE2_BROWSING_POOL: list[str] = [
    # 1. Short 1-bubble (COD flexibility)
    "เผื่อคุณลูกค้าสะดวกชำระตอนรับของ ทางร้านมีบริการเก็บเงินปลายทาง (COD) ทุกขนาดเลยนะคะ สนใจรับชุดไหนแจ้งน้องบุกได้เลยค่า 🚚💚",
    # 2. Short 1-bubble (Zero konjac odor highlight)
    "หลายคนกังวลว่าข้าวบุกจะมีกลิ่นเฉพาะตัว 🍚 ของสุขใจไร้กลิ่นหัวบุก 100% เลยนะคะ หอมนุ่มทานคู่กับข้าวอะไรก็อร่อยค่ะ ลองสักชุดไหมคะ 😊",
    # 3. Medium 1-bubble (Calorie control & satiety)
    "ข้าวบุกสุขใจเหมาะกับมื้อที่อยากคุมแคลอรีและลดแป้งแบบสบายๆ ค่ะ 🌾 ตักชงน้ำร้อนแค่ 10 นาทีก็ได้ข้าวสวยร้อนๆ ทานอิ่มอยู่ท้องนาน ไม่หิวจุกจิกเลยนะคะ สนใจโปรไหนทักน้องบุกได้เลยค่า 💚",
    # 4. Long 2-bubble (Taste + payment options)
    "แวะมาแจ้งเพิ่มเติมเผื่อคุณลูกค้ากำลังตัดสินใจอยู่ค่า 🍚✨ "
    "ข้าวบุกสุขใจไม่มีกลิ่นหัวบุกเลยนะคะ หอมนุ่มเหมือนข้าวหอมมะลิแท้ "
    "แค่ตักเติมน้ำร้อนปิดฝา 10 นาทีก็ทานได้เลยค่ะ|||"
    "มีทั้งแบบโอนเงินส่งฟรี (ตั้งแต่ 1 กก.) และบริการเก็บเงินปลายทาง "
    "สนใจรับขนาดไหนแจ้งน้องบุกได้เลยนะคะ 😊🙏",
    # 5. Medium 1-bubble (Starter trial suggestion)
    "ถ้าคุณลูกค้ายังไม่แน่ใจว่าจะเริ่มขนาดไหน ลองเป็นชุดทดลอง 500 กรัม (239.-) หรือเซ็ตซองพกพา 60g ไปชิมความนุ่มก่อนได้นะคะ ทานง่ายมากค่ะ 😊🍚",
    # 6. Long 2-bubble (Busy day time-saver)
    "ข้อดีที่ลูกค้าชอบกันมากคือความสะดวกค่ะ ✨ วันไหนรีบๆ แค่กดน้ำร้อนใส่ถ้วยปิดฝาไว้ 10 นาที พอเตรียมกับข้าวเสร็จ ข้าวก็สุกนุ่มพอดีเลยค่ะ|||"
    "หากอยากลองรับไปทานดู แจ้งขนาดที่สนใจให้น้องบุกสรุปยอดที่คุ้มที่สุดให้ได้เลยนะคะ 💚",
    # 7. Short 1-bubble (Gentle comparison offer)
    "คุณลูกค้าพอจะมีเซ็ตที่ถูกใจหรือยังคะ 😊 ถ้าอยากให้น้องบุกช่วยเทียบความคุ้มแต่ละขนาด ทักบอกได้ตลอดเลยนะคะ 🌾",
    # 8. Medium 1-bubble (Stock-up bundle highlight)
    "สำหรับบ้านที่หุงทานทุกวัน ชุดตุน 1 กก. 2 แถม 2 (899.- ส่งฟรีทุกช่องทาง) จะเป็นเซ็ตที่คุ้มค่าที่สุดเลยค่ะ เก็บไว้ทานได้นาน สนใจรับโปรไหนแจ้งน้องบุกได้นะคะ 🙏💚",
]

REENGAGE_STAGE2_PENDING_POOL: list[str] = [
    # 1. Short 1-bubble
    "หากคุณลูกค้าไม่สะดวกโอนเงิน สามารถแจ้งเปลี่ยนเป็นเก็บเงินปลายทาง (COD) ได้เลยนะคะ พิมพ์ชื่อ-ที่อยู่-เบอร์โทรไว้ให้น้องบุกได้เลยค่า 🚚😊",
    # 2. Medium 1-bubble
    "ออเดอร์ข้าวบุกสุขใจที่คุยกันไว้ยังสามารถจัดส่งได้ตามปกตินะคะ 🍚 สะดวกเป็นโอนเงินหรือเก็บปลายทาง แจ้งที่อยู่และเบอร์ติดต่อให้น้องบุกดูแลต่อได้เลยค่ะ 💚",
    # 3. Long 2-bubble
    "สวัสดีค่ะคุณลูกค้า 🍚 ออเดอร์ข้าวบุกสุขใจยังค้างอยู่ในระบบนะคะ|||"
    "หากยังไม่สะดวกโอนเงิน สามารถแจ้งเปลี่ยนเป็นบริการเก็บเงินปลายทาง (COD) ได้เลยนะคะ "
    "สะดวกแบบไหนแจ้งน้องบุกได้เลยค่า 😊🙏",
    # 4. Short 1-bubble
    "แวะมาทวนออเดอร์ให้ค่า 📦 ถ้าคุณลูกค้าพร้อมให้จัดส่งแล้ว ส่งชื่อ-ที่อยู่-เบอร์โทร หรือสลิปโอนเงินไว้ในแชทได้เลยนะคะ 💚",
    # 5. Medium 1-bubble
    "เผื่อคุณลูกค้าติดธุระอยู่ ไม่ต้องรีบนะคะ 😊 เมื่อไหร่ที่สะดวก แจ้งชื่อ-ที่อยู่-เบอร์โทรทิ้งไว้ได้เลย เดี๋ยวน้องบุกจัดคิวส่งรอบถัดไปให้ทันทีค่ะ 🚚",
    # 6. Long 2-bubble
    "น้องบุกยังล็อกรายการสินค้าตามโปรโมชั่นไว้ให้อยู่นะคะ 🌾✨|||"
    "เปลี่ยนเป็นเก็บเงินปลายทางหน้าบ้านก็ได้เช่นกันค่ะ แจ้งชื่อ-ที่อยู่-เบอร์โทรไว้ได้เลยนะคะ 🙏💚",
]

REENGAGE_STAGE3_BROWSING_POOL: list[str] = [
    # 1. Short 1-bubble
    "แวะมาฝากโปรโมชั่นส่งท้ายไว้ให้ในแชทนะคะ 🍚💚 สะดวกสั่งซื้อข้าวบุกสุขใจวันไหน พิมพ์ชื่อ-ที่อยู่-เบอร์โทรทักน้องบุกมาได้ตลอดเลยค่า 😊",
    # 2. Medium 1-bubble
    "วันนี้สิทธิ์โปรโมชั่นข้าวบุกสุขใจ (ถุงใหญ่ 1 กก. 459.- โอนส่งฟรี / โปรตุน 2 แถม 2 ราคา 899.-) ยังใช้ได้ตามปกตินะคะ พร้อมรับเมื่อไหร่ทักแจ้งน้องบุกได้เลยค่า 🌾🙏",
    # 3. Long 2-bubble
    "สวัสดีค่าคุณลูกค้า 🍚💚 วันนี้สิทธิ์โปรโมชั่นส่งฟรีสำหรับถุงใหญ่ 1 กก. (459.-) "
    "และโปรตุน 2 แถม 2 (899.-) ยังใช้ได้อยู่นะคะ|||"
    "ถ้าคุณลูกค้าสะดวกสั่งซื้อเมื่อไหร่ ทักแจ้งชื่อ-ที่อยู่-เบอร์โทร "
    "หรือเลือกเก็บปลายทางกับน้องบุกไว้ได้เลยนะคะ 😊🙏",
    # 4. Short 1-bubble
    "น้องบุกเก็บสิทธิ์ราคาโปรโมชั่นไว้ให้ในแชทเรียบร้อยแล้วนะคะ ✨ อยากรับขนาดไหนไปดูแลมื้ออาหาร ทักเรียกน้องบุกได้ทุกเมื่อเลยค่ะ 💚",
    # 5. Medium 1-bubble
    "เผื่อคุณลูกค้ากำลังมองหาตัวช่วยลดแป้งที่ทานง่ายและอิ่มนาน ข้าวบุกสุขใจพร้อมส่งทุกขนาดเลยนะคะ สะดวกวันไหนแวะมาสั่งซื้อได้เสมอเลยค่า 😊🍚",
    # 6. Long 2-bubble
    "แวะมาส่งตารางโปรโมชั่นไว้ให้ดูประกอบการตัดสินใจนะคะ 🌾|||"
    "ไม่ว่าจะรับซองพกพา 60g ถุง 500g หรือถุงใหญ่ 1 กก. ทักแจ้งน้องบุกได้ตลอด 24 ชม. เลยนะคะ ยินดีบริการเสมอค่า 🙏💚",
]

REENGAGE_STAGE3_PENDING_POOL: list[str] = [
    # 1. Short 1-bubble
    "น้องบุกยังเก็บสิทธิ์โปรโมชั่นตามรายการที่คุยไว้ให้นะคะ 😊 สะดวกให้จัดส่งวันไหน แจ้งชื่อ-ที่อยู่-เบอร์โทรมาได้เลยค่า 🚚💚",
    # 2. Medium 1-bubble
    "สำหรับรายการข้าวบุกสุขใจที่เลือกไว้ หากคุณลูกค้าพร้อมรับสินค้าเมื่อไหร่ สามารถแจ้งที่อยู่จัดส่งหรือแนบสลิปโอนเงินให้น้องบุกได้ตลอดเลยนะคะ 🍚🙏",
    # 3. Long 2-bubble
    "แจ้งเตือนรอบจัดส่งวันนี้ค่า 🚚✨ น้องบุกยังเก็บสิทธิ์โปรโมชั่นข้าวบุกสุขใจไว้ให้คุณลูกค้านะคะ|||"
    "หากต้องการให้จัดส่งรอบวันนี้ แจ้งชื่อ-ที่อยู่-เบอร์โทรคอนเฟิร์มกับน้องบุกได้เลยนะคะ 💚🙏",
    # 4. Short 1-bubble
    "ออเดอร์ที่เลือกไว้ยังรับสิทธิ์ราคาเดิมได้อยู่นะคะ ✨ พร้อมให้จัดส่งเมื่อไหร่ พิมพ์ที่อยู่และเบอร์ติดต่อทิ้งไว้ให้น้องบุกได้เลยค่ะ 💚",
    # 5. Medium 1-bubble
    "แวะมาแจ้งว่าน้องบุกบันทึกโปรโมชั่นที่คุณลูกค้าเลือกไว้ให้แล้วนะคะ 😊 สะดวกชำระแบบโอนหรือเก็บปลายทาง ทักคอนเฟิร์มที่อยู่ได้ทุกเมื่อเลยค่า 🚚",
    # 6. Long 2-bubble
    "รอบจัดส่งวันนี้ยังทันนะคะคุณลูกค้า 📦✨|||"
    "หากสะดวกแล้ว พิมพ์ชื่อ-ที่อยู่-เบอร์โทรไว้ในแชทได้เลย เดี๋ยวน้องบุกรีบจัดส่งข้าวบุกสุขใจไปให้ค่ะ 🙏💚",
]

# Track non-repeating deck order per pool so consecutive customers never receive the same pattern
_POOL_DECKS: dict[str, list[int]] = {}


def _pick_unique_from_pool(pool_key: str, pool: list[str], psid: str = "") -> str:
    """Select a message variant using a shuffled deck so consecutive sends never repeat the same pattern."""
    import random

    if not pool:
        return ""
    deck = _POOL_DECKS.get(pool_key)
    if not deck:
        indices = list(range(len(pool)))
        random.shuffle(indices)
        _POOL_DECKS[pool_key] = indices
        deck = _POOL_DECKS[pool_key]
    idx = deck.pop(0)
    return pool[idx]


def detect_reengage_stage_from_text(text: str) -> int:
    """Detect whether an assistant message text belongs to Ghost Re-engagement Stage 1, 2, or 3.
    Survives container restarts and Facebook Graph API message syncs where sender_label was lost."""
    raw = " ".join(str(text or "").split())
    if not raw:
        return 0

    stage3_sigs = (
        "วันนี้สิทธิ์โปรโมชั่นส่งฟรีสำหรับถุงใหญ่",
        "แจ้งเตือนรอบจัดส่งวันนี้ค่า",
        "แวะมาฝากโปรโมชั่นส่งท้ายไว้ให้ในแชท",
        "วันนี้สิทธิ์โปรโมชั่นข้าวบุกสุขใจ",
        "น้องบุกเก็บสิทธิ์ราคาโปรโมชั่นไว้ให้ในแชท",
        "เผื่อคุณลูกค้ากำลังมองหาตัวช่วยลดแป้งที่ทานง่าย",
        "แวะมาส่งตารางโปรโมชั่นไว้ให้ดูประกอบการตัดสินใจ",
        "น้องบุกยังเก็บสิทธิ์โปรโมชั่นตามรายการที่คุยไว้",
        "สำหรับรายการข้าวบุกสุขใจที่เลือกไว้ หากคุณลูกค้าพร้อมรับสินค้าเมื่อไหร่",
        "ออเดอร์ที่เลือกไว้ยังรับสิทธิ์ราคาเดิมได้อยู่นะคะ",
        "แวะมาแจ้งว่าน้องบุกบันทึกโปรโมชั่นที่คุณลูกค้าเลือกไว้ให้แล้ว",
        "รอบจัดส่งวันนี้ยังทันนะคะคุณลูกค้า",
    )
    stage2_sigs = (
        "แวะมาแจ้งเพิ่มเติมเผื่อคุณลูกค้ากำลังตัดสินใจอยู่ค่า",
        "มีทั้งแบบโอนเงินส่งฟรี (ตั้งแต่ 1 กก.)",
        "ออเดอร์ข้าวบุกสุขใจยังค้างอยู่ในระบบนะคะ",
        "หากยังไม่สะดวกโอนเงิน สามารถแจ้งเปลี่ยนเป็นบริการเก็บเงินปลายทาง",
        "เผื่อคุณลูกค้าสะดวกชำระตอนรับของ ทางร้านมีบริการเก็บเงินปลายทาง",
        "หลายคนกังวลว่าข้าวบุกจะมีกลิ่นเฉพาะตัว",
        "ข้าวบุกสุขใจเหมาะกับมื้อที่อยากคุมแคลอรีและลดแป้งแบบสบายๆ",
        "ถ้าคุณลูกค้ายังไม่แน่ใจว่าจะเริ่มขนาดไหน ลองเป็นชุดทดลอง",
        "ข้อดีที่ลูกค้าชอบกันมากคือความสะดวกค่ะ",
        "คุณลูกค้าพอจะมีเซ็ตที่ถูกใจหรือยังคะ",
        "สำหรับบ้านที่หุงทานทุกวัน ชุดตุน 1 กก. 2 แถม 2",
        "หากคุณลูกค้าไม่สะดวกโอนเงิน สามารถแจ้งเปลี่ยนเป็นเก็บเงินปลายทาง",
        "ออเดอร์ข้าวบุกสุขใจที่คุยกันไว้ยังสามารถจัดส่งได้ตามปกติ",
        "แวะมาทวนออเดอร์ให้ค่า",
        "เผื่อคุณลูกค้าติดธุระอยู่ ไม่ต้องรีบนะคะ",
        "น้องบุกยังล็อกรายการสินค้าตามโปรโมชั่นไว้ให้อยู่นะคะ",
    )
    stage1_sigs = (
        "คุณลูกค้าดูโปรโมชั่นไว้ พอจะมีขนาดไหนที่สนใจเป็นพิเศษไหมคะ",
        "ถ้าเพิ่งเริ่มลองทาน ลูกค้าส่วนใหญ่จะนิยม",
        "สำหรับออเดอร์ข้าวบุกสุขใจที่เลือกไว้",
        "แอบแวะมาถามไถ่ค่า",
        "เผื่อคุณลูกค้ายังลังเลเรื่องวิธีหุง",
        "ทักมาให้ข้อมูลเพิ่มเติมนิดนึงนะคะ",
        "คุณลูกค้าสนใจรับไปลองทานกี่มื้อดีคะ",
        "สำหรับคุณลูกค้าที่อยากจัดสมดุลคาร์บแบบไม่ต้องอดข้าว",
        "ติดขัดหรืออยากสอบถามรายละเอียดตรงไหนเพิ่มเติม พิมพ์ทิ้งไว้ให้น้องบุก",
        "แวะมาบอกเคล็ดลับความสะดวกค่า",
        "หากสะดวกแล้ว แจ้งชื่อ-ที่อยู่-เบอร์โทร (หรือแนบสลิป) ให้น้องบุกจัดเตรียมพัสดุ",
        "น้องบุกจดรายการที่เลือกไว้ให้เรียบร้อยแล้วค่า",
        "สำหรับออเดอร์ข้าวบุกสุขใจที่คุณลูกค้าเลือกไว้ ถ้าสะดวกจัดส่งที่ไหน",
        "แวะมาเช็กข้อมูลจัดส่งค่า",
        "รายการข้าวบุกสุขใจที่คุณลูกค้าดูไว้พร้อมจัดส่งนะคะ",
    )

    if any(sig in raw for sig in stage3_sigs):
        return 3
    if any(sig in raw for sig in stage2_sigs):
        return 2
    if any(sig in raw for sig in stage1_sigs):
        return 1

    def _matches_pool(pool: list[str]) -> bool:
        for tpl in pool:
            for bubble in tpl.split("|||"):
                b_clean = " ".join(bubble.split())
                if len(b_clean) >= 18 and b_clean in raw:
                    return True
        return False

    if _matches_pool(REENGAGE_STAGE3_BROWSING_POOL) or _matches_pool(REENGAGE_STAGE3_PENDING_POOL):
        return 3
    if _matches_pool(REENGAGE_STAGE2_BROWSING_POOL) or _matches_pool(REENGAGE_STAGE2_PENDING_POOL):
        return 2
    if _matches_pool(REENGAGE_STAGE1_BROWSING_POOL) or _matches_pool(REENGAGE_STAGE1_PENDING_POOL):
        return 1
    return 0


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


def build_reengage_message(stage: int, state: str, psid: str = "") -> tuple[str, str, str | None]:
    """Build (message_text, broadcast_tag, optional_image_key) for Ghost Re-engagement Stage 1, 2, or 3
    using a shuffled non-repeating pool of short, medium, and 2-bubble patterns."""
    is_pending = state == "pending_payment"

    if stage == 1:
        if is_pending:
            msg = _pick_unique_from_pool("s1_pending", REENGAGE_STAGE1_PENDING_POOL, psid=psid)
            return msg, "ตามที่อยู่_1ชม", None
        msg = _pick_unique_from_pool("s1_browsing", REENGAGE_STAGE1_BROWSING_POOL, psid=psid)
        return msg, "ขุดแชท_1ชม", None

    if stage == 2:
        if is_pending:
            msg = _pick_unique_from_pool("s2_pending", REENGAGE_STAGE2_PENDING_POOL, psid=psid)
            return msg, "ตามที่อยู่_6ชม", None
        msg = _pick_unique_from_pool("s2_browsing", REENGAGE_STAGE2_BROWSING_POOL, psid=psid)
        return msg, "ขุดแชท_6ชม", None

    # Stage 3 (20 hours — Final nudge inside Facebook 24h window)
    if is_pending:
        msg = _pick_unique_from_pool("s3_pending", REENGAGE_STAGE3_PENDING_POOL, psid=psid)
        return msg, "ตามที่อยู่_20ชม", None
    msg = _pick_unique_from_pool("s3_browsing", REENGAGE_STAGE3_BROWSING_POOL, psid=psid)
    img_key = "promo_3sizes" if "ส่งตารางโปรโมชั่น" in msg else None
    return msg, "ขุดแชท_20ชม", img_key


def get_session_reengage_status(psid: str) -> dict:
    """Inspect a session's message history and tags to determine its Ghost Re-engagement stage and eligibility."""
    import re

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
        or "ยกเลิกออเดอร์" in tags_str
        or "ถาม อย." in tags_str
        or "#JST_ORDER:" in notes_str
    ):
        return {
            "psid": psid,
            "eligible": False,
            "reason": "ลูกค้าติดดาว ⭐ / ชำระเงินแล้ว / หรือยกเลิกออเดอร์แล้ว — ระบบบล็อกไม่ให้ทักขุดซ้ำค่ะ",
            "state": user.state,
            "current_stage": 0,
            "hours_silent": 0.0,
        }

    # Check message history for customer slip attachment, transfer confirmation, cancellation, or shipping address/phone
    user_texts_joined = "\n".join(
        str(m.get("content") or "") for m in msgs if m.get("role") == "user"
    ).lower()
    if any(
        k in user_texts_joined
        for k in ("[image:", "โอนแล้ว", "ส่งสลิป", "แนบสลิป", "ส่งการชำระเงินจำนวน", "ขอยกเลิก", "ไม่เอาแล้ว", "ยกเลิกค่ะ", "ยกเลิกครับ")
    ):
        return {
            "psid": psid,
            "eligible": False,
            "reason": "ตรวจพบสลิปโอนเงินหรือข้อความขอยกเลิกในประวัติแชท — ป้องกันการทักขุดซ้ำค่ะ",
            "state": user.state,
            "current_stage": 0,
            "hours_silent": 0.0,
        }

    # Block re-engagement if customer already provided a 10-digit Thai phone number or full address (e.g. COD order)
    has_thai_phone = bool(re.search(r"(?:\+66\s*0?|0)[689]\d(?:[\s\-]*\d){7}", user_texts_joined))
    has_address_kw = sum(
        1 for kw in ("ตำบล", "อำเภอ", "จังหวัด", "ต.", "อ.", "จ.", "หมู่", "ซอย", "ถนน", "แขวง", "เขต")
        if kw in user_texts_joined
    ) >= 2
    all_bot_texts = "\n".join(
        str(m.get("content") or "") for m in msgs if m.get("role") in ("assistant", "admin")
    )
    has_order_confirmed_reply = any(
        kw in all_bot_texts
        for kw in ("#BUY", "ได้รับข้อมูลจัดส่ง", "จัดเตรียมพัสดุให้เรียบร้อย", "เพจ : ข้าวบุก สุขใจ")
    )
    if has_thai_phone or has_address_kw or has_order_confirmed_reply:
        return {
            "psid": psid,
            "eligible": False,
            "reason": "ลูกค้าแจ้งชื่อ-ที่อยู่-เบอร์โทร หรือยืนยันออเดอร์เรียบร้อยแล้ว — ระบบบล็อกไม่ให้ทักขุดซ้ำค่ะ",
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
            else:
                detected_stage = detect_reengage_stage_from_text(str(m.get("content") or ""))
                if detected_stage > 0:
                    current_stage = max(current_stage, detected_stage)

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

    # Determine next stage to trigger automatically with STRICT minimum spacing between stages:
    # - Stage 1: >= stage1_hours (1h) since user msg AND >= 1.0h since last bot msg
    # - Stage 2: >= stage2_hours (6h) since user msg AND >= 5.0h since Stage 1 (never 30 mins after Stage 1!)
    # - Stage 3: >= stage3_hours (20h) since user msg AND >= 12.0h since Stage 2
    next_auto_stage = None
    if hours_since_user <= cfg["max_window_hours"]:
        if current_stage == 0 and hours_since_user >= cfg["stage1_hours"] and hours_since_any >= 1.0:
            next_auto_stage = 1
        elif current_stage == 1 and hours_since_user >= cfg["stage2_hours"] and hours_since_any >= 5.0:
            next_auto_stage = 2
        elif current_stage == 2 and hours_since_user >= cfg["stage3_hours"] and hours_since_any >= 12.0:
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

    # 1. Live Facebook Graph API sync before sending to ensure customer didn't already buy/pay or already get re-engaged!
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
    # Prevent sending a duplicate or lower/equal stage in auto mode after live sync
    if not force_manual:
        live_current_stage = int(status_info.get("current_stage") or 0)
        live_next_stage = status_info.get("next_auto_stage")
        if live_current_stage >= stage or live_next_stage != stage:
            return {
                "status": "skipped",
                "psid": psid,
                "reason": f"ซิงค์แชทล่าสุดแล้วพบว่าอยู่รอบ {live_current_stage} (ยังไม่ถึงเกณฑ์ส่งรอบ {stage} ซ้ำค่ะ)",
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

    msg_text, new_tag, img_key = build_reengage_message(stage, user.state, psid=psid)
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
    """Scan all active browsing/pending_payment sessions and trigger Stage 1/2/3 Ghost Re-engagement.
    Capped at max 3 sends per scan cycle with staggered delays and shuffled templates."""
    import asyncio
    import random

    all_sessions = database.list_all_sessions()
    triggered = []
    skipped = 0
    max_per_cycle = 3

    for s in all_sessions:
        if len(triggered) >= max_per_cycle:
            break
        psid = s["psid"]
        if s.get("state") == "completed" or not s.get("bot_enabled", True):
            skipped += 1
            continue
        st = get_session_reengage_status(psid)
        next_stage = st.get("next_auto_stage")
        if st.get("eligible") and next_stage in (1, 2, 3):
            if triggered:
                await asyncio.sleep(random.uniform(1.5, 3.5))
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


_AUTO_REPLIED_FB_SIGS: set[str] = set()


async def auto_reply_unanswered_facebook_chats(
    max_age_minutes: float = 60.0,
    min_wait_seconds: float = 35.0,
) -> list[dict]:
    """Fallback active auto-responder for Facebook Page conversations via Graph API polling.

    Ensures that even if Meta Webhooks do not fire (or when the user's PC is turned off overnight),
    any customer who messages the Facebook Page or triggers a comment-to-messenger stub
    receives an AI response automatically within ~35–60 seconds.
    """
    main_mod = sys.modules.get("app.main")
    if not main_mod or not hasattr(main_mod, "process_omnichannel_message"):
        return []

    now_utc = datetime.now(timezone.utc)
    all_sessions = database.list_all_sessions()
    replied_list: list[dict] = []

    for s in all_sessions:
        if s.get("platform") != "facebook":
            continue
        if not s.get("bot_enabled", True) or s.get("state") == "completed":
            continue
        ext_id = str(s.get("external_user_id") or "")
        if not ext_id or "_test_" in ext_id or ext_id.startswith("FB"):
            continue

        psid = s["psid"]
        msgs = database.get_full_messages(psid, limit=30)
        if not msgs:
            continue

        last_msg = msgs[-1]
        last_role = str(last_msg.get("role") or "")
        last_content = str(last_msg.get("content") or "").strip()
        last_dt_str = str(last_msg.get("created_at") or "")
        if not last_dt_str:
            continue

        try:
            last_dt = datetime.fromisoformat(last_dt_str.replace("+0000", "+00:00"))
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue

        age_sec = (now_utc - last_dt).total_seconds()
        if age_sec < min_wait_seconds or age_sec > (max_age_minutes * 60.0):
            continue

        is_comment_auto_stub = (
            last_role in ("assistant", "admin")
            and (
                "สวัสดีค่ะน้องแอดมินส่งรายละเอียดเพิ่มเติมให้นะคะ" in last_content
                or "คุณกำลังตอบกลับความคิดเห็นของผู้ใช้ต่อโพสต์บนเพจของคุณ" in last_content
            )
        )
        if last_role != "user" and not is_comment_auto_stub:
            continue

        sig = f"{psid}:{last_dt_str}:{last_content[:80]}"
        if sig in _AUTO_REPLIED_FB_SIGS:
            continue

        # Collect trailing consecutive user messages if customer sent multiple lines
        if is_comment_auto_stub:
            trigger_text = "สนใจ ขอรายละเอียดโปรโมชั่นค่ะ"
        else:
            trailing_user_lines: list[str] = []
            for m in reversed(msgs):
                if m.get("role") == "user":
                    c = str(m.get("content") or "").strip()
                    if c.startswith("[IMAGE:"):
                        trailing_user_lines.append("[ลูกค้าแนบสลิปเข้ามาในแชทค่ะ]")
                    elif c:
                        trailing_user_lines.append(c)
                else:
                    break
            trailing_user_lines.reverse()
            trigger_text = "\n".join(trailing_user_lines).strip() or last_content

        if not trigger_text:
            continue

        _AUTO_REPLIED_FB_SIGS.add(sig)
        logger.info(
            "Graph API Active Auto-Responder replying to unanswered Facebook chat %s (%s): %s",
            psid,
            s.get("customer_name"),
            trigger_text[:80],
        )
        try:
            res = await main_mod.process_omnichannel_message(
                brand_id=s.get("brand_id") or "buksukjai",
                platform="facebook",
                external_user_id=ext_id,
                text=trigger_text,
                customer_name=s.get("customer_name") or "",
                skip_user_log=True,
            )
            replied_list.append(
                {
                    "psid": psid,
                    "customer_name": s.get("customer_name"),
                    "trigger_text": trigger_text,
                    "bot_replied": res.get("bot_replied"),
                }
            )
        except Exception as exc:
            logger.warning("Auto-reply failed for %s: %s", psid, exc)

    return replied_list


async def followup_loop(config: dict, public_base_url_getter=None) -> None:
    try:
        _register_jst_routes()
    except Exception as exc:
        logger.warning("Route registration warning: %s", exc)
    poll_seconds = float(os.getenv("FOLLOWUP_POLL_SECONDS", "60"))
    render_health_url = os.getenv("RENDER_EXTERNAL_URL", "https://buksukjai-omnichannel.onrender.com") + "/health"

    logger.info(
        "24/7 Cloud Scheduler & Graph API Auto-Responder running: polling every %s sec",
        poll_seconds,
    )
    cycle_idx = 0
    while True:
        try:
            import httpx

            pub_url = public_base_url_getter() if public_base_url_getter else os.getenv("PUBLIC_BASE_URL", "")

            # 0.0 Keep Render cloud container warm 24/7 (prevents Render 15-min spin-down when PC is off)
            try:
                async with httpx.AsyncClient(timeout=8.0) as _ka_client:
                    await _ka_client.get(render_health_url)
            except Exception:
                pass

            # 0.1 Sync latest Facebook conversations & auto-reply to any unanswered customer messages!
            await messenger.sync_recent_facebook_conversations("buksukjai", limit=25)
            await auto_reply_unanswered_facebook_chats(max_age_minutes=60.0, min_wait_seconds=35.0)

            # 0.2 Daily 01:00 AM Sales & Stock Reconciliation Summary (สรุปยอดขายของเมื่อวานทุกวันเวลา 01:00 น.)
            from . import daily_sheet_report

            should_rep, yest_date = daily_sheet_report.should_run_daily_1am_report()
            if should_rep:
                logger.info("Running Daily 01:00 AM (BKK) Sales & Stock Summary for %s...", yest_date)
                await asyncio.to_thread(daily_sheet_report.load_or_build_daily_report, yest_date)

            # 0.5 Daily 06:00 AM Batch Keying into JST ERP (คีย์ข้อมูลวันละ 1 ครั้ง ตอน 06:00 น. เวลาไทย รวบรวมออเดอร์ของเมื่อวาน)
            importlib.reload(jst_erp)
            if jst_erp.should_run_daily_6am_sync():
                logger.info("Running Daily 06:00 AM (BKK) JST ERP Batch Order Sync...")
                await messenger.sync_recent_facebook_conversations("buksukjai", limit=60)
                await asyncio.to_thread(jst_erp.sync_all_confirmed_orders_to_jst, 2, True)
                # Refresh Google Sheet after 06:00 AM keying finishes
                await asyncio.to_thread(daily_sheet_report.load_or_build_daily_report, yest_date)

            # 0.65 Daily 07:00 AM LINE Work Group Report (แจ้งสรุปยอดขายแต่ละช่องทาง โอน/COD และตัดสต็อกโกดังในกลุ่มไลน์งานหลังคีย์เสร็จ)
            importlib.reload(daily_sheet_report)
            should_line_7am, yest_7am = daily_sheet_report.should_run_daily_7am_line_report()
            if should_line_7am:
                logger.info("Running Daily 07:00 AM (BKK) LINE Work Group Summary for %s...", yest_7am)
                await asyncio.to_thread(
                    daily_sheet_report.send_daily_summary_to_line_groups,
                    yest_7am,
                    "workbot",
                    None,
                    None,
                    True,
                )

            # Heavy background scans run every 10 cycles (~10 minutes)
            if cycle_idx % 10 == 0:
                # 0.6 Smart Slip Verifier & Auto-Confirm (ตรวจสลิปที่ติด Fail เวลาชำระเงินไม่ตรงกัน แล้วกดยืนยันให้อัตโนมัติ)
                await asyncio.to_thread(jst_erp.verify_and_auto_confirm_jst_slips, 40)

                # 0.7 2-Stage Automated Parcel Tracking Notifier (แจ้งเลขพัสดุเมื่อขนส่งเข้ารับแล้ว & แจ้งเมื่อพัสดุส่งถึงมือลูกค้าพร้อมเวลา)
                from . import parcel_tracker

                importlib.reload(parcel_tracker)
                await parcel_tracker.check_and_send_parcel_tracking_updates(public_base_url=pub_url)

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
        cycle_idx += 1
        await asyncio.sleep(poll_seconds)


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
                **jst_erp.get_daily_sync_state(),
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

    if "/api/jst/sync-tracking" not in existing_paths:
        @fastapi_app.get("/api/jst/tracking-status")
        async def api_jst_tracking_status():
            from . import parcel_tracker

            return parcel_tracker.get_tracking_state()

        @fastapi_app.post("/api/jst/sync-tracking")
        async def api_jst_sync_tracking(dry_run: bool = False):
            from . import parcel_tracker

            pub_url = getattr(main_mod, "PUBLIC_BASE_URL", "")
            return await parcel_tracker.check_and_send_parcel_tracking_updates(
                public_base_url=pub_url,
                dry_run=dry_run,
            )

        @fastapi_app.post("/api/jst/verify-slips")
        async def api_jst_verify_slips():
            return await asyncio.to_thread(jst_erp.verify_and_auto_confirm_jst_slips, 50)


_register_jst_routes()
