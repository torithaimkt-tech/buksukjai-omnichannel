"""Media Catalog Manager for ข้าวบุกสุขใจ (Buk Sukjai).

STRICT RULE: NEVER generate synthetic table cards. ONLY use the official images
from `D:\\buksukjai\\pro buksukjai`:
- promo_3sizes  : โปรพิเศษ 3 ขนาด (60g 39.- / 500g 239.- / 1kg 459.-)
- promo_60g_set : โปรคุ้มที่สุด ขนาด 60g (1 ถุง 39.- / 15 ถุง 555.- ส่งฟรี / 20 ถุง 720.- ส่งฟรี)
- promo_899     : โปรตุนสุดคุ้ม ซื้อ 1 กก. 2 ถุง แถม 60g 2 ถุง = 899.- ส่งฟรี
- promo_1299    : โปรตุนสุดคุ้ม ซื้อ 1 กก. 3 ถุง แถม 60g 3 ถุง = 1,299.- ส่งฟรี
"""

import json
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"
MEDIA_DIR = STATIC_DIR / "media"
MEDIA_CATALOG_PATH = MEDIA_DIR / "catalog.json"
PRO_SOURCE_DIR = Path(r"D:\buksukjai\pro buksukjai")
MRBUK_LINE_OA_DIR = Path(r"D:\MrBuk Content\Mr buk line oa")

BANNED_GENERATED_FILES = (
    "promo_catalog.png",
    "product_photo.png",
    "how_to_cook.png",
    "payment_qr.png",
)

SOURCE_FILES_MAP = {
    "promo_3sizes.jpg": "833779260_1464046612289191_1677233490609810415_n.jpg",
    "promo_60g_set.jpg": "839008140_2022772361717236_6125442964393378345_n.jpg",
    "promo_899.jpg": "833296835_2006071957015432_4696061562761295679_n.jpg",
    "promo_1299.jpg": "833260523_1863026684665733_769880910253820938_n.jpg",
}

MRBUK_QR_FILES_MAP = {
    "MrBuk_QR_Give_1pt.png": "MrBuk_QR_Give_1pt.png",
    "MrBuk_QR_Give_2pt.png": "MrBuk_QR_Give_2pt.png",
    "MrBuk_QR_Give_4pt.png": "MrBuk_QR_Give_4pt.png",
}

DEFAULT_SLOTS = {
    "promo_3sizes": {
        "key": "promo_3sizes",
        "title": "โปรพิเศษ 3 ขนาด (39.- / 239.- / 459.-)",
        "subtitle": "รูปจริงจากโฟลเดอร์ pro buksukjai (ส่งเมื่อลูกค้าทักสนใจ/ถามราคา)",
        "filename": "promo_3sizes.jpg",
    },
    "promo_60g_set": {
        "key": "promo_60g_set",
        "title": "โปรซองพกพา 60g (1 ซอง 39.- / 15 ซอง 555.- / 20 ซอง 720.-)",
        "subtitle": "รูปจริงจากโฟลเดอร์ pro buksukjai (ซองเล็ก 60g / เซ็ต 15–20 ซอง)",
        "filename": "promo_60g_set.jpg",
    },
    "promo_899": {
        "key": "promo_899",
        "title": "โปรตุนสุดคุ้ม 2 แถม 2 (899.- ส่งฟรี)",
        "subtitle": "รูปจริงจากโฟลเดอร์ pro buksukjai (ซื้อ 1 กก. 2 ถุง แถม 60g 2 ถุง)",
        "filename": "promo_899.jpg",
    },
    "promo_1299": {
        "key": "promo_1299",
        "title": "โปรตุนสุดคุ้ม 3 แถม 3 (1,299.- ส่งฟรี)",
        "subtitle": "รูปจริงจากโฟลเดอร์ pro buksukjai (ซื้อ 1 กก. 3 ถุง แถม 60g 3 ถุง)",
        "filename": "promo_1299.jpg",
    },
    "mrbuk_qr_1pt": {
        "key": "mrbuk_qr_1pt",
        "title": "QR Code รับแต้ม มิสเตอร์บุก VIP (+1 แต้ม)",
        "subtitle": "สแกนรับ 1 แต้มเข้าบัตรสะสมแต้ม LINE OA @misterbuk (ยอดซื้อ 500.- / ถุง 1 กก. 490.- / เซ็ตคู่ 950.-)",
        "filename": "MrBuk_QR_Give_1pt.png",
    },
    "mrbuk_qr_2pt": {
        "key": "mrbuk_qr_2pt",
        "title": "QR Code รับแต้ม มิสเตอร์บุก VIP (+2 แต้ม)",
        "subtitle": "สแกนรับ 2 แต้มเข้าบัตรสะสมแต้ม LINE OA @misterbuk (ยอดซื้อ 1,000.- ขึ้นไป / เซ็ต 30 ซอง 1,190.-)",
        "filename": "MrBuk_QR_Give_2pt.png",
    },
    "mrbuk_qr_4pt": {
        "key": "mrbuk_qr_4pt",
        "title": "QR Code รับแต้ม มิสเตอร์บุก VIP (+4 แต้ม)",
        "subtitle": "สแกนรับ 4 แต้มเข้าบัตรสะสมแต้ม LINE OA @misterbuk (ยอดซื้อ 2,000.- ขึ้นไป / เซ็ตใหญ่ 5 กก. 2,390.-)",
        "filename": "MrBuk_QR_Give_4pt.png",
    },
}

