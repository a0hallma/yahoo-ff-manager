import json
from collections import Counter

from agents import function_tool

from provider_context import (
    get_current_provider,
    get_provider_display_name,
)
from league_tools import load_league_settings
from roster_tools import load_roster
from waiver_tools import load_available_players


def normalize_name(name):
    return name.strip().lower()


def load_current_roster_data():
    """
    Load the roster belonging to the currently selected
    fantasy provider.
    """

    return load_roster()


def validate_transaction(
    add_player,
    drop_player,
):
    """
    Deterministically validate a proposed add/drop against
    the currently selected fantasy provider.

    Yahoo:
      FA and W are known acquisition states.

    Sleeper:
      UNROSTERED proves only that the player is not currently
      owned. Until addability/waiver state is established,
      Python must not certify the transaction as executable.
    """

    provider = get_current_provider()
    provider_name = get_provider_display_name()

    roster = load_current_roster_data()
    available = load_available_players()
    league = load_league_settings()

    roster_players = roster.get(
        "players",
        [],
    )

    available_players = available.get(
        "players",
        [],
    )

    roster_index = {
        normalize_name(
            player["name"]
        ): player
        for player in roster_players
    }

    available_index = {
        normalize_name(
            player["name"]
        ): player
        for player in available_players
    }

    add_key = normalize_name(
        add_player
    )

    drop_key = normalize_name(
        drop_player
    )

    errors = []
    warnings = []

    add = available_index.get(
        add_key
    )

    drop = roster_index.get(
        drop_key
    )

    if add_key in roster_index:
        errors.append(
            (
                f"{add_player} is already on the "
                f"current {provider_name} roster."
            )
        )

    if not add:
        errors.append(
            (
                f"{add_player} is not in the current "
                f"{provider_name} available-player snapshot."
            )
        )

    if not drop:
        errors.append(
            (
                f"{drop_player} is not on the current "
                f"{provider_name} roster."
            )
        )

    if add_key == drop_key:
        errors.append(
            (
                "The add player and drop player "
                "cannot be the same player."
            )
        )

    if errors:
        return {
            "provider": provider,
            "provider_name": provider_name,
            "is_valid": False,
            "transaction_blocked": False,
            "errors": errors,
            "warnings": warnings,
        }

    availability = add.get(
        "availability"
    )

    # ---------------------------------------------------------
    # Provider-specific acquisition validation
    # ---------------------------------------------------------

    if provider == "yahoo":
        if availability not in {
            "FA",
            "W",
        }:
            return {
                "provider": provider,
                "provider_name": provider_name,
                "is_valid": False,
                "transaction_blocked": True,
                "block_reason": (
                    "Yahoo acquisition state is not recognized."
                ),
                "errors": [
                    (
                        f"{add['name']} has unsupported Yahoo "
                        f"availability state: {availability}"
                    )
                ],
                "warnings": warnings,
            }

        acquisition_state_confirmed = True
        transaction_executable = True

    elif provider == "sleeper":
        if availability != "UNROSTERED":
            return {
                "provider": provider,
                "provider_name": provider_name,
                "is_valid": False,
                "transaction_blocked": True,
                "block_reason": (
                    "Sleeper acquisition state is not recognized."
                ),
                "errors": [
                    (
                        f"{add['name']} has unsupported Sleeper "
                        f"availability state: {availability}"
                    )
                ],
                "warnings": warnings,
            }

        return {
            "provider": provider,
            "provider_name": provider_name,
            "is_valid": False,
            "transaction_blocked": True,
            "transaction_executable": False,
            "acquisition_state_confirmed": False,
            "block_reason": (
                "Sleeper confirms that the player is unrostered, "
                "but immediate addability versus waivers has not "
                "yet been established."
            ),
            "add": {
                "name": add["name"],
                "position": add["position"],
                "nfl_team": add.get(
                    "nfl_team"
                ),
                "availability": availability,
                "waiver_date": add.get(
                    "waiver_date"
                ),
            },
            "drop": {
                "name": drop["name"],
                "position": drop["position"],
                "nfl_team": drop.get(
                    "nfl_team"
                ),
            },
            "errors": [],
            "warnings": [
                (
                    "Do not present this Sleeper add/drop "
                    "as executable until acquisition state "
                    "is verified."
                )
            ],
        }

    else:
        return {
            "provider": provider,
            "provider_name": provider_name,
            "is_valid": False,
            "transaction_blocked": True,
            "transaction_executable": False,
            "acquisition_state_confirmed": False,
            "block_reason": (
                "Provider-specific transaction semantics "
                "have not been established."
            ),
            "errors": [],
            "warnings": warnings,
        }

    # ---------------------------------------------------------
    # Resulting roster structure
    # ---------------------------------------------------------

    resulting_roster = [
        player
        for player in roster_players
        if (
            normalize_name(
                player["name"]
            )
            != drop_key
        )
    ]

    resulting_roster.append(
        {
            "name": add[
                "name"
            ],
            "position": add[
                "position"
            ],
            "nfl_team": add.get(
                "nfl_team"
            ),
        }
    )

    position_counts = Counter(
        player.get(
            "position"
        )
        for player in resulting_roster
    )

    roster_slots = league.get(
        "roster_slots",
        {},
    )

    if (
        roster_slots.get(
            "K",
            0,
        )
        > 0
        and position_counts.get(
            "K",
            0,
        )
        == 0
    ):
        warnings.append(
            (
                "Resulting roster would contain no kicker "
                "even though the league requires one."
            )
        )

    if (
        roster_slots.get(
            "DEF",
            0,
        )
        > 0
        and position_counts.get(
            "DEF",
            0,
        )
        == 0
    ):
        warnings.append(
            (
                "Resulting roster would contain no defense "
                "even though the league requires one."
            )
        )

    if position_counts.get(
        "QB",
        0,
    ) >= 3:
        warnings.append(
            (
                "Resulting roster would contain "
                f"{position_counts['QB']} quarterbacks."
            )
        )

    if position_counts.get(
        "TE",
        0,
    ) >= 3:
        warnings.append(
            (
                "Resulting roster would contain "
                f"{position_counts['TE']} tight ends."
            )
        )

    return {
        "provider": provider,
        "provider_name": provider_name,
        "is_valid": True,
        "transaction_blocked": False,
        "transaction_executable": (
            transaction_executable
        ),
        "acquisition_state_confirmed": (
            acquisition_state_confirmed
        ),
        "add": {
            "name": add[
                "name"
            ],
            "position": add[
                "position"
            ],
            "nfl_team": add.get(
                "nfl_team"
            ),
            "availability": availability,
            "waiver_date": add.get(
                "waiver_date"
            ),
        },
        "drop": {
            "name": drop[
                "name"
            ],
            "position": drop[
                "position"
            ],
            "nfl_team": drop.get(
                "nfl_team"
            ),
        },
        "roster_size_before": len(
            roster_players
        ),
        "roster_size_after": len(
            resulting_roster
        ),
        "resulting_position_counts": dict(
            position_counts
        ),
        "errors": errors,
        "warnings": warnings,
    }


@function_tool
def validate_add_drop(
    add_player: str,
    drop_player: str,
) -> str:
    """
    Deterministically validate a proposed fantasy add/drop
    against the currently selected provider.

    Yahoo FA/W acquisition states can be validated.

    Sleeper UNROSTERED means only that the player is not
    currently owned. Until the exact acquisition state is
    established, an executable Sleeper transaction is blocked.
    """

    return json.dumps(
        validate_transaction(
            add_player=add_player,
            drop_player=drop_player,
        ),
        indent=2,
    )