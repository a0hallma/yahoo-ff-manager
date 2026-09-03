import json
from datetime import datetime
from urllib.parse import urlparse

from dotenv import load_dotenv
from pydantic import BaseModel
from agents import Agent, Runner, WebSearchTool

from roster_tools import ROSTER_FILE


load_dotenv()


MODEL_NAME = "gpt-5.6-luna"

INJURY_SNAPSHOT_FILE = "data/injury_research_snapshot.json"


class InjuryResearch(BaseModel):
    player_name: str

    exact_reported_injury: str | None = None
    injury_source_publisher: str | None = None
    injury_source_url: str | None = None
    injury_source_date: str | None = None

    latest_practice_date: str | None = None
    latest_practice_participation: str | None = None
    latest_practice_source_publisher: str | None = None
    latest_practice_source_url: str | None = None

    official_game_status: str | None = None
    official_status_source_publisher: str | None = None
    official_status_source_url: str | None = None

    newest_credible_update_datetime: str | None = None
    newest_credible_update_publisher: str | None = None
    newest_credible_update_url: str | None = None
    newest_credible_update_summary: str | None = None

    schefter_or_rapoport_update: str | None = None
    notes: str | None = None


class InjuryResearchReport(BaseModel):
    players: list[InjuryResearch]


INJURY_RESEARCH_INSTRUCTIONS = """
You are a factual NFL injury research analyst.

Your only job is to research the current injury facts for the
specific players supplied by the program.

Do NOT make fantasy lineup decisions.

Research rules:

1. Search for the newest credible information first.
   Prioritize information from the last 48 hours.

2. Source priority:
   - official NFL or team sources,
   - major national sports reporting,
   - reputable beat reporters and major local sports reporting,
   - reputable fantasy-football reporting only when necessary.

3. The Yahoo designation supplied by the program is authoritative
   only for the Yahoo roster designation.
   A Yahoo Q designation does NOT tell you the injury body part.

4. exact_reported_injury must use the exact injury description
   supported by a source.
   Do not rename an injury.
   Do not infer a body part.
   Do not turn "psoas soreness" into "groin injury."
   If no credible source establishes an exact injury, return null.

5. Practice participation must be exact.
   Examples:
   - Full
   - Limited
   - Did Not Participate

   If a source merely says a player "returned to practice" but does
   not say whether participation was full or limited, use:
   "Not specified"

   Never infer Full or Limited.

6. official_game_status means an actual official weekly game
   designation such as:
   - Questionable
   - Doubtful
   - Out

   If the official weekly status has not yet been released, return:
   "Not yet available"

   Do not convert a reporter expectation or fantasy projection into
   an official game status.

7. newest_credible_update should represent the freshest meaningful
   report you can verify.

8. Search for recent reporting from Adam Schefter and Ian Rapoport.
   If there is no verified relevant report, return null.

   If another publication quotes one of them but you cannot verify
   the direct post, clearly identify that distinction.

9. Publisher names and URLs must match.

   The publisher field must identify the organization HOSTING the
   supplied URL.

   Examples:
   - An ESPN URL must use ESPN as the publisher.
   - An NFL.com URL must use NFL.com as the publisher.
   - A Rams team URL must identify the Los Angeles Rams.

   If an article itself cites another reporter or publication,
   mention that in the summary or notes instead of pretending the
   linked URL belongs to that other publisher.

10. Use a specific article or report URL whenever possible.

    Do NOT use:
    - generic injury-index pages,
    - generic team injury tables,
    - search-result pages,
    - homepages

    as evidence for an exact injury description.

11. If current weekly practice reports are not yet available, say
    so. Older training-camp or preseason information may be used as
    background but must not be presented as current weekly status.

12. Research every supplied player and return exactly one result
    for each player. Do not add players that were not supplied.
"""


injury_research_agent = Agent(
    name="NFL Injury Fact Researcher",
    instructions=INJURY_RESEARCH_INSTRUCTIONS,
    model=MODEL_NAME,
    output_type=InjuryResearchReport,
    tools=[
        WebSearchTool(),
    ],
)


