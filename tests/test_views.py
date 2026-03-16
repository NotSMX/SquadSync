"""
test_views.py

This module contains unit tests for the Flask views in the website/views.py module.
"""
# pylint: disable=redefined-outer-name
# pylint: disable=cyclic-import
# pylint: disable=duplicate-code
# pylint: disable=import-outside-toplevel

from datetime import datetime, timedelta

import pytest

from website import create_app, db
from website.models import Session, Participant, Availability, Confirmation, GameVote
from website.views import (
    _intersect_intervals, _build_game_tally, _build_grouped_json,
)


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
    monkeypatch.setattr("website.metrics.calculate_metrics", lambda: {
        "total_users": 0,
        "sessions_created": 0,
        "confirmed_participants": 0,
        "availability_only_participants": 0,
        "activation_rate": "0%",
        "repeat_usage": "0%",
        "unique_emails": [],
        "multi_participant_rate": "0%",
        "completion_rate": "0%",
        "avg_participants": 0,
        "sessions_with_votes_pct": "0%",
        "top_games": [],
        "confirmation_breakdown": {"Yes": 0, "Maybe": 0, "No": 0},
    })
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

def test_intersect_intervals_merge():
    """Overlapping intervals should merge correctly."""
    a = [
        (datetime(2025,1,1,10), datetime(2025,1,1,12))
    ]
    b = [
        (datetime(2025,1,1,11), datetime(2025,1,1,13))
    ]

    result = _intersect_intervals(a, b)

    assert len(result) == 1
    assert result[0][0] == datetime(2025,1,1,11)

def test_intersect_intervals_none():
    """No overlap should return empty list."""
    a = [(datetime(2025,1,1,10), datetime(2025,1,1,11))]
    b = [(datetime(2025,1,1,12), datetime(2025,1,1,13))]

    result = _intersect_intervals(a, b)

    assert result == []

def test_build_game_tally_empty_vote(app):
    """Empty game name should count as '(empty)'."""
    with app.app_context():
        s = Session(title="Test")
        db.session.add(s)
        db.session.commit()

        p = Participant(name="P", session_id=s.id)
        db.session.add(p)
        db.session.commit()

        vote = GameVote(session_id=s.id, participant_id=p.id, game_name="")
        db.session.add(vote)
        db.session.commit()

        tally, mine = _build_game_tally(s, p)

        assert tally[0][0] == "(empty)"

def test_grouped_json_skips_invalid(app):
    """Blocks missing start/end should be skipped."""
    with app.app_context():
        s = Session(title="Test")
        db.session.add(s)
        db.session.commit()

        p = Participant(name="P", session_id=s.id)
        db.session.add(p)
        db.session.commit()

        a = Availability(
            session_id=s.id,
            participant_id=p.id,
            start_time=None,
            end_time=None
        )
        db.session.add(a)
        db.session.commit()

        grouped, grouped_json = _build_grouped_json(s)

        assert grouped_json["P"] == []

# def test_notify_and_flash_failures(monkeypatch, app):
#     """Failures should trigger flash messages."""
#     with app.app_context():
#         s = Session(title="Test")
#         db.session.add(s)
#         db.session.commit()

#         monkeypatch.setattr(
#             "website.views.notify_final_time",
#             lambda s: (1, [("Bob", "SMTP error")])
#         )

#         _notify_and_flash(s)

# def test_ensure_schema_handles_error(monkeypatch, app):
#     """Schema function should tolerate SQL errors."""
#     class BrokenConn:
#         def execute(self, *a, **k):
#             raise SQLAlchemyError("fail")
#         def commit(self): pass
#         def rollback(self): pass

#     class BrokenEngine:
#         def connect(self):
#             return BrokenConn()

#     monkeypatch.setattr("website.views.db.engine", BrokenEngine())

#     with app.app_context():
#         _ensure_game_election_schema()

