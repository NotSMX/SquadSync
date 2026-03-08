"""
test_metrics.py

Unit tests for website/metrics.py
"""

import pytest
from datetime import datetime, timedelta

from website import create_app, db
from website.models import Session, Participant, Availability, Confirmation
from website.metrics import calculate_metrics, _unique_key

@pytest.fixture
def app():
    app = create_app()
    app.config.update({
    "TESTING": True,
    "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
    "SQLALCHEMY_EXPIRE_ON_COMMIT": False
    })

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()

@pytest.fixture
def sample_data(app):
    with app.app_context():

        s1 = Session(title="Game Night")
        s2 = Session(title="Board Games")
        db.session.add_all([s1, s2])
        db.session.commit()

        p1 = Participant(name="Alice", email="alice@test.com", session_id=s1.id)
        p2 = Participant(name="Bob", email="bob@test.com", session_id=s2.id)
        p3 = Participant(name="NoEmail", session_id=s1.id)

        db.session.add_all([p1, p2, p3])
        db.session.commit()

        s1.host_id = p1.id
        s2.host_id = p2.id
        db.session.commit()

        a1 = Availability(
            participant_id=p1.id,
            session_id=s1.id,
            start_time=datetime.utcnow(),
            end_time=datetime.utcnow() + timedelta(hours=1)
        )

        c1 = Confirmation(
            participant_id=p2.id,
            session_id=s2.id,
            status="yes"
        )

        db.session.add_all([a1, c1])
        db.session.commit()

        return {
            "p1": p1.id,
            "p2": p2.id,
            "p3": p3.id,
            "s1": s1.id,
            "s2": s2.id
        }

def test_unique_key_email(app):
    with app.app_context():
        s = Session(title="Test")
        db.session.add(s)
        db.session.commit()

        p = Participant(name="Test", email="user@test.com", session_id=s.id)
        db.session.add(p)
        db.session.commit()

        assert _unique_key(p) == "user@test.com"

def test_unique_key_no_email(app):
    with app.app_context():
        s = Session(title="Test")
        db.session.add(s)
        db.session.commit()

        p = Participant(name="NoEmail", session_id=s.id)
        db.session.add(p)
        db.session.commit()

        assert _unique_key(p).startswith("id:")

def test_calculate_metrics_basic(app, sample_data):
    with app.app_context():
        metrics = calculate_metrics()

    assert metrics["total_users"] >= 3
    assert metrics["sessions_created"] >= 2
    assert "activation_rate" in metrics
    assert "repeat_usage" in metrics

def test_calculate_metrics_with_repeat_usage(app):
    with app.app_context():

        s = Session(title="Repeat Session")
        db.session.add(s)
        db.session.commit()

        p = Participant(name="Repeat", email="repeat@test.com", session_id=s.id)
        db.session.add(p)
        db.session.commit()

        now = datetime.utcnow()

        s1 = Session(title="Session1", host_id=p.id, final_time=now)
        s2 = Session(title="Session2", host_id=p.id, final_time=now + timedelta(days=1))

        db.session.add_all([s1, s2])
        db.session.commit()

        metrics = calculate_metrics()

    assert "repeat_usage" in metrics

def test_calculate_metrics_no_data(app):
    with app.app_context():
        metrics = calculate_metrics()

    assert metrics["total_users"] == 0
    assert metrics["sessions_created"] == 0
    assert metrics["confirmed_participants"] == 0
    assert metrics["activation_rate"] == "0%"
    assert metrics["repeat_usage"] == "0%"

def test_calculate_metrics_availability_and_confirmation(app):
    with app.app_context():

        s = Session(title="Session")
        db.session.add(s)
        db.session.commit()

        p = Participant(name="AvailUser", email="avail@test.com", session_id=s.id)
        db.session.add(p)
        db.session.commit()

        a = Availability(
            participant_id=p.id,
            session_id=s.id,
            start_time=datetime.utcnow(),
            end_time=datetime.utcnow() + timedelta(hours=2)
        )

        c = Confirmation(
            participant_id=p.id,
            session_id=s.id,
            status="yes"
        )

        db.session.add_all([a, c])
        db.session.commit()

        metrics = calculate_metrics()

    assert metrics["confirmed_participants"] >= 1

def test_calculate_metrics_handles_query_failure(monkeypatch, app):

    def broken_query(*args, **kwargs):
        raise Exception("DB failure")

    monkeypatch.setattr("website.metrics.Session.query", broken_query)

    with app.app_context():
        metrics = calculate_metrics()

        assert metrics["sessions_created"] == 0
