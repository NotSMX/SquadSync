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

def notify_feedback_submitted(feedback_data):
    """Email the feedback responses to the app's own email address."""
    app_email = current_app.config.get("MAIL_USERNAME")
    
    if not (app_email and current_app.config.get("MAIL_PASSWORD")):
        return False, "Mail not configured"

    body = (
        "New Feedback Received for SynQ:\n\n"
        f"1. How easy was it to use the app? (1-5): {feedback_data.get('ease_of_use')}\n\n"
        f"2. What is one thing you would change about SynQ to make it better?:\n{feedback_data.get('improvement')}\n\n"
        f"3. Were you able to accomplish what you came to do today?: {feedback_data.get('accomplished_goal')}\n\n"
        f"4. How likely are you to return to SynQ in the future? (1-5): {feedback_data.get('return_likelihood')}\n\n"
        f"5. How likely are you to recommend this app to a friend? (1-5): {feedback_data.get('recommend_likelihood')}\n"
        f"6. Anything else you would like to add?:\n{feedback_data.get('additional_comments')}\n"
    )
    

    msg = Message(
        subject="SynQ - New User Feedback",
        recipients=[app_email], 
        body=body
    )
    
    try:
        mail.send(msg)
        return True, None
    except Exception as e: 
        return False, str(e)