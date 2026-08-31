import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from agents import function_tool

from schedule_tools import build_roster_schedule
from waiver_tools import build_available_player_summary


DATA_DIR = Path(__file__).parent / "data"

LEAGUE_FILE = DATA_DIR / "league_settings.json"
ROSTER_FILE = DATA_DIR / "roster.json"
AVAILABLE_FILE = DATA_DIR / "available_players.json"

EASTERN = ZoneInfo("America/New_York")


REQUIRED_STARTERS = {
    "QB": 1,
    "RB": 2,
    "WR": 2,
    "TE": 1,
    "FLEX": 1,
    "K": 1,
    "DEF": 1,
}


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


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def add_check(checks, name, status, detail):
    checks.append(
        {
            "name": name,
            "status": status,
            "detail": detail,
        }
    )


def build_data_health_report():
    checks = []

    league = None
    roster = None
    available = None

    # ---------------------------------------------------------
    # 1. Required files
    # ---------------------------------------------------------

    for label, path in [
        ("League settings file", LEAGUE_FILE),
        ("Roster file", ROSTER_FILE),
        ("Available players file", AVAILABLE_FILE),
    ]:
        if not path.exists():
            add_check(
                checks,
                label,
                "FAIL",
                f"Missing file: {path}",
            )
        else:
            add_check(
                checks,
                label,
                "PASS",
                f"Found {path.name}",
            )

    # ---------------------------------------------------------
    # 2. Parse JSON
    # ---------------------------------------------------------

    try:
        league = load_json(LEAGUE_FILE)
        add_check(
            checks,
            "League settings JSON",
            "PASS",
            "League settings loaded successfully.",
        )
    except Exception as exc:
        add_check(
            checks,
            "League settings JSON",
            "FAIL",
            str(exc),
        )

    try:
        roster = load_json(ROSTER_FILE)
        add_check(
            checks,
            "Roster JSON",
            "PASS",
            "Roster loaded successfully.",
        )
    except Exception as exc:
        add_check(
            checks,
            "Roster JSON",
            "FAIL",
            str(exc),
        )

    try:
        available = load_json(AVAILABLE_FILE)
        add_check(
            checks,
            "Available players JSON",
            "PASS",
            "Available-player snapshot loaded successfully.",
        )
    except Exception as exc:
        add_check(
            checks,
            "Available players JSON",
            "FAIL",
            str(exc),
        )

    # ---------------------------------------------------------
    # 3. League basics
    # ---------------------------------------------------------

    if league:
        season = league.get("season")

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

    # ---------------------------------------------------------
    # 4. Roster integrity
    # ---------------------------------------------------------

    if roster:
        players = roster.get("players", [])
        player_count = len(players)

        if 15 <= player_count <= 17:
            add_check(
                checks,
                "Roster player count",
                "PASS",
                f"{player_count} players loaded.",
            )
        elif player_count < 15:
            add_check(
                checks,
                "Roster player count",
                "WARN",
                f"Only {player_count} players loaded. "
                "There may be an open roster spot.",
            )
        else:
            add_check(
                checks,
                "Roster player count",
                "FAIL",
                f"{player_count} players loaded, which exceeds "
                "the expected 17-slot maximum.",
            )

        names = [
            player.get("name", "").strip().lower()
            for player in players
            if player.get("name")
        ]

        duplicates = [
            name
            for name, count in Counter(names).items()
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
            f"{player.get('name')} ({player.get('nfl_team')})"
            for player in players
            if player.get("nfl_team") not in NFL_TEAMS
        ]

        if invalid_teams:
            add_check(
                checks,
                "NFL team codes",
                "FAIL",
                "Invalid team assignments: "
                + ", ".join(invalid_teams),
            )
        else:
            add_check(
                checks,
                "NFL team codes",
                "PASS",
                "All roster NFL team codes are valid.",
            )

        # -----------------------------------------------------
        # 5. Current starting lineup structure
        # -----------------------------------------------------

        starter_counts = Counter(
            player.get("lineup_slot")
            for player in players
            if player.get("lineup_slot") in REQUIRED_STARTERS
        )

        lineup_errors = []

        for slot, required_count in REQUIRED_STARTERS.items():
            actual_count = starter_counts.get(slot, 0)

            if actual_count != required_count:
                lineup_errors.append(
                    f"{slot}: expected {required_count}, found {actual_count}"
                )

        if lineup_errors:
            add_check(
                checks,
                "Current lineup slot structure",
                "WARN",
                "; ".join(lineup_errors),
            )
        else:
            add_check(
                checks,
                "Current lineup slot structure",
                "PASS",
                "All 9 required starting slots are populated.",
            )

    # ---------------------------------------------------------
    # 6. Available-player health
    # ---------------------------------------------------------

    try:
        available_summary = build_available_player_summary()

        total_available = available_summary["total_players"]

        if total_available > 0:
            add_check(
                checks,
                "Available-player population",
                "PASS",
                f"{total_available} available players loaded "
                f"({available_summary['free_agents']} FA, "
                f"{available_summary['waivers']} waivers).",
            )
        else:
            add_check(
                checks,
                "Available-player population",
                "WARN",
                "Available-player list is empty.",
            )

        last_updated = available_summary.get("last_updated")

        if last_updated:
            try:
                updated_date = datetime.fromisoformat(
                    last_updated
                ).date()

                today = datetime.now(EASTERN).date()
                age_days = (today - updated_date).days

                if age_days <= 1:
                    add_check(
                        checks,
                        "Available-player freshness",
                        "PASS",
                        f"Snapshot is {age_days} day(s) old.",
                    )
                else:
                    add_check(
                        checks,
                        "Available-player freshness",
                        "WARN",
                        f"Snapshot is {age_days} days old.",
                    )

            except Exception:
                add_check(
                    checks,
                    "Available-player freshness",
                    "WARN",
                    f"Could not parse last_updated: {last_updated}",
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
    # 7. Live NFL schedule health
    # ---------------------------------------------------------

    try:
        roster_schedule = build_roster_schedule()

        if roster_schedule.get("using_cache"):
            add_check(
                checks,
                "NFL schedule source",
                "WARN",
                "NFL.com fetch failed or was unavailable. "
                "Using the last successful cached schedule.",
            )
        else:
            add_check(
                checks,
                "NFL schedule source",
                "PASS",
                "Fresh NFL.com schedule retrieved successfully.",
            )

        schedule_players = roster_schedule.get("players", [])

        missing_schedule = [
            player
            for player in schedule_players
            if not player.get("schedule_found")
        ]

        invalid_missing = [
            player
            for player in missing_schedule
            if player.get("nfl_team") not in NFL_TEAMS
        ]

        possible_byes = [
            player
            for player in missing_schedule
            if player.get("nfl_team") in NFL_TEAMS
        ]

        if invalid_missing:
            add_check(
                checks,
                "Roster schedule matching",
                "FAIL",
                "Invalid team codes prevented schedule matching.",
            )
        elif possible_byes:
            names = ", ".join(
                f"{player['name']} ({player['nfl_team']})"
                for player in possible_byes
            )

            add_check(
                checks,
                "Roster schedule matching",
                "WARN",
                "No game found for: "
                + names
                + ". These may be bye-week players.",
            )
        else:
            add_check(
                checks,
                "Roster schedule matching",
                "PASS",
                "Every roster player matched to an NFL game.",
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

    statuses = [check["status"] for check in checks]

    if "FAIL" in statuses:
        overall_status = "FAIL"
    elif "WARN" in statuses:
        overall_status = "WARN"
    else:
        overall_status = "PASS"

    return {
        "overall_status": overall_status,
        "checked_at": datetime.now(EASTERN).isoformat(),
        "checks": checks,
    }


@function_tool
def get_data_health() -> str:
    """
    Run deterministic health checks against the fantasy league data,
    roster, available players, lineup structure, and live NFL schedule.
    """
    return json.dumps(
        build_data_health_report(),
        indent=2,
    )