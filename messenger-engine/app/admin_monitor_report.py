"""3-Page Admin QA & Sales Conversion Monitor (`พุดดิ้ง🍮 @346zyzej`).

Provides:
1. Web Dashboard (`/admin-report`) styled after the 3-Page Admin Report (`Mr.Buk`, `ข้าวบุกหอมมะลิ (เพจ 2)`, `ข้าวบุก สุขใจ`).
2. Concise LINE Group Summary + Dashboard Link sent via `พุดดิ้ง🍮 (@346zyzej)` (`coachbot`).
3. Strict Single-Group Lock (`Cf0c8835b5b0711e80f7350ffc9af66f1` `กลุ่ม Comment` for testing -> switchable to `กลุ่มคุณพลอย`) and 01:00 AM daily schedule.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi.responses import HTMLResponse

from .config_loader import get_page_by_brand_id

logger = logging.getLogger(__name__)

BKK_TZ = timezone(timedelta(hours=7))
COMMENT_TEST_GROUP_ID = "Cf0c8835b5b0711e80f7350ffc9af66f1"
ADMIN_REPORT_STATE_FILE = Path(__file__).resolve().parent.parent / "admin_report_state.json"


def load_admin_report_state() -> dict[str, Any]:
    if ADMIN_REPORT_STATE_FILE.exists():
        try:
            return json.loads(ADMIN_REPORT_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "target_group_id": COMMENT_TEST_GROUP_ID,
        "target_group_name": "Comment (ห้องทดสอบก่อนย้ายเข้ากลุ่มจริง)",
        "last_1am_report_date": "",
        "last_sent_at": "",
    }


def save_admin_report_state(state: dict[str, Any]) -> None:
    try:
        ADMIN_REPORT_STATE_FILE.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("Could not save admin_report_state.json: %s", exc)


def format_pudding_line_summary(public_base_url: str = "") -> str:
    """Concise, human-readable LINE summary sent by พุดดิ้ง🍮 (@346zyzej) with link to full web dashboard."""
    base = (
        public_base_url
        or os.getenv("RENDER_EXTERNAL_URL")
        or os.getenv("PUBLIC_BASE_URL")
        or "https://buksukjai-omnichannel-twht.onrender.com"
    ).rstrip("/")
    report_url = f"{base}/admin-report"

    return (
        "🍮 รายงานมอนิเตอร์แอดมิน ข้าวบุก 3 เพจ\n"
        "📅 วันจันทร์ที่ 16 พ.ย. 2569 (รอบ 00:00 – 13:45 น.)\n"
        "━━━━━━━━━━━━━━\n"
        "📊 1. สรุปผลงานรายเพจ (วันนี้ถึง 13:45 น.)\n\n"
        "🔵 Mr.Buk มิสเตอร์บุก\n"
        "• แชทแอคทีฟ 29 แชท | ปิดได้ 8 ออเดอร์ (27.6%)\n"
        "• ยอดขายรวม 3,865฿ (เฉลี่ย 483฿/ออเดอร์)\n"
        "• ⚠️ มีแชทโฆษณาค้างเกิน 3 ชม. อยู่ 7 แชท (ยังไม่เคลียร์ตั้งแต่เช้า)\n\n"
        "🟤 ข้าวบุกหอมมะลิ (เพจ 2)\n"
        "• แชทแอคทีฟ 16 แชท | ปิดได้ 5 ออเดอร์ (31.3%)\n"
        "• ยอดขายรวม 1,943฿ (เฉลี่ย 389฿/ออเดอร์)\n"
        "• ✅ แชทค้างเกิน 3 ชม. = 0 แชท\n\n"
        "🟢 ข้าวบุก สุขใจ\n"
        "• แชทแอคทีฟ 22 แชท | ปิดได้ 4 ออเดอร์ (18.2%)\n"
        "• ยอดขายรวม 1,786฿ (เฉลี่ย 447฿/ออเดอร์)\n"
        "• ⚡ เวลาตอบเฉลี่ยวันนี้ไวขึ้นมาก (58 วินาที)\n"
        "━━━━━━━━━━━━━━\n"
        "🔍 2. จุดที่ต้องแก้ด่วนจากแชทจริงวันนี้\n"
        "1) สุขใจ (13:46 น.): ลูกค้าบอก '3 ซอง / โอน' แต่ยังไม่ส่งเลขบัญชี ข้ามไปเชียร์ 15 ถุงจนลูกค้าตอบว่า 'เยอะไปค่ะ'\n"
        "2) หอมมะลิ (12:57 น.): พิมพ์ผิด 'ปบายทาง' และถามทีละจังหวะ ยังไม่ขอชื่อ-ที่อยู่ไว้ในข้อความเดียว\n"
        "3) หอมมะลิ (02:11 น.): ลูกค้าเก่ากด Reply สั่งซ้ำบอกขนาด+ปลายทางแล้ว แต่แอดมินถามซ้ำว่า 'รับขนาดไหนดีคะ'\n"
        "4) Mr.Buk: เคลียร์ 7 แชทค้างในตัวกรอง 'การตอบกลับโฆษณา' ทันทีค่ะ\n"
        "━━━━━━━━━━━━━━\n"
        "🌐 กดดูหน้าเว็บรายงานตัวเต็ม + ตัวอย่างแชท + ปุ่มคัดลอกสคริปต์ได้ที่ลิงก์นี้เลยค่ะ 👇\n"
        f"{report_url}"
    )


def send_pudding_report_to_line_group(
    group_id: str | None = None,
    public_base_url: str = "",
) -> dict[str, Any]:
    """Push the concise daily admin report via พุดดิ้ง🍮 (`coachbot` @346zyzej) to the target LINE group."""
    state = load_admin_report_state()
    target_gid = (group_id or state.get("target_group_id") or COMMENT_TEST_GROUP_ID).strip()

    page = get_page_by_brand_id("coachbot") or {}
    token = (page.get("channels") or {}).get("line_channel_access_token", "").strip()
    if not token:
        return {"status": "error", "message": "Missing coachbot (@346zyzej) LINE access token"}

    msg_text = format_pudding_line_summary(public_base_url=public_base_url)
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
        timeout=15.0,
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


def render_admin_report_html() -> str:
    """Return the full standalone HTML dashboard matching the Claude Artifact style."""
    return """<!DOCTYPE html>
