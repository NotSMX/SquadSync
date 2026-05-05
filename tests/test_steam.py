"""
test_steam.py

Unit tests for steam.py — resolve_steam_id() and get_steam_games()
"""

import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _mock_response(json_data: dict, raise_for_status: bool = False):
    mock = MagicMock()
    mock.json.return_value = json_data
    if raise_for_status:
        mock.raise_for_status.side_effect = Exception("HTTP Error")
    else:
        mock.raise_for_status.return_value = None
    return mock


# ===========================================================================
# resolve_steam_id
# ===========================================================================

class TestResolveSteamId:

    KEY = "FAKE_KEY"

    def test_numeric_steam64_returned_directly(self):
        from website.steam import resolve_steam_id
        assert resolve_steam_id("76561198012345678", self.KEY) == "76561198012345678"

    def test_numeric_steam64_with_whitespace(self):
        from website.steam import resolve_steam_id
        assert resolve_steam_id("  76561198012345678  ", self.KEY) == "76561198012345678"

    def test_short_number_not_treated_as_steam64(self):
        from website.steam import resolve_steam_id
        with patch("website.steam.requests.get") as mock_get:
            mock_get.return_value = _mock_response({"response": {"success": 42}})
            assert resolve_steam_id("1234567", self.KEY) is None

    def test_profiles_url_with_numeric_id(self):
        from website.steam import resolve_steam_id
        url = "https://steamcommunity.com/profiles/76561198012345678"
        assert resolve_steam_id(url, self.KEY) == "76561198012345678"

    def test_profiles_url_trailing_slash(self):
        from website.steam import resolve_steam_id
        url = "https://steamcommunity.com/profiles/76561198012345678/"
        assert resolve_steam_id(url, self.KEY) == "76561198012345678"

    def test_profiles_url_non_numeric_falls_through_to_vanity(self):
        from website.steam import resolve_steam_id
        with patch("website.steam.requests.get") as mock_get:
            mock_get.return_value = _mock_response({"response": {"success": 42}})
            assert resolve_steam_id(
                "https://steamcommunity.com/profiles/notanumber", self.KEY
            ) is None

    def test_vanity_url_resolved_successfully(self):
        from website.steam import resolve_steam_id
        with patch("website.steam.requests.get") as mock_get:
            mock_get.return_value = _mock_response({
                "response": {"success": 1, "steamid": "76561198099999999"}
            })
            result = resolve_steam_id("https://steamcommunity.com/id/myvanity", self.KEY)
        assert result == "76561198099999999"
        assert mock_get.call_args[1]["params"]["vanityurl"] == "myvanity"

    def test_vanity_url_trailing_slash(self):
        from website.steam import resolve_steam_id
        with patch("website.steam.requests.get") as mock_get:
            mock_get.return_value = _mock_response({
                "response": {"success": 1, "steamid": "76561198099999999"}
            })
            resolve_steam_id("https://steamcommunity.com/id/myvanity/", self.KEY)
        assert mock_get.call_args[1]["params"]["vanityurl"] == "myvanity"

    def test_vanity_url_not_found(self):
        from website.steam import resolve_steam_id
        with patch("website.steam.requests.get") as mock_get:
            mock_get.return_value = _mock_response({"response": {"success": 42}})
            assert resolve_steam_id("https://steamcommunity.com/id/nobody", self.KEY) is None

    def test_raw_vanity_name_resolved(self):
        from website.steam import resolve_steam_id
        with patch("website.steam.requests.get") as mock_get:
            mock_get.return_value = _mock_response({
                "response": {"success": 1, "steamid": "76561198011111111"}
            })
            result = resolve_steam_id("gaben", self.KEY)
        assert result == "76561198011111111"
        assert mock_get.call_args[1]["params"]["vanityurl"] == "gaben"

    def test_raw_vanity_name_not_found(self):
        from website.steam import resolve_steam_id
        with patch("website.steam.requests.get") as mock_get:
            mock_get.return_value = _mock_response({"response": {"success": 42}})
            assert resolve_steam_id("doesnotexist", self.KEY) is None


