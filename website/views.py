"""
views.py

Routes for SynQ MVP:
Create Session → Join → Submit Availability → Auto Pick → Confirm
"""
# pylint: disable=redefined-outer-name
# pylint: disable=cyclic-import
# pylint: disable=duplicate-code

import json
from flask import has_request_context
from flask_socketio import join_room
from datetime import datetime

from flask import Blueprint, current_app, render_template, redirect, url_for, request, flash, jsonify
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from website import db, socketio
from website.models import Confirmation, Participant, Session, Availability, GameVote, Feedback
from website.utils import notify_final_time, notify_personal_link, notify_feedback_submitted

from gevent import spawn

main = Blueprint("main", __name__)

@socketio.on("join")
def on_join(data):
    join_room(data["session_hash"])

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
    from sqlalchemy import text
    with db.engine.connect() as conn:
        conn.execute(text("UPDATE session SET host_id = NULL"))
        conn.commit()
    GameVote.query.delete()
    Confirmation.query.delete()
    Availability.query.delete()
    Participant.query.delete()
    Session.query.delete()
    db.session.commit()
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

def strip_tz(dt):
    """Convert to UTC then strip timezone for naive storage."""
    if dt.tzinfo is not None:
        from datetime import timezone
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt

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
            ("experiment_result", "link_token", "VARCHAR(64)"),
            ("experiment_result", "click_count", "INTEGER"),
            ("experiment_result", "scroll_depth", "REAL"),
            ("experiment_result", "first_interaction_ms", "INTEGER"),
            ("experiment_result", "used_calendar", "INTEGER"),
            ("experiment_result", "typed_game", "INTEGER"),
            ("experiment_result", "calendar_block_count", "INTEGER"),
            ("experiment_result", "calendar_section_ms", "INTEGER"),
            ("experiment_result", "game_section_ms", "INTEGER"),
            ("experiment_result", "time_to_calendar_ms", "INTEGER"),
            ("experiment_result", "time_to_game_ms", "INTEGER"),
            ("experiment_result", "rage_click_count", "INTEGER"),
            ("experiment_result", "form_focus_ms", "INTEGER"),
            ("experiment_result", "nudge_hover", "INTEGER"),
            ("experiment_result", "ease_of_use", "INTEGER"),
            ("experiment_result", "layout_clarity", "INTEGER"),
            ("experiment_result", "noticed_first", "VARCHAR(20)"),
            ("experiment_result", "real_use_likelihood", "INTEGER"),
            ("experiment_result", "feedback_text", "TEXT"),
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
        host_name = (request.form.get("name") or "").strip() or "Host"
        title = (request.form.get("title") or "").strip() or f"{host_name}'s session"
        email = request.form.get("email", "").strip()
        is_public = "is_public" in request.form

        new_session = Session(title=title, is_public=is_public)
        db.session.add(new_session)
        db.session.commit()

        host_participant = Participant(
            name=host_name, session_id=new_session.id, email=email
        )
        db.session.add(host_participant)
        db.session.commit()
        spawn(notify_personal_link, current_app._get_current_object(), host_participant, new_session)

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

    spawn(notify_personal_link, current_app._get_current_object(), participant, game_session)

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

def _emit_state(session_hash):
    """Broadcast current session state to all clients in the room."""
    game_session = Session.query.filter_by(hash_id=session_hash).first()
    if not game_session:
        return
    _, grouped_json = _build_grouped_json(game_session)
    game_tally, _ = _build_game_tally(game_session, None)
    tally_out = [{"name": g[0], "count": g[1]} for g in game_tally]

    confs = Confirmation.query.filter_by(session_id=game_session.id).all()
    conf_map = {}
    for c in confs:
        p = next((x for x in game_session.participants if x.id == c.participant_id), None)
        if p:
            conf_map[p.name] = c.status

    socketio.emit("state_update", {
        "availability": grouped_json,
        "game_tally": tally_out,
        "chosen_game": game_session.chosen_game,
        "final_time": game_session.final_time.isoformat() if game_session.final_time else None,
        "confirmations": conf_map,
        "participants": [p.name for p in game_session.participants],
    }, room=session_hash)

@main.route('/session/<session_hash>')
def view_session(session_hash):
    """View a session page."""
    game_session = Session.query.filter_by(hash_id=session_hash).first()
    if not game_session:
        flash("This session no longer exists.", "warning")
        return redirect(url_for("main.index"))
    
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

    if not has_request_context():
        return sent_count, failed

    if sent_count > 0:
        flash(f"Emails sent to {sent_count} participant(s).", "success")

    for name, reason in failed:
        flash(f"Failed to email {name}: {reason}", "danger")

    return sent_count, failed


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
    _emit_state(session_hash)
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
    _emit_state(session_hash)
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
    _emit_state(participant.session.hash_id)

    # Return JSON for fetch requests, redirect for normal form posts
    if request.headers.get("X-Requested-With") == "XMLHttpRequest" or \
       request.accept_mimetypes.accept_json:
        return jsonify({"ok": True})
    return redirect(url_for(
        "main.view_session",
        session_hash=participant.session.hash_id, token=token
    ))


