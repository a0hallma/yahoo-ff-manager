import json
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

from agents import function_tool

from provider_context import (
    get_current_provider,
    get_provider_display_name,
)
from league_tools import load_league_settings
from roster_tools import load_roster
from schedule_tools import build_roster_schedule
from waiver_tools import build_available_player_summary


EASTERN = ZoneInfo("America/New_York")


NFL_TEAMS = {
    "ARI", "ATL", "BAL", "BUF",
    "CAR", "CHI", "CIN", "CLE",
    "DAL", "DEN", "DET", "GB",
    "HOU", "IND", "JAX", "KC",
    "LV", "LAC", "LAR", "MIA",
    "MIN", "NE", "NO", "NYG",
    "NYJ", "PHI", "PIT", "SF",
    "SEA", "TB", "TEN", "WAS",
}


def add_check(checks, name, status, detail):
    checks.append(
        {
            "name": name,
            "status": status,
            "detail": detail,
        }
    )


def get_required_starters(league):
    """
    Build the expected starting-lineup structure from the
    selected league's normalized roster settings.
    """

    roster_slots = league.get(
        "roster_slots",
        {},
    )

    supported_slots = [
        "QB",
        "RB",
        "WR",
        "TE",
        "FLEX",
        "SUPERFLEX",
        "K",
        "DEF",
    ]

    required = {}

    for slot in supported_slots:
        count = roster_slots.get(
            slot,
            0,
        )

        if isinstance(count, int) and count > 0:
            required[slot] = count

    return required


def get_expected_roster_range(league):
    """
    Calculate the expected number of players from the actual
    league configuration.

    Minimum:
      starters + bench

    Maximum:
      starters + bench + IR

    Empty IR slots therefore do not produce a false warning.
    """

    roster_slots = league.get(
        "roster_slots",
        {},
    )

    required_starters = get_required_starters(
        league
    )

    starting_count = sum(
        required_starters.values()
    )

    bench_count = roster_slots.get(
        "BENCH",
        0,
    )

    ir_count = roster_slots.get(
        "IR",
        0,
    )

    minimum = (
        starting_count
        + bench_count
    )

    maximum = (
        minimum
        + ir_count
    )

    return minimum, maximum