# ===========================================================================
# get_steam_games
# ===========================================================================

class TestGetSteamGames:

    STEAM_ID = "76561198012345678"
    KEY = "FAKE_KEY"

    def _patch(self, recent_json, owned_json):
        return patch("website.steam.requests.get", side_effect=[
            _mock_response(recent_json),
            _mock_response(owned_json),
        ])

    def test_returns_all_three_keys(self):
        from website.steam import get_steam_games
        with self._patch({"response": {"games": []}}, {"response": {"games": []}}):
            result = get_steam_games(self.STEAM_ID, self.KEY)
        assert set(result.keys()) == {"recent_games", "top_games", "all_names"}

    def test_recent_games_extracted(self):
        from website.steam import get_steam_games
        with self._patch(
            {"response": {"games": [{"name": "Game A"}, {"name": "Game B"}]}},
            {"response": {"games": []}},
        ):
            result = get_steam_games(self.STEAM_ID, self.KEY)
        assert result["recent_games"] == ["Game A", "Game B"]

    def test_top_games_sorted_by_playtime(self):
        from website.steam import get_steam_games
        owned = [
            {"name": "Low",  "playtime_forever": 10},
            {"name": "High", "playtime_forever": 9999},
            {"name": "Mid",  "playtime_forever": 500},
        ]
        with self._patch({"response": {"games": []}}, {"response": {"games": owned}}):
            result = get_steam_games(self.STEAM_ID, self.KEY, top_n=2)
        assert result["top_games"] == ["High", "Mid"]

    def test_top_n_limits_results(self):
        from website.steam import get_steam_games
        owned = [{"name": f"Game {i}", "playtime_forever": i} for i in range(10, 0, -1)]
        with self._patch({"response": {"games": []}}, {"response": {"games": owned}}):
            result = get_steam_games(self.STEAM_ID, self.KEY, top_n=3)
        assert len(result["top_games"]) == 3

    def test_all_names_lowercased(self):
        from website.steam import get_steam_games
        owned = [{"name": "Counter-Strike 2", "playtime_forever": 100}]
        with self._patch({"response": {"games": []}}, {"response": {"games": owned}}):
            result = get_steam_games(self.STEAM_ID, self.KEY)
        assert "counter-strike 2" in result["all_names"]
        assert "Counter-Strike 2" not in result["all_names"]

    def test_games_without_name_skipped(self):
        from website.steam import get_steam_games
        owned = [
            {"appid": 730, "playtime_forever": 9999},         # no "name"
            {"name": "Valve Game", "playtime_forever": 100},
        ]
        with self._patch({"response": {"games": []}}, {"response": {"games": owned}}):
            result = get_steam_games(self.STEAM_ID, self.KEY)
        assert result["top_games"] == ["Valve Game"]
        assert "valve game" in result["all_names"]

    def test_empty_library(self):
        from website.steam import get_steam_games
        with self._patch({"response": {}}, {"response": {}}):
            result = get_steam_games(self.STEAM_ID, self.KEY)
        assert result == {"recent_games": [], "top_games": [], "all_names": set()}

    def test_http_error_on_recent_raises(self):
        from website.steam import get_steam_games
        with patch("website.steam.requests.get", return_value=_mock_response({}, raise_for_status=True)):
            with pytest.raises(Exception, match="HTTP Error"):
                get_steam_games(self.STEAM_ID, self.KEY)

    def test_http_error_on_owned_raises(self):
        from website.steam import get_steam_games
        with patch("website.steam.requests.get", side_effect=[
            _mock_response({"response": {"games": []}}),
            _mock_response({}, raise_for_status=True),
        ]):
            with pytest.raises(Exception, match="HTTP Error"):
                get_steam_games(self.STEAM_ID, self.KEY)