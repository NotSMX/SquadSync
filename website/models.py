"""
models.py

SQLAlchemy models for SynQ MVP.
"""
# pylint: disable=too-few-public-methods
# pylint: disable=cyclic-import

import secrets
import uuid
from datetime import datetime, timezone

from flask_login import UserMixin

from website import db


class User(db.Model, UserMixin):
    """Placeholder user model (auth optional for MVP)."""

    id = db.Column(db.Integer, primary_key=True)

    def __repr__(self):
        """Return string representation."""
        return f"<User {self.id}>"


class Session(db.Model):
    """A game session that participants join and schedule."""

    id = db.Column(db.Integer, primary_key=True)
    hash_id = db.Column(
        db.String(32), unique=True, default=lambda: uuid.uuid4().hex
    )
    title = db.Column(db.String(100))
    datetime = db.Column(
        db.DateTime, nullable=True,
        default=lambda: datetime.now(timezone.utc)
    )
    host_id = db.Column(db.Integer, db.ForeignKey('participant.id'))
    host = db.relationship(
        'Participant',
        foreign_keys=[host_id],
        post_update=True
    )
    participants = db.relationship(
        'Participant', backref='session',
        cascade="all, delete-orphan",
        foreign_keys='Participant.session_id'
    )
    final_time = db.Column(db.DateTime, nullable=True)
    chosen_game = db.Column(db.String(120), nullable=True)
    is_public = db.Column(db.Boolean, nullable=False, default=True)

    def __repr__(self):
        """Return string representation."""
        return f"<Session {self.title}>"


class Participant(db.Model):
    """A person who has joined a session."""

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    session_id = db.Column(
        db.Integer, db.ForeignKey('session.id', ondelete="CASCADE"), nullable=False
    )
    email = db.Column(db.String(120))
    availabilities = db.relationship(
        'Availability', backref='participant',
        lazy=True, cascade="all, delete-orphan"
    )
    token = db.Column(
        db.String(32), unique=True,
        default=lambda: secrets.token_hex(16)
    )

    def __repr__(self):
        """Return string representation."""
        return f"<Participant {self.name}>"


class Availability(db.Model):
    """A time block when a participant is available."""

    id = db.Column(db.Integer, primary_key=True)
    participant_id = db.Column(db.Integer, db.ForeignKey('participant.id'))
    session_id = db.Column(db.Integer, db.ForeignKey('session.id'))
    start_time = db.Column(db.DateTime)
    end_time = db.Column(db.DateTime)

    def __repr__(self):
        """Return string representation."""
        return f"<Availability {self.start_time} - {self.end_time}>"


class Confirmation(db.Model):
    """A participant's RSVP to a finalised session time."""

    id = db.Column(db.Integer, primary_key=True)
    participant_id = db.Column(db.Integer, db.ForeignKey('participant.id'))
    session_id = db.Column(db.Integer, db.ForeignKey('session.id'))
    status = db.Column(db.String(10))

    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc)
    )
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False,
        default=lambda context: context.get_current_parameters()['created_at'],
        onupdate=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self):
        """Return string representation."""
        return f"<Confirmation {self.status}>"


class ExperimentSession(db.Model):
    """
    A controlled template session for the A/B experiment.
    Holds fake title + pre-loaded availability blocks as JSON.
    Participants who join during an experiment run are tracked separately
    and can be wiped without touching real session data.
    """

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False, default="Game Night")
    availability_json = db.Column(db.Text, nullable=False, default="[]")
    chosen_game = db.Column(db.String(120), nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self):
        return f"<ExperimentSession {self.title}>"


class ExperimentResult(db.Model):
    """One row per experiment session — records condition, timer, and join outcome."""

    id = db.Column(db.Integer, primary_key=True)
    condition = db.Column(db.String(1), nullable=False)
    experiment_session_id = db.Column(db.Integer, db.ForeignKey('experiment_session.id'), nullable=True)
    participant_id = db.Column(db.Integer, db.ForeignKey('participant.id'), nullable=True)
    joined = db.Column(db.Boolean, nullable=False, default=False)
    time_to_join_ms = db.Column(db.Integer, nullable=True)
    link_token = db.Column(db.String(64), nullable=True, unique=True)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc)
    )
    click_count = db.Column(db.Integer, default=0)
    scroll_depth = db.Column(db.Float, default=0.0)
    first_interaction_ms = db.Column(db.Integer, nullable=True)
    used_calendar = db.Column(db.Boolean, default=False)
    typed_game = db.Column(db.Boolean, default=False)

    # Extended behavioral metrics (collected by JS but previously not persisted)
    calendar_block_count = db.Column(db.Integer, default=0)
    calendar_section_ms = db.Column(db.Integer, default=0)
    game_section_ms = db.Column(db.Integer, default=0)
    time_to_calendar_ms = db.Column(db.Integer, nullable=True)
    time_to_game_ms = db.Column(db.Integer, nullable=True)
    rage_click_count = db.Column(db.Integer, default=0)
    form_focus_ms = db.Column(db.Integer, default=0)
    nudge_hover = db.Column(db.Boolean, default=False)

    # Post-experiment feedback fields
    ease_of_use = db.Column(db.Integer, nullable=True)
    layout_clarity = db.Column(db.Integer, nullable=True)
    noticed_first = db.Column(db.String(20), nullable=True)
    real_use_likelihood = db.Column(db.Integer, nullable=True)
    feedback_text = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f"<ExperimentResult condition={self.condition} joined={self.joined}>"


class GameVote(db.Model):
    """One vote per participant per session for a preferred game."""

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(
        db.Integer, db.ForeignKey('session.id'), nullable=False
    )
    participant_id = db.Column(
        db.Integer, db.ForeignKey('participant.id'), nullable=False
    )
    game_name = db.Column(db.String(120), nullable=False)
    __table_args__ = (
        db.UniqueConstraint(
            'session_id', 'participant_id',
            name='uq_game_vote_session_participant'
        ),
    )

    def __repr__(self):
        """Return string representation."""
        return f"<GameVote {self.game_name}>"
    
class Feedback(db.Model):
    """User feedback submitted via the footer form."""

    id = db.Column(db.Integer, primary_key=True)
    ease_of_use = db.Column(db.Integer)  # 1-5 scale
    improvement = db.Column(db.Text)  #Open-Ended
    accomplished_goal = db.Column(db.String(10))  # Yes/No
    return_likelihood = db.Column(db.Integer)  # 1-5 scale
    recommend_likelihood = db.Column(db.Integer)  # 1-5 scale
    additional_comments = db.Column(db.Text) #Open-Ended
    
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self):
        return f"<Feedback {self.id}>"