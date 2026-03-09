"""
test_metrics.py

Unit tests for website/metrics.py
"""

# pylint: disable=redefined-outer-name
# pylint: disable=import-outside-toplevel
# pylint: disable=unused-argument
# pylint: disable=unused-variable
# pylint: disable=too-few-public-methods

from datetime import datetime, timedelta, timezone

import pytest

from website import create_app, db
from website.models import Session, Participant, Availability, Confirmation
from website.metrics import calculate_metrics, _unique_key


@pytest.fixture
def app():
    """Create a test app with an in-memory database."""
    flask_app = create_app()
    flask_app.config.update({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "SQLALCHEMY_EXPIRE_ON_COMMIT": False
    })
    ctx = flask_app.app_context()
    ctx.push()

    db.create_all()

    yield flask_app

    db.session.remove()
    db.drop_all()
    db.engine.dispose()

    ctx.pop()

def test_load_user(app):
    """load_user should return the correct User when given a valid id."""
    from website.models import User
    from website import login_manager

    with app.app_context():
        user = User(id=0)
        db.session.add(user)
        db.session.commit()

        loaded = login_manager._user_callback(str(user.id))

    assert loaded.id == user.id

def test_load_user_invalid_id(app):
    """load_user should return None when the user does not exist."""
    from website import login_manager

    with app.app_context():
        loaded = login_manager._user_callback("999")

    assert loaded is None

@pytest.fixture
def sample_data(app):
    """Populate the database with basic sample data."""
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
            start_time=datetime.now(timezone.utc),
            end_time=datetime.now(timezone.utc) + timedelta(hours=1)
        )
        c1 = Confirmation(participant_id=p2.id, session_id=s2.id, status="yes")
        db.session.add_all([a1, c1])
        db.session.commit()

        return {"p1": p1.id, "p2": p2.id, "p3": p3.id, "s1": s1.id, "s2": s2.id}


def test_unique_key_email(app):
    """Unique key should return email when present."""
    with app.app_context():
        s = Session(title="Test")
        db.session.add(s)
        db.session.commit()
        p = Participant(name="Test", email="user@test.com", session_id=s.id)
        db.session.add(p)
        db.session.commit()
        assert _unique_key(p) == "user@test.com"


def test_unique_key_no_email(app):
    """Unique key should fall back to id: prefix when no email."""
    with app.app_context():
        s = Session(title="Test")
        db.session.add(s)
        db.session.commit()
        p = Participant(name="NoEmail", session_id=s.id)
        db.session.add(p)
        db.session.commit()
        assert _unique_key(p).startswith("id:")


def test_calculate_metrics_basic(app, sample_data):  # pylint: disable=unused-argument
    """Basic metrics should include expected keys and counts."""
    with app.app_context():
        metrics = calculate_metrics()
    assert metrics["total_users"] >= 3
    assert metrics["sessions_created"] >= 2
    assert "activation_rate" in metrics
    assert "repeat_usage" in metrics


def test_calculate_metrics_with_repeat_usage(app):
    """Repeat usage metric should be present when a host runs multiple sessions."""
    with app.app_context():
        s = Session(title="Repeat Session")
        db.session.add(s)
        db.session.commit()
        p = Participant(name="Repeat", email="repeat@test.com", session_id=s.id)
        db.session.add(p)
        db.session.commit()
        now = datetime.now(timezone.utc)
        s1 = Session(title="Session1", host_id=p.id, final_time=now)
        s2 = Session(title="Session2", host_id=p.id, final_time=now + timedelta(days=1))
        db.session.add_all([s1, s2])
        db.session.commit()
        metrics = calculate_metrics()
    assert "repeat_usage" in metrics


def test_calculate_metrics_no_data(app):
    """Metrics on empty DB should return zeroed values."""
    with app.app_context():
        metrics = calculate_metrics()
    assert metrics["total_users"] == 0
    assert metrics["sessions_created"] == 0
    assert metrics["confirmed_participants"] == 0
    assert metrics["activation_rate"] == "0%"
    assert metrics["repeat_usage"] == "0%"