KEY_ALIASES = {
    "promo_catalog": "promo_3sizes",
    "product_photo": "promo_3sizes",
    "how_to_cook": "promo_3sizes",
    "payment_qr": "promo_3sizes",
    "MrBuk_QR_Give_1pt.png": "mrbuk_qr_1pt",
    "MrBuk_QR_Give_2pt.png": "mrbuk_qr_2pt",
    "MrBuk_QR_Give_4pt.png": "mrbuk_qr_4pt",
    "qr_1pt": "mrbuk_qr_1pt",
    "qr_2pt": "mrbuk_qr_2pt",
    "qr_4pt": "mrbuk_qr_4pt",
}


def sync_official_promo_images() -> None:
    """Purge any old generated PNGs and sync official JPGs/PNGs from Buk Sukjai & Mr.Buk folders."""
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    for banned in BANNED_GENERATED_FILES:
        bp = MEDIA_DIR / banned
        if bp.exists():
            try:
                bp.unlink()
            except Exception:
                pass

    if PRO_SOURCE_DIR.exists():
        for dest_name, src_name in SOURCE_FILES_MAP.items():
            src_path = PRO_SOURCE_DIR / src_name
            dest_path = MEDIA_DIR / dest_name
            if src_path.exists() and not dest_path.exists():
                shutil.copy2(src_path, dest_path)

    if MRBUK_LINE_OA_DIR.exists():
        for dest_name, src_name in MRBUK_QR_FILES_MAP.items():
            src_path = MRBUK_LINE_OA_DIR / src_name
            dest_path = MEDIA_DIR / dest_name
            if src_path.exists() and not dest_path.exists():
                shutil.copy2(src_path, dest_path)


def load_media_catalog() -> dict:
    sync_official_promo_images()
    save_media_catalog(DEFAULT_SLOTS)
    return dict(DEFAULT_SLOTS)


def save_media_catalog(catalog: dict) -> None:
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    MEDIA_CATALOG_PATH.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")


def get_media_item(image_key: str) -> dict | None:
    resolved_key = KEY_ALIASES.get(image_key, image_key)
    catalog = load_media_catalog()
    item = catalog.get(resolved_key)
    if not item:
        return None
    if item["filename"] in BANNED_GENERATED_FILES:
        return None
    file_path = MEDIA_DIR / item["filename"]
    if not file_path.exists():
        return None
    return {
        **item,
        "local_path": str(file_path),
        "relative_url": f"/static/media/{item['filename']}",
    }


def get_all_promo_items() -> list[dict]:
    """Return all 4 official promo images in order."""
    items = []
    for k in ("promo_3sizes", "promo_60g_set", "promo_899", "promo_1299"):
        it = get_media_item(k)
        if it:
            items.append(it)
    return items


def resolve_media_items(image_key: str | None) -> list[dict]:
    """Resolve an image_key ('promo_3sizes', 'promo_all', etc.) into 1 or 4 official promo image dicts."""
    if not image_key or image_key == "none":
        return []
    if image_key == "promo_all":
        return get_all_promo_items()
    single = get_media_item(image_key)
    return [single] if single else []


def get_mrbuk_qr_media_for_points(points: int) -> list[dict]:
    """Return the official Mr.Buk LINE OA Point QR Code media item(s) matching `points` (using 4pt, 2pt, 1pt denominations).

    - 1 point  -> [MrBuk_QR_Give_1pt.png]
    - 2 points -> [MrBuk_QR_Give_2pt.png]
    - 3 points -> [MrBuk_QR_Give_2pt.png, MrBuk_QR_Give_1pt.png]
    - 4 points -> [MrBuk_QR_Give_4pt.png]
    - etc. (capped at 4 images per LINE reply batch).
    """
    sync_official_promo_images()
    remaining = max(0, int(points))
    if remaining <= 0:
        return []

    denominations = [
        (4, "mrbuk_qr_4pt"),
        (2, "mrbuk_qr_2pt"),
        (1, "mrbuk_qr_1pt"),
    ]
    selected: list[dict] = []
    for denom, slot_key in denominations:
        while remaining >= denom and len(selected) < 4:
            item = get_media_item(slot_key)
            if not item:
                break
            selected.append(item)
            remaining -= denom
    return selected
