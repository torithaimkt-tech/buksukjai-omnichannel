"""Omnichannel Send API client + webhook signature verification
for Facebook Messenger, Instagram DM, LINE Official Account (Messaging API), and Web Chat.

Supports Multi-Bubble Thai Chat Style + Image Sending:
- Splits replies on `|||` into 2–3 short, natural chat bubbles (with zero asterisks).
- Sends images (Promo Catalog, Product Photo, How-to-Cook, Payment QR, or Custom Admin Uploads)
  across LINE OA (HTTPS URL in Reply/Push API) and Facebook Messenger/IG (Direct Multipart Upload + URL fallback).
"""

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path

import httpx

from .config_loader import get_page_by_brand_id
from .llm import clean_chat_text, split_into_bubbles

logger = logging.getLogger(__name__)

GRAPH_API_URL = "https://graph.facebook.com/v21.0/me/messages"
LINE_REPLY_URL = "https://api.line.me/v2/bot/message/reply"
LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"
MESSENGER_CHAR_LIMIT = 2000


def _chunk(text: str, limit: int = MESSENGER_CHAR_LIMIT) -> list[str]:
    """Messenger rejects messages over 2000 chars — split on line breaks when possible."""
    if len(text) <= limit:
        return [text]
    chunks, current = [], ""
    for line in text.split("\n"):
        while len(line) > limit:
            chunks.append(line[:limit])
            line = line[limit:]
        if len(current) + len(line) + 1 > limit:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks


def _get_channel_token(brand_id: str, platform: str) -> str:
    page = get_page_by_brand_id(brand_id)
    channels = page.get("channels", {})
    if platform == "line":
        return channels.get("line_channel_access_token") or os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
    if platform == "instagram":
        return (
            channels.get("ig_access_token")
            or channels.get("fb_page_access_token")
            or os.getenv("IG_ACCESS_TOKEN")
            or os.getenv("PAGE_ACCESS_TOKEN", "")
        )
    return channels.get("fb_page_access_token") or os.getenv("PAGE_ACCESS_TOKEN", "")


async def send_omnichannel_text(
    platform: str,
    external_user_id: str,
    text: str,
    brand_id: str = "buksukjai",
    reply_token: str | None = None,
    image_url: str | None = None,
    image_local_path: str | None = None,
    media_items: list[dict] | None = None,
    public_base_url: str = "",
) -> None:
    """Send optional promo image(s) FIRST, followed by 1–2 short chat bubbles to LINE OA, Facebook Messenger, IG, or Web."""
    bubbles = split_into_bubbles(text)
    resolved_items: list[dict] = []
    if media_items:
        for it in media_items:
            rel = it.get("relative_url", "")
            full_url = it.get("public_url") or (f"{public_base_url}{rel}" if (public_base_url and rel) else image_url)
            resolved_items.append({"image_url": full_url, "image_local_path": it.get("local_path")})
    elif image_url or image_local_path:
        resolved_items.append({"image_url": image_url, "image_local_path": image_local_path})

    if platform == "web" or (reply_token and reply_token.startswith("sim_")) or "_test_" in external_user_id:
        logger.info(
            "[SIMULATOR / WEB | %s/%s] reply (%d images + %d bubbles) to %s:\n%s",
            brand_id,
            platform,
            len(resolved_items),
            len(bubbles),
            external_user_id,
            "\n---\n".join(bubbles),
        )
        return

    token = _get_channel_token(brand_id, platform)
    if not token:
        logger.info(
            "[LOCAL DEV — no %s token for %s] reply (%d bubbles) to %s:\n%s",
            platform.upper(),
            brand_id,
            len(bubbles),
            external_user_id,
            "\n---\n".join(bubbles),
        )
        return

    if platform == "line":
        await _send_line_message(token, external_user_id, bubbles, reply_token, media_items=resolved_items)
    else:
        await _send_meta_message(
            token,
            external_user_id,
            bubbles,
            platform,
            media_items=resolved_items,
        )