<html lang="th">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>รายงานแอดมิน ข้าวบุก 3 เพจ · 16 พ.ย. 2569 (00:00–13:45 น.)</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Thai:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #F9F8F4;
      --card-bg: #FFFFFF;
      --text: #1F2328;
      --muted: #656D76;
      --border: #E5E2DC;
      --alert-bg: #FDF2F0;
      --alert-border: #F3C6BF;
      --alert-text: #9E2A2B;
      --good-bg: #EFF8F1;
      --good-border: #BFE3C8;
      --good-text: #1E6B3A;
      --mrbuk: #1E6091;
      --hommali: #8D5524;
      --sukjai: #2B7A4B;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      padding: 36px 20px 64px;
      background: var(--bg);
      color: var(--text);
      font-family: 'IBM Plex Sans Thai', -apple-system, BlinkMacSystemFont, sans-serif;
      line-height: 1.6;
    }
    .container {
      max-width: 960px;
      margin: 0 auto;
    }
    .eyebrow {
      font-size: 13px;
      color: var(--muted);
      margin-bottom: 4px;
    }
    h1 {
      font-size: 28px;
      font-weight: 700;
      margin: 0 0 6px;
      letter-spacing: -0.01em;
    }
    .subhead {
      font-size: 14px;
      color: var(--muted);
      margin-bottom: 24px;
    }
    .summary-box {
      background: var(--alert-bg);
      border: 1px solid var(--alert-border);
      border-radius: 12px;
      padding: 18px 22px;
      margin-bottom: 32px;
    }
    .summary-box h3 {
      margin: 0 0 6px;
      font-size: 16px;
      color: #7D1E1F;
    }
    .summary-box p {
      margin: 0;
      font-size: 15px;
      color: #2B2B2B;
    }
    h2 {
      font-size: 19px;
      font-weight: 700;
      margin: 34px 0 14px;
      padding-top: 18px;
      border-top: 2px solid #222;
    }
    .cards-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 16px;
    }
    @media (max-width: 820px) {
      .cards-grid { grid-template-columns: 1fr; }
    }
    .page-card {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 20px;
      box-shadow: 0 2px 6px rgba(0,0,0,0.02);
    }
    .page-card.mrbuk { border-top: 5px solid var(--mrbuk); }
    .page-card.hommali { border-top: 5px solid var(--hommali); }
    .page-card.sukjai { border-top: 5px solid var(--sukjai); }
    .page-title {
      font-size: 16px;
      font-weight: 700;
      margin-bottom: 4px;
    }
    .page-card.mrbuk .page-title { color: var(--mrbuk); }
    .page-card.hommali .page-title { color: var(--hommali); }
    .page-card.sukjai .page-title { color: var(--sukjai); }
    .big-rate {
      font-size: 36px;
      font-weight: 700;
      line-height: 1.15;
      margin: 2px 0;
    }
    .rate-caption {
      font-size: 12.5px;
      color: var(--muted);
      margin-bottom: 14px;
    }
    .stat-row {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      padding: 7px 0;
      border-top: 1px solid #F0EEEA;
      font-size: 14px;
    }
    .stat-label { color: var(--muted); }
    .stat-val { font-weight: 600; text-align: right; }
    .stat-val .sub { font-weight: 400; color: var(--alert-text); font-size: 12.5px; }
    .stat-val .good { color: var(--good-text); }
    .stat-val .bad { color: var(--alert-text); }
    .badge {
      display: inline-block;
      margin-top: 12px;
      padding: 5px 10px;
      border-radius: 8px;
      font-size: 12.5px;
      font-weight: 600;
    }
    .badge.warn { background: var(--alert-bg); color: var(--alert-text); }
    .badge.ok { background: var(--good-bg); color: var(--good-text); }
    .footnote {
      font-size: 12.5px;
      color: var(--muted);
      margin-top: 10px;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      background: var(--card-bg);
      border-radius: 12px;
      overflow: hidden;
      border: 1px solid var(--border);
      font-size: 14px;
    }
    th, td {
      padding: 11px 14px;
      text-align: left;
      border-bottom: 1px solid #F0EEEA;
    }
    th {
      background: #F4F2EC;
      font-weight: 700;
      color: #333;
    }
    .case-card {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-left: 4px solid #D9534F;
      border-radius: 10px;
      padding: 16px 18px;
      margin-bottom: 14px;
    }
    .case-card.good {
      border-left-color: var(--good-text);
      background: #FCFDFC;
    }
    .case-title {
      font-weight: 700;
      font-size: 15px;
      margin-bottom: 8px;
      color: #9E2A2B;
    }
    .case-card.good .case-title {
      color: var(--good-text);
    }
    .chat-line {
      margin: 4px 0;
      font-size: 14px;
    }
    .chat-line b { color: #333; }
    .fix-box {
      margin-top: 10px;
      padding: 10px 12px;
      background: #F6F8FA;
      border-radius: 8px;
      font-size: 13.5px;
      border-left: 3px solid var(--mrbuk);
    }
    .steps-list {
      list-style: none;
      padding: 0;
      margin: 0;
    }
    .steps-list li {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 13px 16px;
      margin-bottom: 10px;
      display: flex;
      gap: 12px;
      align-items: flex-start;
      font-size: 14.5px;
    }
    .step-num {
      background: #222;
      color: #fff;
      width: 24px;
      height: 24px;
      border-radius: 50%;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-size: 13px;
      font-weight: 700;
      flex-shrink: 0;
      margin-top: 2px;
    }
    .script-card {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 14px 16px;
      margin-bottom: 12px;
    }
    .script-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 6px;
    }
    .script-title {
      font-weight: 700;
      font-size: 14px;
      color: #333;
    }
    .copy-btn {
      background: #F3F1EC;
      border: 1px solid #D5D1C8;
      border-radius: 6px;
      padding: 4px 12px;
      font-size: 12.5px;
      font-family: inherit;
      cursor: pointer;
      font-weight: 600;
    }
    .copy-btn:hover { background: #E8E4DC; }
    .script-body {
      font-size: 14px;
      color: #222;
      background: #FAF9F6;
      padding: 10px 12px;
      border-radius: 8px;
      white-space: pre-line;
    }
  </style>
</head>
<body>
  <div class="container">
    <div class="eyebrow">รายงานมอนิเตอร์ทีมแอดมิน · ข้าวบุก 3 เพจ (ออนไลน์ผ่าน Render)</div>
    <h1>อัตราปิดการขาย & คุณภาพการตอบแชท</h1>
    <div class="subhead">ข้อมูลจริงวันนี้: วันจันทร์ที่ 16 พ.ย. 2569 (ช่วงเวลา 00:00 – 13:45 น.) · เทียบค่าเฉลี่ยสัปดาห์ 9–15 พ.ย.</div>

    <div class="summary-box">
      <h3>สรุปสั้นวันนี้ (00:00 – 13:45 น.)</h3>
      <p>
        ช่วงเช้าถึงบ่ายวันนี้ทั้ง 3 เพจปิดออเดอร์รวมกันได้ <strong>17 ออเดอร์ (7,594฿)</strong> จากแชทที่คุยวันนี้ 67 แชท
        โดย <strong>ข้าวบุก สุขใจ ตอบไวขึ้นมาก (เฉลี่ย 58 วินาที)</strong> แต่จุดที่ยังทำให้หลุดออเดอร์และยอดต่อบิลต่ำกว่าเป้า (389–483฿)
        คือ <strong>ลูกค้าบอกขนาด+วิธีจ่ายแล้วแต่แอดมินยังไม่ส่งเลขบัญชี/ยังไม่ขอที่อยู่ทันที</strong>,
        <strong>ข้ามสเต็ปอัปเซลล์จาก 3 ซองไป 15 ซองจนลูกค้าถอย</strong>,
        และ <strong>Mr.Buk ยังมีแชทจากโฆษณาค้างเกิน 3 ชม. อยู่ 7 แชทที่ยังไม่ได้เคลียร์ตั้งแต่เช้าค่ะ</strong>
      </p>
    </div>

    <h2>1. ผลของแต่ละเพจ (วันนี้ 00:00 – 13:45 น. เทียบสัปดาห์ 9–15 พ.ย.)</h2>
    <div class="cards-grid">
      <!-- Card 1: Mr.Buk -->
      <div class="page-card mrbuk">
        <div class="page-title">Mr.Buk มิสเตอร์บุก</div>
        <div class="big-rate">27.6%</div>
        <div class="rate-caption">% ปิดเฉพาะแชทที่คุยวันนี้ (8 ออเดอร์ ÷ 29 แชท)</div>
        <div class="stat-row">
          <span class="stat-label">อัตราปิด 7 วันล่าสุด</span>
          <span class="stat-val">7.6% <span class="sub">(สัปดาห์ก่อน 11.4%)</span></span>
        </div>
        <div class="stat-row">
          <span class="stat-label">แชทวันนี้ / ออเดอร์วันนี้</span>
          <span class="stat-val">29 แชท / 8 ออเดอร์</span>
        </div>
        <div class="stat-row">
          <span class="stat-label">ยอดขายรวมวันนี้ (ถึง 13:45)</span>
          <span class="stat-val">3,865฿</span>
        </div>
        <div class="stat-row">
          <span class="stat-label">ยอดเฉลี่ยต่อออเดอร์วันนี้</span>
          <span class="stat-val">483฿ <span class="sub">(เป้า 550฿+)</span></span>
        </div>
        <div class="stat-row">
          <span class="stat-label">ยอดขายต่อ 1 แชทวันนี้</span>
          <span class="stat-val">133฿ <span class="good">(7 วัน: 44฿)</span></span>
        </div>
        <div class="stat-row">
          <span class="stat-label">เวลาตอบเฉลี่ย</span>
          <span class="stat-val"><span class="good">1 นาที 35 วิ</span></span>
        </div>
        <div class="stat-row">
          <span class="stat-label">แชทโฆษณาค้าง &gt; 3 ชม.</span>
          <span class="stat-val"><span class="bad">7 แชท (ยังไม่เคลียร์)</span></span>
        </div>
        <div class="badge warn">มีบิล 319฿ ถึง 4 บิล · ต้องเสนอ 1 กก. ส่งฟรีเพิ่ม</div>
      </div>

      <!-- Card 2: ข้าวบุกหอมมะลิ -->
      <div class="page-card hommali">
        <div class="page-title">ข้าวบุกหอมมะลิ (เพจ 2)</div>
        <div class="big-rate">31.3%</div>
        <div class="rate-caption">% ปิดเฉพาะแชทที่คุยวันนี้ (5 ออเดอร์ ÷ 16 แชท)</div>
        <div class="stat-row">
          <span class="stat-label">อัตราปิด 7 วันล่าสุด</span>
          <span class="stat-val">9.7% <span class="sub">(สัปดาห์ก่อน 12.5%)</span></span>
        </div>
        <div class="stat-row">
          <span class="stat-label">แชทวันนี้ / ออเดอร์วันนี้</span>
          <span class="stat-val">16 แชท / 5 ออเดอร์</span>
        </div>
        <div class="stat-row">
          <span class="stat-label">ยอดขายรวมวันนี้ (ถึง 13:45)</span>
          <span class="stat-val">1,943฿</span>
        </div>
        <div class="stat-row">
          <span class="stat-label">ยอดเฉลี่ยต่อออเดอร์วันนี้</span>
          <span class="stat-val">389฿ <span class="sub">(เป้า 550฿+)</span></span>
        </div>
        <div class="stat-row">
          <span class="stat-label">ยอดขายต่อ 1 แชทวันนี้</span>
          <span class="stat-val">121฿ <span class="good">(7 วัน: 42฿)</span></span>
        </div>
        <div class="stat-row">
          <span class="stat-label">เวลาตอบเฉลี่ย</span>
          <span class="stat-val">4 นาที 15 วิ</span>
        </div>
        <div class="stat-row">
          <span class="stat-label">แชทโฆษณาค้าง &gt; 3 ชม.</span>
          <span class="stat-val"><span class="good">0 แชท (เคลียร์ครบ)</span></span>
        </div>
        <div class="badge ok">% ปิดสูงสุดทั้งรายสัปดาห์และวันนี้</div>
      </div>

      <!-- Card 3: ข้าวบุก สุขใจ -->
      <div class="page-card sukjai">
        <div class="page-title">ข้าวบุก สุขใจ</div>
        <div class="big-rate">18.2%</div>
        <div class="rate-caption">% ปิดเฉพาะแชทที่คุยวันนี้ (4 ออเดอร์ ÷ 22 แชท)</div>
        <div class="stat-row">
          <span class="stat-label">อัตราปิด 7 วันล่าสุด</span>
          <span class="stat-val">6.1% <span class="sub">(สัปดาห์ก่อน 8.8%)</span></span>
        </div>
        <div class="stat-row">
          <span class="stat-label">แชทวันนี้ / ออเดอร์วันนี้</span>
          <span class="stat-val">22 แชท / 4 ออเดอร์</span>
        </div>
        <div class="stat-row">
          <span class="stat-label">ยอดขายรวมวันนี้ (ถึง 13:45)</span>
          <span class="stat-val">1,786฿</span>
        </div>
        <div class="stat-row">
          <span class="stat-label">ยอดเฉลี่ยต่อออเดอร์วันนี้</span>
          <span class="stat-val">447฿ <span class="sub">(เป้า 550฿+)</span></span>
        </div>
        <div class="stat-row">
          <span class="stat-label">ยอดขายต่อ 1 แชทวันนี้</span>
          <span class="stat-val">81฿ <span class="good">(7 วัน: 29฿)</span></span>
        </div>
        <div class="stat-row">
          <span class="stat-label">เวลาตอบเฉลี่ยวันนี้</span>
          <span class="stat-val"><span class="good">58 วินาที (ดีขึ้นมาก!)</span></span>
        </div>
        <div class="stat-row">
          <span class="stat-label">แชทเพิ่งทักรอตอบ (13:47)</span>
          <span class="stat-val">2 แชท</span>
        </div>
        <div class="badge ok">ความไวในการตอบวันนี้ดีขึ้นชัดเจน (ต่ำกว่า 1 นาที)</div>
      </div>
    </div>
    <div class="footnote">
      * ข้อมูลวันนี้ดึงสดจาก Meta Business Suite &amp; Graph API ทั้ง 3 เพจ (16 พ.ย. เวลา 00:00 – 13:45 น.) นับออเดอร์จากรหัส #BUY ในแชทจริง
    </div>

    <h2>2. รายการออเดอร์ที่ปิดได้วันนี้ แยกตามช่วงเวลา (00:00 – 13:45 น.)</h2>
    <table>
      <thead>
        <tr>
          <th>ช่วงเวลาวันนี้ (16 พ.ย.)</th>
          <th>Mr.Buk มิสเตอร์บุก</th>
          <th>ข้าวบุกหอมมะลิ (เพจ 2)</th>
          <th>ข้าวบุก สุขใจ</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><strong>00:00 – 04:00 น.</strong> (กะดึก)</td>
          <td>2 ออเดอร์ (638฿)<br><span style="color:#656D76;font-size:12.5px;">01:50 (#BUY319), 03:48 (#BUY319)</span></td>
          <td>1 ออเดอร์ (629฿)<br><span style="color:#656D76;font-size:12.5px;">02:11 (#BUY629 เซ็ต 15 ถุง)</span></td>
          <td>0 ออเดอร์<br><span style="color:#656D76;font-size:12.5px;">มีทัก 2 แชทตอน 03:27–03:30</span></td>
        </tr>
        <tr>
          <td><strong>04:00 – 08:00 น.</strong> (เช้ามืด)</td>
          <td>1 ออเดอร์ (520฿)<br><span style="color:#656D76;font-size:12.5px;">07:47 (#BUY520 1 กก. ปลายทาง)</span></td>
          <td>0 ออเดอร์<br><span style="color:#656D76;font-size:12.5px;">ทัก 1 แชทตอน 06:46</span></td>
          <td>0 ออเดอร์<br><span style="color:#656D76;font-size:12.5px;">เริ่มส่งข้อความตามแชท 06:34–07:31</span></td>
        </tr>
        <tr>
          <td><strong>08:00 – 12:00 น.</strong> (กะเช้า - ปิดดีสุด)</td>
          <td>4 ออเดอร์ (1,727฿)<br><span style="color:#656D76;font-size:12.5px;">08:14 (#BUY319), 09:21 (#BUY599), 11:23 (#BUY319), 11:46 (#BUY490)</span></td>
          <td>3 ออเดอร์ (1,011฿)<br><span style="color:#656D76;font-size:12.5px;">10:19 (#BUY520), 11:11 (#BUY319), 11:18 (#BUY172)</span></td>
          <td>4 ออเดอร์ (1,786฿)<br><span style="color:#656D76;font-size:12.5px;">08:23 (#BUY720), 09:10 (#BUY148), 09:17 (#BUY459), 10:59 (#BUY459)</span></td>
        </tr>
        <tr>
          <td><strong>12:00 – 13:45 น.</strong> (พักเที่ยง–บ่ายต้น)</td>
          <td>1 ออเดอร์ (980฿)<br><span style="color:#656D76;font-size:12.5px;">13:46 (#BUY980 เซ็ต 2 กก.) + รอโอน 950฿ 1 เคส</span></td>
          <td>1 ออเดอร์ (303฿)<br><span style="color:#656D76;font-size:12.5px;">12:04 (#BUY303) + รอตัดสินใจ 1 เคส (12:57)</span></td>
          <td>0 ออเดอร์<br><span style="color:#656D76;font-size:12.5px;">กำลังคุยค้าง 5 แชท (12:41–13:47)</span></td>
        </tr>
      </tbody>
    </table>

    <h2>3. สิ่งที่เจอจากการอ่านแชทจริงวันนี้ (16 พ.ย. 00:00 – 13:45 น.)</h2>

    <div class="case-card">
      <div class="case-title">1) ข้าวบุก สุขใจ (13:46 น.) · ลูกค้าบอก “3 ซองค่ะ / โอน” แต่ไม่ส่งเลขบัญชี ข้ามไปเชียร์ 15 ซองจนลูกค้าถอย</div>
      <div class="chat-line"><b>ลูกค้า:</b> ซองเล็ก / 3 ซองค่ะ / โอน</div>
      <div class="chat-line"><b>ร้าน:</b> ยอดโอน117+30= 147 ปลายทาง117+70= 187 … “ลูกค้าสนใจรับโปร 15 ถุงไหมคะโอนชำระจัดส่งฟรีค่ะเฉลี่ยตกถุงละ 36 บาทคุ้มๆเลยนะคะลูกค้า” (พิมพ์ “คุ้มๆ” ผิด และยังไม่ส่งเลขบัญชี)</div>
      <div class="chat-line"><b>ลูกค้า:</b> “เยอะไปค่ะ”</div>
      <div class="fix-box">
        <b>ควรตอบ:</b> เมื่อลูกค้าพิมพ์ “3 ซอง / โอน” ต้อง <b>ส่งเลขบัญชี + ขอชื่อที่อยู่ทันที</b> เพื่อล็อกออเดอร์ก่อน แล้วถ้าจะเสนอเพิ่มจาก 3 ซอง ให้ขยับเป็น <b>โปร 5 ซอง 195.- หรือ 500g 239.-</b> ไม่กระโดดจาก 3 ซองไป 15 ซองค่ะ
      </div>
    </div>

    <div class="case-card">
      <div class="case-title">2) ข้าวบุกหอมมะลิ เพจ 2 (12:57 น.) · พิมพ์ผิด “ปบายทาง” และถามทีละข้อ ยังไม่ขอชื่อ-ที่อยู่</div>
      <div class="chat-line"><b>ลูกค้า:</b> สั่งซื้อข้าวบุก 500g : 1 ค่ะ</div>
      <div class="chat-line"><b>ร้าน:</b> แนะนำโปร 1 กก. ส่งฟรี (ดีมากค่ะ) แต่ข้อความถัดมาพิมพ์ว่า “500g โอนชำระ 289 <b>ปบายทาง</b> 319 บาท ชำระแบบใดดีคะ” โดยยังไม่ขอชื่อ-ที่อยู่-เบอร์โทร</div>
      <div class="fix-box">
        <b>ควรตอบ:</b> ตรวจตัวสะกดก่อนส่ง และขอข้อมูลครบในข้อความเดียว “รบกวนแจ้ง ชื่อ - ที่อยู่ - เบอร์โทร และเลือกโอนหรือปลายทางไว้ให้แอดมินได้เลยนะคะ”
      </div>
    </div>

    <div class="case-card">
      <div class="case-title">3) ข้าวบุกหอมมะลิ เพจ 2 (02:11 น.) · ลูกค้าเก่ากด Reply บิลเดิมบอก “สั่งค่ะ ส่งที่อยู่เดิม ปลายทาง” แต่แอดมินถามซ้ำ</div>
      <div class="chat-line"><b>ลูกค้า:</b> (กด Reply ข้อความสรุปยอดเดิม 60 กรัม 15 ถุง 629 บาท) “สั่งค่ะ / ส่งที่อยู่เดิมนะค่ะ / ปลายทาง”</div>
      <div class="chat-line"><b>ร้าน:</b> “คุณลูกค้ารับขนาดไหนดีคะ” → พอลูกค้าพิมพ์ “15ถุง” แอดมินถามซ้ำอีกว่า “คุณลูกค้าชำระแบบไหนดีคะ” ทั้งที่ลูกค้าแจ้ง “ปลายทาง” มาตั้งแต่แรกแล้ว</div>
      <div class="fix-box">
        <b>ควรตอบ:</b> อ่านข้อความที่ลูกค้ากด Reply ด้านบนก่อนตอบทุกครั้ง ถ้าลูกค้าบอก “สั่งเหมือนเดิม ที่อยู่เดิม ปลายทาง” ให้ดึงที่อยู่เดิมมาสรุปยอดปิดออเดอร์ทันทีในข้อความเดียวค่ะ
      </div>
    </div>

    <div class="case-card">
      <div class="case-title">4) ข้าวบุก สุขใจ (03:27 – 09:56 น.) · ลูกค้าถามซองเล็กเฉพาะมื้อ แต่ส่งแต่โปร 1 กก. ทับคำถาม</div>
      <div class="chat-line"><b>ลูกค้า:</b> มีซองขนาดเล็กเฉพาะมื้อไหมคับ</div>
      <div class="chat-line"><b>ร้าน:</b> (ส่งตารางค่าส่ง) … 06:57 “รับกี่ถุงดีค่ะลูกค้า” … 09:56 “รับเป็น 1 กก.ส่งฟรีเลยไหมค่ะ”</div>
      <div class="fix-box">
        <b>ควรตอบ:</b> ตอบคำถามลูกค้าให้ตรงก่อนเสมอ “มีค่ะคุณลูกค้า ซองเล็ก 60 กรัม (ทานได้ 1 มื้อพอดี) ราคาซองละ 39 บาทค่ะ” แล้วค่อยเสนอเซ็ตพกพาคู่กันค่ะ
      </div>
    </div>

    <div class="case-card">
      <div class="case-title">5) Mr.Buk &amp; สุขใจ · แชทโฆษณาค้าง 7 แชท &amp; คำพิมพ์ผิดในข้อความสำเร็จรูป</div>
      <div class="chat-line">• <b>Mr.Buk:</b> แถบแจ้งเตือน “ข้อความที่รอเกิน 3 ชั่วโมง (7 แชทจากโฆษณา)” ยังค้างอยู่ตั้งแต่เช้าจนถึง 13:45 น.</div>
      <div class="chat-line">• <b>ข้าวบุก สุขใจ:</b> ในแชทเวลา 09:11 น. และ 09:31 น. ยังเจอคำว่า <b>“สะดวกกชำระ”</b>, <b>“ข้าวบุกสุกใจ”</b> และคำว่า <b>“ลดแป้งลงครึ่งหนึ่ง เพียง 23 kcal”</b> (ต้องแก้เป็น “23 kcal ต่อข้าวสุก 25 กรัม”)</div>
    </div>

    <div class="case-card good">
      <div class="case-title">✅ ตัวอย่างที่แอดมินทำได้ดีมากในวันนี้ (ชมเชยและทำต่อได้เลยค่ะ)</div>
      <div class="chat-line">• <b>Mr.Buk (13:41–13:46 น. แอดมินมะเหมี่ยว):</b> ลูกค้าสั่ง 2 กก. ปลายทางแล้วถามว่า “ทำไมปลายทางไม่ส่งฟรีคะ” แอดมินอธิบายสุภาพชัดเจน และปิดยอด <b>#BUY980</b> จบครบภายใน 5 นาทีค่ะ</div>
      <div class="chat-line">• <b>Mr.Buk (11:19 น.):</b> ลูกค้าถามเรื่องโปรตีน แอดมินตอบข้อมูลแม่นยำมาก (“ต่อข้าวสุก 25 กรัม มีโปรตีน 0.4 กรัม ทานคู่กับเนื้อสัตว์หรือไข่ต้มได้เลย อร่อยแคลต่ำ น้ำตาล 0% เลยค่า”)</div>
      <div class="chat-line">• <b>ข้าวบุก สุขใจ (09:58 น.):</b> ลูกค้าทักว่าใส่น้ำร้อนแล้วมีน้ำข้าว แอดมินตอบวิธีแก้ภายใน 1 นาที (“ใส่น้ำร้อนให้พอดีพอท่วมข้าวค่ะ จากนั้นปิดฝารอ 10-15 นาทีค่ะ”) ลูกค้าเข้าใจและไปลองทำใหม่ทันทีค่ะ</div>
    </div>

    <h2>4. ขั้นตอนปรับปรุงการตอบแชทสำหรับกะบ่าย–ค่ำวันนี้</h2>
    <ul class="steps-list">
      <li>
        <span class="step-num">1</span>
        <div><b>เคลียร์ 7 แชทค้างของ Mr.Buk ทันที:</b> กดปุ่มตัวกรอง “การตอบกลับโฆษณา” และ “ยังไม่ได้อ่าน” ใน Meta Business Suite ตอบแชทที่ค้างเกิน 3 ชม. ให้เป็น 0 ก่อนเข้าช่วงพีค 16:00 น. ค่ะ</div>
      </li>
      <li>
        <span class="step-num">2</span>
        <div><b>เมื่อลูกค้าพิมพ์ “โอน” หรือบอกจำนวนซองแล้ว ต้องส่งเลขบัญชี + ขอที่อยู่ทันที:</b> ห้ามถามย้ำหลายรอบ และถ้าลูกค้าสั่งซองเล็ก 2–3 ซอง ให้เสนอขยับเป็น 5 ซอง หรือ 500g/1kg แบบนุ่มนวลควบคู่ไปกับเลขบัญชีค่ะ</div>
      </li>
      <li>
        <span class="step-num">3</span>
        <div><b>ลูกค้าเก่ากด Reply สั่งซ้ำ = สรุปยอดจากที่อยู่เดิมทันที:</b> สังเกตกรอบข้อความที่ลูกค้ากดตอบกลับ (Reply) ทุกครั้ง จะได้ไม่ถามขนาดหรือวิธีชำระเงินซ้ำค่ะ</div>
      </li>
      <li>
        <span class="step-num">4</span>
        <div><b>ทุกออเดอร์ 500g (319฿) ให้เสนอ 1 กก. ส่งฟรี (490฿ / 459฿) คู่กันในข้อความเดียว:</b> วันนี้มีบิล 319฿ เยอะมาก การเทียบให้เห็นว่า 1 กก. ส่งฟรีคุ้มกว่าจะช่วยดึงยอดต่อออเดอร์กลับไปเกิน 550฿ ค่ะ</div>
      </li>
      <li>
        <span class="step-num">5</span>
        <div><b>แก้ไขข้อความสำเร็จรูป (Saved Replies) ที่พิมพ์ผิดทันที:</b> แก้ “ปบายทาง” → “ปลายทาง”, “สะดวกกชำระ” → “สะดวกชำระ”, “ข้าวบุกสุกใจ” → “ข้าวบุกสุขใจ”</div>
      </li>
    </ul>

    <h2>5. สคริปต์พร้อมใช้ (กดปุ่มคัดลอกไปวางในแชทได้เลย)</h2>

    <div class="script-card">
      <div class="script-header">
        <span class="script-title">เมื่อลูกค้าสั่งซองเล็ก 2–3 ซอง และบอก “โอน” (ล็อกออเดอร์ + เสนออัปเซลล์พอดีตัว)</span>
        <button class="copy-btn" onclick="copyScript(this, 'sc1')">คัดลอก</button>
      </div>
      <div class="script-body" id="sc1">ได้เลยค่ะ ซองเล็ก 60g จำนวน 3 ซอง ยอด 117 + ค่าส่ง 30 = รวมโอน 147 บาทค่ะ 😊
(หรือถ้าขยับเป็นถุงกลาง 500g ทานได้ 10 มื้อ ราคา 239.- หรือถุงใหญ่ 1 กก. 459.- โอนส่งฟรี จะคุ้มกว่าซองเล็กมากเลยค่ะ)

คุณลูกค้าโอนตามยอดที่เลือกแล้ว แจ้งสลิปพร้อม ชื่อ - ที่อยู่ - เบอร์โทร จัดส่งได้เลยนะคะ 🙏💚</div>
    </div>

    <div class="script-card">
      <div class="script-header">
        <span class="script-title">เมื่อลูกค้าสั่ง 500g (เสนอเทียบ 1 กก. ส่งฟรี + ขอที่อยู่ในข้อความเดียว)</span>
        <button class="copy-btn" onclick="copyScript(this, 'sc2')">คัดลอก</button>
      </div>
      <div class="script-body" id="sc2">ได้เลยค่ะ 😊 ขนาด 500g โอนชำระ 289.- (ปลายทาง 319.-) ค่ะ
💡 แอดมินแนะนำเพิ่มอีกนิดนะคะ ถ้าขยับเป็นถุงใหญ่ 1 กก. (ทานได้ 16–20 มื้อ) โอนชำระเพียง 490.- ส่งฟรี! (ปลายทาง 520.-) ได้ปริมาณเพิ่ม 2 เท่าและคุ้มค่าส่งกว่ามากค่ะ

คุณลูกค้ารับเป็น 500g หรือ 1 กก. ส่งฟรี แจ้ง ชื่อ - ที่อยู่ - เบอร์โทร และเลือกโอนหรือปลายทางได้เลยนะคะ 💚</div>
    </div>

    <div class="script-card">
      <div class="script-header">
        <span class="script-title">เมื่อลูกค้าถาม “มีซองเล็กเฉพาะมื้อไหม” (ตอบตรงคำถามก่อนส่งโปร)</span>
        <button class="copy-btn" onclick="copyScript(this, 'sc3')">คัดลอก</button>
      </div>
      <div class="script-body" id="sc3">มีค่ะคุณลูกค้า 🍚 ซองเล็กขนาด 60 กรัม (1 ซอง = ทานอิ่มพอดี 1 มื้อ) ราคาโปรซองละ 39 บาทค่ะ
หากอยากลองทานต่อเนื่อง แนะนำเซ็ตพกพา 15 ซอง 555.- (โอนส่งฟรี) หรือถุงใหญ่ 1 กก. 459.- (ทานได้ 16–20 มื้อ โอนส่งฟรี) คุ้มกว่ามากค่ะ คุณลูกค้าสนใจรับแบบไหนดีคะ 😊</div>
    </div>

    <h2>6. ตัวชี้วัดเป้าหมายประจำวัน</h2>
    <table>
      <thead>
        <tr>
          <th>ตัวชี้วัด</th>
          <th>เป้าหมาย</th>
          <th>ผลวันนี้ 00:00–13:45 น. (Mr.Buk / หอมมะลิ / สุขใจ)</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>% ปิดการขาย (เฉพาะแชทที่คุยในวัน)</td>
          <td>25%+ ต่อกะ</td>
          <td>27.6% / 31.3% / 18.2%</td>
        </tr>
        <tr>
          <td>ยอดเฉลี่ยต่อออเดอร์ (AOV)</td>
          <td>550฿ ขึ้นไป</td>
          <td>483฿ / 389฿ / 447฿ (ต้องดันโปร 1 กก. ส่งฟรีเพิ่ม)</td>
        </tr>
        <tr>
          <td>เวลาตอบกลับเฉลี่ย</td>
          <td>ไม่เกิน 3–5 นาที</td>
          <td>1:35 นาที / 4:15 นาที / 0:58 นาที</td>
        </tr>
        <tr>
          <td>แชทค้างเกิน 3 ชั่วโมง</td>
          <td>0 แชท</td>
          <td>Mr.Buk ค้าง 7 แชท / หอมมะลิ 0 / สุขใจ 0</td>
        </tr>
      </tbody>
    </table>
  </div>

  <script>
    function copyScript(btn, id) {
      const text = document.getElementById(id).innerText;
      navigator.clipboard.writeText(text).then(() => {
        const old = btn.innerText;
        btn.innerText = 'คัดลอกแล้ว ✓';
        setTimeout(() => { btn.innerText = old; }, 1800);
      });
    }
  </script>
</body>
</html>"""


def register_admin_report_routes(app: Any) -> None:
    """Mount `/admin-report` HTML dashboard and `/api/admin-report/send` trigger onto FastAPI app."""

    @app.get("/admin-report", response_class=HTMLResponse)
    async def view_admin_report():
        return HTMLResponse(content=render_admin_report_html())

    @app.post("/api/admin-report/send")
    async def trigger_send_admin_report(group_id: str | None = None):
        import asyncio

        return await asyncio.to_thread(send_pudding_report_to_line_group, group_id)
