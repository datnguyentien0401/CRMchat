from __future__ import annotations

from fastapi import Depends, FastAPI, Header, Query
from sqlmodel import Session
from uuid import UUID

from app.auth import get_current_user, seed_users
from app.db import create_sqlite_engine, get_session, init_db
from app.deps import get_db
from app.models import Campaign, Channel, KOC, User
from sqlmodel import select
from app.schemas import (
    AuditLogOut,
    ConversationCreate,
    ConversationOut,
    ConversationStatusUpdate,
    DealOut,
    DealUpsert,
    RiskFlagOut,
    MessageCreate,
    MessageOut,
    WebhookIngestOut,
    WebhookMessageIn,
)
from app.service import (
    add_message,
    create_conversation,
    evaluate_conversation_risks,
    upsert_deal,
    list_audits,
    list_conversations_for_user,
    list_messages,
    list_risk_flags,
    ingest_webhook_message,
    update_conversation_status,
)


def create_app(db_url: str | None = None) -> FastAPI:
    import os

    db_url = db_url or os.getenv("CRMCHAT_DB_URL") or "sqlite:///./crmchat.db"
    engine = create_sqlite_engine(db_url)
    init_db(engine)

    app = FastAPI(title="CRMchat MVP API")
    app.state.engine = engine

    def _get_db():
        yield from get_session(engine)

    app.dependency_overrides[get_db] = _get_db

    @app.on_event("startup")
    def _startup_seed() -> None:
        with Session(engine) as session:
            seed_users(session)
            # Seed a few KOC/Campaign for demo/dev convenience
            if session.exec(select(KOC)).first() is None:
                session.add(KOC(display_name="KOC A"))
                session.add(KOC(display_name="KOC B"))
            if session.exec(select(Campaign)).first() is None:
                session.add(Campaign(name="Campaign 1"))
            session.commit()

    @app.post("/conversations", response_model=ConversationOut)
    def api_create_conversation(
        payload: ConversationCreate,
        session: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ):
        conv = create_conversation(
            session=session,
            actor=user,
            koc_id=payload.koc_id,
            campaign_id=payload.campaign_id,
            assigned_booker_id=payload.assigned_booker_id,
        )
        return conv

    @app.get("/conversations", response_model=list[ConversationOut])
    def api_list_conversations(
        booker_id: str | None = Query(default=None),
        session: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ):
        return list_conversations_for_user(session=session, user=user, booker_id=booker_id)

    @app.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
    def api_list_messages(
        conversation_id: UUID,
        session: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ):
        return list_messages(session=session, user=user, conversation_id=conversation_id)

    @app.post("/conversations/{conversation_id}/messages", response_model=MessageOut)
    def api_add_message(
        conversation_id: UUID,
        payload: MessageCreate,
        session: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ):
        msg = add_message(
            session=session,
            actor=user,
            conversation_id=conversation_id,
            body=payload.body,
            attach_to_koc_id=payload.attach_to_koc_id,
            attach_to_campaign_id=payload.attach_to_campaign_id,
        )
        return msg

    @app.patch("/conversations/{conversation_id}/status", response_model=ConversationOut)
    def api_update_status(
        conversation_id: UUID,
        payload: ConversationStatusUpdate,
        session: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ):
        return update_conversation_status(
            session=session,
            actor=user,
            conversation_id=conversation_id,
            status_value=payload.status,
        )

    @app.get("/conversations/{conversation_id}/audits", response_model=list[AuditLogOut])
    def api_list_audits(
        conversation_id: UUID,
        session: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ):
        return list_audits(session=session, user=user, conversation_id=conversation_id)

    @app.get("/conversations/{conversation_id}/risk_flags", response_model=list[RiskFlagOut])
    def api_list_risks(
        conversation_id: UUID,
        session: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ):
        return list_risk_flags(session=session, user=user, conversation_id=conversation_id)

    @app.put("/conversations/{conversation_id}/deal", response_model=DealOut)
    def api_upsert_deal(
        conversation_id: UUID,
        payload: DealUpsert,
        session: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ):
        deal = upsert_deal(
            session=session,
            actor=user,
            conversation_id=conversation_id,
            data=payload.model_dump(),
        )
        return deal

    @app.post("/conversations/{conversation_id}/risk/evaluate", response_model=list[RiskFlagOut])
    def api_evaluate_risk(
        conversation_id: UUID,
        session: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ):
        # Require access to conversation; evaluation results are scoped to same rules.
        # (We don't take user input here; just compute.)
        _ = list_messages(session=session, user=user, conversation_id=conversation_id)
        return evaluate_conversation_risks(session=session, conversation_id=conversation_id)

    def _verify_webhook_secret(channel: Channel, secret: str | None) -> bool:
        expected = {
            Channel.whatsapp: "whatsapp-secret",
            Channel.telegram: "telegram-secret",
        }[channel]
        return bool(secret) and secret == expected

    @app.post("/webhooks/{channel}", response_model=WebhookIngestOut)
    def api_webhook_receiver(
        channel: Channel,
        payload: WebhookMessageIn,
        x_webhook_secret: str | None = Header(default=None, alias="X-Webhook-Secret"),
        session: Session = Depends(get_db),
    ):
        verified = _verify_webhook_secret(channel, x_webhook_secret)
        result = ingest_webhook_message(
            session=session,
            channel=channel,
            payload=payload.model_dump(mode="json"),
            verified=verified,
        )
        return result

    return app


app = create_app()

