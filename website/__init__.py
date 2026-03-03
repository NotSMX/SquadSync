"""
This module initializes the Flask application and registers the main blueprint.
"""
import os
from flask import Flask, app
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_mail import Mail
from dotenv import load_dotenv
load_dotenv()

db = SQLAlchemy()
login_manager = LoginManager()
mail = Mail()

def create_app():
    app = Flask(__name__)

    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL").replace("postgres://", "postgresql://")
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    app.config.update(
        MAIL_SERVER='smtp.gmail.com',
        MAIL_PORT=587,
        MAIL_USE_TLS=True,
        MAIL_USERNAME=os.environ.get("EMAIL_USER"),
        MAIL_PASSWORD=os.environ.get("EMAIL_PASSWORD"),
        MAIL_DEFAULT_SENDER='no-reply@example.com'
    )

    mail.init_app(app)

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "main.login"

    from website.models import User

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    from website.views import main
    app.register_blueprint(main)

    with app.app_context():
        db.create_all()

    return app