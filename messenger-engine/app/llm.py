"""AI Processing Engine — Supports Google Gemini (gemini-2.5-flash / gemini-2.0-flash)
AND OpenAI (gpt-4o-mini / gpt-4o) automatically based on the API key prefix!

- If the key starts with `AIza...` or `AQ....` (or GEMINI_API_KEY is set) -> Uses Google Gemini API
- If the key starts with `sk-...` (or OPENAI_API_KEY is set) -> Uses OpenAI API
- If no key is set -> Runs in Smart Brand Demo Mode for ข้าวบุกสุขใจ
"""

import json
import logging
import os
import re

import openai

from .prompt_engine import IMAGE_KEYS, ORDER_STATES

logger = logging.getLogger(__name__)

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

RESPONSE_SCHEMA = {
    "name": "messenger_reply",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "reply": {
                "type": "string",
                "description": (
                    "Short, cute, natural Thai chat reply. Separate 2-3 short message bubbles "
                    "using '|||'. Never use asterisks (* or **). Space out bullet items with blank lines."
                ),
            },
            "state": {
                "type": "string",
                "enum": ORDER_STATES,
                "description": "The customer's order state after this reply.",
            },
            "image_key": {
                "type": "string",
                "enum": IMAGE_KEYS,
                "description": (
                    "Official brand promo image to send with the reply: ALWAYS use 'promo_all' (sends all 4 promo images at once) "
                    "whenever customer says 'สนใจ', asks for price, sizes, or promotions; "
                    "'promo_60g_set' only if asking specifically about 60g pouches; 'promo_899' only if asking specifically about 899.-; "
                    "'promo_1299' only if asking specifically about 1299.-; or 'none' otherwise."
                ),
            },
        },
        "required": ["reply", "state", "image_key"],
        "additionalProperties": False,
    },
}


def clean_chat_text(text: str) -> str:
    """Strip all Markdown asterisks (* / **), enforce female polite particles (ค่ะ/คะ/นะคะ), and ensure airy spacing."""
    if not text:
        return ""
    # 1. Remove Markdown bold/italic/code markers (**bold**, __bold__, `code`)
    cleaned = text.replace("**", "").replace("__", "").replace("`", "")
    # 2. Convert leading * or - bullets on any line into "• "
    cleaned = re.sub(r"(?m)^\s*[\*\-]\s+", "• ", cleaned)
    # 3. Remove any stray single asterisks left around words
    cleaned = cleaned.replace("*", "")
    # 4. Enforce female polite particles (never allow ครับ / นะครับ / คับ)
    cleaned = cleaned.replace("นะครับ", "นะคะ").replace("ครับผม", "ค่ะ")
    cleaned = re.sub(r"(ไหม|มั้ย|ดี|ไหน|อะไร|เท่าไหร่|กี่บาท|ยังไง|อย่างไร|หรือเปล่า|รึเปล่า)\s*ครับ", r"\1คะ", cleaned)
    cleaned = cleaned.replace("ครับ", "ค่ะ").replace("คับ", "ค่ะ")

    # 5. Ensure consecutive bullet lines (• ...) have a blank line between them so they aren't squished
    raw_lines = [line.strip() for line in cleaned.splitlines()]
    spaced_lines: list[str] = []
    for line in raw_lines:
        if not line:
            if spaced_lines and spaced_lines[-1] != "":
                spaced_lines.append("")
            continue
        if line.startswith("•") and spaced_lines and spaced_lines[-1] != "":
            spaced_lines.append("")
        spaced_lines.append(line)

    result = "\n".join(spaced_lines).strip()
    # Collapse 3+ newlines into 2 newlines
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result


