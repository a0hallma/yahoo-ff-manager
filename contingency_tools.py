import json
from datetime import datetime

from agents import function_tool

from lineup_tools import SLOT_ELIGIBILITY
from schedule_tools import (
    build_roster_schedule,
    fetch_official_schedule,
)
from waiver_tools import load_available_players


def get_eligible_slots(position):
    return [
        slot
        for slot, eligible_positions in SLOT_ELIGIBILITY.items()
        if position in eligible_positions
    ]


def build_games_by_team():
    schedule = fetch_official_schedule()

    games_by_team = {}

    for game in schedule["games"]:
        away = game["away"]
        home = game["home"]

        games_by_team[away] = {
            "opponent": home,
            "kickoff": game["kickoff"],
        }

        games_by_team[home] = {
            "opponent": away,
            "kickoff": game["kickoff"],
        }

    return games_by_team


def build_lock_aware_player_pool(
    player_name,
    lineup_slot=None,
):
    roster_schedule = build_roster_schedule()
    roster_players = roster_schedule["players"]

    affected = next(
        (
            player
            for player in roster_players
            if player["name"].strip().lower()
            == player_name.strip().lower()
        ),
        None,
    )

    if not affected:
        raise ValueError(
            f"{player_name} was not found on the current roster."
        )

    if not affected.get("kickoff"):
        raise ValueError(
            f"No kickoff time was found for {affected['name']}."
        )

    decision_time = datetime.fromisoformat(
        affected["kickoff"]
    )

    affected_slot = (
        lineup_slot
        if lineup_slot
        else affected.get("lineup_slot")
    )

    if affected_slot not in SLOT_ELIGIBILITY:
        raise ValueError(
            f"Invalid lineup slot: {affected_slot}"
        )

    if affected["position"] not in SLOT_ELIGIBILITY[affected_slot]:
        raise ValueError(
            f"{affected['name']} ({affected['position']}) "
            f"is not eligible for {affected_slot}."
        )

    # ---------------------------------------------------------
    # Current roster options
    # ---------------------------------------------------------

    roster_pool = []

    for player in roster_players:
        if (
            player["name"].strip().lower()
            == affected["name"].strip().lower()
        ):
            continue

        kickoff_value = player.get("kickoff")

        if kickoff_value:
            kickoff = datetime.fromisoformat(kickoff_value)

            # Same-kickoff players are still changeable
            # immediately before kickoff.
            unlocked = kickoff >= decision_time
        else:
            unlocked = False

        eligible_slots = get_eligible_slots(
            player["position"]
        )

        roster_pool.append(
            {
                "name": player["name"],
                "position": player["position"],
                "nfl_team": player["nfl_team"],
                "current_lineup_slot": player["lineup_slot"],
                "kickoff": kickoff_value,
                "eligible_slots": eligible_slots,
                "direct_replacement_for_current_slot": (
                    affected_slot in eligible_slots
                ),
                "unlocked_at_decision_time": unlocked,
            }
        )

    unlocked_roster_players = [
        player
        for player in roster_pool
        if player["unlocked_at_decision_time"]
    ]

    already_locked_roster_players = [
        player
        for player in roster_pool
        if not player["unlocked_at_decision_time"]
    ]

    # ---------------------------------------------------------
    # Current free-agent options
    # ---------------------------------------------------------

    available_data = load_available_players()
    available_players = available_data.get(
        "players",
        []
    )

    games_by_team = build_games_by_team()

    free_agent_options = []

    for player in available_players:
        if player.get("availability") != "FA":
            continue

        team = (
            player.get("nfl_team")
            or player.get("team")
        )

        if not team:
            continue

        game = games_by_team.get(team)

        if not game:
            continue

        kickoff_value = game["kickoff"]
        kickoff = datetime.fromisoformat(
            kickoff_value
        )

        if kickoff < decision_time:
            continue

        position = player.get("position")
        eligible_slots = get_eligible_slots(
            position
        )

        free_agent_options.append(
            {
                "name": player["name"],
                "position": position,
                "nfl_team": team,
                "opponent": game["opponent"],
                "kickoff": kickoff_value,
                "availability": "FA",
                "eligible_slots": eligible_slots,
                "direct_replacement_for_current_slot": (
                    affected_slot in eligible_slots
                ),
            }
        )

    free_agent_options.sort(
        key=lambda player: (
            player["kickoff"],
            player["name"],
        )
    )

    return {
        "affected_player": affected["name"],
        "affected_position": affected["position"],
        "affected_lineup_slot": affected_slot,
        "decision_time": affected["kickoff"],
        "unlocked_roster_players": unlocked_roster_players,
        "already_locked_roster_players": already_locked_roster_players,
        "current_free_agent_emergency_options": free_agent_options,
    }


@function_tool
def get_lock_aware_player_pool(
    player_name: str,
    lineup_slot: str,
) -> str:
    """
    For a questionable or uncertain roster player, determine which
    roster players and current free agents will still be unlocked
    immediately before that player's NFL kickoff.

    lineup_slot must be the slot occupied by the player in the proposed
    starting lineup, such as RB, WR, TE, or FLEX.

    Use this to build late-game injury contingencies.
    """

    return json.dumps(
        build_lock_aware_player_pool(
            player_name,
            lineup_slot=lineup_slot,
        ),
        indent=2,
    )