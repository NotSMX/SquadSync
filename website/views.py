"""
views.py

Routes for SynQ MVP:
Create Session → Join → Submit Availability → Auto Pick → Confirm
"""
# pylint: disable=cyclic-import
import json
from datetime import datetime

from flask import Blueprint, current_app, render_template, redirect, url_for, request, flash, jsonify
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from website import db
from website.models import Confirmation, Participant, Session, Availability, GameVote
from website.utils import notify_final_time

main = Blueprint("main", __name__)

@main.route("/")
def index():
    """Render the homepage."""
    return render_template("index.html")


@main.route("/dashboard")
def dashboard():
    """Render the metrics dashboard."""
    from website.metrics import calculate_metrics  # pylint: disable=import-outside-toplevel
    return render_template("dashboard.html", metrics=calculate_metrics())


@main.route("/reset-db", methods=["POST"])
def reset_db():
    """Drop all tables and recreate (for testing)."""
    db.drop_all()
    db.create_all()
    flash("Database reset.", "success")
    return redirect(url_for("main.dashboard"))


@main.route("/sessions")
def list_sessions():
    """List all public sessions."""
    public_sessions = Session.query.filter_by(is_public=True).all()

    sessions_data = []

    for s in public_sessions:
        host = None
        if s.host_id:
            host = Participant.query.get(s.host_id)

        sessions_data.append({
            "session": s,
            "participants": s.participants,
            "host": host
        })

    return render_template(
        "sessions.html",
        sessions=sessions_data
    )


def _ensure_game_election_schema():
    """Ensure DB has columns/tables needed for game election (handles old SQLite DBs)."""
    with db.engine.connect() as conn:
        for table, col, typ in [
            ("session", "hash_id", "VARCHAR(32)"),
            ("session", "host_id", "INTEGER"),
            ("session", "final_time", "DATETIME"),
            ("session", "chosen_game", "VARCHAR(120)"),
            ("session", "is_public", "INTEGER"),
            ("availability", "participant_id", "INTEGER"),
            ("availability", "session_id", "INTEGER"),
            ("availability", "start_time", "DATETIME"),
            ("availability", "end_time", "DATETIME"),
        ]:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {typ}"))
                conn.commit()
            except SQLAlchemyError:
                conn.rollback()
    db.create_all()


@main.route("/test-game-election")
def test_game_election():
    """Create a test session and redirect to it for game election testing."""
    _ensure_game_election_schema()
    session_obj = Session(title="Game election test")
    db.session.add(session_obj)
    db.session.commit()
    host = Participant(
        name="Test Host", session_id=session_obj.id, email="test@test.com"
    )
    db.session.add(host)
    db.session.commit()
    session_obj.host_id = host.id
    db.session.commit()
    return redirect(
        url_for("main.view_session", session_hash=session_obj.hash_id, token=host.token)
    )


@main.route("/create", methods=["GET", "POST"])
def create_session():
    """Create a new session and redirect the host to it."""
    if request.method == "POST":
        _ensure_game_election_schema()
        title = request.form["title"]
        host_name = request.form["name"]
        email = request.form["email"]
        is_public = "is_public" in request.form

        new_session = Session(title=title, is_public=is_public)
        db.session.add(new_session)
        db.session.commit()

        host_participant = Participant(
            name=host_name, session_id=new_session.id, email=email
        )
        db.session.add(host_participant)
        db.session.commit()

        new_session.host_id = host_participant.id
        db.session.commit()

        return redirect(url_for(
            "main.view_session",
            session_hash=new_session.hash_id,
            token=host_participant.token
        ))

    return render_template("create_session.html")


@main.route("/join/<int:session_id>", methods=["POST"])
def join_session(session_id):
    """Join an existing session."""
    name = request.form["name"]
    email = request.form["email"]

    participant = Participant(name=name, email=email, session_id=session_id)
    db.session.add(participant)
    db.session.commit()

    game_session = db.session.get(Session, session_id)
    if not game_session.host_id:
        game_session.host_id = participant.id
        db.session.commit()

    return redirect(url_for(
        "main.view_session",
        session_hash=game_session.hash_id,
        token=participant.token
    ))


