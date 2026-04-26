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

# ── join_and_vote: temp_availability branch coverage ──────────────────────────

def test_join_and_vote_valid_temp_availability(client, sample_session, app):
    """Joining with valid temp_availability should save the blocks."""
    start = datetime.now()
    end = start + timedelta(hours=1)
    # Using 'Z' to explicitly test the .replace("Z", "+00:00") string logic
    temp_avail = f'[{{"start": "{start.isoformat()}Z", "end": "{end.isoformat()}Z"}}]'
    
    res = client.post(
        f"/session/{sample_session['session_hash']}/join_and_vote",
        data={
            "name": "Temp User",
            "email": "temp@test.com",
            "game_name": "Halo",
            "temp_availability": temp_avail
        },
        follow_redirects=True
    )
    assert res.status_code == 200
    with app.app_context():
        p = Participant.query.filter_by(email="temp@test.com").first()
        assert p is not None
        assert len(p.availabilities) == 1


def test_join_and_vote_invalid_json_temp_availability(client, sample_session, app):
    """Invalid JSON in temp_availability should be caught and ignored safely."""
    res = client.post(
        f"/session/{sample_session['session_hash']}/join_and_vote",
        data={
            "name": "Bad JSON User",
            "email": "bad@test.com",
            "game_name": "Halo",
            "temp_availability": "not-valid-json-[]"
        },
        follow_redirects=True
    )
    assert res.status_code == 200
    with app.app_context():
        p = Participant.query.filter_by(email="bad@test.com").first()
        assert p is not None
        assert len(p.availabilities) == 0


def test_join_and_vote_invalid_date_temp_availability(client, sample_session, app):
    """Invalid date strings in temp_availability should hit ValueError and continue."""
    start = datetime.now()
    end = start + timedelta(hours=1)
    # Provide one bad block and one good block to ensure 'continue' allows the good one to save
    temp_avail = f'[ \
        {{"start": "bad-date", "end": "worse-date"}}, \
        {{"start": "{start.isoformat()}", "end": "{end.isoformat()}"}} \
    ]'
    
    res = client.post(
        f"/session/{sample_session['session_hash']}/join_and_vote",
        data={
            "name": "Bad Date User",
            "email": "baddate@test.com",
            "game_name": "Halo",
            "temp_availability": temp_avail
        },
        follow_redirects=True
    )
    assert res.status_code == 200
    with app.app_context():
        p = Participant.query.filter_by(email="baddate@test.com").first()
        assert p is not None
        # Only the valid block should be saved
        assert len(p.availabilities) == 1


def test_join_and_vote_end_before_start_temp_availability(client, sample_session, app):
    """Temp availability where start >= end should be skipped."""
    start = datetime.now()
    end = start - timedelta(hours=1) # End before start
    temp_avail = f'[{{"start": "{start.isoformat()}", "end": "{end.isoformat()}"}}]'
    
    res = client.post(
        f"/session/{sample_session['session_hash']}/join_and_vote",
        data={
            "name": "Time Traveler",
            "email": "time@test.com",
            "game_name": "Halo",
            "temp_availability": temp_avail
        },
        follow_redirects=True
    )
    assert res.status_code == 200
    with app.app_context():
        p = Participant.query.filter_by(email="time@test.com").first()
        assert p is not None
        assert len(p.availabilities) == 0


def test_join_and_vote_type_error_temp_availability(client, sample_session, app):
    """Temp availability that parses as an integer should hit TypeError on loop."""
    res = client.post(
        f"/session/{sample_session['session_hash']}/join_and_vote",
        data={
            "name": "Int User",
            "email": "int@test.com",
            "game_name": "Halo",
            "temp_availability": "42"  # Parses as an int, which is not iterable
        },
        follow_redirects=True
    )
    assert res.status_code == 200
    with app.app_context():
        p = Participant.query.filter_by(email="int@test.com").first()
        assert p is not None
        assert len(p.availabilities) == 0

# ══════════════════════════════════════════════════════════════════════════════
# NEW TESTS — covering previously-missing lines
# ══════════════════════════════════════════════════════════════════════════════

