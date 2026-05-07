from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.models import ApprovalStatus, ConversationStatus, PipelineStatus


class ConversationCreate(BaseModel):
    koc_id: UUID
    campaign_id: UUID
    assigned_booker_id: str


class ConversationOut(BaseModel):
    id: UUID
    koc_id: UUID
    campaign_id: UUID
    assigned_booker_id: str
    team_id: str
    status: ConversationStatus
    created_at: datetime


class MessageCreate(BaseModel):
    body: str = Field(min_length=1, max_length=10000)
    attach_to_koc_id: UUID | None = None
    attach_to_campaign_id: UUID | None = None


class MessageOut(BaseModel):
    id: UUID
    conversation_id: UUID
    sender_user_id: str | None
    body: str
    created_at: datetime


class ConversationStatusUpdate(BaseModel):
    status: ConversationStatus


class AuditLogOut(BaseModel):
    id: UUID
    created_at: datetime
    actor_user_id: str
    conversation_id: UUID
    event_type: Literal["message_added", "conversation_status_changed"]
    payload: dict[str, Any]


class WebhookMessageIn(BaseModel):
    external_message_id: str = Field(min_length=1, max_length=200)
    external_sender_id: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=10000)
    assigned_booker_id: str = Field(min_length=1, max_length=100)
    koc_display_name: str | None = None
    campaign_id: UUID


class WebhookIngestOut(BaseModel):
    accepted: bool
    deduplicated: bool = False
    conversation_id: UUID | None = None
    message_id: UUID | None = None
    raw_event_id: UUID


class RiskFlagOut(BaseModel):
    id: UUID
    created_at: datetime
    conversation_id: UUID
    message_id: UUID | None
    risk_type: str
    severity: str
    reason: str
    payload: dict[str, Any]


class DealUpsert(BaseModel):
    initial_price: int | None = None
    final_price: int | None = None
    benchmark_price: int | None = None
    approval_status: ApprovalStatus = ApprovalStatus.not_requested
    pipeline_status: PipelineStatus = PipelineStatus.contact
    approval_requested_at: datetime | None = None


class DealOut(BaseModel):
    conversation_id: UUID
    initial_price: int | None
    final_price: int | None
    benchmark_price: int | None
    approval_status: ApprovalStatus
    pipeline_status: PipelineStatus
    approval_requested_at: datetime | None

