import json
from collections import Counter

from agents import function_tool

from provider_context import (
    get_current_provider,
    get_provider_display_name,
)
from league_tools import (
    load_league_settings,
)
from roster_tools import (
    load_roster,
)
from waiver_tools import (
    load_available_players,
)


def normalize_name(name):
    return name.strip().lower()


def load_current_roster_data():
    """
    Load the roster belonging to the currently selected
    fantasy provider.
    """

    return load_roster()


def build_blocked_transaction(
    provider,
    provider_name,
    add,
    drop,
    reason,
    error,
    warnings=None,
):
    warnings = warnings or []

    return {
        "provider": provider,
        "provider_name": (
            provider_name
        ),
        "is_valid": False,
        "transaction_blocked": True,
        "transaction_executable": False,
        "acquisition_state_confirmed": False,
        "block_reason": reason,
        "add": (
            {
                "name": add.get(
                    "name"
                ),
                "position": add.get(
                    "position"
                ),
                "nfl_team": add.get(
                    "nfl_team"
                ),
                "availability": add.get(
                    "availability"
                ),
                "acquisition_reason": add.get(
                    "acquisition_reason"
                ),
                "acquisition_state_confirmed": (
                    add.get(
                        "acquisition_state_confirmed"
                    )
                ),
                "immediately_addable": (
                    add.get(
                        "immediately_addable"
                    )
                ),
                "waiver_date": add.get(
                    "waiver_date"
                ),
            }
            if add
            else None
        ),
        "drop": (
            {
                "name": drop.get(
                    "name"
                ),
                "position": drop.get(
                    "position"
                ),
                "nfl_team": drop.get(
                    "nfl_team"
                ),
            }
            if drop
            else None
        ),
        "errors": [
            error
        ],
        "warnings": warnings,
    }