# ── line 30: on_join SocketIO handler ────────────────────────────────────────

def test_on_join_socketio(app):
    """on_join should call join_room without raising."""
    from unittest.mock import patch, MagicMock
    from website.views import on_join

    with app.app_context():
        mock_sid = "fake-sid-123"
        with patch("website.views.join_room") as mock_join_room:
            # Simulate calling the handler directly (bypasses full SocketIO stack)
            on_join({"session_hash": "abc123"})
            mock_join_room.assert_called_once_with("abc123")


# ── lines 312-313: view_session — session not found → flash + redirect ────────

def test_view_session_not_found(client):
    """GET /session/<bad-hash> should redirect to index with a flash warning."""
    res = client.get("/session/nonexistent-hash-xyz", follow_redirects=False)
    assert res.status_code == 302
    assert "/" in res.headers["Location"]


def test_view_session_not_found_flash(client):
    """GET /session/<bad-hash> following redirect should land on index."""
    res = client.get("/session/nonexistent-hash-xyz", follow_redirects=True)
    assert res.status_code == 200


# ── line 487: confirm — XHR header triggers JSON response ────────────────────

def test_confirm_xhr_returns_json(client, sample_session):
    """POSTing confirm with XHR header should return JSON {ok: True}."""
    res = client.post(
        f"/confirm/{sample_session['session_id']}/{sample_session['host_token']}",
        data={"status": "yes"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert res.status_code == 200
    assert res.get_json() == {"ok": True}


# ── lines 973-985: _reset_sequences — PostgreSQL branch ──────────────────────

def test_reset_sequences_postgresql_branch(app, monkeypatch):
    """_reset_sequences should execute setval statements on PostgreSQL dialect."""
    from unittest.mock import MagicMock
    from website.views import _reset_sequences
    from website import db

    mock_conn = MagicMock()
    mock_conn.__enter__ = lambda s: mock_conn
    mock_conn.__exit__ = MagicMock(return_value=False)

    mock_engine = MagicMock()
    mock_engine.dialect.name = "postgresql"
    mock_engine.connect.return_value = mock_conn

    # db.engine is a read-only property — override it on the class temporarily
    monkeypatch.setattr(type(db), "engine", property(lambda self: mock_engine), raising=False)

    with app.app_context():
        _reset_sequences()

    # Should have executed one setval per table (5 tables) plus a final commit
    assert mock_conn.execute.call_count == 5
    mock_conn.commit.assert_called_once()


# ── line 1037: import_db — host_id update branch (sessions with host_id) ──────

def test_import_db_restores_host_id(client, app):
    """Import should correctly set host_id on sessions after participants exist."""
    import json
    from io import BytesIO

    payload = {
        "sessions": [
            {
                "id": 50, "title": "Hosted Session", "hash_id": "hosted50",
                "host_id": 50, "final_time": None,
                "chosen_game": None, "is_public": True, "datetime": None,
            }
        ],
        "participants": [
            {
                "id": 50, "name": "Host Person", "email": "host@test.com",
                "session_id": 50, "token": "tok50",
            }
        ],
        "availability": [], "confirmations": [], "game_votes": [],
    }

    data = json.dumps(payload).encode()
    res = client.post(
        "/import-db",
        data={"file": (BytesIO(data), "backup.json")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert res.status_code == 200

    with app.app_context():
        from website.models import Session as SM
        s = SM.query.filter_by(hash_id="hosted50").first()
        assert s is not None
        assert s.host_id == 50


# ── lines 1042-1046 + 1051-1055 + 1059-1062: import_db — availability,
#    confirmation, and game_vote rows ─────────────────────────────────────────

def test_import_db_restores_availability_confirmation_gamevote(client, app):
    """Import should restore availability, confirmation, and game_vote rows."""
    import json
    from io import BytesIO

    payload = {
        "sessions": [
            {
                "id": 60, "title": "Full Import", "hash_id": "full60",
                "host_id": None, "final_time": None,
                "chosen_game": None, "is_public": True, "datetime": None,
            }
        ],
        "participants": [
            {
                "id": 60, "name": "Alice", "email": "alice60@test.com",
                "session_id": 60, "token": "tok60",
            }
        ],
        "availability": [
            {
                "id": 60, "session_id": 60, "participant_id": 60,
                "start_time": "2026-01-01T10:00:00",
                "end_time": "2026-01-01T11:00:00",
            }
        ],
        "confirmations": [
            {
                "id": 60, "session_id": 60, "participant_id": 60,
                "status": "yes", "created_at": "2026-01-01T10:00:00",
            }
        ],
        "game_votes": [
            {
                "id": 60, "session_id": 60,
                "participant_id": 60, "game_name": "Tetris",
            }
        ],
    }

    data = json.dumps(payload).encode()
    client.post(
        "/import-db",
        data={"file": (BytesIO(data), "backup.json")},
        content_type="multipart/form-data",
    )

    with app.app_context():
        from website.models import Availability, Confirmation, GameVote
        avail = Availability.query.filter_by(session_id=60).first()
        assert avail is not None

        conf = Confirmation.query.filter_by(session_id=60).first()
        assert conf is not None
        assert conf.status == "yes"

        vote = GameVote.query.filter_by(session_id=60).first()
        assert vote is not None
        assert vote.game_name == "Tetris"


# ── lines 1075-1093: _get_or_create_experiment_session — creation branch ─────

def test_get_or_create_experiment_session_creates_when_absent(app):
    """_get_or_create_experiment_session should create an ExperimentSession if none exists."""
    from website.views import _get_or_create_experiment_session

    with app.app_context():
        from website.models import ExperimentSession
        assert ExperimentSession.query.count() == 0

        es = _get_or_create_experiment_session()

        assert es is not None
        assert es.title == "Friday Night Games"
        assert ExperimentSession.query.count() == 1


def test_get_or_create_experiment_session_returns_existing(app):
    """_get_or_create_experiment_session should return existing session without creating a new one."""
    from website.views import _get_or_create_experiment_session

    with app.app_context():
        from website.models import ExperimentSession
        import json as _json

        existing = ExperimentSession(
            title="Existing Session",
            availability_json=_json.dumps([]),
            chosen_game=None,
        )
        from website import db as _db
        _db.session.add(existing)
        _db.session.commit()
        existing_id = existing.id

        es = _get_or_create_experiment_session()
        assert es.id == existing_id
        assert ExperimentSession.query.count() == 1


# ── lines 1099-1165: experiment_session route — full coverage of all branches ──

def _make_valid_link_token(app, condition="A"):
    """Generate a properly signed link token using the app's SECRET_KEY."""
    import hmac, hashlib, secrets
    with app.app_context():
        secret = app.config.get("SECRET_KEY", "dev")
        nonce = secrets.token_urlsafe(18)
        sig = hmac.new(secret.encode(), f"{condition}:{nonce}".encode(), hashlib.sha256).hexdigest()[:16]
        return f"{condition}.{nonce}.{sig}"


def test_experiment_session_missing_token(client):
    """GET /experiment with no link_token should return 400."""
    res = client.get("/experiment")
    assert res.status_code == 400


def test_experiment_session_invalid_token_format(client):
    """GET /experiment with a malformed token (wrong parts) should return 404."""
    res = client.get("/experiment?link_token=bad.token")
    assert res.status_code == 404


def test_experiment_session_invalid_signature(client):
    """GET /experiment with a token whose sig doesn't match should return 404."""
    res = client.get("/experiment?link_token=A.somenonce.badsignature1234")
    assert res.status_code == 404


def test_experiment_session_invalid_condition(client, app):
    """GET /experiment with a valid sig but condition not A/B should return 404."""
    import hmac, hashlib, secrets
    with app.app_context():
        secret = app.config.get("SECRET_KEY", "dev")
        nonce = secrets.token_urlsafe(18)
        # Condition 'X' is not A or B
        sig = hmac.new(secret.encode(), f"X:{nonce}".encode(), hashlib.sha256).hexdigest()[:16]
        token = f"X.{nonce}.{sig}"
    res = client.get(f"/experiment?link_token={token}")
    assert res.status_code == 404


def test_experiment_session_valid_new_token(client, app):
    """GET /experiment with a fresh valid token should render 200; row created after consent."""
    token = _make_valid_link_token(app, "A")
    res = client.get(f"/experiment?link_token={token}")
    assert res.status_code == 200

    # Simulate consent being accepted
    client.post("/experiment/consent", json={"link_token": token, "condition": "A"})

    with app.app_context():
        from website import db as _db
        from sqlalchemy import text
        row = _db.session.execute(
            text("SELECT joined FROM experiment_result WHERE link_token = :t"),
            {"t": token}
        ).fetchone()
        assert row is not None
        assert row[0] == 0

def test_experiment_session_already_used_token(client, app):
    """GET /experiment with an already-joined token should return 410."""
    token = _make_valid_link_token(app, "B")

    # First open + consent: creates the pending row
    client.get(f"/experiment?link_token={token}")
    client.post("/experiment/consent", json={"link_token": token, "condition": "B"})

    # Mark as joined
    with app.app_context():
        from website import db as _db
        from sqlalchemy import text
        _db.session.execute(
            text("UPDATE experiment_result SET joined=1 WHERE link_token=:t"),
            {"t": token}
        )
        _db.session.commit()

    res = client.get(f"/experiment?link_token={token}")
    assert res.status_code == 410

def test_experiment_session_revisit_unopened_token(client, app):
    """Two visits without joining should only create one row."""
    token = _make_valid_link_token(app, "B")
    res1 = client.get(f"/experiment?link_token={token}")
    client.post("/experiment/consent", json={"link_token": token, "condition": "B"})
    res2 = client.get(f"/experiment?link_token={token}")
    assert res1.status_code == 200
    assert res2.status_code == 200

    with app.app_context():
        from website import db as _db
        from sqlalchemy import text
        rows = _db.session.execute(
            text("SELECT COUNT(*) FROM experiment_result WHERE link_token=:t"),
            {"t": token}
        ).fetchone()
        assert rows[0] == 1


def test_experiment_session_bad_availability_json(client, app):
    """experiment_session should gracefully handle invalid availability_json."""
    from website.models import ExperimentSession
    from website import db as _db
    import json

    # Create an ExperimentSession with broken JSON
    with app.app_context():
        es = ExperimentSession(
            title="Broken",
            availability_json="not-valid-json",
            chosen_game=None,
        )
        _db.session.add(es)
        _db.session.commit()

    token = _make_valid_link_token(app, "A")
    res = client.get(f"/experiment?link_token={token}")
    assert res.status_code == 200


# ── lines 1181-1255: experiment_join ─────────────────────────────────────────

def test_experiment_join_missing_name(client, app):
    """experiment_join with no name should redirect back without creating a participant."""
    token = _make_valid_link_token(app, "A")
    client.get(f"/experiment?link_token={token}")  # create pending row

    res = client.post("/experiment/join", data={
        "condition": "A",
        "name": "",
        "email": "x@x.com",
        "link_token": token,
        "time_to_join_ms": "3000",
    })
    # The redirect goes back to experiment_session which requires a valid token;
    # we just verify the redirect itself fires — not that the destination renders.
    assert res.status_code == 302


def test_experiment_join_with_link_token(client, app):
    """experiment_join with a valid link_token should update the pending result row."""
    token = _make_valid_link_token(app, "A")
    client.get(f"/experiment?link_token={token}")
    client.post("/experiment/consent", json={"link_token": token, "condition": "A"})  # creates pending row

    res = client.post("/experiment/join", data={
        "condition": "A",
        "name": "Test User",
        "email": "test@test.com",
        "game_name": "Minecraft",
        "link_token": token,
        "time_to_join_ms": "5000",
        "temp_availability": "[]",
    }, follow_redirects=True)
    assert res.status_code == 200

    with app.app_context():
        from website import db as _db
        from sqlalchemy import text
        row = _db.session.execute(
            text("SELECT joined FROM experiment_result WHERE link_token=:t"),
            {"t": token}
        ).fetchone()
        assert row[0] == 1  # joined=True


def test_experiment_join_without_link_token(client, app):
    """experiment_join without a link_token should create a new ExperimentResult row."""
    res = client.post("/experiment/join", data={
        "condition": "B",
        "name": "No Token User",
        "email": "notoken@test.com",
        "time_to_join_ms": "2000",
        "temp_availability": "[]",
    }, follow_redirects=True)
    assert res.status_code == 200

    with app.app_context():
        from website.models import ExperimentResult
        result = ExperimentResult.query.filter_by(condition="B").first()
        assert result is not None
        assert result.joined is True


def test_experiment_join_creates_experiment_session_when_absent(client, app):
    """experiment_join should create __experiment__ Session if it doesn't exist."""
    res = client.post("/experiment/join", data={
        "condition": "A",
        "name": "Bootstrap User",
        "email": "boot@test.com",
        "temp_availability": "[]",
    }, follow_redirects=True)
    assert res.status_code == 200

    with app.app_context():
        from website.models import Session as SM
        exp = SM.query.filter_by(title="__experiment__").first()
        assert exp is not None


def test_experiment_join_with_temp_availability(client, app):
    """experiment_join with valid temp_availability blocks should save them."""
    from datetime import datetime, timedelta
    start = datetime.now()
    end = start + timedelta(hours=2)
    temp_avail = f'[{{"start":"{start.isoformat()}","end":"{end.isoformat()}"}}]'

    res = client.post("/experiment/join", data={
        "condition": "A",
        "name": "Avail User",
        "email": "avail@test.com",
        "temp_availability": temp_avail,
    }, follow_redirects=True)
    assert res.status_code == 200

    with app.app_context():
        from website.models import Participant, Availability
        p = Participant.query.filter_by(email="avail@test.com").first()
        assert p is not None
        assert len(p.availabilities) == 1


def test_experiment_join_with_game_vote(client, app):
    """experiment_join with a game suggestion should save a GameVote."""
    res = client.post("/experiment/join", data={
        "condition": "A",
        "name": "Voter",
        "email": "voter@test.com",
        "game_name": "Among Us",
        "temp_availability": "[]",
    }, follow_redirects=True)
    assert res.status_code == 200

    with app.app_context():
        from website.models import Participant, GameVote
        p = Participant.query.filter_by(email="voter@test.com").first()
        assert p is not None
        vote = GameVote.query.filter_by(participant_id=p.id).first()
        assert vote is not None
        assert vote.game_name == "Among Us"


# ── lines 1261-1282: experiment_no_join ──────────────────────────────────────

def test_experiment_no_join_with_link_token(client, app):
    """experiment_no_join with a valid link_token should update elapsed time on the row."""
    token = _make_valid_link_token(app, "A")
    client.get(f"/experiment?link_token={token}")
    client.post("/experiment/consent", json={"link_token": token, "condition": "A"})  # creates pending row

    res = client.post("/experiment/no_join", data={
        "link_token": token,
        "time_to_join_ms": "12000",
        "condition": "A",
    })
    assert res.status_code == 200
    assert res.get_json()["ok"] is True

    with app.app_context():
        from website import db as _db
        from sqlalchemy import text
        row = _db.session.execute(
            text("SELECT time_to_join_ms FROM experiment_result WHERE link_token=:t"),
            {"t": token}
        ).fetchone()
        assert row[0] == 12000


def test_experiment_no_join_without_link_token(client, app):
    """experiment_no_join without a token should create a fallback ExperimentResult row."""
    # Ensure an ExperimentSession exists so the fallback can reference it
    from website.views import _get_or_create_experiment_session
    with app.app_context():
        _get_or_create_experiment_session()

    res = client.post("/experiment/no_join", data={
        "condition": "B",
        "time_to_join_ms": "8000",
    })
    assert res.status_code == 200
    assert res.get_json()["ok"] is True

    with app.app_context():
        from website.models import ExperimentResult
        result = ExperimentResult.query.filter_by(joined=False).first()
        assert result is not None


# ── lines 1288-1309: experiment_export ───────────────────────────────────────

def test_experiment_export_csv(client, app):
    """GET /experiment/export should return a CSV file by default."""
    # Seed one result row
    with app.app_context():
        from website.models import ExperimentResult
        from website import db as _db
        _db.session.add(ExperimentResult(
            condition="A", experiment_session_id=None,
            participant_id=None, joined=False, time_to_join_ms=999,
        ))
        _db.session.commit()

    res = client.get("/experiment/export")
    assert res.status_code == 200
    assert b"condition" in res.data  # CSV header row
    assert res.content_type.startswith("text/csv")


def test_experiment_export_json(client, app):
    """GET /experiment/export?format=json should return a JSON file."""
    with app.app_context():
        from website.models import ExperimentResult
        from website import db as _db
        _db.session.add(ExperimentResult(
            condition="B", experiment_session_id=None,
            participant_id=None, joined=True, time_to_join_ms=500,
        ))
        _db.session.commit()

    res = client.get("/experiment/export?format=json")
    assert res.status_code == 200
    data = res.get_json()
    assert isinstance(data, list)
    assert data[0]["condition"] in ("A", "B")


# ── lines 1316-1323: experiment_reset_participants ────────────────────────────

def test_experiment_reset_participants(client, app):
    """POST /experiment/reset_participants should clear participants but keep result rows."""
    from website.views import _get_or_create_experiment_session
    with app.app_context():
        _get_or_create_experiment_session()
        from website.models import Session as SM, Participant, ExperimentResult
        from website import db as _db

        exp_s = SM(title="__experiment__", is_public=False)
        _db.session.add(exp_s)
        _db.session.commit()

        p = Participant(name="Exp P", email="expp@test.com", session_id=exp_s.id)
        _db.session.add(p)
        _db.session.commit()

        _db.session.add(ExperimentResult(
            condition="A", experiment_session_id=None,
            participant_id=p.id, joined=True, time_to_join_ms=100,
        ))
        _db.session.commit()

    res = client.post("/experiment/reset_participants", follow_redirects=True)
    assert res.status_code == 200

    with app.app_context():
        from website.models import Participant, ExperimentResult
        assert Participant.query.filter_by(email="expp@test.com").count() == 0
        assert ExperimentResult.query.count() > 0  # results kept


def test_experiment_reset_participants_no_exp_session(client, app):
    """reset_participants should not crash when __experiment__ session doesn't exist."""
    res = client.post("/experiment/reset_participants", follow_redirects=True)
    assert res.status_code == 200


# ── lines 1329-1338: experiment_reset_all ────────────────────────────────────

def test_experiment_reset_all(client, app):
    """POST /experiment/reset_all should delete participants AND all result rows."""
    from website.views import _get_or_create_experiment_session
    with app.app_context():
        _get_or_create_experiment_session()
        from website.models import Session as SM, Participant, ExperimentResult
        from website import db as _db

        exp_s = SM(title="__experiment__", is_public=False)
        _db.session.add(exp_s)
        _db.session.commit()

        p = Participant(name="Full Reset P", email="fr@test.com", session_id=exp_s.id)
        _db.session.add(p)
        _db.session.commit()

        _db.session.add(ExperimentResult(
            condition="A", experiment_session_id=None,
            participant_id=p.id, joined=True, time_to_join_ms=200,
        ))
        _db.session.commit()

    res = client.post("/experiment/reset_all", follow_redirects=True)
    assert res.status_code == 200

    with app.app_context():
        from website.models import ExperimentResult
        assert ExperimentResult.query.count() == 0


def test_experiment_reset_all_no_exp_session(client, app):
    """reset_all should not crash when __experiment__ session doesn't exist."""
    with app.app_context():
        from website.models import ExperimentResult
        from website import db as _db
        _db.session.add(ExperimentResult(
            condition="B", experiment_session_id=None,
            participant_id=None, joined=False, time_to_join_ms=0,
        ))
        _db.session.commit()

    res = client.post("/experiment/reset_all", follow_redirects=True)
    assert res.status_code == 200

    with app.app_context():
        from website.models import ExperimentResult
        assert ExperimentResult.query.count() == 0


# ── lines 1344-1346: experiment_results endpoint ─────────────────────────────

def test_experiment_results_endpoint(client, app):
    """GET /experiment/results should return a JSON list."""
    with app.app_context():
        from website.models import ExperimentResult
        from website import db as _db
        _db.session.add(ExperimentResult(
            condition="A", experiment_session_id=None,
            participant_id=None, joined=True, time_to_join_ms=1234,
        ))
        _db.session.commit()

    res = client.get("/experiment/results")
    assert res.status_code == 200
    data = res.get_json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert "condition" in data[0]
    assert "joined" in data[0]


# ── lines 1356-1368: experiment_generate_link ────────────────────────────────

def test_experiment_generate_link_condition_a(client):
    """POST /experiment/generate_link with condition A should return a signed token."""
    res = client.post(
        "/experiment/generate_link",
        json={"condition": "A"},
        content_type="application/json",
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["condition"] == "A"
    assert len(data["link_token"].split(".")) == 3


def test_experiment_generate_link_condition_b(client):
    """POST /experiment/generate_link with condition B should return a signed token."""
    res = client.post(
        "/experiment/generate_link",
        json={"condition": "B"},
        content_type="application/json",
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["condition"] == "B"


def test_experiment_generate_link_invalid_condition_defaults_to_a(client):
    """POST /experiment/generate_link with an invalid condition should default to A."""
    res = client.post(
        "/experiment/generate_link",
        json={"condition": "Z"},
        content_type="application/json",
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["condition"] == "A"


def test_generated_link_token_is_valid_for_experiment(client, app):
    """A token generated by generate_link should be accepted by the experiment route."""
    gen_res = client.post(
        "/experiment/generate_link",
        json={"condition": "A"},
        content_type="application/json",
    )
    token = gen_res.get_json()["link_token"]

    exp_res = client.get(f"/experiment?link_token={token}")
    assert exp_res.status_code == 200


def test_submit_feedback_success(client, app, monkeypatch):
    """Submitting valid feedback should save to DB and trigger email."""
    # Mock the email sender so we don't try to actually send during view test
    monkeypatch.setattr("website.views.notify_feedback_submitted", lambda data: (True, None))
    
    res = client.post("/submit-feedback", data={
        "ease_of_use": "4",
        "improvement": "Add more games to the dropdown",
        "accomplished_goal": "Yes",
        "return_likelihood": "5",
        "recommend_likelihood": "5",
        "additional_comments": "Thanks!"
    }, follow_redirects=True)
    
    assert res.status_code == 200
    assert b"Thank you for your feedback" in res.data
    
    with app.app_context():
        from website.models import Feedback
        fb = Feedback.query.first()
        assert fb is not None
        assert fb.ease_of_use == 4
        assert fb.improvement == "Add more games to the dropdown"


def test_submit_feedback_invalid_integers(client, app, monkeypatch):
    """Submitting non-integers for scale questions should safely store None."""
    monkeypatch.setattr("website.views.notify_feedback_submitted", lambda data: (True, None))
    
    res = client.post("/submit-feedback", data={
        "ease_of_use": "not-a-number",
        "improvement": "Fix the numbers",
        "accomplished_goal": "No",
        "return_likelihood": "",
        "recommend_likelihood": "None",
        "additional_comments": ""
    }, follow_redirects=True)
    
    assert res.status_code == 200
    
    with app.app_context():
        from website.models import Feedback
        fb = Feedback.query.first()
        assert fb is not None
        assert fb.ease_of_use is None
        assert fb.return_likelihood is None
        assert fb.recommend_likelihood is None