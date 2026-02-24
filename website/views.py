"""
views.py

This module contains the Flask view functions for handling routes and rendering templates.
"""
from flask import Blueprint, app, render_template, redirect, url_for, request
from flask import session as flask_session
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash
from website import db
from website.models import User, Session, Availability
from datetime import datetime
import uuid

main = Blueprint("main", __name__)

@main.route("/")
def index():
    return render_template("base.html")

@main.route("/create", methods=["GET", "POST"])
def create_session():
    if request.method == "POST":
        title = request.form["title"]
        dt = datetime.strptime(request.form["datetime"], "%Y-%m-%dT%H:%M")

        session = Session(title=title, datetime=dt)
        db.session.add(session)
        db.session.commit()

        return redirect(url_for("main.view_session", session_id=session.id))

    return render_template("create_session.html")

@main.route("/session/<int:session_id>", methods=["GET", "POST"])
@login_required
def view_session(session_id):
    session = Session.query.get_or_404(session_id)

    if request.method == "POST":
        response = request.form.get("response")

        availability = Availability.query.filter_by(
            session_id=session.id,
            user_id=current_user.id
        ).first()

        if availability:
            availability.response = response
        else:
            availability = Availability(
                session_id=session.id,
                user_id=current_user.id,
                response=response
            )
            db.session.add(availability)

        db.session.commit()

    participants = Availability.query.filter_by(session_id=session.id).all()

    return render_template(
        "session.html",
        session=session,
        participants=participants
    )

@main.route("/sessions")
@login_required
def list_sessions():
    # Fetch all sessions, order by datetime
    sessions = Session.query.order_by(Session.datetime.asc()).all()
    
    # Prepare data for template (e.g., participant counts or RSVP status if desired)
    session_data = []
    for s in sessions:
        participants = Availability.query.filter_by(session_id=s.id).all()
        session_data.append({
            "session": s,
            "participants": participants
        })

    return render_template("sessions.html", sessions=session_data)

@main.route("/dashboard")
@login_required
def dashboard():
    from website.metrics import calculate_metrics
    metrics = calculate_metrics()
    return render_template("dashboard.html", metrics=metrics)

@main.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form["username"]
        email = request.form["email"]

        # link this user to the anonymous session
        user_id = flask_session["user_id"]

        # save in database
        user = User(
            anonymous_id=user_id,
            username=username,
            email=email
        )
        db.session.add(user)
        db.session.commit()

        flask_session["signed_up"] = True
        return redirect(url_for("main.dashboard"))

    return render_template("signup.html")

@main.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        user = User(username=username)
        user.set_password(password)

        db.session.add(user)
        db.session.commit()

        login_user(user)
        return redirect(url_for("main.dashboard"))

    return render_template("register.html")

@main.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for("main.dashboard"))

    return render_template("login.html")


@main.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("main.login"))