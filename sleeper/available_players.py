import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from sleeper.acquisition_state import (
    resolve_acquisition_state,
)
from sleeper.normalizer import (
    get_player_name,
    normalize_injury_status,
)
from sleeper.schedule_context import (
    fetch_week_schedule,
)


SLEEPER_AVAILABLE_PLAYERS_FILE = Path(
    "data/sleeper_available_players.json"
)


FANTASY_POSITIONS = {
    "QB",
    "RB",
    "WR",
    "TE",
    "K",
    "DEF",
}


def get_recent_transactions(
    client,
    league_id,
    current_week,
):
    """
    Fetch the current and immediately previous scoring
    week's transactions.

    Two weeks are sufficient for the league's current
    48-hour after-drop window while also catching an add
    immediately preceding a drop across the week boundary.
    """

    transactions = []
    errors = []

    weeks = [
        current_week
    ]

    if current_week > 1:
        weeks.append(
            current_week - 1
        )

    for week in weeks:
        try:
            week_transactions = (
                client.get_transactions(
                    league_id,
                    week,
                )
            )

            transactions.extend(
                week_transactions
            )

        except Exception as exc:
            errors.append(
                {
                    "week": week,
                    "error": str(exc),
                }
            )

    # Defensive de-duplication by Sleeper transaction ID.
    unique = {}

    for transaction in transactions:
        transaction_id = str(
            transaction.get(
                "transaction_id"
            )
            or (
                transaction.get(
                    "created"
                )
            )
        )

        unique[
            transaction_id
        ] = transaction

    return (
        list(
            unique.values()
        ),
        errors,
    )


def get_schedule_context(
    season,
    current_week,
):
    """
    Fetch current and previous NFL weeks.

    If either required schedule cannot be established, we
    retain the error and refuse to certify an apparent FA
    state. A known waiver restriction can still safely be
    reported as W.
    """

    current_week_games = []
    previous_week_games = []

    errors = []

    try:
        current_schedule = (
            fetch_week_schedule(
                season=season,
                week=current_week,
            )
        )

        current_week_games = (
            current_schedule.get(
                "games",
                [],
            )
        )

    except Exception as exc:
        errors.append(
            {
                "week": current_week,
                "error": str(exc),
            }
        )

    if current_week > 1:
        try:
            previous_schedule = (
                fetch_week_schedule(
                    season=season,
                    week=current_week - 1,
                )
            )

            previous_week_games = (
                previous_schedule.get(
                    "games",
                    [],
                )
            )

        except Exception as exc:
            errors.append(
                {
                    "week": current_week - 1,
                    "error": str(exc),
                }
            )

    return (
        current_week_games,
        previous_week_games,
        errors,
    )


