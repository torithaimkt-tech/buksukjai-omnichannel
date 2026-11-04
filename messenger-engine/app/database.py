"""Omnichannel Session & State Tracker — SQLite via SQLAlchemy.

Tracks each customer across LINE OA, Facebook Messenger, Instagram DM, and Web
 across up to 5 Pages/Brands, including order state, AI bot toggle (Human Handover),
customer display name, notes, and full message log.
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import Boolean, DateTime, Integer, String, Text, create_engine, inspect, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

logger = logging.getLogger(__name__)

PERSISTENT_SNAPSHOT_PATH = Path(__file__).resolve().parent.parent / "db_persistent_snapshot.json"


def _normalize_database_url(raw_url: str) -> str:
    url = (raw_url or "").strip() or "sqlite:///chatbot.db"
    if url.startswith("postgres://"):
        url = "postgresql+psycopg2://" + url[len("postgres://") :]
    elif url.startswith("postgresql://") and "+psycopg" not in url:
        url = "postgresql+psycopg2://" + url[len("postgresql://") :]
    return url


DATABASE_URL = _normalize_database_url(
    os.getenv("EXTERNAL_DATABASE_URL") or os.getenv("POSTGRES_URL") or os.getenv("DATABASE_URL", "sqlite:///chatbot.db")
)
_IS_SQLITE = DATABASE_URL.startswith("sqlite")


def _build_engine(db_url: str):
    global _IS_SQLITE
    if db_url.startswith("sqlite"):
        _IS_SQLITE = True
        return create_engine(db_url, connect_args={"check_same_thread": False})
    try:
        _IS_SQLITE = False
        eng = create_engine(
            db_url,
            pool_pre_ping=True,
            pool_recycle=300,
            pool_size=5,
            max_overflow=10,
        )
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Connected to persistent PostgreSQL database successfully.")
        return eng
    except Exception as exc:
        logger.warning("PostgreSQL connection failed (%s); falling back to local SQLite with persistent snapshot.", exc)
        _IS_SQLITE = True
        return create_engine("sqlite:///chatbot.db", connect_args={"check_same_thread": False})


engine = _build_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

VALID_STATES = ("browsing", "pending_payment", "completed")
VALID_PLATFORMS = ("line", "facebook", "instagram", "web")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class UserSession(Base):
    __tablename__ = "user_sessions"

    psid: Mapped[str] = mapped_column(String(128), primary_key=True)
    brand_id: Mapped[str] = mapped_column(String(64), default="buksukjai", index=True)
    platform: Mapped[str] = mapped_column(String(32), default="facebook", index=True)
    external_user_id: Mapped[str] = mapped_column(String(128), default="")
    customer_name: Mapped[str] = mapped_column(String(128), default="ลูกค้าใหม่")
    state: Mapped[str] = mapped_column(String(32), default="browsing")
    is_starred: Mapped[bool] = mapped_column(Boolean, default=False)
    bot_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    unread_count: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str] = mapped_column(Text, default="")
    broadcast_tags: Mapped[str] = mapped_column(Text, default="")
    purchased_sku: Mapped[str] = mapped_column(String(64), default="BSJ1KG1")
    purchased_qty: Mapped[int] = mapped_column(Integer, default=1)
    purchased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    after_sales_stage: Mapped[int] = mapped_column(Integer, default=0)
    last_interaction_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    followup_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MessageLog(Base):
    __tablename__ = "message_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    psid: Mapped[str] = mapped_column(String(128), index=True)
    role: Mapped[str] = mapped_column(String(16))  # "user" | "assistant" | "admin"
    sender_label: Mapped[str] = mapped_column(String(64), default="")
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LoyaltyMember(Base):
    """Tracks customer loyalty points for Mr.Buk VIP (@misterbuk / @305lhvvt) linked by 10-digit phone number."""

    __tablename__ = "loyalty_members"

    phone: Mapped[str] = mapped_column(String(16), primary_key=True)
    brand_id: Mapped[str] = mapped_column(String(64), default="mrbuk", index=True)
    customer_name: Mapped[str] = mapped_column(String(128), default="")
    line_user_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    fb_psid: Mapped[str] = mapped_column(String(128), default="")
    total_points: Mapped[int] = mapped_column(Integer, default=0)
    lifetime_points: Mapped[int] = mapped_column(Integer, default=0)
    lifetime_spend_thb: Mapped[int] = mapped_column(Integer, default=0)
    carryover_thb: Mapped[int] = mapped_column(Integer, default=0)
    pending_reward: Mapped[str] = mapped_column(Text, default="")
    redeemed_history: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LoyaltyClaimedOrder(Base):
    """Prevents duplicate bill claiming across Facebook (chatbot.db) and JST ERP orders."""

    __tablename__ = "loyalty_claimed_orders"

    order_ref: Mapped[str] = mapped_column(String(128), primary_key=True)
    brand_id: Mapped[str] = mapped_column(String(64), default="mrbuk", index=True)
    phone: Mapped[str] = mapped_column(String(16), index=True)
    customer_name: Mapped[str] = mapped_column(String(128), default="")
    claimed_by_line_user_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    source: Mapped[str] = mapped_column(String(32), default="chatbot_db")  # "jst_erp" | "chatbot_db" | "admin_manual"
    order_amount_thb: Mapped[int] = mapped_column(Integer, default=0)
    points_awarded: Mapped[int] = mapped_column(Integer, default=0)
    qr_images_sent: Mapped[str] = mapped_column(String(256), default="")
    order_date: Mapped[str] = mapped_column(String(64), default="")
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


def init_db() -> None:
    Base.metadata.create_all(engine)
    _ensure_columns()
    restore_persistent_snapshot_if_needed()


def _ensure_columns() -> None:
    """Auto-migrate existing SQLite or PostgreSQL tables if upgraded from an older version."""
    inspector = inspect(engine)
    ts_col_type = "DATETIME NULL" if _IS_SQLITE else "TIMESTAMP WITH TIME ZONE NULL"
    if "user_sessions" in inspector.get_table_names():
        existing = {c["name"] for c in inspector.get_columns("user_sessions")}
        migrations = [
            ("brand_id", "VARCHAR(64) DEFAULT 'buksukjai'"),
            ("platform", "VARCHAR(32) DEFAULT 'facebook'"),
            ("external_user_id", "VARCHAR(128) DEFAULT ''"),
            ("customer_name", "VARCHAR(128) DEFAULT 'ลูกค้าใหม่'"),
            ("is_starred", "BOOLEAN DEFAULT FALSE"),
            ("bot_enabled", "BOOLEAN DEFAULT TRUE"),
            ("unread_count", "INTEGER DEFAULT 0"),
            ("notes", "TEXT DEFAULT ''"),
            ("broadcast_tags", "TEXT DEFAULT ''"),
            ("purchased_sku", "VARCHAR(64) DEFAULT 'BSJ1KG1'"),
            ("purchased_qty", "INTEGER DEFAULT 1"),
            ("purchased_at", ts_col_type),
            ("after_sales_stage", "INTEGER DEFAULT 0"),
        ]
        with engine.begin() as conn:
            for col_name, col_def in migrations:
                if col_name not in existing:
                    conn.execute(text(f"ALTER TABLE user_sessions ADD COLUMN {col_name} {col_def}"))
            conn.execute(
                text(
                    "UPDATE user_sessions SET is_starred = TRUE "
                    "WHERE state = 'completed' OR broadcast_tags LIKE '%ชำระเงินแล้ว%' OR broadcast_tags LIKE '%ติดดาว%'"
                )
            )

    if "message_log" in inspector.get_table_names():
        existing_msg = {c["name"] for c in inspector.get_columns("message_log")}
        with engine.begin() as conn:
            if "sender_label" not in existing_msg:
                conn.execute(text("ALTER TABLE message_log ADD COLUMN sender_label VARCHAR(64) DEFAULT ''"))


def _parse_iso_dt(val: str | None) -> datetime | None:
    if not val:
        return None
    try:
        return datetime.fromisoformat(val)
    except Exception:
        return None


def save_persistent_snapshot() -> None:
    """Persist all Omnichannel sessions, messages, and loyalty records to db_persistent_snapshot.json."""
    try:
        with SessionLocal() as db:
            all_sessions = db.execute(select(UserSession)).scalars().all()
            all_msgs = db.execute(select(MessageLog).order_by(MessageLog.id.asc())).scalars().all()
            loyalty_members = db.execute(select(LoyaltyMember)).scalars().all()
            loyalty_claims = db.execute(select(LoyaltyClaimedOrder)).scalars().all()

            payload = {
                "updated_at": utcnow().isoformat(),
                "sessions": [
                    {
                        "psid": s.psid,
                        "brand_id": s.brand_id,
                        "platform": s.platform,
                        "external_user_id": s.external_user_id,
                        "customer_name": s.customer_name,
                        "state": s.state,
                        "is_starred": bool(s.is_starred),
                        "bot_enabled": bool(s.bot_enabled),
                        "unread_count": s.unread_count or 0,
                        "notes": s.notes or "",
                        "broadcast_tags": s.broadcast_tags or "",
                        "purchased_sku": s.purchased_sku or "BSJ1KG1",
                        "purchased_qty": s.purchased_qty or 1,
                        "purchased_at": s.purchased_at.isoformat() if s.purchased_at else None,
                        "after_sales_stage": s.after_sales_stage or 0,
                        "last_interaction_time": s.last_interaction_time.isoformat() if s.last_interaction_time else None,
                        "followup_sent_at": s.followup_sent_at.isoformat() if s.followup_sent_at else None,
                        "created_at": s.created_at.isoformat() if s.created_at else None,
                    }
                    for s in all_sessions
                ],
                "messages": [
                    {
                        "psid": m.psid,
                        "role": m.role,
                        "sender_label": m.sender_label or "",
                        "content": m.content[:4000] if m.content else "",
                        "created_at": m.created_at.isoformat() if m.created_at else None,
                    }
                    for m in all_msgs
                    if m.content and not str(m.content).startswith("data:image/")
                ],
                "loyalty_members": [
                    {
                        "phone": lm.phone,
                        "brand_id": lm.brand_id,
                        "customer_name": lm.customer_name,
                        "line_user_id": lm.line_user_id,
                        "fb_psid": lm.fb_psid,
                        "total_points": lm.total_points,
                        "lifetime_points": lm.lifetime_points,
                        "lifetime_spend_thb": lm.lifetime_spend_thb,
                        "carryover_thb": lm.carryover_thb,
                        "pending_reward": lm.pending_reward,
                        "redeemed_history": lm.redeemed_history,
                    }
                    for lm in loyalty_members
                ],
                "loyalty_claimed_orders": [
                    {
                        "order_ref": lc.order_ref,
                        "brand_id": lc.brand_id,
                        "phone": lc.phone,
                        "customer_name": lc.customer_name,
                        "claimed_by_line_user_id": lc.claimed_by_line_user_id,
                        "source": lc.source,
                        "order_amount_thb": lc.order_amount_thb,
                        "points_awarded": lc.points_awarded,
                        "qr_images_sent": lc.qr_images_sent,
                        "order_date": lc.order_date,
                    }
                    for lc in loyalty_claims
                ],
            }
        with open(PERSISTENT_SNAPSHOT_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.warning("Failed to save persistent DB snapshot: %s", exc)


def restore_persistent_snapshot_if_needed() -> None:
    """Restore all Omnichannel sessions, messages, and loyalty records from db_persistent_snapshot.json if missing."""
    if not PERSISTENT_SNAPSHOT_PATH.exists():
        return
    try:
        with open(PERSISTENT_SNAPSHOT_PATH, encoding="utf-8") as f:
            data = json.load(f)
        with SessionLocal() as db:
            existing_psids = set(db.execute(select(UserSession.psid)).scalars().all())
            restored_sessions = 0
            for s in data.get("sessions", []):
                psid = s.get("psid")
                if not psid or psid in existing_psids:
                    continue
                existing_psids.add(psid)
                db.add(
                    UserSession(
                        psid=psid,
                        brand_id=s.get("brand_id", "buksukjai"),
                        platform=s.get("platform", "line"),
                        external_user_id=s.get("external_user_id", ""),
                        customer_name=s.get("customer_name", "ลูกค้า LINE"),
                        state=s.get("state", "browsing"),
                        is_starred=bool(s.get("is_starred", False)),
                        bot_enabled=bool(s.get("bot_enabled", True)),
                        unread_count=int(s.get("unread_count", 0)),
                        notes=s.get("notes", ""),
                        broadcast_tags=s.get("broadcast_tags", ""),
                        purchased_sku=s.get("purchased_sku", "BSJ1KG1"),
                        purchased_qty=int(s.get("purchased_qty", 1)),
                        purchased_at=_parse_iso_dt(s.get("purchased_at")),
                        after_sales_stage=int(s.get("after_sales_stage", 0)),
                        last_interaction_time=_parse_iso_dt(s.get("last_interaction_time")) or utcnow(),
                        followup_sent_at=_parse_iso_dt(s.get("followup_sent_at")),
                        created_at=_parse_iso_dt(s.get("created_at")) or utcnow(),
                    )
                )
                restored_sessions += 1

            existing_msg_keys = {
                (row[0], row[1], row[2])
                for row in db.execute(select(MessageLog.psid, MessageLog.role, MessageLog.content)).all()
            }
            for m in data.get("messages", []):
                psid = m.get("psid")
                role = m.get("role", "user")
                content = m.get("content", "")
                if not psid or not content:
                    continue
                key = (psid, role, content)
                if key not in existing_msg_keys:
                    existing_msg_keys.add(key)
                    db.add(
                        MessageLog(
                            psid=psid,
                            role=role,
                            sender_label=m.get("sender_label", ""),
                            content=content,
                            created_at=_parse_iso_dt(m.get("created_at")) or utcnow(),
                        )
                    )

            for lm in data.get("loyalty_members", []):
                phone = lm.get("phone")
                if phone and db.get(LoyaltyMember, phone) is None:
                    db.add(
                        LoyaltyMember(
                            phone=phone,
                            brand_id=lm.get("brand_id", "mrbuk"),
                            customer_name=lm.get("customer_name", ""),
                            line_user_id=lm.get("line_user_id", ""),
                            fb_psid=lm.get("fb_psid", ""),
                            total_points=int(lm.get("total_points", 0)),
                            lifetime_points=int(lm.get("lifetime_points", 0)),
                            lifetime_spend_thb=int(lm.get("lifetime_spend_thb", 0)),
                            carryover_thb=int(lm.get("carryover_thb", 0)),
                            pending_reward=lm.get("pending_reward", ""),
                            redeemed_history=lm.get("redeemed_history", ""),
                        )
                    )

            for lc in data.get("loyalty_claimed_orders", []):
                ref = lc.get("order_ref")
                if ref and db.get(LoyaltyClaimedOrder, ref) is None:
                    db.add(
                        LoyaltyClaimedOrder(
                            order_ref=ref,
                            brand_id=lc.get("brand_id", "mrbuk"),
                            phone=lc.get("phone", ""),
                            customer_name=lc.get("customer_name", ""),
                            claimed_by_line_user_id=lc.get("claimed_by_line_user_id", ""),
                            source=lc.get("source", "chatbot_db"),
                            order_amount_thb=int(lc.get("order_amount_thb", 0)),
                            points_awarded=int(lc.get("points_awarded", 0)),
                            qr_images_sent=lc.get("qr_images_sent", ""),
                            order_date=lc.get("order_date", ""),
                        )
                    )
            db.commit()
            if restored_sessions > 0:
                logger.info("Restored %d LINE OA sessions from persistent snapshot.", restored_sessions)
    except Exception as exc:
        logger.warning("Failed to restore persistent DB snapshot: %s", exc)


def get_database_status() -> dict:
    """Return current database backend type (PostgreSQL vs SQLite) and record counts."""
    with SessionLocal() as db:
        total_sessions = len(db.execute(select(UserSession.psid)).scalars().all())
        line_sessions = len(
            db.execute(select(UserSession.psid).where(UserSession.platform == "line")).scalars().all()
        )
        loyalty_count = len(db.execute(select(LoyaltyMember.phone)).scalars().all())
    return {
        "backend": "sqlite_with_snapshot" if _IS_SQLITE else "postgresql",
        "is_persistent_postgres": not _IS_SQLITE,
        "snapshot_file_exists": PERSISTENT_SNAPSHOT_PATH.exists(),
        "total_sessions": total_sessions,
        "line_sessions": line_sessions,
        "loyalty_members": loyalty_count,
    }


def make_session_key(brand_id: str, platform: str, external_user_id: str) -> str:
    """Create a unique composite key per brand + platform + user."""
    if ":" in external_user_id:
        return external_user_id
    return f"{brand_id}:{platform}:{external_user_id}"


def get_or_create_session(
    psid: str,
    brand_id: str = "buksukjai",
    platform: str = "facebook",
    external_user_id: str = "",
    customer_name: str = "",
) -> UserSession:
    with SessionLocal() as db:
        user = db.get(UserSession, psid)
        if user is None:
            ext_id = external_user_id or psid.split(":")[-1]
            default_name = customer_name or f"ลูกค้า {platform.upper()} ({ext_id[-4:]})"
            user = UserSession(
                psid=psid,
                brand_id=brand_id,
                platform=platform,
                external_user_id=ext_id,
                customer_name=default_name,
                bot_enabled=True,
                unread_count=0,
                notes="",
            )
            db.add(user)
            db.commit()
        else:
            changed = False
            if customer_name and (not user.customer_name or user.customer_name.startswith("ลูกค้า ")):
                user.customer_name = customer_name
                changed = True
            if not user.external_user_id:
                user.external_user_id = external_user_id or psid.split(":")[-1]
                changed = True
            if changed:
                db.commit()
        return user


def log_message(psid: str, role: str, content: str, sender_label: str = "") -> None:
    if role == "assistant" and content and not content.startswith("[IMAGE:"):
        from .llm import clean_chat_text

        content = clean_chat_text(content)
    with SessionLocal() as db:
        db.add(MessageLog(psid=psid, role=role, content=content, sender_label=sender_label))
        user = db.get(UserSession, psid)
        if user is not None:
            # Do not bump last_interaction_time for automated background follow-up/after-sales/re-engagement messages,
            # so old completed orders never look newly active to daily batch jobs.
            is_automated_bg = any(
                tag in (sender_label or "")
                for tag in ("AI บริการหลังการขาย", "AI บอทขุดแชท", "AI แจ้งสถานะพัสดุ", "AI ติดตาม")
            )
            if not is_automated_bg:
                user.last_interaction_time = utcnow()
            if role == "user":
                user.followup_sent_at = None  # new activity resets the follow-up clock
                user.unread_count = (user.unread_count or 0) + 1
            elif role == "admin":
                user.unread_count = 0
        db.commit()
    if _IS_SQLITE and ":line:" in (psid or ""):
        save_persistent_snapshot()


def get_history(psid: str, limit: int = 30) -> list[dict]:
    """Return the most recent messages for LLM context (admin messages map to assistant)."""
    from .llm import clean_chat_text

    with SessionLocal() as db:
        rows = db.execute(
            select(MessageLog)
            .where(MessageLog.psid == psid)
            .order_by(MessageLog.id.desc())
            .limit(limit)
        ).scalars().all()
    return [
        {
            "role": "user" if r.role == "user" else "assistant",
            "content": (
                clean_chat_text(r.content)
                if (r.role != "user" and r.content and not r.content.startswith("[IMAGE:"))
                else r.content
            ),
        }
        for r in reversed(rows)
    ]


def get_full_messages(psid: str, limit: int = 100) -> list[dict]:
    """Return full message logs with timestamps and sender role for Admin UI."""
    from .llm import clean_chat_text

    with SessionLocal() as db:
        rows = db.execute(
            select(MessageLog)
            .where(MessageLog.psid == psid)
            .order_by(MessageLog.id.desc())
            .limit(limit)
        ).scalars().all()
    return [
        {
            "id": r.id,
            "role": r.role,
            "sender_label": r.sender_label or ("ลูกค้า" if r.role == "user" else ("แอดมิน" if r.role == "admin" else "AI น้องบุก")),
            "content": (
                clean_chat_text(r.content)
                if (r.role == "assistant" and r.content and not r.content.startswith("[IMAGE:"))
                else r.content
            ),
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in reversed(rows)
    ]


def list_all_sessions(brand_id: str | None = None, platform: str | None = None, state: str | None = None) -> list[dict]:
    """Return all tracked sessions ordered by most recent interaction first, including last message preview."""
    with SessionLocal() as db:
        allowed_brands = ("buksukjai", "mrbuk", "pada", "aify", "workbot", "coachbot")
        stmt = select(UserSession).where(UserSession.brand_id.in_(allowed_brands)).order_by(UserSession.last_interaction_time.desc())
        if brand_id and brand_id != "all":
            stmt = stmt.where(UserSession.brand_id == brand_id)
        if platform and platform != "all":
            stmt = stmt.where(UserSession.platform == platform)
        if state and state != "all":
            if state == "starred":
                stmt = stmt.where((UserSession.is_starred.is_(True)) | (UserSession.state == "completed"))
            else:
                stmt = stmt.where(UserSession.state == state)

        rows = db.execute(stmt).scalars().all()
        result = []
        for r in rows:
            last_msg = db.execute(
                select(MessageLog)
                .where(MessageLog.psid == r.psid)
                .order_by(MessageLog.id.desc())
                .limit(1)
            ).scalars().first()
            is_star = bool(getattr(r, "is_starred", False) or r.state == "completed" or "ชำระเงินแล้ว" in (r.broadcast_tags or "") or "ติดดาว" in (r.broadcast_tags or ""))
            result.append(
                {
                    "psid": r.psid,
                    "brand_id": r.brand_id or "buksukjai",
                    "platform": r.platform or "facebook",
                    "external_user_id": r.external_user_id or r.psid,
                    "customer_name": r.customer_name or f"ลูกค้า ({r.psid[-4:]})",
                    "state": r.state,
                    "is_starred": is_star,
                    "bot_enabled": bool(r.bot_enabled if r.bot_enabled is not None else True),
                    "unread_count": r.unread_count or 0,
                    "notes": r.notes or "",
                    "broadcast_tags": r.broadcast_tags or "",
                    "purchased_sku": r.purchased_sku or "BSJ1KG1",
                    "purchased_qty": r.purchased_qty or 1,
                    "purchased_at": r.purchased_at.isoformat() if r.purchased_at else None,
                    "after_sales_stage": r.after_sales_stage or 0,
                    "last_message": last_msg.content if last_msg else "",
                    "last_message_role": last_msg.role if last_msg else "",
                    "last_interaction_time": r.last_interaction_time.isoformat() if r.last_interaction_time else None,
                    "followup_sent_at": r.followup_sent_at.isoformat() if r.followup_sent_at else None,
                }
            )
        return result


def _add_tag_str(existing_tags: str, new_tag: str) -> str:
    tags = [t.strip() for t in (existing_tags or "").split(",") if t.strip()]
    if new_tag not in tags:
        tags.append(new_tag)
    return ", ".join(tags)


def update_state(psid: str, state: str) -> None:
    if state not in VALID_STATES:
        return
    with SessionLocal() as db:
        user = db.get(UserSession, psid)
        if user is not None:
            user.state = state
            if state == "completed":
                user.is_starred = True
                if not user.purchased_at:
                    user.purchased_at = utcnow()
                tags = _add_tag_str(user.broadcast_tags or "", "ชำระเงินแล้ว")
                user.broadcast_tags = _add_tag_str(tags, "⭐ ติดดาว (ซื้อแล้ว)")
            db.commit()


def update_session_meta(
    psid: str,
    bot_enabled: bool | None = None,
    state: str | None = None,
    is_starred: bool | None = None,
    customer_name: str | None = None,
    notes: str | None = None,
    broadcast_tags: str | None = None,
    purchased_sku: str | None = None,
    purchased_qty: int | None = None,
    after_sales_stage: int | None = None,
    clear_unread: bool = False,
) -> UserSession | None:
    with SessionLocal() as db:
        user = db.get(UserSession, psid)
        if user is None:
            return None
        if bot_enabled is not None:
            user.bot_enabled = bot_enabled
        if customer_name is not None:
            user.customer_name = customer_name
        if notes is not None:
            user.notes = notes
        if broadcast_tags is not None:
            user.broadcast_tags = broadcast_tags
        if state is not None and state in VALID_STATES:
            user.state = state
            if state == "completed":
                user.is_starred = True
                if not user.purchased_at:
                    user.purchased_at = utcnow()
                tags = _add_tag_str(user.broadcast_tags or "", "ชำระเงินแล้ว")
                user.broadcast_tags = _add_tag_str(tags, "⭐ ติดดาว (ซื้อแล้ว)")
        if is_starred is not None:
            user.is_starred = bool(is_starred)
            if is_starred:
                user.state = "completed"
                if not user.purchased_at:
                    user.purchased_at = utcnow()
                tags = _add_tag_str(user.broadcast_tags or "", "ชำระเงินแล้ว")
                user.broadcast_tags = _add_tag_str(tags, "⭐ ติดดาว (ซื้อแล้ว)")
        if purchased_sku is not None:
            user.purchased_sku = purchased_sku
        if purchased_qty is not None:
            user.purchased_qty = max(1, int(purchased_qty))
        if after_sales_stage is not None:
            user.after_sales_stage = after_sales_stage
        if clear_unread:
            user.unread_count = 0
        db.commit()
        return user


def get_completed_sessions_for_after_sales() -> list[UserSession]:
    """Return all completed sessions that have not yet finished all 3 after-sales stages."""
    with SessionLocal() as db:
        rows = db.execute(
            select(UserSession).where(
                UserSession.state == "completed",
                UserSession.after_sales_stage < 3,
            )
        ).scalars().all()
    return rows


def get_stale_pending_sessions(older_than_hours: float) -> list[UserSession]:
    """Sessions stuck in pending_payment with no interaction for X hours,
    that haven't received a follow-up yet."""
    from datetime import timedelta

    cutoff = utcnow() - timedelta(hours=older_than_hours)
    with SessionLocal() as db:
        rows = db.execute(
            select(UserSession).where(
                UserSession.state == "pending_payment",
                UserSession.last_interaction_time < cutoff,
                UserSession.followup_sent_at.is_(None),
            )
        ).scalars().all()
    return rows


def mark_followup_sent(psid: str) -> None:
    with SessionLocal() as db:
        user = db.get(UserSession, psid)
        if user is not None:
            user.followup_sent_at = utcnow()
            db.commit()


def set_bot_enabled(psid: str, enabled: bool) -> None:
    update_session_meta(psid, bot_enabled=enabled)
