"""
conftest.py

Pytest fixtures for testing the SynQ application.
"""
import pytest
from website import create_app, db


@pytest.fixture
def app():
    """Create a test app with an in-memory database."""
    flask_app = create_app()
    flask_app.config.update({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "SQLALCHEMY_EXPIRE_ON_COMMIT": False
    })

    ctx = flask_app.app_context()
    ctx.push()

    db.create_all()

    yield flask_app

    db.session.remove()
    db.drop_all()
    db.engine.dispose()

    ctx.pop()
