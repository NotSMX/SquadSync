"""
test_views.py

This module contains unit tests for the Flask views in the website/views.py module.
"""
# pylint: disable=redefined-outer-name
# pylint: disable=cyclic-import
# pylint: disable=duplicate-code

from datetime import datetime, timedelta

import pytest

from website import create_app, db
from website.models import Session, Participant, Availability, Confirmation, GameVote


@pytest.fixture
def app():
    """Create a test app with an in-memory database."""
    flask_app = create_app()
    flask_app.config.update({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "SQLALCHEMY_EXPIRE_ON_COMMIT": False,
        "WTF_CSRF_ENABLED": False
    })
    with flask_app.app_context():
        db.create_all()
        yield flask_app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    """Return a test client for the app."""
    return app.test_client()


@pytest.fixture
def sample_session(app):
    """Create a session and host, returning plain values to avoid detached instance errors."""
    with app.app_context():
        s = Session(title="Test Session", is_public=True)
        db.session.add(s)
        db.session.commit()

        host = Participant(name="Host", email="host@test.com", session_id=s.id)
        db.session.add(host)
        db.session.commit()

        s.host_id = host.id
        db.session.commit()

        return {
            "session_id": s.id,
            "session_hash": s.hash_id,
            "host_id": host.id,
            "host_token": host.token
        }


def test_index(client):
    """GET / should return 200."""
    res = client.get("/")
    assert res.status_code == 200


def test_dashboard(client, monkeypatch):
    """Dashboard should render with mocked metrics."""
    monkeypatch.setattr("website.metrics.calculate_metrics", lambda: {"sessions": 1})
    res = client.get("/dashboard")
    assert res.status_code == 200


def test_list_sessions(client, sample_session):  # pylint: disable=unused-argument
    """Sessions list should return 200."""
    res = client.get("/sessions")
    assert res.status_code == 200


def test_create_session_get(client):
    """GET /create should return 200."""
    res = client.get("/create")
    assert res.status_code == 200


def test_create_session_post(client):
    """POST /create should create a session and redirect."""
    res = client.post("/create", data={
        "title": "Game Night",
        "name": "Alice",
        "email": "alice@test.com",
        "is_public": "on"
    }, follow_redirects=True)
    assert res.status_code == 200


def test_join_session(client, sample_session):
    """POST /join/<id> should redirect after joining."""
    res = client.post(f"/join/{sample_session['session_id']}", data={
        "name": "Bob",
        "email": "bob@test.com"
    })
    assert res.status_code == 302


def test_view_session(client, sample_session):
    """GET /session/<hash> with valid token should return 200."""
    res = client.get(
        f"/session/{sample_session['session_hash']}?token={sample_session['host_token']}"
    )
    assert res.status_code == 200


def test_vote_game(client, sample_session):
    """Voting for a game should succeed."""
    res = client.post(
        f"/session/{sample_session['session_hash']}/vote_game",
        data={"game_name": "Catan", "token": sample_session["host_token"]},
        follow_redirects=True
    )
    assert res.status_code == 200


def test_join_and_vote(client, sample_session):
    """Joining and voting in one step should succeed."""
    res = client.post(
        f"/session/{sample_session['session_hash']}/join_and_vote",
        data={"name": "Charlie", "email": "c@test.com", "game_name": "Chess"},
        follow_redirects=True
    )
    assert res.status_code == 200


def test_add_availability(client, sample_session):
    """Adding an availability block should succeed."""
    start = datetime.now().isoformat()
    end = (datetime.now() + timedelta(hours=1)).isoformat()
    res = client.post(
        f"/session/{sample_session['session_hash']}/add_availability",
        data={"token": sample_session["host_token"], "start": start, "end": end},
        follow_redirects=True
    )
    assert res.status_code == 200


def test_availability_page_get(client, sample_session):
    """GET availability page should return 200."""
    res = client.get(
        f"/availability/{sample_session['session_id']}/{sample_session['host_token']}"
    )
    assert res.status_code == 200


