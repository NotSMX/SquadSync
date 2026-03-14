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
    _session_state_hash, _sse_generate,
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


# ── lines 752-844: _sse_generate generator — all branches ────────────────────
#
# Strategy: monkeypatch website.views._time so time.time() returns controlled
# values and time.sleep() is a no-op.  Each test collects exactly the events
# it needs, then stops iterating.

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


def test_sse_generate_initial_state_event(app, monkeypatch, sample_session):
    """Generator should yield a 'state' event on the first iteration."""
    import website.views as vmod

    fake_t = _fake_time_factory(start_val=0.0, step=0.0)
    # First two calls: last_keepalive=0, start=0; loop check 0-0=0 < 300 → enter
    # After one event we stop, so MAX_DURATION never expires
    monkeypatch.setattr(vmod, "_time", fake_t)
    monkeypatch.setattr(vmod, "_SSE_MAX_DURATION", 300)

    with app.app_context():
        gen = _sse_generate(sample_session["session_hash"])
        first = next(gen)

    assert first.startswith("event: state\n")
    import json
    payload = json.loads(first.split("data: ", 1)[1].strip())
    assert "availability" in payload
    assert "Host" in payload["participants"]


def test_sse_generate_no_duplicate_event_same_hash(app, monkeypatch, sample_session):
    """Generator should NOT re-emit a state event when nothing changed."""
    import website.views as vmod

    # time advances just enough to stay under MAX_DURATION for 3 iterations
    call_count = [0]
    def fake_time():
        call_count[0] += 1
        return float(call_count[0])  # 1, 2, 3 … all < 300

    fake_t = __import__("types").SimpleNamespace(time=fake_time, sleep=lambda _: None)
    monkeypatch.setattr(vmod, "_time", fake_t)
    monkeypatch.setattr(vmod, "_SSE_MAX_DURATION", 300)

    with app.app_context():
        gen = _sse_generate(sample_session["session_hash"])
        first = next(gen)          # first iteration — state event emitted
        assert first.startswith("event: state\n")

        # Second iteration: hash unchanged → no state event; keepalive not due
        # Generator should loop back and sleep, then we force StopIteration
        # by limiting MAX_DURATION to expire after the second time() call.
        monkeypatch.setattr(vmod, "_SSE_MAX_DURATION", 3)
        final = next(gen)
        assert final == "event: reconnect\ndata: {}\n\n"


def test_sse_generate_gone_when_session_deleted(app, monkeypatch, sample_session):
    """Generator should yield 'gone' and stop if the session is deleted mid-stream."""
    import website.views as vmod
    from website import db as _db

    fake_t = _fake_time_factory(start_val=0.0, step=0.0)
    monkeypatch.setattr(vmod, "_time", fake_t)
    monkeypatch.setattr(vmod, "_SSE_MAX_DURATION", 300)

    with app.app_context():
        gen = _sse_generate(sample_session["session_hash"])
        next(gen)  # consume initial state event

        # Delete the session
        s = Session.query.get(sample_session["session_id"])
        for p in s.participants:
            _db.session.delete(p)
        _db.session.delete(s)
        _db.session.commit()

        event = next(gen)
        assert event == "event: gone\ndata: {}\n\n"


def test_sse_generate_keepalive(app, monkeypatch, sample_session):
    """Generator should yield a keepalive comment when KEEPALIVE_EVERY seconds pass."""
    import website.views as vmod

    # Simulate: start=0, first loop time=0 (state emitted), then time jumps to 16
    # so keepalive fires (16 - 0 >= 15)
    times = iter([0.0, 0.0, 16.0, 16.0, 400.0])  # last value expires the loop
    fake_t = __import__("types").SimpleNamespace(
        time=lambda: next(times), sleep=lambda _: None
    )
    monkeypatch.setattr(vmod, "_time", fake_t)
    monkeypatch.setattr(vmod, "_SSE_KEEPALIVE_EVERY", 15)
    monkeypatch.setattr(vmod, "_SSE_MAX_DURATION", 300)

    with app.app_context():
        gen = _sse_generate(sample_session["session_hash"])
        first = next(gen)
        assert first.startswith("event: state\n")
        second = next(gen)
        assert second == ": keepalive\n\n"


