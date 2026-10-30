"""AI Process 1 — Daily Sales & Warehouse Stock Reconciliation Report (สรุปยอดขายรายวันเวลา 01:00 น.).

Generates the daily sales & SKU unit breakdown for the previous day (or any target date YYYY-MM-DD)
from JST ERP (`NewQueryOrders`), separating:
- Product quantities by physical size (`1 กิโลกรัม`, `500 กรัม`, `60 กรัม`) for warehouse stock reconciliation
- Payment totals into separate cells (`โอน` vs `COD` vs `รวมทั้งสิ้น`)
"""

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
DAILY_REPORT_HOUR_BKK = 1  # 01:00 AM Bangkok time (สรุปยอดของเมื่อวานทั้งหมด)
REPORT_STATE_FILE = Path(__file__).resolve().parent.parent / "daily_report_state.json"


def parse_sku_physical_counts(skus_list: list[Any]) -> tuple[str, int, int, int, int]:
    """Return `(sku_code_str, total_pieces, count_1kg, count_500g, count_60g)`."""
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
    """Fetch all non-cancelled orders for `target_date` (`YYYY-MM-DD`) and build table rows + summary cells."""
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
        "ลำดับ",
        "วันที่สั่งซื้อ",
        "ช่องทาง",
        "ชื่อลูกค้า",
        "ที่อยู่จัดส่ง",
        "เบอร์โทรศัพท์",
        "รหัส SKU",
        "จำนวนสินค้า",
        "จำนวนเงิน (บาท)",
        "รูปแบบการชำระเงิน",
        "เลขออเดอร์ JST / เลขพัสดุ",
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

        row = [
            idx,
            target_date,
            channel,
            cust_name,
            addr,
            phone_cell,
            sku_str,
            pieces,
            amt,
            pay_label,
            jst_col,
        ]
        table_rows.append(row)
        order_items_out.append(
            {
                "seq": idx,
                "date": target_date,
                "channel": channel,
                "customer_name": cust_name,
                "address": addr,
                "phone": phone,
                "sku": sku_str,
                "qty_pieces": pieces,
                "qty_1kg": k1,
                "qty_500g": g500,
                "qty_60g": g60,
                "amount": amt,
                "payment_method": pay_label,
                "order_id": order_id,
                "tracking": tracking,
                "status": status_disp,
            }
        )

    tot_pieces = tot_1kg + tot_500g + tot_60g
    grand_total = round(tot_transfer + tot_cod, 2)

    # Blank separator row
    table_rows.append(["", "", "", "", "", "", "", "", "", "", ""])

    # Warehouse Stock Summary by size (Label in Col G, Quantity in Col H under จำนวนสินค้า)
    table_rows.append(["", "", "", "", "", "", "1 กิโลกรัม", tot_1kg, "", "", ""])
    table_rows.append(["", "", "", "", "", "", "500 กรัม", tot_500g, "", "", ""])
    table_rows.append(["", "", "", "", "", "", "60 กรัม", tot_60g, "", "", ""])
    table_rows.append(["", "", "", "", "", "", "รวมจำนวนสินค้าทั้งหมด", tot_pieces, "", "", ""])

    # Blank separator row
    table_rows.append(["", "", "", "", "", "", "", "", "", "", ""])

    # Channel Sales Summary in separate cells (Label in Col H, Amount in Col I under จำนวนเงิน)
    table_rows.append(["", "", "", "", "", "", "", "Facebook", round(tot_facebook, 2), "", ""])
    table_rows.append(["", "", "", "", "", "", "", "TikTok", round(tot_tiktok, 2), "", ""])
    if tot_shopee > 0:
        table_rows.append(["", "", "", "", "", "", "", "Shopee", round(tot_shopee, 2), "", ""])

    # Blank separator row
    table_rows.append(["", "", "", "", "", "", "", "", "", "", ""])

    # Payment Summary in separate cells (Label in Col H, Amount in Col I under จำนวนเงิน)
    table_rows.append(["", "", "", "", "", "", "", "โอน", round(tot_transfer, 2), "", ""])
    table_rows.append(["", "", "", "", "", "", "", "COD", round(tot_cod, 2), "", ""])
    table_rows.append(["", "", "", "", "", "", "", "รวมทั้งสิ้น", grand_total, "", ""])

    return {
        "target_date": target_date,
        "order_count": len(order_items_out),
        "tot_1kg": tot_1kg,
        "tot_500g": tot_500g,
        "tot_60g": tot_60g,
        "tot_pieces": tot_pieces,
        "tot_facebook": round(tot_facebook, 2),
        "tot_tiktok": round(tot_tiktok, 2),
        "tot_shopee": round(tot_shopee, 2),
        "tot_transfer": round(tot_transfer, 2),
        "tot_cod": round(tot_cod, 2),
        "grand_total": grand_total,
        "orders": order_items_out,
        "sheet_rows": table_rows,
    }


def should_run_daily_1am_report() -> tuple[bool, str]:
    """Return `(True, yesterday_str)` if current Bangkok hour is 01:00 and yesterday's report hasn't been generated yet."""
    now_bkk = datetime.now(BKK_TZ)
    yesterday_str = (now_bkk - timedelta(days=1)).strftime("%Y-%m-%d")
    if now_bkk.hour != DAILY_REPORT_HOUR_BKK:
        return False, yesterday_str
    state: dict[str, Any] = {}
    if REPORT_STATE_FILE.exists():
        try:
            state = json.loads(REPORT_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            state = {}
    return state.get("last_report_date") != yesterday_str, yesterday_str


GOOGLE_SHEET_FILE_ID = "1mMO_aZnaCaDskrJMreJiaonFqna-WNKBhOoozAWxIhE"


def save_daily_report_snapshot(report: dict[str, Any], sync_google_sheet: bool = True) -> Path:
    """Save the daily report JSON, TSV & CSV snapshot, and auto-update the connected Google Sheet via gdrive CLI."""
    import csv
    import shutil
    import subprocess

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
            subprocess.run(
                [
                    gdrive_bin,
                    "mutate",
                    "update",
                    GOOGLE_SHEET_FILE_ID,
                    str(csv_path),
                    "--mime-type",
                    "application/vnd.google-apps.spreadsheet",
                ],
                check=False,
                timeout=30,
            )
        except Exception as exc:
            logger.warning("gdrive sheet update warning: %s", exc)

    REPORT_STATE_FILE.write_text(
        json.dumps(
            {
                "last_report_date": target_date,
                "generated_at": datetime.now(BKK_TZ).isoformat(),
                "order_count": report["order_count"],
                "grand_total": report["grand_total"],
                "google_sheet_id": GOOGLE_SHEET_FILE_ID,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return csv_path
