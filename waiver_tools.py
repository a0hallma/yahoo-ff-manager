import json
from datetime import datetime
from pathlib import Path

from agents import function_tool


AVAILABLE_PLAYERS_FILE = (
    Path(__file__).parent
    / "data"
    / "available_players.json"
)


REQUIRED_PLAYER_FIELDS = {
    "name",
    "position",
    "nfl_team",
    "availability",
}


def validate_available_player_snapshot(data):
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

        if availability not in {
            "FA",
            "W",
        }:
            errors.append(
                f"{player.get('name', 'Unknown player')} has "
                f"unsupported availability value: "
                f"{availability}"
            )

    if errors:
        raise RuntimeError(
            "Available-player snapshot failed validation: "
            + "; ".join(errors)
        )

    return True


def load_available_players():
    """
    Return the authoritative available-player snapshot currently
    available to the Fantasy GM.

    Today this comes from the local Yahoo snapshot file.

    Once Yahoo API access is available, this function can be changed
    to refresh from Yahoo while preserving the same return structure
    for every other Fantasy GM component.
    """

    if not AVAILABLE_PLAYERS_FILE.exists():
        raise RuntimeError(
            "Available-player snapshot does not exist: "
            f"{AVAILABLE_PLAYERS_FILE}"
        )

    with open(
        AVAILABLE_PLAYERS_FILE,
        "r",
        encoding="utf-8",
    ) as f:
        data = json.load(f)

    validate_available_player_snapshot(
        data
    )

    return data


def save_available_players_snapshot(
    players,
    source,
    last_updated=None,
):
    """
    Save available-player data using the common snapshot format.

    This is the interface the future Yahoo API refresh process can
    use after it retrieves and normalizes live Yahoo player data.
    """

    if last_updated is None:
        last_updated = (
            datetime.now()
            .astimezone()
            .date()
            .isoformat()
        )

    snapshot = {
        "last_updated": last_updated,
        "source": source,
        "players": players,
    }

    validate_available_player_snapshot(
        snapshot
    )

    AVAILABLE_PLAYERS_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with open(
        AVAILABLE_PLAYERS_FILE,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            snapshot,
            f,
            indent=2,
        )

    return snapshot


def build_available_player_summary():
    data = load_available_players()

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

    by_position = {}

    for position in positions:
        position_players = [
            player
            for player in players
            if player.get(
                "position"
            ) == position
        ]

        by_position[position] = {
            "total": len(
                position_players
            ),
            "free_agents": sum(
                1
                for player
                in position_players
                if player.get(
                    "availability"
                ) == "FA"
            ),
            "waivers": sum(
                1
                for player
                in position_players
                if player.get(
                    "availability"
                ) == "W"
            ),
        }

    return {
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
        "free_agents": sum(
            1
            for player in players
            if player.get(
                "availability"
            ) == "FA"
        ),
        "waivers": sum(
            1
            for player in players
            if player.get(
                "availability"
            ) == "W"
        ),
        "by_position": by_position,
    }


@function_tool
def get_available_players() -> str:
    """
    Return players currently represented as available in my Yahoo
    Fantasy Football league for waiver-wire and free-agent analysis.

    The response includes source and last-updated information so the
    caller can determine whether availability is fresh enough to use.
    """

    return json.dumps(
        load_available_players(),
        indent=2,
    )


@function_tool
def get_available_player_summary() -> str:
    """
    Return deterministic counts of available fantasy players,
    including totals by position, free-agent versus waiver status,
    snapshot source, and last-updated date.
    """

    return json.dumps(
        build_available_player_summary(),
        indent=2,
    )