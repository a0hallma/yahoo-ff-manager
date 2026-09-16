import json
from datetime import datetime, timezone
from pathlib import Path

from sleeper.normalizer import (
    get_player_name,
    normalize_injury_status,
)


SLEEPER_AVAILABLE_PLAYERS_FILE = Path(
    "data/sleeper_available_players.json"
)

FANTASY_POSITIONS = {
    "QB",
    "RB",
    "WR",
    "TE",
    "K",
    "DEF",
}


def build_available_player_snapshot(
    client,
    league_id,
):
    """
    Build Sleeper's live unrostered-player pool.

    Sleeper does not expose one endpoint called
    "available players".

    Instead:
      1. Get every roster in the league.
      2. Collect every rostered player ID.
      3. Get Sleeper's active NFL player directory.
      4. Keep players who are not rostered.
    """

    rosters = client.get_league_rosters(league_id)

    rostered_player_ids = set()

    for roster in rosters:
        for player_id in roster.get("players") or []:
            rostered_player_ids.add(str(player_id))

    player_map = client.get_players(active=True)

    available_players = []

    for player_id, player in player_map.items():
        player_id = str(player_id)

        if player_id in rostered_player_ids:
            continue

        position = player.get("position")

        if position not in FANTASY_POSITIONS:
            continue

        nfl_team = player.get("team")

        if not nfl_team:
            continue

        available_players.append(
            {
                "player_id": player_id,
                "name": get_player_name(player),
                "position": position,
                "nfl_team": nfl_team,

                # We know the player is not rostered.
                # We do NOT yet claim whether Sleeper
                # considers them FA or waiver-locked.
                "availability": "UNROSTERED",

                "status": normalize_injury_status(
                    player.get("injury_status")
                ),

                "search_rank": player.get(
                    "search_rank"
                ),

                "depth_chart_order": player.get(
                    "depth_chart_order"
                ),
            }
        )

    available_players.sort(
        key=lambda player: (
            player.get("search_rank")
            if isinstance(
                player.get("search_rank"),
                (int, float),
            )
            else 999999,
            player.get("name", ""),
        )
    )

    snapshot = {
        "provider": "sleeper",
        "league_id": str(league_id),
        "last_updated": datetime.now(
            timezone.utc
        ).date().isoformat(),
        "source": "live_sleeper_api",
        "players": available_players,
    }

    return snapshot


def save_available_player_snapshot(snapshot):
    """
    Save Sleeper's available-player pool separately
    from the Yahoo available-player snapshot.
    """

    SLEEPER_AVAILABLE_PLAYERS_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with SLEEPER_AVAILABLE_PLAYERS_FILE.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            snapshot,
            file,
            indent=2,
            ensure_ascii=False,
        )

    return SLEEPER_AVAILABLE_PLAYERS_FILE