@main.route('/availability/<int:session_id>/<token>', methods=['GET', 'POST'])
def availability(session_id, token):
    """View or submit availability for a session."""
    participant = Participant.query.filter_by(
        session_id=session_id, token=token
    ).first_or_404()

    if request.method == 'POST':
        raw = request.form.get('availability_data', '[]')
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            data = []
        if not isinstance(data, list):
            data = []

        def parse_iso(s):
            if not s:
                return None
            s = str(s).strip().replace('Z', '+00:00')
            try:
                return datetime.fromisoformat(s)
            except ValueError:
                return None

        Availability.query.filter_by(
            session_id=session_id, participant_id=participant.id
        ).delete()

        for block in data:
            start = parse_iso(block.get('start'))
            end = parse_iso(block.get('end'))
            if start is None or end is None or start >= end:
                continue
            db.session.add(Availability(
                session_id=session_id,
                participant_id=participant.id,
                start_time=start,
                end_time=end
            ))

        db.session.commit()
        flash("Availability saved.", "success")
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


def _build_grouped_json(game_session):
    """Build the grouped availability dict for JSON serialisation."""
    grouped = {}
    grouped_json = {}
    for p in game_session.participants:
        grouped[p] = p.availabilities
        grouped_json[p.name] = [
            {
                "start": block.start_time.isoformat(),
                "end": block.end_time.isoformat(),
            }
            for block in p.availabilities
            if block.start_time and block.end_time
        ]
    return grouped, grouped_json


def _build_game_tally(game_session, participant):
    """Return (game_tally, my_game_vote) for the session."""
    game_votes_raw = GameVote.query.filter_by(session_id=game_session.id).all()
    tally_by_key = {}
    my_game_vote = None
    for v in game_votes_raw:
        raw = (v.game_name or "").strip() or "(empty)"
        key = raw.lower()
        if key not in tally_by_key:
            tally_by_key[key] = [raw, 0]
        tally_by_key[key][1] += 1
        if participant and v.participant_id == participant.id:
            my_game_vote = v.game_name
    game_tally = sorted(tally_by_key.values(), key=lambda x: -x[1])
    return game_tally, my_game_vote


@main.route('/session/<session_hash>')
def view_session(session_hash):
    """View a session page."""
    game_session = Session.query.filter_by(hash_id=session_hash).first_or_404()
    participant_token = request.args.get('token')
    participant = (
        Participant.query.filter_by(token=participant_token).first()
        if participant_token else None
    )
    is_host = bool(participant and participant.id == game_session.host_id)

    grouped, grouped_json = _build_grouped_json(game_session)

    confirmations = {
        p.id: (
            Confirmation.query.filter_by(
                participant_id=p.id, session_id=game_session.id
            ).first() or type('obj', (object,), {'status': None})()
        ).status
        for p in game_session.participants
    }

    game_tally, my_game_vote = _build_game_tally(game_session, participant)
    return render_template(
        'session.html',
        session=game_session,
        participants=game_session.participants,
        is_host=is_host,
        participant=participant,
        token=participant.token if participant else None,
        grouped_availability=grouped,
        grouped_json=json.dumps(grouped_json),
        confirmations=confirmations,
        game_tally=game_tally,
        my_game_vote=my_game_vote,
        rawg_key=current_app.config.get("RAWG_API_KEY", ""),
    )


def _intersect_intervals(intervals_a, intervals_b):
    """Return list of (start, end) that lie in both interval lists. Merged."""
    out = []
    for (a_s, a_e) in intervals_a:
        for (b_s, b_e) in intervals_b:
            s = max(a_s, b_s)
            e = min(a_e, b_e)
            if s < e:
                out.append((s, e))
    if not out:
        return []
    out.sort(key=lambda x: x[0])
    merged = [out[0]]
    for s, e in out[1:]:
        if s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def _notify_and_flash(session_obj):
    """Send final time emails and flash results."""
    sent_count, failed = notify_final_time(session_obj)
    if sent_count > 0:
        flash(f"Emails sent to {sent_count} participant(s).", "success")
    for name, reason in failed:
        flash(f"Failed to email {name}: {reason}", "danger")


