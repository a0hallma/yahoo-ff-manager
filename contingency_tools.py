import json
from datetime import datetime

from agents import function_tool

from provider_context import (
    get_current_provider,
    get_provider_display_name,
)
from lineup_tools import SLOT_ELIGIBILITY
from schedule_tools import (
    build_roster_schedule,
    fetch_official_schedule,
)
from waiver_tools import load_available_players


def get_eligible_slots(position):
    return [
        slot
        for slot, eligible_positions
        in SLOT_ELIGIBILITY.items()
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


def build_acquisition_candidates(
    available_players,
    games_by_team,
    decision_time,
    affected_slot,
):
    """
    Build provider-aware late-game acquisition candidates.

    Yahoo FA means the player is represented as a free agent.

    Sleeper UNROSTERED means only that the player is not currently
    on another roster. It does not prove immediate addability.
    """

    provider = get_current_provider()

    if provider == "yahoo":
        allowed_states = {
            "FA",
        }

    else:
        allowed_states = {
            "UNROSTERED",
        }

    candidates = []

    for player in available_players:
        availability = player.get(
            "availability"
        )

        if availability not in allowed_states:
            continue

        team = (
            player.get("nfl_team")
            or player.get("team")
        )

        if not team:
            continue

        game = games_by_team.get(
            team
        )

        if not game:
            continue

        kickoff_value = game[
            "kickoff"
        ]

        kickoff = datetime.fromisoformat(
            kickoff_value
        )

        if kickoff < decision_time:
            continue

        position = player.get(
            "position"
        )

        eligible_slots = get_eligible_slots(
            position
        )

        immediate_addability_confirmed = (
            provider == "yahoo"
            and availability == "FA"
        )

        if immediate_addability_confirmed:
            availability_interpretation = (
                "Confirmed Yahoo free agent."
            )

        else:
            availability_interpretation = (
                "Unrostered in Sleeper. "
                "Immediate addability is not confirmed."
            )

        candidates.append(
            {
                "name": player["name"],
                "position": position,
                "nfl_team": team,
                "opponent": game[
                    "opponent"
                ],
                "kickoff": kickoff_value,
                "availability": availability,
                "availability_interpretation": (
                    availability_interpretation
                ),
                "immediate_addability_confirmed": (
                    immediate_addability_confirmed
                ),
                "eligible_slots": eligible_slots,
                "direct_replacement_for_current_slot": (
                    affected_slot
                    in eligible_slots
                ),
            }
        )

    candidates.sort(
        key=lambda player: (
            player["kickoff"],
            player["name"],
        )
    )

    return candidates


def build_lock_aware_player_pool(
    player_name,
    lineup_slot=None,
):
    provider = get_current_provider()
    provider_name = get_provider_display_name()

    roster_schedule = (
        build_roster_schedule()
    )

    roster_players = (
        roster_schedule[
            "players"
        ]
    )

    affected = next(
        (
            player
            for player in roster_players
            if (
                player[
                    "name"
                ].strip().lower()
                == player_name.strip().lower()
            )
        ),
        None,
    )

    if not affected:
        raise ValueError(
            (
                f"{player_name} was not found "
                f"on the current "
                f"{provider_name} roster."
            )
        )

    if not affected.get(
        "kickoff"
    ):
        raise ValueError(
            (
                "No kickoff time was found for "
                f"{affected['name']}."
            )
        )

    decision_time = (
        datetime.fromisoformat(
            affected[
                "kickoff"
            ]
        )
    )

    affected_slot = (
        lineup_slot
        if lineup_slot
        else affected.get(
            "lineup_slot"
        )
    )

    if affected_slot not in SLOT_ELIGIBILITY:
        raise ValueError(
            (
                "Invalid lineup slot: "
                f"{affected_slot}"
            )
        )

    if (
        affected["position"]
        not in SLOT_ELIGIBILITY[
            affected_slot
        ]
    ):
        raise ValueError(
            (
                f"{affected['name']} "
                f"({affected['position']}) "
                f"is not eligible for "
                f"{affected_slot}."
            )
        )

    # ---------------------------------------------------------
    # Current roster options
    # ---------------------------------------------------------

    roster_pool = []

    for player in roster_players:
        if (
            player[
                "name"
            ].strip().lower()
            == affected[
                "name"
            ].strip().lower()
        ):
            continue

        kickoff_value = player.get(
            "kickoff"
        )

        if kickoff_value:
            kickoff = (
                datetime.fromisoformat(
                    kickoff_value
                )
            )

            # Same-kickoff players are still changeable
            # immediately before kickoff.
            unlocked = (
                kickoff
                >= decision_time
            )

        else:
            unlocked = False

        eligible_slots = (
            get_eligible_slots(
                player[
                    "position"
                ]
            )
        )

        roster_pool.append(
            {
                "name": player[
                    "name"
                ],
                "position": player[
                    "position"
                ],
                "nfl_team": player[
                    "nfl_team"
                ],
                "current_lineup_slot": (
                    player[
                        "lineup_slot"
                    ]
                ),
                "kickoff": kickoff_value,
                "eligible_slots": (
                    eligible_slots
                ),
                "direct_replacement_for_current_slot": (
                    affected_slot
                    in eligible_slots
                ),
                "unlocked_at_decision_time": (
                    unlocked
                ),
            }
        )

    unlocked_roster_players = [
        player
        for player in roster_pool
        if player[
            "unlocked_at_decision_time"
        ]
    ]

    already_locked_roster_players = [
        player
        for player in roster_pool
        if not player[
            "unlocked_at_decision_time"
        ]
    ]

    # ---------------------------------------------------------
    # Provider-aware acquisition candidates
    # ---------------------------------------------------------

    available_data = (
        load_available_players()
    )

    available_players = (
        available_data.get(
            "players",
            [],
        )
    )

    games_by_team = (
        build_games_by_team()
    )

    acquisition_candidates = (
        build_acquisition_candidates(
            available_players=available_players,
            games_by_team=games_by_team,
            decision_time=decision_time,
            affected_slot=affected_slot,
        )
    )

    # Preserve the existing Yahoo field for downstream code.
    #
    # Sleeper UNROSTERED does not prove that a player can
    # immediately be added, so Sleeper players must not appear
    # in this legacy "free agent" field.
    free_agent_options = [
        player
        for player
        in acquisition_candidates
        if player[
            "immediate_addability_confirmed"
        ]
    ]

    if provider == "sleeper":
        acquisition_warning = (
            "Sleeper candidates are confirmed unrostered only. "
            "Immediate addability versus waivers has not yet "
            "been established, so they must not be treated as "
            "confirmed emergency free agents."
        )

    else:
        acquisition_warning = None

    return {
        "provider": provider,
        "provider_name": provider_name,
        "affected_player": affected[
            "name"
        ],
        "affected_position": affected[
            "position"
        ],
        "affected_lineup_slot": (
            affected_slot
        ),
        "decision_time": affected[
            "kickoff"
        ],
        "unlocked_roster_players": (
            unlocked_roster_players
        ),
        "already_locked_roster_players": (
            already_locked_roster_players
        ),
        "current_acquisition_candidates": (
            acquisition_candidates
        ),
        "current_free_agent_emergency_options": (
            free_agent_options
        ),
        "acquisition_warning": (
            acquisition_warning
        ),
    }


@function_tool
def get_lock_aware_player_pool(
    player_name: str,
    lineup_slot: str,
) -> str:
    """
    For an uncertain roster player, determine which roster
    players will still be unlocked immediately before that
    player's NFL kickoff.

    Also return provider-aware acquisition candidates.

    For Sleeper, UNROSTERED does not prove immediate
    addability, so those players are not represented as
    confirmed free-agent emergency options.

    lineup_slot must be the slot occupied by the player in
    the proposed starting lineup, such as RB, WR, TE, or FLEX.
    """

    return json.dumps(
        build_lock_aware_player_pool(
            player_name,
            lineup_slot=lineup_slot,
        ),
        indent=2,
    )