from website import db
from website.models import Participant, Session, Availability, Confirmation
from datetime import timezone, timedelta

def _unique_key(p):
    """Same person across sessions = 1 (use email; if no email, use id)."""
    return (p.email or "").strip() or f"id:{p.id}"

def calculate_metrics():
    try:
        total_sessions = Session.query.count()
    except Exception:
        total_sessions = 0

    # Unique participants: count each person once even if they joined multiple sessions
    try:
        all_participants = Participant.query.all()
        unique_joined = len({_unique_key(p) for p in all_participants})
    except Exception:
        unique_joined = 0
        all_participants = []

    # Unique participants who actually confirmed availability (submitted time slots)
    with_avail = set()
    with_confirm = set()
    confirmed_unique_keys = set()
    try:
        with_avail = {r[0] for r in db.session.query(Availability.participant_id).distinct().all() if r[0] is not None}
        with_confirm = {r[0] for r in db.session.query(Confirmation.participant_id).distinct().all() if r[0] is not None}
        for pid in with_avail | with_confirm:
            p = Participant.query.get(pid)
            if p:
                confirmed_unique_keys.add(_unique_key(p))
        confirmed_availability_count = len(confirmed_unique_keys)
    except Exception:
        confirmed_availability_count = 0

    try:
        hosts = {r[0] for r in Session.query.filter(Session.host_id.isnot(None)).with_entities(Session.host_id).distinct().all() if r[0] is not None}
        host_keys = {_unique_key(Participant.query.get(h)) for h in hosts if Participant.query.get(h)}
        activated_keys = host_keys | confirmed_unique_keys
        activation_rate = round((len(activated_keys) / unique_joined * 100), 1) if unique_joined else 0
    except Exception:
        activation_rate = 0

    repeat_count = 0
    try:
        seen_keys = set()
        for p in all_participants:
            key = _unique_key(p)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            times = []
            try:
                for s in Session.query.filter_by(host_id=p.id).all():
                    if s.final_time:
                        t = s.final_time
                        times.append(t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t)
            except Exception:
                pass
            try:
                for a in Availability.query.filter_by(participant_id=p.id).all():
                    if a.start_time:
                        t = a.start_time
                        times.append(t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t)
            except Exception:
                pass
            times.sort()
            if len(times) >= 2 and (times[1] - times[0]) <= timedelta(days=7):
                repeat_count += 1
        repeat_usage = round((repeat_count / unique_joined * 100), 1) if unique_joined else 0
    except Exception:
        repeat_usage = 0

    return {
        "total_users": unique_joined,
        "sessions_created": total_sessions,
        "confirmed_participants": confirmed_availability_count,
        "activation_rate": f"{activation_rate}%",
        "repeat_usage": f"{repeat_usage}%",
    }
