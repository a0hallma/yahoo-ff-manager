import json
from collections import Counter
from pathlib import Path

from agents import function_tool

from provider_context import (
    get_current_provider,
    get_provider_display_name,
)


DATA_DIR = Path(__file__).parent / "data"

LEAGUE_ROSTER_FILES = {
    "sleeper": DATA_DIR / "sleeper_league_rosters.json",
}


def load_league_rosters():
    """
    Load league-wide roster data for the currently selected
    fantasy provider.

    Sleeper is currently supported.

    Yahoo will be added once live Yahoo league-wide roster
    data is available.
    """

    provider = get_current_provider()
    provider_name = get_provider_display_name()

    roster_file = LEAGUE_ROSTER_FILES.get(
        provider
    )

    if roster_file is None:
        raise RuntimeError(
            f"League-wide roster data is not yet available "
            f"for {provider_name}."
        )

    if not roster_file.exists():
        raise RuntimeError(
            f"League-wide roster snapshot does not exist: "
            f"{roster_file}"
        )

    with roster_file.open(
        "r",
        encoding="utf-8",
    ) as file:
        data = json.load(
            file
        )

    data.setdefault(
        "provider",
        provider,
    )

    return data


def build_league_roster_summary():
    """
    Build a compact trade-analysis view of every team.

    Includes:
      - team name
      - roster ID
      - whether it is my team
      - positional counts
      - players grouped by position
    """

    data = load_league_rosters()

    teams = []

    for team in data.get(
        "teams",
        [],
    ):
        players = team.get(
            "players",
            [],
        )

        position_counts = Counter(
            player.get(
                "position",
                "UNKNOWN",
            )
            for player in players
        )

        players_by_position = {}

        for player in players:
            position = player.get(
                "position",
                "UNKNOWN",
            )

            players_by_position.setdefault(
                position,
                [],
            ).append(
                player.get(
                    "name"
                )
            )

        for position in players_by_position:
            players_by_position[
                position
            ] = sorted(
                players_by_position[
                    position
                ]
            )

        teams.append(
            {
                "roster_id": team.get(
                    "roster_id"
                ),
                "team_name": team.get(
                    "team_name"
                ),
                "is_my_team": team.get(
                    "is_my_team",
                    False,
                ),
                "player_count": len(
                    players
                ),
                "position_counts": dict(
                    position_counts
                ),
                "players_by_position": (
                    players_by_position
                ),
            }
        )

    return {
        "provider": data.get(
            "provider"
        ),
        "league_id": data.get(
            "league_id"
        ),
        "league_name": data.get(
            "league_name"
        ),
        "generated_at": data.get(
            "generated_at"
        ),
        "team_count": len(
            teams
        ),
        "teams": teams,
    }


@function_tool
def get_league_rosters() -> str:
    """
    Return current league-wide fantasy rosters for trade
    and opponent-roster analysis.

    Use this before evaluating realistic trade opportunities.

    Do not invent opposing rosters when this tool is unavailable.
    """

    return json.dumps(
        load_league_rosters(),
        indent=2,
    )


@function_tool
def get_league_roster_summary() -> str:
    """
    Return a compact league-wide roster summary for trade
    analysis, including positional depth and player names
    for every team.
    """

    return json.dumps(
        build_league_roster_summary(),
        indent=2,
    )