def split_into_bubbles(text: str, max_bubbles: int = 4) -> list[str]:
    """Split a reply into short, natural Thai chat bubbles.

    Strictly isolates any `#BUY<amount>` tag (e.g. `#BUY399`, `#BUY459`) into its own
    standalone bubble with zero surrounding text so ROI Tracking captures it cleanly.
    """
    if not text:
        return []

    if "|||" in text:
        raw_parts = [p.strip() for p in text.split("|||") if p.strip()]
    else:
        # Fallback if the model didn't use |||: keep bullet blocks together, split intro/outro paragraphs
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        if len(paragraphs) <= 1:
            raw_parts = [text.strip()]
        else:
            raw_parts = []
            bullet_buf: list[str] = []
            for p in paragraphs:
                if p.startswith(("•", "*", "-", "📌", "1.", "2.", "3.", "1️⃣", "2️⃣", "3️⃣", "💰")):
                    bullet_buf.append(p)
                else:
                    if bullet_buf:
                        raw_parts.append("\n\n".join(bullet_buf))
                        bullet_buf = []
                    raw_parts.append(p)
            if bullet_buf:
                raw_parts.append("\n\n".join(bullet_buf))

    isolated_bubbles: list[str] = []
    seen_buy_tag: str | None = None
    for part in raw_parts:
        buy_matches = re.findall(r"#BUY\s*([\d,]+)", part, flags=re.IGNORECASE)
        clean_part = re.sub(r"#BUY\s*[\d,]+", "", part, flags=re.IGNORECASE).strip()
        cleaned_txt = clean_chat_text(clean_part)
        if cleaned_txt:
            isolated_bubbles.append(cleaned_txt)
        for bm in buy_matches:
            digits = bm.replace(",", "").strip()
            if digits.isdigit() and int(digits) > 0:
                seen_buy_tag = f"#BUY{int(digits)}"

    if not isolated_bubbles and not seen_buy_tag:
        return [clean_chat_text(text)]

    if len(isolated_bubbles) > max_bubbles:
        isolated_bubbles = isolated_bubbles[: max_bubbles - 1] + [
            "\n\n".join(isolated_bubbles[max_bubbles - 1 :])
        ]

    if seen_buy_tag:
        # Place the standalone #BUY<amount> bubble right before the final thank-you bubble (or at the end if 1 bubble)
        if len(isolated_bubbles) >= 2:
            isolated_bubbles.insert(len(isolated_bubbles) - 1, seen_buy_tag)
        else:
            isolated_bubbles.append(seen_buy_tag)

    return isolated_bubbles


def _get_official_payment_info(config: dict | None = None) -> dict:
    cfg = config or {}
    brand_id = cfg.get("brand_id", "buksukjai")
    pay = cfg.get("payment_info")
    if pay and pay.get("account_number"):
        return pay
    if brand_id == "mrbuk":
        return {
            "bank_name": "ธนาคารกสิกรไทย",
            "account_name": "บจก. ทูเคพี อิควิปเม้นท์",
            "account_number": "989-2-13624-3",
            "account_number_raw": "9892136243",
            "formatted_block": (
                "โอนเงินบัญชี 🫶🏻\n"
                "ธนาคารกสิกรไทย\n"
                "บจก. ทูเคพี อิควิปเม้นท์\n"
                "เลขที่บัญชี 989-2-13624-3"
            ),
        }
    return {
        "bank_name": "ธนาคารไทยพาณิชย์ จำกัด (มหาชน) / สาขา สำโรง",
        "account_name": "บริษัท ดิจิสท์ ฮับ จำกัด",
        "account_number": "304-407545-5",
        "account_number_raw": "3044075455",
        "formatted_block": (
            "Account Name: บริษัท ดิจิสท์ ฮับ จำกัด\n"
            "ธนาคาร : ธนาคารไทยพาณิชย์ จำกัด (มหาชน) / สาขา สำโรง\n"
            "Account Number / เลขที่บัญชี : 304-407545-5"
        ),
    }


