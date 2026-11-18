"""3-Page Admin QA & Sales Conversion Monitor (`พุดดิ้ง🍮 @346zyzej`).

Provides:
1. Live 3-Page Facebook Graph API Monitor (100% Read-Only — never sends messages to customers):
   - `Mr.Buk มิสเตอร์บุก` (`110007064468438`)
   - `ข้าวบุกหอมมะลิ (เพจ 2)` (`772314109306371`)
   - `ข้าวบุก สุขใจ` (`806129109240845`)
2. Dynamic Web Dashboard (`/admin-report?date=YYYY-MM-DD`) with 4-hour breakdown, real chat QA cases, and copyable scripts.
3. Concise LINE Group Summary + Dashboard Link sent via `พุดดิ้ง🍮 (@346zyzej)` (`coachbot`).
4. Strict Single-Group Lock (`C5b961d8bd8703af909d4ed769d63a18a` `ข้าวบุกคุณพลอยรวม`) and 01:00 AM daily schedule.
"""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import html
import json
import logging
import os
from pathlib import Path
import re
import time
from typing import Any

from fastapi.responses import HTMLResponse
import httpx

from .config_loader import get_page_by_brand_id

logger = logging.getLogger(__name__)

BKK_TZ = timezone(timedelta(hours=7))
COMMENT_TEST_GROUP_ID = "Cf0c8835b5b0711e80f7350ffc9af66f1"
PLOY_ADMIN_GROUP_ID = "C5b961d8bd8703af909d4ed769d63a18a"
PLOY_ADMIN_GROUP_NAME = "ข้าวบุกคุณพลอยรวม"
ADMIN_REPORT_STATE_FILE = Path(__file__).resolve().parent.parent / "admin_report_state.json"

THREE_PAGES_SPECS = [
    {
        "key": "mrbuk",
        "page_id": "110007064468438",
        "title": "Mr.Buk มิสเตอร์บุก",
        "short_name": "Mr.Buk",
        "css_class": "mrbuk",
    },
    {
        "key": "hommali",
        "page_id": "772314109306371",
        "title": "ข้าวบุกหอมมะลิ (เพจ 2)",
        "short_name": "หอมมะลิ",
        "css_class": "hommali",
    },
    {
        "key": "buksukjai",
        "page_id": "806129109240845",
        "title": "ข้าวบุก สุขใจ",
        "short_name": "สุขใจ",
        "css_class": "sukjai",
    },
]