async def send_omnichannel_image(
    platform: str,
    external_user_id: str,
    image_url: str | None = None,
    image_local_path: str | None = None,
    brand_id: str = "buksukjai",
    reply_token: str | None = None,
) -> None:
    """Send a standalone image to LINE OA, Facebook Messenger, or Instagram DM."""
    if platform == "web" or (reply_token and reply_token.startswith("sim_")) or "_test_" in external_user_id:
        logger.info("[SIMULATOR / WEB | %s/%s] image sent to %s: %s", brand_id, platform, external_user_id, image_url or image_local_path)
        return

    token = _get_channel_token(brand_id, platform)
    if not token:
        logger.warning("No %s token for %s — skipping image send", platform, brand_id)
        return

    if platform == "line":
        if not image_url or not image_url.startswith("https://"):
            logger.warning("LINE OA requires an HTTPS image_url (got %s)", image_url)
            return
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        msg_obj = {
            "type": "image",
            "originalContentUrl": image_url,
            "previewImageUrl": image_url,
        }
        async with httpx.AsyncClient(timeout=15) as client:
            if reply_token and not reply_token.startswith("sim_"):
                resp = await client.post(
                    LINE_REPLY_URL,
                    headers=headers,
                    json={"replyToken": reply_token, "messages": [msg_obj]},
                )
                if resp.status_code == 200:
                    return
            resp = await client.post(
                LINE_PUSH_URL,
                headers=headers,
                json={"to": external_user_id, "messages": [msg_obj]},
            )
            if resp.status_code != 200:
                logger.error("LINE Image Push error %s: %s", resp.status_code, resp.text)
    else:
        async with httpx.AsyncClient(timeout=20) as client:
            await _send_meta_image_only(client, token, external_user_id, image_url, image_local_path, platform)


async def _send_line_message(
    channel_access_token: str,
    user_id: str,
    bubbles: list[str],
    reply_token: str | None = None,
    media_items: list[dict] | None = None,
) -> None:
    headers = {
        "Authorization": f"Bearer {channel_access_token}",
        "Content-Type": "application/json",
    }
    expanded_chunks: list[str] = []
    for b in bubbles:
        expanded_chunks.extend(_chunk(clean_chat_text(b), limit=4500))

    clean_texts = [c for c in expanded_chunks if c.strip()]
    img_objs: list[dict] = []
    for it in media_items or []:
        u = it.get("image_url") or ""
        if u.startswith("https://"):
            img_objs.append(
                {
                    "type": "image",
                    "originalContentUrl": u,
                    "previewImageUrl": u,
                }
            )

    messages_payload: list[dict] = []
    if img_objs:
        # Always place promo image(s) FIRST, followed by 1–2 short accompanying text bubbles!
        # LINE allows max 5 message objects per reply/push call.
        messages_payload.extend(img_objs[:4])
        remaining_slots = 5 - len(messages_payload)
        if clean_texts and remaining_slots > 0:
            if len(clean_texts) <= remaining_slots:
                messages_payload.extend({"type": "text", "text": t} for t in clean_texts)
            else:
                head = clean_texts[: remaining_slots - 1]
                tail = "\n\n".join(clean_texts[remaining_slots - 1 :])
                messages_payload.extend({"type": "text", "text": t} for t in head)
                messages_payload.append({"type": "text", "text": tail})
    else:
        messages_payload = [{"type": "text", "text": t} for t in clean_texts[:5]]

    if not messages_payload:
        return

    async with httpx.AsyncClient(timeout=15) as client:
        if reply_token and not reply_token.startswith("sim_"):
            resp = await client.post(
                LINE_REPLY_URL,
                headers=headers,
                json={"replyToken": reply_token, "messages": messages_payload[:5]},
            )
            if resp.status_code == 200:
                return
            logger.warning("LINE replyToken failed (%s: %s), falling back to Push API", resp.status_code, resp.text)

        resp = await client.post(
            LINE_PUSH_URL,
            headers=headers,
            json={"to": user_id, "messages": messages_payload[:5]},
        )
        if resp.status_code != 200:
            logger.error("LINE Push API error %s: %s", resp.status_code, resp.text)


