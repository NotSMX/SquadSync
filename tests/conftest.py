"""
conftest.py

This module contains pytest fixtures for setting up the Flask test environment
and mocking API calls with fake functions.
"""
import pytest
from website import create_app, views

# -----------------------------
# Fake data
# -----------------------------
fake_weather_data = {
    "temp": 70,
    "feels_like": 68,
    "description": "Clear Sky",
    "icon": "01d",
    "wind": 5,
    "humidity": 40,
    "pressure": 1012,
    "visibility": 10,
    "dew_point": 45,
    "city": "London",
    "state": "N/A",
    "country": "GB",
}

fake_forecast = [
    {
        "date": "2026-02-09",
        "day_name": "Monday",
        "temp_min": 50,
        "temp_max": 70,
        "description": "Clear Sky",
        "icon": "01d",
    }
] * 5

# -----------------------------
# Fake functions
# -----------------------------
def fake_fetch_weather(_lat, _lon):
    """Return fake weather data regardless of input coordinates."""
    return fake_weather_data

def fake_geocode_city(_city, _state, _country):
    """Return fixed coordinates for any city input."""
    return 51.5074, -0.1278

def fake_fetch_5day_forecast(_lat, _lon):
    """Return a fake 5-day forecast regardless of input coordinates."""
    return fake_forecast

def fake_reverse_geocode(_lat, _lon):
    """Return fixed location data for any input coordinates."""
    return {"city": "London", "state": "N/A", "country": "GB"}

# -----------------------------
# Fixtures
# -----------------------------
@pytest.fixture
def test_client():
    """
    Create a Flask test client and monkey-patch API calls with fakes.
    """
    app = create_app()
    app.config["TESTING"] = True

    views.fetch_weather = fake_fetch_weather
    views.geocode_city = fake_geocode_city
    views.reverse_geocode = fake_reverse_geocode
    views.fetch_5day_forecast = fake_fetch_5day_forecast

    with app.test_client() as client:
        yield client