THAI_WEEKDAYS = ["วันจันทร์", "วันอังคาร", "วันพุธ", "วันพฤหัสบดี", "วันศุกร์", "วันเสาร์", "วันอาทิตย์"]
THAI_MONTHS_SHORT = ["", "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]

TIME_BUCKET_SPECS = [
    (0, 4, "00:00 – 04:00 น.", "กะดึก"),
    (4, 8, "04:00 – 08:00 น.", "เช้ามืด"),
    (8, 12, "08:00 – 12:00 น.", "กะเช้า"),
    (12, 16, "12:00 – 16:00 น.", "กะบ่ายต้น"),
    (16, 20, "16:00 – 20:00 น.", "กะเย็น"),
    (20, 24, "20:00 – 24:00 น.", "กะค่ำ"),
]

_REPORT_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_TTL_SECONDS = 300.0


# ---------------------------------------------------------------------------
# Authenticated Token Seal (PBKDF2-HMAC-SHA256 + CTR-HMAC-SHA256)
# Keyed exclusively by the server's private PAGE_ACCESS_TOKEN env var
# ---------------------------------------------------------------------------

def _derive_aead_keys(master_secret: str, salt: bytes) -> tuple[bytes, bytes]:
    dk = hashlib.pbkdf2_hmac("sha256", master_secret.encode("utf-8"), salt, 200_000, dklen=64)
    return dk[:32], dk[32:]


def _xor_keystream(data: bytes, enc_key: bytes, nonce: bytes) -> bytes:
    out = bytearray(len(data))
    offset = 0
    counter = 0
    while offset < len(data):
        block = hmac.new(enc_key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest()
        chunk = data[offset : offset + 32]
        for idx, b in enumerate(chunk):
            out[offset + idx] = b ^ block[idx]
        offset += 32
        counter += 1
    return bytes(out)


def seal_tokens_payload(tokens_map: dict[str, str], master_secret: str) -> str:
    salt = os.urandom(16)
    nonce = os.urandom(16)
    enc_key, mac_key = _derive_aead_keys(master_secret.strip(), salt)
    plaintext = json.dumps(tokens_map, ensure_ascii=False).encode("utf-8")
    ciphertext = _xor_keystream(plaintext, enc_key, nonce)
    tag = hmac.new(mac_key, salt + nonce + ciphertext, hashlib.sha256).digest()
    return ":".join(
        base64.urlsafe_b64encode(part).decode("ascii")
        for part in (salt, nonce, ciphertext, tag)
    )


def unseal_tokens_payload(sealed_blob: str, master_secret: str) -> dict[str, str]:
    if not sealed_blob or not master_secret:
        return {}
    try:
        parts = sealed_blob.strip().split(":")
        if len(parts) != 4:
            return {}
        salt, nonce, ciphertext, tag = (base64.urlsafe_b64decode(p.encode("ascii")) for p in parts)
        enc_key, mac_key = _derive_aead_keys(master_secret.strip(), salt)
        expected_tag = hmac.new(mac_key, salt + nonce + ciphertext, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected_tag):
            return {}
        plaintext = _xor_keystream(ciphertext, enc_key, nonce)
        data = json.loads(plaintext.decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning("Could not unseal page tokens payload: %s", exc)
        return {}


def _get_master_buksukjai_token() -> str:
    env_tok = os.getenv("PAGE_ACCESS_TOKEN", "").strip()
    if env_tok:
        return env_tok
    page = get_page_by_brand_id("buksukjai") or {}
    return ((page.get("channels") or {}).get("fb_page_access_token") or "").strip()


def resolve_three_page_tokens() -> dict[str, str]:
    """Resolve Read-Only Facebook Page Access Tokens for all 3 pages."""
    buksukjai_tok = _get_master_buksukjai_token()
    mrbuk_page = get_page_by_brand_id("mrbuk") or {}
    mrbuk_ch = mrbuk_page.get("channels") or {}

    mrbuk_tok = (
        os.getenv("MRBUK_PAGE_ACCESS_TOKEN", "").strip()
        or (mrbuk_ch.get("fb_page_access_token") or "").strip()
    )
    hommali_tok = (
        os.getenv("HOMMALI_PAGE_ACCESS_TOKEN", "").strip()
        or (mrbuk_ch.get("hommali_fb_page_access_token") or "").strip()
    )

    if (not mrbuk_tok or not hommali_tok) and buksukjai_tok:
        state = load_admin_report_state()
        sealed = (state.get("sealed_page_tokens") or "").strip()
        if sealed:
            unsealed = unseal_tokens_payload(sealed, buksukjai_tok)
            if not mrbuk_tok:
                mrbuk_tok = (unsealed.get("mrbuk") or "").strip()
            if not hommali_tok:
                hommali_tok = (unsealed.get("hommali") or "").strip()

    return {
        "mrbuk": mrbuk_tok,
        "hommali": hommali_tok,
        "buksukjai": buksukjai_tok,
    }


# ---------------------------------------------------------------------------
# State & Group Lock Management
# ---------------------------------------------------------------------------

def load_admin_report_state() -> dict[str, Any]:
    if ADMIN_REPORT_STATE_FILE.exists():
        try:
            data = json.loads(ADMIN_REPORT_STATE_FILE.read_text(encoding="utf-8"))
            if not data.get("target_group_id"):
                data["target_group_id"] = PLOY_ADMIN_GROUP_ID
                data["target_group_name"] = PLOY_ADMIN_GROUP_NAME
            return data
        except Exception:
            pass
    return {
        "target_group_id": PLOY_ADMIN_GROUP_ID,
        "target_group_name": PLOY_ADMIN_GROUP_NAME,
        "last_1am_report_date": "",
        "last_sent_at": "",
    }


def save_admin_report_state(state: dict[str, Any]) -> None:
    try:
        existing = load_admin_report_state()
        if existing.get("sealed_page_tokens") and not state.get("sealed_page_tokens"):
            state["sealed_page_tokens"] = existing["sealed_page_tokens"]
        ADMIN_REPORT_STATE_FILE.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("Could not save admin_report_state.json: %s", exc)


def register_pudding_admin_group(group_id: str) -> str:
    """Silently register the newly joined Admin Group ID without sending any chat reply."""
    gid = (group_id or "").strip()
    if not gid or gid == COMMENT_TEST_GROUP_ID:
        return ""

    group_name = f"กลุ่มแอดมิน ({gid[-6:]})"
    try:
        page = get_page_by_brand_id("coachbot") or {}
        token = (page.get("channels") or {}).get("line_channel_access_token", "").strip()
        if token:
            resp = httpx.get(
                f"https://api.line.me/v2/bot/group/{gid}/summary",
                headers={"Authorization": f"Bearer {token}"},
                timeout=8.0,
            )
            if resp.status_code == 200:
                group_name = resp.json().get("groupName") or group_name
    except Exception:
        pass

    state = load_admin_report_state()
    state["target_group_id"] = gid
    state["target_group_name"] = group_name
    save_admin_report_state(state)

    try:
        from . import database

        psid = database.make_session_key("coachbot", "line_group", gid)
        database.get_or_create_session(
            psid=psid,
            brand_id="coachbot",
            platform="line_group",
            external_user_id=gid,
            customer_name=group_name,
        )
        database.update_session_meta(psid=psid, customer_name=group_name, notes="ACTIVE_ADMIN_GROUP")
        database.set_bot_enabled(psid, False)
    except Exception as exc:
        logger.warning("Could not persist Pudding admin group in DB: %s", exc)

    logger.info("🍮 Silently locked Pudding (@346zyzej) target Admin Group -> %s (%s)", group_name, gid)
    return gid


def unregister_pudding_admin_group(group_id: str) -> None:
    """Remove a group when Pudding leaves or is removed."""
    gid = (group_id or "").strip()
    if not gid:
        return
    state = load_admin_report_state()
    if state.get("target_group_id") == gid:
        state["target_group_id"] = ""
        state["target_group_name"] = ""
        save_admin_report_state(state)
    try:
        from . import database

        psid = database.make_session_key("coachbot", "line_group", gid)
        database.update_session_meta(psid=psid, notes="LEFT_GROUP")
    except Exception:
        pass


def get_active_pudding_admin_group_id() -> str:
    """Resolve the active Admin Group ID from state file or persistent DB."""
    state = load_admin_report_state()
    gid = (state.get("target_group_id") or "").strip()
    if gid and gid != COMMENT_TEST_GROUP_ID:
        return gid
    try:
        from . import database

        for s in database.list_all_sessions():
            if (
                s.get("brand_id") == "coachbot"
                and s.get("platform") == "line_group"
                and s.get("external_user_id")
                and s.get("external_user_id") != COMMENT_TEST_GROUP_ID
                and s.get("notes") != "LEFT_GROUP"
            ):
                return str(s["external_user_id"]).strip()
    except Exception:
        pass
    return PLOY_ADMIN_GROUP_ID


# ---------------------------------------------------------------------------
# Live 3-Page Graph API Metrics & Real Chat QA Analyzer
# ---------------------------------------------------------------------------

def _format_thai_date(date_str: str) -> str:
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        wd = THAI_WEEKDAYS[dt.weekday()]
        m_short = THAI_MONTHS_SHORT[dt.month]
        be_year = dt.year + 543
        return f"{wd}ที่ {dt.day} {m_short} {be_year}"
    except Exception:
        return date_str


def _format_duration_thai(seconds: int) -> str:
    if seconds <= 0:
        return "-"
    if seconds < 60:
        return f"{seconds} วินาที"
    mins = seconds // 60
    rem = seconds % 60
    if rem == 0:
        return f"{mins} นาที"
    return f"{mins} นาที {rem} วิ"


def _format_duration_compact(seconds: int) -> str:
    if seconds <= 0:
        return "-"
    mins = seconds // 60
    rem = seconds % 60
    return f"{mins}:{rem:02d} นาที"


def _is_closing_ack(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        # Empty text in Graph API means attachment (payment slip, photo, sticker, voice) — NEVER treat as closing ack!
        return False
    ack_words = (
        "ขอบคุณ", "ขอบใจ", "โอเค", "ok", "okay", "ค่ะ", "คะ", "ครับ", "คับ",
        "จ้า", "จร้า", "ได้ค่ะ", "ได้ครับ", "รับทราบ", "รอรับ", "เรียบร้อย",
        "เข้าใจแล้ว", "คำนวณดูก่อน", "ดูก่อนนะ", "ไว้ก่อน", "ยังครับ", "ยังค่ะ",
    )
    if any(k in t for k in ("โอน", "ปลายทาง", "สั่ง", "เอา", "รับโปร", "กิโล", "กรัม", "ซอง", "ถุง")) and not any(
        d in t for d in ("ดูก่อน", "คำนวณดูก่อน", "ยังครับ", "ยังค่ะ", "ไว้ก่อน")
    ):
        return False
    if len(t) <= 28 and any(w in t for w in ack_words):
        return True
    if any(d in t for d in ("คำนวณดูก่อน", "ขอดูก่อน", "ตัดสินใจก่อน", "ไว้โอกาสหน้า")):
        return True
    return False


_SYSTEM_OR_AUTO_MARKERS = (
    "ตอบกลับโฆษณา",
    "คุณกำลังตอบกลับความคิดเห็น",
    "ข้อความนี้ถูกย้ายไปยัง",
    "messenger automatically created",
    "ทำเครื่องหมายคำสั่งซื้อ",
)

_AUTO_WELCOME_SNIPPETS = (
    "ยินดีต้อนรับสู่ mr.buk",
    "โปรโมชั่น ข้าวบุกสุขใจ",
    "สวัสดีค่ะ ขอบคุณที่สนใจข้าวบุกสุขใจ",
    "ใครกำลัง “อยากลดแป้ง",
    "ใครกำลัง \"อยากลดแป้ง",
    "น้องแอดมินมาให้บริการคุณลูกค้าแล้วค่า",
    "สวัสดีค่ะน้องแอดมินส่งรายละเอียดเพิ่มเติมให้นะคะ",
)


def _is_system_page_notice(text: str) -> bool:
    low = (text or "").strip().lower()
    if not low:
        return False
    return any(m in low for m in _SYSTEM_OR_AUTO_MARKERS)


def _is_auto_welcome_reply(text: str, diff_sec: float, prev_cust_text: str) -> bool:
    if _is_system_page_notice(text):
        return True
    low = (text or "").strip().lower()
    c_low = (prev_cust_text or "").strip().lower()
    if diff_sec < 5.0:
        return True
    if low and c_low and low == c_low and diff_sec <= 15.0:
        return True
    if diff_sec <= 22.0 and any(sn in low for sn in _AUTO_WELCOME_SNIPPETS):
        return True
    if diff_sec <= 15.0 and not low and c_low in ("สนใจ", "สนใจค่ะ", "สนใจครับ", "ราคา", "ขอดูโปรวันนี้", "สั่งซื้อเลย"):
        return True
    return False


def _extract_summary_bill_amount(text: str) -> int | None:
    """Detect a completed official admin order summary when #BUY tag was forgotten.
    Strictly requires order header + filled shipping address/phone + explicit net Baht price.
    """
    if not text:
        return None
    has_header = any(
        h in text
        for h in ("ขออนุญาตสรุปยอด", "สรุปยอดให้กับ", "สรุปคำสั่งซื้อ", "สรุปรายการสั่งซื้อ", "สินค้า : ข้าวบุก")
    )
    has_shipping = any(s in text for s in ("ข้อมูลจัดส่ง", "จัดส่ง :", "จัดส่ง:"))
    has_contact = bool(re.search(r"0[689][\d\s-]{7,11}|\b\d{5}\b", text))
    if not (has_header and has_shipping and has_contact):
        return None

    m_price_line = re.search(r"(?:ราคา|ยอดรวม|รวมทั้งสิ้น|ยอดชำระ)\s*[:：][^\n]+", text)
    if not m_price_line:
        return None
    nums = [int(n.replace(",", "")) for n in re.findall(r"\d[\d,]*", m_price_line.group(0))]
    if not nums:
        return None
    amt = nums[-1]
    if 60 <= amt <= 30000:
        return amt
    return None


def _is_customer_question(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    q_markers = (
        "?", "ไหม", "มั้ย", "มัย", "หรือเปล่า", "รึเปล่า", "หรือไม่", "หรือต้อง",
        "หรือว่า", "เท่าไหร่", "เท่าไร", "กี่บาท", "กี่กรัม", "กี่ถุง", "กี่ซอง",
        "ยังไง", "อย่างไร", "แบบไหน", "ส่งฟรีไหม", "มีปลายทาง",
    )
    return any(q in t for q in q_markers)


def _fetch_single_page_report(spec: dict[str, str], token: str, target_date: str) -> dict[str, Any]:
    page_id = spec["page_id"]
    buckets = [
        {"label": label, "shift": shift, "orders": 0, "total_thb": 0, "items": [], "chats": 0}
        for _h0, _h1, label, shift in TIME_BUCKET_SPECS
    ]
    result: dict[str, Any] = {
        "key": spec["key"],
        "page_id": page_id,
        "title": spec["title"],
        "short_name": spec["short_name"],
        "css_class": spec["css_class"],
        "token_connected": bool(token),
        "chats": 0,
        "followup_only_chats": 0,
        "orders": 0,
        "total_thb": 0,
        "conv_rate": 0.0,
        "aov": 0,
        "rev_per_chat": 0,
        "avg_sec": 0,
        "avg_label": "-",
        "avg_compact": "-",
        "overdue_3h": 0,
        "overdue_list": [],
        "small_orders_count": 0,
        "small_no_upsell": [],
        "typos": [],
        "missing_buy_tags": [],
        "unclosed_address": [],
        "missed_intent": [],
        "best_orders": [],
        "buckets": buckets,
    }
    if not token:
        return result

    now_bkk = datetime.now(BKK_TZ)
    is_today = target_date == now_bkk.strftime("%Y-%m-%d")
    ref_end_dt = now_bkk if is_today else datetime.strptime(target_date + " 23:59:59", "%Y-%m-%d %H:%M:%S").replace(tzinfo=BKK_TZ)

    convs: list[dict[str, Any]] = []
    url: str | None = "https://graph.facebook.com/v21.0/me/conversations"
    params: dict[str, Any] | None = {
        "access_token": token,
        "limit": 50,
        "fields": "participants,updated_time,messages.limit(50){id,message,from,created_time}",
    }
    try:
        for _ in range(12):
            if not url:
                break
            resp = httpx.get(url, params=params, timeout=25.0).json()
            batch = resp.get("data") or []
            if not batch:
                break
            convs.extend(batch)
            last_ut_raw = batch[-1].get("updated_time", "")
            if last_ut_raw:
                last_ut_bkk = datetime.strptime(last_ut_raw, "%Y-%m-%dT%H:%M:%S%z").astimezone(BKK_TZ)
                if last_ut_bkk.strftime("%Y-%m-%d") < target_date:
                    break
            url = (resp.get("paging") or {}).get("next")
            params = None
    except Exception as exc:
        logger.warning("Graph API conversation fetch warning on %s: %s", spec["key"], exc)

    resp_times: list[float] = []
    typo_patterns = [
        ("ปบายทาง", "ปลายทาง"),
        ("สะดวกกชำระ", "สะดวกชำระ"),
        ("ข้าวบุกสุกใจ", "ข้าวบุกสุขใจ"),
        ("คุ้มๆ", "คุ้มๆ"),
        ("ลดแป้งลงครึ่งหนึ่ง", "ระบุ '23 kcal ต่อข้าวสุก 25 กรัม' แทน"),
    ]

    for c in convs:
        participants = (c.get("participants") or {}).get("data") or []
        cname = next(
            (p.get("name", "ลูกค้า") for p in participants if str(p.get("id", "")) != page_id),
            "ลูกค้า",
        )
        raw_msgs = list(reversed((c.get("messages") or {}).get("data") or []))

        # If a busy conversation hit the 50-message cap and its oldest message is still on/after target_date,
        # fetch up to 100 messages for this specific conversation so morning #BUY tags are never truncated.
        if len(raw_msgs) >= 50 and c.get("id"):
            try:
                oldest_ct = raw_msgs[0].get("created_time", "")
                if oldest_ct:
                    oldest_bkk = datetime.strptime(oldest_ct, "%Y-%m-%dT%H:%M:%S%z").astimezone(BKK_TZ)
                    if oldest_bkk.strftime("%Y-%m-%d") >= target_date:
                        more_resp = httpx.get(
                            f"https://graph.facebook.com/v21.0/{c['id']}/messages",
                            params={"access_token": token, "limit": 100, "fields": "id,message,from,created_time"},
                            timeout=15.0,
                        ).json()
                        if more_resp.get("data"):
                            raw_msgs = list(reversed(more_resp["data"]))
            except Exception:
                pass

        day_msgs: list[tuple[datetime, str, str]] = []
        for m in raw_msgs:
            ct = m.get("created_time", "")
            if not ct:
                continue
            try:
                dt = datetime.strptime(ct, "%Y-%m-%dT%H:%M:%S%z").astimezone(BKK_TZ)
            except Exception:
                continue
            if dt.strftime("%Y-%m-%d") == target_date:
                day_msgs.append((dt, str((m.get("from") or {}).get("id", "")), m.get("message") or ""))

        if not day_msgs:
            continue

        # Ignore Facebook auto-spam filtered threads
        if any('ข้อความนี้ถูกย้ายไปยัง "สแปม"' in x[2] for x in day_msgs if x[1] == page_id):
            continue

        # 1. Extract closed orders on target_date:
        #    - Primary: #BUY<amount> (supports commas like #BUY1,339)
        #    - Amendment rule: if the page sends an updated #BUY within 2 hours (7,200s) in the same chat
        #      (e.g. changing COD 319 -> Transfer 289, or fixing typo #BUY529 -> #BUY520), replace the prior entry!
        #    - Fallback: completed official order summary with full shipping info where admin forgot #BUY.
        conv_buys: list[tuple[datetime, int, bool]] = []  # (dt, amount, is_missing_buy_tag)
        for dt_m, sid_m, txt_m in day_msgs:
            if sid_m != page_id or not txt_m:
                continue
            for m_b in re.finditer(r"#\s*BUY\s*([\d,]+)", txt_m, re.I):
                amt = int(m_b.group(1).replace(",", ""))
                if not (30 <= amt <= 50000):
                    continue
                if conv_buys and abs((dt_m - conv_buys[-1][0]).total_seconds()) <= 7200:
                    # Amended bill or duplicate #BUY in the same customer session -> keep latest net amount
                    conv_buys[-1] = (dt_m, amt, False)
                else:
                    conv_buys.append((dt_m, amt, False))

        if not conv_buys:
            for dt_m, sid_m, txt_m in day_msgs:
                if sid_m != page_id or not txt_m:
                    continue
                fallback_amt = _extract_summary_bill_amount(txt_m)
                if fallback_amt is not None:
                    if conv_buys and abs((dt_m - conv_buys[-1][0]).total_seconds()) <= 7200:
                        conv_buys[-1] = (dt_m, fallback_amt, True)
                    else:
                        conv_buys.append((dt_m, fallback_amt, True))

        has_cust_msg = any(x[1] != page_id for x in day_msgs)
        if not has_cust_msg and not conv_buys:
            # Page-only outbound follow-up / morning GIF to silent old chat — do NOT inflate active chats!
            result["followup_only_chats"] += 1
            continue

        result["chats"] += 1
        first_cust_dt = next((x[0] for x in day_msgs if x[1] != page_id), day_msgs[0][0])
        b_idx_chat = min(first_cust_dt.hour // 4, 5)
        buckets[b_idx_chat]["chats"] += 1

        # Commit deduplicated/verified orders to page totals & time buckets
        for dt_b, amt, missing_tag in conv_buys:
            result["orders"] += 1
            result["total_thb"] += amt
            b_idx = min(dt_b.hour // 4, 5)
            buckets[b_idx]["orders"] += 1
            buckets[b_idx]["total_thb"] += amt
            buckets[b_idx]["items"].append((dt_b.strftime("%H:%M"), amt, cname))

            if missing_tag:
                result["missing_buy_tags"].append({
                    "time": dt_b.strftime("%H:%M"),
                    "customer": cname,
                    "amount": amt,
                })

            cust_before = [x[0] for x in day_msgs if x[1] != page_id and x[0] <= dt_b]
            close_mins = int(max(1, round((dt_b - cust_before[0]).total_seconds() / 60))) if cust_before else 5
            result["best_orders"].append({
                "time": dt_b.strftime("%H:%M"),
                "customer": cname,
                "amount": amt,
                "close_mins": close_mins,
            })

            if amt <= 350:
                result["small_orders_count"] += 1
                page_texts_joined = " ".join(x[2] for x in day_msgs if x[1] == page_id)
                if not any(k in page_texts_joined for k in ("1 กิโล", "1กิโล", "1 กก", "1กก", "ส่งฟรี")):
                    result["small_no_upsell"].append({
                        "time": dt_b.strftime("%H:%M"),
                        "customer": cname,
                        "amount": amt,
                    })

        # 2. Turn-based human daytime response time (07:00 - 22:59 BKK, excluding auto-welcomes & system notices)
        idx_m = 0
        n_msgs = len(day_msgs)
        while idx_m < n_msgs:
            dt_c, sid_c, txt_c = day_msgs[idx_m]
            if sid_c != page_id:
                # Advance through consecutive customer bubbles in the same turn
                turn_start_dt = dt_c
                first_cust_txt = txt_c
                last_cust_txt = txt_c
                j = idx_m + 1
                while j < n_msgs and day_msgs[j][1] != page_id:
                    if day_msgs[j][2].strip():
                        last_cust_txt = day_msgs[j][2]
                    j += 1
                # Find first genuine human admin reply after this customer turn
                k = j
                while k < n_msgs:
                    if day_msgs[k][1] == page_id:
                        diff_from_start = (day_msgs[k][0] - turn_start_dt).total_seconds()
                        if not _is_auto_welcome_reply(day_msgs[k][2], diff_from_start, first_cust_txt):
                            if 7 <= turn_start_dt.hour < 23 and not _is_closing_ack(last_cust_txt):
                                if 5 <= diff_from_start <= 28800:
                                    resp_times.append(diff_from_start)
                            break
                    k += 1
                idx_m = j
            else:
                idx_m += 1

        # 3. Saved-reply typos & compliance check
        seen_typo_words: set[str] = set()
        for dt_m, sid_m, txt_m in day_msgs:
            if sid_m != page_id or not txt_m:
                continue
            for bad_word, fix_word in typo_patterns:
                if bad_word in txt_m and bad_word not in seen_typo_words:
                    seen_typo_words.add(bad_word)
                    result["typos"].append({
                        "time": dt_m.strftime("%H:%M"),
                        "customer": cname,
                        "bad": bad_word,
                        "fix": fix_word,
                    })

        # 4. Overdue unanswered customer chats (> 3h) & high-value unclosed leads
        if not conv_buys:
            last_cust_idx = max((idx for idx, x in enumerate(day_msgs) if x[1] != page_id), default=-1)
            if last_cust_idx != -1:
                last_c_dt, _last_c_sid, last_c_txt = day_msgs[last_cust_idx]
                after_page_msgs = [x for x in day_msgs[last_cust_idx + 1 :] if x[1] == page_id]
                has_human_reply = any(
                    not _is_auto_welcome_reply(px[2], (px[0] - last_c_dt).total_seconds(), last_c_txt)
                    for px in after_page_msgs
                )
                wait_sec = (ref_end_dt - last_c_dt).total_seconds()
                if not has_human_reply and wait_sec > 10800 and not _is_closing_ack(last_c_txt):
                    result["overdue_3h"] += 1
                    result["overdue_list"].append({
                        "time": last_c_dt.strftime("%H:%M"),
                        "customer": cname,
                        "text": (last_c_txt or "[ส่งรูปภาพ/สลิป/สติกเกอร์]").strip()[:60],
                        "wait_hours": round(wait_sec / 3600, 1),
                    })

            # 5A. Customer already sent shipping address / 10-digit phone number, but order not closed with #BUY yet!
            cust_msgs_nonempty = [(dt_m, txt_m.strip()) for dt_m, sid_m, txt_m in day_msgs if sid_m != page_id and txt_m.strip()]
            cust_joined_all = " ".join(t for _dt, t in cust_msgs_nonempty)
            cust_digits = re.sub(r"[-\s]", "", cust_joined_all)
            has_phone_or_zip = bool(re.search(r"0[689]\d{8}", cust_digits)) or (
                bool(re.search(r"\b[1-9]\d{4}\b", cust_joined_all))
                and any(a in cust_joined_all for a in ("ต.", "ตำบล", "อ.", "อำเภอ", "แขวง", "เขต", "จ.", "จังหวัด", "หมู่", "ถ."))
            )
            declined_later = any(
                d in (cust_msgs_nonempty[-1][1] if cust_msgs_nonempty else "")
                for d in ("ยังครับ", "ยังค่ะ", "ยกเลิก", "ไม่รับ", "เยอะไป", "ดูก่อน")
            )
            if has_phone_or_zip and not declined_later:
                addr_dt = next(
                    (
                        dt_m
                        for dt_m, t in cust_msgs_nonempty
                        if re.search(r"0[689][\d\s-]{7,11}|\b[1-9]\d{4}\b", t)
                    ),
                    cust_msgs_nonempty[-1][0],
                )
                page_after_addr = " ".join(
                    txt_m for dt_m, sid_m, txt_m in day_msgs if sid_m == page_id and dt_m >= addr_dt and txt_m
                )
                if "โอนชำระ" in page_after_addr and "ปลายทาง" in page_after_addr:
                    note = "ลูกค้าส่งชื่อ-ที่อยู่สั่งซื้อแล้ว แอดมินรวมยอดให้เลือกโอน/ปลายทางแล้ว แนะนำทักตามปิดบิลช่วงเช้าค่ะ"
                else:
                    note = "ลูกค้าแจ้งชื่อ-ที่อยู่จัดส่งแล้ว แต่ยังไม่ได้สรุปยอดและติดรหัส #BUY ปิดออเดอร์ค่ะ"
                result["unclosed_address"].append({
                    "time": addr_dt.strftime("%H:%M"),
                    "customer": cname,
                    "cust_text": cust_joined_all[:75].replace("\n", " "),
                    "reason": note,
                })
            elif not declined_later:
                # 5B. Genuine explicit purchase statement (NOT a question!) where admin missed bank account or address prompt
                page_texts = [txt_m.strip() for _dt_m, sid_m, txt_m in day_msgs if sid_m == page_id and txt_m.strip()]
                joined_page = " ".join(page_texts)
                sent_bank = any(b in joined_page for b in ("กสิกร", "ไทยพาณิชย์", "เลขที่บัญชี", "เลขบัญชี", "304-4", "989-2", "3044075455", "9892136243"))
                asked_addr = any(a in joined_page for a in ("ชื่อ", "ที่อยู่", "เบอร์โทร", "ข้อมูลจัดส่ง"))

                for dt_c, c_txt in cust_msgs_nonempty:
                    if c_txt in ("สั่งซื้อเลย", "สนใจ", "สนใจค่ะ", "สนใจครับ", "ขอดูโปรวันนี้", "ราคา"):
                        continue
                    if _is_customer_question(c_txt) or _is_closing_ack(c_txt):
                        continue
                    c_norm = c_txt.strip()
                    chose_transfer = bool(
                        re.match(r"^(?:ขอ)?โอน(?:เงิน|ชำระ|เลย|จ้า|ค่ะ|คะ|ครับ|คับ)?$", c_norm)
                        or any(p in c_norm for p in ("โอนค่ะ", "โอนครับ", "โอนชำระค่ะ", "แบบโอนค่ะ", "ขอเลขบัญชี"))
                    )
                    explicit_order = any(
                        p in c_norm
                        for p in ("สั่งค่ะ", "สั่งครับ", "สั่ง ", "เอา ", "รับโปร", "รับ 1", "รับ 2", "รับ 3", "เอา 1", "เอา 2")
                    )
                    if (chose_transfer or explicit_order) and (ref_end_dt - dt_c).total_seconds() > 2700:
                        if chose_transfer and not sent_bank:
                            result["missed_intent"].append({
                                "time": dt_c.strftime("%H:%M"),
                                "customer": cname,
                                "cust_text": c_norm[:70].replace("\n", " "),
                                "reason": "ลูกค้าแจ้งเลือกโอนเงินแล้ว แต่ยังไม่ได้ส่งเลขบัญชีเพื่อล็อกออเดอร์ทันทีค่ะ",
                                "priority": 1,
                            })
                            break
                        if explicit_order and not asked_addr and not sent_bank:
                            result["missed_intent"].append({
                                "time": dt_c.strftime("%H:%M"),
                                "customer": cname,
                                "cust_text": c_norm[:70].replace("\n", " "),
                                "reason": "ลูกค้าพิมพ์สั่งซื้อแล้ว แต่ยังไม่ได้ส่งเลขบัญชีหรือขอชื่อ-ที่อยู่-เบอร์โทรค่ะ",
                                "priority": 1,
                            })
                            break

    if result["chats"] > 0:
        result["conv_rate"] = round((result["orders"] / result["chats"]) * 100, 1)
        result["rev_per_chat"] = int(round(result["total_thb"] / result["chats"]))
    if result["orders"] > 0:
        result["aov"] = int(round(result["total_thb"] / result["orders"]))
    if resp_times:
        avg_s = int(round(sum(resp_times) / len(resp_times)))
        result["avg_sec"] = avg_s
        result["avg_label"] = _format_duration_thai(avg_s)
        result["avg_compact"] = _format_duration_compact(avg_s)

    return result


def _synthesize_praise_and_cases(pages_data: list[dict[str, Any]]) -> tuple[str, list[dict[str, str]]]:
    """Build concise praise summary + top 4 verified real chat QA cases from live data."""
    # 1. Praise line
    fast_pages = [p for p in pages_data if p["avg_sec"] > 0]
    fast_pages.sort(key=lambda x: x["avg_sec"])
    all_best_orders = []
    for p in pages_data:
        for bo in p["best_orders"]:
            all_best_orders.append((bo["amount"], -bo["close_mins"], p["short_name"], bo))
    all_best_orders.sort(key=lambda x: (x[0], x[1]), reverse=True)

    praise_parts = []
    if fast_pages:
        fp = fast_pages[0]
        praise_parts.append(f"{fp['short_name']} ตอบไวเฉลี่ย {fp['avg_label']}")
    if all_best_orders:
        _amt, _neg_m, p_short, bo = all_best_orders[0]
        praise_parts.append(
            f"{p_short} ปิดบิลใหญ่ #BUY{bo['amount']:,} (คุณ {bo['customer']}) ได้ครบเรียบร้อยค่ะ 👏💚"
        )
    praise_text = " และ ".join(praise_parts) if praise_parts else "ทีมแอดมินดูแลตอบแชทและปิดออเดอร์ต่อเนื่องครบทั้ง 3 เพจค่ะ 👏💚"

    # 2. Actionable cases (up to 4, strictly verified)
    cases: list[dict[str, str]] = []

    # Priority 1: Closed summary bill where admin forgot to type #BUY<amount>
    for p in pages_data:
        for mb in p.get("missing_buy_tags", []):
            cases.append({
                "line_header": f"{p['short_name']} ({mb['time']} น. · ลืมติด #BUY)",
                "customer": f"คุณ {mb['customer']}",
                "line_bullet": f"ส่งใบสรุปยอด {mb['amount']:,}฿ แล้วแต่ลืมพิมพ์ #BUY{mb['amount']} กำกับ (ระบบนับยอดรวมให้แล้ว ฝากพิมพ์ #BUY ทุกบิลนะคะ)",
                "html_title": f"{p['title']} ({mb['time']} น.) · ลูกค้า คุณ {mb['customer']} — สรุปบิล {mb['amount']:,}฿ แล้วแต่ลืมพิมพ์ #BUY{mb['amount']}",
                "html_detail": f"แอดมินส่งใบสรุปยอดและที่อยู่จัดส่งครบถ้วนแล้ว ({mb['amount']:,}฿) แต่ไม่มีข้อความ #BUY{mb['amount']} ปิดท้าย",
                "html_fix": f"ฝากพิมพ์ #BUY{mb['amount']} แยก 1 บับเบิลทุกครั้งหลังสรุปยอด เพื่อให้ระบบนับยอดแอดและติดแท็กอัตโนมัติไม่ตกหล่นค่ะ",
            })

    # Priority 2: Customer already sent shipping address / phone number, waiting to close #BUY
    for p in pages_data:
        for ua in p.get("unclosed_address", [])[:2]:
            if len(cases) >= 3:
                break
            cases.append({
                "line_header": f"{p['short_name']} ({ua['time']} น. · รอสรุปปิดบิล)",
                "customer": f"คุณ {ua['customer']}",
                "line_bullet": f"{ua['reason']}",
                "html_title": f"{p['title']} ({ua['time']} น.) · ลูกค้า คุณ {ua['customer']} — {ua['reason']}",
                "html_detail": f"ข้อความลูกค้า: “{ua['cust_text']}”",
                "html_fix": "ตรวจสอบแชทที่ลูกค้าส่งชื่อ-ที่อยู่ไว้แล้ว ทักยืนยันยอด/วิธีชำระสั้นๆ และสรุปบิลพร้อมติด #BUY ทันทีค่ะ",
            })

    # Priority 3: Explicit purchase intent where admin missed sending bank / asking address
    all_missed = []
    for p in pages_data:
        for m in p["missed_intent"]:
            all_missed.append((m["priority"], p["short_name"], p["title"], m))
    all_missed.sort(key=lambda x: x[0])
    for _prio, p_short, p_title, m in all_missed[:2]:
        if len(cases) >= 3:
            break
        cases.append({
            "line_header": f"{p_short} ({m['time']} น.)",
            "customer": f"คุณ {m['customer']}",
            "line_bullet": f"ลูกค้าพิมพ์ \"{m['cust_text']}\" — {m['reason']}",
            "html_title": f"{p_title} ({m['time']} น.) · ลูกค้า คุณ {m['customer']} — {m['reason']}",
            "html_detail": f"ข้อความลูกค้า: “{m['cust_text']}”",
            "html_fix": "เมื่อลูกค้ายืนยันสั่งซื้อหรือเลือกโอนแล้ว ให้ส่งเลขบัญชีและขอชื่อ-ที่อยู่-เบอร์โทรทันทีเพื่อล็อกออเดอร์ค่ะ",
        })

    # Priority 4: Saved-reply typos & compliance words
    typo_groups: list[str] = []
    typo_customers: list[str] = []
    typo_pages: list[str] = []
    typo_times: list[str] = []
    for p in pages_data:
        for t in p["typos"]:
            if p["short_name"] not in typo_pages:
                typo_pages.append(p["short_name"])
            cust_label = f"คุณ {t['customer']}"
            if cust_label not in typo_customers:
                typo_customers.append(cust_label)
            if f"'{t['bad']}'" not in typo_groups:
                typo_groups.append(f"'{t['bad']}'")
            typo_times.append(t["time"])
    if typo_groups and len(cases) < 4:
        t_range = f"{min(typo_times)} – {max(typo_times)} น." if len(typo_times) > 1 else f"{typo_times[0]} น."
        cases.append({
            "line_header": f"{' & '.join(typo_pages)} ({t_range})",
            "customer": " / ".join(typo_customers[:2]),
            "line_bullet": f"พบคำในข้อความสำเร็จรูป {', '.join(typo_groups[:4])} ฝากเข้าไปแก้คำผิดและระบุ '23 kcal ต่อข้าวสุก 25 กรัม' นะคะ",
            "html_title": f"{' & '.join(typo_pages)} ({t_range}) · ลูกค้า {' / '.join(typo_customers[:2])} — คำพิมพ์ผิดในข้อความสำเร็จรูป (Saved Replies)",
            "html_detail": f"พบคำว่า {', '.join(typo_groups[:4])} ในข้อความที่ส่งหาลูกค้า",
            "html_fix": "เข้าไปแก้ไขข้อความตอบกลับที่บันทึกไว้ (Saved Replies) ให้ถูกต้องทั้งหมด และระบุหน่วยโภชนาการเป็น '23 kcal ต่อข้าวสุก 25 กรัม' เสมอค่ะ",
        })

    # Priority 5: Overdue unanswered chats > 3h
    overdue_pages = [p for p in pages_data if p["overdue_3h"] > 0]
    for p in overdue_pages:
        if len(cases) >= 4:
            break
        sample_names = ", ".join(f"คุณ {x['customer']} ({x['time']})" for x in p["overdue_list"][:2])
        cases.append({
            "line_header": f"{p['short_name']} (แชทรอตอบ > 3 ชม.)",
            "customer": sample_names or f"ค้าง {p['overdue_3h']} แชท",
            "line_bullet": f"มีแชทลูกค้ารอตอบเกิน 3 ชม. อยู่ {p['overdue_3h']} แชท ฝากกดตัวกรอง 'ยังไม่ได้อ่าน / การตอบกลับโฆษณา' เคลียร์ให้ครบ 0 แชทนะคะ",
            "html_title": f"{p['title']} · แชทลูกค้ารอตอบเกิน 3 ชั่วโมง {p['overdue_3h']} แชท",
            "html_detail": f"ตัวอย่างแชทที่รอตอบ: {sample_names}",
            "html_fix": "กดตัวกรอง 'ยังไม่ได้อ่าน' และ 'การตอบกลับโฆษณา' ใน Meta Business Suite / Pancake ไล่ตอบให้ครบ 0 แชทก่อนเปลี่ยนกะทุกครั้งค่ะ",
        })

    # Priority 6: Small orders upsell opportunity (if room in top 4)
    if len(cases) < 4:
        for p in pages_data:
            if p["small_orders_count"] >= 2:
                sample_sm = p["small_no_upsell"][0] if p["small_no_upsell"] else None
                cust_ref = f"คุณ {sample_sm['customer']} (#BUY{sample_sm['amount']})" if sample_sm else f"บิลเล็ก {p['small_orders_count']} บิล"
                cases.append({
                    "line_header": f"{p['short_name']} (โอกาสอัปเซลล์เพิ่มยอดต่อบิล)",
                    "customer": cust_ref,
                    "line_bullet": f"มีบิลขนาดเริ่มต้น {p['small_orders_count']} บิล (เฉลี่ยทั้งเพจ {p['aov']:,}฿) แนะนำเชียร์ขยับเป็นโปร 1 กก. โอนส่งฟรี ควบคู่ทุกครั้งค่ะ",
                    "html_title": f"{p['title']} · มีบิลขนาดเริ่มต้น {p['small_orders_count']} บิล (โอกาสขยับยอดเฉลี่ยสู่เป้า 550฿+)",
                    "html_detail": f"ยอดเฉลี่ยต่อออเดอร์อยู่ที่ {p['aov']:,}฿ ({cust_ref})",
                    "html_fix": "เมื่อลูกค้าถาม 500g หรือซองเล็ก ให้เทียบความคุ้มค่า 'ถุงใหญ่ 1 กิโล โอนส่งฟรี ทานได้ 16–20 มื้อ' สั้นๆ ให้ลูกค้าเลือกก่อนสรุปบิลค่ะ",
                })
                break

    return praise_text, cases[:4]


def get_three_pages_live_report(target_date: str | None = None, force_refresh: bool = False) -> dict[str, Any]:
    """Fetch and compute full 3-page report for `target_date` (defaults to yesterday at night/morning, or today)."""
    now_bkk = datetime.now(BKK_TZ)
    if not target_date:
        # Between 00:00 and 11:59 BKK, default to yesterday's completed 24h report
        if now_bkk.hour < 12:
            target_date = (now_bkk - timedelta(days=1)).strftime("%Y-%m-%d")
        else:
            target_date = now_bkk.strftime("%Y-%m-%d")

    cached = _REPORT_CACHE.get(target_date)
    if cached and not force_refresh and (time.time() - cached[0]) < _CACHE_TTL_SECONDS:
        return cached[1]

    tokens = resolve_three_page_tokens()
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [
            pool.submit(_fetch_single_page_report, spec, tokens.get(spec["key"], ""), target_date)
            for spec in THREE_PAGES_SPECS
        ]
        pages_data = [f.result() for f in futures]

    total_chats = sum(p["chats"] for p in pages_data)
    total_orders = sum(p["orders"] for p in pages_data)
    total_thb = sum(p["total_thb"] for p in pages_data)
    is_today = target_date == now_bkk.strftime("%Y-%m-%d")
    period_label = (
        f"ข้อมูลสด 00:00 – {now_bkk.strftime('%H:%M')} น."
        if is_today
        else "รอบปิดวัน 24 ชม. · 00:00 – 23:59 น."
    )
    praise_text, cases = _synthesize_praise_and_cases(pages_data)

    report = {
        "target_date": target_date,
        "thai_date": _format_thai_date(target_date),
        "is_today": is_today,
        "period_label": period_label,
        "generated_at": now_bkk.strftime("%H:%M น."),
        "total_chats": total_chats,
        "total_orders": total_orders,
        "total_thb": total_thb,
        "pages": pages_data,
        "praise_text": praise_text,
        "cases": cases,
    }
    _REPORT_CACHE[target_date] = (time.time(), report)
    return report


def fetch_live_24h_buksukjai_metrics(target_date: str) -> dict[str, Any]:
    """Backward-compatible helper returning live stats for ข้าวบุก สุขใจ."""
    tokens = resolve_three_page_tokens()
    res = _fetch_single_page_report(THREE_PAGES_SPECS[2], tokens.get("buksukjai", ""), target_date)
    return {
        "chats": res["chats"],
        "orders": res["orders"],
        "total_thb": res["total_thb"],
        "avg_sec": res["avg_sec"],
    }


# ---------------------------------------------------------------------------
# 01:00 AM Daily Scheduler & LINE Push Formatter
# ---------------------------------------------------------------------------

def should_run_daily_1am_admin_report() -> tuple[bool, str]:
    """Check if it is 01:00–01:59 AM Bangkok time and yesterday's 24h report has not been sent yet."""
    now_bkk = datetime.now(BKK_TZ)
    target_date = (now_bkk - timedelta(days=1)).strftime("%Y-%m-%d")
    if now_bkk.hour != 1:
        return False, target_date
    state = load_admin_report_state()
    if state.get("last_1am_report_date") == target_date:
        return False, target_date
    if not get_active_pudding_admin_group_id():
        return False, target_date
    return True, target_date


def run_and_send_daily_1am_admin_report(target_date: str | None = None) -> dict[str, Any]:
    """Run and send the 01:00 AM daily 24-hour Admin Report strictly once per night to the locked Admin Group."""
    now_bkk = datetime.now(BKK_TZ)
    t_date = target_date or (now_bkk - timedelta(days=1)).strftime("%Y-%m-%d")
    target_gid = get_active_pudding_admin_group_id()
    if not target_gid:
        return {"status": "skipped", "reason": "No active Admin Group registered yet"}

    res = send_pudding_report_to_line_group(group_id=target_gid, target_date=t_date, force_refresh=True)
    if res.get("status") == "ok":
        state = load_admin_report_state()
        state["last_1am_report_date"] = t_date
        state["last_sent_at"] = now_bkk.isoformat()
        save_admin_report_state(state)
    return res


def format_pudding_line_summary(
    public_base_url: str = "",
    target_date: str | None = None,
    force_refresh: bool = False,
) -> str:
    """Concise, easy-to-scan LINE summary sent by พุดดิ้ง🍮 (@346zyzej) with live 3-page metrics."""
    base = (
        public_base_url
        or os.getenv("RENDER_EXTERNAL_URL")
        or os.getenv("PUBLIC_BASE_URL")
        or "https://buksukjai-omnichannel-twht.onrender.com"
    ).rstrip("/")

    rep = get_three_pages_live_report(target_date=target_date, force_refresh=force_refresh)
    report_url = f"{base}/admin-report?date={rep['target_date']}"

    lines = [
        "🍮 รายงานสำหรับทีมแอดมิน · ข้าวบุก 3 เพจ",
        f"📅 {rep['thai_date']} ({rep['period_label']})",
        f"💰 รวม 3 เพจ: {rep['total_orders']} ออเดอร์ ({rep['total_thb']:,}฿) จาก {rep['total_chats']} แชท",
        "━━━━━━━━━━━━━━",
        "📊 1. สรุปผลงานรายเพจ",
        "━━━━━━━━━━━━━━",
    ]

    for idx, p in enumerate(rep["pages"]):
        overdue_line = (
            f"• ⚠️ มีแชทรอตอบเกิน 3 ชม. อยู่ {p['overdue_3h']} แชท"
            if p["overdue_3h"] > 0
            else "• ✅ แชทค้างเกิน 3 ชม. 0 แชท"
        )
        lines.extend([
            f"🔵 {p['title']}",
            f"• 💬 แชทแอคทีฟ {p['chats']} แชท",
            f"• 🚛 ปิดได้ {p['orders']} ออเดอร์ ({p['conv_rate']}%)",
            f"• 💸 ยอดขายรวม {p['total_thb']:,}฿",
            f"• 💰 เฉลี่ย {p['aov']:,}฿/ออเดอร์",
            f"• ⚡ เวลาตอบเฉลี่ย (ไม่รวมดึก) {p['avg_label']}",
            overdue_line,
            "━━━━━━━━━━━━━━",
        ])

    lines.extend([
        "🌟 ชมเชยวันนี้:",
        f"• {rep['praise_text']}",
        "━━━━━━━━━━━━━━",
        "💡 2. เคสตัวอย่างวันนี้",
        "━━━━━━━━━━━━━━",
    ])

    if rep["cases"]:
        for c_idx, case in enumerate(rep["cases"], start=1):
            lines.append(f"{c_idx}) {case['line_header']}")
            lines.append(f"• {case['customer']}")
            lines.append(f"- {case['line_bullet']}")
            if c_idx < len(rep["cases"]):
                lines.append("")
    else:
        lines.append("• วันนี้ยังไม่พบคำพิมพ์ผิดหรือแชทค้างเกิน 3 ชม. รักษามาตรฐานดีมากค่ะ 💚")

    lines.extend([
        "━━━━━━━━━━━━━━",
        "🌐 กดดูรายละเอียดรายช่วงเวลาและสคริปต์พร้อมใช้ 👇",
        report_url,
    ])
    return "\n".join(lines)


def send_pudding_report_to_line_group(
    group_id: str | None = None,
    public_base_url: str = "",
    target_date: str | None = None,
    force_refresh: bool = True,
) -> dict[str, Any]:
    """Push the concise daily admin report via พุดดิ้ง🍮 (`coachbot` @346zyzej) to the target LINE group."""
    state = load_admin_report_state()
    target_gid = (group_id or get_active_pudding_admin_group_id()).strip()
    if not target_gid:
        return {"status": "error", "message": "No active target Admin Group registered yet"}

    page = get_page_by_brand_id("coachbot") or {}
    token = (page.get("channels") or {}).get("line_channel_access_token", "").strip()
    if not token:
        return {"status": "error", "message": "Missing coachbot (@346zyzej) LINE access token"}

    msg_text = format_pudding_line_summary(
        public_base_url=public_base_url,
        target_date=target_date,
        force_refresh=force_refresh,
    )
    resp = httpx.post(
        "https://api.line.me/v2/bot/message/push",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={
            "to": target_gid,
            "messages": [{"type": "text", "text": msg_text}],
        },
        timeout=20.0,
    )
    now_bkk = datetime.now(BKK_TZ)
    if resp.status_code == 200:
        state["last_sent_at"] = now_bkk.isoformat()
        save_admin_report_state(state)
        return {
            "status": "ok",
            "group_id": target_gid,
            "sent_at": state["last_sent_at"],
            "message_preview": msg_text,
        }
    return {
        "status": "error",
        "http_status": resp.status_code,
        "response": resp.text,
        "group_id": target_gid,
    }


# ---------------------------------------------------------------------------
# Dynamic Standalone HTML Dashboard (`/admin-report`)
# ---------------------------------------------------------------------------

def render_admin_report_html(target_date: str | None = None, force_refresh: bool = False) -> str:
    """Render the full live HTML dashboard for all 3 pages."""
    rep = get_three_pages_live_report(target_date=target_date, force_refresh=force_refresh)
    now_bkk = datetime.now(BKK_TZ)
    today_str = now_bkk.strftime("%Y-%m-%d")
    yesterday_str = (now_bkk - timedelta(days=1)).strftime("%Y-%m-%d")

    cards_html_parts = []
    for p in rep["pages"]:
        overdue_html = (
            f'<span class="bad">{p["overdue_3h"]} แชท (รอตอบ &gt; 3 ชม.)</span>'
            if p["overdue_3h"] > 0
            else '<span class="good">0 แชท (เคลียร์ครบ)</span>'
        )
        if p["overdue_3h"] > 0:
            badge_html = f'<div class="badge warn">มีแชทค้าง &gt; 3 ชม. {p["overdue_3h"]} แชท · ฝากเคลียร์ก่อนเปลี่ยนกะ</div>'
        elif p["aov"] > 0 and p["aov"] < 500:
            badge_html = f'<div class="badge warn">ยอดเฉลี่ย {p["aov"]:,}฿ · ดันโปร 1 กก. โอนส่งฟรีเพิ่ม</div>'
        else:
            badge_html = '<div class="badge ok">ภาพรวมและเวลาตอบอยู่ในเกณฑ์ดีมากค่ะ</div>'

        cards_html_parts.append(f"""
      <div class="page-card {p['css_class']}">
        <div class="page-title">{html.escape(p['title'])}</div>
        <div class="big-rate">{p['conv_rate']}%</div>
        <div class="rate-caption">% ปิดเฉพาะแชทที่คุยในวัน ({p['orders']} ออเดอร์ ÷ {p['chats']} แชท)</div>
        <div class="stat-row">
          <span class="stat-label">แชทแอคทีฟ / ออเดอร์</span>
          <span class="stat-val">{p['chats']} แชท / {p['orders']} ออเดอร์</span>
        </div>
        <div class="stat-row">
          <span class="stat-label">ยอดขายรวม (#BUY)</span>
          <span class="stat-val">{p['total_thb']:,}฿</span>
        </div>
        <div class="stat-row">
          <span class="stat-label">ยอดเฉลี่ยต่อออเดอร์</span>
          <span class="stat-val">{p['aov']:,}฿ <span class="sub">(เป้า 550฿+)</span></span>
        </div>
        <div class="stat-row">
          <span class="stat-label">ยอดขายต่อ 1 แชท</span>
          <span class="stat-val">{p['rev_per_chat']:,}฿</span>
        </div>
        <div class="stat-row">
          <span class="stat-label">เวลาตอบเฉลี่ย (07:00–23:00)</span>
          <span class="stat-val"><span class="good">{html.escape(p['avg_label'])}</span></span>
        </div>
        <div class="stat-row">
          <span class="stat-label">แชทรอตอบ &gt; 3 ชม.</span>
          <span class="stat-val">{overdue_html}</span>
        </div>
        {badge_html}
      </div>""")

    bucket_rows_html = []
    for b_idx, (_h0, _h1, b_label, b_shift) in enumerate(TIME_BUCKET_SPECS):
        cells = []
        for p in rep["pages"]:
            b = p["buckets"][b_idx]
            if b["orders"] > 0:
                tags = ", ".join(f"{hhmm} (#BUY{amt})" for hhmm, amt, _c in b["items"][:5])
                if len(b["items"]) > 5:
                    tags += f" +{len(b['items']) - 5} บิล"
                cells.append(
                    f'<td><strong>{b["orders"]} ออเดอร์ ({b["total_thb"]:,}฿)</strong><br>'
                    f'<span style="color:#656D76;font-size:12.5px;">{html.escape(tags)}</span></td>'
                )
            else:
                sub_note = f"มีทัก {b['chats']} แชท" if b["chats"] > 0 else "ไม่มีแชทใหม่"
                cells.append(f'<td>0 ออเดอร์<br><span style="color:#656D76;font-size:12.5px;">{sub_note}</span></td>')
        bucket_rows_html.append(
            f"<tr><td><strong>{b_label}</strong> ({b_shift})</td>{''.join(cells)}</tr>"
        )

    cases_html_parts = []
    for idx, c in enumerate(rep["cases"], start=1):
        cases_html_parts.append(f"""
    <div class="case-card">
      <div class="case-title">{idx}) {html.escape(c['html_title'])}</div>
      <div class="chat-line">{html.escape(c['html_detail'])}</div>
      <div class="fix-box"><b>แนวทางปรับนิดเดียว:</b> {html.escape(c['html_fix'])}</div>
    </div>""")
    if not cases_html_parts:
        cases_html_parts.append("""
    <div class="case-card good">
      <div class="case-title">✅ ไม่พบคำพิมพ์ผิดใน Saved Replies และไม่มีแชทค้างเกิน 3 ชั่วโมงค่ะ</div>
      <div class="chat-line">ทีมแอดมินรักษามาตรฐานความไวและความถูกต้องได้ดีมากค่ะ</div>
    </div>""")

    p0, p1, p2 = rep["pages"][0], rep["pages"][1], rep["pages"][2]
    active_y = "active-pill" if rep["target_date"] == yesterday_str else ""
    active_t = "active-pill" if rep["target_date"] == today_str else ""

    return f"""<!DOCTYPE html>
<html lang="th">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>รายงานสำหรับทีมแอดมิน · ข้าวบุก 3 เพจ ({html.escape(rep['thai_date'])})</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Thai:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg: #F9F8F4; --card-bg: #FFFFFF; --text: #1F2328; --muted: #656D76;
      --border: #E5E2DC; --alert-bg: #FDF2F0; --alert-border: #F3C6BF; --alert-text: #9E2A2B;
      --good-bg: #EFF8F1; --good-border: #BFE3C8; --good-text: #1E6B3A;
      --mrbuk: #1E6091; --hommali: #8D5524; --sukjai: #2B7A4B;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0; padding: 32px 20px 64px; background: var(--bg); color: var(--text);
      font-family: 'IBM Plex Sans Thai', -apple-system, BlinkMacSystemFont, sans-serif; line-height: 1.6;
    }}
    .container {{ max-width: 980px; margin: 0 auto; }}
    .top-bar {{ display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; margin-bottom: 10px; }}
    .eyebrow {{ font-size: 13px; color: var(--muted); }}
    .date-pills {{ display: flex; gap: 8px; flex-wrap: wrap; }}
    .pill {{
      text-decoration: none; font-size: 13px; font-weight: 600; padding: 6px 12px;
      border-radius: 20px; border: 1px solid var(--border); background: #fff; color: var(--text);
    }}
    .pill.active-pill {{ background: #1F2328; color: #fff; border-color: #1F2328; }}
    h1 {{ font-size: 28px; font-weight: 700; margin: 0 0 6px; letter-spacing: -0.01em; }}
    .subhead {{ font-size: 14px; color: var(--muted); margin-bottom: 22px; }}
    .summary-box {{
      background: var(--good-bg); border: 1px solid var(--good-border);
      border-radius: 12px; padding: 18px 22px; margin-bottom: 28px;
    }}
    .summary-box h3 {{ margin: 0 0 6px; font-size: 16px; color: var(--good-text); }}
    .summary-box p {{ margin: 0; font-size: 15px; color: #222; }}
    h2 {{ font-size: 19px; font-weight: 700; margin: 34px 0 14px; padding-top: 18px; border-top: 2px solid #222; }}
    .cards-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }}
    @media (max-width: 820px) {{ .cards-grid {{ grid-template-columns: 1fr; }} }}
    .page-card {{
      background: var(--card-bg); border: 1px solid var(--border);
      border-radius: 14px; padding: 20px; box-shadow: 0 2px 6px rgba(0,0,0,0.02);
    }}
    .page-card.mrbuk {{ border-top: 5px solid var(--mrbuk); }}
    .page-card.hommali {{ border-top: 5px solid var(--hommali); }}
    .page-card.sukjai {{ border-top: 5px solid var(--sukjai); }}
    .page-title {{ font-size: 16px; font-weight: 700; margin-bottom: 4px; }}
    .page-card.mrbuk .page-title {{ color: var(--mrbuk); }}
    .page-card.hommali .page-title {{ color: var(--hommali); }}
    .page-card.sukjai .page-title {{ color: var(--sukjai); }}
    .big-rate {{ font-size: 36px; font-weight: 700; line-height: 1.15; margin: 2px 0; }}
    .rate-caption {{ font-size: 12.5px; color: var(--muted); margin-bottom: 14px; }}
    .stat-row {{
      display: flex; justify-content: space-between; align-items: baseline;
      padding: 7px 0; border-top: 1px solid #F0EEEA; font-size: 14px;
    }}
    .stat-label {{ color: var(--muted); }}
    .stat-val {{ font-weight: 600; text-align: right; }}
    .stat-val .sub {{ font-weight: 400; color: var(--alert-text); font-size: 12.5px; }}
    .stat-val .good {{ color: var(--good-text); }}
    .stat-val .bad {{ color: var(--alert-text); }}
    .badge {{
      display: inline-block; margin-top: 12px; padding: 5px 10px;
      border-radius: 8px; font-size: 12.5px; font-weight: 600;
    }}
    .badge.warn {{ background: var(--alert-bg); color: var(--alert-text); }}
    .badge.ok {{ background: var(--good-bg); color: var(--good-text); }}
    .footnote {{ font-size: 12.5px; color: var(--muted); margin-top: 10px; }}
    table {{
      width: 100%; border-collapse: collapse; background: var(--card-bg);
      border-radius: 12px; overflow: hidden; border: 1px solid var(--border); font-size: 14px;
    }}
    th, td {{ padding: 11px 14px; text-align: left; border-bottom: 1px solid #F0EEEA; vertical-align: top; }}
    th {{ background: #F4F2EC; font-weight: 700; color: #333; }}
    .case-card {{
      background: var(--card-bg); border: 1px solid var(--border);
      border-left: 4px solid #D9534F; border-radius: 10px; padding: 16px 18px; margin-bottom: 14px;
    }}
    .case-card.good {{ border-left-color: var(--good-text); background: #FCFDFC; }}
    .case-title {{ font-weight: 700; font-size: 15px; margin-bottom: 8px; color: #9E2A2B; }}
    .case-card.good .case-title {{ color: var(--good-text); }}
    .chat-line {{ margin: 4px 0; font-size: 14px; }}
    .fix-box {{
      margin-top: 10px; padding: 10px 12px; background: #F6F8FA;
      border-radius: 8px; font-size: 13.5px; border-left: 3px solid var(--mrbuk);
    }}
    .script-card {{
      background: var(--card-bg); border: 1px solid var(--border);
      border-radius: 10px; padding: 14px 16px; margin-bottom: 12px;
    }}
    .script-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }}
    .script-title {{ font-weight: 700; font-size: 14px; color: #333; }}
    .copy-btn {{
      background: #F3F1EC; border: 1px solid #D5D1C8; border-radius: 6px;
      padding: 4px 12px; font-size: 12.5px; font-family: inherit; cursor: pointer; font-weight: 600;
    }}
    .script-body {{
      font-size: 14px; color: #222; background: #FAF9F6;
      padding: 10px 12px; border-radius: 8px; white-space: pre-line;
    }}
  </style>
</head>
<body>
  <div class="container">
    <div class="top-bar">
      <div class="eyebrow">รายงานสำหรับทีมแอดมิน · ข้าวบุก 3 เพจ (อัปเดตสดจาก Graph API)</div>
      <div class="date-pills">
        <a class="pill {active_y}" href="/admin-report?date={yesterday_str}">เมื่อวาน 24 ชม. ({yesterday_str})</a>
        <a class="pill {active_t}" href="/admin-report?date={today_str}&refresh=1">วันนี้สด ({today_str})</a>
      </div>
    </div>
    <h1>อัตราปิดการขาย &amp; คุณภาพการตอบแชท</h1>
    <div class="subhead">ข้อมูลจริง: {html.escape(rep['thai_date'])} · {html.escape(rep['period_label'])} (ดึงข้อมูลเมื่อ {html.escape(rep['generated_at'])})</div>

    <div class="summary-box">
      <h3>สรุปภาพรวมทั้ง 3 เพจ ({html.escape(rep['thai_date'])})</h3>
      <p>
        ทั้ง 3 เพจปิดออเดอร์รวมกันได้ <strong>{rep['total_orders']} ออเดอร์ ({rep['total_thb']:,}฿)</strong>
        จากแชทที่คุยในวันทั้งหมด <strong>{rep['total_chats']} แชท</strong> ·
        🌟 <strong>ชมเชย:</strong> {html.escape(rep['praise_text'])}
      </p>
    </div>

    <h2>1. ผลของแต่ละเพจ ({html.escape(rep['period_label'])})</h2>
    <div class="cards-grid">
      {''.join(cards_html_parts)}
    </div>
    <div class="footnote">
      * ดึงสดจาก Facebook Graph API ทั้ง 3 เพจแบบ Read-Only 100% · นับออเดอร์จากรหัส #BUY ในแชทจริง · เวลาตอบเฉลี่ยคิดเฉพาะกะกลางวัน 07:00–23:00 น. (ไม่รวมช่วงดึก)
    </div>

    <h2>2. รายการออเดอร์แยกตามช่วงเวลา 4 ชั่วโมง ({html.escape(rep['thai_date'])})</h2>
    <table>
      <thead>
        <tr>
          <th>ช่วงเวลา</th>
          <th>Mr.Buk มิสเตอร์บุก</th>
          <th>ข้าวบุกหอมมะลิ (เพจ 2)</th>
          <th>ข้าวบุก สุขใจ</th>
        </tr>
      </thead>
      <tbody>
        {''.join(bucket_rows_html)}
      </tbody>
    </table>

    <h2>3. เคสตัวอย่างจากแชทจริง ({html.escape(rep['thai_date'])})</h2>
    {''.join(cases_html_parts)}

    <h2>4. สคริปต์สั้นๆ พร้อมใช้ (กดคัดลอกไปใช้ได้ทันที)</h2>
    <div class="script-card">
      <div class="script-header">
        <span class="script-title">เมื่อลูกค้าบอก “3 ซอง / โอน” (ส่งยอด + เลขบัญชีล็อกออเดอร์ทันที)</span>
        <button class="copy-btn" onclick="copyScript(this, 'sc1')">คัดลอก</button>
      </div>
      <div class="script-body" id="sc1">ได้เลยค่ะ ซองเล็ก 60g 3 ซอง ยอด 117 + ค่าส่ง 30 = รวมโอน 147 บาทค่ะ 😊
(หรือถ้ารับ 5 ซอง 195.- / ถุงกลาง 500g 239.- ก็แจ้งปรับได้นะคะ)

โอนแล้วแจ้งสลิปพร้อม ชื่อ - ที่อยู่ - เบอร์โทร ได้เลยค่ะ 🙏💚</div>
    </div>

    <div class="script-card">
      <div class="script-header">
        <span class="script-title">เมื่อลูกค้าสั่ง 500g (เชียร์ขยับ 1 กก. โอนส่งฟรีสั้นๆ)</span>
        <button class="copy-btn" onclick="copyScript(this, 'sc2')">คัดลอก</button>
      </div>
      <div class="script-body" id="sc2">ได้เลยค่ะ 😊 ขนาด 500g โอนชำระ 289 บาท (ปลายทาง 319 บาท) ค่ะ
แต่ถ้าเพิ่มอีกนิดเป็นถุงใหญ่ 1 กิโล 490 บาท (โอนส่งฟรี! ทานได้ 16–20 มื้อ) จะคุ้มกว่ามากเลยค่ะ คุณลูกค้ารับเป็น 500g หรือ 1 กก. ดีคะ 🥰</div>
    </div>

    <div class="script-card">
      <div class="script-header">
        <span class="script-title">เมื่อลูกค้าถาม “มีซองเล็กเฉพาะมื้อไหม” (ตอบสั้นตรงคำถามก่อน)</span>
        <button class="copy-btn" onclick="copyScript(this, 'sc3')">คัดลอก</button>
      </div>
      <div class="script-body" id="sc3">มีค่ะคุณลูกค้า 🍚 ซองเล็ก 60 กรัม (ทานอิ่มพอดี 1 มื้อ) ราคาโปรซองละ 39 บาทค่ะ
คุณลูกค้าสนใจรับไปลองทานกี่ซองดีคะ 😊</div>
    </div>

    <h2>5. ตัวชี้วัดเป้าหมายประจำวัน</h2>
    <table>
      <thead>
        <tr>
          <th>ตัวชี้วัด</th>
          <th>เป้าหมาย</th>
          <th>ผลจริง (Mr.Buk / หอมมะลิ / สุขใจ)</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>% ปิดการขาย (เฉพาะแชทที่คุยในวัน)</td>
          <td>25%+ ต่อกะ</td>
          <td>{p0['conv_rate']}% / {p1['conv_rate']}% / {p2['conv_rate']}%</td>
        </tr>
        <tr>
          <td>ยอดเฉลี่ยต่อออเดอร์ (AOV)</td>
          <td>550฿ ขึ้นไป</td>
          <td>{p0['aov']:,}฿ / {p1['aov']:,}฿ / {p2['aov']:,}฿</td>
        </tr>
        <tr>
          <td>เวลาตอบกลับเฉลี่ย (07:00–23:00 น.)</td>
          <td>ไม่เกิน 3–5 นาที</td>
          <td>{html.escape(p0['avg_compact'])} / {html.escape(p1['avg_compact'])} / {html.escape(p2['avg_compact'])}</td>
        </tr>
        <tr>
          <td>แชทรอตอบเกิน 3 ชั่วโมง</td>
          <td>0 แชท</td>
          <td>Mr.Buk {p0['overdue_3h']} / หอมมะลิ {p1['overdue_3h']} / สุขใจ {p2['overdue_3h']}</td>
        </tr>
      </tbody>
    </table>
  </div>

  <script>
    function copyScript(btn, id) {{
      const text = document.getElementById(id).innerText;
      navigator.clipboard.writeText(text).then(() => {{
        const old = btn.innerText;
        btn.innerText = 'คัดลอกแล้ว ✓';
        setTimeout(() => {{ btn.innerText = old; }}, 1800);
      }});
    }}
  </script>
</body>
</html>"""


def register_admin_report_routes(app: Any) -> None:
    """Mount `/admin-report`, `/api/admin-report/status`, `/api/admin-report/preview`, and `/api/admin-report/send`."""

    @app.get("/admin-report", response_class=HTMLResponse)
    async def view_admin_report(date: str | None = None, refresh: int = 0):
        import asyncio

        html_out = await asyncio.to_thread(render_admin_report_html, date, bool(refresh))
        return HTMLResponse(content=html_out)

    @app.get("/api/admin-report/status")
    async def get_admin_report_status():
        state = load_admin_report_state()
        toks = resolve_three_page_tokens()
        public_state = {k: v for k, v in state.items() if k != "sealed_page_tokens"}
        return {
            "status": "ok",
            "bot": "พุดดิ้ง🍮 (@346zyzej)",
            "silent_mode": True,
            "schedule_time_bkk": "01:00",
            "active_admin_group_id": get_active_pudding_admin_group_id(),
            "pages_connected": {k: bool(v) for k, v in toks.items()},
            "state": public_state,
        }

    @app.get("/api/admin-report/preview")
    async def preview_admin_report(date: str | None = None, refresh: int = 0):
        import asyncio

        rep = await asyncio.to_thread(get_three_pages_live_report, date, bool(refresh))
        line_text = await asyncio.to_thread(format_pudding_line_summary, "", rep["target_date"], False)
        return {
            "status": "ok",
            "target_date": rep["target_date"],
            "total_orders": rep["total_orders"],
            "total_thb": rep["total_thb"],
            "total_chats": rep["total_chats"],
            "pages": [
                {
                    "key": p["key"],
                    "title": p["title"],
                    "chats": p["chats"],
                    "orders": p["orders"],
                    "total_thb": p["total_thb"],
                    "conv_rate": p["conv_rate"],
                    "aov": p["aov"],
                    "avg_label": p["avg_label"],
                    "overdue_3h": p["overdue_3h"],
                }
                for p in rep["pages"]
            ],
            "line_preview": line_text,
        }

    @app.post("/api/admin-report/send")
    async def trigger_send_admin_report(group_id: str | None = None, date: str | None = None):
        import asyncio

        return await asyncio.to_thread(send_pudding_report_to_line_group, group_id, "", date, True)