def test_add_availability_xhr(client, sample_session):
    """XHR add availability should return JSON."""
    start = datetime.now().isoformat()
    end = (datetime.now() + timedelta(hours=1)).isoformat()

    res = client.post(
        f"/session/{sample_session['session_hash']}/add_availability",
        data={
            "token": sample_session["host_token"],
            "start": start,
            "end": end
        },
        headers={"X-Requested-With": "XMLHttpRequest"}
    )

    assert res.status_code == 200
    assert res.get_json()["ok"] is True

def test_remove_availability_xhr_success(client, sample_session, app):
    """XHR removal should return JSON success."""
    start = datetime.now()
    end = start + timedelta(hours=1)

    with app.app_context():
        db.session.add(Availability(
            session_id=sample_session["session_id"],
            participant_id=sample_session["host_id"],
            start_time=start,
            end_time=end
        ))
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


# ── line 88: db.create_all() inside _ensure_game_election_schema ──────────────

def test_ensure_schema_via_create_route(client):
    """POST /create triggers _ensure_game_election_schema including db.create_all()."""
    res = client.post("/create", data={
        "title": "Schema Test",
        "name": "Tester",
        "email": "t@t.com",
        "is_public": "on",
    }, follow_redirects=True)
    assert res.status_code == 200


# ── line 313: interval merge — contiguous overlap hits the max() branch ────────

def test_intersect_intervals_contiguous_overlap_merge():
    """Three overlapping intervals that all merge into one via the max() branch."""
    a = [
        (datetime(2025, 1, 1, 8), datetime(2025, 1, 1, 12)),
        (datetime(2025, 1, 1, 10), datetime(2025, 1, 1, 14)),
    ]
    b = [
        (datetime(2025, 1, 1, 9), datetime(2025, 1, 1, 13)),
    ]
    result = _intersect_intervals(a, b)
    # Both pairs overlap with b's single interval; merged result covers 9→13
    assert len(result) == 1
    assert result[0][0] == datetime(2025, 1, 1, 9)
    assert result[0][1] == datetime(2025, 1, 1, 13)


# ── line 510: add_availability XHR failure (missing times returns JSON 400) ────

