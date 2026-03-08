"""
test_views.py

This module contains unit tests for the Flask views in the website/views.py module.
"""

import pytest
from datetime import datetime, timedelta
from website import create_app, db
from website.models import Session, Participant, Availability, Confirmation, GameVote

@pytest.fixture
def app():
    app = create_app()
    app.config.update({
    "TESTING": True,
    "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
    "SQLALCHEMY_EXPIRE_ON_COMMIT": False,
    "WTF_CSRF_ENABLED": False
    })

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()

@pytest.fixture
def client(app):
    return app.test_client()

@pytest.fixture
def sample_session(app):
    """
    Creates a session + host and returns simple values instead of ORM objects
    to avoid SQLAlchemy detached instance errors.
    """
    with app.app_context():
        s = Session(title="Test Session", is_public=True)
        db.session.add(s)
        db.session.commit()

        host = Participant(
            name="Host",
            email="host@test.com",
            session_id=s.id
        )
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
    res = client.get("/")
    assert res.status_code == 200

def test_dashboard(client, monkeypatch):
    monkeypatch.setattr(
    "website.metrics.calculate_metrics",
    lambda: {"sessions": 1}
    )

    res = client.get("/dashboard")
    assert res.status_code == 200

def test_list_sessions(client, sample_session):
    res = client.get("/sessions")
    assert res.status_code == 200

def test_create_session_get(client):
    res = client.get("/create")
    assert res.status_code == 200

def test_create_session_post(client):
    res = client.post("/create", data={
    "title": "Game Night",
    "name": "Alice",
    "email": "[alice@test.com](mailto:alice@test.com)",
    "is_public": "on"
    }, follow_redirects=True)

    assert res.status_code == 200

def test_join_session(client, sample_session):
    res = client.post(
    f"/join/{sample_session['session_id']}",
    data={
    "name": "Bob",
    "email": "[bob@test.com](mailto:bob@test.com)"
    }
    )

    assert res.status_code == 302

def test_view_session(client, sample_session):
    res = client.get(
    f"/session/{sample_session['session_hash']}?token={sample_session['host_token']}"
    )

    assert res.status_code == 200

def test_vote_game(client, sample_session):
    res = client.post(
    f"/session/{sample_session['session_hash']}/vote_game",
    data={
    "game_name": "Catan",
    "token": sample_session["host_token"]
    },
    follow_redirects=True
    )

    assert res.status_code == 200

def test_join_and_vote(client, sample_session):
    res = client.post(
    f"/session/{sample_session['session_hash']}/join_and_vote",
    data={
    "name": "Charlie",
    "email": "[c@test.com](mailto:c@test.com)",
    "game_name": "Chess"
    },
    follow_redirects=True
    )

    assert res.status_code == 200


def test_add_availability(client, sample_session):
    start = datetime.now().isoformat()
    end = (datetime.now() + timedelta(hours=1)).isoformat()

    res = client.post(
        f"/session/{sample_session['session_hash']}/add_availability",
        data={
            "token": sample_session["host_token"],
            "start": start,
            "end": end
        },
        follow_redirects=True
    )

    assert res.status_code == 200

def test_availability_page_get(client, sample_session):
    res = client.get(
    f"/availability/{sample_session['session_id']}/{sample_session['host_token']}"
    )

    assert res.status_code == 200

def test_availability_post(client, sample_session):
    data = [
    {
    "start": datetime.now().isoformat(),
    "end": (datetime.now() + timedelta(hours=1)).isoformat()
    }
    ]

    res = client.post(
        f"/availability/{sample_session['session_id']}/{sample_session['host_token']}",
        data={"availability_data": str(data).replace("'", '"')},
        follow_redirects=True
    )

    assert res.status_code == 200

def test_auto_pick(client, sample_session, monkeypatch, app):
    with app.app_context():
        a = Availability(
        session_id=sample_session["session_id"],
        participant_id=sample_session["host_id"],
        start_time=datetime.now(),
        end_time=datetime.now() + timedelta(hours=1)
        )
        db.session.add(a)
        db.session.commit()

    monkeypatch.setattr(
        "website.views.notify_final_time",
        lambda session: (0, [])
    )

    res = client.get(
        f"/auto_pick/{sample_session['session_hash']}?token={sample_session['host_token']}",
        follow_redirects=True
    )

    assert res.status_code == 200

def test_manual_pick(client, sample_session, monkeypatch):
    monkeypatch.setattr(
    "website.views.notify_final_time",
    lambda session: (0, [])
    )

    res = client.post(
        f"/manual_pick/{sample_session['session_hash']}?token={sample_session['host_token']}",
        data={"manual_time": datetime.now().isoformat()},
        follow_redirects=True
    )

    assert res.status_code == 200

def test_confirm(client, sample_session):
    res = client.post(
    f"/confirm/{sample_session['session_id']}/{sample_session['host_token']}",
    data={"status": "yes"},
    follow_redirects=True
    )

    assert res.status_code == 200

def test_set_game(client, sample_session):
    res = client.post(
    f"/session/{sample_session['session_hash']}/set_game",
    data={
    "game_name": "Mario Kart",
    "token": sample_session["host_token"]
    },
    follow_redirects=True
    )

    assert res.status_code == 200

def test_test_game_election_route(client):
    res = client.get("/test-game-election", follow_redirects=True)
    assert res.status_code == 200

def test_join_session_sets_host(client, app):
    with app.app_context():
        s = Session(title="No Host Yet", is_public=True)
        db.session.add(s)
        db.session.commit()

        session_id = s.id

    res = client.post(
        f"/join/{session_id}",
        data={"name": "First", "email": "first@test.com"}
    )

    assert res.status_code == 302

    with app.app_context():
        updated = Session.query.get(session_id)
        assert updated.host_id is not None

