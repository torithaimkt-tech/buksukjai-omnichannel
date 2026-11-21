"""2-Stage Automated Parcel Tracking & Delivery Notification Engine for ข้าวบุกสุขใจ (buksukjai).

Strictly Isolated Mode (`parcel_tracking_enabled = True`, Sales Bot `active = False`):
- Sends ONLY:
  1. Stage 1 (จัดส่งสินค้าแล้ว): Triggered when a JST ERP order gets a tracking number (`LogisticsTrackingNumber`)
     and the courier scans/collects the parcel (`Collected` / `รับพัสดุ`).
  2. Stage 2 (พัสดุจัดส่งถึงแล้ว): Triggered when live courier trajectory confirms delivery (`Delivered` / `Signed` / `เซ็นรับ`).
- Supports BOTH Facebook Messenger (with `POST_PURCHASE_UPDATE` fallback >24h) and LINE OA (`@602xbpha` Push API).
- Enforces Bangkok Time Send Window (`09:00–20:00` BKK) so customers are never disturbed late at night.
- Uses 10 distinct concise Stage 1 patterns + 10 distinct concise Stage 2 patterns (shuffled non-repeating deck).
- Syncs encrypted state (`parcel_tracking_vault.json`) to `jst-vault` so Render container restarts never cause duplicates
  or lose LINE OA customer phone-to-userId mappings.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import random
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from . import database, jst_erp, messenger
from .config_loader import get_page_by_brand_id
from .llm import split_into_bubbles

logger = logging.getLogger(__name__)

BKK_TZ = timezone(timedelta(hours=7))
BUKSUKJAI_SHOP_ID = 20759963
PARCEL_VAULT_FILE = "parcel_tracking_vault.json"

TRACKING_STATE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "parcel_tracking_state.json",
)

DEFAULT_TRACKING_STATE: dict[str, Any] = {
    "auto_enabled": True,
    "brand_id": "buksukjai",
    "send_window_start_hour": 9,
    "send_window_end_hour": 20,
    "min_order_date": "2026-11-19",
    "baseline_delivered_before": "2026-11-21 22:00:00",
    "max_pickup_age_hours": 36.0,
    "max_delivery_age_hours": 20.0,
    "last_scan_at": "",
    "last_full_fb_sync_date": "",
    "state_updated_at": "",
    "deck_stage1": [],
    "deck_stage2": [],
    "last_stage1_idx": -1,
    "last_stage2_idx": -1,
    "phone_index": {},
    "orders": {},
}

PHONE_REGEX = re.compile(r"(?:\+66\s*0?|0)[689]\d(?:[\s\-._/]*\d){7}")


def _now_bkk() -> datetime:
    return datetime.now(BKK_TZ)


def _parse_bkk_dt(dt_str: str) -> datetime | None:
    raw = (dt_str or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(raw[:19], fmt).replace(tzinfo=BKK_TZ)
        except Exception:
            continue
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return dt.replace(tzinfo=BKK_TZ)
        return dt.astimezone(BKK_TZ)
    except Exception:
        return None


def is_within_send_window(now_bkk: datetime | None = None, state: dict[str, Any] | None = None) -> tuple[bool, str]:
    """Check whether current Bangkok time is inside the allowed customer notification window (default 09:00–20:00)."""
    st = state or get_tracking_state()
    start_h = int(st.get("send_window_start_hour", 9))
    end_h = int(st.get("send_window_end_hour", 20))
    cur = now_bkk or _now_bkk()
    allowed = start_h <= cur.hour < end_h
    window_label = f"{start_h:02d}:00-{end_h:02d}:00"
    return allowed, window_label


def get_tracking_state() -> dict[str, Any]:
    st = json.loads(json.dumps(DEFAULT_TRACKING_STATE))
    if os.path.exists(TRACKING_STATE_PATH):
        try:
            with open(TRACKING_STATE_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                st.update(saved)
                if not isinstance(st.get("orders"), dict):
                    st["orders"] = {}
                if not isinstance(st.get("phone_index"), dict):
                    st["phone_index"] = {}
                if not isinstance(st.get("deck_stage1"), list):
                    st["deck_stage1"] = []
                if not isinstance(st.get("deck_stage2"), list):
                    st["deck_stage2"] = []
        except Exception as exc:
            logger.warning("Failed to load parcel_tracking_state.json: %s", exc)
    return st


def save_tracking_state(state: dict[str, Any], touch_updated_at: bool = True) -> dict[str, Any]:
    if touch_updated_at:
        state["state_updated_at"] = _now_bkk().isoformat()
    try:
        with open(TRACKING_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.warning("Failed to save parcel_tracking_state.json: %s", exc)
    return state


# --- Encrypted Cloud Vault Sync (`parcel_tracking_vault.json` on `jst-vault`) ---

def _sign_parcel_vault(updated_at: str, encrypted_blob: str) -> str:
    master = jst_erp._get_vault_secret_bytes()
    if not master or not updated_at or not encrypted_blob:
        return ""
    msg = f"parcel-vault-v1:{updated_at}:{encrypted_blob}".encode("utf-8")
    return hmac.new(master, msg, hashlib.sha256).hexdigest()


def export_encrypted_parcel_vault() -> dict[str, str]:
    """Export encrypted parcel tracking state + LINE OA phone index for safe cloud persistence."""
    st = get_tracking_state()
    updated_at = str(st.get("state_updated_at") or "").strip() or _now_bkk().isoformat()
    compact_payload = {
        "min_order_date": st.get("min_order_date", "2026-11-19"),
        "baseline_delivered_before": st.get("baseline_delivered_before", "2026-11-21 22:00:00"),
        "last_scan_at": st.get("last_scan_at", ""),
        "deck_stage1": st.get("deck_stage1", []),
        "deck_stage2": st.get("deck_stage2", []),
        "last_stage1_idx": st.get("last_stage1_idx", -1),
        "last_stage2_idx": st.get("last_stage2_idx", -1),
        "phone_index": st.get("phone_index", {}),
        "orders": st.get("orders", {}),
    }
    plaintext = json.dumps(compact_payload, ensure_ascii=False, separators=(",", ":"))
    enc = jst_erp.encrypt_cookie_blob(plaintext)
    sig = _sign_parcel_vault(updated_at, enc)
    return {
        "version": "1",
        "state_updated_at": updated_at,
        "persisted_state_enc": enc,
        "vault_sig": sig,
    }


def import_encrypted_parcel_vault(envelope: dict[str, Any], force: bool = False) -> dict[str, Any]:
    """Verify and merge encrypted parcel tracking vault so sent flags & LINE phone mappings never get lost."""
    if not isinstance(envelope, dict):
        return {"status": "invalid_envelope"}
    rem_ts = str(envelope.get("state_updated_at") or "").strip()
    enc = str(envelope.get("persisted_state_enc") or "").strip()
    sig = str(envelope.get("vault_sig") or "").strip()
    if not rem_ts or not enc or not sig:
        return {"status": "missing_fields"}
    expected_sig = _sign_parcel_vault(rem_ts, enc)
    if not expected_sig or not hmac.compare_digest(sig, expected_sig):
        return {"status": "invalid_signature"}
    decrypted = jst_erp.decrypt_cookie_blob(enc)
    if not decrypted:
        return {"status": "decryption_failed"}
    try:
        rem_data = json.loads(decrypted)
    except Exception:
        return {"status": "invalid_json"}

    local_st = get_tracking_state()
    local_ts = str(local_st.get("state_updated_at") or "").strip()

    # Merge orders & phone_index additively so neither side ever loses a sent marker or LINE phone!
    merged_orders = dict(local_st.get("orders") or {})
    for oid, r_ord in (rem_data.get("orders") or {}).items():
        if not isinstance(r_ord, dict):
            continue
        cur_ord = merged_orders.get(oid)
        if not isinstance(cur_ord, dict):
            merged_orders[oid] = r_ord
        else:
            merged = {**cur_ord, **r_ord}
            merged["stage1_pickup_sent_at"] = (
                cur_ord.get("stage1_pickup_sent_at") or r_ord.get("stage1_pickup_sent_at") or ""
            )
            merged["stage2_delivered_sent_at"] = (
                cur_ord.get("stage2_delivered_sent_at") or r_ord.get("stage2_delivered_sent_at") or ""
            )
            merged["is_picked_up"] = bool(cur_ord.get("is_picked_up") or r_ord.get("is_picked_up"))
            merged["is_delivered"] = bool(cur_ord.get("is_delivered") or r_ord.get("is_delivered"))
            merged_orders[oid] = merged

    merged_phones = dict(local_st.get("phone_index") or {})
    for ph, r_ph in (rem_data.get("phone_index") or {}).items():
        if not isinstance(r_ph, dict):
            continue
        cur_ph = merged_phones.get(ph)
        if not isinstance(cur_ph, dict) or str(r_ph.get("updated_at") or "") >= str(cur_ph.get("updated_at") or ""):
            merged_phones[ph] = r_ph
            # Also ensure UserSession exists in local SQLite after Render restart
            psid = str(r_ph.get("psid") or "")
            ext_id = str(r_ph.get("external_user_id") or "")
            plat = str(r_ph.get("platform") or "line")
            cname = str(r_ph.get("customer_name") or "")
            if psid and ext_id:
                database.get_or_create_session(
                    psid=psid,
                    brand_id="buksukjai",
                    platform=plat,
                    external_user_id=ext_id,
                    customer_name=cname,
                )
                jst_erp._append_session_note(psid, f"#PHONE:{ph}")

    local_st["orders"] = merged_orders
    local_st["phone_index"] = merged_phones
    if force or not local_ts or rem_ts > local_ts:
        for k in ("deck_stage1", "deck_stage2", "last_stage1_idx", "last_stage2_idx", "last_scan_at"):
            if k in rem_data:
                local_st[k] = rem_data[k]
        local_st["state_updated_at"] = rem_ts
        save_tracking_state(local_st, touch_updated_at=False)
        return {"status": "adopted", "state_updated_at": rem_ts, "orders_count": len(merged_orders)}

    save_tracking_state(local_st, touch_updated_at=False)
    return {"status": "merged_kept_local_ts", "state_updated_at": local_ts, "orders_count": len(merged_orders)}


def restore_parcel_vault_from_cloud() -> dict[str, Any]:
    """Pull `parcel_tracking_vault.json` from `jst-vault` branch on Render startup."""
    ts_now = int(time.time())
    repo = getattr(jst_erp, "JST_VAULT_REPO", "torithaimkt-tech/buksukjai-omnichannel")
    branch = getattr(jst_erp, "JST_VAULT_BRANCH", "jst-vault")
    urls = [
        (
            f"https://api.github.com/repos/{repo}/contents/{PARCEL_VAULT_FILE}?ref={branch}&t={ts_now}",
            {"Accept": "application/vnd.github.raw", "User-Agent": "buksukjai-parcel-vault/1.0"},
        ),
        (
            f"https://raw.githubusercontent.com/{repo}/{branch}/{PARCEL_VAULT_FILE}?t={ts_now}",
            {"Cache-Control": "no-cache", "User-Agent": "buksukjai-parcel-vault/1.0"},
        ),
    ]
    for u, hdrs in urls:
        try:
            r = httpx.get(u, headers=hdrs, timeout=8.0, follow_redirects=True)
            if r.status_code == 200 and r.text.strip().startswith("{"):
                env = json.loads(r.text)
                res = import_encrypted_parcel_vault(env, force=False)
                if res.get("status") in ("adopted", "merged_kept_local_ts"):
                    logger.info("Parcel tracking cloud vault restored (%s): %s orders", res.get("status"), res.get("orders_count"))
                    return res
        except Exception as exc:
            logger.debug("Parcel vault fetch warning (%s): %s", u, exc)
    return {"status": "vault_not_found_or_unreachable"}


def record_silent_customer_contact(
    brand_id: str,
    platform: str,
    external_user_id: str,
    text: str = "",
    customer_name: str = "",
    role: str = "user",
) -> list[str]:
    """Silently log incoming Messenger / LINE OA customer messages and index any 10-digit Thai phone number.
    Used when AI Sales Bot is disabled (`active=False`) so parcel tracking still matches 100% of customers!
    """
    if brand_id != "buksukjai" or platform not in ("line", "facebook") or not external_user_id:
        return []

    psid = database.make_session_key(brand_id, platform, external_user_id)
    session = database.get_or_create_session(
        psid=psid,
        brand_id=brand_id,
        platform=platform,
        external_user_id=external_user_id,
        customer_name=customer_name or "",
    )
    if customer_name and (not session.customer_name or session.customer_name.startswith("ลูกค้า")):
        database.update_session_meta(psid, customer_name=customer_name)

    clean_text = (text or "").strip()
    if clean_text:
        database.log_message(psid, role, clean_text)

    normalized_txt = jst_erp.translate_thai_numerals(clean_text)
    found_phones: list[str] = []
    for raw_m in PHONE_REGEX.findall(normalized_txt):
        p_norm = jst_erp.normalize_thai_phone(raw_m)
        if p_norm and p_norm not in found_phones:
            found_phones.append(p_norm)

    if found_phones:
        st = get_tracking_state()
        phone_index = st.setdefault("phone_index", {})
        now_iso = _now_bkk().isoformat()
        resolved_name = customer_name or session.customer_name or ""
        for ph in found_phones:
            jst_erp._append_session_note(psid, f"#PHONE:{ph}")
            phone_index[ph] = {
                "psid": psid,
                "platform": platform,
                "external_user_id": external_user_id,
                "customer_name": resolved_name,
                "updated_at": now_iso,
            }
        save_tracking_state(st, touch_updated_at=True)
        try:
            database.save_persistent_snapshot()
        except Exception:
            pass

    return found_phones


def _norm_name(s: str) -> str:
    s = re.sub(r"\s*\(#.*\)$", "", s or "")
    return re.sub(r"\s+", " ", s).strip().lower()


def _extract_hhmm(dt_str: str) -> str:
    """Extract HH:MM from 'YYYY-MM-DD HH:MM:SS'."""
    m = re.search(r"\b(\d{2}:\d{2})(?::\d{2})?\b", str(dt_str or ""))
    return m.group(1) if m else ""


# --- 10 Distinct Concise Stage 1 Patterns + 10 Distinct Concise Stage 2 Patterns ---
# All patterns strictly follow:
# - Feminine polite particles ONLY (ค่ะ / คะ / นะคะ / ค่า)
# - Short, crisp, 3–4 lines (~5–7 Thai words per line)
# - 100% Ad-Safe & Meta POST_PURCHASE_UPDATE compliant (factual shipping/delivery care, zero upsells)
# - Visual & structural variety so consecutive customers never look copy-pasted, and Stage 2 never repeats Stage 1!

def _pick_from_persisted_deck(state: dict[str, Any], stage: int, pool_size: int) -> int:
    deck_key = "deck_stage1" if stage == 1 else "deck_stage2"
    last_key = "last_stage1_idx" if stage == 1 else "last_stage2_idx"
    deck = [i for i in (state.get(deck_key) or []) if isinstance(i, int) and 0 <= i < pool_size]
    last_idx = int(state.get(last_key, -1))
    if not deck:
        deck = list(range(pool_size))
        random.shuffle(deck)
        if len(deck) > 1 and deck[0] == last_idx:
            deck[0], deck[-1] = deck[-1], deck[0]
    chosen = deck.pop(0)
    state[deck_key] = deck
    state[last_key] = chosen
    return chosen


def build_stage1_pickup_message(
    courier_name: str,
    tracking_no: str,
    state: dict[str, Any] | None = None,
) -> tuple[str, int]:
    """Return (message_text, pattern_idx) for Stage 1 (Parcel Shipped / Picked Up)."""
    c = (courier_name or "J&T Express").strip()
    t = tracking_no.strip()
    pool = [
        # 0: การ์ดแจ้งเลขพัสดุคลีนๆ
        (
            f"แจ้งเลขพัสดุข้าวบุกสุขใจค่ะ 📦\n"
            f"ขนส่ง: {c}\n"
            f"เลขพัสดุ: {t}\n"
            f"ของถึงแล้วแอดมินแจ้งอีกทีนะคะ 💚"
        ),
        # 1: ประโยคบอกเล่าสั้นอบอุ่น
        (
            f"ข้าวบุกสุขใจจัดส่งออกแล้วนะคะ 🚚\n"
            f"ส่งผ่าน {c}\n"
            f"เลขพัสดุ {t} ค่ะ\n"
            f"รอรับพัสดุได้เลยนะคะ ขอบคุณมากค่า 🙏"
        ),
        # 2: บุลเล็ตสั้นอ่านง่าย
        (
            f"อัปเดตการจัดส่งสินค้าค่ะ ✨\n"
            f"• ขนส่ง: {c}\n"
            f"• หมายเลขพัสดุ: {t}\n"
            f"พัสดุกำลังเดินทางไปหาคุณลูกค้าแล้วนะคะ 💚"
        ),
        # 3: โทนกันเองสุภาพ
        (
            f"คุณลูกค้าคะ ทางร้านส่งของให้แล้วน้า 📦\n"
            f"เลขพัสดุ {t} ({c}) ค่ะ\n"
            f"หากพัสดุถึงปลายทางแล้วจะแวะมาบอกนะคะ 😊"
        ),
        # 4: มินิมอลกระชับ 3 บรรทัด
        (
            f"🚚 พัสดุเข้าระบบขนส่งเรียบร้อยค่ะ\n"
            f"[{c}] {t}\n"
            f"ขอบคุณที่อุดหนุนข้าวบุกสุขใจนะคะ 🍚💚"
        ),
        # 5: แจ้งส่งมอบพี่ขนส่ง
        (
            f"ส่งมอบพัสดุให้พี่ขนส่งแล้วค่า 📦✨\n"
            f"ขนส่ง {c}\n"
            f"เลขติดตาม: {t}\n"
            f"ทางร้านช่วยดูสถานะให้จนถึงมือเลยนะคะ 💚"
        ),
        # 6: สุภาพตรงประเด็น
        (
            f"ขออนุญาตแจ้งเลขพัสดุนะคะ 🙏\n"
            f"{c} : {t}\n"
            f"สินค้าอยู่ระหว่างเดินทางไปหาคุณลูกค้าค่ะ 🚚"
        ),
        # 7: โทนโฮมมี่สบายตา
        (
            f"แพ็กข้าวบุกสุขใจส่งออกเรียบร้อยค่ะ 🍚📦\n"
            f"เช็กสถานะได้ที่ {c}\n"
            f"เลขพัสดุ {t} นะคะ 💚"
        ),
        # 8: ป้ายสถานะคำสั่งซื้อ
        (
            f"🔖 สถานะคำสั่งซื้อ: จัดส่งแล้วค่ะ\n"
            f"ขนส่ง: {c}\n"
            f"เลขพัสดุ: {t}\n"
            f"ขอบพระคุณที่ไว้วางใจทางร้านนะคะ 😊🙏"
        ),
        # 9: กระชับสดใส
        (
            f"พัสดุข้าวบุกสุขใจออกเดินทางแล้วค่า 🚚💨\n"
            f"หมายเลขพัสดุ {t}\n"
            f"จัดส่งโดย {c} รอรับได้เลยนะคะ 💚"
        ),
    ]
    if state is not None:
        idx = _pick_from_persisted_deck(state, stage=1, pool_size=len(pool))
    else:
        idx = random.randrange(len(pool))
    return pool[idx], idx


def build_stage2_delivered_message(
    courier_name: str,
    tracking_no: str,
    delivered_hhmm: str,
    state: dict[str, Any] | None = None,
) -> tuple[str, int]:
    """Return (message_text, pattern_idx) for Stage 2 (Parcel Delivered).
    Intentionally omits the courier/tracking block so it never looks like a duplicate of Stage 1!
    """
    time_badge = f" (เวลา {delivered_hhmm} น.)" if delivered_hhmm else ""
    time_word = f"เมื่อเวลา {delivered_hhmm} น. " if delivered_hhmm else ""
    pool = [
        # 0: สั้นคลีนขอบคุณ
        (
            f"พัสดุจัดส่งถึงเรียบร้อยแล้วนะคะ{time_badge} ✅\n"
            f"ขอบพระคุณที่อุดหนุนข้าวบุกสุขใจค่ะ\n"
            f"ทานให้อร่อยนะคะ 🍚💚"
        ),
        # 1: แจ้งของถึง + ทริคชงสั้นๆ
        (
            f"🎉 ขนส่งแจ้งว่าส่งพัสดุสำเร็จแล้วค่า{time_badge}\n"
            f"แค่ตักเติมน้ำร้อน ปิดฝารอ 10–15 นาที\n"
            f"ก็พร้อมทานมื้ออร่อยได้เลยนะคะ 😊"
        ),
        # 2: โทนอบอุ่นสบายใจ
        (
            f"ข้าวบุกสุขใจส่งถึงปลายทางแล้วค่ะ{time_badge} 📦✨\n"
            f"หากได้รับสินค้าเรียบร้อยแล้ว\n"
            f"ขอให้เป็นมื้อที่อิ่มอร่อยสบายท้องนะคะ 💚🙏"
        ),
        # 3: อัปเดตสถานะสั้นกระชับ
        (
            f"อัปเดตสถานะ: พัสดุส่งถึงมือแล้วนะคะ{time_badge} ✅\n"
            f"ขอบคุณที่เลือกข้าวบุกสุขใจดูแลมื้ออาหารค่ะ\n"
            f"สงสัยวิธีชงทักถามได้ตลอดเลยนะคะ 🍚"
        ),
        # 4: ทักทายสุภาพเป็นกันเอง
        (
            f"คุณลูกค้าคะ ขนส่งจัดส่งของถึงแล้วน้า{time_badge} 🎉\n"
            f"ขอบพระคุณมากๆ ที่ไว้วางใจทางร้านนะคะ\n"
            f"ทานข้าวบุกสุขใจให้อร่อยค่า 💚"
        ),
        # 5: เน้นวิธีทำตัก-เติม-รอ
        (
            f"✅ จัดส่งสำเร็จเรียบร้อยค่ะ {time_word}\n".rstrip() + "\n"
            f"วิธีทำง่ายๆ แค่ตัก เติมน้ำร้อน ปิดฝา 10–15 นาทีค่ะ\n"
            f"ขอบคุณที่อุดหนุนนะคะ 🙏✨"
        ),
        # 6: สั้นกระชับพร้อมดูแล
        (
            f"📦 พัสดุเดินทางถึงคุณลูกค้าแล้วค่า{time_badge}\n"
            f"ทางร้านขอขอบพระคุณจากใจเลยนะคะ\n"
            f"มีคำถามเพิ่มเติมทักแชทได้เสมอค่ะ 😊💚"
        ),
        # 7: แจ้งเช็กรับพัสดุ
        (
            f"แจ้งเตือนพัสดุถึงปลายทางแล้วค่ะ{time_badge} 🍚✨\n"
            f"เช็กรับกล่องพัสดุได้เลยนะคะ\n"
            f"ขอบคุณที่ให้ข้าวบุกสุขใจดูแลในทุกมื้อค่ะ 💚"
        ),
        # 8: แจ้งถึงแล้ว + วิธีเก็บรักษาสั้นๆ
        (
            f"ส่งถึงมือเรียบร้อยแล้วนะคะ{time_badge} 🎉\n"
            f"เก็บในอุณหภูมิห้องพ้นแสงแดดได้เลยค่ะ\n"
            f"ขอบพระคุณที่อุดหนุนข้าวบุกสุขใจนะคะ 🙏💚"
        ),
        # 9: ป้ายสถานะส่งสำเร็จมินิมอล
        (
            f"✨ สถานะพัสดุ: จัดส่งสำเร็จแล้วค่ะ{time_badge}\n"
            f"ขอให้อิ่มอร่อยกับข้าวบุกสุขใจในทุกมื้อนะคะ\n"
            f"ขอบคุณมากค่า 😊🍚"
        ),
    ]
    if state is not None:
        idx = _pick_from_persisted_deck(state, stage=2, pool_size=len(pool))
    else:
        idx = random.randrange(len(pool))
    return pool[idx], idx


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
        r_upd = httpx.post(
            "https://asia.jsterp.com/OMS/OrderLogistics/UpdateLogisticsTrajectory",
            headers=h,
            json=[{"ShopId": BUKSUKJAI_SHOP_ID, "OrderId": oid_int}],
            timeout=12.0,
        )
        jst_erp.update_cookie_from_response(r_upd)
    except Exception as exc:
        logger.debug("UpdateLogisticsTrajectory warning for %s: %s", oid_int, exc)

    try:
        r_get = httpx.post(
            "https://asia.jsterp.com/OMS/OrderLogistics/GetLogisticsTrajectory",
            headers=h,
            json={"OrderId": oid_int, "InoutId": 0},
            timeout=12.0,
        )
        jst_erp.update_cookie_from_response(r_get)
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
    send_time = str(order_row.get("SendTime") or "").strip()
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

        if "รับพัสดุ" == st_txt or "รับพัสดุแล้ว" in desc_txt or st_txt.lower() == "collected":
            pickup_op_time = op_time
            is_picked_up = True

        if (
            "เซ็นรับ" in st_txt
            or "เซ็นรับแล้ว" in desc_txt
            or "จัดส่งสำเร็จ" in desc_txt
            or st_txt.lower() in ("delivered", "signed")
        ):
            is_delivered = True
            is_picked_up = True
            if not delivered_op_time:
                delivered_op_time = op_time

    if not is_delivered and logistics_status in ("Delivered", "Signed"):
        is_delivered = True
        delivered_op_time = sign_time or delivered_op_time

    if is_picked_up and not pickup_op_time:
        if events:
            pickup_op_time = str(events[-1].get("OperationTime") or "").strip()
        if not pickup_op_time and send_time:
            pickup_op_time = send_time

    return {
        "order_id": order_id,
        "tracking_no": tracking_no,
        "courier_name": courier_name,
        "is_picked_up": is_picked_up,
        "pickup_time": pickup_op_time,
        "pickup_hhmm": _extract_hhmm(pickup_op_time),
        "is_delivered": is_delivered,
        "delivered_time": delivered_op_time or sign_time,
        "delivered_hhmm": _extract_hhmm(delivered_op_time or sign_time),
        "events_count": len(events),
        "events": events,
        "latest_event": events[0] if events else None,
    }


def _query_recent_jst_orders(page_size: int = 150) -> list[dict[str, Any]]:
    """Fetch recent orders from JST ERP (`NewQueryOrders`)."""
    jst_erp.restore_cookie_from_cloud_vault()
    h = jst_erp._headers(json_body=True)
    resp = httpx.post(
        "https://asia.jsterp.com/OMS/MiniShopOrder/NewQueryOrders",
        headers=h,
        json={
            "RequestModel": {"SendFrom": "NewQueryOrders"},
            "DataPage": {"pageSize": page_size, "pageIndex": 1, "total": 0, "sizes": [50, 100, 200]},
        },
        timeout=25.0,
    )
    jst_erp.update_cookie_from_response(resp)
    resp.raise_for_status()
    rows_obj = (resp.json() or {}).get("Rows") or {}
    cols = rows_obj.get("cols") or []
    raw_rows = rows_obj.get("rows") or []
    return [dict(zip(cols, r)) for r in raw_rows]


def _is_eligible_buksukjai_chat_order(row: dict[str, Any]) -> bool:
    """Strictly allow ONLY ข้าวบุกสุขใจ manual chat orders (Facebook Messenger & LINE OA).
    Blocks Marketplace orders (TikTok Shop, Shopee) and blocks any non-BukSukjai brand SKUs.
    """
    shop_id = int(row.get("ShopId") or 0)
    shop_name = str(row.get("ShopName") or "").strip()
    if shop_id and shop_id != BUKSUKJAI_SHOP_ID and shop_name != "ข้าวบุกสุขใจ":
        return False

    order_from = str(row.get("OrderFrom") or "").strip().upper()
    if order_from in ("TIKTOK_SHOP", "SHOPEE", "LAZADA"):
        return False

    platform_from = str(row.get("OrderFromPlatfrom") or "").strip().lower()
    if platform_from in ("shopee", "lazada"):
        return False

    skus = row.get("Skus") or []
    if any("MRBUK" in str(sk).upper() for sk in skus):
        return False

    raw_mob = str(row.get("ReceiverMobileEn") or "").strip()
    remark = str(row.get("SellerRemark") or "").strip()
    if (not raw_mob or "*" in raw_mob) and not remark.startswith(("FB:", "LINE:")):
        return False

    return True


def _build_session_lookup_maps(state: dict[str, Any]) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Return (order_id_to_psid, phone_to_psid, norm_name_to_psid) strictly for `buksukjai` Messenger & LINE OA.
    Because `list_all_sessions` is sorted by `last_interaction_time DESC`, if a customer exists on both Facebook and LINE,
    the channel where they most recently interacted wins automatically!
    """
    all_sessions = database.list_all_sessions(brand_id="buksukjai")
    order_id_to_psid: dict[str, str] = {}
    phone_candidates: dict[str, tuple[str, str]] = {}  # phone -> (iso_ts, psid)
    name_to_psid: dict[str, str] = {}

    # 1. Load persisted phone_index (especially LINE OA customers captured by silent webhook listener)
    for ph, entry in (state.get("phone_index") or {}).items():
        if not isinstance(entry, dict):
            continue
        psid = str(entry.get("psid") or "")
        plat = str(entry.get("platform") or "")
        upd = str(entry.get("updated_at") or "")
        if psid.startswith("buksukjai:") and plat in ("line", "facebook"):
            phone_candidates[ph] = (upd, psid)

    # 2. Scan SQLite sessions (ordered newest interaction first)
    for s in all_sessions:
        psid = str(s.get("psid") or "")
        plat = str(s.get("platform") or "")
        if s.get("brand_id") != "buksukjai" or plat not in ("facebook", "line"):
            continue

        last_ts = str(s.get("last_interaction_time") or "")
        cname = _norm_name(s.get("customer_name") or "")
        notes = (s.get("notes") or "").strip()
        if cname and cname not in name_to_psid:
            name_to_psid[cname] = psid

        for m_oid in re.findall(r"#JST_ORDER:(\d+)", notes):
            order_id_to_psid[m_oid] = psid

        for m_ph in re.findall(r"#PHONE:(0[689]\d{8})", notes):
            prev = phone_candidates.get(m_ph)
            if not prev or last_ts > prev[0]:
                phone_candidates[m_ph] = (last_ts, psid)

        norm_notes = jst_erp.translate_thai_numerals(notes)
        for m_ph in PHONE_REGEX.findall(norm_notes):
            clean_p = jst_erp.normalize_thai_phone(m_ph)
            if clean_p:
                prev = phone_candidates.get(clean_p)
                if not prev or last_ts > prev[0]:
                    phone_candidates[clean_p] = (last_ts, psid)

        msgs = database.get_full_messages(psid, limit=60)
        for msg in msgs:
            txt = jst_erp.translate_thai_numerals(str(msg.get("content") or ""))
            msg_ts = str(msg.get("created_at") or last_ts)
            for m_ph in PHONE_REGEX.findall(txt):
                clean_p = jst_erp.normalize_thai_phone(m_ph)
                if clean_p:
                    prev = phone_candidates.get(clean_p)
                    if not prev or msg_ts > prev[0]:
                        phone_candidates[clean_p] = (msg_ts, psid)

    phone_to_psid = {ph: pair[1] for ph, pair in phone_candidates.items()}
    return order_id_to_psid, phone_to_psid, name_to_psid


