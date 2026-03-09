"""
metrics.py

Calculates usage metrics for the SynQ dashboard.
"""

from datetime import timezone, timedelta

from sqlalchemy.exc import SQLAlchemyError

from website import db
from website.models import Participant, Session, Availability, Confirmation


def _unique_key(p):
    """Return a stable identity key for a participant (email if present, else id)."""
    return (p.email or "").strip().lower() or f"id:{p.id}"


def _collect_confirmed_keys():
    """
    Return set of unique participant keys who have a confirmation.
    Only participants with a confirmation count as 'confirmed'.
    """
    confirmed_keys = set()
    confirmed_participant_ids = {
        r[0] for r in db.session.query(Confirmation.participant_id).distinct().all()
        if r[0] is not None
    }
    for pid in confirmed_participant_ids:
        p = db.session.get(Participant, pid)
        if p:
            confirmed_keys.add(_unique_key(p))
    return confirmed_keys

def _collect_availability_keys():
    """
    Return set of unique participant keys who have submitted availability,
    but may not have confirmed yet.
    """
    availability_keys = set()
    participant_ids = {
        r[0] for r in db.session.query(Availability.participant_id).distinct().all()
        if r[0] is not None
    }
    for pid in participant_ids:
        p = db.session.get(Participant, pid)
        if p:
            availability_keys.add(_unique_key(p))
    return availability_keys

def _collect_activated_keys():
    """
    Return set of unique participant keys who have activity:
    - Hosted a session
    - Created or updated a confirmation
    """
    activated_keys = set()

    # Participants who hosted sessions
    hosts = {
        r[0] for r in Session.query.with_entities(Session.host_id).distinct().all()
        if r[0] is not None
    }
    for h in hosts:
        p = db.session.get(Participant, h)
        if p:
            activated_keys.add(_unique_key(p))

    # Participants who confirmed (created or updated)
    confirmations = Confirmation.query.all()
    for c in confirmations:
        p = db.session.get(Participant, c.participant_id)
        if p:
            activated_keys.add(_unique_key(p))

    return activated_keys

def _collect_activation_rate(unique_joined):
    """Return activation rate as a percentage based on actual activity."""
    activated_keys = _collect_activated_keys()
    return round(len(activated_keys) / unique_joined * 100, 1) if unique_joined else 0

def _collect_repeat_usage(all_participants, unique_joined):
    """Return repeat usage rate as a rounded float."""
    repeat_count = 0
    seen_keys = set()

    for p in all_participants:
        key = (p.email or "").strip().lower()
        if not key or key in seen_keys:
            continue
        seen_keys.add(key)

        events = []

        # Hosting sessions
        for s in Session.query.filter_by(host_id=p.id).all():
            if s.datetime:
                t = s.datetime.replace(tzinfo=timezone.utc) if s.datetime.tzinfo is None else s.datetime
                events.append((t, s.id, 'host'))

        # Confirmations (created or updated)
        for c in Confirmation.query.filter_by(participant_id=p.id).all():
            for t_attr in ['created_at', 'updated_at']:
                t = getattr(c, t_attr, None)
                if t:
                    t = t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t
                    events.append((t, c.session_id, t_attr))

        # Sort by timestamp
        events.sort(key=lambda x: x[0])

        # Track if any repeat activity exists
        for i in range(1, len(events)):
            prev = events[i - 1]
            curr = events[i]

            # Ignore if both activities are for same session and same timestamp
            if prev[1] == curr[1] and prev[0] == curr[0]:
                continue

            # Count as repeat if within window
            if (curr[0] - prev[0]) <= timedelta(days=7):
                repeat_count += 1
                break  # Count each participant only once

    return round(repeat_count / unique_joined * 100, 1) if unique_joined else 0

def calculate_metrics():
    """Return dashboard metrics dict."""
    try:
        all_participants = Participant.query.all()
        unique_joined = len({_unique_key(p) for p in all_participants})
    except SQLAlchemyError:
        all_participants = []
        unique_joined = 0

    try:
        confirmed_keys = _collect_confirmed_keys()
        confirmed_count = len(confirmed_keys)
    except SQLAlchemyError:
        confirmed_keys = set()
        confirmed_count = 0
    
    try:
        availability_keys = _collect_availability_keys()
        # Only count users who submitted availability but are NOT confirmed
        availability_only_count = len(availability_keys - confirmed_keys)
    except SQLAlchemyError:
        availability_only_count = 0

    try:
        activation_rate = _collect_activation_rate(unique_joined)
    except SQLAlchemyError:
        activation_rate = 0

    try:
        repeat_usage = _collect_repeat_usage(all_participants, unique_joined)
    except SQLAlchemyError:
        repeat_usage = 0

    try:
        total_sessions = Session.query.count()
    except SQLAlchemyError:
        total_sessions = 0

    return {
        "total_users": unique_joined,
        "sessions_created": total_sessions,
        "confirmed_participants": confirmed_count,
        "availability_only_participants": availability_only_count,
        "activation_rate": f"{activation_rate}%",
        "repeat_usage": f"{repeat_usage}%",
    }
