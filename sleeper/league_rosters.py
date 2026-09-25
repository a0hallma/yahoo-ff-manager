import json
from datetime import datetime
from pathlib import Path

from sleeper.client import SleeperClient
from sleeper.normalizer import (
    get_player_name,
    get_team_name,
)


OUTPUT_FILE = Path(
    "data/sleeper_league_rosters.json"
)


def build_player(
    player_id,
    player_map,
    lineup_slot,
):
    raw = player_map.get(
        str(player_id),
        {},
    )

    return {
        "player_id": str(player_id),
       "name": get_player_name(
        raw
        ),
        "position": raw.get(
            "position"
        ),
        "nfl_team": raw.get(
            "team"
        ),
        "lineup_slot": lineup_slot,
    }


def build_league_rosters(
    client,
    username,
    league_name,
    season=2026,
):
    """
    Build a normalized snapshot of every roster in the
    selected Sleeper league.
    """

    user = client.get_user(
        username
    )

    if not user:
        raise RuntimeError(
            f"Sleeper user not found: {username}"
        )

    user_id = str(
        user["user_id"]
    )

    league = client.find_user_league(
        user_id=user_id,
        season=season,
        league_name=league_name,
    )

    if not league:
        raise RuntimeError(
            f"Sleeper league not found: {league_name}"
        )

    league_id = str(
        league["league_id"]
    )

    rosters = client.get_league_rosters(
        league_id
    )

    league_users = client.get_league_users(
        league_id
    )

    player_map = client.get_players(
        active=True
    )

    users_by_id = {
        str(item["user_id"]): item
        for item in league_users
        if item.get("user_id")
    }

    roster_positions = league.get(
        "roster_positions",
        [],
    )

    starter_slots = [
        slot
        for slot in roster_positions
        if slot not in {
            "BN",
            "IR",
        }
    ]

    teams = []

    for roster in rosters:
        roster_id = roster.get(
            "roster_id"
        )

        owner_id = roster.get(
            "owner_id"
        )

        owner = (
            users_by_id.get(
                str(owner_id)
            )
            if owner_id
            else None
        )

        team_name = (
            get_team_name(owner)
            if owner
            else f"Roster {roster_id}"
        )

        starter_ids = [
            str(player_id)
            for player_id
            in roster.get(
                "starters",
                [],
            )
        ]

        roster_player_ids = [
            str(player_id)
            for player_id
            in roster.get(
                "players",
                [],
            )
        ]

        starter_slot_by_id = {}

        for index, player_id in enumerate(
            starter_ids
        ):
            slot = (
                starter_slots[index]
                if index < len(starter_slots)
                else "STARTER"
            )

            starter_slot_by_id[
                player_id
            ] = slot

        players = []

        for player_id in roster_player_ids:
            lineup_slot = (
                starter_slot_by_id.get(
                    player_id,
                    "BN",
                )
            )

            players.append(
                build_player(
                    player_id=player_id,
                    player_map=player_map,
                    lineup_slot=lineup_slot,
                )
            )

        starters = [
            player
            for player in players
            if player[
                "lineup_slot"
            ] != "BN"
        ]

        bench = [
            player
            for player in players
            if player[
                "lineup_slot"
            ] == "BN"
        ]

        teams.append(
            {
                "roster_id": roster_id,
                "owner_id": (
                    str(owner_id)
                    if owner_id
                    else None
                ),
                "team_name": team_name,
                "is_my_team": (
                    str(owner_id)
                    == user_id
                    if owner_id
                    else False
                ),
                "players": players,
                "starters": starters,
                "bench": bench,
            }
        )

    teams.sort(
        key=lambda team: (
            not team[
                "is_my_team"
            ],
            team[
                "roster_id"
            ],
        )
    )

    return {
        "provider": "sleeper",
        "season": season,
        "league_id": league_id,
        "league_name": league.get(
            "name"
        ),
        "generated_at": (
            datetime.now()
            .astimezone()
            .isoformat()
        ),
        "team_count": len(
            teams
        ),
        "teams": teams,
    }


def save_league_rosters(
    data,
):
    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with OUTPUT_FILE.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            data,
            file,
            indent=2,
        )

    return OUTPUT_FILE


def refresh_league_rosters(
    username,
    league_name,
    season=2026,
):
    client = SleeperClient()

    data = build_league_rosters(
        client=client,
        username=username,
        league_name=league_name,
        season=season,
    )

    save_league_rosters(
        data
    )

    return data