def _has_already_sent_in_chat(psid: str, tracking_no: str, stage: int) -> bool:
    """Check UserSession.notes and MessageLog to guarantee we NEVER send duplicate notifications
    (even if a human admin manually pasted the tracking number or if Render restarted).
    """
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

    # Locate the latest order summary in chat so older historical orders don't block a repeat purchase!
    last_order_idx = -1
    for idx, m in enumerate(msgs):
        c = str(m.get("content") or "")
        if (
            (("เพจ :" in c or "เพจ:" in c) and ("จัดส่ง" in c or "สินค้า" in c))
            or re.search(r"#BUY\s*\d+", c, re.I)
            or "รับออเดอร์เรียบร้อย" in c
        ):
            last_order_idx = idx

    msgs_since_order = msgs[last_order_idx + 1 :] if last_order_idx >= 0 else msgs

    stage1_markers = (
        "เลขพัสดุ:",
        "เลขพัสดุ ",
        "หมายเลขพัสดุ",
        "เลขติดตาม:",
        "แจ้งเลขพัสดุ",
        "จัดส่งพัสดุออกเรียบร้อย",
        "ข้าวบุกสุขใจจัดส่งออกแล้ว",
        "อัปเดตการจัดส่งสินค้าค่ะ",
        "ทางร้านส่งของให้แล้วน้า",
        "พัสดุเข้าระบบขนส่งเรียบร้อย",
        "ส่งมอบพัสดุให้พี่ขนส่งแล้ว",
        "สถานะคำสั่งซื้อ: จัดส่งแล้ว",
        "พัสดุข้าวบุกสุขใจออกเดินทางแล้ว",
    )
    stage2_markers = (
        "พัสดุจัดส่งถึงเรียบร้อย",
        "พัสดุส่งถึงมือเรียบร้อย",
        "ขนส่งแจ้งว่าพัสดุจัดส่งสำเร็จ",
        "ขนส่งแจ้งว่าส่งพัสดุสำเร็จ",
        "ข้าวบุกสุขใจเดินทางถึงปลายทาง",
        "ข้าวบุกสุขใจส่งถึงปลายทางแล้ว",
        "สถานะ: พัสดุส่งถึงมือแล้ว",
        "ขนส่งจัดส่งของถึงแล้วน้า",
        "จัดส่งสำเร็จเรียบร้อยค่ะ",
        "พัสดุเดินทางถึงคุณลูกค้าแล้ว",
        "แจ้งเตือนพัสดุถึงปลายทางแล้ว",
        "ส่งถึงมือเรียบร้อยแล้วนะคะ",
        "สถานะพัสดุ: จัดส่งสำเร็จแล้ว",
        "ของถึงเรียบร้อยแล้วนะคะ",
        "ส่งถึงมือสำเร็จแล้วค่า",
    )
    user_already_received_or_issue_markers = (
        "ได้รับสินค้าแล้ว",
        "ได้รับของแล้ว",
        "ได้รับข้าวแล้ว",
        "ของถึงแล้ว",
        "ไปส่งมา 2 บิล",
        "ส่งมา2บิล",
        "2 บิล",
        "2บิล",
        "จ่าย2รอบ",
        "จ่าย 2 รอบ",
        "ส่งซ้ำ",
        "ตีกลับ",
    )

    # 1. Exact tracking_no already sent by page/admin/bot anywhere in thread
    for m in msgs:
        if m.get("role") != "user" and tracking_no and tracking_no in str(m.get("content") or ""):
            if stage == 1:
                return True

    # 2. Check messages since the latest order summary
    for m in msgs_since_order:
        role = m.get("role")
        content = str(m.get("content") or "")
        s_label = str(m.get("sender_label") or "")
        if role == "user":
            if any(umk in content for umk in user_already_received_or_issue_markers):
                return True
            continue
        if stage == 1:
            if "ระยะที่ 1" in s_label or any(mk in content for mk in stage1_markers):
                return True
        if stage == 2:
            if "ระยะที่ 2" in s_label or any(mk in content for mk in stage2_markers):
                return True
    return False


