import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from agents import function_tool


LEAGUE_FILE = Path(__file__).parent / "data" / "league_settings.json"
ROSTER_FILE = Path(__file__).parent / "data" / "roster.json"
CACHE_FILE = Path(__file__).parent / "data" / "nfl_schedule_cache.json"

EASTERN = ZoneInfo("America/New_York")

NFL_URL = "https://www.nfl.com/schedules/{season}/by-week/week-{week}"

TEAM_ABBREVIATIONS = {
    "Cardinals": "ARI",
    "Falcons": "ATL",
    "Ravens": "BAL",
    "Bills": "BUF",
    "Panthers": "CAR",
    "Bears": "CHI",
    "Bengals": "CIN",
    "Browns": "CLE",
    "Cowboys": "DAL",
    "Broncos": "DEN",
    "Lions": "DET",
    "Packers": "GB",
    "Texans": "HOU",
    "Colts": "IND",
    "Jaguars": "JAX",
    "Chiefs": "KC",
    "Raiders": "LV",
    "Chargers": "LAC",
    "Rams": "LAR",
    "Dolphins": "MIA",
    "Vikings": "MIN",
    "Patriots": "NE",
    "Saints": "NO",
    "Giants": "NYG",
    "Jets": "NYJ",
    "Eagles": "PHI",
    "Steelers": "PIT",
    "49ers": "SF",
    "Seahawks": "SEA",
    "Buccaneers": "TB",
    "Titans": "TEN",
    "Commanders": "WAS",
}


TEAM_PATTERN = "|".join(
    sorted(
        (re.escape(name) for name in TEAM_ABBREVIATIONS),
        key=len,
        reverse=True,
    )
)

GAME_PATTERN = re.compile(
    rf"(?P<away>{TEAM_PATTERN}) at "
    rf"(?P<home>{TEAM_PATTERN}), "
    rf"(?P<weekday>Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday), "
    rf"(?P<month>[A-Za-z]+) "
    rf"(?P<day>\d{{1,2}})(?:st|nd|rd|th), "
    rf"(?P<time>\d{{1,2}}:\d{{2}}) "
    rf"(?P<ampm>AM|PM)",
    re.IGNORECASE,
)


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_season_and_week():
    league = load_json(LEAGUE_FILE)
    roster = load_json(ROSTER_FILE)

    season = int(league["season"])
    week = int(roster["week"])

    return season, week


def build_kickoff(season, month, day, time_value, ampm):
    month_number = datetime.strptime(month, "%B").month

    # NFL regular seasons cross into January of the following calendar year.
    calendar_year = season + 1 if month_number <= 2 else season

    dt = datetime.strptime(
        f"{calendar_year} {month} {day} {time_value} {ampm}",
        "%Y %B %d %I:%M %p",
    )

    return dt.replace(tzinfo=EASTERN)


def save_cache(data):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_cache(season, week):
    if not CACHE_FILE.exists():
        return None

    data = load_json(CACHE_FILE)

    if data.get("season") != season or data.get("week") != week:
        return None

    data["using_cache"] = True
    return data


def fetch_official_schedule():
    season, week = get_season_and_week()
    url = NFL_URL.format(season=season, week=week)

    try:
        response = requests.get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/151 Safari/537.36"
                )
            },
            timeout=20,
        )

        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        page_text = " ".join(soup.stripped_strings)

        games = []
        seen = set()

        for match in GAME_PATTERN.finditer(page_text):
            away_name = match.group("away")
            home_name = match.group("home")

            away = TEAM_ABBREVIATIONS[away_name]
            home = TEAM_ABBREVIATIONS[home_name]

            kickoff = build_kickoff(
                season,
                match.group("month"),
                int(match.group("day")),
                match.group("time"),
                match.group("ampm").upper(),
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

        # A regular-season week should have substantially more than a few games.
        # If parsing suddenly returns very little, assume NFL.com changed rather
        # than silently trusting incomplete data.
        if len(games) < 8:
            raise RuntimeError(
                f"Only {len(games)} games were parsed from NFL.com."
            )

        data = {
            "season": season,
            "week": week,
            "source": "NFL.com",
            "source_url": url,
            "fetched_at": datetime.now(EASTERN).isoformat(),
            "using_cache": False,
            "games": games,
        }

        save_cache(data)

        return data

    except Exception as exc:
        cached = load_cache(season, week)

        if cached:
            cached["fetch_error"] = str(exc)
            return cached

        raise RuntimeError(
            f"Unable to retrieve the NFL schedule and no cache exists: {exc}"
        )


def build_roster_schedule():
    schedule = fetch_official_schedule()
    roster = load_json(ROSTER_FILE)

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
        team = player["nfl_team"]
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
        key=lambda p: (
            p["kickoff"] is None,
            p["kickoff"] or "9999",
        )
    )

    return {
        "season": schedule["season"],
        "week": schedule["week"],
        "schedule_source": schedule["source"],
        "schedule_fetched_at": schedule["fetched_at"],
        "using_cache": schedule.get("using_cache", False),
        "fetch_error": schedule.get("fetch_error"),
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
        "next_lock": earliest.isoformat(),
        "players": players,
        "using_cache": schedule["using_cache"],
        "schedule_fetched_at": schedule["schedule_fetched_at"],
    }


@function_tool
def get_roster_schedule() -> str:
    """
    Fetch the current official NFL.com schedule and return the opponent
    and kickoff time for every player on my fantasy roster.
    """
    return json.dumps(build_roster_schedule(), indent=2)


@function_tool
def get_next_roster_lock() -> str:
    """
    Return the earliest upcoming NFL kickoff involving anyone currently
    on my fantasy roster.
    """
    return json.dumps(build_next_roster_lock(), indent=2)