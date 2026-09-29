import csv
import io
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from agents import function_tool

from provider_context import get_current_provider, get_provider_display_name
from league_tools import load_league_settings
from roster_tools import load_roster

CACHE_FILE = Path(__file__).parent / "data" / "nfl_schedule_cache.json"
EASTERN = ZoneInfo("America/New_York")

NFLVERSE_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"

MIN_EXPECTED_GAMES = 8
MAX_CACHE_AGE_HOURS = 96

NFL_TEAMS = {
    "ARI","ATL","BAL","BUF","CAR","CHI","CIN","CLE","DAL","DEN","DET","GB",
    "HOU","IND","JAX","KC","LV","LAC","LAR","MIA","MIN","NE","NO","NYG",
    "NYJ","PHI","PIT","SF","SEA","TB","TEN","WAS",
}

TEAM_ALIASES = {
    "JAC": "JAX",
    "WSH": "WAS",
    "OAK": "LV",
    "SD": "LAC",
    "STL": "LAR",
    "LA": "LAR",
}


def load_json(path):
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def get_season_and_week():
    league = load_league_settings()
    roster = load_roster()
    return int(league["season"]), int(roster["week"])


def normalize_team_abbreviation(value):
    value = str(value or "").strip().upper()
    value = TEAM_ALIASES.get(value, value)
    if value not in NFL_TEAMS:
        raise RuntimeError(
            f"Unknown NFL team abbreviation returned by schedule source: {value!r}"
        )
    return value


def validate_games(games, source_name):
    if len(games) < MIN_EXPECTED_GAMES:
        raise RuntimeError(
            f"Only {len(games)} games were parsed from {source_name}."
        )

    seen_matchups = set()
    seen_teams = set()

    for game in games:
        away = normalize_team_abbreviation(game.get("away"))
        home = normalize_team_abbreviation(game.get("home"))

        if away == home:
            raise RuntimeError(f"Invalid {source_name} matchup: {away} vs {home}.")

        matchup = (away, home)

        if matchup in seen_matchups:
            raise RuntimeError(
                f"Duplicate {source_name} matchup: {away} at {home}."
            )

        if away in seen_teams or home in seen_teams:
            raise RuntimeError(
                f"{source_name} returned a team more than once in the same week."
            )

        kickoff = datetime.fromisoformat(game["kickoff"])
        if kickoff.tzinfo is None:
            raise RuntimeError(
                f"{source_name} returned a kickoff without timezone information."
            )

        seen_matchups.add(matchup)
        seen_teams.add(away)
        seen_teams.add(home)


def save_cache(data):
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with CACHE_FILE.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)


def load_cache(season, week):
    if not CACHE_FILE.exists():
        return None

    try:
        data = load_json(CACHE_FILE)
    except Exception:
        return None

    if int(data.get("season", -1)) != season or int(data.get("week", -1)) != week:
        return None

    try:
        validate_games(data.get("games", []), "cached schedule")
    except Exception:
        return None

    fetched_at = data.get("fetched_at")
    if not fetched_at:
        return None

    try:
        fetched = datetime.fromisoformat(fetched_at)
        if fetched.tzinfo is None:
            return None

        age = datetime.now(EASTERN) - fetched.astimezone(EASTERN)
        if age > timedelta(hours=MAX_CACHE_AGE_HOURS):
            return None
    except Exception:
        return None

    data["using_cache"] = True
    return data


def fetch_nflverse_schedule(season, week):
    response = requests.get(
        NFLVERSE_URL,
        headers={"User-Agent": "fantasy-gm/1.0"},
        timeout=30,
    )
    response.raise_for_status()

    reader = csv.DictReader(io.StringIO(response.text))
    games = []

    for row in reader:
        try:
            row_season = int(row.get("season", -1))
            row_week = int(row.get("week", -1))
        except (TypeError, ValueError):
            continue

        if row_season != season or row_week != week:
            continue

        if str(row.get("game_type", "")).strip().upper() != "REG":
            continue

        gameday = str(row.get("gameday", "")).strip()
        gametime = str(row.get("gametime", "")).strip()

        if not gameday or not gametime:
            raise RuntimeError(
                f"nflverse returned a Week {week} game without gameday/gametime."
            )

        kickoff = datetime.strptime(
            f"{gameday} {gametime}",
            "%Y-%m-%d %H:%M",
        ).replace(tzinfo=EASTERN)

        away = normalize_team_abbreviation(row.get("away_team"))
        home = normalize_team_abbreviation(row.get("home_team"))

        games.append(
            {
                "away": away,
                "home": home,
                "kickoff": kickoff.isoformat(),
            }
        )

    games.sort(key=lambda game: game["kickoff"])
    validate_games(games, "nflverse")

    return {
        "season": season,
        "week": week,
        "source": "nflverse",
        "source_url": NFLVERSE_URL,
        "fetched_at": datetime.now(EASTERN).isoformat(),
        "using_cache": False,
        "games": games,
    }


def parse_espn_datetime(value):
    value = str(value or "").strip()

    if not value:
        raise RuntimeError("ESPN event did not contain a kickoff time.")

    if value.endswith("Z"):
        value = value[:-1] + "+00:00"

    kickoff = datetime.fromisoformat(value)

    if kickoff.tzinfo is None:
        raise RuntimeError("ESPN kickoff did not contain timezone information.")

    return kickoff.astimezone(EASTERN)