@main.route("/auto_pick/<session_hash>")
def auto_pick(session_hash):
    """Auto-pick the first time slot that works for all participants."""
    session_obj = Session.query.filter_by(hash_id=session_hash).first_or_404()
    participant_token = request.args.get('token')
    participant = Participant.query.filter_by(token=participant_token).first_or_404()

    if participant.id != session_obj.host_id:
        return "Unauthorized", 403

    participants_with_avail = [
        [(a.start_time, a.end_time) for a in p.availabilities
         if a.session_id == session_obj.id and a.start_time and a.end_time]
        for p in session_obj.participants
    ]
    participants_with_avail = [b for b in participants_with_avail if b]

    if not participants_with_avail:
        flash("No availability submitted yet.", "warning")
        return redirect(url_for(
            "main.view_session",
            session_hash=session_obj.hash_id, token=participant.token
        ))

    overlap = participants_with_avail[0]
    for other in participants_with_avail[1:]:
        overlap = _intersect_intervals(overlap, other)
        if not overlap:
            break

    if not overlap:
        flash(
            "No time works for everyone. Try manual pick or ask for more availability.",
            "warning"
        )
        return redirect(url_for(
            "main.view_session",
            session_hash=session_obj.hash_id, token=participant.token
        ))

    start, _ = overlap[0]
    session_obj.final_time = start
    db.session.commit()
    flash(
        f"Session set to {start.strftime('%A, %B %d at %I:%M %p')} "
        "(time that works for everyone).",
        "success"
    )
    _notify_and_flash(session_obj)
    return redirect(url_for(
        "main.view_session", session_hash=session_obj.hash_id, token=participant.token
    ))


@main.route("/manual_pick/<session_hash>", methods=["POST"])
def manual_pick(session_hash):
    """Manually set the final session time."""
    session_obj = Session.query.filter_by(hash_id=session_hash).first_or_404()
    participant_token = request.args.get('token')
    participant = Participant.query.filter_by(token=participant_token).first_or_404()

    if participant.id != session_obj.host_id:
        return "Unauthorized", 403

    manual_time_str = request.form["manual_time"]
    session_obj.final_time = datetime.fromisoformat(manual_time_str)
    db.session.commit()
    _notify_and_flash(session_obj)
    return redirect(url_for(
        "main.view_session", session_hash=session_obj.hash_id, token=participant.token
    ))


@main.route("/confirm/<session_id>/<token>", methods=["POST"])
def confirm(session_id, token):
    """Record a participant's confirmation status for the final time."""
    participant = Participant.query.filter_by(
        session_id=session_id, token=token
    ).first_or_404()
    status = request.form.get("status")

    confirmation = Confirmation.query.filter_by(
        participant_id=participant.id, session_id=session_id
    ).first()

    if not confirmation:
        confirmation = Confirmation(
            participant_id=participant.id, session_id=session_id, status=status
        )
        db.session.add(confirmation)
    else:
        confirmation.status = status

    db.session.commit()
    return redirect(url_for(
        "main.view_session",
        session_hash=participant.session.hash_id, token=token
    ))


@main.route("/session/<session_hash>/join_and_vote", methods=["POST"])
def join_and_vote(session_hash):
    """Join a session and vote for a game in one step (for public link visitors)."""
    game_session = Session.query.filter_by(hash_id=session_hash).first_or_404()
    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip()
    game_name = (request.form.get("game_name") or "").strip()

    if not name:
        flash("Please enter your name.", "warning")
        return redirect(url_for("main.view_session", session_hash=session_hash))
    if not game_name:
        flash("Please enter your preferred game.", "warning")
        return redirect(url_for("main.view_session", session_hash=session_hash))

    participant = Participant(name=name, email=email or None, session_id=game_session.id)
    db.session.add(participant)
    db.session.commit()

    if not game_session.host_id:
        game_session.host_id = participant.id
        db.session.commit()

    vote = GameVote(
        session_id=game_session.id, participant_id=participant.id, game_name=game_name
    )
    db.session.add(vote)
    db.session.commit()
    flash("Thanks! Your vote was added.", "success")
    return redirect(url_for(
        "main.view_session", session_hash=session_hash, token=participant.token
    ))


@main.route("/session/<session_hash>/vote_game", methods=["POST"])
def vote_game(session_hash):
    """Submit or update a game vote for the session."""
    game_session = Session.query.filter_by(hash_id=session_hash).first_or_404()
    participant_token = request.args.get("token") or request.form.get("token")
    participant = Participant.query.filter_by(
        session_id=game_session.id, token=participant_token
    ).first_or_404()
    game_name = (request.form.get("game_name") or "").strip() or None

    if not game_name:
        flash("Enter a game name to vote.", "warning")
        return redirect(url_for(
            "main.view_session", session_hash=session_hash, token=participant_token
        ))

    vote = GameVote.query.filter_by(
        session_id=game_session.id, participant_id=participant.id
    ).first()
    if vote:
        vote.game_name = game_name
    else:
        db.session.add(GameVote(
            session_id=game_session.id,
            participant_id=participant.id,
            game_name=game_name
        ))
    db.session.commit()
    flash("Vote saved.", "success")
    return redirect(url_for(
        "main.view_session", session_hash=session_hash, token=participant_token
    ))