async def _send_meta_image_only(
    client: httpx.AsyncClient,
    token: str,
    recipient_id: str,
    image_url: str | None,
    image_local_path: str | None,
    platform: str = "facebook",
) -> None:
    """Send image to Facebook Messenger / IG via direct file upload first, or HTTPS URL fallback."""
    if image_local_path and Path(image_local_path).exists():
        path_obj = Path(image_local_path)
        mime = "image/png" if path_obj.suffix.lower() == ".png" else "image/jpeg"
        try:
            with open(path_obj, "rb") as f:
                resp = await client.post(
                    GRAPH_API_URL,
                    params={"access_token": token},
                    data={
                        "recipient": json.dumps({"id": recipient_id}),
                        "messaging_type": "RESPONSE",
                        "message": json.dumps({"attachment": {"type": "image", "payload": {"is_reusable": True}}}),
                    },
                    files={"filedata": (path_obj.name, f, mime)},
                )
                if resp.status_code == 200:
                    return
                logger.warning("%s direct image upload returned %s: %s", platform.upper(), resp.status_code, resp.text)
        except Exception as e:
            logger.warning("%s direct image upload failed: %s", platform.upper(), e)

    if image_url and image_url.startswith("https://"):
        resp = await client.post(
            GRAPH_API_URL,
            params={"access_token": token},
            json={
                "recipient": {"id": recipient_id},
                "messaging_type": "RESPONSE",
                "message": {
                    "attachment": {
                        "type": "image",
                        "payload": {"url": image_url, "is_reusable": True},
                    }
                },
            },
        )
        if resp.status_code != 200:
            logger.error("%s Image URL Send error %s: %s", platform.upper(), resp.status_code, resp.text)


async def _send_meta_message(
    token: str,
    recipient_id: str,
    bubbles: list[str],
    platform: str = "facebook",
    media_items: list[dict] | None = None,
) -> None:
    expanded_chunks: list[str] = []
    for b in bubbles:
        expanded_chunks.extend(_chunk(clean_chat_text(b), limit=MESSENGER_CHAR_LIMIT))

    clean_chunks = [c for c in expanded_chunks if c.strip()]

    async with httpx.AsyncClient(timeout=25) as client:
        # 1. Always send the promo image(s) FIRST!
        for idx, it in enumerate(media_items or []):
            if idx > 0:
                await asyncio.sleep(0.2)
            await _send_meta_image_only(
                client,
                token,
                recipient_id,
                it.get("image_url"),
                it.get("image_local_path"),
                platform,
            )

        # 2. Then send the 1–2 short accompanying text bubbles right after!
        for idx, chunk in enumerate(clean_chunks):
            if idx > 0 or media_items:
                await asyncio.sleep(0.25)
            resp = await client.post(
                GRAPH_API_URL,
                params={"access_token": token},
                json={
                    "recipient": {"id": recipient_id},
                    "messaging_type": "RESPONSE",
                    "message": {"text": chunk},
                },
            )
            if resp.status_code != 200 and platform == "facebook":
                # Fallback to POST_PURCHASE_UPDATE tag for Day 3 / Day 5 / After-Sales check-ins beyond 24h window
                resp2 = await client.post(
                    GRAPH_API_URL,
                    params={"access_token": token},
                    json={
                        "recipient": {"id": recipient_id},
                        "messaging_type": "MESSAGE_TAG",
                        "tag": "POST_PURCHASE_UPDATE",
                        "message": {"text": chunk},
                    },
                )
                if resp2.status_code == 200:
                    continue
            if resp.status_code != 200:
                logger.error("%s Send API error %s: %s", platform.upper(), resp.status_code, resp.text)


async def send_text(psid: str, text: str) -> None:
    """Backward-compatible helper that parses composite session keys `brand:platform:ext_id`."""
    if ":" in psid:
        parts = psid.split(":", 2)
        if len(parts) == 3:
            brand_id, platform, ext_id = parts
            await send_omnichannel_text(platform, ext_id, text, brand_id=brand_id)
            return
    await send_omnichannel_text("facebook", psid, text, brand_id="buksukjai")


