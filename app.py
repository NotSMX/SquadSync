"""
app.py

This is the main entry point for the Flask application. It creates and runs the app.
"""
import os

from website import create_app, socketio

app = create_app()

if __name__ == '__main__':
    # PORT from env (Heroku). Default 5001: macOS often reserves 5000 for AirPlay Receiver.
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", debug=True, port=port)
