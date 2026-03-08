"""
test_utils.py

Unit tests for website/utils.py
"""

# pylint: disable=redefined-outer-name
# pylint: disable=too-few-public-methods

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
