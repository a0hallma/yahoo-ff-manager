import re

import requests
from bs4 import BeautifulSoup

from schedule_tools import (
    NFL_URL,
    GAME_PATTERN,
    TEAM_PATTERN,
    TEAM_ABBREVIATIONS,
    build_kickoff,
)


COMPLETED_GAME_PATTERN = re.compile(
    rf"(?P<away>{TEAM_PATTERN})\s+\d+,\s+"
    rf"(?P<home>{TEAM_PATTERN})\s+\d+,\s+"
    rf"FINAL(?:/OT)?,\s+"
    rf"(?P<weekday>"
    rf"Monday|Tuesday|Wednesday|Thursday|"
    rf"Friday|Saturday|Sunday"
    rf"),\s+"
    rf"(?P<month>[A-Za-z]+)\s+"
    rf"(?P<day>\d{{1,2}})(?:st|nd|rd|th)",
    re.IGNORECASE,
)


def fetch_week_schedule(
    season,
    week,
    timeout=20,
):
    """
    Fetch one arbitrary NFL week.

    Supports both:
      - upcoming games with exact kickoff times,
      - completed games where NFL.com removes the kickoff
        time and displays the final score instead.

    For completed games, noon Eastern is used as a
    date-only placeholder. Acquisition-state logic only
    needs to know that the team's game occurred on that
    calendar day before the weekly waiver boundary.
    """

    url = NFL_URL.format(
        season=season,
        week=week,
    )

    response = requests.get(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "Chrome/151 Safari/537.36"
            )
        },
        timeout=timeout,
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    page_text = " ".join(
        soup.stripped_strings
    )

    games = []
    seen_matchups = set()

    # -----------------------------------------------------
    # Upcoming / not-yet-final games
    # -----------------------------------------------------

    for match in GAME_PATTERN.finditer(
        page_text
    ):
        away_name = match.group(
            "away"
        )

        home_name = match.group(
            "home"
        )

        away = TEAM_ABBREVIATIONS[
            away_name
        ]

        home = TEAM_ABBREVIATIONS[
            home_name
        ]

        matchup_key = (
            away,
            home,
        )

        if matchup_key in seen_matchups:
            continue

        kickoff = build_kickoff(
            season,
            match.group(
                "month"
            ),
            int(
                match.group(
                    "day"
                )
            ),
            match.group(
                "time"
            ),
            match.group(
                "ampm"
            ).upper(),
        )

        seen_matchups.add(
            matchup_key
        )

        games.append(
            {
                "away": away,
                "home": home,
                "kickoff": (
                    kickoff.isoformat()
                ),
                "kickoff_precision": (
                    "exact"
                ),
                "game_status": (
                    "scheduled"
                ),
            }
        )

    # -----------------------------------------------------
    # Completed games
    #
    # NFL.com removes kickoff time once the game is final.
    # Noon Eastern is intentionally used only as a
    # date-level placeholder.
    # -----------------------------------------------------

    for match in (
        COMPLETED_GAME_PATTERN.finditer(
            page_text
        )
    ):
        away_name = match.group(
            "away"
        )

        home_name = match.group(
            "home"
        )

        away = TEAM_ABBREVIATIONS[
            away_name
        ]

        home = TEAM_ABBREVIATIONS[
            home_name
        ]

        matchup_key = (
            away,
            home,
        )

        if matchup_key in seen_matchups:
            continue

        kickoff = build_kickoff(
            season,
            match.group(
                "month"
            ),
            int(
                match.group(
                    "day"
                )
            ),
            "12:00",
            "PM",
        )

        seen_matchups.add(
            matchup_key
        )

        games.append(
            {
                "away": away,
                "home": home,
                "kickoff": (
                    kickoff.isoformat()
                ),
                "kickoff_precision": (
                    "date_only"
                ),
                "game_status": (
                    "final"
                ),
            }
        )

    if len(games) < 8:
        raise RuntimeError(
            f"Only {len(games)} games were parsed "
            f"for NFL Week {week}."
        )

    return {
        "season": int(
            season
        ),
        "week": int(
            week
        ),
        "source": "NFL.com",
        "source_url": url,
        "games": games,
    }
