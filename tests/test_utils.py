"""
test_utils.py

Unit tests for website/utils.py
"""

import pytest
from types import SimpleNamespace
from datetime import datetime, timedelta
from flask import Flask
from unittest.mock import MagicMock
import website.utils as utils
import website
from website.utils import notify_final_time


@pytest.fixture
def app():
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
    # Create a fake session object with participants
    class FakeParticipant:
        def __init__(self, name, email, token):
            self.name = name
            self.email = email
            self.token = token

    class FakeSession:
        def __init__(self):
            self.id = 1
            self.title = "Test Session"
            self.final_time = datetime.utcnow() + timedelta(days=1)
            self.participants = [
                FakeParticipant("Alice", "alice@test.com", "token1"),
                FakeParticipant("Bob", "bob@test.com", "token2"),
            ]

    return FakeSession()


def test_notify_no_credentials(sample_session):
    """Should return 0, [] if MAIL_USERNAME/PASSWORD not configured"""
    app = Flask(__name__)
    app.config.update({"MAIL_USERNAME": None, "MAIL_PASSWORD": None})
    with app.app_context():
        sent_count, failed = notify_final_time(sample_session)
        assert sent_count == 0
        assert failed == []