def test_availability_invalid_json(client, sample_session):
    res = client.post(
    f"/availability/{sample_session['session_id']}/{sample_session['host_token']}",
    data={"availability_data": "invalid_json"},
    follow_redirects=True
    )

    assert res.status_code == 200

def test_availability_invalid_block(client, sample_session):
    start = datetime.now().isoformat()

    res = client.post(
        f"/availability/{sample_session['session_id']}/{sample_session['host_token']}",
        data={
            "availability_data": f'[{{"start":"{start}","end":"{start}"}}]'
        },
        follow_redirects=True
    )

    assert res.status_code == 200

def test_auto_pick_unauthorized(client, sample_session):
    res = client.get(
    f"/auto_pick/{sample_session['session_hash']}?token=invalidtoken"
    )

    assert res.status_code == 404

def test_manual_pick_unauthorized(client, sample_session):
    res = client.post(
    f"/manual_pick/{sample_session['session_hash']}?token=invalidtoken",
    data={"manual_time": datetime.now().isoformat()}
    )

    assert res.status_code == 404

def test_confirm_update_existing(client, sample_session, app):
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
            participant_id = sample_session["host_id"],
            session_id = sample_session["session_id"]
            ).first()
        
        assert updated.status == "yes"

def test_join_and_vote_missing_name(client, sample_session):
    res = client.post(
    f"/session/{sample_session['session_hash']}/join_and_vote",
    data={"name": "", "game_name": "Catan"},
    follow_redirects=True
    )

    assert res.status_code == 200

def test_join_and_vote_missing_game(client, sample_session):
    res = client.post(
    f"/session/{sample_session['session_hash']}/join_and_vote",
    data={"name": "Player", "game_name": ""},
    follow_redirects=True
    )

    assert res.status_code == 200

def test_vote_game_empty(client, sample_session):
    res = client.post(
    f"/session/{sample_session['session_hash']}/vote_game",
    data={"game_name": "", "token": sample_session["host_token"]},
    follow_redirects=True
    )

    assert res.status_code == 200

def test_add_availability_missing_fields(client, sample_session):
    res = client.post(
    f"/session/{sample_session['session_hash']}/add_availability",
    data={"token": sample_session["host_token"]},
    follow_redirects=True
    )

    assert res.status_code == 200

def test_add_availability_invalid_time(client, sample_session):
    res = client.post(
    f"/session/{sample_session['session_hash']}/add_availability",
    data={
    "token": sample_session["host_token"],
    "start": "invalid",
    "end": "invalid"
    },
    follow_redirects=True
    )

    assert res.status_code == 200

def test_add_availability_end_before_start(client, sample_session):
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
    with app.app_context():
        p = Participant(
        name="Other",
        email="other@test.com",
        session_id=sample_session["session_id"]
        )
        db.session.add(p)
        db.session.commit()

        other_token = p.token

    res = client.post(
        f"/session/{sample_session['session_hash']}/set_game",
        data={
            "game_name": "Halo",
            "token": other_token
        },
        follow_redirects=True
    )

    assert res.status_code == 200

def test_set_game_clear(client, sample_session):
    res = client.post(
    f"/session/{sample_session['session_hash']}/set_game",
    data={"game_name": "", "token": sample_session["host_token"]},
    follow_redirects=True
    )

    assert res.status_code == 200

def test_vote_game_update_existing(client, sample_session, app):
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
        data={
            "game_name": "NewGame",
            "token": sample_session["host_token"]
        },
        follow_redirects=True
    )

    assert res.status_code == 200

def test_auto_pick_no_availability(client, sample_session, monkeypatch):
    monkeypatch.setattr(
        "website.views.notify_final_time",
        lambda session: (0, [])
    )

    res = client.get(
        f"/auto_pick/{sample_session['session_hash']}?token={sample_session['host_token']}",
        follow_redirects=True
    )

    assert res.status_code == 200

def test_manual_pick_missing_time(client, sample_session):
    res = client.post(
    f"/manual_pick/{sample_session['session_hash']}?token={sample_session['host_token']}",
    data={},
    follow_redirects=True
    )

    assert res.status_code == 400


def test_confirm_invalid_status(client, sample_session):
    res = client.post(
    f"/confirm/{sample_session['session_id']}/{sample_session['host_token']}",
    data={"status": "invalid"},
    follow_redirects=True
    )

    assert res.status_code == 200

def test_availability_empty_list(client, sample_session):
    res = client.post(
    f"/availability/{sample_session['session_id']}/{sample_session['host_token']}",
    data={"availability_data": "[]"},
    follow_redirects=True
    )

    assert res.status_code == 200

def test_join_session_missing_fields(client, sample_session):
    res = client.post(
    f"/join/{sample_session['session_id']}",
    data={"name": "", "email": ""},
    follow_redirects=True
    )

    assert res.status_code == 200

def test_view_session_invalid_token(client, sample_session):
    res = client.get(
    f"/session/{sample_session['session_hash']}?token=badtoken"
    )

    assert res.status_code in (200, 302, 404)

def test_set_game_whitespace(client, sample_session):
    res = client.post(
    f"/session/{sample_session['session_hash']}/set_game",
    data={
    "game_name": " ",
    "token": sample_session["host_token"]
    },
    follow_redirects=True
    )

    assert res.status_code == 200

def test_confirm_multiple_updates(client, sample_session, app):
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