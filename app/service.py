from __future__ import annotations

from fastapi import HTTPException, status
from sqlmodel import Session, col, select
from uuid import UUID

from app.models import (
    ApprovalStatus,
    AuditEventType,
    AuditLog,
    Campaign,
    Channel,
    Conversation,
    ConversationStatus,
    Deal,
    ExternalMessageRef,
    KOC,
    KOCIdentity,
    Message,
    PipelineStatus,
    RiskFlag,
    RiskSeverity,
    Role,
    User,
    WebhookRawEvent,
    now_utc,
)


def ensure_conversation_access(*, user: User, conv: Conversation) -> None:
    if user.role == Role.booker:
        if conv.assigned_booker_id != user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        return
    if user.role == Role.manager:
        if conv.team_id != user.team_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


def create_conversation(
    *,
    session: Session,
    actor: User,
    koc_id: UUID,
    campaign_id: UUID,
    assigned_booker_id: str,
) -> Conversation:
    koc = session.get(KOC, koc_id)
    if not koc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="KOC not found")
    campaign = session.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")

    assigned = session.get(User, assigned_booker_id)
    if not assigned or assigned.role != Role.booker:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid assigned_booker_id")

    if actor.role == Role.booker and assigned_booker_id != actor.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Booker can only assign self")
    if actor.role == Role.manager and assigned.team_id != actor.team_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Assigned booker not in team")

    # MVP rule: conversations always belong to a team, derived from assigned booker.
    conv = Conversation(
        koc_id=koc_id,
        campaign_id=campaign_id,
        assigned_booker_id=assigned_booker_id,
        team_id=assigned.team_id,
        status=ConversationStatus.open,
    )
    session.add(conv)
    session.commit()
    session.refresh(conv)
    return conv


def list_conversations_for_user(*, session: Session, user: User, booker_id: str | None) -> list[Conversation]:
    stmt = select(Conversation)
    if user.role == Role.booker:
        stmt = stmt.where(Conversation.assigned_booker_id == user.id)
    elif user.role == Role.manager:
        stmt = stmt.where(Conversation.team_id == user.team_id)
        if booker_id:
            stmt = stmt.where(Conversation.assigned_booker_id == booker_id)
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    stmt = stmt.order_by(col(Conversation.created_at).desc())
    return list(session.exec(stmt).all())


def list_messages(*, session: Session, user: User, conversation_id: UUID) -> list[Message]:
    conv = session.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    ensure_conversation_access(user=user, conv=conv)

    stmt = select(Message).where(Message.conversation_id == conversation_id).order_by(col(Message.created_at).asc())
    return list(session.exec(stmt).all())


def add_message(
    *,
    session: Session,
    actor: User,
    conversation_id: UUID,
    body: str,
    attach_to_koc_id: UUID | None,
    attach_to_campaign_id: UUID | None,
) -> Message:
    conv = session.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    ensure_conversation_access(user=actor, conv=conv)

    # Enforce: conversation must be attached to KOC & campaign; message attachments if present must match.
    if conv.koc_id is None or conv.campaign_id is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Conversation missing KOC/campaign")
    if attach_to_koc_id and attach_to_koc_id != conv.koc_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="attach_to_koc_id mismatch")
    if attach_to_campaign_id and attach_to_campaign_id != conv.campaign_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="attach_to_campaign_id mismatch")

    # Atomic write: message + audit + (optional) risk flag
    try:
        msg = Message(conversation_id=conversation_id, sender_user_id=actor.id, body=body)
        session.add(msg)
        session.flush()

        session.add(
            AuditLog(
                actor_user_id=actor.id,
                conversation_id=conversation_id,
                event_type=AuditEventType.message_added,
                payload={
                    "message_id": str(msg.id),
                    "koc_id": str(conv.koc_id),
                    "campaign_id": str(conv.campaign_id),
                },
            )
        )

        kws = _contains_any(body, MONEY_KEYWORDS)
        if kws:
            session.add(
                RiskFlag(
                    conversation_id=conversation_id,
                    message_id=msg.id,
                    risk_type="sensitive_keyword",
                    severity=RiskSeverity.high,
                    reason=f"Sensitive money keyword(s): {', '.join(sorted(set(kws)))}",
                    payload={"keywords": sorted(set(kws)), "source": "internal_message"},
                )
            )

        session.commit()
        session.refresh(msg)
        return msg
    except Exception:
        session.rollback()
        raise