@main.route("/session/<session_hash>/add_availability", methods=["POST"])
def add_availability_from_calendar(session_hash):
    """Add one availability block via the calendar drag interface."""
    game_session = Session.query.filter_by(hash_id=session_hash).first_or_404()
    participant_token = request.form.get("token")
    participant = Participant.query.filter_by(
        session_id=game_session.id, token=participant_token
    ).first_or_404()
    start_str = (request.form.get("start") or "").strip()
    end_str = (request.form.get("end") or "").strip()
    is_xhr = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    def fail_json(msg):
        if is_xhr:
            return {"ok": False, "error": msg}, 400
        flash(msg, "warning")
        return redirect(url_for(
            "main.view_session", session_hash=session_hash, token=participant_token
        ))

    def ok_redirect():
        if is_xhr:
            return {"ok": True}
        flash("Availability added.", "success")
        return redirect(url_for(
            "main.view_session", session_hash=session_hash, token=participant_token
        ))

    if not start_str or not end_str:
        return fail_json("Missing start or end time.")

    start_str = start_str.replace("Z", "+00:00")
    end_str = end_str.replace("Z", "+00:00")

    try:
        start_dt = datetime.fromisoformat(start_str)
        end_dt = datetime.fromisoformat(end_str)
    except ValueError:
        return fail_json("Invalid time format.")

    if start_dt >= end_dt:
        return fail_json("End must be after start.")

    db.session.add(Availability(
        session_id=game_session.id,
        participant_id=participant.id,
        start_time=start_dt,
        end_time=end_dt,
    ))
    db.session.commit()
    return ok_redirect()


@main.route("/session/<session_hash>/set_game", methods=["POST"])
def set_game(session_hash):
    """Host sets or clears the chosen game for the session."""
    game_session = Session.query.filter_by(hash_id=session_hash).first_or_404()
    participant_token = request.args.get("token") or request.form.get("token")
    participant = Participant.query.filter_by(
        session_id=game_session.id, token=participant_token
    ).first_or_404()

    if participant.id != game_session.host_id:
        flash("Only the host can set the game.", "danger")
        return redirect(url_for(
            "main.view_session", session_hash=session_hash, token=participant_token
        ))

    game_name = (request.form.get("game_name") or "").strip() or None
    game_session.chosen_game = game_name
    db.session.commit()
    flash("Game set." if game_name else "Game cleared.", "success")
    return redirect(url_for(
        "main.view_session", session_hash=session_hash, token=participant_token
    ))


@main.route("/session/<session_hash>/remove_availability", methods=["POST"])
def remove_availability_from_calendar(session_hash):
    """Remove one availability block via the calendar."""
    game_session = Session.query.filter_by(hash_id=session_hash).first_or_404()
    participant_token = request.form.get("token")
    participant = Participant.query.filter_by(
        session_id=game_session.id, token=participant_token
    ).first_or_404()
    start_str = (request.form.get("start") or "").strip()
    end_str = (request.form.get("end") or "").strip()
    is_xhr = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    def fail(msg):
        if is_xhr:
            return {"ok": False, "error": msg}, 400
        flash(msg, "warning")
        return redirect(url_for(
            "main.view_session", session_hash=session_hash, token=participant_token
        ))

    if not start_str or not end_str:
        return fail("Missing start or end time.")

    start_str = start_str.replace("Z", "+00:00")
    end_str = end_str.replace("Z", "+00:00")

    try:
        start_dt = datetime.fromisoformat(start_str)
        end_dt = datetime.fromisoformat(end_str)
    except ValueError:
        return fail("Invalid time format.")

    block = Availability.query.filter_by(
        session_id=game_session.id,
        participant_id=participant.id,
        start_time=start_dt,
        end_time=end_dt
    ).first()

    if not block:
        return fail("Availability block not found.")

    db.session.delete(block)
    db.session.commit()

    if is_xhr:
        return {"ok": True}

    flash("Availability removed.", "success")
    return redirect(url_for(
        "main.view_session", session_hash=session_hash, token=participant_token
    ))


@main.route("/session/<session_hash>/availability_data")
def availability_data(session_hash):
    """Return live availability data as JSON for calendar polling."""
    game_session = Session.query.filter_by(hash_id=session_hash).first_or_404()
    grouped_json = {
        p.name: [
            {"start": b.start_time.isoformat(), "end": b.end_time.isoformat()}
            for b in p.availabilities if b.start_time and b.end_time
        ]
        for p in game_session.participants
    }
    return jsonify(grouped_json)
