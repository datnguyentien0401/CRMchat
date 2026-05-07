from __future__ import annotations

from datetime import datetime, timezone, timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import create_app
from app.models import Campaign, Conversation, KOC, Message, PipelineStatus, RiskFlag


def _auth(user_id: str) -> dict[str, str]:
    return {"X-User-Id": user_id}


def _seed_conv(client: TestClient, engine):
    with Session(engine) as s:
        k = KOC(display_name="K1")
        c = Campaign(name="C1")
        s.add_all([k, c])
        s.commit()
        s.refresh(k)
        s.refresh(c)
    r = client.post(
        "/conversations",
        headers=_auth("manager-1"),
        json={"koc_id": str(k.id), "campaign_id": str(c.id), "assigned_booker_id": "booker-1"},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"], k.id, c.id


def test_no_risk_when_price_evidence_exists(tmp_path):
    app = create_app(f"sqlite:///{tmp_path}/r1.db")
    with TestClient(app) as client:
        engine = app.state.engine
        conv_id, _, camp_id = _seed_conv(client, engine)

        # Price discussion evidence in chat
        r = client.post(
            f"/conversations/{conv_id}/messages",
            headers=_auth("booker-1"),
            json={"body": "Giá 10tr nhé"},
        )
        assert r.status_code == 200

        # Price changed in deal, but chat has evidence => should not create "no discussion" risk
        r = client.put(
            f"/conversations/{conv_id}/deal",
            headers=_auth("booker-1"),
            json={
                "initial_price": 10_000_000,
                "final_price": 12_000_000,
                "benchmark_price": 20_000_000,
                "pipeline_status": "negotiating",
                "approval_status": "not_requested",
                "approval_requested_at": None,
            },
        )
        assert r.status_code == 200, r.text

        r = client.post(f"/conversations/{conv_id}/risk/evaluate", headers=_auth("manager-1"))
        assert r.status_code == 200
        types = {f["risk_type"] for f in r.json()}
        assert "rule_price_changed_no_discussion" not in types


def test_risk_price_changed_without_discussion(tmp_path):
    app = create_app(f"sqlite:///{tmp_path}/r2.db")
    with TestClient(app) as client:
        engine = app.state.engine
        conv_id, _, _ = _seed_conv(client, engine)

        # No price mentions in chat
        client.post(f"/conversations/{conv_id}/messages", headers=_auth("booker-1"), json={"body": "hello"})

        client.put(
            f"/conversations/{conv_id}/deal",
            headers=_auth("booker-1"),
            json={
                "initial_price": 10_000_000,
                "final_price": 12_000_000,
                "benchmark_price": 50_000_000,
                "pipeline_status": "negotiating",
                "approval_status": "not_requested",
                "approval_requested_at": None,
            },
        )

        r = client.post(f"/conversations/{conv_id}/risk/evaluate", headers=_auth("manager-1"))
        types = {f["risk_type"] for f in r.json()}
        assert "rule_price_changed_no_discussion" in types


def test_risk_sensitive_keyword(tmp_path):
    app = create_app(f"sqlite:///{tmp_path}/r3.db")
    with TestClient(app) as client:
        engine = app.state.engine
        conv_id, _, _ = _seed_conv(client, engine)

        client.post(
            f"/conversations/{conv_id}/messages",
            headers=_auth("booker-1"),
            json={"body": "commission riêng nhé"},
        )
        r = client.post(f"/conversations/{conv_id}/risk/evaluate", headers=_auth("manager-1"))
        types = {f["risk_type"] for f in r.json()}
        assert "rule_sensitive_money_keywords" in types


def test_risk_price_above_benchmark(tmp_path):
    app = create_app(f"sqlite:///{tmp_path}/r4.db")
    with TestClient(app) as client:
        engine = app.state.engine
        conv_id, _, _ = _seed_conv(client, engine)

        client.put(
            f"/conversations/{conv_id}/deal",
            headers=_auth("booker-1"),
            json={
                "initial_price": 10_000_000,
                "final_price": 16_000_000,
                "benchmark_price": 10_000_000,
                "pipeline_status": "negotiating",
                "approval_status": "not_requested",
                "approval_requested_at": None,
            },
        )
        r = client.post(f"/conversations/{conv_id}/risk/evaluate", headers=_auth("manager-1"))
        types = {f["risk_type"] for f in r.json()}
        assert "rule_price_above_benchmark" in types


def test_risk_commit_before_approval_requested(tmp_path):
    app = create_app(f"sqlite:///{tmp_path}/r5.db")
    with TestClient(app) as client:
        engine = app.state.engine
        conv_id, _, _ = _seed_conv(client, engine)

        # Commitment message
        client.post(
            f"/conversations/{conv_id}/messages",
            headers=_auth("booker-1"),
            json={"body": "Ok deal, chốt nhé"},
        )

        approval_requested_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        client.put(
            f"/conversations/{conv_id}/deal",
            headers=_auth("booker-1"),
            json={
                "initial_price": 10_000_000,
                "final_price": 10_000_000,
                "benchmark_price": 10_000_000,
                "pipeline_status": "committed",
                "approval_status": "requested",
                "approval_requested_at": approval_requested_at,
            },
        )

        r = client.post(f"/conversations/{conv_id}/risk/evaluate", headers=_auth("manager-1"))
        types = {f["risk_type"] for f in r.json()}
        assert "rule_commit_before_approval_request" in types