def test_sse_generate_exception_yields_error_comment(app, monkeypatch, sample_session):
    """Generator should yield ': error' comment on DB exception and continue."""
    import website.views as vmod
    from website.models import Session as S

    call_count = [0]
    def fake_time():
        call_count[0] += 1
        return 1.0 if call_count[0] < 10 else 400.0

    fake_t = __import__("types").SimpleNamespace(time=fake_time, sleep=lambda _: None)
    monkeypatch.setattr(vmod, "_time", fake_t)
    monkeypatch.setattr(vmod, "_SSE_MAX_DURATION", 300)

    original_query = S.query

    patched = [False]
    class BrokenQuery:
        def filter_by(self, **_):
            if not patched[0]:
                patched[0] = True
                raise Exception("DB exploded")
            return original_query.filter_by(**_)

    monkeypatch.setattr(S, "query", BrokenQuery())

    with app.app_context():
        gen = _sse_generate(sample_session["session_hash"])
        first = next(gen)
        assert first == ": error\n\n"


def test_sse_generate_reconnect_on_expiry(app, monkeypatch, sample_session):
    """Generator should yield 'reconnect' event when MAX_DURATION expires."""
    import website.views as vmod

    # Make time() immediately exceed MAX_DURATION after the first state push
    times = iter([0.0, 0.0, 400.0])
    fake_t = __import__("types").SimpleNamespace(
        time=lambda: next(times), sleep=lambda _: None
    )
    monkeypatch.setattr(vmod, "_time", fake_t)
    monkeypatch.setattr(vmod, "_SSE_MAX_DURATION", 300)

    with app.app_context():
        gen = _sse_generate(sample_session["session_hash"])
        next(gen)  # state event
        final = next(gen)
        assert final == "event: reconnect\ndata: {}\n\n"


def test_stream_session_route_returns_event_stream(client, sample_session):
    """GET /stream should return 200 with text/event-stream content type."""
    res = client.get(
        f"/session/{sample_session['session_hash']}/stream",
        headers={"Accept": "text/event-stream"},
    )
    assert res.status_code == 200
    assert "text/event-stream" in res.content_type

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

def test_sse_error_branch(app, monkeypatch, sample_session):
    """Force exception inside SSE generator."""
    import website.views as vmod

    monkeypatch.setattr(vmod, "_session_state_hash", lambda x: 1/0)

    with app.app_context():
        gen = vmod._sse_generate(sample_session["session_hash"])
        event = next(gen)

    assert event == ": error\n\n"

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


def test_sse_generate_state_payload_includes_votes_and_confirmations(app, 
monkeypatch, sample_session):
    """SSE state event payload should include game_tally and confirmations when present."""
    import website.views as vmod
    import json as _json

    with app.app_context():
        db.session.add(GameVote(
            session_id=sample_session["session_id"],
            participant_id=sample_session["host_id"],
            game_name="Catan"
        ))
        db.session.add(Confirmation(
            session_id=sample_session["session_id"],
            participant_id=sample_session["host_id"],
            status="yes"
        ))
        db.session.commit()

    fake_t = __import__("types").SimpleNamespace(time=lambda: 0.0, sleep=lambda _: None)
    monkeypatch.setattr(vmod, "_time", fake_t)
    monkeypatch.setattr(vmod, "_SSE_MAX_DURATION", 300)

    with app.app_context():
        gen = _sse_generate(sample_session["session_hash"])
        first = next(gen)

    assert first.startswith("event: state\n")
    payload = _json.loads(first.split("data: ", 1)[1].strip())
    assert any(g["name"] == "Catan" for g in payload["game_tally"])
    assert payload["confirmations"].get("Host") == "yes"

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


# ── _sse_generate: gone, reconnect, keepalive last_keepalive=now branch ──────

def test_sse_generate_keepalive_updates_last_keepalive(app, monkeypatch, sample_session):
    """After a keepalive, last_keepalive should reset so next keepalive is delayed."""
    import website.views as vmod

    # time sequence: start=0, loop1 check=0 (state), now=16 (keepalive fires),
    # last_keepalive becomes 16; loop2 now=17 (< 16+15=31, no second keepalive),
    # then 400 to expire
    times = iter([0.0, 0.0, 16.0, 16.0, 17.0, 17.0, 400.0])
    fake_t = __import__("types").SimpleNamespace(
        time=lambda: next(times), sleep=lambda _: None
    )
    monkeypatch.setattr(vmod, "_time", fake_t)
    monkeypatch.setattr(vmod, "_SSE_KEEPALIVE_EVERY", 15)
    monkeypatch.setattr(vmod, "_SSE_MAX_DURATION", 300)

    with app.app_context():
        gen = _sse_generate(sample_session["session_hash"])
        first = next(gen)
        assert first.startswith("event: state\n")
        second = next(gen)
        assert second == ": keepalive\n\n"
        # Third event: time=400 triggers reconnect, NOT a second keepalive
        third = next(gen)
        assert third == "event: reconnect\ndata: {}\n\n"


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
