"""AI Process 1 — Daily Sales & Warehouse Stock Reconciliation Report (สรุปยอดขายรายวันเวลา 01:00 น.)."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from . import jst_erp

logger = logging.getLogger(__name__)

BKK_TZ = timezone(timedelta(hours=7))
DAILY_REPORT_HOUR_BKK = 1
REPORT_STATE_FILE = Path(__file__).resolve().parent.parent / "daily_report_state.json"
GOOGLE_SHEET_FILE_ID = "1mMO_aZnaCaDskrJMreJiaonFqna-WNKBhOoozAWxIhE"
GOOGLE_SHEET_URL = f"https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_FILE_ID}/edit?gid=0#gid=0"
DAILY_LINE_GROUP_HOUR_BKK = 7
LINE_GROUP_CONFIG_FILE = Path(__file__).resolve().parent.parent / "line_group_config.json"


def parse_sku_physical_counts(skus_list: list[Any]) -> tuple[str, int, int, int, int]:
    c1kg, c500g, c60g = 0, 0, 0
    sku_codes: list[str] = []
    total_qty = 0
    for s in skus_list or []:
        code = str(s[1] if len(s) > 1 else "").strip()
        qty = int(s[8] if (len(s) > 8 and s[8]) else 1)
        if not code:
            continue
        if code not in sku_codes:
            sku_codes.append(code)
        if code == "BSJ1KG1":
            c1kg += 1 * qty
            total_qty += 1 * qty
        elif code == "BSJ1KG2":
            c1kg += 2 * qty
            total_qty += 2 * qty
        elif code == "BSJ1KG3":
            c1kg += 3 * qty
            total_qty += 3 * qty
        elif code == "BSJ1KG2_60G2":
            c1kg += 2 * qty
            c60g += 2 * qty
            total_qty += 4 * qty
        elif code == "BSJ1KG3_60G3":
            c1kg += 3 * qty
            c60g += 3 * qty
            total_qty += 6 * qty
        elif code == "BSJ500G1":
            c500g += 1 * qty
            total_qty += 1 * qty
        elif code.startswith("BSJ60G"):
            m = re.search(r"BSJ60G(\d+)", code)
            n = int(m.group(1)) if m else 1
            c60g += n * qty
            total_qty += n * qty
        else:
            total_qty += qty
    return ", ".join(sku_codes), total_qty, c1kg, c500g, c60g


def build_daily_sales_sheet_rows(target_date: str) -> dict[str, Any]:
    resp = httpx.post(
        "https://asia.jsterp.com/OMS/MiniShopOrder/NewQueryOrders",
        headers=jst_erp._headers(True),
        json={
            "RequestModel": {"SendFrom": "NewQueryOrders"},
            "DataPage": {"pageSize": 200, "pageIndex": 1, "total": 0, "sizes": [50, 100, 200]},
        },
        timeout=20.0,
    )
    resp.raise_for_status()
    rows_obj = resp.json().get("Rows") or {}
    cols = rows_obj.get("cols") or []
    raw_rows = [dict(zip(cols, r)) for r in (rows_obj.get("rows") or [])]

    day_orders = [
        x
        for x in raw_rows
        if str(x.get("OrderTime") or "").startswith(target_date)
        and "ยกเลิก" not in str(x.get("StatusDisplay") or "")
        and "Cancel" not in str(x.get("Status") or "")
    ]
    day_orders.sort(key=lambda x: str(x.get("OrderTime") or ""))

    header = [
        "ลำดับ", "วันที่สั่งซื้อ", "ช่องทาง", "ชื่อลูกค้า", "ที่อยู่จัดส่ง",
        "เบอร์โทรศัพท์", "รหัส SKU", "จำนวนสินค้า", "จำนวนเงิน (บาท)",
        "รูปแบบการชำระเงิน", "เลขออเดอร์ JST / เลขพัสดุ",
    ]
    table_rows: list[list[Any]] = [header]
    tot_transfer = 0.0
    tot_cod = 0.0
    tot_facebook = 0.0
    tot_tiktok = 0.0
    tot_shopee = 0.0
    tot_1kg = 0
    tot_500g = 0
    tot_60g = 0
    order_items_out: list[dict[str, Any]] = []

    for idx, o in enumerate(day_orders, 1):
        sku_str, pieces, k1, g500, g60 = parse_sku_physical_counts(o.get("Skus") or [])
        tot_1kg += k1
        tot_500g += g500
        tot_60g += g60
        amt = round(float(o.get("PayAmount") or 0.0), 2)
        is_cod = bool(o.get("IsCod"))
        if is_cod:
            tot_cod += amt
        else:
            tot_transfer += amt
        save_type = str(o.get("SaveType") or "")
        plat_id = str(o.get("PlatformId") or "")
        channel = "Facebook" if save_type == "ManualOrder" else (plat_id or "TikTok")
        if channel.lower() == "facebook":
            tot_facebook += amt
        elif channel.lower() == "shopee":
            tot_shopee += amt
        else:
            tot_tiktok += amt
        first_en = str(o.get("ReceiverFirstNameEn") or "").strip()
        last_en = str(o.get("ReceiverLastNameEn") or "").strip()
        cust_name = f"{first_en} {last_en}".strip() or str(o.get("ReceiverName") or "").strip()
        phone = str(o.get("ReceiverMobileEn") or o.get("ReceiverPhoneEn") or "").strip()
        addr = re.sub(r"\s+", " ", str(o.get("ReceiverAddress") or o.get("Address") or "").strip())
        pay_label = "COD" if is_cod else "โอน"
        order_id = str(o.get("OrderId") or "")
        tracking = str(o.get("LogisticsTrackingNumber") or "").strip()
        status_disp = str(o.get("StatusDisplay") or "").strip()
        jst_col = f"#{order_id} ({status_disp} {tracking})".strip()
        phone_cell = f"'{phone}" if phone.startswith("0") else phone
        row = [idx, target_date, channel, cust_name, addr, phone_cell, sku_str, pieces, amt, pay_label, jst_col]
        table_rows.append(row)
        order_items_out.append({"seq": idx, "date": target_date, "channel": channel, "customer_name": cust_name, "address": addr, "phone": phone, "sku": sku_str, "qty_pieces": pieces, "qty_1kg": k1, "qty_500g": g500, "qty_60g": g60, "amount": amt, "payment_method": pay_label, "order_id": order_id, "tracking": tracking, "status": status_disp})

    tot_pieces = tot_1kg + tot_500g + tot_60g
    grand_total = round(tot_transfer + tot_cod, 2)
    table_rows.append(["", "", "", "", "", "", "", "", "", "", ""])
    table_rows.append(["", "", "", "", "", "", "1 กิโลกรัม", tot_1kg, "", "", ""])
    table_rows.append(["", "", "", "", "", "", "500 กรัม", tot_500g, "", "", ""])
    table_rows.append(["", "", "", "", "", "", "60 กรัม", tot_60g, "", "", ""])
    table_rows.append(["", "", "", "", "", "", "รวมจำนวนสินค้าทั้งหมด", tot_pieces, "", "", ""])
    table_rows.append(["", "", "", "", "", "", "", "", "", "", ""])
    table_rows.append(["", "", "", "", "", "", "", "Facebook", round(tot_facebook, 2), "", ""])
    table_rows.append(["", "", "", "", "", "", "", "TikTok", round(tot_tiktok, 2), "", ""])
    if tot_shopee > 0:
        table_rows.append(["", "", "", "", "", "", "", "Shopee", round(tot_shopee, 2), "", ""])
    table_rows.append(["", "", "", "", "", "", "", "", "", "", ""])
    table_rows.append(["", "", "", "", "", "", "", "โอน", round(tot_transfer, 2), "", ""])
    table_rows.append(["", "", "", "", "", "", "", "COD", round(tot_cod, 2), "", ""])
    table_rows.append(["", "", "", "", "", "", "", "รวมทั้งสิ้น", grand_total, "", ""])
    return {
        "target_date": target_date, "order_count": len(order_items_out),
        "tot_1kg": tot_1kg, "tot_500g": tot_500g, "tot_60g": tot_60g, "tot_pieces": tot_pieces,
        "tot_facebook": round(tot_facebook, 2), "tot_tiktok": round(tot_tiktok, 2), "tot_shopee": round(tot_shopee, 2),
        "tot_transfer": round(tot_transfer, 2), "tot_cod": round(tot_cod, 2), "grand_total": grand_total,
        "orders": order_items_out, "sheet_rows": table_rows,
    }


def should_run_daily_1am_report() -> tuple[bool, str]:
    now_bkk = datetime.now(BKK_TZ)
    yesterday_str = (now_bkk - timedelta(days=1)).strftime("%Y-%m-%d")
    if now_bkk.hour < DAILY_REPORT_HOUR_BKK:
        return False, yesterday_str
    state: dict[str, Any] = {}
    if REPORT_STATE_FILE.exists():
        try:
            state = json.loads(REPORT_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            state = {}
    return state.get("last_report_date") != yesterday_str, yesterday_str


def load_line_group_config() -> dict[str, Any]:
    import os
    cfg: dict[str, Any] = {"groups": [], "group_meta": {}, "last_7am_report_date": "", "last_7am_sent_at": ""}
    if LINE_GROUP_CONFIG_FILE.exists():
        try:
            loaded = json.loads(LINE_GROUP_CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                cfg.update(loaded)
        except Exception:
            pass
    env_groups = [g.strip() for g in os.getenv("LINE_WORK_GROUP_IDS", "").split(",") if g.strip()]
    groups_list: list[str] = list(cfg.get("groups") or [])
    for g in env_groups:
        if g not in groups_list:
            groups_list.append(g)
    try:
        from . import database
        for s in database.list_all_sessions(brand_id="all", platform="line_group", state="all"):
            ext_id = str(s.get("external_user_id") or "").strip()
            if ext_id and ext_id not in groups_list:
                groups_list.append(ext_id)
    except Exception:
        pass
    cfg["groups"] = groups_list
    return cfg


def save_line_group_config(cfg: dict[str, Any]) -> None:
    try:
        LINE_GROUP_CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("Failed to write line_group_config.json: %s", exc)


def register_line_group(group_id: str, brand_id: str = "workbot", group_type: str = "group") -> bool:
    group_id = (group_id or "").strip()
    if not group_id:
        return False
    cfg = load_line_group_config()
    groups: list[str] = list(cfg.get("groups") or [])
    is_new = group_id not in groups
    if is_new:
        groups.append(group_id)
    cfg["groups"] = groups
    meta = dict(cfg.get("group_meta") or {})
    now_iso = datetime.now(BKK_TZ).isoformat()
    if group_id not in meta:
        meta[group_id] = {"group_id": group_id, "brand_id": brand_id, "group_type": group_type, "joined_at": now_iso, "last_active_at": now_iso}
    else:
        meta[group_id]["last_active_at"] = now_iso
        meta[group_id]["brand_id"] = brand_id
    cfg["group_meta"] = meta
    save_line_group_config(cfg)
    try:
        from . import database
        psid = database.make_session_key(brand_id, "line_group", group_id)
        database.get_or_create_session(psid=psid, brand_id=brand_id, platform="line_group", external_user_id=group_id, customer_name=f"กลุ่มไลน์งาน ({group_id[:8]}...)")
        database.update_session_meta(psid=psid, bot_enabled=False, notes="Registered LINE Work Group for 07:00 AM Daily Report")
    except Exception as exc:
        logger.warning("SQLite line_group session save warning: %s", exc)
    return is_new


def unregister_line_group(group_id: str) -> None:
    group_id = (group_id or "").strip()
    if not group_id:
        return
    cfg = load_line_group_config()
    cfg["groups"] = [g for g in (cfg.get("groups") or []) if g != group_id]
    save_line_group_config(cfg)


def format_line_group_daily_summary(report: dict[str, Any]) -> str:
    t_date = report.get("target_date", "")
    order_count = int(report.get("order_count") or 0)
    fb_amt = float(report.get("tot_facebook") or 0.0)
    tt_amt = float(report.get("tot_tiktok") or 0.0)
    sp_amt = float(report.get("tot_shopee") or 0.0)
    tr_amt = float(report.get("tot_transfer") or 0.0)
    cod_amt = float(report.get("tot_cod") or 0.0)
    grand_amt = float(report.get("grand_total") or 0.0)
    qty_60g = int(report.get("tot_60g") or 0)
    qty_500g = int(report.get("tot_500g") or 0)
    qty_1kg = int(report.get("tot_1kg") or 0)
    qty_total = int(report.get("tot_pieces") or (qty_60g + qty_500g + qty_1kg))
    lines = [
        f"📊 สรุปยอดขายและตัดสต็อกประจำวันที่ {t_date}",
        "(รายงานอัตโนมัติหลังคีย์ออเดอร์เสร็จ 07:00 น. ค่ะ)",
        "━━━━━━━━━━━━━━━",
        f"🛒 ยอดขายแยกตามช่องทาง (รวม {order_count} ออเดอร์)",
        f"• Facebook : {fb_amt:,.2f} บาท",
        f"• TikTok : {tt_amt:,.2f} บาท",
        f"• Shopee : {sp_amt:,.2f} บาท",
        "",
        "💰 ยอดขายแยกตามวิธีชำระเงิน",
        f"• ยอดโอน : {tr_amt:,.2f} บาท",
        f"• ยอด COD : {cod_amt:,.2f} บาท",
        f"✨ รวมยอดขายสุทธิทั้งสิ้น : {grand_amt:,.2f} บาท",
        "━━━━━━━━━━━━━━━",
        "📦 จำนวนสินค้าที่หมดไป (สำหรับตัดสต็อกโกดัง)",
        f"• ขนาด 60 กรัม หมดไป : {qty_60g:,} ซอง",
        f"• ขนาด 500 กรัม หมดไป : {qty_500g:,} ถุง",
        f"• ขนาด 1 กิโลกรัม หมดไป : {qty_1kg:,} ถุง",
        f"✅ รวมจำนวนสินค้าที่หมดไปทั้งหมด : {qty_total:,} ชิ้น",
        "━━━━━━━━━━━━━━━",
        "🔗 ดูตารางรายชื่อและรายละเอียดใน Google Sheets:",
        GOOGLE_SHEET_URL,
    ]
    return "\n".join(lines)


def should_run_daily_7am_line_report() -> tuple[bool, str]:
    now_bkk = datetime.now(BKK_TZ)
    yesterday_str = (now_bkk - timedelta(days=1)).strftime("%Y-%m-%d")
    if now_bkk.hour < DAILY_LINE_GROUP_HOUR_BKK:
        return False, yesterday_str
    cfg = load_line_group_config()
    if not cfg.get("groups"):
        return False, yesterday_str
    return cfg.get("last_7am_report_date") != yesterday_str, yesterday_str


def fetch_report_from_google_sheet(target_date: str | None = None) -> dict[str, Any] | None:
    import csv
    import io
    export_url = f"https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_FILE_ID}/export?format=csv"
    try:
        resp = httpx.get(export_url, follow_redirects=True, timeout=15.0)
        if resp.status_code != 200 or not resp.text.strip():
            return None
        raw_csv = resp.content.decode("utf-8", errors="replace")
    except Exception as exc:
        logger.warning("Google Sheet CSV fetch warning: %s", exc)
        return None
    rows = list(csv.reader(io.StringIO(raw_csv)))
    if len(rows) < 2:
        return None
    sheet_dates: list[str] = []
    order_rows: list[list[str]] = []
    for r in rows[1:]:
        if len(r) >= 10 and str(r[0]).strip().isdigit() and re.match(r"^\d{4}-\d{2}-\d{2}$", str(r[1]).strip()):
            d_str = str(r[1]).strip()
            sheet_dates.append(d_str)
            if not target_date or d_str == target_date:
                order_rows.append(r)
    if not order_rows:
        return None
    effective_date = target_date or sheet_dates[0]
    tot_transfer = 0.0
    tot_cod = 0.0
    tot_facebook = 0.0
    tot_tiktok = 0.0
    tot_shopee = 0.0
    tot_1kg = 0
    tot_500g = 0
    tot_60g = 0
    for r in order_rows:
        channel = str(r[2]).strip()
        sku_str = str(r[6]).strip()
        try:
            amt = float(str(r[8]).replace(",", "").strip() or 0.0)
        except ValueError:
            amt = 0.0
        pay_label = str(r[9]).strip().upper()
        if "COD" in pay_label:
            tot_cod += amt
        else:
            tot_transfer += amt
        ch_low = channel.lower()
        if "facebook" in ch_low:
            tot_facebook += amt
        elif "shopee" in ch_low:
            tot_shopee += amt
        else:
            tot_tiktok += amt
        try:
            row_qty = int(float(str(r[7]).replace(",", "").strip() or 1))
        except ValueError:
            row_qty = 1
        codes = [c.strip() for c in sku_str.split(",") if c.strip()]
        for code in codes:
            if code == "BSJ1KG1":
                tot_1kg += row_qty
            elif code == "BSJ1KG2":
                tot_1kg += 2
            elif code == "BSJ1KG3":
                tot_1kg += 3
            elif code == "BSJ1KG2_60G2":
                tot_1kg += 2
                tot_60g += 2
            elif code == "BSJ1KG3_60G3":
                tot_1kg += 3
                tot_60g += 3
            elif code == "BSJ500G1":
                tot_500g += row_qty
            elif code.startswith("BSJ60G"):
                tot_60g += row_qty
    if len(set(sheet_dates)) == 1 and sheet_dates[0] == effective_date:
        for r in rows[1:]:
            col_g = str(r[6]).strip() if len(r) > 6 else ""
            col_h = str(r[7]).strip() if len(r) > 7 else ""
            col_i = str(r[8]).strip() if len(r) > 8 else ""
            try:
                if col_g == "1 กิโลกรัม" and col_h:
                    tot_1kg = int(float(col_h.replace(",", "")))
                elif col_g == "500 กรัม" and col_h:
                    tot_500g = int(float(col_h.replace(",", "")))
                elif col_g == "60 กรัม" and col_h:
                    tot_60g = int(float(col_h.replace(",", "")))
                elif col_h == "Facebook" and col_i:
                    tot_facebook = float(col_i.replace(",", ""))
                elif col_h == "TikTok" and col_i:
                    tot_tiktok = float(col_i.replace(",", ""))
                elif col_h == "Shopee" and col_i:
                    tot_shopee = float(col_i.replace(",", ""))
                elif col_h == "โอน" and col_i:
                    tot_transfer = float(col_i.replace(",", ""))
                elif col_h == "COD" and col_i:
                    tot_cod = float(col_i.replace(",", ""))
            except ValueError:
                pass
    tot_pieces = tot_1kg + tot_500g + tot_60g
    grand_total = round(tot_transfer + tot_cod, 2)
    return {
        "target_date": effective_date, "order_count": len(order_rows),
        "tot_1kg": tot_1kg, "tot_500g": tot_500g, "tot_60g": tot_60g, "tot_pieces": tot_pieces,
        "tot_facebook": round(tot_facebook, 2), "tot_tiktok": round(tot_tiktok, 2), "tot_shopee": round(tot_shopee, 2),
        "tot_transfer": round(tot_transfer, 2), "tot_cod": round(tot_cod, 2), "grand_total": grand_total,
        "orders": [], "sheet_rows": rows, "source": "google_sheet",
    }


def load_or_build_daily_report(target_date: str) -> dict[str, Any]:
    jst_report: dict[str, Any] | None = None
    try:
        jst_report = build_daily_sales_sheet_rows(target_date)
        if jst_report and jst_report.get("order_count", 0) > 0:
            save_daily_report_snapshot(jst_report, sync_google_sheet=True)
    except Exception as exc:
        logger.info("JST live query skipped/fallback to Google Sheet for %s: %s", target_date, exc)
    sheet_report = fetch_report_from_google_sheet(target_date)
    if sheet_report and sheet_report.get("order_count", 0) >= (jst_report.get("order_count", 0) if jst_report else 0):
        return sheet_report
    if jst_report:
        return jst_report
    json_path = Path(__file__).resolve().parent.parent / "reports" / f"daily_sales_{target_date}.json"
    if json_path.exists():
        try:
            return json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "target_date": target_date, "order_count": 0, "tot_1kg": 0, "tot_500g": 0, "tot_60g": 0, "tot_pieces": 0,
        "tot_facebook": 0.0, "tot_tiktok": 0.0, "tot_shopee": 0.0, "tot_transfer": 0.0, "tot_cod": 0.0, "grand_total": 0.0,
        "orders": [], "sheet_rows": [],
    }


def send_daily_summary_to_line_groups(
    target_date: str | None = None,
    brand_id: str = "workbot",
    target_group_id: str | None = None,
    reply_token: str | None = None,
    mark_7am_done: bool = False,
) -> dict[str, Any]:
    from .messenger import LINE_PUSH_URL, LINE_REPLY_URL, _get_channel_token
    now_bkk = datetime.now(BKK_TZ)
    if not target_date:
        target_date = (now_bkk - timedelta(days=1)).strftime("%Y-%m-%d")
    report = load_or_build_daily_report(target_date)
    summary_text = format_line_group_daily_summary(report)
    token = _get_channel_token(brand_id, "line")
    if not token:
        return {"status": "error", "reason": "missing_line_channel_access_token", "target_date": target_date, "summary_text": summary_text}
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    msg_payload = [{"type": "text", "text": summary_text}]
    cfg = load_line_group_config()
    groups_to_send = [target_group_id] if target_group_id else list(cfg.get("groups") or [])
    sent_groups: list[str] = []
    errors: list[dict[str, Any]] = []
    with httpx.Client(timeout=15.0) as client:
        replied_ok = False
        if reply_token and target_group_id and not reply_token.startswith("sim_"):
            resp = client.post(LINE_REPLY_URL, headers=headers, json={"replyToken": reply_token, "messages": msg_payload})
            if resp.status_code == 200:
                replied_ok = True
                sent_groups.append(target_group_id)
        if not replied_ok:
            for gid in groups_to_send:
                if not gid:
                    continue
                resp = client.post(LINE_PUSH_URL, headers=headers, json={"to": gid, "messages": msg_payload})
                if resp.status_code == 200:
                    sent_groups.append(gid)
                else:
                    errors.append({"group_id": gid, "status_code": resp.status_code, "body": resp.text})
    if mark_7am_done and sent_groups:
        cfg["last_7am_report_date"] = target_date
        cfg["last_7am_sent_at"] = now_bkk.isoformat()
        save_line_group_config(cfg)
    return {
        "status": "ok" if sent_groups else ("no_groups_registered" if not groups_to_send else "error"),
        "target_date": target_date, "sent_groups": sent_groups, "errors": errors, "summary_text": summary_text,
        "report": {
            "order_count": report["order_count"], "tot_facebook": report["tot_facebook"], "tot_tiktok": report["tot_tiktok"],
            "tot_shopee": report["tot_shopee"], "tot_transfer": report["tot_transfer"], "tot_cod": report["tot_cod"],
            "grand_total": report["grand_total"], "tot_60g": report["tot_60g"], "tot_500g": report["tot_500g"],
            "tot_1kg": report["tot_1kg"], "tot_pieces": report["tot_pieces"],
        },
    }


def save_daily_report_snapshot(report: dict[str, Any], sync_google_sheet: bool = True) -> Path:
    import csv, shutil, subprocess
    out_dir = Path(__file__).resolve().parent.parent / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    target_date = report["target_date"]
    json_path = out_dir / f"daily_sales_{target_date}.json"
    tsv_path = out_dir / f"daily_sales_{target_date}.tsv"
    csv_path = out_dir / f"daily_sales_{target_date}.csv"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    tsv_lines = ["\t".join(str(c) for c in r) for r in report["sheet_rows"]]
    tsv_path.write_text("\n".join(tsv_lines), encoding="utf-8")
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        for row in report["sheet_rows"]:
            writer.writerow(row)
    gdrive_bin = shutil.which("gdrive")
    if sync_google_sheet and gdrive_bin:
        try:
            subprocess.run([gdrive_bin, "mutate", "update", GOOGLE_SHEET_FILE_ID, str(csv_path), "--mime-type", "application/vnd.google-apps.spreadsheet"], check=False, timeout=30)
        except Exception as exc:
            logger.warning("gdrive sheet update warning: %s", exc)
    REPORT_STATE_FILE.write_text(json.dumps({"last_report_date": target_date, "generated_at": datetime.now(BKK_TZ).isoformat(), "order_count": report["order_count"], "grand_total": report["grand_total"], "google_sheet_id": GOOGLE_SHEET_FILE_ID}, ensure_ascii=False, indent=2), encoding="utf-8")
    return csv_path