def update_conversation_status(
    *,
    session: Session,
    actor: User,
    conversation_id: UUID,
    status_value: ConversationStatus,
) -> Conversation:
    conv = session.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    ensure_conversation_access(user=actor, conv=conv)

    try:
        old = conv.status
        conv.status = status_value
        session.add(conv)

        session.add(
            AuditLog(
                actor_user_id=actor.id,
                conversation_id=conversation_id,
                event_type=AuditEventType.conversation_status_changed,
                payload={"from": old, "to": status_value},
            )
        )

        session.commit()
        session.refresh(conv)
        return conv
    except Exception:
        session.rollback()
        raise


def list_audits(*, session: Session, user: User, conversation_id: UUID) -> list[AuditLog]:
    conv = session.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    ensure_conversation_access(user=user, conv=conv)

    stmt = (
        select(AuditLog)
        .where(AuditLog.conversation_id == conversation_id)
        .order_by(col(AuditLog.created_at).asc())
    )
    return list(session.exec(stmt).all())


SENSITIVE_KEYWORDS = [
    "commission riêng",
]


def _detect_sensitive_keywords(text: str) -> list[str]:
    t = text.lower()
    return [kw for kw in SENSITIVE_KEYWORDS if kw in t]


def ingest_webhook_message(
    *,
    session: Session,
    channel: Channel,
    payload: dict,
    verified: bool,
) -> dict:
    """
    Ingest a normalized webhook payload.

    Always stores raw event. Returns dict for API response.
    """
    external_message_id = payload.get("external_message_id")
    raw = WebhookRawEvent(
        channel=channel,
        external_message_id=external_message_id,
        verified=verified,
        accepted=False,
        payload=payload,
    )
    session.add(raw)
    session.commit()
    session.refresh(raw)

    if not verified:
        raw.rejection_reason = "invalid_signature"
        session.add(raw)
        session.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature")

    # Deduplicate by (channel, external_message_id)
    existing = session.exec(
        select(ExternalMessageRef).where(
            ExternalMessageRef.channel == channel,
            ExternalMessageRef.external_message_id == external_message_id,
        )
    ).first()
    if existing:
        raw.accepted = True
        raw.deduplicated = True
        session.add(raw)
        session.commit()
        return {
            "accepted": True,
            "deduplicated": True,
            "conversation_id": existing.conversation_id,
            "message_id": existing.message_id,
            "raw_event_id": raw.id,
        }

    external_sender_id = payload["external_sender_id"]
    identity = session.exec(
        select(KOCIdentity).where(
            KOCIdentity.channel == channel,
            KOCIdentity.external_sender_id == external_sender_id,
        )
    ).first()
    if identity:
        koc_id = identity.koc_id
    else:
        # Create placeholder KOC + identity mapping
        display = payload.get("koc_display_name") or f"{channel}:{external_sender_id}"
        koc = KOC(display_name=display)
        session.add(koc)
        session.commit()
        session.refresh(koc)

        identity = KOCIdentity(channel=channel, external_sender_id=external_sender_id, koc_id=koc.id)
        session.add(identity)
        session.commit()
        koc_id = koc.id

    campaign_id = UUID(str(payload["campaign_id"]))
    assigned_booker_id = payload["assigned_booker_id"]
    assigned = session.get(User, assigned_booker_id)
    if not assigned or assigned.role != Role.booker:
        raw.rejection_reason = "invalid_assigned_booker"
        session.add(raw)
        session.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid assigned_booker_id")

    # Find an existing non-closed conversation for that koc+campaign+booker, else create.
    conv = session.exec(
        select(Conversation)
        .where(
            Conversation.koc_id == koc_id,
            Conversation.campaign_id == campaign_id,
            Conversation.assigned_booker_id == assigned_booker_id,
            Conversation.status != ConversationStatus.closed,
        )
        .order_by(col(Conversation.created_at).desc())
    ).first()
    # Atomic write for accepted event: conversation (optional) + message + external ref + audit + risk + raw.accepted
    try:
        if not conv:
            if not session.get(Campaign, campaign_id):
                raw.rejection_reason = "campaign_not_found"
                session.add(raw)
                session.commit()
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")
            conv = Conversation(
                koc_id=koc_id,
                campaign_id=campaign_id,
                assigned_booker_id=assigned_booker_id,
                team_id=assigned.team_id,
                status=ConversationStatus.open,
            )
            session.add(conv)
            session.flush()

        msg = Message(conversation_id=conv.id, sender_user_id=None, body=payload["text"])
        session.add(msg)
        session.flush()

        session.add(
            ExternalMessageRef(
                channel=channel,
                external_message_id=external_message_id,
                conversation_id=conv.id,
                message_id=msg.id,
            )
        )

        session.add(
            AuditLog(
                actor_user_id="system",
                conversation_id=conv.id,
                event_type=AuditEventType.message_added,
                payload={
                    "message_id": str(msg.id),
                    "koc_id": str(conv.koc_id),
                    "campaign_id": str(conv.campaign_id),
                    "channel": channel,
                    "external_message_id": external_message_id,
                },
            )
        )

        kws = _detect_sensitive_keywords(payload["text"])
        if kws:
            session.add(
                RiskFlag(
                    conversation_id=conv.id,
                    message_id=msg.id,
                    risk_type="sensitive_keyword",
                    severity=RiskSeverity.high,
                    reason=f"Sensitive keyword detected: {', '.join(kws)}",
                    payload={"keywords": kws, "channel": channel, "external_message_id": external_message_id},
                )
            )

        raw.accepted = True
        session.add(raw)
        session.commit()
    except Exception:
        session.rollback()
        raise

    return {
        "accepted": True,
        "deduplicated": False,
        "conversation_id": conv.id,
        "message_id": msg.id,
        "raw_event_id": raw.id,
    }


