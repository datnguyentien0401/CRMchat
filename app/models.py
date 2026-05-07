from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

from sqlalchemy import UniqueConstraint
from sqlmodel import JSON, Column, Field, SQLModel


class Role(str, Enum):
    booker = "booker"
    manager = "manager"


class ConversationStatus(str, Enum):
    open = "open"
    negotiating = "negotiating"
    pending_approval = "pending_approval"
    closed = "closed"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class User(SQLModel, table=True):
    id: str = Field(primary_key=True)
    role: Role
    team_id: str


class KOC(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    display_name: str


class Campaign(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str


class Conversation(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)

    koc_id: UUID = Field(foreign_key="koc.id", index=True)
    campaign_id: UUID = Field(foreign_key="campaign.id", index=True)

    assigned_booker_id: str = Field(foreign_key="user.id", index=True)
    team_id: str = Field(index=True)

    status: ConversationStatus = Field(default=ConversationStatus.open, index=True)
    created_at: datetime = Field(default_factory=now_utc, index=True)


class Message(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)

    conversation_id: UUID = Field(foreign_key="conversation.id", index=True)
    sender_user_id: Optional[str] = Field(foreign_key="user.id", default=None, index=True)

    body: str
    created_at: datetime = Field(default_factory=now_utc, index=True)


class AuditEventType(str, Enum):
    message_added = "message_added"
    conversation_status_changed = "conversation_status_changed"


class AuditLog(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    created_at: datetime = Field(default_factory=now_utc, index=True)

    actor_user_id: str = Field(foreign_key="user.id", index=True)
    conversation_id: UUID = Field(foreign_key="conversation.id", index=True)
    event_type: AuditEventType = Field(index=True)

    payload: dict[str, Any] = Field(
        sa_column=Column(JSON, nullable=False),
        default_factory=dict,
    )


class Channel(str, Enum):
    whatsapp = "whatsapp"
    telegram = "telegram"


class KOCIdentity(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("channel", "external_sender_id", name="uq_koc_identity_sender"),)

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    channel: Channel = Field(index=True)
    external_sender_id: str = Field(index=True)
    koc_id: UUID = Field(foreign_key="koc.id", index=True)
    created_at: datetime = Field(default_factory=now_utc, index=True)


class WebhookRawEvent(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    received_at: datetime = Field(default_factory=now_utc, index=True)

    channel: Channel = Field(index=True)
    external_message_id: str | None = Field(default=None, index=True)

    verified: bool = Field(default=False, index=True)
    accepted: bool = Field(default=False, index=True)
    deduplicated: bool = Field(default=False, index=True)
    rejection_reason: str | None = Field(default=None)

    payload: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False), default_factory=dict)


class ExternalMessageRef(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("channel", "external_message_id", name="uq_external_message_id"),)

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    channel: Channel = Field(index=True)
    external_message_id: str = Field(index=True)

    conversation_id: UUID = Field(foreign_key="conversation.id", index=True)
    message_id: UUID = Field(foreign_key="message.id", index=True)

    created_at: datetime = Field(default_factory=now_utc, index=True)


class RiskSeverity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class RiskFlag(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    created_at: datetime = Field(default_factory=now_utc, index=True)

    conversation_id: UUID = Field(foreign_key="conversation.id", index=True)
    message_id: UUID | None = Field(foreign_key="message.id", default=None, index=True)

    risk_type: str = Field(index=True)
    severity: RiskSeverity = Field(default=RiskSeverity.medium, index=True)
    reason: str
    payload: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False), default_factory=dict)


class ApprovalStatus(str, Enum):
    not_requested = "not_requested"
    requested = "requested"
    approved = "approved"
    rejected = "rejected"


class PipelineStatus(str, Enum):
    contact = "contact"
    negotiating = "negotiating"
    pending_approval = "pending_approval"
    committed = "committed"
    closed = "closed"


class Deal(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("conversation_id", name="uq_deal_conversation"),)

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    created_at: datetime = Field(default_factory=now_utc, index=True)
    updated_at: datetime = Field(default_factory=now_utc, index=True)

    conversation_id: UUID = Field(foreign_key="conversation.id", index=True)

    # Simple MVP money fields: store as integer (e.g. VND) to avoid float issues
    initial_price: int | None = Field(default=None)
    final_price: int | None = Field(default=None, index=True)
    benchmark_price: int | None = Field(default=None)

    approval_status: ApprovalStatus = Field(default=ApprovalStatus.not_requested, index=True)
    pipeline_status: PipelineStatus = Field(default=PipelineStatus.contact, index=True)

    approval_requested_at: datetime | None = Field(default=None)