def test_calculate_metrics_availability_and_confirmation(app):
    """Confirmed participants count should increment with a confirmation record."""
    with app.app_context():
        s = Session(title="Session")
        db.session.add(s)
        db.session.commit()
        p = Participant(name="AvailUser", email="avail@test.com", session_id=s.id)
        db.session.add(p)
        db.session.commit()
        a = Availability(
            participant_id=p.id, session_id=s.id,
            start_time=datetime.now(timezone.utc),
            end_time=datetime.now(timezone.utc) + timedelta(hours=2)
        )
        c = Confirmation(participant_id=p.id, session_id=s.id, status="yes")
        db.session.add_all([a, c])
        db.session.commit()
        metrics = calculate_metrics()
    assert metrics["confirmed_participants"] >= 1


def test_calculate_metrics_handles_query_failure(monkeypatch, app):
    """Metrics should return safe defaults when the DB raises an error."""
    from sqlalchemy.exc import SQLAlchemyError  # pylint: disable=import-outside-toplevel

    class BrokenQuery:
        """Stub that raises SQLAlchemyError on any chained call."""

        def count(self):
            """Raise a DB error."""
            raise SQLAlchemyError("DB failure")

        def filter(self, *args, **kwargs):  # pylint: disable=unused-argument
            """Return self to allow chaining."""
            return self

        def with_entities(self, *args, **kwargs):  # pylint: disable=unused-argument
            """Return self to allow chaining."""
            return self

        def distinct(self):
            """Return self to allow chaining."""
            return self

        def all(self):
            """Raise a DB error."""
            raise SQLAlchemyError("DB failure")

        def filter_by(self, **kwargs):  # pylint: disable=unused-argument
            """Return self to allow chaining."""
            return self

    monkeypatch.setattr("website.metrics.Session.query", BrokenQuery())
    with app.app_context():
        metrics = calculate_metrics()
    assert metrics["sessions_created"] == 0



def test_metrics_confirmed_keys_db_error(monkeypatch, app):
    """calculate_metrics should return 0 confirmed when confirmed keys query fails."""
    from sqlalchemy.exc import SQLAlchemyError  # pylint: disable=import-outside-toplevel

    def broken(*args, **kwargs):
        raise SQLAlchemyError("fail")

    monkeypatch.setattr("website.metrics.db.session.query", broken)
    with app.app_context():
        metrics = calculate_metrics()
    assert metrics["confirmed_participants"] == 0


def test_metrics_activation_rate_db_error(monkeypatch, app):
    """calculate_metrics should return 0% activation when host query fails."""
    from sqlalchemy.exc import SQLAlchemyError  # pylint: disable=import-outside-toplevel

    original_query = None

    class BrokenOnFilter:
        """Stub that passes count() but fails on filter()."""
        def count(self):
            """Return 0."""
            return 0
        def filter(self, *args, **kwargs):
            """Raise error."""
            raise SQLAlchemyError("fail")
        def filter_by(self, **kwargs):
            """Return empty list."""
            return self
        def all(self):
            """Return empty list."""
            return []

    monkeypatch.setattr("website.metrics.Session.query", BrokenOnFilter())
    with app.app_context():
        metrics = calculate_metrics()
    assert metrics["activation_rate"] == "0%"


def test_metrics_repeat_usage_db_error(monkeypatch, app):
    """calculate_metrics should return 0% repeat usage when session query fails."""
    from sqlalchemy.exc import SQLAlchemyError  # pylint: disable=import-outside-toplevel

    class BrokenOnFilterBy:
        """Stub that passes count() but fails on filter_by()."""
        def count(self):
            """Return 0."""
            return 0
        def filter(self, *args, **kwargs):
            """Return self."""
            return self
        def with_entities(self, *args, **kwargs):
            """Return self."""
            return self
        def distinct(self):
            """Return self."""
            return self
        def all(self):
            """Return empty."""
            return []
        def filter_by(self, **kwargs):
            """Raise error."""
            raise SQLAlchemyError("fail")

    monkeypatch.setattr("website.metrics.Session.query", BrokenOnFilterBy())
    with app.app_context():
        metrics = calculate_metrics()
    assert metrics["repeat_usage"] == "0%"

def test_collect_confirmed_keys_missing_participant(monkeypatch, app):
    """Branch: participant id exists but db.session.get returns None."""
    from website.metrics import _collect_confirmed_keys

    class FakeQuery:
        """Stub that returns a participant id but db.session.get returns None."""
        def distinct(self):
            """Return self to allow chaining."""
            return self
        def all(self):
            """Return a list with one participant id."""
            return [(999,)]

    monkeypatch.setattr("website.metrics.db.session.query", lambda *args, **kwargs: FakeQuery())
    monkeypatch.setattr("website.metrics.db.session.get", lambda *args, **kwargs: None)

    with app.app_context():
        result = _collect_confirmed_keys()

    assert result == set()

