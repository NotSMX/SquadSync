from app.models import User, Session, Availability

def calculate_metrics():
    total_users = User.query.count()
    total_sessions = Session.query.count()

    total_availabilities = Availability.query.count()

    if total_sessions > 0:
        completion_rate = (total_availabilities / total_sessions) * 100
    else:
        completion_rate = 0

    return {
        "total_users": total_users,
        "total_sessions": total_sessions,
        "core_action_rate": round(completion_rate, 2)
    }