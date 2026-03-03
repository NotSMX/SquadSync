"""
views.py

Routes for SynQ MVP:
Create Session → Join → Submit Availability → Auto Pick → Confirm
"""

import token

from flask import Blueprint, render_template, redirect, session, url_for, request, flash
from matplotlib.pyplot import title
from website import db
from website.models import Confirmation, Participant, Session, Availability
from datetime import datetime, timedelta, timedelta
from collections import defaultdict
import json

from website.utils import notify_final_time

main = Blueprint("main", __name__)

@main.route("/")
def index():
    return render_template("index.html")

@main.route("/create", methods=["GET", "POST"])
def create_session():
    if request.method == "POST":
        title = request.form["title"]
        host_name = request.form["name"]
        email = request.form["email"]

        # Create session
        session = Session(title=title)
        db.session.add(session)
        db.session.commit()

        # Create host participant
        host_participant = Participant(
            name=host_name,
            session_id=session.id,
            email=email
        )
        db.session.add(host_participant)
        db.session.commit()

        # Assign host
        session.host_id = host_participant.id
        db.session.commit()

        # Redirect host to availability page
        return redirect(url_for(
            "main.availability",
            session_id=session.id,
            token=host_participant.token
        ))

    return render_template("create_session.html")

@main.route("/join/<int:session_id>", methods=["POST"])
def join_session(session_id):
    name = request.form["name"]
    email = request.form["email"]

    participant = Participant(
        name=name,
        email=email,
        session_id=session_id
    )

    db.session.add(participant)
    db.session.commit()

    # If no host yet, make first participant host
    game_session = Session.query.get(session_id)
    if not game_session.host_id:
        game_session.host_id = participant.id
        db.session.commit()

    return redirect(url_for(
        "main.availability",
        session_id=session_id,
        token=participant.token
    ))

@main.route('/availability/<int:session_id>/<token>', methods=['GET', 'POST'])
def availability(session_id, token):

    participant = Participant.query.filter_by(session_id=session_id, token=token).first_or_404()

    if request.method == 'POST':
        data = json.loads(request.form['availability_data'])

        for block in data:
            start = datetime.fromisoformat(block['start'])
            end = datetime.fromisoformat(block['end'])

            new_availability = Availability(
                session_id=session_id,
                participant_id=participant.id,
                start_time=start,
                end_time=end
            )

            db.session.add(new_availability)

        db.session.commit()

        return redirect(url_for(
            'main.view_session',
            session_hash=participant.session.hash_id,
            token=participant.token
        ))

    return render_template(
        'availability.html',
        participant=participant,
        session_id=session_id,
        session_hash=participant.session.hash_id,
        token=participant.token
    )

@main.route('/session/<session_hash>')
def view_session(session_hash):
    game_session = Session.query.filter_by(hash_id=session_hash).first_or_404()
    token = request.args.get('token')
    participant = Participant.query.filter_by(token=token).first() if token else None

    is_host = participant and participant.id == game_session.host_id

    # Build grouped_availability for template display
    grouped = {}
    grouped_json = {}
    for i, p in enumerate(game_session.participants):
        grouped[p] = p.availabilities  # for name display in HTML
        grouped_json[p.name] = []
        for block in p.availabilities:
            grouped_json[p.name].append({
                "start": block.start_time.isoformat(),
                "end": block.end_time.isoformat(),
                "color_index": i
            })

    # Collect confirmation statuses
    confirmations = {}
    for p in game_session.participants:
        conf = Confirmation.query.filter_by(participant_id=p.id, session_id=game_session.id).first()
        confirmations[p.id] = conf.status if conf else None


    return render_template(
        'session.html',
        session=game_session,
        participants=game_session.participants,
        is_host=participant and participant.id == game_session.host_id,
        participant=participant,
        token=participant.token if participant else None,
        grouped_availability=grouped,
        grouped_json=json.dumps(grouped_json),
        confirmations=confirmations
    )

@main.route("/auto_pick/<session_hash>")
def auto_pick(session_hash):
    session_obj = Session.query.filter_by(hash_id=session_hash).first_or_404()
    token = request.args.get('token')
    participant = Participant.query.filter_by(token=token).first_or_404()

    if participant.id != session_obj.host_id:
        return "Unauthorized", 403

    availabilities = Availability.query.filter_by(session_id=session_obj.id).all()

    slot_counts = {}

    for a in availabilities:
        start = a.start_time
        end = a.end_time
        current = start
        while current < end:
            slot_counts[current] = slot_counts.get(current, 0) + 1
            current += timedelta(minutes=30)  

    if slot_counts:
        # Pick the time with the max count
        best_time = max(slot_counts, key=lambda k: slot_counts[k])
        session_obj.final_time = best_time
        db.session.commit()
    
    # Notify participants
    sent_count, failed = notify_final_time(session_obj)
    flash(f"Emails sent successfully to {sent_count} participant(s).", "success")
    if failed:
        for name, reason in failed:
            flash(f"Failed to send email to {name}: {reason}", "danger")

    return redirect(url_for("main.view_session", session_hash=session_obj.hash_id, token=participant.token))

@main.route("/manual_pick/<session_hash>", methods=["POST"])
def manual_pick(session_hash):
    session_obj = Session.query.filter_by(hash_id=session_hash).first_or_404()
    token = request.args.get('token')
    participant = Participant.query.filter_by(token=token).first_or_404()

    if participant.id != session_obj.host_id:
        return "Unauthorized", 403

    manual_time_str = request.form["manual_time"]

    manual_time = datetime.fromisoformat(manual_time_str)
    session_obj.final_time = manual_time
    db.session.commit()
    
    # Notify participants
    sent_count, failed = notify_final_time(session_obj)
    flash(f"Emails sent successfully to {sent_count} participant(s).", "success")
    if failed:
        for name, reason in failed:
            flash(f"Failed to send email to {name}: {reason}", "danger")

    return redirect(url_for("main.view_session", session_hash=session_obj.hash_id, token=participant.token))

@main.route("/confirm/<session_id>/<token>", methods=["POST"])
def confirm(session_id, token):
    participant = Participant.query.filter_by(session_id=session_id, token=token).first_or_404()
    status = request.form.get("status")
    
    confirmation = Confirmation.query.filter_by(
        participant_id=participant.id,
        session_id=session_id
    ).first()
    
    if not confirmation:
        confirmation = Confirmation(
            participant_id=participant.id,
            session_id=session_id,
            status=status
        )
        db.session.add(confirmation)
    else:
        confirmation.status = status
    
    db.session.commit()
    
    return redirect(url_for("main.view_session", session_hash=participant.session.hash_id, token=token))

