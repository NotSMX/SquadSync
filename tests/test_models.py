"""
test_models.py

Tests for the SQLAlchemy models in website/models.py."""
from datetime import datetime, timedelta, timezone

import pytest

from sqlalchemy.exc import IntegrityError
from website import db
from website.models import User, Session, Participant, Availability, Confirmation, GameVote

def test_user_repr(app):
    """User __repr__ should include id."""

    with app.app_context():
        user = User()
        db.session.add(user)
        db.session.commit()

        assert repr(user) == f"<User {user.id}>"

def test_session_defaults(app):
    """Session should generate defaults."""

    with app.app_context():
        session = Session(title="Game Night")
        db.session.add(session)
        db.session.commit()

        assert session.hash_id is not None
        assert session.datetime is not None
        assert session.is_public is True
        assert repr(session) == "<Session Game Night>"

def test_participant_defaults(app):
    """Participant should generate token and link to session."""

    with app.app_context():
        s = Session(title="Test")
        db.session.add(s)
        db.session.commit()

        p = Participant(name="Alice", session_id=s.id, email="alice@test.com")
        db.session.add(p)
        db.session.commit()

        assert p.token is not None
        assert p.session_id == s.id
        assert repr(p) == "<Participant Alice>"

def test_availability_relationship(app):
    """Availability should attach to participant."""

    with app.app_context():
        s = Session(title="Test")
        db.session.add(s)
        db.session.commit()

        p = Participant(name="Bob", session_id=s.id)
        db.session.add(p)
        db.session.commit()

        a = Availability(
            participant_id=p.id,
            session_id=s.id,
            start_time=datetime.now(timezone.utc),
            end_time=datetime.now(timezone.utc) + timedelta(hours=1),
        )

        db.session.add(a)
        db.session.commit()

        assert len(p.availabilities) == 1
        assert "<Availability" in repr(a)

def test_confirmation_repr(app):
    """Confirmation repr should include status."""

    with app.app_context():
        s = Session(title="Test")
        db.session.add(s)
        db.session.commit()

        p = Participant(name="Chris", session_id=s.id)
        db.session.add(p)
        db.session.commit()

        c = Confirmation(participant_id=p.id, session_id=s.id, status="yes")
        db.session.add(c)
        db.session.commit()

        assert repr(c) == "<Confirmation yes>"

def test_game_vote_unique_constraint(app):
    """A participant should only vote once per session."""

    with app.app_context():
        s = Session(title="VoteSession")
        db.session.add(s)
        db.session.commit()

        p = Participant(name="Dana", session_id=s.id)
        db.session.add(p)
        db.session.commit()

        vote1 = GameVote(session_id=s.id, participant_id=p.id, game_name="Catan")
        vote2 = GameVote(session_id=s.id, participant_id=p.id, game_name="Chess")

        db.session.add(vote1)
        db.session.commit()
        assert repr(vote1) == f"<GameVote {'Catan'}>"

        db.session.add(vote2)

        with pytest.raises(IntegrityError):
            db.session.commit()

def test_session_host_relationship(app):
    """Session.host should resolve to the participant."""

    with app.app_context():
        s = Session(title="HostTest")
        db.session.add(s)
        db.session.commit()

        p = Participant(name="Host", session_id=s.id)
        db.session.add(p)
        db.session.commit()

        s.host_id = p.id
        db.session.commit()

        assert s.host.name == "Host"

def test_feedback_model_creation(app):
    """Test creating a Feedback entry and its __repr__."""
    from website.models import Feedback
    
    with app.app_context():
        fb = Feedback(
            ease_of_use=5,
            improvement="Make it load faster",
            accomplished_goal="Yes",
            return_likelihood=4,
            recommend_likelihood=5,
            additional_comments="Great job so far!"
        )
        db.session.add(fb)
        db.session.commit()

        assert fb.id is not None
        assert fb.created_at is not None
        assert fb.ease_of_use == 5
        assert repr(fb) == f"<Feedback {fb.id}>"