def validate_transaction(
    add_player,
    drop_player,
):
    """
    Deterministically validate a proposed add/drop against
    the currently selected fantasy provider.

    Yahoo:
      FA and W are provider-confirmed acquisition states.

    Sleeper:
      FA = confirmed immediately addable.
      W  = confirmed waiver-claim candidate.
      LOCKED and UNKNOWN cannot be recommended as executable.
    """

    provider = (
        get_current_provider()
    )

    provider_name = (
        get_provider_display_name()
    )

    roster = (
        load_current_roster_data()
    )

    available = (
        load_available_players()
    )

    league = (
        load_league_settings()
    )

    roster_players = roster.get(
        "players",
        [],
    )

    available_players = (
        available.get(
            "players",
            [],
        )
    )

    roster_index = {
        normalize_name(
            player[
                "name"
            ]
        ): player
        for player
        in roster_players
    }

    available_index = {
        normalize_name(
            player[
                "name"
            ]
        ): player
        for player
        in available_players
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
            "provider_name": (
                provider_name
            ),
            "is_valid": False,
            "transaction_blocked": False,
            "transaction_executable": False,
            "errors": errors,
            "warnings": warnings,
        }

    availability = add.get(
        "availability"
    )

    transaction_mode = None

    # ---------------------------------------------------------
    # Provider-specific acquisition validation
    # ---------------------------------------------------------

    if provider == "yahoo":
        if availability not in {
            "FA",
            "W",
        }:
            return build_blocked_transaction(
                provider=provider,
                provider_name=provider_name,
                add=add,
                drop=drop,
                reason=(
                    "unsupported_yahoo_acquisition_state"
                ),
                error=(
                    f"{add['name']} has unsupported Yahoo "
                    f"availability state: {availability}"
                ),
                warnings=warnings,
            )

        acquisition_state_confirmed = True
        transaction_executable = True

        if availability == "FA":
            transaction_mode = (
                "free_agent_add"
            )
        else:
            transaction_mode = (
                "waiver_claim"
            )

            warnings.append(
                (
                    "This transaction represents a waiver "
                    "claim. Submission is possible, but the "
                    "player is not guaranteed to be awarded."
                )
            )

    elif provider == "sleeper":
        supported_states = {
            "FA",
            "W",
            "LOCKED",
            "UNKNOWN",
        }

        if (
            availability
            not in supported_states
        ):
            return build_blocked_transaction(
                provider=provider,
                provider_name=provider_name,
                add=add,
                drop=drop,
                reason=(
                    "unsupported_sleeper_acquisition_state"
                ),
                error=(
                    f"{add['name']} has unsupported Sleeper "
                    f"availability state: {availability}"
                ),
                warnings=warnings,
            )

        confirmed = add.get(
            "acquisition_state_confirmed",
            False,
        )

        if availability == "UNKNOWN":
            return build_blocked_transaction(
                provider=provider,
                provider_name=provider_name,
                add=add,
                drop=drop,
                reason=(
                    "unverified_sleeper_acquisition_state"
                ),
                error=(
                    f"{add['name']}'s Sleeper acquisition "
                    "state could not be confirmed."
                ),
                warnings=warnings,
            )

        if availability == "LOCKED":
            return build_blocked_transaction(
                provider=provider,
                provider_name=provider_name,
                add=add,
                drop=drop,
                reason=(
                    "sleeper_acquisition_locked"
                ),
                error=(
                    f"{add['name']} is currently locked "
                    "for acquisition in Sleeper."
                ),
                warnings=warnings,
            )

        if confirmed is not True:
            return build_blocked_transaction(
                provider=provider,
                provider_name=provider_name,
                add=add,
                drop=drop,
                reason=(
                    "unverified_sleeper_acquisition_state"
                ),
                error=(
                    f"{add['name']}'s Sleeper acquisition "
                    "state is not deterministically confirmed."
                ),
                warnings=warnings,
            )

        if availability == "FA":
            if (
                add.get(
                    "immediately_addable"
                )
                is not True
            ):
                return build_blocked_transaction(
                    provider=provider,
                    provider_name=provider_name,
                    add=add,
                    drop=drop,
                    reason=(
                        "inconsistent_sleeper_free_agent_state"
                    ),
                    error=(
                        f"{add['name']} reports FA but is "
                        "not confirmed immediately addable."
                    ),
                    warnings=warnings,
                )

            acquisition_state_confirmed = True
            transaction_executable = True
            transaction_mode = (
                "free_agent_add"
            )

        elif availability == "W":
            acquisition_state_confirmed = True
            transaction_executable = True
            transaction_mode = (
                "waiver_claim"
            )

            warnings.append(
                (
                    "Sleeper confirms this player is on "
                    "waivers. This recommendation represents "
                    "a waiver claim, not an immediate add, "
                    "and successful acquisition is not guaranteed."
                )
            )

    else:
        return build_blocked_transaction(
            provider=provider,
            provider_name=provider_name,
            add=add,
            drop=drop,
            reason=(
                "unsupported_provider_transaction_semantics"
            ),
            error=(
                "Provider-specific transaction semantics "
                "have not been established."
            ),
            warnings=warnings,
        )

    # ---------------------------------------------------------
    # Resulting roster structure
    # ---------------------------------------------------------

    resulting_roster = [
        player
        for player
        in roster_players
        if (
            normalize_name(
                player[
                    "name"
                ]
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
        for player
        in resulting_roster
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
        "provider_name": (
            provider_name
        ),
        "is_valid": True,
        "transaction_blocked": False,
        "transaction_executable": (
            transaction_executable
        ),
        "transaction_mode": (
            transaction_mode
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
            "availability": (
                availability
            ),
            "acquisition_reason": (
                add.get(
                    "acquisition_reason"
                )
            ),
            "acquisition_state_confirmed": (
                add.get(
                    "acquisition_state_confirmed",
                    acquisition_state_confirmed,
                )
            ),
            "immediately_addable": (
                add.get(
                    "immediately_addable"
                )
            ),
            "waiver_date": (
                add.get(
                    "waiver_date"
                )
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
        "errors": [],
        "warnings": warnings,
    }


@function_tool
def validate_add_drop(
    add_player: str,
    drop_player: str,
) -> str:
    """
    Deterministically validate a proposed fantasy add/drop.

    Sleeper FA players may be added immediately.

    Sleeper W players may be submitted as waiver claims.

    LOCKED or UNKNOWN Sleeper states are blocked.
    """

    return json.dumps(
        validate_transaction(
            add_player=add_player,
            drop_player=drop_player,
        ),
        indent=2,
    )
