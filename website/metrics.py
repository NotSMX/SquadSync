from website import db
from website.models import Participant, Session, Availability, Confirmation
from datetime import timezone, timedelta

def calculate_metrics():
    try:
        total_users = Participant.query.count()
    except Exception:
        total_users = 0
    try:
        total_sessions = Session.query.count()
    except Exception:
        total_sessions = 0

    with_avail = set()
    with_confirm = set()
    try:
        with_avail = {r[0] for r in db.session.query(Availability.participant_id).distinct().all() if r[0] is not None}
        with_confirm = {r[0] for r in db.session.query(Confirmation.participant_id).distinct().all() if r[0] is not None}
        confirmed_participants = len(with_avail | with_confirm)
    except Exception:
        confirmed_participants = 0

    try:
        hosts = {r[0] for r in Session.query.filter(Session.host_id.isnot(None)).with_entities(Session.host_id).distinct().all() if r[0] is not None}
        activated = len(hosts | with_avail | with_confirm)
        activation_rate = round((activated / total_users * 100), 1) if total_users else 0
    except Exception:
        activation_rate = 0

    repeat_count = 0
    try:
        for p in Participant.query.all():
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
        repeat_usage = round((repeat_count / total_users * 100), 1) if total_users else 0
    except Exception:
        repeat_usage = 0

    return {
        "total_users": total_users,
        "sessions_created": total_sessions,
        "confirmed_participants": confirmed_participants,
        "activation_rate": f"{activation_rate}%",
        "repeat_usage": f"{repeat_usage}%",
    }