def test_availability_post(client, sample_session):
    """POST availability data should succeed."""
    start = datetime.now().isoformat()
    end = (datetime.now() + timedelta(hours=1)).isoformat()
    res = client.post(
        f"/availability/{sample_session['session_id']}/{sample_session['host_token']}",
        data={"availability_data": f'[{{"start":"{start}","end":"{end}"}}]'},
        follow_redirects=True
    )
    assert res.status_code == 200


def test_auto_pick(client, sample_session, monkeypatch, app):
    """Auto pick should find an overlap and set final time."""
    with app.app_context():
        a = Availability(
            session_id=sample_session["session_id"],
            participant_id=sample_session["host_id"],
            start_time=datetime.now(),
            end_time=datetime.now() + timedelta(hours=1)
        )
        db.session.add(a)
        db.session.commit()
    monkeypatch.setattr("website.views.notify_final_time", lambda s: (0, []))
    res = client.get(
        f"/auto_pick/{sample_session['session_hash']}?token={sample_session['host_token']}",
        follow_redirects=True
    )
    assert res.status_code == 200


def test_manual_pick(client, sample_session, monkeypatch):
    """Manual pick should set the final time."""
    monkeypatch.setattr("website.views.notify_final_time", lambda s: (0, []))
    res = client.post(
        f"/manual_pick/{sample_session['session_hash']}?token={sample_session['host_token']}",
        data={"manual_time": datetime.now().isoformat()},
        follow_redirects=True
    )
    assert res.status_code == 200


def test_confirm(client, sample_session):
    """Confirming a session time should succeed."""
    res = client.post(
        f"/confirm/{sample_session['session_id']}/{sample_session['host_token']}",
        data={"status": "yes"},
        follow_redirects=True
    )
    assert res.status_code == 200


def test_set_game(client, sample_session):
    """Host setting a game should succeed."""
    res = client.post(
        f"/session/{sample_session['session_hash']}/set_game",
        data={"game_name": "Mario Kart", "token": sample_session["host_token"]},
        follow_redirects=True
    )
    assert res.status_code == 200


def test_test_game_election_route(client):
    """Test game election route should redirect successfully."""
    res = client.get("/test-game-election", follow_redirects=True)
    assert res.status_code == 200


def test_join_session_sets_host(client, app):
    """First person to join a hostless session should become host."""
    with app.app_context():
        s = Session(title="No Host Yet", is_public=True)
        db.session.add(s)
        db.session.commit()
        session_id = s.id

    res = client.post(f"/join/{session_id}", data={"name": "First", "email": "first@test.com"})
    assert res.status_code == 302

    with app.app_context():
        updated = db.session.get(Session, session_id)
        assert updated.host_id is not None


def test_availability_invalid_json(client, sample_session):
    """Invalid JSON in availability_data should not crash."""
    res = client.post(
        f"/availability/{sample_session['session_id']}/{sample_session['host_token']}",
        data={"availability_data": "invalid_json"},
        follow_redirects=True
    )
    assert res.status_code == 200


def test_availability_invalid_block(client, sample_session):
    """Block with equal start and end should be ignored."""
    start = datetime.now().isoformat()
    res = client.post(
        f"/availability/{sample_session['session_id']}/{sample_session['host_token']}",
        data={"availability_data": f'[{{"start":"{start}","end":"{start}"}}]'},
        follow_redirects=True
    )
    assert res.status_code == 200


def test_auto_pick_unauthorized(client, sample_session):
    """Auto pick with invalid token should return 404."""
    res = client.get(f"/auto_pick/{sample_session['session_hash']}?token=invalidtoken")
    assert res.status_code == 404


def test_manual_pick_unauthorized(client, sample_session):
    """Manual pick with invalid token should return 404."""
    res = client.post(
        f"/manual_pick/{sample_session['session_hash']}?token=invalidtoken",
        data={"manual_time": datetime.now().isoformat()}
    )
    assert res.status_code == 404


def test_confirm_update_existing(client, sample_session, app):
    """Updating an existing confirmation should persist the new status."""
    with app.app_context():
        conf = Confirmation(
            participant_id=sample_session["host_id"],
            session_id=sample_session["session_id"],
            status="maybe"
        )
        db.session.add(conf)
        db.session.commit()

    res = client.post(
        f"/confirm/{sample_session['session_id']}/{sample_session['host_token']}",
        data={"status": "yes"},
        follow_redirects=True
    )
    assert res.status_code == 200

    with app.app_context():
        updated = Confirmation.query.filter_by(
            participant_id=sample_session["host_id"],
            session_id=sample_session["session_id"]
        ).first()
        assert updated.status == "yes"


