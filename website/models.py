from website import db
from flask_login import UserMixin
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash, check_password_hash

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), nullable=True)  # optional for MVP
    email = db.Column(db.String(120), nullable=True)    # optional for MVP
    password_hash = db.Column(db.String(128), nullable=True)  # optional for MVP
    availabilities = db.relationship("Availability", backref="user", lazy=True)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Session(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    datetime = db.Column(db.DateTime, nullable=False)
    creator_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

class Availability(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    response = db.Column(db.String(10))  # yes/maybe/no
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    session_id = db.Column(db.Integer, db.ForeignKey("session.id"))
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))