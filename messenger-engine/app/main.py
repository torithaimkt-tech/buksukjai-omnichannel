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

from . import audit, database, followup, loyalty, media_generator, messenger  # noqa: E402
from .config_loader import (  # noqa: E402
    get_page_by_brand_id,
    load_brand_config,
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
_BRAND_CONFIGS: dict[str, dict] = {}
_BRAND_LLMS: dict[str, LLMEngine] = {}
PUBLIC_BASE_URL: str = os.getenv("PUBLIC_BASE_URL", "")
_TUNNEL_PROC = None
_RECENT_MSG_CACHE: dict[str, float] = {}


def _get_brand_config_and_llm(brand_id: str = "buksukjai") -> tuple[dict, LLMEngine]:
    """Return cached brand-specific config and LLMEngine (loads `config_mrbuk.json` for `mrbuk`)."""
    global CONFIG, LLM
    b_id = (brand_id or "buksukjai").strip().lower()
    if b_id == "buksukjai":
        if not CONFIG:
            CONFIG = load_config()
        if LLM is None:
            LLM = LLMEngine(build_system_prompt(CONFIG), CONFIG)
        return CONFIG, LLM

    if b_id not in _BRAND_CONFIGS:
        _BRAND_CONFIGS[b_id] = load_brand_config(b_id)
    cfg = _BRAND_CONFIGS[b_id]
    if b_id not in _BRAND_LLMS:
        _BRAND_LLMS[b_id] = LLMEngine(build_system_prompt(cfg), cfg)
    return cfg, _BRAND_LLMS[b_id]


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
                    "สวัสดีค่ะคุณลูกค้า 🍚🌿 ข้าวบุกสุขใจ (บุก 59% ผสมข้าวหอมมะลิ 29% และน้ำ 12% เพียง 23 kcal/25g) มีโปรโมชั่นดังนี้ค่ะ:\n"
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
            # (Ignore Meta automated system echoes like transfer requests or Ad welcome templates!)
            if message.get("is_echo"):
                echo_app_id = str(message.get("app_id") or "")
                if recipient_id and echo_app_id != "1414062917046427":
                    echo_txt = (text or "").strip()
                    echo_low = echo_txt.lower()
                    auto_meta_echo_markers = (
                        "messenger automatically created a transfer request",
                        "ส่งคำขอให้โอนแล้ว",
                        "คุณร้องขอไป ฿",
                        "ทำเครื่องหมายคำสั่งซื้อว่าชำระเงินแล้ว",
                        "เอเจนต์ ai ของคุณจะตอบกลับ",
                        "you took over this chat",
                        "ตอบกลับโฆษณา",
                        "กำลังตอบกลับความคิดเห็น",
                        "โปรโมชั่น ข้าวบุกสุขใจ",
                    )
                    is_auto_system_echo = (not echo_txt) or any(mk in echo_low for mk in auto_meta_echo_markers)
                    session_key = database.make_session_key(brand_id, platform, recipient_id)
                    database.get_or_create_session(
                        psid=session_key,
                        brand_id=brand_id,
                        platform=platform,
                        external_user_id=recipient_id,
                    )
                    if echo_txt:
                        database.log_message(session_key, "admin", echo_txt)
                    if not is_auto_system_echo:
                        logger.info("Human admin message logged in Meta Inbox for %s (AI stays ready for next customer reply)", session_key)
                continue

            if attachments:
                from . import jst_erp as _jst_img_mod

                for att in attachments:
                    att_type = str(att.get("type") or "").lower()
                    payload_obj = att.get("payload", {}) or {}
                    if att_type == "image":
                        img_url = payload_obj.get("url", "")
                        sticker_id = payload_obj.get("sticker_id")
                        # Ignore Facebook Thumbs-Up / stickers so they are never mistaken for payment slips
                        if sticker_id or "39178562_1505197616293642" in img_url:
                            continue
                        if img_url and sender_id:
                            session_key = database.make_session_key(brand_id, platform, sender_id)
                            sess_obj = database.get_or_create_session(
                                psid=session_key,
                                brand_id=brand_id,
                                platform=platform,
                                external_user_id=sender_id,
                            )
                            recent_u_txt = text or ""
                            if not recent_u_txt:
                                recent_hist = database.get_history(session_key, limit=4)
                                recent_u_txt = " ".join(
                                    str(m.get("content") or "") for m in recent_hist if m.get("role") == "user"
                                )
                            img_cls = _jst_img_mod.classify_incoming_chat_image(
                                image_url=img_url,
                                accompanying_text=recent_u_txt,
                                is_completed_order=(sess_obj.state == "completed"),
                            )
                            if img_cls.get("is_slip"):
                                database.log_message(session_key, "user", f"[IMAGE:{img_url}]")
                            elif img_cls.get("category") == "parcel_or_claim":
                                database.log_message(session_key, "user", f"[IMAGE_PARCEL:{img_url}]")
                            else:
                                database.log_message(session_key, "user", f"[IMAGE_PROMO:{img_url}]")
                            if not text:
                                text = str(img_cls.get("placeholder_text") or "[ลูกค้าแนบสลิปเข้ามาในแชทค่ะ]")
                    elif att_type in ("template", "fallback") and not text:
                        # Customer clicked Facebook's "คำขอโอนเงิน (Transfer Request)" button which hides the slip image from Graph API
                        text = "[ลูกค้ากดแนบสลิปผ่านปุ่มคำขอโอนเงิน Facebook]"

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

            enqueue_debounced_omnichannel_message(
                brand_id=brand_id,
                platform=platform,
                external_user_id=sender_id,
                text=text,
                reply_token=None,
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
        source_type = source.get("type", "user")
        user_id = source.get("userId")
        reply_token = event.get("replyToken")

        # Handle LINE Group / Multi-person Room events OR dedicated workbot (@934ndvfs) / coachbot (@346zyzej) separately
        # (Work Group / AI Coach Bot mode — never spam customer sales pitches!)
        if brand_id in ("workbot", "coachbot") or source_type in ("group", "room"):
            group_id = source.get("groupId") or source.get("roomId") or user_id
            if group_id:
                background_tasks.add_task(
                    _handle_line_group_event,
                    brand_id=brand_id if brand_id in ("workbot", "coachbot") else "workbot",
                    group_id=group_id,
                    group_type=source_type,
                    event_type=event_type or "",
                    event=event,
                    reply_token=reply_token,
                )
            continue

        if not user_id:
            continue

        if event_type == "follow":
            from .llm import FULL_PROMO_SUMMARY_BUBBLE, MRBUK_FULL_PROMO_SUMMARY_BUBBLE

            brand_cfg, _ = _get_brand_config_and_llm(brand_id)
            if brand_id == "mrbuk":
                greeting = (
                    f"{brand_cfg['brand_persona']['greeting_message']}|||"
                    f"{MRBUK_FULL_PROMO_SUMMARY_BUBBLE}|||"
                    "🎁 พิเศษสำหรับสมาชิก LINE @misterbuk! หากคุณลูกค้าสั่งซื้อครบ 500 บาท (หรือถุงใหญ่ 1 กก. 490.-) "
                    "สามารถพิมพ์แจ้ง เบอร์โทรศัพท์ 10 หลัก (หรือชื่อผู้รับ) ในแชทนี้เพื่อรับ QR Code สะสมแต้ม VIP ได้เลยนะคะ 💚"
                )
                all_promo_items = []
            else:
                greeting = f"{brand_cfg['brand_persona']['greeting_message']}|||{FULL_PROMO_SUMMARY_BUBBLE}"
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
                enqueue_debounced_omnichannel_message(
                    brand_id=brand_id,
                    platform="line",
                    external_user_id=user_id,
                    text=text,
                    reply_token=reply_token,
                )
            elif msg_type == "image":
                msg_id = str(msg_obj.get("id") or "").strip()
                background_tasks.add_task(
                    _handle_line_user_image_message,
                    brand_id=brand_id,
                    user_id=user_id,
                    msg_id=msg_id,
                    reply_token=reply_token,
                )

    return {"status": "ok"}


async def _handle_line_group_event(
    brand_id: str,
    group_id: str,
    group_type: str,
    event_type: str,
    event: dict,
    reply_token: str | None = None,
) -> None:
    """Handle LINE Group / Multi-person Room events as an internal work group bot:
    - Auto-registers the group ID for the 07:00 AM daily sales & stock report
    - Logs group messages and member join/leave activity without running customer sales replies
    - Responds immediately with the sales & stock summary when someone types 'สรุปยอด' or 'เช็กยอด'
    """
    import asyncio
    import re
    from datetime import datetime, timedelta, timezone
    from . import daily_sheet_report

    if event_type == "leave":
        if brand_id != "coachbot":
            daily_sheet_report.unregister_line_group(group_id)
        return

    psid = database.make_session_key(brand_id, "line_group", group_id)

    # =========================================================================
    # DEDICATED AI COACH BOT (@346zyzej Muzart พามู — brand_id == "coachbot")
    # Strictly for receiving screenshots & comments from Amy/Nut to update AI rules.
    # NEVER registers for daily sales reports and NEVER sends messages to customers!
    # =========================================================================
    if brand_id == "coachbot":
        database.get_or_create_session(
            psid=psid,
            brand_id="coachbot",
            platform="line_group",
            external_user_id=group_id,
            customer_name=f"กลุ่ม AI Coach ปรับปรุงบอท ({group_id[-6:]})",
        )
        database.set_bot_enabled(psid, False)

        if event_type in ("join", "follow"):
            coach_welcome = (
                "สวัสดีค่ะ ขออนุญาตรายงานตัวเข้ากลุ่ม AI Coach (รับคอมเมนต์ปรับปรุงแชทบอท) นะคะ 🙏💚\n"
                "บอทตัวนี้ (@346zyzej) แยกออกมาเฉพาะสำหรับการรับคอมเมนต์และรูปแคปหน้าจอจากคุณแอมมี่และคุณนัดค่ะ "
                "(ปลอดภัย 100% ไม่มีระบบส่งข้อความออกไปหาลูกค้าเด็ดขาดค่ะ)\n\n"
                "📌 วิธีใช้งานง่ายๆ ได้ตลอด 24 ชม. (แม้ปิดคอมพิวเตอร์):\n"
                "1. ส่งรูปแคปหน้าจอแชทลูกค้า + พิมพ์คอมเมนต์บอกจุดที่ต้องการให้ปรับปรุงได้เลยค่ะ\n"
                "2. หรือพิมพ์สั่งสอนกฎใหม่ / คำพูดที่อยากให้ใช้แทน / คำถาม-คำตอบใหม่ ได้เลยค่ะ\n"
                "3. ระบบจะอ่านรูปและคอมเมนต์ แล้วอัปเดตแก้ไขวิธีตอบของบอทในระบบออนไลน์ทันที พร้อมตอบกลับยืนยันในกลุ่มนี้ค่ะ 😊"
            )
            database.log_message(psid, "bot", coach_welcome, sender_label="AI Coach (@346zyzej)")
            await messenger.send_omnichannel_text("line", group_id, coach_welcome, "coachbot", reply_token)
            return

        if event_type == "message":
            msg_obj = event.get("message", {})
            msg_type = str(msg_obj.get("type") or "")
            sender_uid = (event.get("source") or {}).get("userId") or "ผู้บริหาร"

            if msg_type == "image":
                msg_id = str(msg_obj.get("id") or "").strip()
                database.log_message(
                    psid,
                    "user",
                    f"[ส่งรูปแคปหน้าจอเข้ามาในกลุ่ม AI Coach (ID: {msg_id})]",
                    sender_label=f"คุณแอมมี่/คุณนัด ({sender_uid[-6:]})",
                )
                data_url = await asyncio.to_thread(
                    daily_sheet_report.download_line_message_image_b64,
                    msg_id,
                    "coachbot",
                    group_id,
                )
                if data_url:
                    # Wait 20s in case a text comment is being typed right after the screenshot
                    await asyncio.sleep(20.0)
                    cached_img = daily_sheet_report._RECENT_GROUP_IMAGES.get(group_id) or {}
                    if cached_img.get("message_id") == msg_id and not cached_img.get("analyzed"):
                        coach_res = await asyncio.to_thread(
                            daily_sheet_report.process_line_group_coaching_feedback,
                            group_id,
                            "",
                            data_url,
                            sender_uid,
                        )
                        if coach_res and coach_res.get("reply_message"):
                            reply_msg = str(coach_res["reply_message"])
                            database.log_message(psid, "bot", reply_msg, sender_label="AI Coach (@346zyzej)")
                            await messenger.send_omnichannel_text("line", group_id, reply_msg, "coachbot", None)
                return

            if msg_type == "text":
                text = (msg_obj.get("text") or "").strip()
                if not text:
                    return
                database.log_message(psid, "user", text, sender_label=f"คุณแอมมี่/คุณนัด ({sender_uid[-6:]})")
                coach_res = await asyncio.to_thread(
                    daily_sheet_report.process_line_group_coaching_feedback,
                    group_id,
                    text,
                    None,
                    sender_uid,
                )
                if coach_res and coach_res.get("reply_message"):
                    reply_msg = str(coach_res["reply_message"])
                    database.log_message(psid, "bot", reply_msg, sender_label="AI Coach (@346zyzej)")
                    await messenger.send_omnichannel_text("line", group_id, reply_msg, "coachbot", reply_token)
                return
        return

    # =========================================================================
    # WORK GROUP BOT (@934ndvfs GENIUS POINT — brand_id == "workbot")
    # Strictly for 07:00 AM daily sales & stock summary + [#Q1] customer escalations
    # =========================================================================
    daily_sheet_report.register_line_group(group_id, brand_id=brand_id, group_type=group_type)

    if event_type == "join":
        welcome_text = (
            "สวัสดีค่ะ ขออนุญาตรายงานตัวเข้ากลุ่มงานนะคะ 🙏\n"
            "บันทึกกลุ่มนี้สำหรับแจ้งสรุปยอดประจำวันเรียบร้อยแล้วค่ะ\n"
            "• ทุกเช้าเวลา 07:00 น. (หลังคีย์ออเดอร์เสร็จ) บอทจะส่งสรุปยอดขายแต่ละช่องทาง ยอดโอน/COD และสรุปจำนวนสินค้าที่ตัดสต็อกโกดัง (60 กรัม / 500 กรัม / 1 กิโลกรัม) ของเมื่อวานให้ในกลุ่มนี้อัตโนมัติค่ะ\n"
            "• หากต้องการดูสรุปยอดทันที สามารถพิมพ์คำว่า สรุปยอด ในกลุ่มได้เลยนะคะ"
        )
        database.log_message(psid, "bot", welcome_text, sender_label="บอทสรุปยอดกลุ่มงาน")
        await messenger.send_omnichannel_text("line", group_id, welcome_text, brand_id, reply_token)
        return

    if event_type == "memberJoined":
        joined_members = event.get("joined", {}).get("members", [])
        database.log_message(
            psid,
            "user",
            f"[มีสมาชิกใหม่เข้าร่วมกลุ่มไลน์งาน {len(joined_members)} ท่านค่ะ]",
            sender_label="ระบบกลุ่มไลน์",
        )
        return

    if event_type == "memberLeft":
        left_members = event.get("left", {}).get("members", [])
        database.log_message(
            psid,
            "user",
            f"[มีสมาชิกออกจากกลุ่มไลน์งาน {len(left_members)} ท่านค่ะ]",
            sender_label="ระบบกลุ่มไลน์",
        )
        return

    if event_type == "message":
        msg_obj = event.get("message", {})
        msg_type = str(msg_obj.get("type") or "")
        sender_uid = (event.get("source") or {}).get("userId") or "สมาชิกในกลุ่ม"

        if msg_type == "image":
            msg_id = str(msg_obj.get("id") or "").strip()
            database.log_message(
                psid,
                "user",
                f"[ส่งรูปภาพเข้ามาในกลุ่มสรุปยอด (ID: {msg_id})]",
                sender_label=f"สมาชิกกลุ่ม ({sender_uid[-6:]})",
            )
            return

        if msg_type != "text":
            return
        text = (msg_obj.get("text") or "").strip()
        if not text:
            return
        quoted_msg_id = str(msg_obj.get("quotedMessageId") or "").strip() or None
        database.log_message(psid, "user", text, sender_label=f"สมาชิกกลุ่ม ({sender_uid[-6:]})")

        pre_key_keywords = (
            "เช็กออเดอร์",
            "เช็คออเดอร์",
            "เช็ก jst",
            "เช็ค jst",
            "ตรวจ jst",
            "ตรวจออเดอร์ก่อนคีย์",
            "คีย์หรือยัง",
        )
        if any(k in text.lower() for k in pre_key_keywords):
            from . import jst_erp

            await messenger.sync_recent_facebook_conversations("buksukjai", limit=40)
            chk = await asyncio.to_thread(jst_erp.build_pre_keying_jst_checklist, 2)
            msg_out = str(chk.get("summary_text") or "")
            if msg_out:
                database.log_message(psid, "bot", msg_out, sender_label="บอทตรวจสอบออเดอร์ JST")
                await messenger.send_omnichannel_text("line", group_id, msg_out, brand_id, reply_token)
            return

        auto_key_keywords = ("คีย์ออเดอร์", "คีย์ jst", "สั่งคีย์ออเดอร์")
        if any(k in text.lower() for k in auto_key_keywords):
            from . import jst_erp

            await messenger.sync_recent_facebook_conversations("buksukjai", limit=60)
            sync_res = await asyncio.to_thread(jst_erp.sync_all_confirmed_orders_to_jst, 2, False)
            chk = await asyncio.to_thread(jst_erp.build_pre_keying_jst_checklist, 2)
            created_cnt = len(sync_res.get("created") or [])
            dup_cnt = len(sync_res.get("duplicate_skipped") or [])
            msg_out = (
                f"🤖 ระบบอัตโนมัติตรวจสอบและคีย์ออเดอร์ลง JST ERP เรียบร้อยแล้วค่ะ!\n"
                f"• คีย์ออเดอร์ใหม่สำเร็จ : {created_cnt} รายการ\n"
                f"• ป้องกันออเดอร์ซ้ำ (ข้ามอัตโนมัติ) : {dup_cnt} รายการ\n\n"
                f"{chk.get('summary_text') or ''}"
            )
            database.log_message(psid, "bot", msg_out, sender_label="บอทคีย์ออเดอร์ JST")
            await messenger.send_omnichannel_text("line", group_id, msg_out, brand_id, reply_token)
            return

        trigger_keywords = ("สรุปยอด", "เช็กยอด", "เช็คยอด", "รายงานยอด", "ยอดขายเมื่อวาน", "ลงทะเบียนกลุ่ม", "ทดสอบบอท", "เทสบอท")
        if any(k in text for k in trigger_keywords):
            bkk_tz = timezone(timedelta(hours=7))
            now_bkk = datetime.now(bkk_tz)
            m_date = re.search(r"(202\d-\d{2}-\d{2})", text)
            if m_date:
                target_date = m_date.group(1)
            elif "วันนี้" in text:
                target_date = now_bkk.strftime("%Y-%m-%d")
            else:
                target_date = (now_bkk - timedelta(days=1)).strftime("%Y-%m-%d")

            res = await asyncio.to_thread(
                daily_sheet_report.send_daily_summary_to_line_groups,
                target_date,
                brand_id,
                group_id,
                reply_token,
                False,
            )
            if res.get("summary_text"):
                database.log_message(psid, "bot", res["summary_text"], sender_label="บอทสรุปยอดกลุ่มงาน")
            return

        # Check if someone in the LINE Group is answering a paused customer escalation!
        matched_esc = await asyncio.to_thread(
            daily_sheet_report.resolve_line_group_escalation_reply,
            text,
            quoted_msg_id,
        )
        if matched_esc:
            cust_psid = str(matched_esc.get("psid") or "")
            cust_brand = str(matched_esc.get("brand_id") or "buksukjai")
            cust_plat = str(matched_esc.get("platform") or "facebook")
            cust_ext_id = str(matched_esc.get("external_user_id") or "")
            cust_name = str(matched_esc.get("customer_name") or "คุณลูกค้า")
            cust_reply = str(matched_esc.get("customer_reply") or "")
            case_id = str(matched_esc.get("case_id") or "Q")

            if cust_psid and cust_ext_id and cust_reply:
                # 1. Log & send the answer to the customer on their original platform (Facebook / LINE OA / IG)
                database.log_message(cust_psid, "admin", cust_reply, sender_label="แอดมิน (ตอบผ่านกลุ่ม LINE)")
                await messenger.send_omnichannel_text(
                    platform=cust_plat,
                    external_user_id=cust_ext_id,
                    text=cust_reply,
                    brand_id=cust_brand,
                )

                # 2. Unpause the AI bot for this customer so AI can continue assisting after the answer
                try:
                    cust_sess = database.get_or_create_session(cust_psid)
                    raw_tags = getattr(cust_sess, "broadcast_tags", "") or ""
                    cleaned_tags = ",".join(
                        t.strip()
                        for t in raw_tags.split(",")
                        if t.strip() and "รอแอดมิน" not in t
                    )
                    new_tags = database._add_tag_str(cleaned_tags, "แอดมินตอบผ่านกลุ่มแล้ว")
                    database.update_session_meta(
                        psid=cust_psid,
                        bot_enabled=True,
                        broadcast_tags=new_tags,
                        clear_unread=True,
                    )
                except Exception as exc:
                    logger.warning("Failed to re-enable bot for %s after LINE group reply: %s", cust_psid, exc)
                    database.set_bot_enabled(cust_psid, True)

                # 3. Confirm back inside the LINE Summary Group
                plat_label = {"facebook": "Facebook เพจ", "line": "LINE OA", "instagram": "Instagram DM"}.get(cust_plat.lower(), cust_plat)
                confirm_msg = (
                    f"✅ ส่งคำตอบ [#{case_id}] ให้ {cust_name} ({plat_label}) เรียบร้อยแล้วค่ะ!\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"💬 ข้อความที่ส่งให้ลูกค้า :\n"
                    f"“{cust_reply}”\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"🤖 เปิดบอท AI ดูแลแชทลูกค้าท่านนี้ต่อให้อัตโนมัติแล้วค่ะ (และบันทึกคำตอบนี้ไว้ให้ AI จำไปใช้ในครั้งต่อไปเรียบร้อยค่ะ) 🙏💚"
                )
                database.log_message(psid, "bot", confirm_msg, sender_label="บอทสรุปยอดกลุ่มงาน")
                await messenger.send_omnichannel_text("line", group_id, confirm_msg, brand_id, reply_token)
                return


# --- 3.5-Second Per-Customer Debounce & Image Type Classifier (LINE & Meta) -----

DEBOUNCE_WAIT_SECONDS: float = 3.5
_DEBOUNCE_BUFFERS: dict[str, dict] = {}


def enqueue_debounced_omnichannel_message(
    brand_id: str,
    platform: str,
    external_user_id: str,
    text: str,
    customer_name: str = "",
    reply_token: str | None = None,
    wait_seconds: float = DEBOUNCE_WAIT_SECONDS,
) -> None:
    """Buffer rapid consecutive customer messages/images for `wait_seconds` (3.5s) per customer:
    - Immediately logs each incoming bubble to DB in arrival order.
    - Always keeps the LATEST `reply_token` so LINE OA replies once for free without using Push Message quota.
    - Prevents the bot from replying 'รบกวนส่งสลิปนะคะ' while the customer is attaching the slip 2 seconds later.
    """
    import asyncio

    clean_t = (text or "").strip()
    if not clean_t or not external_user_id:
        return

    session_key = database.make_session_key(brand_id, platform, external_user_id)
    database.get_or_create_session(
        psid=session_key,
        brand_id=brand_id,
        platform=platform,
        external_user_id=external_user_id,
        customer_name=customer_name,
    )
    database.log_message(session_key, "user", clean_t)

    buf = _DEBOUNCE_BUFFERS.get(session_key)
    if buf is None:
        buf = {
            "brand_id": brand_id,
            "platform": platform,
            "external_user_id": external_user_id,
            "customer_name": customer_name,
            "texts": [],
            "reply_token": None,
            "timer_task": None,
        }
        _DEBOUNCE_BUFFERS[session_key] = buf

    buf["texts"].append(clean_t)
    if customer_name:
        buf["customer_name"] = customer_name
    # Always overwrite with the LAST message's reply_token so LINE Reply API succeeds for free
    if reply_token:
        buf["reply_token"] = reply_token

    old_task = buf.get("timer_task")
    if old_task and not old_task.done():
        old_task.cancel()

    # Smart Context Wait (Adaptive Debounce):
    # If the customer sends a very short 1-2 word fragment (<= 12 chars, e.g. "ไม่คะ", "คือว่า", "เดี๋ยว", "สอบถามค่ะ")
    # that is not a standalone 'สนใจ'/'ราคา' trigger, wait a bit longer (6.0s on LINE / 8.0s on FB/IG)
    # in case they are typing a second bubble explaining their context right after!
    effective_wait = wait_seconds
    combined_now = "\n".join(buf["texts"]).strip()
    if (
        len(combined_now) <= 12
        and not combined_now.startswith("[ลูกค้า")
        and combined_now.lower() not in ("สนใจ", "สนใจค่ะ", "สนใจคะ", "ราคา", "ขอราคา", "โอน", "โอนค่ะ", "โอนคะ")
    ):
        effective_wait = max(wait_seconds, 6.0 if platform == "line" else 8.0)

    async def _flush_after_delay() -> None:
        try:
            await asyncio.sleep(effective_wait)
        except asyncio.CancelledError:
            return
        entry = _DEBOUNCE_BUFFERS.pop(session_key, None)
        if not entry or not entry.get("texts"):
            return
        combined_text = "\n".join(entry["texts"])
        latest_token = entry.get("reply_token")
        await process_omnichannel_message(
            brand_id=entry["brand_id"],
            platform=entry["platform"],
            external_user_id=entry["external_user_id"],
            text=combined_text,
            customer_name=entry.get("customer_name") or "",
            reply_token=latest_token,
            skip_user_log=True,
        )

    buf["timer_task"] = asyncio.create_task(_flush_after_delay())


async def _handle_line_user_image_message(
    brand_id: str,
    user_id: str,
    msg_id: str,
    reply_token: str | None = None,
) -> None:
    """Download customer image from LINE Content API ($0 cost), classify whether it is:
    1) Payment slip, 2) Promo/product photo, or 3) Parcel/damage photo,
    and feed into the 3.5s per-customer debounce buffer with the latest `reply_token`.
    """
    import asyncio
    import httpx
    from . import jst_erp

    session_key = database.make_session_key(brand_id, "line", user_id)
    sess_obj = database.get_or_create_session(
        psid=session_key,
        brand_id=brand_id,
        platform="line",
        external_user_id=user_id,
    )

    img_bytes: bytes | None = None
    rel_url = ""
    token = messenger._get_channel_token(brand_id, "line")
    if token and msg_id:
        try:
            async with httpx.AsyncClient(timeout=12.0) as client:
                r = await client.get(
                    f"https://api-data.line.me/v2/bot/message/{msg_id}/content",
                    headers={"Authorization": f"Bearer {token}"},
                )
                if r.status_code == 200 and r.content:
                    img_bytes = r.content
                    media_generator.MEDIA_DIR.mkdir(parents=True, exist_ok=True)
                    fname = f"line_img_{msg_id}.jpg"
                    (media_generator.MEDIA_DIR / fname).write_bytes(img_bytes)
                    rel_url = f"/static/media/{fname}"
        except Exception as exc:
            logger.warning("Failed to download LINE user image %s: %s", msg_id, exc)

    recent_hist = database.get_history(session_key, limit=4)
    recent_u_txt = " ".join(str(m.get("content") or "") for m in recent_hist if m.get("role") == "user")
    buf_now = _DEBOUNCE_BUFFERS.get(session_key)
    if buf_now and buf_now.get("texts"):
        recent_u_txt = f"{recent_u_txt} {' '.join(buf_now['texts'])}".strip()

    img_cls = await asyncio.to_thread(
        jst_erp.classify_incoming_chat_image,
        rel_url,
        img_bytes,
        0,
        0,
        recent_u_txt,
        sess_obj.state == "completed",
    )
    if rel_url:
        if img_cls.get("is_slip"):
            database.log_message(session_key, "user", f"[IMAGE:{rel_url}]")
        elif img_cls.get("category") == "parcel_or_claim":
            database.log_message(session_key, "user", f"[IMAGE_PARCEL:{rel_url}]")
        else:
            database.log_message(session_key, "user", f"[IMAGE_PROMO:{rel_url}]")

    placeholder = str(img_cls.get("placeholder_text") or "[ลูกค้าแนบสลิปเข้ามาในแชทค่ะ]")
    enqueue_debounced_omnichannel_message(
        brand_id=brand_id,
        platform="line",
        external_user_id=user_id,
        text=placeholder,
        reply_token=reply_token,
    )


# --- Unified Message Processor (AI + Human Handover) ----------------------------

async def process_omnichannel_message(
    brand_id: str,
    platform: str,
    external_user_id: str,
    text: str,
    customer_name: str = "",
    reply_token: str | None = None,
    skip_user_log: bool = False,
) -> dict:
    session_key = database.make_session_key(brand_id, platform, external_user_id)
    try:
        # Real-time Facebook Graph API verification BEFORE replying:
        # Checks if customer already ordered/paid in past Facebook history or if human admin is handling the chat!
        if platform == "facebook" and not str(external_user_id).startswith(("FB_", "sim_", "test_")):
            await messenger.sync_facebook_user_thread(external_user_id, brand_id=brand_id)

        user = database.get_or_create_session(
            psid=session_key,
            brand_id=brand_id,
            platform=platform,
            external_user_id=external_user_id,
            customer_name=customer_name,
        )
        if not skip_user_log:
            database.log_message(session_key, "user", text)

        from .llm import (
            is_active_order_or_payment_intent,
            is_bank_transfer_request,
            is_customer_claiming_paid,
        )

        transfer_req = is_bank_transfer_request(text)
        claimed_paid = is_customer_claiming_paid(text) or (
            text == "[ลูกค้ากดแนบสลิปผ่านปุ่มคำขอโอนเงิน Facebook]"
        )
        # If customer explicitly asks for bank account, chooses bank transfer, or claims they paid,
        # ALWAYS auto-wake the bot so it works 100% autonomously without human admins!
        if not user.bot_enabled and (transfer_req or claimed_paid):
            raw_tags = getattr(user, "broadcast_tags", "") or ""
            cleaned_tags = ",".join(
                t.strip() for t in raw_tags.split(",") if t.strip() and "รอแอดมิน" not in t
            )
            database.update_session_meta(session_key, bot_enabled=True, broadcast_tags=cleaned_tags)
            user.bot_enabled = True
            user.broadcast_tags = cleaned_tags
            logger.info("Auto-re-enabled AI bot for %s on payment/transfer event: %s", session_key, text)

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
        wants_to_reorder = (
            is_active_order_or_payment_intent(text)
            or transfer_req
            or (user.state == "pending_payment")
        )
        wants_to_cancel = (
            "ไม่ยกเลิก" not in low_txt
            and any(
                w in low_txt
                for w in ("ขอยกเลิก", "ยกเลิกก่อน", "ยกเลิกค่ะ", "ยกเลิกคะ", "ยกเลิกครับ", "ยกเลิกนะ", "ไม่เอาแล้ว", "ไม่รับแล้ว", "ยังไม่รับ", "แคนเซิล", "cancel")
            )
        ) or low_txt in ("ยกเลิก", "cancel")
        if wants_to_cancel:
            is_paid_customer = False
            database.update_session_meta(session_key, state="browsing", is_starred=False)
            user.state = "browsing"
            user.is_starred = False

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
        has_user_slip_image = any(
            m.get("role") == "user" and str(m.get("content", "")).startswith("[IMAGE:")
            for m in history
        )
        # Zero-Human Auto-Slip Recovery:
        # If customer says "โอนแล้วค่ะ / โอนไปแล้วค่ะ" or clicks Facebook's hidden Transfer Request button,
        # but Graph API has NO visible [IMAGE:...] slip in normal chat, politely ask them to send the slip image in normal chat!
        if platform == "facebook" and claimed_paid and not has_user_slip_image:
            recovery_msg = (
                "ขอบพระคุณมากค่ะคุณลูกค้า 🍚💚 พอดีหากกดแนบสลิปผ่านปุ่ม 'คำขอโอนเงิน' ของระบบ Facebook "
                "รูปสลิปจะไม่แสดงในระบบจัดส่งอัตโนมัติของทางร้านค่ะ รบกวนคุณลูกค้ากดส่งรูปสลิปลงในช่องแชทปกติ "
                "(กดปุ่มรูปภาพด้านล่างซ้ายของแชท) อีกครั้งนะคะ พอน้องบุกได้รับรูปสลิปแล้วจะรีบตัดสต็อกและจัดส่งให้ทันทีเลยค่ะ 😊🙏"
            )
            database.log_message(session_key, "assistant", recovery_msg)
            await messenger.send_omnichannel_text(
                platform=platform,
                external_user_id=external_user_id,
                text=recovery_msg,
                brand_id=brand_id,
                reply_token=reply_token,
            )
            logger.info("Sent Auto-Slip Recovery prompt to %s (claimed paid without visible API image)", session_key)
            return {
                "session_key": session_key,
                "bot_replied": True,
                "reply": recovery_msg,
                "bubbles": [recovery_msg],
                "state": user.state,
            }

        clean_history = [
            m for m in history if not str(m.get("content", "")).startswith("[IMAGE:")
        ]

        # Mr.Buk VIP LINE OA Loyalty & Point Accumulation Handler (@misterbuk / @305lhvvt)
        if brand_id == "mrbuk" and platform in ("line", "web"):
            import asyncio as _aio_loy

            prior_history = clean_history[:-1] if len(clean_history) >= 1 else []
            loyalty_res = await _aio_loy.to_thread(
                loyalty.handle_line_loyalty_message,
                text,
                external_user_id,
                prior_history,
                brand_id,
            )
            if loyalty_res is not None:
                loy_bubbles = loyalty_res.get("bubbles") or []
                loy_media = loyalty_res.get("media_items") or []
                for item in loy_media:
                    database.log_message(session_key, "assistant", f"[IMAGE:{item['relative_url']}]")
                for b in loy_bubbles:
                    database.log_message(session_key, "assistant", b)
                await messenger.send_omnichannel_text(
                    platform=platform,
                    external_user_id=external_user_id,
                    text="|||".join(loy_bubbles),
                    brand_id=brand_id,
                    reply_token=reply_token,
                    media_items=loy_media,
                    public_base_url=PUBLIC_BASE_URL,
                )
                return {
                    "session_key": session_key,
                    "bot_replied": True,
                    "reply": "\n\n".join(loy_bubbles),
                    "bubbles": loy_bubbles,
                    "image_url": loy_media[0]["relative_url"] if loy_media else None,
                    "images": [it["relative_url"] for it in loy_media],
                    "state": user.state,
                    "loyalty": loyalty_res.get("details") or {"status": loyalty_res.get("status")},
                }

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

        brand_config, brand_llm = _get_brand_config_and_llm(brand_id)
        reply, new_state, image_key = await brand_llm.generate(clean_history, user.state)

        # Smart fallback: whenever customer asks for promo/price/sizes/interest, send ALL 4 promo images ('promo_all') at once!
        explicitly_asked_pic = (not is_attachment_placeholder) and (not transfer_req) and (not is_paid_customer or wants_to_reorder) and any(
            w in low_txt for w in ("รูป", "ภาพ", "โปร", "ราคา", "สนใจ", "กี่บาท", "เท่าไหร่", "ขนาด", "ไซส์", "ขายยังไง")
        )
        if is_attachment_placeholder or transfer_req or (is_paid_customer and not wants_to_reorder) or brand_id == "mrbuk":
            if is_attachment_placeholder or transfer_req or (is_paid_customer and not wants_to_reorder):
                image_key = "none"
                if is_paid_customer and not wants_to_reorder:
                    new_state = "completed"
        elif image_key == "promo_3sizes" or ((not image_key or image_key == "none") and explicitly_asked_pic):
            image_key = "promo_all"

        # Layer-1 Automated Pre-Send Audit (ตรวจสอบความถูกต้อง 7 ข้อก่อนส่งให้ลูกค้าจริง)
        llm_esc = getattr(brand_llm, "last_escalation", None) if brand_llm else None
        bubbles, new_state, selected_media_items, audit_report = audit.audit_outgoing_reply(
            psid=session_key,
            brand_id=brand_id,
            user_session=user,
            history=clean_history,
            raw_reply=reply,
            proposed_state=new_state,
            proposed_image_key=image_key,
            config=brand_config,
            llm_escalation=llm_esc,
        )

        # 1. Log promo image(s) FIRST in Admin Inbox DB
        for item in selected_media_items:
            database.log_message(session_key, "assistant", f"[IMAGE:{item['relative_url']}]")

        # 2. Then log the 1–2 short accompanying text bubbles right after
        for b in bubbles:
            database.log_message(session_key, "assistant", b)

        audited_reply_text = "|||".join(bubbles)
        database.update_state(session_key, new_state)
        if audited_reply_text or selected_media_items:
            await messenger.send_omnichannel_text(
                platform=platform,
                external_user_id=external_user_id,
                text=audited_reply_text,
                brand_id=brand_id,
                reply_token=reply_token,
                media_items=selected_media_items,
                public_base_url=PUBLIC_BASE_URL,
            )
        # If AI encountered an unfamiliar/uncertain question, notify the LINE Summary Work Group immediately
        if audit_report.get("escalate_to_line_group"):
            import asyncio
            from . import daily_sheet_report

            esc_reason = str(audit_report.get("escalation_reason") or "คำถามแปลกใหม่ / AI ไม่มั่นใจคำตอบ")
            try:
                esc_res = await asyncio.to_thread(
                    daily_sheet_report.send_escalation_alert_to_line_groups,
                    session_key,
                    brand_id,
                    platform,
                    user.customer_name or customer_name,
                    text,
                    "\n".join(bubbles),
                    esc_reason,
                )
                audit_report["line_group_alert"] = esc_res.get("status")
            except Exception as esc_err:
                logger.warning("Failed to send LINE group escalation alert for %s: %s", session_key, esc_err)
        # Immediately key the order into JST ERP right after the Messenger conversation is 100% confirmed (with strict 5-point audit & duplicate check)
        if new_state == "completed":
            database.update_session_meta(session_key, state="completed", is_starred=True)
            try:
                import asyncio as _aio
                from . import jst_erp

                if jst_erp.is_auto_sync_enabled():
                    jst_res = await _aio.to_thread(jst_erp.sync_session_to_jst, session_key)
                    audit_report["jst_instant_sync"] = jst_res.get("status")
                    logger.info("Instant post-chat JST sync for %s: %s", session_key, jst_res.get("status"))
            except Exception as jst_err:
                logger.warning("Instant post-chat JST sync warning for %s: %s", session_key, jst_err)
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
            "bot_replied": bool(bubbles or selected_media_items),
            "reply": "\n\n".join(bubbles) if bubbles else None,
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


_LAST_FB_BULK_SYNC_TS: float = 0.0
_LAST_FB_THREAD_SYNC: dict[str, float] = {}


@app.get("/api/sessions")
async def api_list_sessions(
    brand_id: str = "all",
    platform: str = "all",
    state: str = "all",
):
    import time

    global _LAST_FB_BULK_SYNC_TS
    rows = database.list_all_sessions(brand_id=brand_id, platform=platform, state=state)
    now = time.time()
    has_empty_fb = any(r.get("platform") == "facebook" and not r.get("last_message") for r in rows[:15])
    if has_empty_fb and (now - _LAST_FB_BULK_SYNC_TS > 60):
        _LAST_FB_BULK_SYNC_TS = now
        target_brand = brand_id if (brand_id and brand_id != "all") else "buksukjai"
        await messenger.sync_recent_facebook_conversations(target_brand, limit=40)
        rows = database.list_all_sessions(brand_id=brand_id, platform=platform, state=state)
    return rows


@app.get("/api/sessions/{psid:path}/messages")
async def api_get_messages(psid: str, sync: bool = False):
    import time

    database.update_session_meta(psid, clear_unread=True)
    msgs = database.get_full_messages(psid)
    if ":facebook:" in psid:
        now = time.time()
        last_sync = _LAST_FB_THREAD_SYNC.get(psid, 0.0)
        if not msgs or sync or (now - last_sync > 45):
            _LAST_FB_THREAD_SYNC[psid] = now
            parts = psid.split(":", 2)
            if len(parts) == 3:
                b_id, _, ext_id = parts
                await messenger.sync_facebook_user_thread(ext_id, brand_id=b_id)
                msgs = database.get_full_messages(psid)
    return msgs


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


@app.get("/api/jst/pre-keying-check")
async def api_jst_pre_keying_check(days_lookback: int = 2):
    """Check which recent confirmed chat orders have already been keyed into JST ERP vs which ones still need keying."""
    import asyncio
    from . import jst_erp

    await messenger.sync_recent_facebook_conversations("buksukjai", limit=40)
    return await asyncio.to_thread(jst_erp.build_pre_keying_jst_checklist, days_lookback)


@app.post("/api/reload")
async def api_hot_reload():
    """Hot-reload config.json, prompt_engine, media_generator, database, followup, audit, loyalty, and llm in memory without restarting the tunnel."""
    import importlib
    from . import audit as _audit_mod
    from . import daily_sheet_report as _dsr_mod
    from . import database as _db_mod
    from . import followup as _fu_mod
    from . import llm as _llm_mod
    from . import loyalty as _loy_mod
    from . import media_generator as _mg_mod
    from . import messenger as _msg_mod
    from . import prompt_engine as _pe_mod

    global CONFIG, LLM, split_into_bubbles, _BRAND_CONFIGS, _BRAND_LLMS
    importlib.reload(_pe_mod)
    importlib.reload(_llm_mod)
    importlib.reload(_db_mod)
    importlib.reload(_mg_mod)
    importlib.reload(_loy_mod)
    importlib.reload(_msg_mod)
    importlib.reload(_fu_mod)
    importlib.reload(_audit_mod)
    importlib.reload(_dsr_mod)
    _db_mod.init_db()
    _mg_mod.load_media_catalog()
    split_into_bubbles = _llm_mod.split_into_bubbles
    _BRAND_CONFIGS.clear()
    _BRAND_LLMS.clear()
    CONFIG = load_config()
    sys_prompt = _pe_mod.build_system_prompt(CONFIG)
    LLM = _llm_mod.LLMEngine(sys_prompt, CONFIG)
    return {"status": "reloaded", "ai_mode": LLM.get_status_label(), "public_base_url": PUBLIC_BASE_URL}


class LoyaltyClaimRequest(BaseModel):
    phone: str = ""
    customer_name: str = ""
    line_user_id: str = ""
    brand_id: str = "mrbuk"


class LoyaltyRedeemRequest(BaseModel):
    phone: str = ""
    line_user_id: str = ""
    requested_tier: int | None = None
    brand_id: str = "mrbuk"


@app.get("/api/loyalty/members")
async def api_loyalty_list_members(brand_id: str = "mrbuk"):
    """List all registered Mr.Buk VIP loyalty members and their claimed orders."""
    import asyncio

    members = await asyncio.to_thread(loyalty.list_all_loyalty_members, brand_id)
    return {"status": "ok", "count": len(members), "members": members}


@app.get("/api/loyalty/lookup")
async def api_loyalty_lookup(
    phone: str = "",
    customer_name: str = "",
    line_user_id: str = "",
    brand_id: str = "mrbuk",
):
    """Look up verifiable orders from Facebook (chatbot.db) and JST ERP (check_duplicate_order) plus member balance."""
    import asyncio

    orders_info = await asyncio.to_thread(loyalty.find_verifiable_orders, phone, customer_name, brand_id)
    member_info = await asyncio.to_thread(
        loyalty.get_member_summary,
        orders_info.get("phone") or phone,
        line_user_id,
        brand_id,
    )
    return {
        "status": "ok",
        "resolved_phone": orders_info.get("phone"),
        "resolved_customer_name": orders_info.get("customer_name"),
        "verifiable_orders": orders_info.get("orders"),
        "member": member_info,
    }


@app.post("/api/loyalty/claim")
async def api_loyalty_claim(body: LoyaltyClaimRequest):
    """Verify orders by 10-digit phone or recipient name, prevent duplicate bill claims, award points, and return QR Code images."""
    import asyncio

    return await asyncio.to_thread(
        loyalty.claim_points_for_customer,
        body.phone,
        body.customer_name,
        body.line_user_id,
        body.brand_id,
    )


@app.post("/api/loyalty/redeem")
async def api_loyalty_redeem(body: LoyaltyRedeemRequest):
    """Redeem 5 points (free 60g x 3) or 10 points (free 500g x 1) to be shipped with the customer's next order."""
    import asyncio

    return await asyncio.to_thread(
        loyalty.redeem_loyalty_points,
        body.phone,
        body.line_user_id,
        body.requested_tier,
        body.brand_id,
    )


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


@app.get("/api/reports/daily-sales")
async def api_get_daily_sales_report(date: str | None = None):
    """Return daily sales & SKU stock reconciliation report JSON (defaults to yesterday in Bangkok time)."""
    import asyncio
    from datetime import datetime, timedelta, timezone
    from . import daily_sheet_report

    bkk_tz = timezone(timedelta(hours=7))
    target_date = date or (datetime.now(bkk_tz) - timedelta(days=1)).strftime("%Y-%m-%d")
    rep = await asyncio.to_thread(daily_sheet_report.load_or_build_daily_report, target_date)
    return rep


@app.get("/api/reports/daily-sales.csv")
async def api_get_daily_sales_csv(date: str | None = None):
    """Return UTF-8 CSV for Google Sheets `=IMPORTDATA(...)` or direct cloud sync (defaults to yesterday in Bangkok time)."""
    import asyncio
    import csv
    import io
    from datetime import datetime, timedelta, timezone
    from . import daily_sheet_report

    bkk_tz = timezone(timedelta(hours=7))
    target_date = date or (datetime.now(bkk_tz) - timedelta(days=1)).strftime("%Y-%m-%d")
    rep = await asyncio.to_thread(daily_sheet_report.load_or_build_daily_report, target_date)
    buf = io.StringIO()
    writer = csv.writer(buf)
    for row in rep["sheet_rows"]:
        writer.writerow(row)
    return Response(content=buf.getvalue(), media_type="text/csv; charset=utf-8")


@app.get("/api/line-groups")
async def api_get_line_groups():
    """Return registered LINE Work Group IDs and 07:00 AM daily broadcast state."""
    from . import daily_sheet_report

    cfg = daily_sheet_report.load_line_group_config()
    return {
        "status": "ok",
        "groups": cfg.get("groups", []),
        "group_meta": cfg.get("group_meta", {}),
        "last_7am_report_date": cfg.get("last_7am_report_date", ""),
        "last_7am_sent_at": cfg.get("last_7am_sent_at", ""),
    }


@app.post("/api/line-groups/send-summary")
async def api_send_line_group_summary(
    date: str | None = None,
    group_id: str | None = None,
    brand_id: str = "buksukjai",
):
    """Manually trigger or test the daily sales & stock reconciliation summary push to registered LINE Work Groups."""
    import asyncio
    from . import daily_sheet_report

    if group_id:
        daily_sheet_report.register_line_group(group_id, brand_id=brand_id)
    return await asyncio.to_thread(
        daily_sheet_report.send_daily_summary_to_line_groups,
        date,
        brand_id,
        group_id,
        None,
        False,
    )


@app.get("/api/db/status")
async def db_status():
    return database.get_database_status()


@app.get("/api/n8n/workflows")
async def list_n8n_workflows():
    wf_dir = Path(__file__).resolve().parent.parent / "n8n_workflows"
    workflows = []
    if wf_dir.exists():
        for fp in sorted(wf_dir.glob("*.json")):
            try:
                with open(fp, encoding="utf-8") as f:
                    data = json.load(f)
                workflows.append(
                    {
                        "file": fp.name,
                        "name": data.get("name", fp.stem),
                        "nodes_count": len(data.get("nodes", [])),
                        "workflow": data,
                    }
                )
            except Exception as exc:
                logger.warning("Failed to read n8n workflow %s: %s", fp.name, exc)
    return {"status": "ok", "count": len(workflows), "workflows": workflows}


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "brand": CONFIG.get("brand_persona", {}).get("brand_name"),
        "mock_mode": LLM.mock_mode if LLM else None,
        "pages_supported": len(load_pages_registry()),
        "database": database.get_database_status(),
    }