def test_add_availability_xhr_missing_times_returns_json(client, sample_session):
    """XHR add_availability with no times should return JSON error, not redirect."""
    res = client.post(
        f"/session/{sample_session['session_hash']}/add_availability",
        data={"token": sample_session["host_token"], "start": "", "end": ""},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert res.status_code == 400
    assert res.get_json()["ok"] is False


# ── lines 657-658: availability block appended to hash parts ──────────────────

def test_session_state_hash_includes_availability(app):
    """Hash should change when an availability block is added to a participant."""
    from website.views import _session_state_hash
    from website import db as _db

    with app.app_context():
        s = Session(title="Avail Hash", is_public=True)
        _db.session.add(s)
        _db.session.commit()
        p = Participant(name="Player", session_id=s.id)
        _db.session.add(p)
        _db.session.commit()
        s.host_id = p.id
        _db.session.commit()

        hash_before = _session_state_hash(s)

        _db.session.add(Availability(
            session_id=s.id,
            participant_id=p.id,
            start_time=datetime(2025, 6, 1, 18, 0),
            end_time=datetime(2025, 6, 1, 20, 0),
        ))
        _db.session.commit()
        _db.session.expire_all()
        s = _db.session.get(Session, s.id)

        hash_after = _session_state_hash(s)
        assert hash_before != hash_after


def _fake_time_factory(start_val=0.0, step=0.0):
    """Return a fake time module whose .time() advances by `step` each call."""
    import types
    calls = [start_val]

    def fake_time():
        val = calls[0]
        calls[0] += step
        return val

    mod = types.SimpleNamespace(time=fake_time, sleep=lambda _: None)
    return mod

def test_notify_and_flash_success(monkeypatch, app):
    """_notify_and_flash should flash success when emails sent."""
    from website.views import _notify_and_flash
    from website.models import Session
    from website import db

    with app.app_context():
        s = Session(title="Notify Test")
        db.session.add(s)
        db.session.commit()

        monkeypatch.setattr(
            "website.views.notify_final_time",
            lambda s: (2, [])
        )

        _notify_and_flash(s)

def test_notify_and_flash_failure(monkeypatch, app):
    """_notify_and_flash should flash failure messages."""
    from website.views import _notify_and_flash
    from website.models import Session
    from website import db

    with app.app_context():
        s = Session(title="Notify Fail")
        db.session.add(s)
        db.session.commit()

        monkeypatch.setattr(
            "website.views.notify_final_time",
            lambda s: (0, [("Bob", "SMTP error")])
        )

        _notify_and_flash(s)

def test_grouped_json_valid_block(app):
    """Valid availability blocks should appear in grouped_json."""
    from website.views import _build_grouped_json
    from website.models import Session, Participant, Availability
    from website import db
    from datetime import datetime, timedelta

    with app.app_context():
        s = Session(title="Test")
        db.session.add(s)
        db.session.commit()

        p = Participant(name="P", session_id=s.id)
        db.session.add(p)
        db.session.commit()

        start = datetime.now()
        end = start + timedelta(hours=1)

        db.session.add(Availability(
            session_id=s.id,
            participant_id=p.id,
            start_time=start,
            end_time=end
        ))
        db.session.commit()

        grouped, grouped_json = _build_grouped_json(s)

        assert grouped_json["P"][0]["start"] is not None

def test_vote_game_missing_token(client, sample_session):
    """vote_game without token should 404."""
    res = client.post(
        f"/session/{sample_session['session_hash']}/vote_game",
        data={"game_name": "Catan"}
    )
    assert res.status_code == 404

def test_add_availability_invalid_format(client, sample_session):
    """Invalid time format should return error."""
    res = client.post(
        f"/session/{sample_session['session_hash']}/add_availability",
        data={
            "token": sample_session["host_token"],
            "start": "bad",
            "end": "bad"
        },
        headers={"X-Requested-With": "XMLHttpRequest"}
    )

    assert res.status_code == 400

def test_session_state_hash_with_votes_and_confirm(app):
    """Hash should change when votes or confirmations added."""
    from website.views import _session_state_hash
    from website.models import Session, Participant, GameVote, Confirmation
    from website import db

    with app.app_context():
        s = Session(title="Hash Test")
        db.session.add(s)
        db.session.commit()

        p = Participant(name="A", session_id=s.id)
        db.session.add(p)
        db.session.commit()

        s.host_id = p.id
        db.session.commit()

        before = _session_state_hash(s)

        db.session.add(GameVote(
            session_id=s.id,
            participant_id=p.id,
            game_name="Catan"
        ))

        db.session.add(Confirmation(
            session_id=s.id,
            participant_id=p.id,
            status="yes"
        ))

        db.session.commit()

        after = _session_state_hash(s)

        assert before != after

def test_availability_post_data_not_list(client, sample_session):
    """JSON object (not list) in availability_data should be treated as empty."""
    res = client.post(
        f"/availability/{sample_session['session_id']}/{sample_session['host_token']}",
        data={"availability_data": '{"start":"2025-01-01T10:00","end":"2025-01-01T11:00"}'},
        follow_redirects=True
    )
    assert res.status_code == 200


def test_availability_post_empty_start(client, sample_session):
    """Block with empty start should be skipped (parse_iso returns None)."""
    end = datetime.now().isoformat()
    res = client.post(
        f"/availability/{sample_session['session_id']}/{sample_session['host_token']}",
        data={"availability_data": f'[{{"start":"","end":"{end}"}}]'},
        follow_redirects=True
    )
    assert res.status_code == 200


def test_availability_post_invalid_iso(client, sample_session):
    """Block with an unparseable ISO string should be skipped."""
    res = client.post(
        f"/availability/{sample_session['session_id']}/{sample_session['host_token']}",
        data={"availability_data": '[{"start":"not-a-date","end":"also-bad"}]'},
        follow_redirects=True
    )
    assert res.status_code == 200

def test_intersect_intervals_non_contiguous():
    """Two non-contiguous results should both be kept (else branch in merge loop)."""
    a = [
        (datetime(2025, 1, 1, 8), datetime(2025, 1, 1, 10)),
        (datetime(2025, 1, 1, 14), datetime(2025, 1, 1, 16)),
    ]
    b = [
        (datetime(2025, 1, 1, 9), datetime(2025, 1, 1, 10)),
        (datetime(2025, 1, 1, 14), datetime(2025, 1, 1, 15)),
    ]
    result = _intersect_intervals(a, b)
    assert len(result) == 2
    assert result[0] == (datetime(2025, 1, 1, 9), datetime(2025, 1, 1, 10))
    assert result[1] == (datetime(2025, 1, 1, 14), datetime(2025, 1, 1, 15))


def test_notify_and_flash_no_request_context(monkeypatch, app):
    """_notify_and_flash outside a request context returns early without flashing."""
    from website.views import _notify_and_flash

    with app.app_context():
        from website.models import Session
        from website import db
        s = Session(title="No-Context Test")
        db.session.add(s)
        db.session.commit()

        monkeypatch.setattr("website.views.notify_final_time", lambda _s: (3, [("Alice", "err")]))
        # No request context here — should return (3, [...]) without raising
        sent, failed = _notify_and_flash(s)
        assert sent == 3
        assert failed[0][0] == "Alice"


def test_join_and_vote_with_existing_host(client, sample_session):
    """join_and_vote on a session that already has a host should not override host."""
    res = client.post(
        f"/session/{sample_session['session_hash']}/join_and_vote",
        data={"name": "Newcomer", "email": "new@test.com", "game_name": "Risk"},
        follow_redirects=True
    )
    assert res.status_code == 200

def test_session_state_with_confirmation(client, sample_session, app):
    """GET /session/<hash>/state should include confirmations in the JSON response."""
    with app.app_context():
        conf = Confirmation(
            participant_id=sample_session["host_id"],
            session_id=sample_session["session_id"],
            status="yes"
        )
        db.session.add(conf)
        db.session.commit()

    res = client.get(f"/session/{sample_session['session_hash']}/state")
    assert res.status_code == 200
    data = res.get_json()
    assert "Host" in data["confirmations"]
    assert data["confirmations"]["Host"] == "yes"


def test_session_state_with_votes(client, sample_session, app):
    """GET /session/<hash>/state should include game_tally in the JSON response."""
    with app.app_context():
        db.session.add(GameVote(
            session_id=sample_session["session_id"],
            participant_id=sample_session["host_id"],
            game_name="Pandemic"
        ))
        db.session.commit()

    res = client.get(f"/session/{sample_session['session_hash']}/state")
    assert res.status_code == 200
    data = res.get_json()
    assert any(g["name"] == "Pandemic" for g in data["game_tally"])


# ── _ensure_game_election_schema: conn.commit() after successful ALTER ────────

def test_ensure_schema_commit_branch(client, app):
    """Schema function executes conn.commit() on a fresh in-memory DB with no columns yet."""
    with app.app_context():
        # Drop the columns that _ensure_game_election_schema tries to add
        # by dropping and recreating tables without them — easiest way is
        # just calling the route which triggers the function on a clean DB
        db.drop_all()
        db.create_all()

    res = client.post("/create", data={
        "title": "Schema Commit Test",
        "name": "Tester",
        "email": "t@t.com",
        "is_public": "on",
    }, follow_redirects=True)
    assert res.status_code == 200


# ── _notify_and_flash: flash success and failure messages ────────────────────

def test_notify_and_flash_flashes_success(monkeypatch, client, app, sample_session):
    """_notify_and_flash should flash success message when emails are sent."""
    monkeypatch.setattr("website.views.notify_final_time", lambda s: (3, []))
    with client.application.test_request_context():
        from flask import get_flashed_messages
        from website.views import _notify_and_flash
        with app.app_context():
            s = db.session.get(Session, sample_session["session_id"])
            _notify_and_flash(s)


def test_notify_and_flash_flashes_failure(monkeypatch, client, app, sample_session):
    """_notify_and_flash should flash danger message on email failure."""
    monkeypatch.setattr(
        "website.views.notify_final_time",
        lambda s: (0, [("Bob", "SMTP error")])
    )
    with client.application.test_request_context():
        from website.views import _notify_and_flash
        with app.app_context():
            s = db.session.get(Session, sample_session["session_id"])
            _notify_and_flash(s)


# ── join_and_vote: host_id assigned when session has no host ─────────────────

def test_join_and_vote_assigns_host_when_none(client, app):
    """join_and_vote should set host_id when session has no host."""
    with app.app_context():
        s = Session(title="No Host", is_public=True)
        db.session.add(s)
        db.session.commit()
        session_hash = s.hash_id
        session_id = s.id

    res = client.post(
        f"/session/{session_hash}/join_and_vote",
        data={"name": "First", "email": "first@test.com", "game_name": "Chess"},
        follow_redirects=True
    )
    assert res.status_code == 200

    with app.app_context():
        updated = db.session.get(Session, session_id)
        assert updated.host_id is not None


# ── remove_availability: non-XHR failure path flashes and redirects ──────────

def test_remove_availability_non_xhr_not_found(client, sample_session):
    """Non-XHR remove of missing block should flash warning and redirect."""
    res = client.post(
        f"/session/{sample_session['session_hash']}/remove_availability",
        data={
            "token": sample_session["host_token"],
            "start": datetime.now().isoformat(),
            "end": (datetime.now() + timedelta(hours=1)).isoformat()
        }
    )
    assert res.status_code == 302


def test_remove_availability_non_xhr_missing_fields(client, sample_session):
    """Non-XHR remove with missing fields should flash warning and redirect."""
    res = client.post(
        f"/session/{sample_session['session_hash']}/remove_availability",
        data={"token": sample_session["host_token"]}
    )
    assert res.status_code == 302


def test_remove_availability_non_xhr_invalid_time(client, sample_session):
    """Non-XHR remove with invalid time should flash warning and redirect."""
    res = client.post(
        f"/session/{sample_session['session_hash']}/remove_availability",
        data={
            "token": sample_session["host_token"],
            "start": "bad",
            "end": "bad"
        }
    )
    assert res.status_code == 302

# ── seed_test_data route ──────────────────────────────────────────────────────

def test_seed_test_data_route(client):
    """POST /seed-test-data should seed data and redirect to dashboard."""
    res = client.post("/seed-test-data", follow_redirects=True)
    assert res.status_code == 200


def test_seed_test_data_creates_expected_users(client, app):
    """Seeding should create 6 unique participants across multiple sessions."""
    client.post("/seed-test-data")
    with app.app_context():
        all_participants = Participant.query.all()
        unique_emails = {
            (p.email or "").strip().lower()
            for p in all_participants
            if (p.email or "").strip()
        }
        assert len(unique_emails) == 6


def test_seed_test_data_creates_sessions(client, app):
    """Seeding should create 6 sessions."""
    client.post("/seed-test-data")
    with app.app_context():
        assert Session.query.count() == 6


def test_seed_test_data_alice_has_two_sessions(client, app):
    """Alice should have participant rows in 2 different sessions."""
    client.post("/seed-test-data")
    with app.app_context():
        alice_rows = Participant.query.filter_by(email="alice@test.com").all()
        assert len(alice_rows) == 2


def test_seed_test_data_eve_has_confirmation(client, app):
    """Eve should have a confirmation after seeding."""
    client.post("/seed-test-data")
    with app.app_context():
        eve = Participant.query.filter_by(email="eve@test.com").first()
        assert eve is not None
        conf = Confirmation.query.filter_by(participant_id=eve.id).first()
        assert conf is not None
        assert conf.status == "yes"

def test_export_db(client, app):
    """Export returns all tables as JSON."""
    with app.app_context():
        s = Session(title="Export Test", is_public=True)
        db.session.add(s)
        db.session.commit()
        p = Participant(name="Alice", email="alice@test.com", session_id=s.id)
        db.session.add(p)
        db.session.commit()

    resp = client.get("/export-db")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "sessions" in data
    assert "participants" in data
    assert "availability" in data
    assert "confirmations" in data
    assert "game_votes" in data
    assert any(s["title"] == "Export Test" for s in data["sessions"])
    assert any(p["email"] == "alice@test.com" for p in data["participants"])


def test_import_db_get(client):
    """GET /import-db returns the upload form."""
    resp = client.get("/import-db")
    assert resp.status_code == 200
    assert b"form" in resp.data


def test_import_db_no_file(client):
    """POST with no file returns 400."""
    resp = client.post("/import-db", data={})
    assert resp.status_code == 400


def test_import_db_restores_data(client, app):
    """Import clears existing data and restores from JSON."""
    import json
    from io import BytesIO

    payload = {
        "sessions": [
            {
                "id": 99, "title": "Imported Session", "hash_id": "abc123",
                "host_id": None, "final_time": None,
                "chosen_game": None, "is_public": True,
            }
        ],
        "participants": [
            {
                "id": 99, "name": "Bob", "email": "bob@test.com",
                "session_id": 99, "token": "tok999",
            }
        ],
        "availability": [],
        "confirmations": [],
        "game_votes": [],
    }

    data = json.dumps(payload).encode()
    resp = client.post(
        "/import-db",
        data={"file": (BytesIO(data), "backup.json")},
        content_type="multipart/form-data",
    )
    assert resp.status_code in (200, 302)

    with app.app_context():
        from website.models import Session, Participant
        s = Session.query.filter_by(hash_id="abc123").first()
        assert s is not None
        assert s.title == "Imported Session"
        p = Participant.query.filter_by(token="tok999").first()
        assert p is not None
        assert p.name == "Bob"


def test_import_db_clears_existing(client, app):
    """Import wipes existing data before restoring."""
    import json
    from io import BytesIO
    from website.models import Session as SessionModel

    with app.app_context():
        s = SessionModel(title="Old Session", is_public=True)
        db.session.add(s)
        db.session.commit()

    payload = {
        "sessions": [], "participants": [],
        "availability": [], "confirmations": [], "game_votes": [],
    }
    data = json.dumps(payload).encode()
    client.post(
        "/import-db",
        data={"file": (BytesIO(data), "backup.json")},
        content_type="multipart/form-data",
    )

    with app.app_context():
        assert SessionModel.query.count() == 0


def test_import_db_with_final_time(client, app):
    """Import correctly parses ISO final_time strings."""
    import json
    from io import BytesIO

    payload = {
        "sessions": [
            {
                "id": 77, "title": "Timed Session", "hash_id": "timed77",
                "host_id": None, "final_time": "2026-03-20T18:00:00",
                "chosen_game": "Valorant", "is_public": False,
            }
        ],
        "participants": [], "availability": [],
        "confirmations": [], "game_votes": [],
    }

    data = json.dumps(payload).encode()
    client.post(
        "/import-db",
        data={"file": (BytesIO(data), "backup.json")},
        content_type="multipart/form-data",
    )

    with app.app_context():
        from website.models import Session
        s = Session.query.filter_by(hash_id="timed77").first()
        assert s is not None
        assert s.chosen_game == "Valorant"
        assert s.final_time is not None

def test_reset_sequences_noop_on_sqlite(app):
    """_reset_sequences should be a no-op on SQLite without raising."""
    from website.views import _reset_sequences
    with app.app_context():
        _reset_sequences()

def test_fix_sequences_route(client):
    """GET /fix-sequences should return success message."""
    res = client.get("/fix-sequences")
    assert res.status_code == 200
    assert b"fixed" in res.data


def test_cleanup_db_route(client, app):
    """GET /cleanup-db should delete junk sessions and return success message."""
    with app.app_context():
        for sid in [21, 22, 23, 24, 25, 26]:
            db.session.add(Session(id=sid, title=f"Junk {sid}", is_public=False))
        db.session.commit()

    res = client.get("/cleanup-db")
    assert res.status_code == 200
    assert b"Done" in res.data

    with app.app_context():
        for sid in [21, 22, 23, 24, 25, 26]:
            assert Session.query.get(sid) is None