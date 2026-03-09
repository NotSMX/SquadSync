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
    return (p.email or "").strip() or f"id:{p.id}"


def _collect_confirmed_keys():
    """Return set of unique keys for participants with availability or confirmation."""
    confirmed_unique_keys = set()
    with_avail = {
        r[0] for r in db.session.query(Availability.participant_id).distinct().all()
        if r[0] is not None
    }
    with_confirm = {
        r[0] for r in db.session.query(Confirmation.participant_id).distinct().all()
        if r[0] is not None
    }
    for pid in with_avail | with_confirm:
        p = db.session.get(Participant, pid)
        if p:
            confirmed_unique_keys.add(_unique_key(p))
    return confirmed_unique_keys


def _collect_activation_rate(unique_joined, confirmed_unique_keys):
    """Return activation rate as a rounded float."""
    hosts = {
        r[0]
        for r in Session.query.filter(
            Session.host_id.isnot(None)
        ).with_entities(Session.host_id).distinct().all()
        if r[0] is not None
    }
    host_keys = {
        _unique_key(db.session.get(Participant, h))
        for h in hosts
        if db.session.get(Participant, h)
    }
    activated_keys = host_keys | confirmed_unique_keys
    return round(len(activated_keys) / unique_joined * 100, 1) if unique_joined else 0


def _collect_repeat_usage(all_participants, unique_joined):
    """Return repeat usage rate as a rounded float."""
    repeat_count = 0
    seen_keys = set()
    for p in all_participants:
        key = _unique_key(p)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        times = []
        for s in Session.query.filter_by(host_id=p.id).all():
            if s.final_time:
                t = s.final_time
                times.append(t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t)
        for a in Availability.query.filter_by(participant_id=p.id).all():
            if a.start_time:
                t = a.start_time
                times.append(t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t)
        times.sort()
        if len(times) >= 2 and (times[1] - times[0]) <= timedelta(days=7):
            repeat_count += 1
    return round(repeat_count / unique_joined * 100, 1) if unique_joined else 0


def calculate_metrics():
    """Return a dict of usage metrics for the dashboard."""
    try:
        total_sessions = Session.query.count()
    except SQLAlchemyError:
        total_sessions = 0

    try:
        all_participants = Participant.query.all()
        unique_joined = len({_unique_key(p) for p in all_participants})
    except SQLAlchemyError:
        unique_joined = 0
        all_participants = []

    try:
        confirmed_unique_keys = _collect_confirmed_keys()
        confirmed_availability_count = len(confirmed_unique_keys)
    except SQLAlchemyError:
        confirmed_unique_keys = set()
        confirmed_availability_count = 0

    try:
        activation_rate = _collect_activation_rate(unique_joined, confirmed_unique_keys)
    except SQLAlchemyError:
        activation_rate = 0

    try:
        repeat_usage = _collect_repeat_usage(all_participants, unique_joined)
    except SQLAlchemyError:
        repeat_usage = 0

    return {
        "total_users": unique_joined,
        "sessions_created": total_sessions,
        "confirmed_participants": confirmed_availability_count,
        "activation_rate": f"{activation_rate}%",
        "repeat_usage": f"{repeat_usage}%",
    }
