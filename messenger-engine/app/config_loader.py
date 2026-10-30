"""Loads and validates brand configs and the 5-page omnichannel registry.
The engine itself is brand-agnostic: every persona, product, price, and rule
comes from config.json (or per-page config files).
"""

import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = BASE_DIR / "config.json"
PAGES_REGISTRY_PATH = BASE_DIR / "pages.json"
DEFAULT_PAGES_REGISTRY_PATH = BASE_DIR / "pages.default.json"

REQUIRED_TOP_LEVEL_KEYS = ("brand_persona", "products", "knowledge_base")
REQUIRED_PERSONA_KEYS = ("brand_name", "bot_name", "tone_of_voice", "greeting_message")


class ConfigError(Exception):
    """Raised when config.json is missing or malformed."""


def load_config(config_path: str | Path | None = None) -> dict:
    path = Path(config_path or os.getenv("CONFIG_PATH") or DEFAULT_CONFIG_PATH)
    if not path.is_absolute():
        path = BASE_DIR / path
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")

    try:
        with open(path, encoding="utf-8") as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        raise ConfigError(f"Config file is not valid JSON: {e}") from e

    for key in REQUIRED_TOP_LEVEL_KEYS:
        if key not in config:
            raise ConfigError(f"Config is missing required key: '{key}'")
    for key in REQUIRED_PERSONA_KEYS:
        if key not in config["brand_persona"]:
            raise ConfigError(f"brand_persona is missing required key: '{key}'")
    if not config["products"]:
        raise ConfigError("Config must define at least one product")

    return config


def load_pages_registry() -> list[dict]:
    """Load the page configuration registry from pages.json or pages.default.json, merging env vars."""
    target_path = PAGES_REGISTRY_PATH if PAGES_REGISTRY_PATH.exists() else DEFAULT_PAGES_REGISTRY_PATH
    if not target_path.exists():
        return [
            {
                "brand_id": "buksukjai",
                "slot": 1,
                "name": "ข้าวบุกสุขใจ (@602xbpha)",
                "active": True,
                "config_file": "config.json",
                "channels": {
                    "line_channel_secret": os.getenv("LINE_CHANNEL_SECRET", ""),
                    "line_channel_access_token": os.getenv("LINE_CHANNEL_ACCESS_TOKEN", ""),
                    "fb_page_id": os.getenv("FB_PAGE_ID", "806129109240845"),
                    "fb_page_access_token": os.getenv("PAGE_ACCESS_TOKEN", ""),
                    "ig_account_id": os.getenv("IG_ACCOUNT_ID", ""),
                    "ig_access_token": os.getenv("IG_ACCESS_TOKEN", ""),
                },
            }
        ]
    with open(target_path, encoding="utf-8") as f:
        data = json.load(f)
    pages = [p for p in data.get("pages", []) if p.get("brand_id") != "pordisuk"]
    for idx, p in enumerate(pages, start=1):
        p["slot"] = idx
        if p.get("brand_id") == "buksukjai":
            ch = p.setdefault("channels", {})
            if not ch.get("line_channel_secret"):
                ch["line_channel_secret"] = os.getenv("LINE_CHANNEL_SECRET", "")
            if not ch.get("line_channel_access_token"):
                ch["line_channel_access_token"] = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
            if not ch.get("fb_page_id"):
                ch["fb_page_id"] = os.getenv("FB_PAGE_ID", "806129109240845")
            if not ch.get("fb_page_access_token"):
                ch["fb_page_access_token"] = os.getenv("PAGE_ACCESS_TOKEN", "")
        elif p.get("brand_id") == "workbot":
            ch = p.setdefault("channels", {})
            if not ch.get("line_channel_secret"):
                ch["line_channel_secret"] = os.getenv("WORKBOT_LINE_CHANNEL_SECRET", "31c6946f80249c4ce55213c996d97cf9")
            if not ch.get("line_channel_access_token"):
                ch["line_channel_access_token"] = os.getenv(
                    "WORKBOT_LINE_CHANNEL_ACCESS_TOKEN",
                    "eDkS5MNncETiXi7yvVJ4Cj4kGwKvZ7qfN94SV5uexiHVzNpc0QpoYdKwlrWEPHpKlJqPWnEmMCNxl+iVcCrUB5r7vDHLsbrZ1UJSTKZp5vtT7EJvo5NC2ZKAfb1AkO0E/3bQ2r+OoZPJTkah2HSR/AdB04t89/1O/w1cDnyilFU=",
                )
    if not any(p.get("brand_id") == "workbot" for p in pages):
        pages.append(
            {
                "brand_id": "workbot",
                "slot": len(pages) + 1,
                "name": "GENIUS POINT (@934ndvfs)",
                "active": True,
                "config_file": "config.json",
                "channels": {
                    "line_channel_secret": os.getenv("WORKBOT_LINE_CHANNEL_SECRET", "31c6946f80249c4ce55213c996d97cf9"),
                    "line_channel_access_token": os.getenv(
                        "WORKBOT_LINE_CHANNEL_ACCESS_TOKEN",
                        "eDkS5MNncETiXi7yvVJ4Cj4kGwKvZ7qfN94SV5uexiHVzNpc0QpoYdKwlrWEPHpKlJqPWnEmMCNxl+iVcCrUB5r7vDHLsbrZ1UJSTKZp5vtT7EJvo5NC2ZKAfb1AkO0E/3bQ2r+OoZPJTkah2HSR/AdB04t89/1O/w1cDnyilFU=",
                    ),
                    "fb_page_id": "",
                    "fb_page_access_token": "",
                    "ig_account_id": "",
                    "ig_access_token": "",
                },
            }
        )
    return pages


def save_pages_registry(pages: list[dict]) -> None:
    """Persist updated 5-page settings to pages.json."""
    with open(PAGES_REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump({"pages": pages}, f, ensure_ascii=False, indent=2)


def get_page_by_brand_id(brand_id: str) -> dict:
    pages = load_pages_registry()
    for p in pages:
        if p["brand_id"] == brand_id:
            return p
    return pages[0]


def resolve_brand_by_meta_id(recipient_id: str, platform: str = "facebook") -> str:
    """Match an incoming Facebook Page ID or IG Account ID to one of the 5 pages."""
    if not recipient_id:
        return "buksukjai"
    pages = load_pages_registry()
    key = "ig_account_id" if platform == "instagram" else "fb_page_id"
    for p in pages:
        if p.get("channels", {}).get(key) == recipient_id:
            return p["brand_id"]
    return "buksukjai"