async def _send_tracking_notification(
    psid: str,
    stage: int,
    order_id: str,
    courier_name: str,
    tracking_no: str,
    state: dict[str, Any],
    delivered_hhmm: str = "",
    public_base_url: str = "",
) -> dict[str, Any] | None:
    """Send Stage 1 (Pickup) or Stage 2 (Delivered) message to customer on Messenger or LINE OA.
    Marks session/state ONLY when the platform API confirms HTTP 200 delivery!
    """
    user = database.get_or_create_session(psid)
    if user.brand_id != "buksukjai" or user.platform not in ("facebook", "line"):
        return None

    if stage == 1:
        msg_text, pat_idx = build_stage1_pickup_message(courier_name, tracking_no, state=state)
        sender_label = "AI แจ้งเลขพัสดุ (ระยะที่ 1)"
        tag_to_add = "แจ้งเลขพัสดุแล้ว"
        note_marker = f"#TRACK_PICKUP_SENT:{tracking_no}"
    else:
        msg_text, pat_idx = build_stage2_delivered_message(courier_name, tracking_no, delivered_hhmm, state=state)
        sender_label = "AI แจ้งพัสดุถึงแล้ว (ระยะที่ 2)"
        tag_to_add = "พัสดุส่งถึงแล้ว"
        note_marker = f"#TRACK_DELIVERED_SENT:{tracking_no}"

    delivered_ok = await messenger.send_omnichannel_text(
        platform=user.platform,
        external_user_id=user.external_user_id,
        text=msg_text,
        brand_id="buksukjai",
        public_base_url=public_base_url,
        allow_inactive=True,
    )
    if not delivered_ok:
        logger.warning(
            "Parcel notification delivery failed (stage=%s, platform=%s, psid=%s, order=%s)",
            stage,
            user.platform,
            psid,
            order_id,
        )
        return None

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
        meta_kwargs["after_sales_stage"] = max(user.after_sales_stage or 0, 1)

    database.update_session_meta(**meta_kwargs)
    return {
        "psid": psid,
        "platform": user.platform,
        "customer_name": user.customer_name,
        "order_id": order_id,
        "tracking_no": tracking_no,
        "courier_name": courier_name,
        "stage": stage,
        "pattern_idx": pat_idx,
        "delivered_hhmm": delivered_hhmm,
        "bubbles": bubbles,
    }