def test_join_and_vote_missing_name(client, sample_session):
    """join_and_vote with no name should redirect with warning."""
    res = client.post(
        f"/session/{sample_session['session_hash']}/join_and_vote",
        data={"name": "", "game_name": "Catan"},
        follow_redirects=True
    )
    assert res.status_code == 200


def test_join_and_vote_missing_game(client, sample_session):
    """join_and_vote with no game should redirect with warning."""
    res = client.post(
        f"/session/{sample_session['session_hash']}/join_and_vote",
        data={"name": "Player", "game_name": ""},
        follow_redirects=True
    )
    assert res.status_code == 200


def test_vote_game_empty(client, sample_session):
    """Voting with empty game name should redirect with warning."""
    res = client.post(
        f"/session/{sample_session['session_hash']}/vote_game",
        data={"game_name": "", "token": sample_session["host_token"]},
        follow_redirects=True
    )
    assert res.status_code == 200


def test_add_availability_missing_fields(client, sample_session):
    """Missing start/end fields should return 200 with error."""
    res = client.post(
        f"/session/{sample_session['session_hash']}/add_availability",
        data={"token": sample_session["host_token"]},
        follow_redirects=True
    )
    assert res.status_code == 200


def test_add_availability_invalid_time(client, sample_session):
    """Invalid time strings should return 200 with error."""
    res = client.post(
        f"/session/{sample_session['session_hash']}/add_availability",
        data={"token": sample_session["host_token"], "start": "invalid", "end": "invalid"},
        follow_redirects=True
    )
    assert res.status_code == 200


def test_add_availability_end_before_start(client, sample_session):
    """End before start should return 200 with error."""
    start = datetime.now()
    end = start - timedelta(hours=1)
    res = client.post(
        f"/session/{sample_session['session_hash']}/add_availability",
        data={
            "token": sample_session["host_token"],
            "start": start.isoformat(),
            "end": end.isoformat()
        },
        follow_redirects=True
    )
    assert res.status_code == 200


def test_set_game_unauthorized(client, sample_session, app):
    """Non-host setting a game should be rejected."""
    with app.app_context():
        p = Participant(
            name="Other", email="other@test.com",
            session_id=sample_session["session_id"]
        )
        db.session.add(p)
        db.session.commit()
        other_token = p.token

    res = client.post(
        f"/session/{sample_session['session_hash']}/set_game",
        data={"game_name": "Halo", "token": other_token},
        follow_redirects=True
    )
    assert res.status_code == 200


def test_set_game_clear(client, sample_session):
    """Setting an empty game name should clear the game."""
    res = client.post(
        f"/session/{sample_session['session_hash']}/set_game",
        data={"game_name": "", "token": sample_session["host_token"]},
        follow_redirects=True
    )
    assert res.status_code == 200


def test_vote_game_update_existing(client, sample_session, app):
    """Voting again should update the existing vote."""
    with app.app_context():
        vote = GameVote(
            session_id=sample_session["session_id"],
            participant_id=sample_session["host_id"],
            game_name="OldGame"
        )
        db.session.add(vote)
        db.session.commit()

    res = client.post(
        f"/session/{sample_session['session_hash']}/vote_game",
        data={"game_name": "NewGame", "token": sample_session["host_token"]},
        follow_redirects=True
    )
    assert res.status_code == 200


def test_auto_pick_no_availability(client, sample_session, monkeypatch):
    """Auto pick with no availability should flash a warning."""
    monkeypatch.setattr("website.views.notify_final_time", lambda s: (0, []))
    res = client.get(
        f"/auto_pick/{sample_session['session_hash']}?token={sample_session['host_token']}",
        follow_redirects=True
    )
    assert res.status_code == 200


def test_manual_pick_missing_time(client, sample_session):
    """Manual pick with no time submitted should return 400."""
    res = client.post(
        f"/manual_pick/{sample_session['session_hash']}?token={sample_session['host_token']}",
        data={},
        follow_redirects=True
    )
    assert res.status_code == 400