def load_flagged_roster_players():
    with open(ROSTER_FILE, "r", encoding="utf-8") as f:
        roster = json.load(f)

    flagged = []

    for player in roster.get("players", []):
        status = (
            player.get("status")
            or ""
        ).strip().upper()

        if not status:
            continue

        flagged.append(
            {
                "name": player["name"],
                "position": player["position"],
                "nfl_team": player["nfl_team"],
                "yahoo_status": status,
                "lineup_slot": player.get(
                    "lineup_slot",
                    "",
                ),
            }
        )

    return flagged


def get_url_domain(url):
    if not url:
        return ""

    parsed = urlparse(url)

    return parsed.netloc.lower()


def is_generic_injury_index(url):
    if not url:
        return False

    parsed = urlparse(url)

    domain = parsed.netloc.lower()
    path = parsed.path.lower().rstrip("/")

    if "espn.com" in domain:
        if path == "/nfl/injuries":
            return True

        if path.startswith("/nfl/injuries/_/"):
            return True

    return False


def publisher_matches_url(
    publisher,
    url,
):
    if not publisher or not url:
        return True

    publisher_lower = publisher.lower()
    domain = get_url_domain(url)

    known_domains = {
        "espn.com": [
            "espn",
        ],
        "nfl.com": [
            "nfl",
        ],
        "therams.com": [
            "rams",
            "los angeles rams",
        ],
        "chiefs.com": [
            "chiefs",
            "kansas city chiefs",
        ],
        "steelers.com": [
            "steelers",
            "pittsburgh steelers",
        ],
        "steelersnow.com": [
            "steelers now",
        ],
        "nbcsports.com": [
            "nbc",
            "pro football talk",
            "pft",
        ],
        "tennesseetitans.com": [
            "titans",
            "tennessee titans",
        ],
    }

    for domain_fragment, allowed_names in known_domains.items():
        if domain_fragment not in domain:
            continue

        return any(
            allowed_name in publisher_lower
            for allowed_name in allowed_names
        )

    return True


def validate_source(
    player_name,
    source_label,
    publisher,
    url,
    allow_not_available=False,
):
    errors = []

    if not url:
        if allow_not_available:
            return errors

        errors.append(
            f"{player_name}: {source_label} has no URL."
        )

        return errors

    parsed = urlparse(url)

    if parsed.scheme not in {
        "http",
        "https",
    }:
        errors.append(
            f"{player_name}: {source_label} URL is not "
            "a valid HTTP/HTTPS URL."
        )

    if not parsed.netloc:
        errors.append(
            f"{player_name}: {source_label} URL has "
            "no domain."
        )

    if is_generic_injury_index(url):
        errors.append(
            f"{player_name}: {source_label} uses a "
            "generic injury-index page instead of a "
            "specific article or report."
        )

    if not publisher_matches_url(
        publisher,
        url,
    ):
        errors.append(
            f"{player_name}: {source_label} publisher "
            f"'{publisher}' does not match URL domain "
            f"'{get_url_domain(url)}'."
        )

    return errors


def validate_research_results(
    flagged_players,
    research_report,
):
    errors = []

    expected_names = {
        player["name"].strip().lower()
        for player in flagged_players
    }

    returned_names = {
        player.player_name.strip().lower()
        for player in research_report.players
    }

    if expected_names != returned_names:
        missing = expected_names - returned_names
        extra = returned_names - expected_names

        if missing:
            errors.append(
                "Missing injury research for: "
                + ", ".join(sorted(missing))
            )

        if extra:
            errors.append(
                "Unexpected injury research for: "
                + ", ".join(sorted(extra))
            )

    for player in research_report.players:
        if player.exact_reported_injury:
            errors.extend(
                validate_source(
                    player_name=player.player_name,
                    source_label="injury source",
                    publisher=(
                        player.injury_source_publisher
                    ),
                    url=player.injury_source_url,
                )
            )

        if player.latest_practice_participation:
            errors.extend(
                validate_source(
                    player_name=player.player_name,
                    source_label="practice source",
                    publisher=(
                        player.latest_practice_source_publisher
                    ),
                    url=player.latest_practice_source_url,
                )
            )

        if (
            player.official_game_status
            and player.official_game_status.lower()
            != "not yet available"
        ):
            errors.extend(
                validate_source(
                    player_name=player.player_name,
                    source_label="official status source",
                    publisher=(
                        player.official_status_source_publisher
                    ),
                    url=player.official_status_source_url,
                )
            )

        if player.newest_credible_update_summary:
            errors.extend(
                validate_source(
                    player_name=player.player_name,
                    source_label="newest credible update",
                    publisher=(
                        player.newest_credible_update_publisher
                    ),
                    url=player.newest_credible_update_url,
                )
            )

    return errors


