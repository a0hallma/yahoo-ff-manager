import json
from collections import Counter
from pathlib import Path

from agents import function_tool


ROSTER_FILE = Path(__file__).parent / "data" / "roster.json"

SLOT_ELIGIBILITY = {
    "QB": {"QB"},
    "RB": {"RB"},
    "WR": {"WR"},
    "TE": {"TE"},
    "FLEX": {"RB", "WR", "TE"},
    "K": {"K"},
    "DEF": {"DEF"},
}


def load_roster():
    with open(ROSTER_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def normalize_name(name):
    return name.strip().lower()


def build_roster_index():
    roster = load_roster()

    return {
        normalize_name(player["name"]): player
        for player in roster.get("players", [])
    }


def check_lineup(
    qb,
    rb1,
    rb2,
    wr1,
    wr2,
    te,
    flex,
    k,
    defense,
):
    roster_index = build_roster_index()

    proposed = [
        ("QB", qb),
        ("RB", rb1),
        ("RB", rb2),
        ("WR", wr1),
        ("WR", wr2),
        ("TE", te),
        ("FLEX", flex),
        ("K", k),
        ("DEF", defense),
    ]

    errors = []
    warnings = []
    resolved_lineup = []

    normalized_names = [
        normalize_name(name)
        for _, name in proposed
        if name and name.strip()
    ]

    duplicate_names = [
        name
        for name, count in Counter(normalized_names).items()
        if count > 1
    ]

    if duplicate_names:
        for duplicate in duplicate_names:
            player = roster_index.get(duplicate)
            display_name = (
                player["name"]
                if player
                else duplicate
            )

            errors.append(
                f"{display_name} appears in more than one starting slot."
            )

    for slot, player_name in proposed:
        if not player_name or not player_name.strip():
            errors.append(
                f"{slot} contains no player."
            )
            continue

        normalized = normalize_name(player_name)
        player = roster_index.get(normalized)

        if not player:
            errors.append(
                f"{player_name} is not on the current roster."
            )
            continue

        position = player.get("position")
        eligible_positions = SLOT_ELIGIBILITY[slot]

        if position not in eligible_positions:
            errors.append(
                f"{player['name']} is a {position} and is not eligible "
                f"for the {slot} slot."
            )

        if player.get("lineup_slot") == "IR":
            warnings.append(
                f"{player['name']} is currently in an IR slot and would "
                f"need to be activated before starting."
            )

        resolved_lineup.append(
            {
                "slot": slot,
                "name": player["name"],
                "position": position,
                "nfl_team": player.get("nfl_team"),
                "current_lineup_slot": player.get("lineup_slot"),
            }
        )

    return {
        "is_legal": len(errors) == 0,
        "expected_starters": 9,
        "resolved_starters": len(resolved_lineup),
        "errors": errors,
        "warnings": warnings,
        "lineup": resolved_lineup,
    }


@function_tool
def validate_lineup(
    qb: str,
    rb1: str,
    rb2: str,
    wr1: str,
    wr2: str,
    te: str,
    flex: str,
    k: str,
    defense: str,
) -> str:
    """
    Deterministically validate a proposed fantasy starting lineup.

    Checks that every player is on the current roster, no player appears
    twice, and each player is eligible for the proposed lineup slot.
    """

    result = check_lineup(
        qb=qb,
        rb1=rb1,
        rb2=rb2,
        wr1=wr1,
        wr2=wr2,
        te=te,
        flex=flex,
        k=k,
        defense=defense,
    )

    return json.dumps(result, indent=2)