def verify_signature(raw_body: bytes, signature_header: str | None) -> bool:
    """Validate Meta X-Hub-Signature-256 against META_APP_SECRET."""
    app_secret = os.getenv("META_APP_SECRET")
    if not app_secret:
        return True
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header.removeprefix("sha256="))


def verify_line_signature(raw_body: bytes, signature_header: str | None, brand_id: str = "buksukjai") -> bool:
    """Validate LINE X-Line-Signature (base64 HMAC-SHA256) against LINE_CHANNEL_SECRET."""
    page = get_page_by_brand_id(brand_id)
    secret = page.get("channels", {}).get("line_channel_secret") or os.getenv("LINE_CHANNEL_SECRET", "")
    if not secret:
        return True  # skip in local dev if secret is not configured
    if not signature_header:
        return False
    hash_bytes = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
    expected = base64.b64encode(hash_bytes).decode("utf-8")
    return hmac.compare_digest(expected, signature_header)


# --- Facebook Graph API Real-Time Conversation & Order Verification Sync --------

PAID_ORDER_MARKERS = (
    "ทำเครื่องหมายคำสั่งซื้อว่าชำระเงินแล้ว",
    "ส่งการชำระเงินจำนวน ฿",
    "ตรวจสอบสลิปเรียบร้อยแล้ว",
    "ขอบคุณที่เลือกข้าวบุกสุขใจนะคะ",
    "วิธีทำข้าวบุกสุขใจนะคะ",
    "facebook.com/share/r/17favnhvpd",
    "#buy",
    "ส่งข้อมูลเข้าคลังจัดส่งให้ทันที",
    "ขนส่ง j&t",
    "ขนส่งj&t",
    "รอรับสินค้า",
    "บันทึกที่อยู่จัดส่งเรียบร้อย",
    "ชำระเงิน : ปลายทาง",
    "ชำระเงิน: ปลายทาง",
)

# Verified starred (⭐ / FOLLOW_UP) customers from Meta Business Suite who have already bought from us
STARRED_META_NAMES = {
    "Jiraporn Saengon",
    "Piyama Singkaravanich",
    "โสภา ศรีสุข",
    "แร๊คดอล แมวป่วน",
    "Meka Nakin",
    "นิภารัตน แสงเพิ่ม",
    "เนาวรัตน์ เงินทิพย์",
    "Pussadee Rattanapimol",
    "แกงส้ม’ ที่รัก",
    "แกงส้ม' ที่รัก",
    "Aomjai Kanyapha",
    "ฅน ไกลบ้าน",
    "อุมัร ซอฟียะห์",
    "Shinbi Valeeplang",
    "แม่ชีต้าห์ กะ โชกุน",
    "อาบูบากัร พูลสวัสดิ์",
    "แมว รุ่งเรืองยางยนต์ ลำปาง",
    "Pattamawadee Noppawong",
    "IlOs Sangayut",
    "ทับทิม ศรีจันแดง",
    "ดวงหทัย ดวงมาลัย",
    "ศศิกร สุวรรณอักษร",
    "Anurak Kongwong",
    "Patporn Swan",
    "พลอย พิศมัย",
    "วาสนา ยังพิทักษ",
    "Jaithipfaiizz",
    "NOK",
}

STARRED_META_PSIDS = {
    "29786497700952484",
    "27869171066111718",
    "27933893459579897",
    "27797372223238102",
    "29021550610833812",
    "25893062207035568",
    "28732274109800353",
    "27346296878322229",
    "28041422415457571",
    "27407359568914146",
    "27790273320594134",
    "29073443488974636",
    "27899681453041154",
    "30073279418942034",
    "29253143071041490",
}

HUMAN_ADMIN_MARKERS = (
    "บริษัท ดิจิสท์ ฮับ จำกัด",
    "304-407545-5",
    "3044075455",
    "ส่งคำขอให้โอนแล้ว",
    "คุณร้องขอไป ฿",
    "messenger automatically created a transfer request",
    "รบกวนขอรหัสไปรษณีย์ค่ะ",
)