def build_injury_research_snapshot(
    max_attempts=3,
):
    flagged_players = load_flagged_roster_players()

    if not flagged_players:
        snapshot = {
            "researched_at": (
                datetime.now()
                .astimezone()
                .isoformat()
            ),
            "player_count": 0,
            "players": [],
        }

        with open(
            INJURY_SNAPSHOT_FILE,
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(
                snapshot,
                f,
                indent=2,
            )

        return snapshot

    base_prompt = f"""
Research the current injury facts for exactly these Yahoo roster
players:

{json.dumps(flagged_players, indent=2)}

The Yahoo status shown above is authoritative for the Yahoo
designation only.

For each player, determine:
- exact reported injury,
- source for that exact injury,
- latest practice information,
- actual official weekly game status if available,
- newest credible update,
- any verified recent Schefter or Rapoport reporting.

Do not make lineup recommendations.
Do not infer injury body parts.
Do not infer practice participation.
"""

    prompt = base_prompt
    last_errors = []

    for attempt in range(
        1,
        max_attempts + 1,
    ):
        result = Runner.run_sync(
            injury_research_agent,
            prompt,
        )

        research_report = result.final_output_as(
            InjuryResearchReport,
            raise_if_incorrect_type=True,
        )

        validation_errors = (
            validate_research_results(
                flagged_players,
                research_report,
            )
        )

        if not validation_errors:
            yahoo_by_name = {
                player["name"].strip().lower(): player
                for player in flagged_players
            }

            players = []

            for researched_player in research_report.players:
                research_data = (
                    researched_player.model_dump()
                )

                yahoo_player = yahoo_by_name[
                    researched_player
                    .player_name
                    .strip()
                    .lower()
                ]

                research_data["yahoo_status"] = (
                    yahoo_player["yahoo_status"]
                )

                research_data["position"] = (
                    yahoo_player["position"]
                )

                research_data["nfl_team"] = (
                    yahoo_player["nfl_team"]
                )

                research_data["roster_lineup_slot"] = (
                    yahoo_player["lineup_slot"]
                )

                players.append(
                    research_data
                )

            snapshot = {
                "researched_at": (
                    datetime.now()
                    .astimezone()
                    .isoformat()
                ),
                "player_count": len(players),
                "research_attempts": attempt,
                "players": players,
            }

            with open(
                INJURY_SNAPSHOT_FILE,
                "w",
                encoding="utf-8",
            ) as f:
                json.dump(
                    snapshot,
                    f,
                    indent=2,
                )

            return snapshot

        last_errors = validation_errors

        prompt = f"""
Your previous injury research failed deterministic Python
source validation.

ORIGINAL RESEARCH REQUEST:

{base_prompt}

VALIDATION ERRORS:

{json.dumps(validation_errors, indent=2)}

Correct every validation error and research again.

Important:
- use specific article/report URLs,
- do not use generic injury index pages,
- the publisher field must match the organization hosting the URL,
- preserve exact injury wording,
- do not infer injury body parts,
- do not infer practice participation,
- return exactly the requested players.
"""

    raise RuntimeError(
        "Unable to produce a source-valid injury research "
        f"snapshot after {max_attempts} attempts. "
        f"Last errors: {last_errors}"
    )