@main.route("/session/<session_hash>/join_and_vote", methods=["POST"])
def join_and_vote(session_hash):
    """Join a session, save temp availability, and vote in one step."""
    game_session = Session.query.filter_by(hash_id=session_hash).first_or_404()
    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip()
    game_name = (request.form.get("game_name") or "").strip()
    temp_availability_raw = request.form.get("temp_availability", "[]")

    if not name:
        flash("Please enter your name.", "warning")
        return redirect(url_for("main.view_session", session_hash=session_hash))

    participant = Participant(name=name, email=email or None, session_id=game_session.id)
    db.session.add(participant)
    db.session.commit()

    if not game_session.host_id:
        game_session.host_id = participant.id
        db.session.commit()

    # Process Temp Availability
    try:
        temp_avail = json.loads(temp_availability_raw)
        for block in temp_avail:
            start_str = block.get("start", "").replace("Z", "+00:00")
            end_str = block.get("end", "").replace("Z", "+00:00")
            try:
                start_dt = strip_tz(datetime.fromisoformat(start_str))
                end_dt = strip_tz(datetime.fromisoformat(end_str))
                if start_dt < end_dt:
                    db.session.add(Availability(
                        session_id=game_session.id,
                        participant_id=participant.id,
                        start_time=start_dt,
                        end_time=end_dt
                    ))
            except ValueError:
                continue
    except (json.JSONDecodeError, TypeError):
        pass

    if game_name:
        vote = GameVote(
            session_id=game_session.id, participant_id=participant.id, game_name=game_name
        )
        db.session.add(vote)
        
    db.session.commit()
    
    # Notify user with their personal link
    spawn(notify_personal_link, current_app._get_current_object(), participant, game_session)
    
    flash("Thanks for joining! Your availability has been saved.", "success")
    _emit_state(session_hash)
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
    _emit_state(session_hash)
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
        _emit_state(session_hash)
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
        start_dt = strip_tz(datetime.fromisoformat(start_str))
        end_dt = strip_tz(datetime.fromisoformat(end_str))
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
    _emit_state(session_hash)
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
        start_dt = strip_tz(datetime.fromisoformat(start_str))  
        end_dt = strip_tz(datetime.fromisoformat(end_str))     
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
    _emit_state(session_hash)
    if is_xhr:
        return {"ok": True}

    flash("Availability removed.", "success")
    return redirect(url_for(
        "main.view_session", session_hash=session_hash, token=participant_token
    ))


# @main.route("/session/<session_hash>/availability_data")
# def availability_data(session_hash):
#     """Return live availability data as JSON for calendar polling."""
#     game_session = Session.query.filter_by(hash_id=session_hash).first_or_404()
#     grouped_json = {
#         p.name: [
#             {"start": b.start_time.isoformat(), "end": b.end_time.isoformat()}
#             for b in p.availabilities if b.start_time and b.end_time
#         ]
#         for p in game_session.participants
#     }
#     return jsonify(grouped_json)

def _session_state_hash(game_session):
    """
    Return a short hash that changes whenever any meaningful session state changes:
    availability blocks, game votes, chosen game, final time, confirmations,
    or the participant list itself.

    This is used by the SSE stream to decide whether to push an update.
    Cheap to compute — no extra DB queries beyond what's already loaded.
    """
    import hashlib  # noqa: PLC0415

    parts = []

    # Participant list + their availability
    for p in sorted(game_session.participants, key=lambda x: x.id):
        parts.append(f"p:{p.id}:{p.name}")
        for b in sorted(p.availabilities, key=lambda x: (x.start_time, x.end_time)):
            if b.start_time and b.end_time:
                parts.append(f"a:{b.start_time.isoformat()}:{b.end_time.isoformat()}")

    # Game votes
    from website.models import GameVote, Confirmation  # noqa: PLC0415
    from website import db  # noqa: PLC0415

    votes = GameVote.query.filter_by(session_id=game_session.id).order_by(
        GameVote.participant_id
    ).all()
    for v in votes:
        parts.append(f"v:{v.participant_id}:{v.game_name}")

    # Chosen game + final time
    parts.append(f"cg:{game_session.chosen_game}")
    parts.append(f"ft:{game_session.final_time}")

    # Confirmations
    confs = Confirmation.query.filter_by(session_id=game_session.id).order_by(
        Confirmation.participant_id
    ).all()
    for c in confs:
        parts.append(f"c:{c.participant_id}:{c.status}")

    return hashlib.md5("|".join(parts).encode()).hexdigest()[:12]


# ── Route 1: lightweight JSON state endpoint (replaces availability_data) ─────

@main.route("/session/<session_hash>/state")
def session_state(session_hash):
    """
    Return full live session state as JSON.
    Replaces /availability_data — now includes game tally, chosen game,
    final time, confirmations, and participant list alongside availability.
    """
    from flask import jsonify  # already imported in views.py  # noqa: PLC0415
    from website.models import GameVote, Confirmation  # noqa: PLC0415

    game_session = Session.query.filter_by(hash_id=session_hash).first_or_404()

    availability = {
        p.name: [
            {"start": b.start_time.isoformat(), "end": b.end_time.isoformat()}
            for b in p.availabilities
            if b.start_time and b.end_time
        ]
        for p in game_session.participants
    }

    votes = GameVote.query.filter_by(session_id=game_session.id).all()
    tally: dict = {}
    for v in votes:
        key = (v.game_name or "").strip().lower()
        display = (v.game_name or "").strip()
        tally[key] = {"name": display, "count": tally.get(key, {}).get("count", 0) + 1}
    game_tally = sorted(tally.values(), key=lambda x: -x["count"])

    confs = Confirmation.query.filter_by(session_id=game_session.id).all()
    conf_map = {}
    for c in confs:
        p = next(
            (x for x in game_session.participants if x.id == c.participant_id), None
        )
        if p:
            conf_map[p.name] = c.status

    return jsonify({
        "availability": availability,
        "game_tally": game_tally,
        "chosen_game": game_session.chosen_game,
        "final_time": (
            game_session.final_time.isoformat() if game_session.final_time else None
        ),
        "confirmations": conf_map,
        "participants": [p.name for p in game_session.participants],
        "state_hash": _session_state_hash(game_session),
    })


