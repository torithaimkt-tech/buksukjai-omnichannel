"""Omnichannel Session & State Tracker — SQLite via SQLAlchemy.

Tracks each customer across LINE OA, Facebook Messenger, Instagram DM, and Web
 across up to 5 Pages/Brands, including order state, AI bot toggle (Human Handover),
customer display name, notes, and full message log.
"""

import os
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text, create_engine, inspect, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///chatbot.db")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
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


def init_db() -> None:
    Base.metadata.create_all(engine)
    _ensure_columns()


def _ensure_columns() -> None:
    """Auto-migrate existing SQLite tables if upgraded from an older version."""
    inspector = inspect(engine)
    if "user_sessions" in inspector.get_table_names():
        existing = {c["name"] for c in inspector.get_columns("user_sessions")}
        migrations = [
            ("brand_id", "VARCHAR(64) DEFAULT 'buksukjai'"),
            ("platform", "VARCHAR(32) DEFAULT 'facebook'"),
            ("external_user_id", "VARCHAR(128) DEFAULT ''"),
            ("customer_name", "VARCHAR(128) DEFAULT 'ลูกค้าใหม่'"),
            ("is_starred", "BOOLEAN DEFAULT 0"),
            ("bot_enabled", "BOOLEAN DEFAULT 1"),
            ("unread_count", "INTEGER DEFAULT 0"),
            ("notes", "TEXT DEFAULT ''"),
            ("broadcast_tags", "TEXT DEFAULT ''"),
            ("purchased_sku", "VARCHAR(64) DEFAULT 'BSJ1KG1'"),
            ("purchased_qty", "INTEGER DEFAULT 1"),
            ("purchased_at", "DATETIME NULL"),
            ("after_sales_stage", "INTEGER DEFAULT 0"),
        ]
        with engine.begin() as conn:
            for col_name, col_def in migrations:
                if col_name not in existing:
                    conn.execute(text(f"ALTER TABLE user_sessions ADD COLUMN {col_name} {col_def}"))
            conn.execute(
                text(
                    "UPDATE user_sessions SET is_starred = 1 "
                    "WHERE state = 'completed' OR broadcast_tags LIKE '%ชำระเงินแล้ว%' OR broadcast_tags LIKE '%ติดดาว%'"
                )
            )

    if "message_log" in inspector.get_table_names():
        existing_msg = {c["name"] for c in inspector.get_columns("message_log")}
        with engine.begin() as conn:
            if "sender_label" not in existing_msg:
                conn.execute(text("ALTER TABLE message_log ADD COLUMN sender_label VARCHAR(64) DEFAULT ''"))


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
            user.last_interaction_time = utcnow()
            if role == "user":
                user.followup_sent_at = None  # new activity resets the follow-up clock
                user.unread_count = (user.unread_count or 0) + 1
            elif role == "admin":
                user.unread_count = 0
        db.commit()


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
        stmt = select(UserSession).order_by(UserSession.last_interaction_time.desc())
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
