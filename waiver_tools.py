import json
from collections import Counter
from pathlib import Path
from agents import function_tool


AVAILABLE_PLAYERS_FILE = (
    Path(__file__).parent / "data" / "available_players.json"
)


def load_available_players():
    with open(AVAILABLE_PLAYERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def build_available_player_summary():
    data = load_available_players()
    players = data.get("players", [])

    positions = sorted(set(p.get("position", "UNKNOWN") for p in players))

    by_position = {}

    for position in positions:
        position_players = [
            p for p in players
            if p.get("position") == position
        ]

        by_position[position] = {
            "total": len(position_players),
            "free_agents": sum(
                1 for p in position_players
                if p.get("availability") == "FA"
            ),
            "waivers": sum(
                1 for p in position_players
                if p.get("availability") == "W"
            ),
        }

    return {
        "last_updated": data.get("last_updated"),
        "total_players": len(players),
        "free_agents": sum(
            1 for p in players
            if p.get("availability") == "FA"
        ),
        "waivers": sum(
            1 for p in players
            if p.get("availability") == "W"
        ),
        "by_position": by_position,
    }


@function_tool
def get_available_players() -> str:
    """
    Return players currently available in my Yahoo Fantasy Football league
    for waiver-wire and free-agent analysis.
    """
    return json.dumps(load_available_players(), indent=2)


@function_tool
def get_available_player_summary() -> str:
    """
    Return exact deterministic counts of currently available fantasy players,
    including totals by position and free-agent versus waiver status.
    """
    return json.dumps(build_available_player_summary(), indent=2)