@main.route("/seed-test-data", methods=["POST"])
def seed_test_data():
    """Seed fake participants and sessions for metrics testing."""
    from datetime import datetime, timezone, timedelta
    from website.models import Participant, Session, Confirmation, Availability
    from sqlalchemy import text
    with db.engine.connect() as conn:
        conn.execute(text("UPDATE session SET host_id = NULL"))
        conn.commit()
    GameVote.query.delete()
    Confirmation.query.delete()
    Availability.query.delete()
    Participant.query.delete()
    Session.query.delete()
    db.session.commit()

    now = datetime.now(timezone.utc)

    # ── User A: repeat user (2 sessions, 3 days apart) ──────────────────
    s1 = Session(title="User A Session 1", is_public=True, datetime=now - timedelta(days=6))
    s2 = Session(title="User A Session 2", is_public=True, datetime=now - timedelta(days=3))
    db.session.add_all([s1, s2])
    db.session.flush()

    a1 = Participant(name="Alice", email="alice@test.com", session_id=s1.id)
    db.session.add(a1)
    db.session.flush()
    s1.host_id = a1.id

    a2 = Participant(name="Alice", email="alice@test.com", session_id=s2.id)
    db.session.add(a2)
    db.session.flush()
    s2.host_id = a2.id

    # ── User B: same-day activity only (should NOT count as repeat) ──────
    s3 = Session(title="User B Session", is_public=True, datetime=now - timedelta(hours=2))
    db.session.add(s3)
    db.session.flush()

    b1 = Participant(name="Bob", email="bob@test.com", session_id=s3.id)
    db.session.add(b1)
    db.session.flush()
    s3.host_id = b1.id

    c1 = Confirmation(participant_id=b1.id, session_id=s3.id, status="yes",
                      created_at=now - timedelta(hours=1))
    db.session.add(c1)

    # ── User C: activity 10 days apart (outside 7-day window, NOT repeat) 
    s4 = Session(title="User C Session 1", is_public=True, datetime=now - timedelta(days=12))
    s5 = Session(title="User C Session 2", is_public=True, datetime=now - timedelta(days=2))
    db.session.add_all([s4, s5])
    db.session.flush()

    c_p1 = Participant(name="Carol", email="carol@test.com", session_id=s4.id)
    db.session.add(c_p1)
    db.session.flush()
    s4.host_id = c_p1.id

    c_p2 = Participant(name="Carol", email="carol@test.com", session_id=s5.id)
    db.session.add(c_p2)
    db.session.flush()
    s5.host_id = c_p2.id

    # ── User D: joined but no activity (not activated) ───────────────────
    s6 = Session(title="Host Session", is_public=True, datetime=now)
    db.session.add(s6)
    db.session.flush()

    host = Participant(name="Host", email="host@test.com", session_id=s6.id)
    db.session.add(host)
    db.session.flush()
    s6.host_id = host.id

    d1 = Participant(name="Dave", email="dave@test.com", session_id=s6.id)
    db.session.add(d1)

    # ── User E: confirmed (activated, not repeat) ─────────────────────────
    e1 = Participant(name="Eve", email="eve@test.com", session_id=s6.id)
    db.session.add(e1)
    db.session.flush()

    conf_e = Confirmation(participant_id=e1.id, session_id=s6.id, status="yes",
                          created_at=now - timedelta(days=1))
    db.session.add(conf_e)

    db.session.commit()
    flash("Test data seeded.", "success")
    return redirect(url_for("main.dashboard"))