async def check_and_send_parcel_tracking_updates(
    public_base_url: str = "",
    min_order_date: str | None = None,
    dry_run: bool = False,
    ignore_time_window: bool = False,
    fb_sync_limit: int = 150,
) -> dict[str, Any]:
    """Scan recent JST ERP orders for ข้าวบุกสุขใจ, check live courier pickup & delivery status,
    and notify customers on Facebook Messenger & LINE OA strictly within 09:00–20:00 Bangkok time.
    """
    page_cfg = get_page_by_brand_id("buksukjai")
    if not page_cfg.get("parcel_tracking_enabled", True) and not dry_run:
        return {"status": "disabled_by_page_config", "sent_stage1": [], "sent_stage2": []}

    state = get_tracking_state()
    if not state.get("auto_enabled", True) and not dry_run:
        return {"status": "disabled", "sent_stage1": [], "sent_stage2": []}

    now_bkk = _now_bkk()
    now_bkk_str = now_bkk.strftime("%Y-%m-%d %H:%M:%S")
    today_bkk_str = now_bkk.strftime("%Y-%m-%d")

    in_window, window_label = is_within_send_window(now_bkk, state)
    if not in_window and not dry_run and not ignore_time_window:
        return {
            "status": "outside_send_window",
            "bkk_time": now_bkk_str,
            "allowed_window_bkk": window_label,
            "sent_stage1": [],
            "sent_stage2": [],
        }

    # Sync recent Facebook Messenger conversations so customer phones & manual admin messages are fresh!
    effective_fb_limit = fb_sync_limit
    if state.get("last_full_fb_sync_date") != today_bkk_str:
        effective_fb_limit = max(effective_fb_limit, 250)
    if effective_fb_limit > 0:
        try:
            await messenger.sync_recent_facebook_conversations(
                brand_id="buksukjai",
                limit=effective_fb_limit,
                allow_inactive=True,
            )
            if not dry_run and effective_fb_limit >= 250:
                state["last_full_fb_sync_date"] = today_bkk_str
        except Exception as exc:
            logger.warning("FB conversation sync before parcel scan warning: %s", exc)

    cutoff_date = (min_order_date or state.get("min_order_date") or "2026-11-19").strip()
    baseline_delivered_before = str(state.get("baseline_delivered_before") or "2026-11-21 22:00:00").strip()
    max_pickup_age_h = float(state.get("max_pickup_age_hours", 36.0))
    max_delivery_age_h = float(state.get("max_delivery_age_hours", 20.0))

    try:
        order_rows = await asyncio.to_thread(_query_recent_jst_orders, 150)
    except Exception as exc:
        logger.warning("Failed to query JST ERP orders for parcel tracking: %s", exc)
        return {"status": "error", "message": str(exc), "sent_stage1": [], "sent_stage2": []}

    order_id_to_psid, phone_to_psid, name_to_psid = await asyncio.to_thread(_build_session_lookup_maps, state)

    sent_stage1: list[dict[str, Any]] = []
    sent_stage2: list[dict[str, Any]] = []
    checked_orders: list[dict[str, Any]] = []
    unmatched_orders: list[dict[str, Any]] = []
    orders_state: dict[str, Any] = state.setdefault("orders", {})
    seen_psid_date: set[tuple[str, str]] = set()
    dry_deck_state: dict[str, Any] = {
        "deck_stage1": list(state.get("deck_stage1") or []),
        "deck_stage2": list(state.get("deck_stage2") or []),
        "last_stage1_idx": int(state.get("last_stage1_idx", -1)),
        "last_stage2_idx": int(state.get("last_stage2_idx", -1)),
    }
    state_dirty = False

    for row in order_rows:
        order_id = str(row.get("OrderId") or "").strip()
        order_time = str(row.get("OrderTime") or "").strip()
        if not order_id or order_time < cutoff_date:
            continue

        status_disp = str(row.get("StatusDisplay") or "")
        if "ยกเลิก" in status_disp or "Cancel" in str(row.get("Status") or ""):
            continue

        if not _is_eligible_buksukjai_chat_order(row):
            continue

        tracking_no = str(row.get("LogisticsTrackingNumber") or "").strip()
        if not tracking_no:
            continue

        phone = jst_erp.normalize_thai_phone(str(row.get("ReceiverMobileEn") or ""))
        remark = str(row.get("SellerRemark") or "").strip()
        rec_name = str(row.get("ReceiverName") or "").strip()

        psid = order_id_to_psid.get(order_id) or (phone_to_psid.get(phone) if phone else None)
        if not psid and remark.startswith(("FB:", "LINE:")):
            psid = name_to_psid.get(_norm_name(remark.split(":", 1)[1]))
        if not psid and rec_name:
            psid = name_to_psid.get(_norm_name(rec_name))

        if not psid:
            unmatched_orders.append(
                {
                    "order_id": order_id,
                    "order_time": order_time,
                    "receiver_name": rec_name,
                    "phone": phone,
                    "tracking_no": tracking_no,
                    "logistics_status": str(row.get("LogisticsStatus") or ""),
                }
            )
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
        pickup_time = info["pickup_time"]
        delivered_time = info["delivered_time"]
        delivered_hhmm = info["delivered_hhmm"]

        user_obj = database.get_or_create_session(psid)
        ord_record = {
            "order_id": order_id,
            "order_time": order_time,
            "tracking_no": tracking_no,
            "courier_name": courier_name,
            "psid": psid,
            "platform": user_obj.platform,
            "customer_name": user_obj.customer_name,
            "receiver_name": rec_name,
            "phone": phone,
            "is_picked_up": is_picked_up,
            "pickup_time": pickup_time,
            "is_delivered": is_delivered,
            "delivered_time": delivered_time,
            "delivered_hhmm": delivered_hhmm,
            "stage1_pickup_sent_at": saved_ord.get("stage1_pickup_sent_at", ""),
            "stage2_delivered_sent_at": saved_ord.get("stage2_delivered_sent_at", ""),
        }

        # Guard against pre-activation historical deliveries
        if is_delivered and delivered_time and delivered_time <= baseline_delivered_before:
            if not ord_record["stage2_delivered_sent_at"]:
                ord_record["stage2_delivered_sent_at"] = "baseline_pre_activation"
                if not ord_record["stage1_pickup_sent_at"]:
                    ord_record["stage1_pickup_sent_at"] = "baseline_pre_activation"
                orders_state[order_id] = ord_record
                state_dirty = True
            checked_orders.append({**ord_record, "action": "skipped_pre_activation_delivery"})
            continue

        if is_delivered:
            # Check freshness of delivery event
            deliv_dt = _parse_bkk_dt(delivered_time)
            deliv_age_h = ((now_bkk - deliv_dt).total_seconds() / 3600.0) if deliv_dt else 0.0
            if deliv_dt and deliv_age_h > max_delivery_age_h:
                ord_record["stage2_delivered_sent_at"] = "skipped_stale_delivery"
                orders_state[order_id] = ord_record
                state_dirty = True
                checked_orders.append({**ord_record, "action": f"skipped_stale_delivery_{deliv_age_h:.1f}h"})
                continue

            already_s2 = bool(ord_record["stage2_delivered_sent_at"]) or _has_already_sent_in_chat(
                psid, tracking_no, 2
            )
            if not already_s2:
                if dry_run:
                    preview_msg, pat_idx = build_stage2_delivered_message(
                        courier_name, tracking_no, delivered_hhmm, state=dry_deck_state
                    )
                    sent_stage2.append(
                        {
                            **ord_record,
                            "dry_run": True,
                            "pattern_idx": pat_idx,
                            "preview_message": preview_msg,
                        }
                    )
                else:
                    res2 = await _send_tracking_notification(
                        psid=psid,
                        stage=2,
                        order_id=order_id,
                        courier_name=courier_name,
                        tracking_no=tracking_no,
                        state=state,
                        delivered_hhmm=delivered_hhmm,
                        public_base_url=public_base_url,
                    )
                    if res2:
                        ord_record["stage2_delivered_sent_at"] = now_bkk_str
                        if not ord_record["stage1_pickup_sent_at"]:
                            ord_record["stage1_pickup_sent_at"] = now_bkk_str
                        sent_stage2.append(res2)
                        state_dirty = True
            else:
                if not ord_record["stage2_delivered_sent_at"]:
                    ord_record["stage2_delivered_sent_at"] = "already_in_chat"
                    state_dirty = True

        elif is_picked_up:
            pickup_dt = _parse_bkk_dt(pickup_time)
            pickup_age_h = ((now_bkk - pickup_dt).total_seconds() / 3600.0) if pickup_dt else 0.0
            if pickup_dt and pickup_age_h > max_pickup_age_h:
                if not ord_record["stage1_pickup_sent_at"]:
                    ord_record["stage1_pickup_sent_at"] = "skipped_stale_pickup"
                    orders_state[order_id] = ord_record
                    state_dirty = True
                checked_orders.append({**ord_record, "action": f"skipped_stale_pickup_{pickup_age_h:.1f}h_waiting_for_delivery"})
                continue

            already_s1 = bool(ord_record["stage1_pickup_sent_at"]) or _has_already_sent_in_chat(
                psid, tracking_no, 1
            )
            if not already_s1:
                if dry_run:
                    preview_msg, pat_idx = build_stage1_pickup_message(
                        courier_name, tracking_no, state=dry_deck_state
                    )
                    sent_stage1.append(
                        {
                            **ord_record,
                            "dry_run": True,
                            "pattern_idx": pat_idx,
                            "preview_message": preview_msg,
                        }
                    )
                else:
                    res1 = await _send_tracking_notification(
                        psid=psid,
                        stage=1,
                        order_id=order_id,
                        courier_name=courier_name,
                        tracking_no=tracking_no,
                        state=state,
                        public_base_url=public_base_url,
                    )
                    if res1:
                        ord_record["stage1_pickup_sent_at"] = now_bkk_str
                        sent_stage1.append(res1)
                        state_dirty = True
            else:
                if not ord_record["stage1_pickup_sent_at"]:
                    ord_record["stage1_pickup_sent_at"] = "already_in_chat"
                    state_dirty = True

        orders_state[order_id] = ord_record
        checked_orders.append(ord_record)

    if not dry_run:
        state["last_scan_at"] = now_bkk_str
        save_tracking_state(state, touch_updated_at=bool(state_dirty or sent_stage1 or sent_stage2))
        if sent_stage1 or sent_stage2:
            try:
                database.save_persistent_snapshot()
            except Exception:
                pass

    return {
        "status": "ok",
        "dry_run": dry_run,
        "bkk_time": now_bkk_str,
        "in_send_window": in_window,
        "allowed_window_bkk": window_label,
        "checked_count": len(checked_orders),
        "unmatched_count": len(unmatched_orders),
        "sent_stage1_count": len(sent_stage1),
        "sent_stage2_count": len(sent_stage2),
        "sent_stage1": sent_stage1,
        "sent_stage2": sent_stage2,
        "checked_orders": checked_orders,
        "unmatched_orders": unmatched_orders[:20],
    }