def fetch_espn_schedule(season, week):
    response = requests.get(
        ESPN_URL,
        params={
            "dates": str(season),
            "seasontype": "2",
            "week": str(week),
        },
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        },
        timeout=20,
    )
    response.raise_for_status()

    payload = response.json()
    events = payload.get("events", [])

    if not events:
        raise RuntimeError(
            f"ESPN returned no NFL events for {season} Week {week}."
        )

    games = []
    seen = set()

    for event in events:
        competitions = event.get("competitions", [])
        if not competitions:
            raise RuntimeError("ESPN event did not contain a competition.")

        competition = competitions[0]
        away = None
        home = None

        for competitor in competition.get("competitors", []):
            abbreviation = normalize_team_abbreviation(
                competitor.get("team", {}).get("abbreviation")
            )
            home_away = str(competitor.get("homeAway", "")).strip().lower()

            if home_away == "away":
                away = abbreviation
            elif home_away == "home":
                home = abbreviation

        if not away or not home:
            raise RuntimeError(
                "ESPN event did not contain both home and away teams."
            )

        kickoff = parse_espn_datetime(
            event.get("date") or competition.get("date")
        )

        game_key = (away, home, kickoff.isoformat())
        if game_key in seen:
            continue

        seen.add(game_key)
        games.append(
            {
                "away": away,
                "home": home,
                "kickoff": kickoff.isoformat(),
            }
        )

    games.sort(key=lambda game: game["kickoff"])
    validate_games(games, "ESPN")

    return {
        "season": season,
        "week": week,
        "source": "ESPN",
        "source_url": response.url,
        "fetched_at": datetime.now(EASTERN).isoformat(),
        "using_cache": False,
        "games": games,
    }


def fetch_official_schedule():
    season, week = get_season_and_week()
    errors = []

    try:
        data = fetch_nflverse_schedule(season, week)
        save_cache(data)
        return data
    except Exception as exc:
        errors.append(f"nflverse: {exc}")

    try:
        data = fetch_espn_schedule(season, week)
        data["fallback_errors"] = list(errors)
        save_cache(data)
        return data
    except Exception as exc:
        errors.append(f"ESPN: {exc}")

    cached = load_cache(season, week)

    if cached:
        cached["fetch_error"] = " | ".join(errors)
        return cached

    raise RuntimeError(
        "Unable to retrieve the NFL schedule and no valid matching cache exists: "
        + " | ".join(errors)
    )


def build_roster_schedule():
    provider = get_current_provider()
    provider_name = get_provider_display_name()
    schedule = fetch_official_schedule()
    roster = load_roster()

    games_by_team = {}

    for game in schedule["games"]:
        away = game["away"]
        home = game["home"]

        games_by_team[away] = {
            "opponent": home,
            "location": "away",
            "kickoff": game["kickoff"],
        }

        games_by_team[home] = {
            "opponent": away,
            "location": "home",
            "kickoff": game["kickoff"],
        }

    players = []

    for player in roster["players"]:
        team = normalize_team_abbreviation(player["nfl_team"])
        game = games_by_team.get(team)

        players.append(
            {
                "name": player["name"],
                "position": player["position"],
                "lineup_slot": player["lineup_slot"],
                "nfl_team": team,
                "opponent": game["opponent"] if game else None,
                "location": game["location"] if game else None,
                "kickoff": game["kickoff"] if game else None,
                "schedule_found": game is not None,
            }
        )

    players.sort(
        key=lambda player: (
            player["kickoff"] is None,
            player["kickoff"] or "9999",
        )
    )

    return {
        "provider": provider,
        "provider_name": provider_name,
        "team_name": roster.get("team_name"),
        "season": schedule["season"],
        "week": schedule["week"],
        "schedule_source": schedule["source"],
        "schedule_source_url": schedule.get("source_url"),
        "schedule_fetched_at": schedule["fetched_at"],
        "using_cache": schedule.get("using_cache", False),
        "fetch_error": schedule.get("fetch_error"),
        "fallback_errors": schedule.get("fallback_errors", []),
        "players": players,
    }


def build_next_roster_lock():
    schedule = build_roster_schedule()
    now = datetime.now(EASTERN)
    upcoming = []

    for player in schedule["players"]:
        if not player["kickoff"]:
            continue

        kickoff = datetime.fromisoformat(player["kickoff"])

        if kickoff > now:
            upcoming.append((kickoff, player))

    if not upcoming:
        return {
            "provider": schedule.get("provider"),
            "next_lock": None,
            "players": [],
        }

    earliest = min(kickoff for kickoff, _ in upcoming)

    players = [
        player
        for kickoff, player in upcoming
        if kickoff == earliest
    ]

    return {
        "provider": schedule.get("provider"),
        "next_lock": earliest.isoformat(),
        "players": players,
        "using_cache": schedule["using_cache"],
        "schedule_fetched_at": schedule["schedule_fetched_at"],
        "schedule_source": schedule.get("schedule_source"),
    }


@function_tool
def get_roster_schedule() -> str:
    return json.dumps(
        build_roster_schedule(),
        indent=2,
    )


@function_tool
def get_next_roster_lock() -> str:
    return json.dumps(
        build_next_roster_lock(),
        indent=2,
    )