@main.route("/export-db")
def export_db():
    from flask import jsonify
    from website.models import Participant, Session, Confirmation, Availability, GameVote

    data = {
        "sessions": [
            {
                "id": s.id, "title": s.title, "hash_id": s.hash_id,
                "host_id": s.host_id, "final_time": s.final_time.isoformat() if s.final_time else None,
                "chosen_game": s.chosen_game, "is_public": s.is_public,
                "datetime": s.datetime.isoformat() if s.datetime else None,
            }
            for s in Session.query.all()
        ],
        "participants": [
            {
                "id": p.id, "name": p.name, "email": p.email,
                "session_id": p.session_id, "token": p.token,
            }
            for p in Participant.query.all()
        ],
        "availability": [
            {
                "id": a.id, "session_id": a.session_id, "participant_id": a.participant_id,
                "start_time": a.start_time.isoformat() if a.start_time else None,
                "end_time": a.end_time.isoformat() if a.end_time else None,
            }
            for a in Availability.query.all()
        ],
        "confirmations": [
            {
                "id": c.id, "session_id": c.session_id,
                "participant_id": c.participant_id, "status": c.status,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in Confirmation.query.all()
        ],
        "game_votes": [
            {
                "id": v.id, "session_id": v.session_id,
                "participant_id": v.participant_id, "game_name": v.game_name,
            }
            for v in GameVote.query.all()
        ],
    }
    return jsonify(data)

def _reset_sequences():
    """Reset PostgreSQL sequences after explicit-id inserts. No-op on SQLite."""
    if db.engine.dialect.name != "postgresql":
        return
    with db.engine.connect() as conn:
        for table, col in [
            ("session", "id"),
            ("participant", "id"),
            ("availability", "id"),
            ("confirmation", "id"),
            ("game_vote", "id"),
        ]:
            conn.execute(text(
                f"SELECT setval(pg_get_serial_sequence('{table}', '{col}'), "
                f"COALESCE((SELECT MAX({col}) FROM {table}), 0) + 1, false)"
            ))
        conn.commit()

@main.route("/import-db", methods=["GET", "POST"])
def import_db():
    if request.method == "GET":
        return '''
        <form method="POST" enctype="multipart/form-data">
            <input type="file" name="file" accept=".json" required>
            <button type="submit">Import</button>
        </form>
        '''

    f = request.files.get("file")
    if not f:
        return "No file uploaded", 400

    data = json.loads(f.read())
    with db.engine.connect() as conn:
        conn.execute(text("UPDATE session SET host_id = NULL"))
        conn.commit()

    # Clear existing data in dependency order
    GameVote.query.delete()
    Confirmation.query.delete()
    Availability.query.delete()
    Participant.query.delete()
    Session.query.delete()
    db.session.commit()

    # Insert sessions without host_id first
    for s in data.get("sessions", []):
        db.session.add(Session(
            id=s["id"], title=s["title"], hash_id=s["hash_id"],
            host_id=None,  # ← set to None initially
            chosen_game=s["chosen_game"],
            is_public=s["is_public"],
            final_time=datetime.fromisoformat(s["final_time"]) if s.get("final_time") else None,
            datetime=datetime.fromisoformat(s["datetime"]) if s.get("datetime") else None,
        ))
    db.session.commit()

    # Insert participants
    for p in data.get("participants", []):
        db.session.add(Participant(
            id=p["id"], name=p["name"], email=p["email"],
            session_id=p["session_id"], token=p["token"],
        ))
    db.session.commit()

    # Now update host_id now that participants exist
    for s in data.get("sessions", []):
        if s.get("host_id"):
            Session.query.filter_by(id=s["id"]).update({"host_id": s["host_id"]})
    db.session.commit()

    # Re-insert availability
    for a in data.get("availability", []):
        db.session.add(Availability(
            id=a["id"], session_id=a["session_id"], participant_id=a["participant_id"],
            start_time=datetime.fromisoformat(a["start_time"]) if a["start_time"] else None,
            end_time=datetime.fromisoformat(a["end_time"]) if a["end_time"] else None,
        ))
    db.session.commit()

    # Re-insert confirmations
    for c in data.get("confirmations", []):
        db.session.add(Confirmation(
            id=c["id"], session_id=c["session_id"],
            participant_id=c["participant_id"], status=c["status"],
            created_at=datetime.fromisoformat(c["created_at"]) if c.get("created_at") else None,
        ))

    # Re-insert game votes
    for v in data.get("game_votes", []):
        db.session.add(GameVote(
            id=v["id"], session_id=v["session_id"],
            participant_id=v["participant_id"], game_name=v["game_name"],
        ))
    db.session.commit()

    # Reset sequences to avoid primary key collisions after explicit-id inserts
    _reset_sequences()

    flash(f"Imported {len(data.get('sessions', []))} sessions and {len(data.get('participants', []))} participants.", "success")
    return redirect(url_for("main.dashboard"))

# ── EXPERIMENT ROUTES ────────────────────────────────────────────────────────

def _get_or_create_experiment_session():
    from website.models import ExperimentSession
    import json as _json
    import random
    from datetime import datetime, timezone, timedelta

    es = ExperimentSession.query.first()
    if es:
        return es

    # Start from today, end June 1st
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    end_date = datetime(2026, 6, 1, tzinfo=timezone.utc)

    people = ["Alex", "Jordan", "Sam", "Taylor"]
    
    # Common gaming windows (Start Hour, End Hour)
    base_slots = [
        (16, 18), (17, 19), (18, 20), 
        (19, 21), (20, 22), (21, 23)
    ]

    blocks = []
    current_day = now

    while current_day < end_date:
        # 1. Decide how many sessions happen this day (0 to 2 for realism)
        # We don't want people gaming every single day, maybe 70% chance of sessions
        if random.random() > 0.3:
            num_sessions = random.randint(1, 2)
            daily_slots = random.sample(base_slots, num_sessions)

            for start_h, end_h in daily_slots:
                start_dt = current_day.replace(hour=start_h)
                end_dt = current_day.replace(hour=end_h)

                # 2. Pick a group (2 to 4 people) who are "available" at this time
                # This creates the "overlap" the users need to find!
                group_size = random.choice([2, 3, 4])
                participants = random.sample(people, group_size)

                for person in participants:
                    blocks.append({
                        "person": person,
                        "start": start_dt.isoformat(),
                        "end": end_dt.isoformat()
                    })

        current_day += timedelta(days=1)

    es = ExperimentSession(
        title="Friday Night Games",
        availability_json=_json.dumps(blocks),
        chosen_game=None,
    )

    db.session.add(es)
    db.session.commit()

    return es


@main.route("/experiment")
def experiment_session():
    """Serve the controlled experiment page. No real session data used."""
    from website.models import ExperimentSession, ExperimentResult  # noqa: PLC0415
    import json as _json  # noqa: PLC0415

    link_token = request.args.get("link_token", "").strip()

    # Validate link token
    if not link_token:
        return render_template("experiment_invalid.html",
                               reason="missing"), 400

    import hmac as _hmac, hashlib as _hashlib  # noqa: PLC0415
    from website.models import ExperimentResult  # noqa: PLC0415

    # Ensure link_token column exists
    try:
        db.session.execute(text("ALTER TABLE experiment_result ADD COLUMN link_token VARCHAR(64)"))
        db.session.commit()
    except Exception:
        db.session.rollback()

    # Validate token signature: format is "CONDITION.nonce.sig"
    parts = link_token.split(".")
    if len(parts) != 3:
        return render_template("experiment_invalid.html", reason="invalid"), 404
    token_condition, nonce, sig = parts
    secret = current_app.config.get("SECRET_KEY", "dev")
    expected = _hmac.new(secret.encode(), f"{token_condition}:{nonce}".encode(), _hashlib.sha256).hexdigest()[:16]
    if not _hmac.compare_digest(sig, expected):
        return render_template("experiment_invalid.html", reason="invalid"), 404

    condition = token_condition.upper()
    if condition not in ("A", "B"):
        return render_template("experiment_invalid.html", reason="invalid"), 404

    # Check if already used
    row = db.session.execute(
        text("SELECT id, joined FROM experiment_result WHERE link_token = :token LIMIT 1"),
        {"token": link_token}
    ).fetchone()

    if row and row[1]:  # joined=True — link already consumed
        return render_template("experiment_invalid.html", reason="used"), 410

    es = _get_or_create_experiment_session()

    try:
        raw_blocks = _json.loads(es.availability_json)
    except (ValueError, TypeError):
        raw_blocks = []

    people = ["Alex", "Jordan", "Sam", "Taylor"]
    grouped_json = {p: [] for p in people}

    for b in raw_blocks:
        person = b.get("person")
        if person in grouped_json:
            grouped_json[person].append({
                "start": b["start"],
                "end": b["end"]
            })
    fake_tally = [["Valorant", 2], ["Minecraft", 1], ["Overwatch", 1], ["Apex Legends", 1]]

    return render_template(
        "experiment_session.html",
        experiment_session=es,
        condition=condition,
        link_token=link_token,
        grouped_json=grouped_json,
        grouped_availability=grouped_json,
        game_tally=fake_tally,
        confirmations={},
        rawg_key=current_app.config.get("RAWG_API_KEY", ""),
    )


@main.route("/experiment/join", methods=["POST"])
def experiment_join():
    """Record a join event. Creates participant in __experiment__ session."""
    from website.models import ExperimentSession, ExperimentResult  # noqa: PLC0415

    _ensure_game_election_schema()
    es = _get_or_create_experiment_session()
    condition = request.form.get("condition", "A").upper()
    time_to_join_ms = request.form.get("time_to_join_ms", type=int)
    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip()
    game_name = (request.form.get("game_name") or "").strip()
    temp_availability_raw = request.form.get("temp_availability", "[]")
    click_count = request.form.get("click_count", type=int, default=0)
    scroll_depth = request.form.get("scroll_depth", type=float, default=0.0)
    first_interaction_ms = request.form.get("first_interaction_ms", type=int, default=-1)
    used_calendar = request.form.get("used_calendar", type=int, default=0)
    typed_game = request.form.get("typed_game", type=int, default=0)
    calendar_block_count = request.form.get("calendar_block_count", type=int, default=0)
    calendar_section_ms = request.form.get("calendar_section_ms", type=int, default=0)
    game_section_ms = request.form.get("game_section_ms", type=int, default=0)
    time_to_calendar_ms = request.form.get("time_to_calendar_ms", type=int)
    time_to_game_ms = request.form.get("time_to_game_ms", type=int)
    rage_click_count = request.form.get("rage_click_count", type=int, default=0)
    form_focus_ms = request.form.get("form_focus_ms", type=int, default=0)
    nudge_hover = request.form.get("nudge_hover", type=int, default=0)

    if not name:
        flash("Please enter your name.", "warning")
        return redirect(url_for("main.experiment_session", condition=condition))

    exp_real_session = Session.query.filter_by(title="__experiment__").first()
    if not exp_real_session:
        exp_real_session = Session(title="__experiment__", is_public=False)
        db.session.add(exp_real_session)
        db.session.commit()

    participant = Participant(name=name, email=email or None, session_id=exp_real_session.id)
    db.session.add(participant)
    db.session.flush()

    try:
        temp_avail = json.loads(temp_availability_raw)
        for block in temp_avail:
            start_str = block.get("start", "").replace("Z", "+00:00")
            end_str = block.get("end", "").replace("Z", "+00:00")
            try:
                start_dt = strip_tz(datetime.fromisoformat(start_str))
                end_dt = strip_tz(datetime.fromisoformat(end_str))
                if start_dt < end_dt:
                    db.session.add(Availability(
                        session_id=exp_real_session.id,
                        participant_id=participant.id,
                        start_time=start_dt,
                        end_time=end_dt
                    ))
            except ValueError:
                continue
    except (json.JSONDecodeError, TypeError):
        pass

    if game_name:
        db.session.add(GameVote(
            session_id=exp_real_session.id,
            participant_id=participant.id,
            game_name=game_name
        ))

    link_token = request.form.get("link_token", "").strip()

    if link_token:
        result_row = db.session.execute(
            text("SELECT id FROM experiment_result WHERE link_token = :token AND joined = false LIMIT 1"),
            {"token": link_token}
        ).fetchone()
        if result_row:
            db.session.execute(
                text("""
                    UPDATE experiment_result 
                    SET participant_id = :pid, 
                        joined = true, 
                        time_to_join_ms = :ms,
                        click_count = :clicks,
                        scroll_depth = :scroll,
                        first_interaction_ms = :first_int,
                        used_calendar = :used_cal,
                        typed_game = :typed_g,
                        calendar_block_count = :cal_blocks,
                        calendar_section_ms = :cal_ms,
                        game_section_ms = :game_ms,
                        time_to_calendar_ms = :ttcal,
                        time_to_game_ms = :ttgame,
                        rage_click_count = :rage,
                        form_focus_ms = :focus_ms,
                        nudge_hover = :nudge
                    WHERE id = :rid
                """),
                {
                    "pid": participant.id, 
                    "ms": time_to_join_ms, 
                    "clicks": click_count,
                    "scroll": scroll_depth,
                    "first_int": first_interaction_ms,
                    "used_cal": bool(used_calendar),
                    "typed_g": bool(typed_game),
                    "cal_blocks": calendar_block_count,
                    "cal_ms": calendar_section_ms,
                    "game_ms": game_section_ms,
                    "ttcal": time_to_calendar_ms if time_to_calendar_ms and time_to_calendar_ms >= 0 else None,
                    "ttgame": time_to_game_ms if time_to_game_ms and time_to_game_ms >= 0 else None,
                    "rage": rage_click_count,
                    "focus_ms": form_focus_ms,
                    "nudge": bool(nudge_hover),
                    "rid": result_row[0]
                }
            )
    else:
        db.session.add(ExperimentResult(
            condition=condition,
            experiment_session_id=es.id,
            participant_id=participant.id,
            joined=True,
            time_to_join_ms=time_to_join_ms,
            click_count=click_count,
            scroll_depth=scroll_depth, 
            first_interaction_ms=first_interaction_ms,
            used_calendar=used_calendar,
            typed_game=typed_game,
            calendar_block_count=calendar_block_count,
            calendar_section_ms=calendar_section_ms,
            game_section_ms=game_section_ms,
            time_to_calendar_ms=time_to_calendar_ms if time_to_calendar_ms and time_to_calendar_ms >= 0 else None,
            time_to_game_ms=time_to_game_ms if time_to_game_ms and time_to_game_ms >= 0 else None,
            rage_click_count=rage_click_count,
            form_focus_ms=form_focus_ms,
            nudge_hover=bool(nudge_hover),
        ))
    db.session.commit()
    
    result_id = request.form.get("result_id")
    if not result_id:
        # fallback lookup
        result = ExperimentResult.query.filter_by(participant_id=participant.id).first()
        result_id = result.id if result else None

    flash("Thanks! Your response has been recorded.", "success")

    return redirect(url_for(
        "main.experiment_feedback",
        condition=condition,
        result_id = result.id if result else None
    ))

@main.route("/experiment/no_join", methods=["POST"])
def experiment_no_join():
    """Record an abandoned (non-join) event via sendBeacon."""
    from website.models import ExperimentSession, ExperimentResult  # noqa: PLC0415
    link_token = request.form.get("link_token", "").strip()
    elapsed = request.form.get("time_to_join_ms", type=int)
    click_count = request.form.get("click_count", type=int, default=0)
    scroll_depth = request.form.get("scroll_depth", type=float, default=0.0)
    first_interaction_ms = request.form.get("first_interaction_ms", type=int)
    used_calendar = request.form.get("used_calendar", type=int, default=0)
    typed_game = request.form.get("typed_game", type=int, default=0)
    calendar_block_count = request.form.get("calendar_block_count", type=int, default=0)
    calendar_section_ms = request.form.get("calendar_section_ms", type=int, default=0)
    game_section_ms = request.form.get("game_section_ms", type=int, default=0)
    time_to_calendar_ms = request.form.get("time_to_calendar_ms", type=int)
    time_to_game_ms = request.form.get("time_to_game_ms", type=int)
    rage_click_count = request.form.get("rage_click_count", type=int, default=0)
    form_focus_ms = request.form.get("form_focus_ms", type=int, default=0)
    nudge_hover = request.form.get("nudge_hover", type=int, default=0)

    if link_token:
        db.session.execute(
            text("""
                UPDATE experiment_result
                SET time_to_join_ms      = :ms,
                    click_count          = :clicks,
                    scroll_depth         = :scroll,
                    first_interaction_ms = :first_int,
                    used_calendar        = :used_cal,
                    typed_game           = :typed_g,
                    calendar_block_count = :cal_blocks,
                    calendar_section_ms  = :cal_ms,
                    game_section_ms      = :game_ms,
                    time_to_calendar_ms  = :ttcal,
                    time_to_game_ms      = :ttgame,
                    rage_click_count     = :rage,
                    form_focus_ms        = :focus_ms,
                    nudge_hover          = :nudge
                WHERE link_token = :token AND joined = false
            """),
            {
                "ms": elapsed,
                "clicks": click_count,
                "scroll": scroll_depth,
                "first_int": first_interaction_ms if first_interaction_ms and first_interaction_ms >= 0 else None,
                "used_cal": bool(used_calendar),
                "typed_g": bool(typed_game),
                "cal_blocks": calendar_block_count,
                "cal_ms": calendar_section_ms,
                "game_ms": game_section_ms,
                "ttcal": time_to_calendar_ms if time_to_calendar_ms and time_to_calendar_ms >= 0 else None,
                "ttgame": time_to_game_ms if time_to_game_ms and time_to_game_ms >= 0 else None,
                "rage": rage_click_count,
                "focus_ms": form_focus_ms,
                "nudge": bool(nudge_hover),
                "token": link_token,
            }
        )
        db.session.commit()
    else:
        # Fallback: no token
        es = ExperimentSession.query.first()
        db.session.add(ExperimentResult(
            condition=request.form.get("condition", "A").upper(),
            experiment_session_id=es.id if es else None,
            participant_id=None,
            joined=False,
            time_to_join_ms=elapsed,
            click_count=click_count,
            scroll_depth=scroll_depth,
            first_interaction_ms=first_interaction_ms if first_interaction_ms and first_interaction_ms >= 0 else None,
            used_calendar=bool(used_calendar),
            typed_game=bool(typed_game),
            calendar_block_count=calendar_block_count,
            calendar_section_ms=calendar_section_ms,
            game_section_ms=game_section_ms,
            time_to_calendar_ms=time_to_calendar_ms if time_to_calendar_ms and time_to_calendar_ms >= 0 else None,
            time_to_game_ms=time_to_game_ms if time_to_game_ms and time_to_game_ms >= 0 else None,
            rage_click_count=rage_click_count,
            form_focus_ms=form_focus_ms,
            nudge_hover=bool(nudge_hover),
        ))
        db.session.commit()
    return jsonify({"ok": True})


@main.route("/experiment/export")
def experiment_export():
    """Export experiment results as CSV or JSON."""
    from website.models import ExperimentResult  # noqa: PLC0415
    import csv, io  # noqa: PLC0415
    from flask import Response  # noqa: PLC0415

    fmt = request.args.get("format", "csv").lower()
    results = ExperimentResult.query.order_by(ExperimentResult.created_at).all()

    if fmt == "json":
        data = [{
            "id": r.id,
            "condition": r.condition,
            "participant_id": r.participant_id,
            "joined": r.joined,
            "time_to_join_ms": r.time_to_join_ms,
            "click_count": r.click_count,
            "scroll_depth": r.scroll_depth,
            "first_interaction_ms": r.first_interaction_ms,
            "used_calendar": r.used_calendar,
            "typed_game": r.typed_game,
            "calendar_block_count": getattr(r, 'calendar_block_count', None),
            "calendar_section_ms": getattr(r, 'calendar_section_ms', None),
            "game_section_ms": getattr(r, 'game_section_ms', None),
            "time_to_calendar_ms": getattr(r, 'time_to_calendar_ms', None),
            "time_to_game_ms": getattr(r, 'time_to_game_ms', None),
            "rage_click_count": getattr(r, 'rage_click_count', None),
            "form_focus_ms": getattr(r, 'form_focus_ms', None),
            "nudge_hover": getattr(r, 'nudge_hover', None),
            "ease_of_use": getattr(r, 'ease_of_use', None),
            "layout_clarity": getattr(r, 'layout_clarity', None),
            "noticed_first": getattr(r, 'noticed_first', None),
            "real_use_likelihood": getattr(r, 'real_use_likelihood', None),
            "feedback_text": getattr(r, 'feedback_text', None),
            "created_at": r.created_at.isoformat() if r.created_at else None,
        } for r in results]
        return Response(json.dumps(data, indent=2), mimetype="application/json",
                        headers={"Content-Disposition": "attachment; filename=experiment_results.json"})

    EXPORT_FIELDS = [
        "id", "condition", "participant_id", "joined",
        "time_to_join_ms", "click_count", "scroll_depth", "first_interaction_ms",
        "used_calendar", "typed_game",
        "calendar_block_count", "calendar_section_ms", "game_section_ms",
        "time_to_calendar_ms", "time_to_game_ms",
        "rage_click_count", "form_focus_ms", "nudge_hover",
        "ease_of_use", "layout_clarity", "noticed_first",
        "real_use_likelihood", "feedback_text", "created_at",
    ]
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(EXPORT_FIELDS)
    for r in results:
        w.writerow([
            r.id, r.condition, r.participant_id, r.joined,
            r.time_to_join_ms, r.click_count, r.scroll_depth, r.first_interaction_ms,
            r.used_calendar, r.typed_game,
            getattr(r, 'calendar_block_count', None),
            getattr(r, 'calendar_section_ms', None),
            getattr(r, 'game_section_ms', None),
            getattr(r, 'time_to_calendar_ms', None),
            getattr(r, 'time_to_game_ms', None),
            getattr(r, 'rage_click_count', None),
            getattr(r, 'form_focus_ms', None),
            getattr(r, 'nudge_hover', None),
            getattr(r, 'ease_of_use', None),
            getattr(r, 'layout_clarity', None),
            getattr(r, 'noticed_first', None),
            getattr(r, 'real_use_likelihood', None),
            getattr(r, 'feedback_text', None),
            r.created_at.isoformat() if r.created_at else "",
        ])
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=experiment_results.csv"})


@main.route("/experiment/reset_participants", methods=["POST"])
def experiment_reset_participants():
    """Delete participants from the experiment session only. Keeps result rows."""
    from website.models import ExperimentResult  # noqa: PLC0415
    exp_session = Session.query.filter_by(title="__experiment__").first()
    if exp_session:
        # Null out FK references before deleting participants so result rows
        # (and their timing data) are preserved.
        db.session.execute(
            text("UPDATE experiment_result SET participant_id = NULL WHERE participant_id IN "
                 "(SELECT id FROM participant WHERE session_id = :sid)"),
            {"sid": exp_session.id}
        )
        GameVote.query.filter_by(session_id=exp_session.id).delete()
        Availability.query.filter_by(session_id=exp_session.id).delete()
        Participant.query.filter_by(session_id=exp_session.id).delete()
        db.session.commit()
    flash("Experiment participants cleared — results kept.", "success")
    return redirect(url_for("main.dashboard"))


@main.route("/experiment/reset_all", methods=["POST"])
def experiment_reset_all():
    """Full reset: delete participants AND all result rows."""
    from website.models import ExperimentResult  # noqa: PLC0415
    # Delete result rows first — they hold a FK to participant
    deleted = ExperimentResult.query.delete()
    exp_session = Session.query.filter_by(title="__experiment__").first()
    if exp_session:
        GameVote.query.filter_by(session_id=exp_session.id).delete()
        Availability.query.filter_by(session_id=exp_session.id).delete()
        Participant.query.filter_by(session_id=exp_session.id).delete()
    db.session.commit()
    flash(f"Full reset — {deleted} result(s) deleted.", "success")
    return redirect(url_for("main.dashboard"))


@main.route("/experiment/results")
def experiment_results():
    """JSON endpoint for dashboard live panel."""
    from website.models import ExperimentResult  # noqa: PLC0415
    results = ExperimentResult.query.order_by(ExperimentResult.created_at).all()
    def serialize_result(r):
        return {
            "id": r.id,
            "condition": r.condition,
            "joined": r.joined,
            "time_to_join_ms": r.time_to_join_ms,
            "click_count": r.click_count,
            "scroll_depth": r.scroll_depth,
            "first_interaction_ms": r.first_interaction_ms,
            "used_calendar": r.used_calendar,
            "typed_game": r.typed_game,
            "calendar_block_count": getattr(r, 'calendar_block_count', None),
            "calendar_section_ms": getattr(r, 'calendar_section_ms', None),
            "game_section_ms": getattr(r, 'game_section_ms', None),
            "time_to_calendar_ms": getattr(r, 'time_to_calendar_ms', None),
            "time_to_game_ms": getattr(r, 'time_to_game_ms', None),
            "rage_click_count": getattr(r, 'rage_click_count', None),
            "form_focus_ms": getattr(r, 'form_focus_ms', None),
            "nudge_hover": getattr(r, 'nudge_hover', None),
            "ease_of_use": getattr(r, 'ease_of_use', None),
            "layout_clarity": getattr(r, 'layout_clarity', None),
            "noticed_first": getattr(r, 'noticed_first', None),
            "real_use_likelihood": getattr(r, 'real_use_likelihood', None),
            "feedback_text": getattr(r, 'feedback_text', None),
            "created_at": r.created_at.isoformat() if r.created_at else None
        }
    return jsonify([serialize_result(r) for r in results])


@main.route("/experiment/generate_link", methods=["POST"])
def experiment_generate_link():
    """Return a signed token for a single-use experiment link. No DB write yet —
    the result row is created when the participant actually opens the link."""
    import secrets as _secrets  # noqa: PLC0415
    import hmac as _hmac, hashlib as _hashlib  # noqa: PLC0415

    condition = (request.json or request.form).get("condition", "A").upper()
    if condition not in ("A", "B"):
        condition = "A"

    nonce = _secrets.token_urlsafe(18)
    secret = current_app.config.get("SECRET_KEY", "dev")
    sig = _hmac.new(secret.encode(), f"{condition}:{nonce}".encode(), _hashlib.sha256).hexdigest()[:16]
    link_token = f"{condition}.{nonce}.{sig}"

    return jsonify({"link_token": link_token, "condition": condition})

@main.route("/experiment/consent", methods=["POST"])
def experiment_consent():
    """Create the pending result row only after consent is confirmed."""
    from website.models import ExperimentSession, ExperimentResult  # noqa: PLC0415
    import json as _json  # noqa: PLC0415

    link_token = (request.json or request.form).get("link_token", "").strip()
    condition = (request.json or request.form).get("condition", "A").upper()

    if not link_token:
        return jsonify({"ok": False, "error": "no token"}), 400

    es = _get_or_create_experiment_session()

    # Only insert if not already present (idempotent)
    existing = db.session.execute(
        text("SELECT id FROM experiment_result WHERE link_token = :token LIMIT 1"),
        {"token": link_token}
    ).fetchone()

    if not existing:
        from datetime import timezone as _tz  # noqa: PLC0415
        now = datetime.now(_tz.utc).isoformat()
        db.session.execute(
            text("INSERT INTO experiment_result (condition, experiment_session_id, participant_id, joined, link_token, time_to_join_ms, created_at) VALUES (:cond, :es_id, NULL, false, :token, NULL, :now)"),
            {"cond": condition, "es_id": es.id, "token": link_token, "now": now}
        )
        db.session.commit()

    return jsonify({"ok": True})

@main.route("/fix-sequences")
def fix_sequences():
    _reset_sequences()
    return "Sequences fixed!"

@main.route("/cleanup-db")
def cleanup_db():
    junk_session_ids = [21, 22, 23, 24, 25, 26]
    for sid in junk_session_ids:
        s = Session.query.get(sid)
        if s:
            db.session.delete(s)
    db.session.commit()
    _reset_sequences()
    return "Done! Junk sessions deleted and sequences fixed."

@main.route("/feedback/data")
def feedback_data():
    """JSON endpoint — all general feedback rows for the dashboard."""
    rows = Feedback.query.order_by(Feedback.created_at).all()
    return jsonify([{
        "id": f.id,
        "ease_of_use": f.ease_of_use,
        "improvement": f.improvement,
        "accomplished_goal": f.accomplished_goal,
        "return_likelihood": f.return_likelihood,
        "recommend_likelihood": f.recommend_likelihood,
        "additional_comments": f.additional_comments,
        "created_at": f.created_at.isoformat() if f.created_at else None,
    } for f in rows])


@main.route("/submit-feedback", methods=["POST"])
def submit_feedback():
    """Handle feedback form submission from the footer modal."""
    ease_of_use = request.form.get("ease_of_use")
    improvement = request.form.get("improvement")
    accomplished_goal = request.form.get("accomplished_goal")
    return_likelihood = request.form.get("return_likelihood")
    recommend_likelihood = request.form.get("recommend_likelihood")
    additional_comments = request.form.get("additional_comments")

    # 1. Save to Database
    feedback = Feedback(
        ease_of_use=int(ease_of_use) if ease_of_use and ease_of_use.isdigit() else None,
        improvement=improvement,
        accomplished_goal=accomplished_goal,
        return_likelihood=int(return_likelihood) if return_likelihood and return_likelihood.isdigit() else None,
        recommend_likelihood=int(recommend_likelihood) if recommend_likelihood and recommend_likelihood.isdigit() else None,
        additional_comments=additional_comments
    )   
    db.session.add(feedback)
    db.session.commit()

    # 2. Send Email
    feedback_data = {
        "ease_of_use": ease_of_use,
        "improvement": improvement,
        "accomplished_goal": accomplished_goal,
        "return_likelihood": return_likelihood,
        "recommend_likelihood": recommend_likelihood,
        "additional_comments": additional_comments
    }
    spawn(notify_feedback_submitted, feedback_data)

    flash("Thank you for your feedback! It helps us improve SynQ.", "success")
    
    return redirect(url_for("main.index"))

@main.route("/experiment/submit_feedback", methods=["POST"])
def submit_experiment_feedback():
    """Save experiment-specific feedback tied to an ExperimentResult row."""
    from website.models import ExperimentResult  # noqa: PLC0415

    result_id = request.form.get("result_id", type=int)
    ease_of_use = request.form.get("ease_of_use")
    layout_clarity = request.form.get("layout_clarity")
    noticed_first = request.form.get("noticed_first")
    real_use_likelihood = request.form.get("real_use_likelihood")
    improvement = request.form.get("improvement", "").strip()

    if result_id:
        db.session.execute(
            text("""
                UPDATE experiment_result
                SET ease_of_use         = :ease,
                    layout_clarity      = :clarity,
                    noticed_first       = :noticed,
                    real_use_likelihood = :likelihood,
                    feedback_text       = :improvement
                WHERE id = :rid
            """),
            {
                "ease": int(ease_of_use) if ease_of_use and ease_of_use.isdigit() else None,
                "clarity": int(layout_clarity) if layout_clarity and layout_clarity.isdigit() else None,
                "noticed": noticed_first,
                "likelihood": int(real_use_likelihood) if real_use_likelihood and real_use_likelihood.isdigit() else None,
                "improvement": improvement or None,
                "rid": result_id,
            }
        )
        db.session.commit()

    flash("Thanks for the feedback!", "success")
    return redirect(url_for("main.index"))


@main.route("/experiment/feedback")
def experiment_feedback():
    from website.models import ExperimentResult  # import fixed

    result_id = request.args.get("result_id", type=int)

    if not result_id:
        return redirect(url_for("main.index"))

    result = ExperimentResult.query.get(result_id)
    if not result:
        return redirect(url_for("main.index"))

    return render_template(
        "experiment_feedback.html",
        condition=result.condition,
        result_id=result.id,
    )