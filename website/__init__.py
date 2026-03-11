"""
This module initializes the Flask application and registers the main blueprint.
"""
import os

from flask import Flask
from flask_login import LoginManager
from flask_mail import Mail
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv

load_dotenv()

db = SQLAlchemy()
login_manager = LoginManager()
mail = Mail()


def create_app():
    """Factory function to create and configure the Flask app."""
    app = Flask(__name__)

    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "DATABASE_URL", "sqlite:///dev.db"
    ).replace("postgres://", "postgresql://")
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["RAWG_API_KEY"] = os.environ.get("RAWG_API_KEY", "")

    # SSE: disable connection pooling timeout issues under high thread counts.
    # pool_size=0 → NullPool when using SQLite; for Postgres keep default but
    # bump pool_size to match your --threads count.
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,
    }

    email_user = os.environ.get("EMAIL_USER")
    app.config.update(
        MAIL_SERVER="smtp.gmail.com",
        MAIL_PORT=587,
        MAIL_USE_TLS=True,
        MAIL_USE_SSL=False,
        MAIL_USERNAME=email_user,
        MAIL_PASSWORD=os.environ.get("EMAIL_PASSWORD"),
        MAIL_DEFAULT_SENDER=(email_user or "no-reply@example.com"),
    )

    mail.init_app(app)
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "main.login"

    from website.models import User  # pylint: disable=import-outside-toplevel
    from website.views import main   # pylint: disable=import-outside-toplevel

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    app.register_blueprint(main)

    with app.app_context():
        db.create_all()

    return app
