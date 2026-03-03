import secrets

from website import db
from flask_login import UserMixin
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash, check_password_hash
import uuid

# Note: The User model is currently commented out as user authentication is optional for the MVP. It can be re-enabled in the future if needed.
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    # username = db.Column(db.String(50), nullable=True)  # optional for MVP
    # email = db.Column(db.String(120), nullable=True)    # optional for MVP
    # password_hash = db.Column(db.String(128), nullable=True)  # optional for MVP
    # availabilities = db.relationship("Availability", backref="user", lazy=True)
    
    # def set_password(self, password):
    #     self.password_hash = generate_password_hash(password)

    # def check_password(self, password):
    #     return check_password_hash(self.password_hash, password)


class Session(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    hash_id = db.Column(db.String(32), unique=True, default=lambda: uuid.uuid4().hex)
    title = db.Column(db.String(100))
    host_id = db.Column(db.Integer, db.ForeignKey('participant.id'))
    host = db.relationship('Participant', foreign_keys=[host_id])
    participants = db.relationship('Participant', backref='session', foreign_keys='Participant.session_id')
    final_time = db.Column(db.DateTime, nullable=True)

class Participant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    session_id = db.Column(db.Integer, db.ForeignKey('session.id'), nullable=False)
    email = db.Column(db.String(120))  
    availabilities = db.relationship(
        'Availability',
        backref='participant',
        lazy=True,
        cascade="all, delete-orphan"
    )
    
    token = db.Column(
        db.String(32),
        unique=True,
        default=lambda: secrets.token_hex(16)
    )

class Availability(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    participant_id = db.Column(db.Integer, db.ForeignKey('participant.id'))
    session_id = db.Column(db.Integer, db.ForeignKey('session.id'))
    start_time = db.Column(db.DateTime)
    end_time = db.Column(db.DateTime)

class Confirmation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    participant_id = db.Column(db.Integer, db.ForeignKey('participant.id'))
    session_id = db.Column(db.Integer, db.ForeignKey('session.id'))
    status = db.Column(db.String(10))  # Yes / Maybe / No