def enforce_authentic_bank_account(bubbles: list[str], history: list[dict], config: dict | None = None) -> list[str]:
    """Hard guardrail:
    1) Never allow hallucinated bank names or fake account numbers (e.g. 043-1-X007X, บริษัท สุขใจ จำกัด).
    2) Always include the authentic bank account block + raw copyable digits when the customer asks for
       a bank account or chooses bank transfer.
    """
    pay = _get_official_payment_info(config)
    acct_num = pay["account_number"]
    acct_raw = pay["account_number_raw"]
    official_block = pay.get("formatted_block") or (
        f"Account Name: {pay['account_name']}\n"
        f"ธนาคาร : {pay['bank_name']}\n"
        f"Account Number / เลขที่บัญชี : {acct_num}"
    )
    brand_id = (config or {}).get("brand_id", "buksukjai")

    fake_markers = ("043-1", "x007x", "สุขใจ จำกัด", "xxx-", "123-4", "เลขบัญชีสมมติ")
    wrong_banks_for_buksukjai = ("กสิกร", "กรุงไทย", "กรุงเทพ", "กรุงศรี", "ออมสิน", "ทหารไทย")

    cleaned_bubbles: list[str] = []
    replaced_fake = False

    for b in bubbles:
        b_low = b.lower()
        has_fake_marker = any(fm in b_low for fm in fake_markers)
        has_wrong_bank = (
            brand_id == "buksukjai"
            and any(wb in b for wb in wrong_banks_for_buksukjai)
            and any(k in b for k in ("บัญชี", "ธนาคาร", "โอน", "เลข"))
        )
        # Check for any dashed bank account number that is not the official one
        dashed_numbers = re.findall(r"\b\d{3}-\d{1,6}-\d{1,5}(?:-\d)?\b", b)
        has_wrong_dashed = any(
            dn != acct_num and not dn.startswith(("08", "09", "06", "02"))
            for dn in dashed_numbers
        )

        if has_fake_marker or has_wrong_bank or has_wrong_dashed:
            if not replaced_fake:
                cleaned_bubbles.append(official_block)
                cleaned_bubbles.append(acct_raw)
                replaced_fake = True
            continue
        cleaned_bubbles.append(b)

    # Check if customer explicitly asked for bank account or chose bank transfer
    user_text = (history[-1].get("content") or "").strip() if history else ""
    u_low = user_text.lower()
    already_paid = any(w in u_low for w in ("โอนแล้ว", "จ่ายแล้ว", "ชำระแล้ว", "ส่งสลิป", "แนบสลิป", "โอนพรุ่งนี้"))
    asked_account = any(
        w in u_low
        for w in (
            "ขอเลขบัญชี",
            "ขอบัญชี",
            "ขอ บช",
            "ขอบช",
            "เลขบัญชี",
            "เลขที่บัญชี",
            "เลข บช",
            "เบอร์บัญชี",
            "โอนเข้าบัญชีไหน",
            "พร้อมเพย์",
        )
    )
    chose_transfer = (
        not already_paid
        and len(user_text) <= 45
        and any(
            w in u_low
            for w in (
                "โอนค่ะ",
                "โอนคะ",
                "โอนครับ",
                "โอนจ้า",
                "โอนนะ",
                "โอนเงิน",
                "แบบโอน",
                "ชำระแบบโอน",
                "จ่ายโอน",
            )
        )
    ) or u_low in ("โอน", "บช", "เลขบช")

    combined_out = "\n".join(cleaned_bubbles)
    if (asked_account or chose_transfer) and acct_num not in combined_out and acct_raw not in combined_out:
        # Insert official bank account + raw digits before the final closing bubble if multiple bubbles exist
        if len(cleaned_bubbles) >= 2:
            cleaned_bubbles = cleaned_bubbles[:-1] + [official_block, acct_raw, cleaned_bubbles[-1]]
        else:
            cleaned_bubbles.extend([official_block, acct_raw])

    return cleaned_bubbles


FULL_PROMO_SUMMARY_BUBBLE = (
    "📌 รวมโปรโมชั่นพิเศษ ข้าวบุกสุขใจ (ครบทุกขนาด) ค่ะ\n\n"
    "• ซองเล็ก 60 กรัม (ไซส์ทดลอง 1 มื้อ) = โปร 39 บาท\n\n"
    "• ถุงกลาง 500 กรัม (ทานประจำ 8–10 มื้อ) = โปร 239 บาท\n\n"
    "• ถุงใหญ่ 1 กก. (ขายดีอันดับ 1 ทานได้ 16–20 มื้อ) = โปร 459 บาท (โอนส่งฟรี! 🔥)\n\n"
    "• เซ็ตพกพา 15 ซอง (60g × 15 ซอง) = โปร 555 บาท (ส่งฟรี!)\n\n"
    "• เซ็ตพกพา 20 ซอง (60g × 20 ซอง) = โปร 720 บาท (ส่งฟรี!)\n\n"
    "• โปรตุน 2 แถม 2 (1 กก. 2 ถุง + แถมฟรี 60g 2 ซอง) = โปร 899 บาท (ส่งฟรี!)\n\n"
    "• โปรตุน 3 แถม 3 (1 กก. 3 ถุง + แถมฟรี 60g 3 ซอง) = โปร 1,299 บาท (ส่งฟรี!)"
)