def lookup_customer_tracking_for_chat(psid: str, user_text: str = "") -> dict[str, Any] | None:
    """Look up live tracking status for a customer asking in chat (used only when AI chat is active)."""
    try:
        user_obj = database.get_or_create_session(psid)
        notes = user_obj.notes or ""
        cust_name = (user_obj.customer_name or "").strip()

        clean_txt = jst_erp.translate_thai_numerals(user_text or "")
        explicit_tno_m = re.search(r"\b(8\d{11}|6\d{11}|TH\w{9,14})\b", clean_txt, re.I)
        explicit_tno = explicit_tno_m.group(1).strip() if explicit_tno_m else ""

        oid_matches = re.findall(r"#(?:JST_ORDER:)?(\d{6,10})", notes)
        saved_prof = jst_erp.get_saved_customer_address_profile(psid)
        target_phone = saved_prof["phone"] if saved_prof else ""

        rows = _query_recent_jst_orders(page_size=120)
        matched_row: dict[str, Any] | None = None

        for r in rows:
            if not _is_eligible_buksukjai_chat_order(r):
                continue
            tno = str(r.get("LogisticsTrackingNumber") or "").strip()
            oid = str(r.get("OrderId") or "").strip()
            r_ph = jst_erp.normalize_thai_phone(str(r.get("ReceiverMobileEn") or ""))
            r_name = str(r.get("ReceiverName") or "").strip()
            remark = str(r.get("SellerRemark") or "").strip()

            if explicit_tno and tno == explicit_tno:
                matched_row = r
                break
            if oid and oid in oid_matches:
                matched_row = r
                break
            if target_phone and r_ph == target_phone:
                matched_row = r
                break
            if cust_name and len(cust_name) >= 3 and (
                cust_name.lower() in r_name.lower() or cust_name.lower() in remark.lower()
            ):
                matched_row = r
                break

        if not matched_row:
            return None

        info = inspect_order_tracking_status(matched_row)
        tracking_no = info["tracking_no"]
        courier_name = info["courier_name"]
        events = info.get("events") or []

        if info["is_delivered"]:
            hhmm_txt = f" เวลา {info['delivered_hhmm']} น." if info.get("delivered_hhmm") else ""
            reply_msg = (
                f"ตรวจสอบสถานะพัสดุให้เรียบร้อยแล้วค่ะ 🚚💚\n"
                f"• ขนส่ง: {courier_name}\n"
                f"• เลขพัสดุ: {tracking_no}\n"
                f"• สถานะล่าสุด: จัดส่งสำเร็จแล้วค่ะ{hhmm_txt} 🙏✨"
            )
        elif info["is_picked_up"] and events:
            latest_ev = events[0]
            ev_time = str(latest_ev.get("OperationTime") or "")[:16]
            ev_desc = str(latest_ev.get("Description") or "อยู่ระหว่างการจัดส่ง").strip()
            reply_msg = (
                f"ตรวจสอบสถานะพัสดุให้เรียบร้อยแล้วค่ะ 🚚💚\n"
                f"• ขนส่ง: {courier_name}\n"
                f"• เลขพัสดุ: {tracking_no}\n"
                f"• สถานะล่าสุด ({ev_time}): {ev_desc} 😊🙏"
            )
        else:
            reply_msg = (
                f"ตรวจสอบเลขพัสดุ {tracking_no} ({courier_name}) เรียบร้อยค่ะ 📦💚\n"
                f"ทางคลังแพ็กสินค้าออกใบปะหน้าแล้ว\n"
                f"อยู่ระหว่างรอรถขนส่งสแกนรับเข้าระบบนะคะ 😊🙏"
            )

        return {
            "found": True,
            "tracking_no": tracking_no,
            "courier_name": courier_name,
            "is_picked_up": info["is_picked_up"],
            "is_delivered": info["is_delivered"],
            "reply_message": reply_msg,
        }
    except Exception as exc:
        logger.warning("lookup_customer_tracking_for_chat failed for %s: %s", psid, exc)
        return None