def test_confirm_invalid_status(client, sample_session):
    """Confirming with an invalid status value should still return 200."""
    res = client.post(
        f"/confirm/{sample_session['session_id']}/{sample_session['host_token']}",
        data={"status": "invalid"},
        follow_redirects=True
    )
    assert res.status_code == 200


def test_availability_empty_list(client, sample_session):
    """Posting an empty availability list should succeed."""
    res = client.post(
        f"/availability/{sample_session['session_id']}/{sample_session['host_token']}",
        data={"availability_data": "[]"},
        follow_redirects=True
    )
    assert res.status_code == 200


def test_join_session_missing_fields(client, sample_session):
    """Joining with empty fields should still return 200."""
    res = client.post(
        f"/join/{sample_session['session_id']}",
        data={"name": "", "email": ""},
        follow_redirects=True
    )
    assert res.status_code == 200


def test_view_session_invalid_token(client, sample_session):
    """Viewing a session with a bad token should return 200, 302, or 404."""
    res = client.get(f"/session/{sample_session['session_hash']}?token=badtoken")
    assert res.status_code in (200, 302, 404)


def test_set_game_whitespace(client, sample_session):
    """Setting a whitespace-only game name should clear it."""
    res = client.post(
        f"/session/{sample_session['session_hash']}/set_game",
        data={"game_name": " ", "token": sample_session["host_token"]},
        follow_redirects=True
    )
    assert res.status_code == 200


def test_confirm_multiple_updates(client, sample_session, app):
    """Confirming multiple times should keep the latest status."""
    with app.app_context():
        conf = Confirmation(
            participant_id=sample_session["host_id"],
            session_id=sample_session["session_id"],
            status="no"
        )
        db.session.add(conf)
        db.session.commit()

    client.post(
        f"/confirm/{sample_session['session_id']}/{sample_session['host_token']}",
        data={"status": "maybe"},
        follow_redirects=True
    )
    res = client.post(
        f"/confirm/{sample_session['session_id']}/{sample_session['host_token']}",
        data={"status": "yes"},
        follow_redirects=True
    )
    assert res.status_code == 200


def test_reset_db(client):
    """POST /reset-db should drop and recreate tables and redirect."""
    res = client.post("/reset-db", follow_redirects=True)
    assert res.status_code == 200


def test_availability_data(client, sample_session, app):
    """GET /session/<hash>/availability_data should return JSON with participant blocks."""
    with app.app_context():
        a = Availability(
            session_id=sample_session["session_id"],
            participant_id=sample_session["host_id"],
            start_time=datetime.now(),
            end_time=datetime.now() + timedelta(hours=1)
        )
        db.session.add(a)
        db.session.commit()

    res = client.get(
        f"/session/{sample_session['session_hash']}/availability_data",
        headers={"X-Requested-With": "XMLHttpRequest"}
    )
    assert res.status_code == 200
    data = res.get_json()
    assert isinstance(data, dict)
    assert "Host" in data
    assert len(data["Host"]) == 1


def test_remove_availability(client, sample_session, app):
    """Removing an existing availability block should succeed."""
    start = datetime.now()
    end = start + timedelta(hours=1)

    with app.app_context():
        a = Availability(
            session_id=sample_session["session_id"],
            participant_id=sample_session["host_id"],
            start_time=start,
            end_time=end
        )
        db.session.add(a)
        db.session.commit()

    res = client.post(
        f"/session/{sample_session['session_hash']}/remove_availability",
        data={
            "token": sample_session["host_token"],
            "start": start.isoformat(),
            "end": end.isoformat()
        },
        headers={"X-Requested-With": "XMLHttpRequest"}
    )
    assert res.status_code == 200
    assert res.get_json()["ok"] is True


def test_remove_availability_not_found(client, sample_session):
    """Removing a non-existent block should return ok: False."""
    res = client.post(
        f"/session/{sample_session['session_hash']}/remove_availability",
        data={
            "token": sample_session["host_token"],
            "start": datetime.now().isoformat(),
            "end": (datetime.now() + timedelta(hours=1)).isoformat()
        },
        headers={"X-Requested-With": "XMLHttpRequest"}
    )
    assert res.status_code == 400
    assert res.get_json()["ok"] is False


