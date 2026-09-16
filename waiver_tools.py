import json
from datetime import datetime
from pathlib import Path

from agents import function_tool

from provider_context import (
    get_current_provider,
    normalize_provider,
)


DATA_DIR = Path(__file__).parent / "data"

AVAILABLE_PLAYER_FILES = {
    "yahoo": DATA_DIR / "available_players.json",
    "sleeper": DATA_DIR / "sleeper_available_players.json",
}


ALLOWED_AVAILABILITY = {
    "yahoo": {
        "FA",
        "W",
    },
    "sleeper": {
        "UNROSTERED",
    },
}


REQUIRED_PLAYER_FIELDS = {
    "name",
    "position",
    "nfl_team",
    "availability",
}


def resolve_provider(provider=None):
    """
    Determine which fantasy provider to use.

    If a provider is explicitly supplied, use it.

    Otherwise, use the provider selected for the current
    Fantasy GM run.
    """

    if provider is None:
        return get_current_provider()

    return normalize_provider(provider)


def validate_available_player_snapshot(
    data,
    provider=None,
):
    """
    Validate an available-player snapshot.

    Yahoo currently uses:
      FA = free agent
      W  = waivers

    Sleeper currently uses:
      UNROSTERED = confirmed not owned by another roster,
                   but exact FA/waiver state is not yet known.
    """

    provider = resolve_provider(provider)

    if not isinstance(data, dict):
        raise RuntimeError(
            "Available-player snapshot must be a JSON object."
        )

    players = data.get("players")

    if not isinstance(players, list):
        raise RuntimeError(
            "Available-player snapshot must contain a players list."
        )

    errors = []

    allowed_availability = ALLOWED_AVAILABILITY[provider]

    for index, player in enumerate(players):
        if not isinstance(player, dict):
            errors.append(
                f"Player #{index + 1} is not a JSON object."
            )
            continue

        missing = [
            field
            for field in REQUIRED_PLAYER_FIELDS
            if not player.get(field)
        ]

        if missing:
            errors.append(
                f"Player #{index + 1} is missing: "
                + ", ".join(sorted(missing))
            )

        availability = player.get("availability")

        if availability not in allowed_availability:
            errors.append(
                f"{player.get('name', 'Unknown player')} has "
                f"unsupported availability value for "
                f"{provider}: {availability}"
            )

    if errors:
        raise RuntimeError(
            "Available-player snapshot failed validation: "
            + "; ".join(errors)
        )

    return True


def load_available_players(
    provider=None,
):
    """
    Load the available-player snapshot for the requested
    fantasy provider.

    If no provider is supplied, use the provider selected
    for the current Fantasy GM run.
    """

    provider = resolve_provider(provider)

    available_players_file = AVAILABLE_PLAYER_FILES[provider]

    if not available_players_file.exists():
        raise RuntimeError(
            "Available-player snapshot does not exist for "
            f"provider '{provider}': "
            f"{available_players_file}"
        )

    with available_players_file.open(
        "r",
        encoding="utf-8",
    ) as file:
        data = json.load(file)

    data.setdefault(
        "provider",
        provider,
    )

    validate_available_player_snapshot(
        data,
        provider=provider,
    )

    return data


def save_available_players_snapshot(
    players,
    source,
    last_updated=None,
    provider=None,
):
    """
    Save available-player data for the requested provider.

    If no provider is supplied, use the provider selected
    for the current Fantasy GM run.
    """

    provider = resolve_provider(provider)

    if last_updated is None:
        last_updated = (
            datetime.now()
            .astimezone()
            .date()
            .isoformat()
        )

    snapshot = {
        "provider": provider,
        "last_updated": last_updated,
        "source": source,
        "players": players,
    }

    validate_available_player_snapshot(
        snapshot,
        provider=provider,
    )

    available_players_file = AVAILABLE_PLAYER_FILES[provider]

    available_players_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with available_players_file.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            snapshot,
            file,
            indent=2,
        )

    return snapshot


def build_available_player_summary(
    provider=None,
):
    """
    Return deterministic available-player counts for
    the selected fantasy provider.
    """

    provider = resolve_provider(provider)

    data = load_available_players(provider)

    players = data.get(
        "players",
        [],
    )

    positions = sorted(
        {
            player.get(
                "position",
                "UNKNOWN",
            )
            for player in players
        }
    )

    availability_values = sorted(
        {
            player.get(
                "availability",
                "UNKNOWN",
            )
            for player in players
        }
    )

    availability_counts = {
        availability: sum(
            1
            for player in players
            if player.get("availability") == availability
        )
        for availability in availability_values
    }

    by_position = {}

    for position in positions:
        position_players = [
            player
            for player in players
            if player.get("position") == position
        ]

        position_availability_counts = {
            availability: sum(
                1
                for player in position_players
                if player.get("availability") == availability
            )
            for availability in availability_values
        }

        by_position[position] = {
            "total": len(position_players),
            "availability_counts": (
                position_availability_counts
            ),
        }

        if provider == "yahoo":
            by_position[position]["free_agents"] = (
                position_availability_counts.get(
                    "FA",
                    0,
                )
            )
            by_position[position]["waivers"] = (
                position_availability_counts.get(
                    "W",
                    0,
                )
            )

        if provider == "sleeper":
            by_position[position]["unrostered"] = (
                position_availability_counts.get(
                    "UNROSTERED",
                    0,
                )
            )

    summary = {
        "provider": provider,
        "last_updated": data.get(
            "last_updated"
        ),
        "source": data.get(
            "source",
            "unknown",
        ),
        "total_players": len(
            players
        ),
        "availability_counts": availability_counts,
        "by_position": by_position,
    }

    if provider == "yahoo":
        summary["free_agents"] = (
            availability_counts.get(
                "FA",
                0,
            )
        )
        summary["waivers"] = (
            availability_counts.get(
                "W",
                0,
            )
        )

    if provider == "sleeper":
        summary["unrostered"] = (
            availability_counts.get(
                "UNROSTERED",
                0,
            )
        )

    return summary


@function_tool
def get_available_players(
    provider: str | None = None,
) -> str:
    """
    Return players represented as available for the selected
    fantasy provider.

    If provider is omitted, use the provider selected for
    the current Fantasy GM run.
    """

    return json.dumps(
        load_available_players(provider),
        indent=2,
    )


@function_tool
def get_available_player_summary(
    provider: str | None = None,
) -> str:
    """
    Return deterministic available-player counts for the
    selected fantasy provider.
    """

    return json.dumps(
        build_available_player_summary(provider),
        indent=2,
    )