def _infer_sku_and_qty_from_text(combined_text: str) -> tuple[str, int]:
    import re

    # Strip long digit sequences (phone numbers, tracking numbers, bank accounts) so '0989913650' never matches '899'
    cleaned = re.sub(r"\+?\d[\d\s-]{7,}\d", " ", combined_text)
    low = cleaned.lower()
    if any(k in low for k in ("1,299", "1299", "3 แถม 3", "3แถม3")):
        return "BSJ_BIG3", 1
    if any(k in low for k in ("899", "2 แถม 2", "2แถม2")):
        return "BSJ_FAM2", 1
    if any(k in low for k in ("720", "20 ซอง", "20 ถุง", "20ถุง")):
        return "BSJ_SET20", 1
    if any(k in low for k in ("555", "15 ซอง", "15 ถุง", "15ถุง")):
        return "BSJ_SET15", 1
    if any(k in low for k in ("500g", "500 กรัม", "ครึ่งโล", "269", "239", "309")):
        return "BSJ500G1", 1
    if any(k in low for k in ("1kg", "1 kg", "1 กก", "1กิโล", "459", "499")):
        return "BSJ1KG1", 1
    if any(k in low for k in ("60g", "60 กรัม")):
        return "BSJ60G1", 1
    return "BSJ1KG1", 1


def analyze_facebook_conversation_dict(conv: dict, page_id: str = "806129109240845") -> dict | None:
    """Inspect a Graph API conversation object to extract customer name, paid status, SKU, and admin takeover."""
    from datetime import datetime, timezone

    parts = conv.get("participants", {}).get("data", [])
    cust_id = ""
    cust_name = ""
    for p in parts:
        pid = str(p.get("id") or "")
        if pid and pid != page_id:
            cust_id = pid
            cust_name = p.get("name") or ""
            break
    if not cust_id:
        return None

    messages = conv.get("messages", {}).get("data", [])
    is_starred = (cust_id in STARRED_META_PSIDS) or (cust_name.strip() in STARRED_META_NAMES)
    is_paid = is_starred
    paid_at_dt = None
    human_admin_active = False
    order_texts: list[str] = []

    for m in messages:
        msg_txt = str(m.get("message") or "")
        low_txt = msg_txt.lower()
        created_str = m.get("created_time") or ""
        msg_dt = None
        if created_str:
            try:
                msg_dt = datetime.fromisoformat(created_str.replace("+0000", "+00:00"))
            except Exception:
                msg_dt = None

        is_order_summary = ("เพจ : ข้าวบุก สุขใจ" in msg_txt and ("สินค้า :" in msg_txt or "จัดส่ง :" in msg_txt))
        has_paid_marker = is_order_summary or any(mk in low_txt for mk in PAID_ORDER_MARKERS)

        if has_paid_marker:
            is_paid = True
            is_starred = True
            order_texts.append(msg_txt)
            if msg_dt and (paid_at_dt is None or msg_dt > paid_at_dt):
                paid_at_dt = msg_dt

        if any(mk in low_txt for mk in HUMAN_ADMIN_MARKERS):
            order_texts.append(msg_txt)
            if msg_dt:
                hours_ago = (datetime.now(timezone.utc) - msg_dt).total_seconds() / 3600.0
                if hours_ago <= 24:
                    human_admin_active = True

    sku, qty = _infer_sku_and_qty_from_text("\n".join(order_texts))
    return {
        "external_user_id": cust_id,
        "customer_name": cust_name,
        "is_paid": is_paid,
        "is_starred": is_starred,
        "paid_at": paid_at_dt,
        "purchased_sku": sku,
        "purchased_qty": qty,
        "human_admin_active": human_admin_active,
        "messages": messages,
    }


