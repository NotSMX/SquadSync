"""
test_utils.py

Unit tests for website/utils.py
"""

# pylint: disable=redefined-outer-name
# pylint: disable=too-few-public-methods
# pylint: disable=unused-argument

from datetime import datetime, timedelta, timezone

import pytest
from flask import Flask

from website.utils import notify_final_time


@pytest.fixture
def flask_app():
    """Create a minimal Flask app for testing utils."""
    app = Flask(__name__)
    app.config.update({
        "TESTING": True,
        "MAIL_USERNAME": "test@example.com",
        "MAIL_PASSWORD": "password"
    })
    with app.app_context():
        yield app


@pytest.fixture
def sample_session():
    """Create a fake session object with participants."""

    class FakeParticipant:
        """Minimal participant stub."""

        def __init__(self, name, email, token):
            """Initialise with name, email and token."""
            self.name = name
            self.email = email
            self.token = token

        def __repr__(self):
            """Return string representation."""
            return f"FakeParticipant({self.name})"

    class FakeSession:
        """Minimal session stub."""

        def __init__(self):
            """Initialise with default test values."""
            self.id = 1
            self.title = "Test Session"
            self.final_time = datetime.now(timezone.utc) + timedelta(days=1)
            self.participants = [
                FakeParticipant("Alice", "alice@test.com", "token1"),
                FakeParticipant("Bob", "bob@test.com", "token2"),
            ]

        def __repr__(self):
            """Return string representation."""
            return f"FakeSession({self.title})"

    return FakeSession()


def test_notify_no_credentials(sample_session):
    """Should return 0, [] if MAIL_USERNAME/PASSWORD not configured."""
    app = Flask(__name__)
    app.config.update({"MAIL_USERNAME": None, "MAIL_PASSWORD": None})
    with app.app_context():
        sent_count, failed = notify_final_time(sample_session)
        assert sent_count == 0
        assert not failed


def _make_app_with_mail():
    """Create a full app with mail configured and SERVER_NAME set."""
    from website import create_app, mail  # pylint: disable=import-outside-toplevel
    flask_app = create_app()
    flask_app.config.update({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "MAIL_USERNAME": "test@example.com",
        "MAIL_PASSWORD": "password",
        "MAIL_SERVER": "smtp.gmail.com",
        "MAIL_PORT": 587,
        "MAIL_USE_TLS": True,
        "MAIL_DEFAULT_SENDER": "test@example.com",
        "SERVER_NAME": "localhost",
    })
    mail.init_app(flask_app)
    return flask_app


def test_notify_sends_email(sample_session, monkeypatch):
    """Should attempt to send emails when credentials are configured."""
    sent = []

    def mock_send(msg):
        sent.append(msg)

    flask_app = _make_app_with_mail()
    monkeypatch.setattr("website.utils.mail.send", mock_send)
    with flask_app.app_context():
        sent_count, failed = notify_final_time(sample_session)

    assert sent_count == 2
    assert not failed


def test_notify_handles_send_failure(sample_session, monkeypatch):
    """Should record failures when mail.send raises."""
    def mock_send_fail(msg):
        raise RuntimeError("SMTP error")

    flask_app = _make_app_with_mail()
    monkeypatch.setattr("website.utils.mail.send", mock_send_fail)
    with flask_app.app_context():
        sent_count, failed = notify_final_time(sample_session)

    assert sent_count == 0
    assert len(failed) == 2


def test_notify_skips_no_email(monkeypatch):
    """Should skip participants with no email address."""
    class FakeParticipant:
        """Participant stub with no email."""
        def __init__(self):
            self.name = "NoEmail"
            self.email = None
            self.token = "tok"
        def __repr__(self):
            return "FakeParticipant(NoEmail)"

    class FakeSession:
        """Session stub with one emailless participant."""
        def __init__(self):
            self.id = 1
            self.title = "Test"
            self.final_time = datetime.now(timezone.utc)
            self.participants = [FakeParticipant()]
        def __repr__(self):
            return "FakeSession(Test)"

    flask_app = _make_app_with_mail()
    with flask_app.app_context():
        sent_count, failed = notify_final_time(FakeSession())

    assert sent_count == 0
    assert not failed