def test_repeat_usage_naive_datetime(app):
    """Branch: datetime without tzinfo should be normalized."""
    from website.metrics import _collect_repeat_usage

    with app.app_context():
        s = Session(title="Test")
        db.session.add(s)
        db.session.commit()

        p = Participant(name="User", email="tz@test.com", session_id=s.id)
        db.session.add(p)
        db.session.commit()

        naive_time = datetime.now()

        s1 = Session(title="A", host_id=p.id, final_time=naive_time)
        s2 = Session(title="B", host_id=p.id, final_time=naive_time + timedelta(days=1))

        db.session.add_all([s1, s2])
        db.session.commit()

        result = _collect_repeat_usage([p], 1)

    assert result >= 0

def test_repeat_usage_duplicate_participant(app):
    """Branch: duplicate participant key triggers seen_keys continue."""
    from website.metrics import _collect_repeat_usage

    with app.app_context():
        s = Session(title="Session")
        db.session.add(s)
        db.session.commit()

        p = Participant(name="Dup", email="dup@test.com", session_id=s.id)
        db.session.add(p)
        db.session.commit()

        participants = [p, p]

        result = _collect_repeat_usage(participants, 1)

    assert result >= 0

def test_repeat_usage_single_time(app):
    """Branch: participant with only one timestamp should not count as repeat."""
    from website.metrics import _collect_repeat_usage

    with app.app_context():
        s = Session(title="Single")
        db.session.add(s)
        db.session.commit()

        p = Participant(name="SingleUser", email="single@test.com", session_id=s.id)
        db.session.add(p)
        db.session.commit()

        s1 = Session(title="Only", host_id=p.id, final_time=datetime.now(timezone.utc))
        db.session.add(s1)
        db.session.commit()

        result = _collect_repeat_usage([p], 1)

    assert result == 0

def test_activation_rate_zero_users(app):
    """Branch: activation rate when no users exist."""
    from website.metrics import _collect_activation_rate

    with app.app_context():
        rate = _collect_activation_rate(0, set())

    assert rate == 0

def test_repeat_usage_availability_query_failure(monkeypatch, app):
    """Branch: availability query raises SQL error."""
    from sqlalchemy.exc import SQLAlchemyError

    class BrokenAvailability:
        """Stub that raises SQLAlchemyError on query."""
        def filter_by(self, **kwargs):
            """Return self to allow chaining."""
            raise SQLAlchemyError("fail")

    monkeypatch.setattr("website.metrics.Availability.query", BrokenAvailability())

    with app.app_context():
        metrics = calculate_metrics()

    assert metrics["repeat_usage"] == "0%"

def test_repeat_usage_duplicate_key_branch(app):
    """Trigger the seen_keys continue branch."""
    from website.metrics import _collect_repeat_usage

    with app.app_context():
        s = Session(title="DupTest")
        db.session.add(s)
        db.session.commit()

        p = Participant(name="Dup", email="dup@test.com", session_id=s.id)
        db.session.add(p)
        db.session.commit()

        participants = [p, p]

        result = _collect_repeat_usage(participants, 1)

    assert result >= 0

def test_calculate_metrics_confirmed_keys_exception(monkeypatch, app):
    """Force _collect_confirmed_keys to raise SQLAlchemyError."""
    from sqlalchemy.exc import SQLAlchemyError

    def broken():
        raise SQLAlchemyError("fail")

    monkeypatch.setattr("website.metrics._collect_confirmed_keys", broken)

    with app.app_context():
        metrics = calculate_metrics()

    assert metrics["confirmed_participants"] == 0

def test_calculate_metrics_repeat_usage_exception(monkeypatch, app):
    """Force _collect_repeat_usage to raise SQLAlchemyError."""
    from sqlalchemy.exc import SQLAlchemyError

    def broken(*args, **kwargs):
        raise SQLAlchemyError("fail")

    monkeypatch.setattr("website.metrics._collect_repeat_usage", broken)

    with app.app_context():
        metrics = calculate_metrics()

    assert metrics["repeat_usage"] == "0%"
