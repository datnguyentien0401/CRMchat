from __future__ import annotations

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.main import create_app
from app.models import Campaign, ConversationStatus, KOC


def _auth(user_id: str) -> dict[str, str]:
    return {"X-User-Id": user_id}


def test_booker_only_sees_own_conversations(tmp_path):
    app = create_app(f"sqlite:///{tmp_path}/t1.db")
    with TestClient(app) as client:
        engine = app.state.engine
        with Session(engine) as s:
            koc = KOC(display_name="K1")
            camp = Campaign(name="C1")
            s.add(koc)
            s.add(camp)
            s.commit()
            s.refresh(koc)
            s.refresh(camp)

        # booker-1 creates conversation assigned to self
        r = client.post(
            "/conversations",
            headers=_auth("booker-1"),
            json={"koc_id": str(koc.id), "campaign_id": str(camp.id), "assigned_booker_id": "booker-1"},
        )
        assert r.status_code == 200, r.text
        created = r.json()
        conv_id = created["id"]
        assert created["koc_id"] == str(koc.id)
        assert created["campaign_id"] == str(camp.id)

        # booker-1 lists -> sees it
        r = client.get("/conversations", headers=_auth("booker-1"))
        assert r.status_code == 200
        convs = r.json()
        assert [c["id"] for c in convs] == [conv_id]
        assert convs[0]["koc_id"] == str(koc.id)
        assert convs[0]["campaign_id"] == str(camp.id)

        # booker-2 lists -> sees none
        r = client.get("/conversations", headers=_auth("booker-2"))
        assert r.status_code == 200
        assert r.json() == []


def test_manager_sees_team_conversations(tmp_path):
    app = create_app(f"sqlite:///{tmp_path}/t2.db")
    with TestClient(app) as client:
        engine = app.state.engine
        with Session(engine) as s:
            k1 = KOC(display_name="K1")
            k2 = KOC(display_name="K2")
            camp = Campaign(name="C1")
            s.add_all([k1, k2, camp])
            s.commit()
            s.refresh(k1)
            s.refresh(k2)
            s.refresh(camp)

        r1 = client.post(
            "/conversations",
            headers=_auth("manager-1"),
            json={"koc_id": str(k1.id), "campaign_id": str(camp.id), "assigned_booker_id": "booker-1"},
        )
        r2 = client.post(
            "/conversations",
            headers=_auth("manager-1"),
            json={"koc_id": str(k2.id), "campaign_id": str(camp.id), "assigned_booker_id": "booker-2"},
        )
        assert r1.status_code == 200, r1.text
        assert r2.status_code == 200, r2.text
        assert r1.json()["koc_id"] == str(k1.id)
        assert r1.json()["campaign_id"] == str(camp.id)
        assert r2.json()["koc_id"] == str(k2.id)
        assert r2.json()["campaign_id"] == str(camp.id)

        r = client.get("/conversations", headers=_auth("manager-1"))
        assert r.status_code == 200
        ids = {c["id"] for c in r.json()}
        assert ids == {r1.json()["id"], r2.json()["id"]}


def test_cannot_add_message_without_permission_and_audit_is_immutable(tmp_path):
    app = create_app(f"sqlite:///{tmp_path}/t3.db")
    with TestClient(app) as client:
        engine = app.state.engine
        with Session(engine) as s:
            k1 = KOC(display_name="K1")
            k_other = KOC(display_name="K2")
            camp = Campaign(name="C1")
            s.add_all([k1, k_other, camp])
            s.commit()
            s.refresh(k1)
            s.refresh(k_other)
            s.refresh(camp)

        r = client.post(
            "/conversations",
            headers=_auth("manager-1"),
            json={"koc_id": str(k1.id), "campaign_id": str(camp.id), "assigned_booker_id": "booker-1"},
        )
        assert r.status_code == 200, r.text
        created = r.json()
        conv_id = created["id"]
        assert created["koc_id"] == str(k1.id)
        assert created["campaign_id"] == str(camp.id)

        # booker-2 cannot add message
        r = client.post(
            f"/conversations/{conv_id}/messages",
            headers=_auth("booker-2"),
            json={"body": "hello"},
        )
        assert r.status_code == 403

        # booker-1 can add message
        r = client.post(
            f"/conversations/{conv_id}/messages",
            headers=_auth("booker-1"),
            json={"body": "deal 10tr", "attach_to_koc_id": str(k1.id), "attach_to_campaign_id": str(camp.id)},
        )
        assert r.status_code == 200, r.text
        msg_id = r.json()["id"]

        # mismatch attach should fail
        r = client.post(
            f"/conversations/{conv_id}/messages",
            headers=_auth("booker-1"),
            json={"body": "bad attach", "attach_to_koc_id": str(k_other.id)},
        )
        assert r.status_code == 400

        # audit log must exist for message
        r = client.get(f"/conversations/{conv_id}/audits", headers=_auth("booker-1"))
        assert r.status_code == 200, r.text
        audits = r.json()
        assert len(audits) == 1
        assert audits[0]["event_type"] == "message_added"
        assert audits[0]["payload"]["message_id"] == msg_id

        # status change must create audit
        r = client.patch(
            f"/conversations/{conv_id}/status",
            headers=_auth("booker-1"),
            json={"status": ConversationStatus.negotiating},
        )
        assert r.status_code == 200

        r = client.get(f"/conversations/{conv_id}/audits", headers=_auth("booker-1"))
        audits2 = r.json()
        assert len(audits2) == 2
        assert audits2[1]["event_type"] == "conversation_status_changed"

        # "immutable" from API PoV: there is no endpoint to modify/delete audit.
        # We at least assert that the original message audit still exists unchanged.
        assert audits2[0]["event_type"] == "message_added"
        assert audits2[0]["payload"]["message_id"] == msg_id


def test_create_conversation_requires_existing_koc_and_campaign(tmp_path):
    app = create_app(f"sqlite:///{tmp_path}/t4.db")
    with TestClient(app) as client:
        engine = app.state.engine
        with Session(engine) as s:
            camp = Campaign(name="C1")
            s.add(camp)
            s.commit()
            s.refresh(camp)

        # KOC does not exist -> 404
        r = client.post(
            "/conversations",
            headers=_auth("manager-1"),
            json={
                "koc_id": "11111111-1111-1111-1111-111111111111",
                "campaign_id": str(camp.id),
                "assigned_booker_id": "booker-1",
            },
        )
        assert r.status_code == 404

        with Session(engine) as s:
            koc = KOC(display_name="K1")
            s.add(koc)
            s.commit()
            s.refresh(koc)

        # Campaign does not exist -> 404
        r = client.post(
            "/conversations",
            headers=_auth("manager-1"),
            json={
                "koc_id": str(koc.id),
                "campaign_id": "22222222-2222-2222-2222-222222222222",
                "assigned_booker_id": "booker-1",
            },
        )
        assert r.status_code == 404


def test_create_conversation_missing_koc_or_campaign_is_422(tmp_path):
    app = create_app(f"sqlite:///{tmp_path}/t5.db")
    with TestClient(app) as client:
        r = client.post(
            "/conversations",
            headers=_auth("manager-1"),
            json={"assigned_booker_id": "booker-1"},
        )
        assert r.status_code == 422

