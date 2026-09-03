import json
from collections import Counter

from agents import function_tool

from roster_tools import ROSTER_FILE
from waiver_tools import load_available_players


def normalize_name(name):
    return name.strip().lower()


def load_current_roster_data():
    with open(ROSTER_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def validate_transaction(add_player, drop_player):
    roster = load_current_roster_data()
    available = load_available_players()

    roster_players = roster.get("players", [])
    available_players = available.get("players", [])

    roster_index = {
        normalize_name(player["name"]): player
        for player in roster_players
    }

    available_index = {
        normalize_name(player["name"]): player
        for player in available_players
    }

    add_key = normalize_name(add_player)
    drop_key = normalize_name(drop_player)

    errors = []
    warnings = []

    add = available_index.get(add_key)
    drop = roster_index.get(drop_key)

    if add_key in roster_index:
        errors.append(
            f"{add_player} is already on the current roster."
        )

    if not add:
        errors.append(
            f"{add_player} is not in the current available-player snapshot."
        )

    if not drop:
        errors.append(
            f"{drop_player} is not on the current roster."
        )

    if add_key == drop_key:
        errors.append(
            "The add player and drop player cannot be the same player."
        )

    if errors:
        return {
            "is_valid": False,
            "errors": errors,
            "warnings": warnings,
        }

    resulting_roster = [
        player
        for player in roster_players
        if normalize_name(player["name"]) != drop_key
    ]

    resulting_roster.append(
        {
            "name": add["name"],
            "position": add["position"],
            "nfl_team": add.get("nfl_team"),
        }
    )

    position_counts = Counter(
        player.get("position")
        for player in resulting_roster
    )

    if position_counts.get("K", 0) == 0:
        warnings.append(
            "Resulting roster would contain no kicker."
        )

    if position_counts.get("DEF", 0) == 0:
        warnings.append(
            "Resulting roster would contain no defense."
        )

    if position_counts.get("QB", 0) >= 3:
        warnings.append(
            f"Resulting roster would contain "
            f"{position_counts['QB']} quarterbacks."
        )

    if position_counts.get("TE", 0) >= 3:
        warnings.append(
            f"Resulting roster would contain "
            f"{position_counts['TE']} tight ends."
        )

    return {
        "is_valid": True,
        "add": {
            "name": add["name"],
            "position": add["position"],
            "nfl_team": add.get("nfl_team"),
            "availability": add.get("availability"),
            "waiver_date": add.get("waiver_date"),
        },
        "drop": {
            "name": drop["name"],
            "position": drop["position"],
            "nfl_team": drop.get("nfl_team"),
        },
        "roster_size_before": len(roster_players),
        "roster_size_after": len(resulting_roster),
        "resulting_position_counts": dict(position_counts),
        "errors": errors,
        "warnings": warnings,
    }


@function_tool
def validate_add_drop(
    add_player: str,
    drop_player: str,
) -> str:
    """
    Deterministically validate a proposed fantasy add/drop transaction.

    Confirms that the add target is currently available, the drop target
    is currently rostered, identifies FA versus waiver status, preserves
    waiver-date information, and reports resulting roster structure.
    """

    return json.dumps(
        validate_transaction(
            add_player=add_player,
            drop_player=drop_player,
        ),
        indent=2,
    )