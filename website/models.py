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
    host = db.relationship('Participant', foreign_keys=[host_id])
    participants = db.relationship(
        'Participant', backref='session',
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
        db.Integer, db.ForeignKey('session.id'), nullable=False
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
