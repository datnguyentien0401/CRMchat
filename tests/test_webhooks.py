from __future__ import annotations

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import create_app
from app.models import Campaign, Channel, ExternalMessageRef, KOC, KOCIdentity, Message, RiskFlag, WebhookRawEvent


def _wh_secret(ok: bool = True) -> dict[str, str]:
    return {"X-Webhook-Secret": "whatsapp-secret" if ok else "wrong"}


def _tg_secret(ok: bool = True) -> dict[str, str]:
    return {"X-Webhook-Secret": "telegram-secret" if ok else "wrong"}


def test_webhook_wrong_secret_rejected_and_raw_saved(tmp_path):
    app = create_app(f"sqlite:///{tmp_path}/w1.db")
    with TestClient(app) as client:
        engine = app.state.engine
        with Session(engine) as s:
            camp = Campaign(name="C1")
            s.add(camp)
            s.commit()
            s.refresh(camp)

        payload = {
            "external_message_id": "m-1",
            "external_sender_id": "u-1",
            "text": "hello",
            "assigned_booker_id": "booker-1",
            "campaign_id": str(camp.id),
        }
        r = client.post("/webhooks/whatsapp", headers=_wh_secret(ok=False), json=payload)
        assert r.status_code == 401

        with Session(engine) as s:
            raws = s.exec(select(WebhookRawEvent)).all()
            assert len(raws) == 1
            assert raws[0].channel == Channel.whatsapp
            assert raws[0].verified is False
            assert raws[0].accepted is False
            assert raws[0].payload["external_message_id"] == "m-1"


def test_deduplicate_external_message_id(tmp_path):
    app = create_app(f"sqlite:///{tmp_path}/w2.db")
    with TestClient(app) as client:
        engine = app.state.engine
        with Session(engine) as s:
            camp = Campaign(name="C1")
            s.add(camp)
            s.commit()
            s.refresh(camp)

        payload = {
            "external_message_id": "m-dup",
            "external_sender_id": "u-1",
            "text": "hello",
            "assigned_booker_id": "booker-1",
            "campaign_id": str(camp.id),
        }
        r1 = client.post("/webhooks/telegram", headers=_tg_secret(ok=True), json=payload)
        assert r1.status_code == 200, r1.text
        r2 = client.post("/webhooks/telegram", headers=_tg_secret(ok=True), json=payload)
        assert r2.status_code == 200, r2.text
        assert r2.json()["deduplicated"] is True

        conv_id = r1.json()["conversation_id"]
        r_msgs = client.get(f"/conversations/{conv_id}/messages", headers={"X-User-Id": "manager-1"})
        assert r_msgs.status_code == 200, r_msgs.text
        assert len(r_msgs.json()) == 1

        with Session(engine) as s:
            ext = s.exec(select(ExternalMessageRef).where(ExternalMessageRef.external_message_id == "m-dup")).all()
            assert len(ext) == 1


def test_new_sender_creates_koc_placeholder_and_identity(tmp_path):
    app = create_app(f"sqlite:///{tmp_path}/w3.db")
    with TestClient(app) as client:
        engine = app.state.engine
        with Session(engine) as s:
            camp = Campaign(name="C1")
            s.add(camp)
            s.commit()
            s.refresh(camp)

        payload = {
            "external_message_id": "m-1",
            "external_sender_id": "new-sender-999",
            "text": "hello",
            "assigned_booker_id": "booker-1",
            "campaign_id": str(camp.id),
        }
        r = client.post("/webhooks/whatsapp", headers=_wh_secret(ok=True), json=payload)
        assert r.status_code == 200, r.text

        with Session(engine) as s:
            ident = s.exec(
                select(KOCIdentity).where(
                    KOCIdentity.channel == Channel.whatsapp,
                    KOCIdentity.external_sender_id == "new-sender-999",
                )
            ).first()
            assert ident is not None
            koc = s.get(KOC, ident.koc_id)
            assert koc is not None


def test_sensitive_keyword_creates_risk_flag(tmp_path):
    app = create_app(f"sqlite:///{tmp_path}/w4.db")
    with TestClient(app) as client:
        engine = app.state.engine
        with Session(engine) as s:
            camp = Campaign(name="C1")
            s.add(camp)
            s.commit()
            s.refresh(camp)

        payload = {
            "external_message_id": "m-risk",
            "external_sender_id": "u-1",
            "text": "Mình có thể commission riêng được không?",
            "assigned_booker_id": "booker-1",
            "campaign_id": str(camp.id),
        }
        r = client.post("/webhooks/telegram", headers=_tg_secret(ok=True), json=payload)
        assert r.status_code == 200, r.text
        conv_id = r.json()["conversation_id"]

        r2 = client.get(f"/conversations/{conv_id}/risk_flags", headers={"X-User-Id": "manager-1"})
        assert r2.status_code == 200, r2.text
        flags = r2.json()
        assert len(flags) == 1
        assert flags[0]["risk_type"] == "sensitive_keyword"
        assert "commission riêng" in flags[0]["reason"].lower()


def test_raw_event_saved_for_audit_debug(tmp_path):
    app = create_app(f"sqlite:///{tmp_path}/w5.db")
    with TestClient(app) as client:
        engine = app.state.engine
        with Session(engine) as s:
            camp = Campaign(name="C1")
            s.add(camp)
            s.commit()
            s.refresh(camp)

        payload = {
            "external_message_id": "m-raw",
            "external_sender_id": "u-raw",
            "text": "hello",
            "assigned_booker_id": "booker-1",
            "campaign_id": str(camp.id),
        }
        r = client.post("/webhooks/whatsapp", headers=_wh_secret(ok=True), json=payload)
        assert r.status_code == 200, r.text

        with Session(engine) as s:
            raw = s.exec(
                select(WebhookRawEvent).where(
                    WebhookRawEvent.channel == Channel.whatsapp,
                    WebhookRawEvent.external_message_id == "m-raw",
                )
            ).first()
            assert raw is not None
            assert raw.payload["external_sender_id"] == "u-raw"
            assert raw.accepted is True