def list_risk_flags(*, session: Session, user: User, conversation_id: UUID) -> list[RiskFlag]:
    conv = session.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    ensure_conversation_access(user=user, conv=conv)
    stmt = select(RiskFlag).where(RiskFlag.conversation_id == conversation_id).order_by(col(RiskFlag.created_at).asc())
    return list(session.exec(stmt).all())


MONEY_KEYWORDS = [
    "commission riêng",
    "commission",
    "hoa hồng",
    "giá",
    "price",
    "payment",
    "chuyển khoản",
    "bank",
    "invoice",
    "tt",
    "ck",
]


COMMIT_KEYWORDS = [
    "chốt",
    "ok deal",
    "confirm deal",
    "đồng ý chốt",
    "commit",
]


KOC_CONFIRM_KEYWORDS = [
    "ok",
    "đồng ý",
    "confirm",
    "chốt nhé",
]


def _contains_any(text: str, keywords: list[str]) -> list[str]:
    t = text.lower()
    return [kw for kw in keywords if kw in t]


def _has_price_evidence(messages: list[Message]) -> bool:
    # MVP heuristic: any message that contains "giá"/"price"/currency-like tokens indicates discussion.
    evidence_tokens = ["giá", "price", "vnd", "usd", "triệu", "tr", "k", "%"]
    for m in messages:
        if _contains_any(m.body, evidence_tokens):
            return True
    return False


def _find_first_message_time(messages: list[Message], keywords: list[str]) -> datetime | None:
    for m in sorted(messages, key=lambda x: x.created_at):
        if _contains_any(m.body, keywords):
            return m.created_at
    return None


def _find_koc_confirmation(messages: list[Message]) -> Message | None:
    # KOC messages are ingested with sender_user_id=None (from webhook)
    for m in sorted(messages, key=lambda x: x.created_at, reverse=True):
        if m.sender_user_id is None and _contains_any(m.body, KOC_CONFIRM_KEYWORDS):
            return m
    return None


AUTO_RULE_PREFIX = "rule_"