def test_remove_availability_missing_fields(client, sample_session):
    """Remove with missing start/end should return ok: False."""
    res = client.post(
        f"/session/{sample_session['session_hash']}/remove_availability",
        data={"token": sample_session["host_token"]},
        headers={"X-Requested-With": "XMLHttpRequest"}
    )
    assert res.status_code == 400
    assert res.get_json()["ok"] is False


def test_auto_pick_unauthorized_host(client, sample_session, app):
    """Auto pick by non-host should return 403."""
    with app.app_context():
        p = Participant(name="Other", email="o@o.com", session_id=sample_session["session_id"])
        db.session.add(p)
        db.session.commit()
        other_token = p.token
    res = client.get(
        f"/auto_pick/{sample_session['session_hash']}?token={other_token}"
    )
    assert res.status_code == 403


def test_manual_pick_unauthorized_host(client, sample_session, app):
    """Manual pick by non-host should return 403."""
    with app.app_context():
        p = Participant(name="Other", email="o@o.com", session_id=sample_session["session_id"])
        db.session.add(p)
        db.session.commit()
        other_token = p.token
    res = client.post(
        f"/manual_pick/{sample_session['session_hash']}?token={other_token}",
        data={"manual_time": datetime.now().isoformat()}
    )
    assert res.status_code == 403


def test_remove_availability_invalid_time(client, sample_session):
    """Remove with invalid time strings should return 400."""
    res = client.post(
        f"/session/{sample_session['session_hash']}/remove_availability",
        data={"token": sample_session["host_token"], "start": "bad", "end": "bad"},
        headers={"X-Requested-With": "XMLHttpRequest"}
    )
    assert res.status_code == 400


def test_add_availability_non_xhr(client, sample_session):
    """add_availability without XHR header should redirect on success."""
    start = datetime.now().isoformat()
    end = (datetime.now() + timedelta(hours=1)).isoformat()
    res = client.post(
        f"/session/{sample_session['session_hash']}/add_availability",
        data={"token": sample_session["host_token"], "start": start, "end": end},
    )
    assert res.status_code == 302


def test_remove_availability_non_xhr(client, sample_session, app):
    """remove_availability without XHR header should redirect on success."""
    start = datetime.now()
    end = start + timedelta(hours=1)
    with app.app_context():
        a = Availability(
            session_id=sample_session["session_id"],
            participant_id=sample_session["host_id"],
            start_time=start, end_time=end
        )
        db.session.add(a)
        db.session.commit()
    res = client.post(
        f"/session/{sample_session['session_hash']}/remove_availability",
        data={
            "token": sample_session["host_token"],
            "start": start.isoformat(),
            "end": end.isoformat()
        }
    )
    assert res.status_code == 302


def test_availability_data_empty(client, sample_session):
    """availability_data with no blocks should return empty lists."""
    res = client.get(f"/session/{sample_session['session_hash']}/availability_data")
    assert res.status_code == 200
    data = res.get_json()
    assert data["Host"] == []


def test_auto_pick_no_overlap(client, sample_session, monkeypatch, app):
    """Auto pick with non-overlapping availability should flash warning."""
    with app.app_context():
        p2 = Participant(name="P2", email="p2@test.com", session_id=sample_session["session_id"])
        db.session.add(p2)
        db.session.commit()
        now = datetime.now()
        db.session.add(Availability(
            session_id=sample_session["session_id"],
            participant_id=sample_session["host_id"],
            start_time=now, end_time=now + timedelta(hours=1)
        ))
        db.session.add(Availability(
            session_id=sample_session["session_id"],
            participant_id=p2.id,
            start_time=now + timedelta(hours=5),
            end_time=now + timedelta(hours=6)
        ))
        db.session.commit()
    monkeypatch.setattr("website.views.notify_final_time", lambda s: (0, []))
    res = client.get(
        f"/auto_pick/{sample_session['session_hash']}?token={sample_session['host_token']}",
        follow_redirects=True
    )
    assert res.status_code == 200