def build_available_player_snapshot(
    client,
    league_id,
):
    """
    Build Sleeper's live acquisition-aware unrostered pool.

    Sleeper does not expose a single available-player endpoint.

    We derive availability from:
      1. league rosters,
      2. the active Sleeper NFL player directory,
      3. league waiver settings,
      4. current/recent transactions,
      5. previous/current NFL kickoff times.

    Resulting states:

      FA       confirmed immediately addable
      W        confirmed on waivers
      LOCKED   league adds disabled
      UNKNOWN  insufficient acquisition context
    """

    now = datetime.now(
        timezone.utc
    )

    league = client.get_league(
        league_id
    )

    league_settings = (
        league.get(
            "settings"
        )
        or {}
    )

    nfl_state = (
        client.get_nfl_state()
    )

    season = int(
        nfl_state.get(
            "season"
        )
        or league.get(
            "season"
        )
    )

    current_week = int(
        nfl_state.get(
            "week",
            1,
        )
        or 1
    )

    rosters = (
        client.get_league_rosters(
            league_id
        )
    )

    rostered_player_ids = set()

    for roster in rosters:
        for player_id in (
            roster.get(
                "players"
            )
            or []
        ):
            rostered_player_ids.add(
                str(
                    player_id
                )
            )

    transactions, transaction_errors = (
        get_recent_transactions(
            client=client,
            league_id=league_id,
            current_week=current_week,
        )
    )

    (
        current_week_games,
        previous_week_games,
        schedule_errors,
    ) = get_schedule_context(
        season=season,
        current_week=current_week,
    )

    player_map = client.get_players(
        active=True
    )

    available_players = []

    for (
        player_id,
        player,
    ) in player_map.items():
        player_id = str(
            player_id
        )

        if (
            player_id
            in rostered_player_ids
        ):
            continue

        position = player.get(
            "position"
        )

        if (
            position
            not in FANTASY_POSITIONS
        ):
            continue

        nfl_team = player.get(
            "team"
        )

        if not nfl_team:
            continue

        acquisition = (
            resolve_acquisition_state(
                player_id=player_id,
                nfl_team=nfl_team,
                league_settings=(
                    league_settings
                ),
                transactions=(
                    transactions
                ),
                current_week_games=(
                    current_week_games
                ),
                previous_week_games=(
                    previous_week_games
                ),
                now=now,
            )
        )

        # We may safely prove a player is on waivers from one
        # known restriction even if another data source failed.
        #
        # We may NOT safely prove FA unless both schedule and
        # transaction context were successfully retrieved.
        if (
            acquisition.get(
                "availability"
            )
            == "FA"
            and (
                transaction_errors
                or schedule_errors
            )
        ):
            acquisition = {
                "availability": (
                    "UNKNOWN"
                ),
                "acquisition_state_confirmed": (
                    False
                ),
                "immediately_addable": (
                    False
                ),
                "reason_code": (
                    "INCOMPLETE_ACQUISITION_CONTEXT"
                ),
                "waiver_clear_at": None,
                "drop_24h_exception": (
                    acquisition.get(
                        "drop_24h_exception",
                        False,
                    )
                ),
                "waiver_constraints": [],
            }

        available_players.append(
            {
                "player_id": (
                    player_id
                ),
                "name": (
                    get_player_name(
                        player
                    )
                ),
                "position": (
                    position
                ),
                "nfl_team": (
                    nfl_team
                ),
                "availability": (
                    acquisition.get(
                        "availability"
                    )
                ),
                "acquisition_state_confirmed": (
                    acquisition.get(
                        "acquisition_state_confirmed",
                        False,
                    )
                ),
                "immediately_addable": (
                    acquisition.get(
                        "immediately_addable",
                        False,
                    )
                ),
                "acquisition_reason": (
                    acquisition.get(
                        "reason_code"
                    )
                ),
                "waiver_date": (
                    acquisition.get(
                        "waiver_clear_at"
                    )
                ),
                "drop_24h_exception": (
                    acquisition.get(
                        "drop_24h_exception",
                        False,
                    )
                ),
                "status": (
                    normalize_injury_status(
                        player.get(
                            "injury_status"
                        )
                    )
                ),
                "search_rank": (
                    player.get(
                        "search_rank"
                    )
                ),
                "depth_chart_order": (
                    player.get(
                        "depth_chart_order"
                    )
                ),
            }
        )

    available_players.sort(
        key=lambda player: (
            player.get(
                "search_rank"
            )
            if isinstance(
                player.get(
                    "search_rank"
                ),
                (int, float),
            )
            else 999999,
            player.get(
                "name",
                "",
            ),
        )
    )

    availability_counts = Counter(
        player.get(
            "availability",
            "UNKNOWN",
        )
        for player
        in available_players
    )

    snapshot = {
        "provider": "sleeper",
        "league_id": str(
            league_id
        ),
        "season": season,
        "week": current_week,
        "last_updated": (
            now.date().isoformat()
        ),
        "generated_at": (
            now.isoformat()
        ),
        "source": (
            "live_sleeper_api_plus_nfl_schedule"
        ),
        "acquisition_context": {
            "daily_waivers": (
                league_settings.get(
                    "daily_waivers"
                )
            ),
            "waiver_clear_days": (
                league_settings.get(
                    "waiver_clear_days"
                )
            ),
            "waiver_day_of_week": (
                league_settings.get(
                    "waiver_day_of_week"
                )
            ),
            "disable_adds": (
                league_settings.get(
                    "disable_adds"
                )
            ),
            "transaction_weeks_checked": [
                current_week,
                *(
                    [
                        current_week - 1
                    ]
                    if current_week > 1
                    else []
                ),
            ],
            "transaction_errors": (
                transaction_errors
            ),
            "schedule_errors": (
                schedule_errors
            ),
        },
        "availability_counts": dict(
            availability_counts
        ),
        "players": available_players,
    }

    return snapshot


def save_available_player_snapshot(
    snapshot,
):
    """
    Save Sleeper's acquisition-aware player pool separately
    from the Yahoo available-player snapshot.
    """

    SLEEPER_AVAILABLE_PLAYERS_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with SLEEPER_AVAILABLE_PLAYERS_FILE.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            snapshot,
            file,
            indent=2,
            ensure_ascii=False,
        )

    return (
        SLEEPER_AVAILABLE_PLAYERS_FILE
    )
