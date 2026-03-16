"""
metrics.py

Calculates usage metrics for the SynQ dashboard.
"""

from collections import Counter
from datetime import timezone, timedelta

from sqlalchemy.exc import SQLAlchemyError

from website import db
from website.models import Participant, Session, Availability, Confirmation, GameVote


def _unique_key(p):
    """Return a stable identity key for a participant (email if present, else id)."""
    return (p.email or "").strip().lower() or f"id:{p.id}"


def _collect_confirmed_keys():
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
    activated_keys = set()

    hosts = {
        r[0] for r in Session.query.with_entities(Session.host_id).distinct().all()
        if r[0] is not None
    }
    for h in hosts:
        p = db.session.get(Participant, h)
        if p:
            activated_keys.add(_unique_key(p))

    confirmations = Confirmation.query.all()
    for c in confirmations:
        p = db.session.get(Participant, c.participant_id)
        if p:
            activated_keys.add(_unique_key(p))

    return activated_keys


def _collect_activation_rate(unique_joined):
    activated_keys = _collect_activated_keys()
    return round(len(activated_keys) / unique_joined * 100, 1) if unique_joined else 0


def _collect_repeat_usage(all_participants, unique_joined):
    repeat_count = 0

    email_to_ids = {}
    for p in all_participants:
        key = (p.email or "").strip().lower() or f"id:{p.id}"
        email_to_ids.setdefault(key, []).append(p.id)

    for key, pids in email_to_ids.items():
        events = []

        for pid in pids:
            for s in Session.query.filter_by(host_id=pid).all():
                if s.datetime:
                    t = s.datetime.replace(tzinfo=timezone.utc) if s.datetime.tzinfo is None else s.datetime
                    events.append((t, s.id, 'host'))

            for c in Confirmation.query.filter_by(participant_id=pid).all():
                for t_attr in ['created_at', 'updated_at']:
                    t = getattr(c, t_attr, None)
                    if t:
                        t = t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t
                        events.append((t, c.session_id, t_attr))

        events.sort(key=lambda x: x[0])

        for i in range(1, len(events)):
            prev = events[i - 1]
            curr = events[i]

            if prev[1] == curr[1] and prev[0] == curr[0]:
                continue

            if timedelta(days=1) <= (curr[0] - prev[0]) <= timedelta(days=7):
                repeat_count += 1
                break

    return round(repeat_count / unique_joined * 100, 1) if unique_joined else 0


def _sessions_with_multiple_participants(all_sessions):
    """% of sessions where participant count > 1."""
    if not all_sessions:
        return 0
    multi = sum(
        1 for s in all_sessions
        if Participant.query.filter_by(session_id=s.id).count() > 1
    )
    return round(multi / len(all_sessions) * 100, 1)


def _session_completion_rate(all_sessions):
    """% of sessions that have a final_time set."""
    if not all_sessions:
        return 0
    completed = sum(1 for s in all_sessions if s.final_time is not None)
    return round(completed / len(all_sessions) * 100, 1)


def _avg_participants_per_session(all_sessions):
    """Average number of participants across all sessions."""
    if not all_sessions:
        return 0
    total = sum(Participant.query.filter_by(session_id=s.id).count() for s in all_sessions)
    return round(total / len(all_sessions), 1)


def _sessions_with_votes(all_sessions):
    """% of sessions that have at least one game vote."""
    if not all_sessions:
        return 0
    with_votes = sum(
        1 for s in all_sessions
        if GameVote.query.filter_by(session_id=s.id).count() > 0
    )
    return round(with_votes / len(all_sessions) * 100, 1)


def _top_games(limit=5):
    """Return list of (game_name, count) tuples sorted by vote count descending."""
    votes = GameVote.query.with_entities(GameVote.game_name).all()
    counts = Counter(v[0] for v in votes if v[0])
    return counts.most_common(limit)


def _confirmation_breakdown():
    """Return dict of {status: count} for all confirmations."""
    rows = Confirmation.query.with_entities(Confirmation.status).all()
    counts = Counter(r[0] for r in rows if r[0])
    return {
        "Yes":   counts.get("Yes", 0),
        "Maybe": counts.get("Maybe", 0),
        "No":    counts.get("No", 0),
    }


def calculate_metrics():
    """Return dashboard metrics dict."""
    try:
        all_participants = Participant.query.all()
        unique_joined = len({_unique_key(p) for p in all_participants})
    except SQLAlchemyError:
        all_participants = []
        unique_joined = 0

    try:
        all_sessions = Session.query.all()
        total_sessions = len(all_sessions)
    except SQLAlchemyError:
        all_sessions = []
        total_sessions = 0

    try:
        confirmed_keys = _collect_confirmed_keys()
        confirmed_count = len(confirmed_keys)
    except SQLAlchemyError:
        confirmed_keys = set()
        confirmed_count = 0

    try:
        availability_keys = _collect_availability_keys()
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
        unique_emails = sorted({
            p.email.strip().lower()
            for p in all_participants
            if p.email and p.email.strip()
        })
    except SQLAlchemyError:
        unique_emails = []

    try:
        multi_participant_rate = _sessions_with_multiple_participants(all_sessions)
    except SQLAlchemyError:
        multi_participant_rate = 0

    try:
        completion_rate = _session_completion_rate(all_sessions)
    except SQLAlchemyError:
        completion_rate = 0

    try:
        avg_participants = _avg_participants_per_session(all_sessions)
    except SQLAlchemyError:
        avg_participants = 0

    try:
        sessions_with_votes_pct = _sessions_with_votes(all_sessions)
    except SQLAlchemyError:
        sessions_with_votes_pct = 0

    try:
        top_games = _top_games()
    except SQLAlchemyError:
        top_games = []

    try:
        confirmation_breakdown = _confirmation_breakdown()
    except SQLAlchemyError:
        confirmation_breakdown = {"Yes": 0, "Maybe": 0, "No": 0}

    return {
        "total_users": unique_joined,
        "sessions_created": total_sessions,
        "confirmed_participants": confirmed_count,
        "availability_only_participants": availability_only_count,
        "activation_rate": f"{activation_rate}%",
        "repeat_usage": f"{repeat_usage}%",
        "unique_emails": unique_emails,
        "multi_participant_rate": f"{multi_participant_rate}%",
        "completion_rate": f"{completion_rate}%",
        "avg_participants": avg_participants,
        "sessions_with_votes_pct": f"{sessions_with_votes_pct}%",
        "top_games": top_games,
        "confirmation_breakdown": confirmation_breakdown,
    }