def _apply_facebook_sync_to_db(info: dict, brand_id: str = "buksukjai") -> dict:
    """Persist verified Facebook conversation status into SQLite `user_sessions`."""
    from datetime import datetime, timezone
    from . import database

    ext_id = info["external_user_id"]
    session_key = database.make_session_key(brand_id, "facebook", ext_id)
    user = database.get_or_create_session(
        psid=session_key,
        brand_id=brand_id,
        platform="facebook",
        external_user_id=ext_id,
        customer_name=info.get("customer_name") or "",
    )

    if info.get("is_paid") or info.get("is_starred"):
        paid_dt = info.get("paid_at") or datetime.now(timezone.utc)
        days_elapsed = (datetime.now(timezone.utc) - paid_dt).total_seconds() / 86400.0
        # If historical order is >= 6 days old, mark stage=2 so we don't send late Day-3/Day-5 checks
        target_stage = max(user.after_sales_stage or 0, 2 if days_elapsed >= 6 else 0)
        new_tags = database._add_tag_str(user.broadcast_tags or "", "ชำระเงินแล้ว")
        new_tags = database._add_tag_str(new_tags, "⭐ ติดดาว (ซื้อแล้ว)")
        with database.SessionLocal() as db:
            row = db.get(database.UserSession, session_key)
            if row is not None:
                row.state = "completed"
                row.is_starred = True
                if info.get("customer_name"):
                    row.customer_name = info["customer_name"]
                row.broadcast_tags = new_tags
                row.purchased_sku = info.get("purchased_sku") or "BSJ1KG1"
                row.purchased_qty = info.get("purchased_qty") or 1
                row.purchased_at = paid_dt
                row.after_sales_stage = target_stage
                db.commit()
    elif info.get("human_admin_active"):
        database.set_bot_enabled(session_key, False)
        if info.get("customer_name"):
            database.update_session_meta(session_key, customer_name=info["customer_name"])
    elif info.get("customer_name"):
        database.update_session_meta(session_key, customer_name=info["customer_name"])

    return {
        "session_key": session_key,
        "customer_name": info.get("customer_name"),
        "is_paid": info.get("is_paid"),
        "is_starred": info.get("is_starred"),
        "purchased_sku": info.get("purchased_sku"),
        "paid_at": info["paid_at"].isoformat() if info.get("paid_at") else None,
        "human_admin_active": info.get("human_admin_active"),
    }


async def sync_facebook_user_thread(external_user_id: str, brand_id: str = "buksukjai") -> dict | None:
    """Query Facebook Graph API for a specific customer's real thread before replying."""
    if not external_user_id or "_test_" in external_user_id or external_user_id.startswith("FB_"):
        return None
    token = _get_channel_token(brand_id, "facebook")
    if not token:
        return None
    page = get_page_by_brand_id(brand_id)
    page_id = str(page.get("channels", {}).get("fb_page_id") or "806129109240845")
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(
                "https://graph.facebook.com/v21.0/me/conversations",
                params={
                    "access_token": token,
                    "user_id": external_user_id,
                    "fields": "participants,updated_time,messages.limit(25){message,from,created_time}",
                },
            )
            if resp.status_code != 200:
                return None
            data = resp.json().get("data", [])
            if not data:
                return None
            info = analyze_facebook_conversation_dict(data[0], page_id=page_id)
            if not info:
                return None
            return _apply_facebook_sync_to_db(info, brand_id=brand_id)
    except Exception:
        logger.exception("Failed to sync Facebook thread for %s", external_user_id)
        return None


async def sync_recent_facebook_conversations(brand_id: str = "buksukjai", limit: int = 40) -> list[dict]:
    """Scan the latest N conversations on the Facebook Page and sync paid/admin status into SQLite."""
    token = _get_channel_token(brand_id, "facebook")
    if not token:
        return []
    page = get_page_by_brand_id(brand_id)
    page_id = str(page.get("channels", {}).get("fb_page_id") or "806129109240845")
    results: list[dict] = []
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://graph.facebook.com/v21.0/me/conversations",
                params={
                    "access_token": token,
                    "limit": limit,
                    "fields": "participants,updated_time,messages.limit(25){message,from,created_time}",
                },
            )
            if resp.status_code != 200:
                return []
            for conv in resp.json().get("data", []):
                info = analyze_facebook_conversation_dict(conv, page_id=page_id)
                if info:
                    results.append(_apply_facebook_sync_to_db(info, brand_id=brand_id))
    except Exception:
        logger.exception("Bulk Facebook conversation sync failed")
    return results
