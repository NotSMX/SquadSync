from flask_mail import Message
from flask import url_for
from website import mail

def notify_final_time(session):
    sent_count = 0
    failed = []

    for participant in session.participants:
        confirm_url = url_for(
            'main.confirm',
            session_id=session.id,
            token=participant.token,
            _external=True 
        )

        msg = Message(
            subject=f"Confirm Final Time for {session.title}",
            recipients=[participant.email],
            body=f"Hi {participant.name},\n\n"
                 f"The final time for the session '{session.title}' has been set to "
                 f"{session.final_time.strftime('%A, %B %d, %Y at %I:%M %p')}.\n"
                 f"Please confirm your availability using this link:\n{confirm_url}\n\n"
                 "Thanks!"
        )
        try:
            mail.send(msg)
            sent_count += 1
        except Exception as e:
            failed.append((participant.name, str(e)))

    return sent_count, failed