def enforce_all_promotions_when_asked(
    bubbles: list[str],
    history: list[dict],
    image_key: str,
) -> tuple[list[str], str]:
    """Ensure that whenever a customer asks about price / promotions / sizes / 'สนใจ',
    we send ALL 4 promo images ('promo_all') AND all 7 promo tiers in a single turn.
    """
    user_text = (history[-1].get("content") or "").strip() if history else ""
    u_low = user_text.lower()

    # Do not inject full promo menu if this is an after-sales system prompt or customer is confirming/paying
    if "[ข้อมูลสำคัญจากระบบ: ลูกค้าท่านนี้ได้สั่งซื้อ" in user_text:
        return bubbles, "none"

    non_promo_intents = (
        "โอนแล้ว", "จ่ายแล้ว", "ชำระแล้ว", "ส่งสลิป", "แนบสลิป", "ยืนยัน", "คอนเฟิร์ม",
        "ขอเลขบัญชี", "ขอบัญชี", "ขอ บช", "เลขบัญชี", "เลขที่บัญชี", "อย.", "เลข อย",
    )
    if any(w in u_low for w in non_promo_intents):
        return bubbles, image_key

    # Check if customer is placing a specific order already (e.g. "เอา 1 กิโล", "สั่งเซ็ต 899", "รับ 500g")
    specific_order_words = ("เอา ", "รับ ", "สั่ง ", "สั่งซื้อ ", "เอาขนาด", "รับขนาด", "รับเซ็ต", "เอาโปร")
    is_specific_order = any(w in u_low for w in specific_order_words) and any(
        sz in u_low for sz in ("60", "39", "500", "239", "1 กิโล", "1 กก", "1kg", "459", "555", "720", "899", "1299", "1,299", "2 แถม 2", "3 แถม 3")
    )
    if is_specific_order:
        return bubbles, image_key

    general_promo_triggers = (
        "สนใจ", "ราคา", "ขอราคา", "กี่บาท", "เท่าไหร่", "โปร", "มีโปร", "ดูโปร",
        "มีขนาด", "ขนาดไหน", "ไซส์ไหน", "ขายยังไง", "ถุงละ", "ซองละ", "สั่งซื้อยังไง",
    )
    asked_general_promo = any(w in u_low for w in general_promo_triggers) or image_key in ("promo_3sizes", "promo_all")

    if not asked_general_promo:
        return bubbles, image_key

    # Always upgrade to promo_all so all 4 official promo images are sent together
    new_image_key = "promo_all"

    combined = "\n".join(bubbles)
    required_tiers = ("39", "239", "459", "555", "720", "899", "1,299")
    tier_hits = sum(1 for t in required_tiers if t in combined or t.replace(",", "") in combined)

    if tier_hits < 5:
        intro = "สวัสดีค่า 🍚✨ ข้าวบุกสุขใจ (บุก 59% ผสมข้าวหอมมะลิ 29% และน้ำ 12% เพียง 23 kcal เติมน้ำร้อน 10 นาทีพร้อมทาน) น้องบุกส่งรูปและโปรโมชั่นทั้งหมดให้เลือกครบทุกชุดเลยนะคะ"
        outro = "🚚 สั่งครบ 1 กก. หรือเซ็ตโปร โอนเงินส่งฟรีเลยค่ะ (เก็บปลายทาง +40 บาท / ต่ำกว่า 1 กก. โอน +30 ปลายทาง +70 บาท) คุณลูกค้าสนใจรับโปรไหนดีคะ 😊💚"
        if not bubbles:
            bubbles = [intro, FULL_PROMO_SUMMARY_BUBBLE, outro]
        elif len(bubbles) == 1:
            bubbles = [bubbles[0], FULL_PROMO_SUMMARY_BUBBLE, outro]
        else:
            # Keep the first greeting/answer bubble, replace partial price list with full promo list, keep closing question
            bubbles = [bubbles[0], FULL_PROMO_SUMMARY_BUBBLE, bubbles[-1] if "สนใจ" in bubbles[-1] or "ดีคะ" in bubbles[-1] else outro]

    return bubbles, new_image_key


