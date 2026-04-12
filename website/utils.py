"""
utils.py

Utility functions for SynQ — email notifications etc.
"""

from flask import url_for, current_app
from flask_mail import Message

from website import mail


def notify_final_time(session):
    """Send confirmation emails to all participants with an email address."""
    if not (
        current_app.config.get("MAIL_USERNAME")
        and current_app.config.get("MAIL_PASSWORD")
    ):
        return 0, []

    sent_count = 0
    failed = []

    for participant in session.participants:
        if not (participant.email and participant.email.strip()):
            continue
        session_url = url_for(
            "main.view_session",
            session_hash=session.hash_id,
            token=participant.token,
            _external=True,
        )
        msg = Message(
            subject=f"Confirm Final Time for {session.title}",
            recipients=[participant.email.strip()],
            body=(
                f"Hi {participant.name},\n\n"
                f"The final time for '{session.title}' has been set to "
                f"{session.final_time.strftime('%A, %B %d, %Y at %I:%M %p')}.\n"
                f"View the session here:\n{session_url}\n\nThanks!"
            ),
        )
        try:
            mail.send(msg)
            sent_count += 1
        except Exception as e:  # pylint: disable=broad-exception-caught
            failed.append((participant.name, str(e)))

    return sent_count, failed

def notify_personal_link(app, participant, session):
    """Send a personal link email to a participant when they join or create a session."""

    with app.app_context(), app.test_request_context():

        if not (
            app.config.get("MAIL_USERNAME")
            and app.config.get("MAIL_PASSWORD")
        ):
            return False, None

        if not (participant.email and participant.email.strip()):
            return False, None

        session_url = url_for(
            "main.view_session",
            session_hash=session.hash_id,
            token=participant.token,
            _external=True,
        )

        msg = Message(
            subject=f"Your personal link for {session.title}",
            recipients=[participant.email.strip()],
            body=(
                f"Hi {participant.name},\n\n"
                f"Here is your personal link for '{session.title}'.\n"
                f"{session_url}\n\nThanks!"
            ),
        )

        try:
            mail.send(msg)
            return True, None
        except Exception as e:
            return False, str(e)
