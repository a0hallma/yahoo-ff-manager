import json
from pathlib import Path


SLEEPER_ROSTER_FILE = Path("data/sleeper_roster.json")


def normalize_injury_status(injury_status):
    """
    Convert Sleeper injury labels into the short status values
    already used by our Fantasy GM.
    """

    if not injury_status:
        return ""

    status = str(injury_status).strip().lower()

    if status == "none":
        return ""

    mappings = {
        "na": "NA",
        "n/a": "NA",
        "questionable": "Q",
        "doubtful": "D",
        "out": "O",
        "injured reserve": "IR",
        "ir": "IR",
        "pup": "PUP",
        "physically unable to perform": "PUP",
        "suspended": "SUSP",
    }

    return mappings.get(status, str(injury_status))


def get_player_name(player):
    """
    Build a readable player name from Sleeper's player record.
    """

    full_name = player.get("full_name")

    if full_name:
        return full_name

    first_name = player.get("first_name", "")
    last_name = player.get("last_name", "")

    name = f"{first_name} {last_name}".strip()

    return name


def get_team_name(user):
    """
    Sleeper may store a custom fantasy team name in user metadata.
    Fall back to the user's display name if no custom name exists.
    """

    metadata = user.get("metadata") or {}

    return (
        metadata.get("team_name")
        or user.get("display_name")
        or user.get("username")
        or "Sleeper Team"
    )


def build_normalized_roster(
    client,
    username,
    league_name,
    season=2026,
):
    """
    Pull the live Sleeper league and roster, then translate it
    into the same roster structure used by our Fantasy GM.
    """

    user = client.get_user(username)

    user_id = user["user_id"]

    league = client.find_user_league(
        user_id=user_id,
        season=season,
        league_name=league_name,
    )

    league_id = league["league_id"]

    roster = client.get_user_roster(
        league_id=league_id,
        user_id=user_id,
    )

    league_users = client.get_league_users(league_id)

    league_user = next(
        (
            item
            for item in league_users
            if str(item.get("user_id")) == str(user_id)
        ),
        user,
    )

    nfl_state = client.get_nfl_state()

    week = nfl_state.get("week") or league.get("settings", {}).get("leg")

    player_map = client.get_players(active=True)

    starter_ids = roster.get("starters") or []
    all_player_ids = roster.get("players") or []

    roster_positions = [
        slot
        for slot in league.get("roster_positions", [])
        if slot != "BN"
    ]

    if len(starter_ids) != len(roster_positions):
        raise ValueError(
            "Sleeper starter count does not match the league's "
            f"starting roster positions. "
            f"Starters={len(starter_ids)}, "
            f"Positions={len(roster_positions)}"
        )

    normalized_players = []

    starter_set = set(starter_ids)

    for player_id, lineup_slot in zip(
        starter_ids,
        roster_positions,
    ):
        if player_id == "0":
            continue

        player = player_map.get(player_id)

        if not player:
            raise ValueError(
                f"Sleeper player ID {player_id} "
                "was not found in the player directory."
            )

        normalized_players.append(
            {
                "name": get_player_name(player),
                "position": player.get("position", ""),
                "nfl_team": player.get("team", ""),
                "lineup_slot": lineup_slot,
                "status": normalize_injury_status(
                    player.get("injury_status")
                ),
            }
        )

    for player_id in all_player_ids:
        if player_id in starter_set:
            continue

        player = player_map.get(player_id)

        if not player:
            raise ValueError(
                f"Sleeper player ID {player_id} "
                "was not found in the player directory."
            )

        normalized_players.append(
            {
                "name": get_player_name(player),
                "position": player.get("position", ""),
                "nfl_team": player.get("team", ""),
                "lineup_slot": "BENCH",
                "status": normalize_injury_status(
                    player.get("injury_status")
                ),
            }
        )

    normalized_roster = {
        "provider": "sleeper",
        "league_name": league.get("name"),
        "league_id": league_id,
        "roster_id": roster.get("roster_id"),
        "team_name": get_team_name(league_user),
        "week": week,
        "players": normalized_players,
    }

    return normalized_roster


def save_normalized_roster(roster):
    """
    Save the normalized Sleeper roster without touching Yahoo data.
    """

    SLEEPER_ROSTER_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with SLEEPER_ROSTER_FILE.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            roster,
            file,
            indent=2,
            ensure_ascii=False,
        )

    return SLEEPER_ROSTER_FILE