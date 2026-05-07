from __future__ import annotations

from uuid import UUID

from sqlmodel import Session, col, select

from app.models import (
    AuditLog,
    AuditEventType,
    Campaign,
    Channel,
    Conversation,
    ConversationStatus,
    Deal,
    ExternalMessageRef,
    KOC,
    KOCIdentity,
    Message,
    RiskFlag,
    RiskSeverity,
    Role,
    User,
    WebhookRawEvent,
    now_utc,
)

class UserRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_id(self, user_id: str) -> User | None:
        return self.session.get(User, user_id)

class KOCRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_id(self, koc_id: UUID) -> KOC | None:
        return self.session.get(KOC, koc_id)

    def create(self, display_name: str) -> KOC:
        koc = KOC(display_name=display_name)
        self.session.add(koc)
        self.session.commit()
        self.session.refresh(koc)
        return koc


class KOCIdentityRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def find_by_channel_and_sender(
        self, channel: Channel, external_sender_id: str
    ) -> KOCIdentity | None:
        return self.session.exec(
            select(KOCIdentity).where(
                KOCIdentity.channel == channel,
                KOCIdentity.external_sender_id == external_sender_id,
            )
        ).first()

    def create(self, channel: Channel, external_sender_id: str, koc_id: UUID) -> KOCIdentity:
        identity = KOCIdentity(
            channel=channel,
            external_sender_id=external_sender_id,
            koc_id=koc_id,
        )
        self.session.add(identity)
        self.session.commit()
        return identity

class CampaignRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_id(self, campaign_id: UUID) -> Campaign | None:
        return self.session.get(Campaign, campaign_id)

class ConversationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_id(self, conversation_id: UUID) -> Conversation | None:
        return self.session.get(Conversation, conversation_id)

    def list_for_booker(self, booker_id: str) -> list[Conversation]:
        stmt = (
            select(Conversation)
            .where(Conversation.assigned_booker_id == booker_id)
            .order_by(col(Conversation.created_at).desc())
        )
        return list(self.session.exec(stmt).all())

    def list_for_manager(
        self, team_id: str, booker_id: str | None = None
    ) -> list[Conversation]:
        stmt = (
            select(Conversation)
            .where(Conversation.team_id == team_id)
            .order_by(col(Conversation.created_at).desc())
        )
        if booker_id:
            stmt = stmt.where(Conversation.assigned_booker_id == booker_id)
        return list(self.session.exec(stmt).all())

    def find_open_for_koc_campaign_booker(
        self,
        koc_id: UUID,
        campaign_id: UUID,
        assigned_booker_id: str,
    ) -> Conversation | None:
        return self.session.exec(
            select(Conversation)
            .where(
                Conversation.koc_id == koc_id,
                Conversation.campaign_id == campaign_id,
                Conversation.assigned_booker_id == assigned_booker_id,
                Conversation.status != ConversationStatus.closed,
            )
            .order_by(col(Conversation.created_at).desc())
        ).first()

    def create(
        self,
        *,
        koc_id: UUID,
        campaign_id: UUID,
        assigned_booker_id: str,
        team_id: str,
        flush_only: bool = False,
    ) -> Conversation:
        conv = Conversation(
            koc_id=koc_id,
            campaign_id=campaign_id,
            assigned_booker_id=assigned_booker_id,
            team_id=team_id,
            status=ConversationStatus.open,
        )
        self.session.add(conv)
        if flush_only:
            self.session.flush()
        else:
            self.session.commit()
            self.session.refresh(conv)
        return conv

    def save(self, conv: Conversation) -> Conversation:
        self.session.add(conv)
        self.session.commit()
        self.session.refresh(conv)
        return conv

class MessageRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_by_conversation(self, conversation_id: UUID) -> list[Message]:
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(col(Message.created_at).asc())
        )
        return list(self.session.exec(stmt).all())

    def create_with_flush(
        self,
        *,
        conversation_id: UUID,
        sender_user_id: str | None,
        body: str,
    ) -> Message:
        msg = Message(
            conversation_id=conversation_id,
            sender_user_id=sender_user_id,
            body=body,
        )
        self.session.add(msg)
        self.session.flush()
        return msg

class AuditLogRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_by_conversation(self, conversation_id: UUID) -> list[AuditLog]:
        stmt = (
            select(AuditLog)
            .where(AuditLog.conversation_id == conversation_id)
            .order_by(col(AuditLog.created_at).asc())
        )
        return list(self.session.exec(stmt).all())

    def create(
        self,
        *,
        actor_user_id: str,
        conversation_id: UUID,
        event_type: AuditEventType,
        payload: dict,
    ) -> None:
        self.session.add(
            AuditLog(
                actor_user_id=actor_user_id,
                conversation_id=conversation_id,
                event_type=event_type,
                payload=payload,
            )
        )

class RiskFlagRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_by_conversation(self, conversation_id: UUID) -> list[RiskFlag]:
        stmt = (
            select(RiskFlag)
            .where(RiskFlag.conversation_id == conversation_id)
            .order_by(col(RiskFlag.created_at).asc())
        )
        return list(self.session.exec(stmt).all())

    def list_auto_flags(self, conversation_id: UUID, prefix: str) -> list[RiskFlag]:
        return list(
            self.session.exec(
                select(RiskFlag).where(
                    RiskFlag.conversation_id == conversation_id,
                    col(RiskFlag.risk_type).like(f"{prefix}%"),
                )
            ).all()
        )

    def delete_all(self, flags: list[RiskFlag]) -> None:
        for flag in flags:
            self.session.delete(flag)

    def create(
        self,
        *,
        conversation_id: UUID,
        message_id: UUID | None,
        risk_type: str,
        severity: RiskSeverity,
        reason: str,
        payload: dict,
    ) -> None:
        self.session.add(
            RiskFlag(
                conversation_id=conversation_id,
                message_id=message_id,
                risk_type=risk_type,
                severity=severity,
                reason=reason,
                payload=payload,
            )
        )

    def create_all(self, flags: list[RiskFlag]) -> None:
        self.session.add_all(flags)

class DealRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_conversation(self, conversation_id: UUID) -> Deal | None:
        return self.session.exec(
            select(Deal).where(Deal.conversation_id == conversation_id)
        ).first()

    def save(self, deal: Deal) -> Deal:
        self.session.add(deal)
        self.session.commit()
        self.session.refresh(deal)
        return deal

class WebhookRawEventRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        channel: Channel,
        external_message_id: str | None,
        verified: bool,
        payload: dict,
    ) -> WebhookRawEvent:
        raw = WebhookRawEvent(
            channel=channel,
            external_message_id=external_message_id,
            verified=verified,
            accepted=False,
            payload=payload,
        )
        self.session.add(raw)
        self.session.commit()
        self.session.refresh(raw)
        return raw

    def save(self, raw: WebhookRawEvent) -> None:
        self.session.add(raw)
        self.session.commit()

class ExternalMessageRefRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def find_by_channel_and_external_id(
        self, channel: Channel, external_message_id: str | None
    ) -> ExternalMessageRef | None:
        return self.session.exec(
            select(ExternalMessageRef).where(
                ExternalMessageRef.channel == channel,
                ExternalMessageRef.external_message_id == external_message_id,
            )
        ).first()

    def create(
        self,
        *,
        channel: Channel,
        external_message_id: str | None,
        conversation_id: UUID,
        message_id: UUID,
    ) -> None:
        self.session.add(
            ExternalMessageRef(
                channel=channel,
                external_message_id=external_message_id,
                conversation_id=conversation_id,
                message_id=message_id,
            )
        )