def evaluate_conversation_risks(*, session: Session, conversation_id: UUID) -> list[RiskFlag]:
    """
    Recompute risk flags for a conversation (MVP).
    Implementation: remove prior auto rule flags, then insert current ones.
    """
    conv = session.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    deal = session.exec(select(Deal).where(Deal.conversation_id == conversation_id)).first()
    msgs = list(
        session.exec(
            select(Message).where(Message.conversation_id == conversation_id).order_by(col(Message.created_at).asc())
        ).all()
    )

    # Delete prior auto flags for idempotency
    old_flags = session.exec(
        select(RiskFlag).where(
            RiskFlag.conversation_id == conversation_id,
            col(RiskFlag.risk_type).like(f"{AUTO_RULE_PREFIX}%"),
        )
    ).all()
    for f in old_flags:
        session.delete(f)
    session.commit()

    new_flags: list[RiskFlag] = []

    # Rule: Message contains sensitive money keywords
    for m in msgs:
        kws = _contains_any(m.body, MONEY_KEYWORDS)
        if kws:
            new_flags.append(
                RiskFlag(
                    conversation_id=conversation_id,
                    message_id=m.id,
                    risk_type="rule_sensitive_money_keywords",
                    severity=RiskSeverity.high,
                    reason=f"Sensitive money keyword(s): {', '.join(sorted(set(kws)))}",
                    payload={"keywords": sorted(set(kws))},
                )
            )

    if deal:
        # Rule: Final price > 150% benchmark
        if deal.final_price is not None and deal.benchmark_price is not None and deal.final_price > int(1.5 * deal.benchmark_price):
            new_flags.append(
                RiskFlag(
                    conversation_id=conversation_id,
                    message_id=None,
                    risk_type="rule_price_above_benchmark",
                    severity=RiskSeverity.high,
                    reason="Final price > 150% benchmark",
                    payload={"final_price": deal.final_price, "benchmark_price": deal.benchmark_price},
                )
            )

        # Rule: Price changed but no price discussion in chat
        if (
            deal.initial_price is not None
            and deal.final_price is not None
            and deal.initial_price != deal.final_price
            and not _has_price_evidence(msgs)
        ):
            new_flags.append(
                RiskFlag(
                    conversation_id=conversation_id,
                    message_id=None,
                    risk_type="rule_price_changed_no_discussion",
                    severity=RiskSeverity.high,
                    reason="Price changed but no price discussion evidence in chat",
                    payload={"initial_price": deal.initial_price, "final_price": deal.final_price},
                )
            )

        # Rule: Deal closed without KOC confirmation message
        if deal.pipeline_status == PipelineStatus.closed and _find_koc_confirmation(msgs) is None:
            new_flags.append(
                RiskFlag(
                    conversation_id=conversation_id,
                    message_id=None,
                    risk_type="rule_closed_without_koc_confirmation",
                    severity=RiskSeverity.high,
                    reason="Deal closed but no KOC confirmation message found",
                    payload={},
                )
            )

        # Rule: Approval requested after commitment message was sent
        if deal.approval_status in (ApprovalStatus.requested, ApprovalStatus.approved, ApprovalStatus.rejected) and deal.approval_requested_at:
            committed_at = _find_first_message_time(msgs, COMMIT_KEYWORDS)
            if committed_at and committed_at < deal.approval_requested_at:
                new_flags.append(
                    RiskFlag(
                        conversation_id=conversation_id,
                        message_id=None,
                        risk_type="rule_commit_before_approval_request",
                        severity=RiskSeverity.high,
                        reason="Commitment message was sent before approval was requested",
                        payload={"committed_at": committed_at.isoformat(), "approval_requested_at": deal.approval_requested_at.isoformat()},
                    )
                )

    session.add_all(new_flags)
    session.commit()

    # Return current flags (auto + manual)
    return list(
        session.exec(
            select(RiskFlag).where(RiskFlag.conversation_id == conversation_id).order_by(col(RiskFlag.created_at).asc())
        ).all()
    )


def upsert_deal(*, session: Session, actor: User, conversation_id: UUID, data: dict) -> Deal:
    conv = session.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    ensure_conversation_access(user=actor, conv=conv)

    deal = session.exec(select(Deal).where(Deal.conversation_id == conversation_id)).first()
    if not deal:
        deal = Deal(conversation_id=conversation_id)
        session.add(deal)

    for k, v in data.items():
        setattr(deal, k, v)
    deal.updated_at = now_utc()
    session.add(deal)
    session.commit()
    session.refresh(deal)
    return deal

