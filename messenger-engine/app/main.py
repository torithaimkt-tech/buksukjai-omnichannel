"""Omnichannel AI Chatbot Engine & Pancake-Style Admin Inbox
(Supports 4 Pages across LINE OA, Facebook Messenger, Instagram DM & Web Chat).

Run locally with:
    python -m uvicorn app.main:app --reload --port 8000
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Query, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

from . import audit, database, followup, media_generator, messenger  # noqa: E402
from .config_loader import (  # noqa: E402
    get_page_by_brand_id,
    load_config,
    load_pages_registry,
    resolve_brand_by_meta_id,
    save_pages_registry,
)
from .llm import LLMEngine, split_into_bubbles  # noqa: E402
from .prompt_engine import build_system_prompt  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"
CLOUDFLARED_PATH = Path(__file__).resolve().parent.parent / "cloudflared.exe"

CONFIG: dict = {}
LLM: LLMEngine | None = None
PUBLIC_BASE_URL: str = os.getenv("PUBLIC_BASE_URL", "")
_TUNNEL_PROC = None
_RECENT_MSG_CACHE: dict[str, float] = {}


def _sync_line_webhooks(base_url: str) -> None:
    """Automatically update LINE OA Webhook URL via LINE Messaging API whenever tunnel starts."""
    import time
    import httpx

    time.sleep(4)  # wait for trycloudflare DNS propagation
    for page in load_pages_registry():
        token = page.get("channels", {}).get("line_channel_access_token", "").strip()
        brand_id = page.get("brand_id", "buksukjai")
        if not token:
            continue
        webhook_url = f"{base_url}/webhook/line/{brand_id}"
        for attempt in range(3):
            try:
                resp = httpx.put(
                    "https://api.line.me/v2/bot/channel/webhook/endpoint",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"endpoint": webhook_url},
                    timeout=10,
                )
                logger.info("Auto-updated LINE OA Webhook for '%s' -> %s (HTTP %s)", brand_id, webhook_url, resp.status_code)
                if resp.status_code == 200:
                    break
            except Exception as e:
                logger.warning("Could not auto-update LINE OA Webhook for '%s': %s", brand_id, e)
            time.sleep(3)


def _start_local_tunnel_if_available() -> None:
    """Launch cloudflared.exe in background if running locally on Windows."""
    global PUBLIC_BASE_URL, _TUNNEL_PROC
    if PUBLIC_BASE_URL:
        import threading
        threading.Thread(target=_sync_line_webhooks, args=(PUBLIC_BASE_URL,), daemon=True).start()
        return
    if not CLOUDFLARED_PATH.exists():
        return

    import re
    import subprocess
    import threading

    def _reader():
        global PUBLIC_BASE_URL, _TUNNEL_PROC
        try:
            _TUNNEL_PROC = subprocess.Popen(
                [str(CLOUDFLARED_PATH), "tunnel", "--url", "http://127.0.0.1:8000"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            for line in _TUNNEL_PROC.stdout:
                m = re.search(r"(https://[a-zA-Z0-9-]+\.trycloudflare\.com)", line)
                if m and not PUBLIC_BASE_URL:
                    PUBLIC_BASE_URL = m.group(1)
                    logger.info("Cloudflare HTTPS Tunnel active: %s", PUBLIC_BASE_URL)
                    _sync_line_webhooks(PUBLIC_BASE_URL)
        except Exception as e:
            logger.warning("Local tunnel exited: %s", e)

    t = threading.Thread(target=_reader, daemon=True)
    t.start()


def _seed_sample_conversations_if_empty() -> None:
    """Seed 3 realistic demo threads (LINE, Facebook, IG) on first startup if DB is empty."""
    existing = database.list_all_sessions()
    if existing:
        return

    samples = [
        {
            "brand_id": "buksukjai",
            "platform": "line",
            "ext_id": "U8891line",
            "name": "คุณพิมพ์ใจ (LINE OA)",
            "state": "pending_payment",
            "notes": "สนใจเซ็ตครอบครัว 899.- รอแจ้งที่อยู่จัดส่ง",
            "messages": [
                ("user", "สวัสดีค่ะ ข้าวบุกสุขใจมีขนาดไหนบ้างคะ แล้วส่งฟรีไหม?"),
                (
                    "assistant",
                    "สวัสดีค่ะคุณลูกค้า 🍚🌿 ข้าวบุกสุขใจ (บุก 60% ผสมข้าวหอมมะลิแท้ 40% เพียง 23 kcal/25g) มีโปรโมชั่นดังนี้ค่ะ:\n"
                    "• 60 กรัม (ไซส์ทดลอง): โปร 39.-\n"
                    "• 500 กรัม (ทานประจำ): โปร 239.-\n"
                    "• 1 กิโลกรัม (คุ้มสุด): โปร 459.- (โอนเงินส่งฟรี!)\n"
                    "• เซ็ตครอบครัว 1 กก.×2 ถุง แถม 60g 2 ซอง: เพียง 899.- ส่งฟรีค่ะ!",
                ),
                ("user", "สนใจสั่งเซ็ตครอบครัว 899 บาทค่ะ"),
                (
                    "assistant",
                    "ยินดีเลยค่ะคุณลูกค้า 🍚🌿 น้องบุกขอสรุปยอดออเดอร์นะคะ:\n\n"
                    "• รายการ: เซ็ตครอบครัว 2 แถม 2 (1 กก. × 2 ถุง + แถมฟรี 60g 2 ซอง) ราคาโปร 899 บาท\n"
                    "• ยอดชำระแบบโอนเงิน: 899 บาท (โอนเงินส่งฟรี!)\n\n"
                    "คุณลูกค้าสามารถแจ้ง ชื่อ-ที่อยู่ และเบอร์โทรศัพท์ สำหรับจัดส่งไว้ได้เลยนะคะ 🙏💚",
                ),
            ],
        },
        {
            "brand_id": "buksukjai",
            "platform": "facebook",
            "ext_id": "FB90231",
            "name": "คุณสมชาย รักสุขภาพ",
            "state": "browsing",
            "notes": "ทักมาจากโพสต์โปรโมชั่นถุง 1 กก.",
            "messages": [
                ("user", "ต้องใช้หม้อหุงข้าวต้มไหมครับ?"),
                (
                    "assistant",
                    "ไม่ต้องหุงและไม่ต้องใช้หม้อหุงข้าวเลยค่ะ 🍚✨ ใช้สูตร 'ตัก-เติม-รอ' ง่ายๆ แค่ตักใส่ชาม เติมน้ำร้อนจัด (ข้าว 1 ส่วน : น้ำร้อน 1.2–1.5 ส่วน) ปิดฝารอ 10–15 นาที ก็พร้อมทานทันทีค่ะ คุณลูกค้าสนใจรับขนาด 1 กก. (459.- โอนส่งฟรี) ไปลองทานดีคะ?",
                ),
            ],
        },
        {
            "brand_id": "buksukjai",
            "platform": "instagram",
            "ext_id": "IG44120",
            "name": "คุณเมย์ (@may_healthy)",
            "state": "completed",
            "notes": "ถุง 1 กก. (459.- โอนส่งฟรี) | โอนแล้ว | จัดส่ง กทม.",
            "messages": [
                ("user", "รับขนาด 1 กิโลกรัม 1 ถุงค่ะ โอนเงินเรียบร้อยแล้วนะคะ จัดส่ง คุณเมย์ 99/12 สุขุมวิท กรุงเทพฯ โทร 089-123-4567"),
                (
                    "assistant",
                    "ขอบพระคุณมากค่ะคุณลูกค้า 🍚💚 น้องบุกได้รับแจ้งยอดและบันทึกที่อยู่จัดส่งเรียบร้อยแล้วค่ะ ทางร้านจะรีบจัดส่งข้าวบุกสุขใจให้ถึงมือภายใน 3–5 วันทำการเลยนะคะ 🙏✨",
                ),
            ],
        },
    ]

    for s in samples:
        key = database.make_session_key(s["brand_id"], s["platform"], s["ext_id"])
        database.get_or_create_session(
            psid=key,
            brand_id=s["brand_id"],
            platform=s["platform"],
            external_user_id=s["ext_id"],
            customer_name=s["name"],
        )
        for role, text in s["messages"]:
            database.log_message(key, role, text)
        database.update_session_meta(key, state=s["state"], notes=s["notes"], clear_unread=(s["state"] == "completed"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    global CONFIG, LLM
    CONFIG = load_config()
    media_generator.load_media_catalog()
    system_prompt = build_system_prompt(CONFIG)
    LLM = LLMEngine(system_prompt, CONFIG)
    database.init_db()
    _seed_sample_conversations_if_empty()
    _start_local_tunnel_if_available()
    logger.info(
        "Omnichannel Engine ready — primary brand '%s' (bot: %s), 4-page registry active",
        CONFIG["brand_persona"]["brand_name"],
        CONFIG["brand_persona"]["bot_name"],
    )

    followup_task = None
    if os.getenv("ENABLE_FOLLOWUP", "true").lower() in ("1", "true", "yes"):
        import asyncio

        asyncio.create_task(messenger.sync_recent_facebook_conversations("buksukjai", limit=40))
        followup_task = asyncio.create_task(followup.followup_loop(CONFIG, lambda: PUBLIC_BASE_URL))
    yield
    if followup_task:
        followup_task.cancel()
    if _TUNNEL_PROC:
        try:
            _TUNNEL_PROC.terminate()
        except Exception:
            pass


app = FastAPI(title="Omnichannel AI Chatbot & Admin Inbox (4-Page Edition)", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _update_public_base_url_from_request(request: Request) -> None:
    """Capture public HTTPS domain from Cloudflare Tunnel or Railway reverse proxy headers."""
    global PUBLIC_BASE_URL
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    if host and ("trycloudflare.com" in host or "railway.app" in host) and not PUBLIC_BASE_URL:
        PUBLIC_BASE_URL = f"https://{host}"


# --- Admin Inbox UI (Pancake-style Dashboard) -----------------------------------

@app.get("/")
async def admin_inbox_ui():
    return FileResponse(STATIC_DIR / "index.html")


# --- Meta Webhook (Facebook Messenger + Instagram DM across 5 Pages) ------------

@app.get("/webhook")
@app.get("/webhook/meta")
async def verify_meta_webhook(
    hub_mode: str = Query(default="", alias="hub.mode"),
    hub_verify_token: str = Query(default="", alias="hub.verify_token"),
    hub_challenge: str = Query(default="", alias="hub.challenge"),
):
    expected = os.getenv("META_VERIFY_TOKEN", "changeme")
    if hub_mode == "subscribe" and hub_verify_token == expected:
        return Response(content=hub_challenge, media_type="text/plain")
    return Response(content="Verification failed", status_code=403)


@app.post("/webhook")
@app.post("/webhook/meta")
async def receive_meta_webhook(request: Request, background_tasks: BackgroundTasks):
    _update_public_base_url_from_request(request)
    raw_body = await request.body()
    if not messenger.verify_signature(raw_body, request.headers.get("X-Hub-Signature-256")):
        return Response(content="Invalid signature", status_code=403)

    payload = await request.json()
    obj_type = payload.get("object")
    if obj_type not in ("page", "instagram"):
        return Response(status_code=404)

    platform = "instagram" if obj_type == "instagram" else "facebook"

    for entry in payload.get("entry", []):
        recipient_page_id = entry.get("id", "")
        brand_id = resolve_brand_by_meta_id(recipient_page_id, platform=platform)
        for event in entry.get("messaging", []):
            sender_id = event.get("sender", {}).get("id")
            recipient_id = event.get("recipient", {}).get("id")
            message = event.get("message", {})
            text = message.get("text")
            attachments = message.get("attachments") or []

            # If a human admin replies from Meta Business Suite / Page Inbox (is_echo=True and app_id != our bot),
            # automatically pause AI for that customer so we NEVER interfere with the human admin!
            if message.get("is_echo"):
                echo_app_id = str(message.get("app_id") or "")
                if recipient_id and echo_app_id != "1414062917046427":
                    session_key = database.make_session_key(brand_id, platform, recipient_id)
                    database.get_or_create_session(
                        psid=session_key,
                        brand_id=brand_id,
                        platform=platform,
                        external_user_id=recipient_id,
                    )
                    if text:
                        database.log_message(session_key, "admin", text)
                    database.set_bot_enabled(session_key, False)
                    logger.info("Human admin replied in Meta Inbox for %s — auto-paused AI bot", session_key)
                continue

            if attachments:
                for att in attachments:
                    if att.get("type") == "image":
                        payload_obj = att.get("payload", {}) or {}
                        img_url = payload_obj.get("url", "")
                        sticker_id = payload_obj.get("sticker_id")
                        # Ignore Facebook Thumbs-Up / stickers so they are never mistaken for payment slips
                        if sticker_id or "39178562_1505197616293642" in img_url:
                            continue
                        if img_url and sender_id:
                            session_key = database.make_session_key(brand_id, platform, sender_id)
                            database.get_or_create_session(
                                psid=session_key,
                                brand_id=brand_id,
                                platform=platform,
                                external_user_id=sender_id,
                            )
                            database.log_message(session_key, "user", f"[IMAGE:{img_url}]")
                        if not text:
                            text = "[ลูกค้าแนบสลิปเข้ามาในแชทค่ะ]"

            if not text:
                continue

            if not sender_id:
                continue
            import time as _time
            mid = message.get("mid", "")
            dedup_key = f"{sender_id}:{mid}" if mid else f"{sender_id}:{text}"
            now_ts = _time.time()
            if dedup_key in _RECENT_MSG_CACHE and (now_ts - _RECENT_MSG_CACHE[dedup_key]) < 15:
                continue
            text_key = f"{sender_id}:{text.strip()}"
            if text_key in _RECENT_MSG_CACHE and (now_ts - _RECENT_MSG_CACHE[text_key]) < 4:
                continue
            _RECENT_MSG_CACHE[dedup_key] = now_ts
            _RECENT_MSG_CACHE[text_key] = now_ts

            background_tasks.add_task(
                process_omnichannel_message,
                brand_id=brand_id,
                platform=platform,
                external_user_id=sender_id,
                text=text,
            )

    return {"status": "ok"}


# --- LINE Official Account (Messaging API) Webhook across 5 Pages ---------------

@app.get("/webhook/line")
@app.get("/webhook/line/{brand_id}")
async def verify_line_webhook_get(brand_id: str = "buksukjai"):
    return {"status": "ok", "channel": "LINE Messaging API Webhook Ready", "brand_id": brand_id}


@app.post("/webhook/line")
@app.post("/webhook/line/{brand_id}")
async def receive_line_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    brand_id: str = "buksukjai",
):
    _update_public_base_url_from_request(request)
    raw_body = await request.body()
    signature = request.headers.get("X-Line-Signature")
    if not messenger.verify_line_signature(raw_body, signature, brand_id=brand_id):
        return Response(content="Invalid LINE signature", status_code=403)

    if not raw_body:
        return {"status": "ok"}

    try:
        payload = await request.json()
    except Exception:
        return {"status": "ok"}

    for event in payload.get("events", []):
        event_type = event.get("type")
        source = event.get("source", {})
        user_id = source.get("userId")
        reply_token = event.get("replyToken")
        if not user_id:
            continue

        if event_type == "follow":
            from .llm import FULL_PROMO_SUMMARY_BUBBLE
            greeting = f"{CONFIG['brand_persona']['greeting_message']}|||{FULL_PROMO_SUMMARY_BUBBLE}"
            all_promo_items = media_generator.get_all_promo_items()
            background_tasks.add_task(
                messenger.send_omnichannel_text,
                "line",
                user_id,
                greeting,
                brand_id,
                reply_token,
                None,
                None,
                all_promo_items,
                PUBLIC_BASE_URL,
            )
        elif event_type == "message":
            msg_obj = event.get("message", {})
            msg_type = msg_obj.get("type")
            if msg_type == "text":
                text = msg_obj.get("text", "")
                background_tasks.add_task(
                    process_omnichannel_message,
                    brand_id=brand_id,
                    platform="line",
                    external_user_id=user_id,
                    text=text,
                    reply_token=reply_token,
                )
            elif msg_type == "image":
                background_tasks.add_task(
                    process_omnichannel_message,
                    brand_id=brand_id,
                    platform="line",
                    external_user_id=user_id,
                    text="[ลูกค้าแนบสลิปเข้ามาในแชทค่ะ]",
                    reply_token=reply_token,
                )

    return {"status": "ok"}


# --- Unified Message Processor (AI + Human Handover) ----------------------------

async def process_omnichannel_message(
    brand_id: str,
    platform: str,
    external_user_id: str,
    text: str,
    customer_name: str = "",
    reply_token: str | None = None,
) -> dict:
    session_key = database.make_session_key(brand_id, platform, external_user_id)
    try:
        # Real-time Facebook Graph API verification BEFORE replying:
        # Checks if customer already ordered/paid in past Facebook history or if human admin is handling the chat!
        if platform == "facebook":
            await messenger.sync_facebook_user_thread(external_user_id, brand_id=brand_id)

        user = database.get_or_create_session(
            psid=session_key,
            brand_id=brand_id,
            platform=platform,
            external_user_id=external_user_id,
            customer_name=customer_name,
        )
        database.log_message(session_key, "user", text)

        # If Human Admin paused the AI bot for this customer, do not auto-reply
        if not user.bot_enabled:
            logger.info("AI paused for %s — waiting for human admin reply", session_key)
            return {
                "session_key": session_key,
                "bot_replied": False,
                "reply": None,
                "state": user.state,
            }

        low_txt = text.lower().strip()
        is_attachment_placeholder = text.startswith("[ลูกค้า")
        is_paid_customer = (
            bool(getattr(user, "is_starred", False))
            or (user.state == "completed")
            or ("ชำระเงินแล้ว" in (user.broadcast_tags or ""))
            or ("ติดดาว" in (user.broadcast_tags or ""))
        )
        wants_to_reorder = any(
            w in low_txt for w in ("สั่งเพิ่ม", "ซื้อเพิ่ม", "สั่งอีก", "เอาอีก", "โปรลูกค้าเก่า", "สั่งซื้อเพิ่ม")
        )

        # If customer already completed an order and just sends a comma, dot, thank-you, or attachment, stay silent!
        if is_paid_customer and not wants_to_reorder:
            if is_attachment_placeholder or low_txt in (
                ",", ".", "👍", "ขอบคุณค่ะ", "ขอบคุณครับ", "ขอบคุณจ้า", "ค่ะ", "ครับ", "จ้า", "โอเค", "โอเคค่ะ", "ok"
            ):
                logger.info("Paid customer %s sent acknowledgement '%s' — skipping sales reply", session_key, text)
                return {
                    "session_key": session_key,
                    "bot_replied": False,
                    "reply": None,
                    "state": "completed",
                }

        history = database.get_history(session_key)
        clean_history = [
            m for m in history if not str(m.get("content", "")).startswith("[IMAGE:")
        ]
        if is_paid_customer and not wants_to_reorder:
            clean_history.append(
                {
                    "role": "user",
                    "content": (
                        f"{text}\n"
                        "[ข้อมูลสำคัญจากระบบ: ลูกค้าท่านนี้ได้สั่งซื้อและชำระเงินเรียบร้อยแล้ว (สถานะ: ชำระเงินแล้ว / บริการหลังการขาย) "
                        "ห้ามเสนอขายสินค้าซ้ำ ห้ามส่งตารางราคา และห้ามถามว่าจะรับไซส์ไหนอีกเด็ดขาด "
                        "ให้ตอบกลับแบบบริการหลังการขายอย่างอบอุ่น เช่น ถามว่าได้รับสินค้าเรียบร้อยดีไหมคะ ทานแล้วรสชาติเป็นอย่างไรบ้าง หรือมีเรื่องไหนให้น้องบุกช่วยดูแลแจ้งได้เลยนะคะ]"
                    ),
                }
            )

        reply, new_state, image_key = await LLM.generate(clean_history, user.state)

        # Smart fallback: whenever customer asks for promo/price/sizes/interest, send ALL 4 promo images ('promo_all') at once!
        explicitly_asked_pic = (not is_attachment_placeholder) and (not is_paid_customer or wants_to_reorder) and any(
            w in low_txt for w in ("รูป", "ภาพ", "โปร", "ราคา", "สนใจ", "กี่บาท", "เท่าไหร่", "ขนาด", "ไซส์", "ขายยังไง")
        )
        if is_attachment_placeholder or (is_paid_customer and not wants_to_reorder):
            image_key = "none"
            if is_paid_customer and not wants_to_reorder:
                new_state = "completed"
        elif image_key == "promo_3sizes" or ((not image_key or image_key == "none") and explicitly_asked_pic):
            image_key = "promo_all"

        # Layer-1 Automated Pre-Send Audit (ตรวจสอบความถูกต้อง 7 ข้อก่อนส่งให้ลูกค้าจริง)
        bubbles, new_state, selected_media_items, audit_report = audit.audit_outgoing_reply(
            psid=session_key,
            brand_id=brand_id,
            user_session=user,
            history=clean_history,
            raw_reply=reply,
            proposed_state=new_state,
            proposed_image_key=image_key,
            config=CONFIG,
        )

        # 1. Log promo image(s) FIRST in Admin Inbox DB
        for item in selected_media_items:
            database.log_message(session_key, "assistant", f"[IMAGE:{item['relative_url']}]")

        # 2. Then log the 1–2 short accompanying text bubbles right after
        for b in bubbles:
            database.log_message(session_key, "assistant", b)

        audited_reply_text = "|||".join(bubbles)
        database.update_state(session_key, new_state)
        await messenger.send_omnichannel_text(
            platform=platform,
            external_user_id=external_user_id,
            text=audited_reply_text,
            brand_id=brand_id,
            reply_token=reply_token,
            media_items=selected_media_items,
            public_base_url=PUBLIC_BASE_URL,
        )
        # Queue confirmed orders for the Daily 06:00 AM JST ERP Batch (no immediate real-time push during the day)
        if new_state == "completed" and user.state != "completed":
            database.update_session_meta(session_key, state="completed", is_starred=True)
            logger.info("Order %s marked completed + starred ⭐ — queued for Daily 06:00 AM JST ERP Batch", session_key)
        logger.info(
            "Replied to %s [%s/%s] (%d images + %d bubbles, img=%s, state: %s -> %s)",
            session_key,
            brand_id,
            platform,
            len(selected_media_items),
            len(bubbles),
            image_key,
            user.state,
            new_state,
        )
        return {
            "session_key": session_key,
            "bot_replied": True,
            "reply": "\n\n".join(bubbles),
            "bubbles": bubbles,
            "image_url": selected_media_items[0]["relative_url"] if selected_media_items else None,
            "images": [it["relative_url"] for it in selected_media_items],
            "state": new_state,
            "audit": audit_report,
        }
    except Exception:
        logger.exception("Failed to process message from %s", session_key)
        fallback = "ขออภัยค่ะ ระบบขัดข้องชั่วคราว กรุณาลองใหม่อีกครั้งนะคะ 🙏"
        await messenger.send_omnichannel_text(platform, external_user_id, fallback, brand_id=brand_id)
        return {"session_key": session_key, "bot_replied": False, "reply": fallback, "state": "browsing"}


# --- Admin Inbox & Simulator REST API -------------------------------------------

class SimulateMessageRequest(BaseModel):
    brand_id: str = "buksukjai"
    platform: str = "line"
    external_user_id: str = "sim_customer_01"
    customer_name: str = "คุณลูกค้า (ทดสอบ)"
    text: str


class AdminReplyRequest(BaseModel):
    text: str
    pause_bot: bool = True


class SessionUpdateRequest(BaseModel):
    bot_enabled: bool | None = None
    state: str | None = None
    is_starred: bool | None = None
    customer_name: str | None = None
    notes: str | None = None
    broadcast_tags: str | None = None
    purchased_sku: str | None = None
    purchased_qty: int | None = None


class TriggerAfterSalesRequest(BaseModel):
    stage: int = 1
    sku: str | None = None
    quantity: int | None = None


class SaveSettingsRequest(BaseModel):
    openai_api_key: str | None = None
    pages: list[dict] | None = None


@app.get("/api/sessions")
async def api_list_sessions(
    brand_id: str = "all",
    platform: str = "all",
    state: str = "all",
):
    return database.list_all_sessions(brand_id=brand_id, platform=platform, state=state)


@app.get("/api/sessions/{psid:path}/messages")
async def api_get_messages(psid: str):
    database.update_session_meta(psid, clear_unread=True)
    return database.get_full_messages(psid)


@app.patch("/api/sessions/{psid:path}")
async def api_update_session(psid: str, body: SessionUpdateRequest):
    updated = database.update_session_meta(
        psid=psid,
        bot_enabled=body.bot_enabled,
        state=body.state,
        is_starred=body.is_starred,
        customer_name=body.customer_name,
        notes=body.notes,
        broadcast_tags=body.broadcast_tags,
        purchased_sku=body.purchased_sku,
        purchased_qty=body.purchased_qty,
    )
    if not updated:
        return Response(status_code=404)
    sched = followup.calculate_depletion_schedule(updated.purchased_sku, updated.purchased_qty)
    return {
        "psid": updated.psid,
        "state": updated.state,
        "is_starred": bool(getattr(updated, "is_starred", False) or updated.state == "completed"),
        "bot_enabled": updated.bot_enabled,
        "customer_name": updated.customer_name,
        "notes": updated.notes,
        "broadcast_tags": updated.broadcast_tags,
        "purchased_sku": updated.purchased_sku,
        "purchased_qty": updated.purchased_qty,
        "depletion_schedule": sched,
    }


@app.post("/api/sessions/{psid:path}/toggle-star")
async def api_toggle_star(psid: str):
    """Toggle ⭐ Star status for a customer. Starring marks them as a verified buyer (completed)."""
    user = database.get_or_create_session(psid)
    current = bool(getattr(user, "is_starred", False) or user.state == "completed")
    new_star = not current
    new_state = "completed" if new_star else user.state
    updated = database.update_session_meta(psid=psid, is_starred=new_star, state=new_state)
    return {
        "status": "ok",
        "psid": psid,
        "is_starred": new_star,
        "state": updated.state if updated else new_state,
        "broadcast_tags": updated.broadcast_tags if updated else "",
    }


@app.post("/api/sessions/{psid:path}/after-sales")
async def api_trigger_after_sales(psid: str, body: TriggerAfterSalesRequest):
    """Manually trigger or test Stage 1 (Day 3), Stage 2 (Day 5), or Stage 3 (Depletion + VIP Promo)."""
    if body.sku or body.quantity:
        database.update_session_meta(psid, purchased_sku=body.sku, purchased_qty=body.quantity)
    return await followup.send_after_sales_stage(psid, body.stage, public_base_url=PUBLIC_BASE_URL)


@app.post("/api/sessions/{psid:path}/reply")
async def api_admin_reply(psid: str, body: AdminReplyRequest):
    """Send a manual admin message from the Pancake-style inbox to LINE / FB / IG."""
    text = body.text.strip()
    if not text:
        return Response(status_code=400, content="Empty message")

    user = database.get_or_create_session(psid)
    if body.pause_bot:
        database.update_session_meta(psid, bot_enabled=False, clear_unread=True)

    database.log_message(psid, "admin", text, sender_label="แอดมิน (คน)")
    await messenger.send_omnichannel_text(
        platform=user.platform,
        external_user_id=user.external_user_id,
        text=text,
        brand_id=user.brand_id,
    )
    return {"status": "ok", "bot_enabled": False if body.pause_bot else user.bot_enabled}


class AdminSendImageRequest(BaseModel):
    image_key: str | None = None
    data_url: str | None = None
    filename: str | None = None
    pause_bot: bool = False


class UploadMediaSlotRequest(BaseModel):
    slot_key: str
    data_url: str
    filename: str = "upload.png"


@app.get("/api/media")
async def api_list_media():
    catalog = media_generator.load_media_catalog()
    items = []
    for k, v in catalog.items():
        items.append(
            {
                **v,
                "relative_url": f"/static/media/{v['filename']}",
                "public_url": f"{PUBLIC_BASE_URL}/static/media/{v['filename']}" if PUBLIC_BASE_URL else f"/static/media/{v['filename']}",
            }
        )
    return {"items": items, "public_base_url": PUBLIC_BASE_URL}


@app.post("/api/media/upload")
async def api_upload_media_slot(body: UploadMediaSlotRequest):
    """Replace one of the 4 AI auto-image slots (promo_catalog, product_photo, how_to_cook, payment_qr) with a real image."""
    import base64 as _b64
    import time as _time

    raw_b64 = body.data_url.split(",", 1)[-1]
    img_bytes = _b64.b64decode(raw_b64)
    ext = ".jpg" if "jpeg" in body.data_url[:40].lower() or body.filename.lower().endswith(".jpg") else ".png"
    safe_key = body.slot_key.strip()
    new_filename = f"{safe_key}_{int(_time.time())}{ext}"
    dest_path = media_generator.MEDIA_DIR / new_filename
    media_generator.MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(img_bytes)

    catalog = media_generator.load_media_catalog()
    if safe_key in catalog:
        catalog[safe_key]["filename"] = new_filename
    else:
        catalog[safe_key] = {
            "key": safe_key,
            "title": safe_key,
            "subtitle": "รูปภาพที่อัปโหลดเพิ่ม",
            "filename": new_filename,
        }
    media_generator.save_media_catalog(catalog)
    return {"status": "ok", "slot_key": safe_key, "relative_url": f"/static/media/{new_filename}"}


@app.post("/api/sessions/{psid:path}/send-image")
async def api_admin_send_image(psid: str, body: AdminSendImageRequest):
    """Send a preset or newly uploaded image directly to the customer in LINE OA / Facebook Messenger."""
    import base64 as _b64
    import time as _time

    user = database.get_or_create_session(psid)
    if body.pause_bot:
        database.update_session_meta(psid, bot_enabled=False, clear_unread=True)

    rel_url = None
    local_path = None

    if body.data_url:
        raw_b64 = body.data_url.split(",", 1)[-1]
        img_bytes = _b64.b64decode(raw_b64)
        ext = ".jpg" if "jpeg" in body.data_url[:40].lower() else ".png"
        fname = f"chat_img_{int(_time.time() * 1000)}{ext}"
        fpath = media_generator.MEDIA_DIR / fname
        media_generator.MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        fpath.write_bytes(img_bytes)
        rel_url = f"/static/media/{fname}"
        local_path = str(fpath)
    elif body.image_key == "promo_all":
        all_items = media_generator.get_all_promo_items()
        for it in all_items:
            r_url = it["relative_url"]
            p_url = f"{PUBLIC_BASE_URL}{r_url}" if PUBLIC_BASE_URL else None
            database.log_message(psid, "admin", f"[IMAGE:{r_url}]", sender_label="แอดมิน (ส่งรูปโปร)")
            await messenger.send_omnichannel_image(
                platform=user.platform,
                external_user_id=user.external_user_id,
                image_url=p_url,
                image_local_path=it["local_path"],
                brand_id=user.brand_id,
            )
        return {"status": "ok", "count": len(all_items)}
    elif body.image_key:
        item = media_generator.get_media_item(body.image_key)
        if item:
            rel_url = item["relative_url"]
            local_path = item["local_path"]

    if not rel_url or not local_path:
        return Response(status_code=400, content="Image not found")

    public_url = f"{PUBLIC_BASE_URL}{rel_url}" if PUBLIC_BASE_URL else None
    database.log_message(psid, "admin", f"[IMAGE:{rel_url}]", sender_label="แอดมิน (ส่งรูป)")
    await messenger.send_omnichannel_image(
        platform=user.platform,
        external_user_id=user.external_user_id,
        image_url=public_url,
        image_local_path=local_path,
        brand_id=user.brand_id,
    )
    return {"status": "ok", "relative_url": rel_url, "public_url": public_url}


@app.post("/api/sessions/{psid:path}/extract-order")
async def api_extract_order(psid: str):
    """Extract structured order details from chat history for JST ERP & Meta ROAS."""
    history = database.get_history(psid, limit=25)
    user = database.get_or_create_session(psid)
    order = await LLM.extract_order_details(history)
    new_name = order.get("recipient_name") if (order.get("recipient_name") and not user.customer_name) else None
    database.update_session_meta(
        psid,
        customer_name=new_name,
        purchased_sku=order.get("sku") or user.purchased_sku,
        purchased_qty=order.get("quantity") or user.purchased_qty,
    )
    sched = followup.calculate_depletion_schedule(order.get("sku") or user.purchased_sku, order.get("quantity") or user.purchased_qty)
    return {
        "psid": psid,
        "state": user.state,
        "platform": user.platform,
        "external_user_id": user.external_user_id,
        "order": order,
        "depletion_schedule": sched,
    }


class SendRoasRequest(BaseModel):
    amount: float
    currency: str = "THB"


@app.post("/api/sessions/{psid:path}/send-roas")
async def api_send_roas(psid: str, body: SendRoasRequest):
    """Send Purchase conversion value (THB) to Meta Conversions API for Click-to-Messenger Ads ROAS."""
    import time as _time
    import httpx as _httpx

    user = database.get_or_create_session(psid)
    page = get_page_by_brand_id(user.brand_id)
    channels = page.get("channels", {})
    page_id = channels.get("fb_page_id") or "806129109240845"
    token = channels.get("fb_page_access_token") or os.getenv("PAGE_ACCESS_TOKEN", "")
    dataset_id = os.getenv("META_DATASET_ID", "").strip()

    capi_status = "logged_ready"
    if dataset_id and token and user.platform == "facebook":
        payload = {
            "data": [
                {
                    "event_name": "Purchase",
                    "event_time": int(_time.time()),
                    "action_source": "business_messaging",
                    "messaging_channel": "messenger",
                    "user_data": {
                        "page_id": page_id,
                        "page_scoped_user_id": user.external_user_id,
                    },
                    "custom_data": {
                        "currency": body.currency,
                        "value": body.amount,
                    },
                }
            ]
        }
        try:
            async with _httpx.AsyncClient(timeout=10) as client:
                r = await client.post(
                    f"https://graph.facebook.com/v21.0/{dataset_id}/events",
                    params={"access_token": token},
                    json=payload,
                )
                capi_status = f"sent_http_{r.status_code}"
        except Exception as e:
            capi_status = f"error:{e}"

    note_line = f"[ROAS: บันทึกยอดซื้อ {body.amount:,.0f} บาท ({capi_status})]"
    new_notes = f"{user.notes}\n{note_line}".strip() if user.notes else note_line
    database.update_session_meta(psid, state="completed", notes=new_notes)
    return {"status": "ok", "amount": body.amount, "capi_status": capi_status, "notes": new_notes}


@app.post("/api/simulate")
async def api_simulate_customer_message(body: SimulateMessageRequest):
    """Local simulator endpoint so you can test LINE OA, Facebook, and IG chats locally."""
    result = await process_omnichannel_message(
        brand_id=body.brand_id,
        platform=body.platform,
        external_user_id=body.external_user_id,
        text=body.text,
        customer_name=body.customer_name,
        reply_token="sim_reply_token",
    )
    return result


@app.get("/api/pages")
async def api_get_pages():
    pages = load_pages_registry()
    ai_label = LLM.get_status_label() if LLM else "Smart Brand Demo Mode"
    has_key = bool(os.getenv("GEMINI_API_KEY", "").strip() or os.getenv("OPENAI_API_KEY", "").strip())
    return {
        "pages": pages,
        "ai_mode": ai_label,
        "has_openai_key": has_key,
        "meta_verify_token": os.getenv("META_VERIFY_TOKEN", "changeme"),
        "public_base_url": PUBLIC_BASE_URL,
    }


def _persist_env_key(key_name: str, value: str) -> None:
    env_file = Path(__file__).resolve().parent.parent / ".env"
    lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
    updated = False
    new_lines = []
    for line in lines:
        if line.strip().startswith(f"{key_name}="):
            new_lines.append(f"{key_name}={value}")
            updated = True
        else:
            new_lines.append(line)
    if not updated:
        new_lines.append(f"{key_name}={value}")
    env_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


@app.post("/api/pages")
async def api_save_pages(body: SaveSettingsRequest):
    if body.openai_api_key is not None:
        clean_key = body.openai_api_key.strip()
        if clean_key:
            if clean_key.startswith("AIza") or clean_key.startswith("AQ."):
                os.environ["GEMINI_API_KEY"] = clean_key
                _persist_env_key("GEMINI_API_KEY", clean_key)
            else:
                os.environ["OPENAI_API_KEY"] = clean_key
                _persist_env_key("OPENAI_API_KEY", clean_key)
            if LLM:
                LLM.refresh_client()
    if body.pages is not None:
        save_pages_registry(body.pages)
    return await api_get_pages()


@app.get("/api/audit/report")
async def api_audit_report(limit: int = 50):
    """Return recent Layer-1 (Pre-Send Chat) and Layer-2 (Pre-JST Order) automated audit logs."""
    events = audit.get_recent_audit_events(limit=limit)
    return {
        "status": "ok",
        "total_events": len(events),
        "auto_fixed_count": sum(1 for e in events if e.get("auto_fixed")),
        "events": events,
    }


@app.get("/api/sessions/{psid:path}/audit")
async def api_audit_session(psid: str):
    """Run Layer-1 Pre-Keying Order Audit on a specific customer session."""
    return audit.audit_session_for_jst(psid)


@app.get("/api/audit/jst-reconcile")
async def api_audit_jst_reconcile(days_lookback: int = 2):
    """Run Layer-2 Post-Keying Reconciliation Audit (cross-checks active JST ERP orders against Facebook chats)."""
    return audit.audit_jst_orders_against_chat(days_lookback=days_lookback)


@app.get("/api/jst/status")
async def api_jst_status():
    """Check JST ERP connection and configuration."""
    from . import jst_erp
    cookie = jst_erp.get_jst_cookie()
    return {
        "status": "ok",
        "configured": bool(cookie),
        "shop_id": jst_erp.JST_SHOP_ID,
        "scb_account": jst_erp.JST_SCB_ACCOUNT,
        "known_skus": list(jst_erp.KNOWN_SKUS.keys()),
    }


@app.post("/api/sessions/{psid:path}/push-jst")
async def api_push_session_to_jst(psid: str, force: bool = False):
    """Run Layer-2 Audit + push confirmed customer order to JST ERP."""
    from . import jst_erp
    return jst_erp.sync_session_to_jst(psid, force_create=force)


@app.post("/api/jst/sync-all")
async def api_sync_all_jst(days_lookback: int = 2):
    """Audit and sync all recent completed orders to JST ERP."""
    from . import jst_erp
    return jst_erp.sync_all_confirmed_orders_to_jst(days_lookback=days_lookback)


@app.post("/api/reload")
async def api_hot_reload():
    """Hot-reload config.json, prompt_engine, media_generator, database, followup, audit, and llm in memory without restarting the tunnel."""
    import importlib
    from . import audit as _audit_mod
    from . import database as _db_mod
    from . import followup as _fu_mod
    from . import llm as _llm_mod
    from . import media_generator as _mg_mod
    from . import messenger as _msg_mod
    from . import prompt_engine as _pe_mod

    global CONFIG, LLM, split_into_bubbles
    importlib.reload(_pe_mod)
    importlib.reload(_llm_mod)
    importlib.reload(_db_mod)
    importlib.reload(_mg_mod)
    importlib.reload(_msg_mod)
    importlib.reload(_fu_mod)
    importlib.reload(_audit_mod)
    _db_mod.init_db()
    _mg_mod.load_media_catalog()
    split_into_bubbles = _llm_mod.split_into_bubbles
    CONFIG = load_config()
    sys_prompt = _pe_mod.build_system_prompt(CONFIG)
    LLM = _llm_mod.LLMEngine(sys_prompt, CONFIG)
    return {"status": "reloaded", "ai_mode": LLM.get_status_label(), "public_base_url": PUBLIC_BASE_URL}


@app.post("/api/sync-facebook")
async def api_sync_facebook(limit: int = 50):
    """Sync real Facebook Messenger threads (names, paid orders, SKU, admin takeover) into SQLite."""
    synced = await messenger.sync_recent_facebook_conversations("buksukjai", limit=limit)
    paid_count = sum(1 for s in synced if s.get("is_paid"))
    return {
        "status": "ok",
        "total_synced": len(synced),
        "paid_customers_detected": paid_count,
        "customers": synced,
    }


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "brand": CONFIG.get("brand_persona", {}).get("brand_name"),
        "mock_mode": LLM.mock_mode if LLM else None,
        "pages_supported": len(load_pages_registry()),
    }
