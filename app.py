"""
app.py

This is the main entry point for the Flask application. It creates and runs the app.
"""

from website import create_app

app = create_app()

if __name__ == '__main__':
    app.run(debug=True)
