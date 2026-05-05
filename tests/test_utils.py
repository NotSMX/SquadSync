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
            self.name = name
            self.email = email
            self.token = token

        def __repr__(self):
            return f"FakeParticipant({self.name})"

    class FakeSession:
        """Minimal session stub."""

        def __init__(self):
            self.id = 1
            self.hash_id = "testhash123"
            self.title = "Test Session"
            self.final_time = datetime.now(timezone.utc) + timedelta(days=1)
            self.participants = [
                FakeParticipant("Alice", "alice@test.com", "token1"),
                FakeParticipant("Bob", "bob@test.com", "token2"),
            ]

        def __repr__(self):
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
            self.hash_id = "testhash123"
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


def test_notify_feedback_no_credentials(flask_app):
    """Should return False if MAIL_USERNAME/PASSWORD not configured."""
    from website.utils import notify_feedback_submitted
    flask_app.config.update({"MAIL_USERNAME": None, "MAIL_PASSWORD": None})
    with flask_app.app_context():
        success, error = notify_feedback_submitted({})
        assert success is False
        assert error == "Mail not configured"

def test_notify_feedback_sends_email(monkeypatch):
    """Should attempt to send the feedback email."""
    from website.utils import notify_feedback_submitted
    flask_app = _make_app_with_mail()
    
    sent = []
    monkeypatch.setattr("website.utils.mail.send", lambda msg: sent.append(msg))
    
    feedback_data = {
        "ease_of_use": "5",
        "improvement": "Dark mode",
        "accomplished_goal": "Yes",
        "return_likelihood": "4",
        "recommend_likelihood": "5",
        "additional_comments": "Nothing else!"
    }
    
    with flask_app.app_context():
        success, error = notify_feedback_submitted(feedback_data)
        
    assert success is True
    assert error is None
    assert len(sent) == 1
    assert "SynQ - New User Feedback" in sent[0].subject
    assert "Dark mode" in sent[0].body

def test_notify_feedback_handles_error(monkeypatch):
    """Should record failures when mail.send raises an exception."""
    from website.utils import notify_feedback_submitted
    flask_app = _make_app_with_mail()
    
    def mock_send_fail(msg):
        raise RuntimeError("SMTP feedback error")
        
    monkeypatch.setattr("website.utils.mail.send", mock_send_fail)
    
    with flask_app.app_context():
        success, error = notify_feedback_submitted({})
        
    assert success is False
    assert error == "SMTP feedback error"

# ---------------------------------------------------------------------------
# notify_personal_link
# ---------------------------------------------------------------------------
 
def _make_participant(name="Alice", email="alice@test.com", token="tok123"):
    class P:
        pass
    p = P()
    p.name, p.email, p.token = name, email, token
    return p
 
 
def _make_session_stub(title="Sprint Review", hash_id="hashxyz"):
    class S:
        pass
    s = S()
    s.title, s.hash_id = title, hash_id
    return s
 
 
def test_personal_link_success(monkeypatch):
    """Returns (True, None) and calls mail.send on the happy path."""
    from website.utils import notify_personal_link
 
    flask_app = _make_app_with_mail()
    sent = []
    monkeypatch.setattr("website.utils.mail.send", lambda msg: sent.append(msg))
 
    success, err = notify_personal_link(flask_app, _make_participant(), _make_session_stub())
 
    assert success is True
    assert err is None
    assert len(sent) == 1
 
 
def test_personal_link_no_mail_username(monkeypatch):
    """Returns (False, None) early when MAIL_USERNAME is missing."""
    from website.utils import notify_personal_link
 
    flask_app = _make_app_with_mail()
    flask_app.config["MAIL_USERNAME"] = None
 
    success, err = notify_personal_link(flask_app, _make_participant(), _make_session_stub())
 
    assert success is False
    assert err is None
 
 
def test_personal_link_no_mail_password(monkeypatch):
    """Returns (False, None) early when MAIL_PASSWORD is missing."""
    from website.utils import notify_personal_link
 
    flask_app = _make_app_with_mail()
    flask_app.config["MAIL_PASSWORD"] = ""
 
    success, err = notify_personal_link(flask_app, _make_participant(), _make_session_stub())
 
    assert success is False
    assert err is None
 
 
def test_personal_link_empty_email():
    """Returns (False, None) when participant email is an empty string."""
    from website.utils import notify_personal_link
 
    flask_app = _make_app_with_mail()
    p = _make_participant(email="")
 
    success, err = notify_personal_link(flask_app, p, _make_session_stub())
 
    assert success is False
    assert err is None
 
 
def test_personal_link_whitespace_email():
    """Returns (False, None) when participant email is only whitespace."""
    from website.utils import notify_personal_link
 
    flask_app = _make_app_with_mail()
    p = _make_participant(email="   ")
 
    success, err = notify_personal_link(flask_app, p, _make_session_stub())
 
    assert success is False
    assert err is None
 
 
def test_personal_link_none_email():
    """Returns (False, None) when participant email is None."""
    from website.utils import notify_personal_link
 
    flask_app = _make_app_with_mail()
    p = _make_participant(email=None)
 
    success, err = notify_personal_link(flask_app, p, _make_session_stub())
 
    assert success is False
    assert err is None
 
 
def test_personal_link_smtp_exception(monkeypatch):
    """Returns (False, error_string) when mail.send raises."""
    from website.utils import notify_personal_link
 
    flask_app = _make_app_with_mail()
    monkeypatch.setattr(
        "website.utils.mail.send",
        lambda msg: (_ for _ in ()).throw(RuntimeError("SMTP timeout")),
    )
 
    success, err = notify_personal_link(flask_app, _make_participant(), _make_session_stub())
 
    assert success is False
    assert "SMTP timeout" in err
 
 
def test_personal_link_recipient_stripped(monkeypatch):
    """Recipient in the sent message has surrounding whitespace removed."""
    from website.utils import notify_personal_link
 
    flask_app = _make_app_with_mail()
    sent = []
    monkeypatch.setattr("website.utils.mail.send", lambda msg: sent.append(msg))
 
    p = _make_participant(email="  carol@test.com  ")
    notify_personal_link(flask_app, p, _make_session_stub())
 
    assert sent[0].recipients == ["carol@test.com"]
 
 
def test_personal_link_subject_contains_session_title(monkeypatch):
    """Email subject references the session title."""
    from website.utils import notify_personal_link
 
    flask_app = _make_app_with_mail()
    sent = []
    monkeypatch.setattr("website.utils.mail.send", lambda msg: sent.append(msg))
 
    notify_personal_link(flask_app, _make_participant(), _make_session_stub(title="Q3 Retro"))
 
    assert "Q3 Retro" in sent[0].subject
 
 
def test_personal_link_body_contains_name_and_url(monkeypatch):
    """Email body greets the participant by name and includes their personal URL."""
    from website.utils import notify_personal_link
 
    flask_app = _make_app_with_mail()
    sent = []
    monkeypatch.setattr("website.utils.mail.send", lambda msg: sent.append(msg))
 
    notify_personal_link(
        flask_app,
        _make_participant(name="Dana", token="mytoken"),
        _make_session_stub(hash_id="hashxyz"),
    )
 
    body = sent[0].body
    assert "Dana" in body
    assert "mytoken" in body or "hashxyz" in body   # URL contains one or both
 