def build_data_health_report():
    checks = []

    provider = get_current_provider()
    provider_name = get_provider_display_name()

    league = None
    roster = None

    # ---------------------------------------------------------
    # 1. Load provider-specific data
    # ---------------------------------------------------------

    try:
        league = load_league_settings()

        add_check(
            checks,
            "League settings data",
            "PASS",
            f"{provider_name} league settings loaded successfully.",
        )

    except Exception as exc:
        add_check(
            checks,
            "League settings data",
            "FAIL",
            str(exc),
        )

    try:
        roster = load_roster()

        add_check(
            checks,
            "Roster data",
            "PASS",
            f"{provider_name} roster loaded successfully.",
        )

    except Exception as exc:
        add_check(
            checks,
            "Roster data",
            "FAIL",
            str(exc),
        )

    # ---------------------------------------------------------
    # 2. League basics
    # ---------------------------------------------------------

    if league:
        season = league.get(
            "season"
        )

        if season:
            add_check(
                checks,
                "Fantasy season",
                "PASS",
                f"Season: {season}",
            )

        else:
            add_check(
                checks,
                "Fantasy season",
                "FAIL",
                "No season found in league settings.",
            )

        league_name = league.get(
            "league_name"
        )

        if league_name:
            add_check(
                checks,
                "Fantasy league",
                "PASS",
                f"{provider_name}: {league_name}",
            )

        else:
            add_check(
                checks,
                "Fantasy league",
                "FAIL",
                "No league name found.",
            )

    # ---------------------------------------------------------
    # 3. Roster integrity
    # ---------------------------------------------------------

    if roster and league:
        players = roster.get(
            "players",
            [],
        )

        player_count = len(
            players
        )

        minimum_roster_size, maximum_roster_size = (
            get_expected_roster_range(
                league
            )
        )

        if (
            minimum_roster_size
            <= player_count
            <= maximum_roster_size
        ):
            add_check(
                checks,
                "Roster player count",
                "PASS",
                (
                    f"{player_count} players loaded. "
                    f"Expected range: "
                    f"{minimum_roster_size}-"
                    f"{maximum_roster_size}."
                ),
            )

        elif player_count < minimum_roster_size:
            add_check(
                checks,
                "Roster player count",
                "WARN",
                (
                    f"Only {player_count} players loaded. "
                    f"Expected at least "
                    f"{minimum_roster_size}."
                ),
            )

        else:
            add_check(
                checks,
                "Roster player count",
                "FAIL",
                (
                    f"{player_count} players loaded, "
                    f"which exceeds the configured "
                    f"{maximum_roster_size}-player maximum."
                ),
            )

        names = [
            player.get(
                "name",
                "",
            ).strip().lower()
            for player in players
            if player.get("name")
        ]

        duplicates = [
            name
            for name, count
            in Counter(names).items()
            if count > 1
        ]

        if duplicates:
            add_check(
                checks,
                "Duplicate roster players",
                "FAIL",
                f"Duplicate players found: {duplicates}",
            )

        else:
            add_check(
                checks,
                "Duplicate roster players",
                "PASS",
                "No duplicate players found.",
            )

        invalid_teams = [
            (
                f"{player.get('name')} "
                f"({player.get('nfl_team')})"
            )
            for player in players
            if player.get(
                "nfl_team"
            ) not in NFL_TEAMS
        ]

        if invalid_teams:
            add_check(
                checks,
                "NFL team codes",
                "FAIL",
                (
                    "Invalid team assignments: "
                    + ", ".join(
                        invalid_teams
                    )
                ),
            )

        else:
            add_check(
                checks,
                "NFL team codes",
                "PASS",
                "All roster NFL team codes are valid.",
            )

        # -----------------------------------------------------
        # 4. Current starting lineup structure
        # -----------------------------------------------------

        required_starters = (
            get_required_starters(
                league
            )
        )

        starter_counts = Counter(
            player.get(
                "lineup_slot"
            )
            for player in players
            if player.get(
                "lineup_slot"
            ) in required_starters
        )

        lineup_errors = []

        for (
            slot,
            required_count,
        ) in required_starters.items():

            actual_count = (
                starter_counts.get(
                    slot,
                    0,
                )
            )

            if actual_count != required_count:
                lineup_errors.append(
                    (
                        f"{slot}: "
                        f"expected {required_count}, "
                        f"found {actual_count}"
                    )
                )

        if lineup_errors:
            add_check(
                checks,
                "Current lineup slot structure",
                "WARN",
                "; ".join(
                    lineup_errors
                ),
            )

        else:
            starting_count = sum(
                required_starters.values()
            )

            add_check(
                checks,
                "Current lineup slot structure",
                "PASS",
                (
                    f"All {starting_count} required "
                    f"starting slots are populated."
                ),
            )

    # ---------------------------------------------------------
    # 5. Available-player health
    # ---------------------------------------------------------

    try:
        available_summary = (
            build_available_player_summary()
        )

        total_available = (
            available_summary[
                "total_players"
            ]
        )

        if total_available > 0:
            if provider == "yahoo":
                detail = (
                    f"{total_available} available players loaded "
                    f"({available_summary['free_agents']} FA, "
                    f"{available_summary['waivers']} waivers)."
                )

            else:
                detail = (
                    f"{total_available} unrostered players loaded "
                    f"from Sleeper."
                )

            add_check(
                checks,
                "Available-player population",
                "PASS",
                detail,
            )

        else:
            add_check(
                checks,
                "Available-player population",
                "WARN",
                "Available-player list is empty.",
            )

        last_updated = (
            available_summary.get(
                "last_updated"
            )
        )

        if last_updated:
            try:
                updated_date = (
                    datetime.fromisoformat(
                        last_updated
                    ).date()
                )

                today = (
                    datetime.now(
                        EASTERN
                    ).date()
                )

                age_days = (
                    today
                    - updated_date
                ).days

                if age_days <= 1:
                    add_check(
                        checks,
                        "Available-player freshness",
                        "PASS",
                        (
                            f"Snapshot is "
                            f"{age_days} day(s) old."
                        ),
                    )

                else:
                    add_check(
                        checks,
                        "Available-player freshness",
                        "WARN",
                        (
                            f"Snapshot is "
                            f"{age_days} days old."
                        ),
                    )

            except Exception:
                add_check(
                    checks,
                    "Available-player freshness",
                    "WARN",
                    (
                        "Could not parse "
                        f"last_updated: {last_updated}"
                    ),
                )

        else:
            add_check(
                checks,
                "Available-player freshness",
                "WARN",
                "No last_updated value exists.",
            )

    except Exception as exc:
        add_check(
            checks,
            "Available-player summary",
            "FAIL",
            str(exc),
        )

    # ---------------------------------------------------------
    # 6. Live NFL schedule health
    # ---------------------------------------------------------

    try:
        roster_schedule = (
            build_roster_schedule()
        )

        if roster_schedule.get(
            "using_cache"
        ):
            add_check(
                checks,
                "NFL schedule source",
                "WARN",
                (
                    "NFL.com fetch failed or was unavailable. "
                    "Using the last successful cached schedule."
                ),
            )

        else:
            add_check(
                checks,
                "NFL schedule source",
                "PASS",
                (
                    "Fresh NFL.com schedule retrieved "
                    "successfully."
                ),
            )

        schedule_players = (
            roster_schedule.get(
                "players",
                [],
            )
        )

        # Make sure the schedule component is actually using
        # the roster belonging to the selected provider.
        if roster:
            expected_names = {
                player.get("name")
                for player
                in roster.get(
                    "players",
                    [],
                )
                if player.get("name")
            }

            schedule_names = {
                player.get("name")
                for player
                in schedule_players
                if player.get("name")
            }

            if expected_names != schedule_names:
                missing = sorted(
                    expected_names
                    - schedule_names
                )

                unexpected = sorted(
                    schedule_names
                    - expected_names
                )

                details = []

                if missing:
                    details.append(
                        "Missing from schedule: "
                        + ", ".join(
                            missing
                        )
                    )

                if unexpected:
                    details.append(
                        "Unexpected schedule players: "
                        + ", ".join(
                            unexpected
                        )
                    )

                add_check(
                    checks,
                    "Schedule provider alignment",
                    "FAIL",
                    "; ".join(
                        details
                    ),
                )

            else:
                add_check(
                    checks,
                    "Schedule provider alignment",
                    "PASS",
                    (
                        f"Schedule matches the "
                        f"{provider_name} roster."
                    ),
                )

        missing_schedule = [
            player
            for player
            in schedule_players
            if not player.get(
                "schedule_found"
            )
        ]

        invalid_missing = [
            player
            for player
            in missing_schedule
            if player.get(
                "nfl_team"
            ) not in NFL_TEAMS
        ]

        possible_byes = [
            player
            for player
            in missing_schedule
            if player.get(
                "nfl_team"
            ) in NFL_TEAMS
        ]

        if invalid_missing:
            add_check(
                checks,
                "Roster schedule matching",
                "FAIL",
                (
                    "Invalid team codes prevented "
                    "schedule matching."
                ),
            )

        elif possible_byes:
            names = ", ".join(
                (
                    f"{player['name']} "
                    f"({player['nfl_team']})"
                )
                for player
                in possible_byes
            )

            add_check(
                checks,
                "Roster schedule matching",
                "WARN",
                (
                    "No game found for: "
                    + names
                    + ". These may be bye-week players."
                ),
            )

        else:
            add_check(
                checks,
                "Roster schedule matching",
                "PASS",
                (
                    "Every roster player matched "
                    "to an NFL game."
                ),
            )

    except Exception as exc:
        add_check(
            checks,
            "NFL schedule",
            "FAIL",
            str(exc),
        )

    # ---------------------------------------------------------
    # Overall result
    # ---------------------------------------------------------

    statuses = [
        check["status"]
        for check
        in checks
    ]

    if "FAIL" in statuses:
        overall_status = "FAIL"

    elif "WARN" in statuses:
        overall_status = "WARN"

    else:
        overall_status = "PASS"

    return {
        "provider": provider,
        "provider_name": provider_name,
        "overall_status": overall_status,
        "checked_at": datetime.now(
            EASTERN
        ).isoformat(),
        "checks": checks,
    }


@function_tool
def get_data_health() -> str:
    """
    Run deterministic health checks against the currently
    selected fantasy provider's league data, roster,
    available players, lineup structure, and NFL schedule.
    """

    return json.dumps(
        build_data_health_report(),
        indent=2,
    )