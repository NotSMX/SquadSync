import requests

STEAM_API_BASE = "https://api.steampowered.com"

def resolve_steam_id(steam_input: str, api_key: str) -> str | None:
    """
    Accepts a Steam64 ID, a full profile URL, or a vanity name.
    Returns the Steam64 ID string, or None on failure.
    """
    steam_input = steam_input.strip().rstrip("/")

    # Already a numeric Steam64 ID
    if steam_input.isdigit() and len(steam_input) == 17:
        return steam_input

    # Extract vanity name from URL
    # e.g. https://steamcommunity.com/id/somename  or  https://steamcommunity.com/profiles/76561198...
    if "steamcommunity.com/profiles/" in steam_input:
        candidate = steam_input.split("steamcommunity.com/profiles/")[-1].strip("/")
        if candidate.isdigit():
            return candidate

    if "steamcommunity.com/id/" in steam_input:
        vanity = steam_input.split("steamcommunity.com/id/")[-1].strip("/")
    else:
        vanity = steam_input  # treat raw input as vanity name

    resp = requests.get(
        f"{STEAM_API_BASE}/ISteamUser/ResolveVanityURL/v1/",
        params={"key": api_key, "vanityurl": vanity},
        timeout=10,
    )
    data = resp.json().get("response", {})
    if data.get("success") == 1:
        return data["steamid"]
    return None


def get_steam_games(steam_id: str, api_key: str, top_n: int = 5) -> dict:
    """
    Returns:
      {
        "recent_games": ["Game A", "Game B", ...],  # played in last 2 weeks
        "top_games":    ["Game A", "Game B", ...],  # top N by all-time playtime
        "all_names":    {"game a", "game b", ...}   # full owned set (lowercase)
      }
    """
    # Recently played (last 2 weeks) — strongest signal
    recent_resp = requests.get(
        f"{STEAM_API_BASE}/IPlayerService/GetRecentlyPlayedGames/v1/",
        params={"key": api_key, "steamid": steam_id, "count": 10},
        timeout=15,
    )
    recent_resp.raise_for_status()
    recent_games = [
        g["name"] for g in recent_resp.json().get("response", {}).get("games", [])
        if "name" in g
    ]

    # Full library — for ownership matching
    owned_resp = requests.get(
        f"{STEAM_API_BASE}/IPlayerService/GetOwnedGames/v1/",
        params={
            "key": api_key,
            "steamid": steam_id,
            "include_appinfo": True,
            "include_played_free_games": True,
        },
        timeout=15,
    )
    owned_resp.raise_for_status()
    owned = owned_resp.json().get("response", {}).get("games", [])
    owned.sort(key=lambda g: g.get("playtime_forever", 0), reverse=True)

    top_games = [g["name"] for g in owned[:top_n] if "name" in g]
    all_names = {g["name"].lower() for g in owned if "name" in g}

    return {"recent_games": recent_games, "top_games": top_games, "all_names": all_names}