class LLMEngine:
    def __init__(self, system_prompt: str, config: dict | None = None):
        self.system_prompt = system_prompt
        self.config = config or {}
        self.provider = "demo"
        self.active_model = "smart-demo"
        self.refresh_client()

    def refresh_client(self) -> None:
        gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
        openai_key = os.getenv("OPENAI_API_KEY", "").strip()

        # Auto-detect if user pasted a Gemini key (`AIza...` or `AQ....`) into OPENAI_API_KEY
        if (openai_key.startswith("AIza") or openai_key.startswith("AQ.")) and not gemini_key:
            gemini_key = openai_key

        if gemini_key:
            self.mock_mode = False
            self.provider = "gemini"
            self.active_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
            self.client = openai.AsyncOpenAI(
                api_key=gemini_key,
                base_url=GEMINI_BASE_URL,
            )
            logger.info("LLM Engine initialized with Google Gemini (%s)", self.active_model)
        elif openai_key:
            self.mock_mode = False
            self.provider = "openai"
            self.active_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
            self.client = openai.AsyncOpenAI(api_key=openai_key)
            logger.info("LLM Engine initialized with OpenAI (%s)", self.active_model)
        else:
            self.mock_mode = True
            self.provider = "demo"
            self.active_model = "smart-demo"
            self.client = None
            logger.info("No API key set — running in Smart Brand Demo Mode")

    def get_status_label(self) -> str:
        if self.provider == "gemini":
            return f"Google Gemini ({self.active_model}) — เชื่อมต่อ API จริงแล้ว"
        if self.provider == "openai":
            return f"OpenAI ({self.active_model}) — เชื่อมต่อ API จริงแล้ว"
        return "Smart Brand Demo Mode (ทดสอบฟรี — รองรับคีย์ Gemini หรือ OpenAI)"

    def build_request(self, history: list[dict], current_state: str, model_override: str | None = None) -> dict:
        model = model_override or self.active_model
        combined_system_prompt = (
            f"{self.system_prompt}\n\n"
            f"## Current Customer Session State\n"
            f"- Current order state for this customer: {current_state}\n"
            f"- Respond strictly as JSON with keys `reply` (string), `state` "
            f"(\"browsing\", \"pending_payment\", or \"completed\"), and `image_key` "
            f"(\"none\", \"promo_3sizes\", \"promo_60g_set\", \"promo_899\", \"promo_1299\", or \"promo_all\").\n"
            f"- CRITICAL: Keep `reply` short, cute, and concise like a real Thai chat admin. "
            f"Separate 2–3 short message bubbles with `|||`. NEVER use `*` or `**`."
        )
        messages = [{"role": "system", "content": combined_system_prompt}] + history
        req = {
            "model": model,
            "max_tokens": 2048,
            "temperature": 0.4,
            "messages": messages,
            "response_format": {"type": "json_schema", "json_schema": RESPONSE_SCHEMA},
        }
        if self.provider == "gemini":
            req["reasoning_effort"] = "none"
        return req

    async def generate(self, history: list[dict], current_state: str) -> tuple[str, str, str]:
        """Returns (reply_text_with_bubble_delimiters, new_state, image_key)."""
        if self.mock_mode:
            return self._smart_demo_generate(history, current_state)

        models_to_try = [self.active_model]
        if self.provider == "gemini" and "2.5-flash-lite" not in self.active_model:
            models_to_try.append("gemini-2.5-flash-lite")

        for model_name in models_to_try:
            try:
                request = self.build_request(history, current_state, model_override=model_name)
                response = await self.client.chat.completions.create(**request)
                message = response.choices[0].message

                if getattr(message, "refusal", None):
                    logger.warning("Model refused: %s; returning safe fallback reply", message.refusal)
                    return ("ขออภัยค่ะ น้องบุกไม่สามารถตอบคำถามนี้ได้ เดี๋ยวให้แอดมินติดต่อกลับนะคะ 🙏", current_state, "none")

                text = (message.content or "").strip()
                if text.startswith("```"):
                    text = text.strip("`").removeprefix("json").strip()
                data = json.loads(text)
                bubbles = split_into_bubbles(data["reply"])
                bubbles = enforce_authentic_bank_account(bubbles, history, self.config)
                image_key = data.get("image_key") or "none"
                bubbles, image_key = enforce_all_promotions_when_asked(bubbles, history, image_key)
                return "|||".join(bubbles), data["state"], image_key
            except Exception as e:
                logger.warning("Model %s call failed (%s)", model_name, e)
                continue

        logger.error("All LLM calls failed; falling back to Smart Demo responder")
        return self._smart_demo_generate(history, current_state)

    async def extract_order_details(self, history: list[dict]) -> dict:
        """Extract structured order details for Meta ROAS & JST ERP Fulfillment with strict confirmation checks."""
        schema = {
            "name": "extracted_order",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "customer_confirmed": {
                        "type": "boolean",
                        "description": "True ONLY if the customer explicitly confirmed the order after address/total summary (e.g. said ยืนยัน/คอนเฟิร์ม/โอเค or sent transfer slip).",
                    },
                    "recipient_name": {"type": "string"},
                    "phone": {"type": "string"},
                    "address_line": {"type": "string"},
                    "subdistrict": {"type": "string"},
                    "district": {"type": "string"},
                    "province": {"type": "string"},
                    "postal_code": {"type": "string"},
                    "sku": {"type": "string", "description": "SKU code e.g. BSJ60G1, BSJ500G1, BSJ1KG1, BSJ_SET20, BSJ_FAM2, BSJ_BIG3"},
                    "quantity": {"type": "integer"},
                    "item_summary": {"type": "string"},
                    "payment_method": {"type": "string", "enum": ["COD", "TRANSFER", "UNKNOWN"]},
                    "total_amount": {"type": "number", "description": "Grand total in THB including shipping."},
                    "jst_filter_text": {
                        "type": "string",
                        "description": "Single-line Thai string combining Name + Phone + Full Address + Postal Code ready to paste into JST ERP address filter box.",
                    },
                },
                "required": [
                    "customer_confirmed",
                    "recipient_name",
                    "phone",
                    "address_line",
                    "subdistrict",
                    "district",
                    "province",
                    "postal_code",
                    "sku",
                    "quantity",
                    "item_summary",
                    "payment_method",
                    "total_amount",
                    "jst_filter_text",
                ],
                "additionalProperties": False,
            },
        }
        prompt = (
            "สกัดข้อมูลคำสั่งซื้อจากบทสนทนาแชทนี้เพื่อเตรียมคีย์ลงระบบคลังสินค้า JST ERP และส่งยอดขาย ROAS\n"
            "- รหัส SKU ของข้าวบุกสุขใจ: ซองเล็ก 60g = BSJ60G1 (39.-), ถุงกลาง 500g = BSJ500G1 (239.-), "
            "ถุงใหญ่ 1 กก. = BSJ1KG1 (459.-), เซ็ตพกพา 20 ซอง = BSJ_SET20 (720.-), "
            "เซ็ตครอบครัว 2 แถม 2 = BSJ_FAM2 (899.-), เซ็ตใหญ่ 3 แถม 3 = BSJ_BIG3 (1299.-)\n"
            "- ค่าส่ง: ต่ำกว่า 1 กก. โอน 30 / COD 70 | ตั้งแต่ 1 กก. ขึ้นไป โอน 0 (ส่งฟรี) / COD 40\n"
            "- สำคัญมาก: `customer_confirmed` จะเป็น true ได้ก็ต่อเมื่อลูกค้ามีชื่อ+เบอร์โทร+ที่อยู่ครบถ้วน และลูกค้ายืนยันคำสั่งซื้อชัดเจนแล้วเท่านั้น"
        )
        if not self.mock_mode and self.client:
            try:
                req = {
                    "model": self.active_model,
                    "max_tokens": 1024,
                    "temperature": 0.1,
                    "messages": [{"role": "system", "content": prompt}] + history,
                    "response_format": {"type": "json_schema", "json_schema": schema},
                }
                if self.provider == "gemini":
                    req["reasoning_effort"] = "none"
                resp = await self.client.chat.completions.create(**req)
                raw = (resp.choices[0].message.content or "").strip()
                if raw.startswith("```"):
                    raw = raw.strip("`").removeprefix("json").strip()
                return json.loads(raw)
            except Exception as e:
                logger.warning("extract_order_details failed: %s", e)

        return {
            "customer_confirmed": False,
            "recipient_name": "",
            "phone": "",
            "address_line": "",
            "subdistrict": "",
            "district": "",
            "province": "",
            "postal_code": "",
            "sku": "BSJ1KG1",
            "quantity": 1,
            "item_summary": "ข้าวบุกสุขใจ 1 กก.",
            "payment_method": "COD",
            "total_amount": 499,
            "jst_filter_text": "",
        }

    def _smart_demo_generate(self, history: list[dict], current_state: str) -> tuple[str, str, str]:
        """Brand-accurate intelligent responder for local testing before API key is added."""
        user_text = (history[-1]["content"] if history else "").strip()
        low = user_text.lower()

        if "อย." in low or "อย " in low or "เลข อย" in low or "มีอยไหม" in low.replace(" ", ""):
            return (
                "ตอนนี้ทางร้านยังอยู่ระหว่างดำเนินการขอเลข อย. ค่ะคุณลูกค้า "
                "เนื่องจากขั้นตอนขอ อย. ในประเทศไทยใช้ระยะเวลาค่อนข้างนาน "
                "พอได้เลขเรียบร้อยแล้วแอดมินจะรีบมาอัปเดตให้ทราบทันทีเลยนะคะ 🙏",
                current_state,
                "none",
            )

        paid_words = ("โอนแล้ว", "จ่ายแล้ว", "ชำระแล้ว", "ส่งสลิป", "สลิป", "โอนเรียบร้อย")
        if any(w in low for w in paid_words):
            return (
                "ขอบพระคุณมากค่ะคุณลูกค้า 🍚💚|||น้องบุกได้รับแจ้งยอดเรียบร้อยแล้วค่ะ จัดส่งให้ภายใน 3–5 วันทำการเลยนะคะ 🙏✨",
                "completed",
                "none",
            )

        acct_words = ("ขอเลขบัญชี", "ขอบัญชี", "ขอ บช", "เลขบัญชี", "เลขที่บัญชี", "เบอร์บัญชี", "โอนค่ะ", "โอนคะ", "โอนเงิน", "แบบโอน")
        if any(w in low for w in acct_words) or low in ("โอน", "บช"):
            pay = _get_official_payment_info(self.config)
            block = pay.get("formatted_block") or (
                f"Account Name: {pay['account_name']}\n"
                f"ธนาคาร : {pay['bank_name']}\n"
                f"Account Number / เลขที่บัญชี : {pay['account_number']}"
            )
            return (
                f"ได้เลยค่ะคุณลูกค้า 🍚 สามารถโอนชำระได้ที่\n\n{block}|||{pay['account_number_raw']}|||"
                f"เมื่อโอนแล้วรบกวนแจ้งสลิป พร้อมชื่อ-นามสกุล ที่อยู่จัดส่ง และเบอร์โทรให้น้องบุกได้เลยนะคะ 😊🙏",
                "pending_payment",
                "none",
            )

        if current_state == "pending_payment" and any(d in low for d in ("08", "09", "06", "โทร", "จังหวัด", "อำเภอ", "เขต", "ต.", "อ.", "จ.")):
            return (
                "น้องบุกบันทึกชื่อ-ที่อยู่และเบอร์โทรจัดส่งเรียบร้อยแล้วค่ะ 📝💚|||หากข้อมูลถูกต้อง รบกวนพิมพ์คำว่า 'ยืนยัน' เพื่อส่งเข้าคลังจัดส่งได้เลยนะคะ 🙏🍚",
                "pending_payment",
                "none",
            )

        buy_words = ("สั่งซื้อ", "สนใจสั่ง", "รับ 1", "เอา 1", "เอาขนาด", "รับเซ็ต", "สั่ง 1", "สั่งเลย", "รับโปร")
        if any(w in low for w in buy_words):
            if "ครอบครัว" in low or "899" in low or "2 แถม 2" in low:
                item_line = "เซ็ตครอบครัว 2 แถม 2 = 899 บาท"
                total_transfer = "899 บาท (โอนส่งฟรี!)"
                total_cod = "939 บาท (ปลายทาง +40 บาท)"
            elif "1 กิโล" in low or "1 กก" in low or "1kg" in low or "459" in low:
                item_line = "ถุงใหญ่ 1 กก. = 459 บาท"
                total_transfer = "459 บาท (โอนส่งฟรี!)"
                total_cod = "499 บาท (ปลายทาง +40 บาท)"
            elif "500" in low or "239" in low:
                item_line = "ถุงกลาง 500 กรัม = 239 บาท"
                total_transfer = "269 บาท (รวมส่งโอน 30 บาท)"
                total_cod = "309 บาท (รวมส่งปลายทาง 70 บาท)"
            elif "60" in low or "39" in low:
                item_line = "ซองเล็ก 60 กรัม = 39 บาท"
                total_transfer = "69 บาท (รวมส่งโอน 30 บาท)"
                total_cod = "109 บาท (รวมส่งปลายทาง 70 บาท)"
            else:
                item_line = "ถุงใหญ่ 1 กก. = 459 บาท"
                total_transfer = "459 บาท (โอนส่งฟรี!)"
                total_cod = "499 บาท (ปลายทาง +40 บาท)"

            return (
                f"ยินดีเลยค่ะคุณลูกค้า 🍚 สรุปยอดออเดอร์นะคะ\n\n"
                f"• รายการ: {item_line}\n\n"
                f"• โอนเงิน: {total_transfer}\n\n"
                f"• เก็บปลายทาง: {total_cod}|||"
                f"คุณลูกค้าสะดวกรับแบบ โอนเงิน หรือ เก็บปลายทาง ดีคะ แจ้งชื่อ-ที่อยู่และเบอร์โทรไว้ได้เลยนะคะ 😊🙏",
                "pending_payment",
                "none",
            )

        if any(w in low for w in ("ค่าส่ง", "ส่งฟรี", "ปลายทาง", "cod", "จัดส่ง")):
            return (
                "ค่าจัดส่งข้าวบุกสุขใจตามนี้เลยค่ะ 🚚✨\n\n"
                "• โอนเงิน = 30 บาท (สั่งครบ 1 กก. โอนส่งฟรี!)\n\n"
                "• เก็บปลายทาง = 70 บาท (สั่งครบ 1 กก. เหลือแค่ 40 บาท)|||"
                "ถ้าทานประจำ แนะนำถุงใหญ่ 1 กก. 459 บาท (โอนส่งฟรี) คุ้มมากเลยค่ะ สนใจรับไซส์ไหนดีคะ 😊🍚",
                current_state,
                "none",
            )

        if any(w in low for w in ("วิธีหุง", "หุงยังไง", "ต้มไหม", "วิธีทำ", "วิธีทาน", "กินยังไง", "หม้อหุงข้าว")):
            return (
                "ข้าวบุกสุขใจ ไม่ต้องหุง ไม่ต้องใช้หม้อหุงข้าวเลยค่า 🍚✨|||"
                "ทำง่ายๆ แค่ 3 ขั้นตอน 'ตัก-เติม-รอ'\n\n"
                "1. ตักข้าวบุกใส่ชาม\n\n"
                "2. เติมน้ำร้อนจัด (ข้าว 1 ส่วน : น้ำร้อน 1.2–1.5 ส่วน)\n\n"
                "3. ปิดฝารอ 10–15 นาที ข้าวพองนุ่มพร้อมทานเลยค่ะ|||"
                "สนใจลองซองเล็ก 60 กรัม (39 บาท) หรือถุงใหญ่ 1 กก. (459 บาท โอนส่งฟรี) ดีคะ 😊",
                current_state,
                "how_to_cook",
            )

        return (
            "ข้าวบุกสุขใจ มีให้เลือกหลายขนาดเลยค่า 🍚✨|||"
            "📌 โปรโมชั่นพิเศษตอนนี้ค่ะ\n\n"
            "• ซองเล็ก 60 กรัม = 39 บาท (ไซส์ทดลอง)\n\n"
            "• ถุงกลาง 500 กรัม = 239 บาท\n\n"
            "• ถุงใหญ่ 1 กก. = 459 บาท (โอนส่งฟรี! 🔥)\n\n"
            "• เซ็ตพกพา 15 ซอง = 555 บาท (ส่งฟรี!)\n\n"
            "• เซ็ตพกพา 20 ซอง = 720 บาท (ส่งฟรี!)\n\n"
            "• โปรตุน 2 แถม 2 = 899 บาท (ส่งฟรี!)\n\n"
            "• โปรตุน 3 แถม 3 = 1,299 บาท (ส่งฟรี!)|||"
            "คุณลูกค้าสนใจลองไซส์ไหนก่อนดีคะ เดี๋ยวน้องบุกดูโปรให้เลยค่า 😊💚",
            current_state,
            "promo_all",
        )
