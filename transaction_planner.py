import json
from datetime import date, datetime

from dotenv import load_dotenv
from pydantic import BaseModel
from agents import Agent, Runner, WebSearchTool

from provider_context import (
    get_current_provider,
    get_provider_display_name,
)
from league_tools import get_league_settings
from roster_tools import get_my_roster
from waiver_tools import (
    load_available_players,
    build_available_player_summary,
    get_available_players,
    get_available_player_summary,
)
from transaction_tools import (
    validate_transaction,
    validate_add_drop,
)


load_dotenv()


MODEL_NAME = "gpt-5.6-luna"

MAX_AVAILABLE_PLAYER_AGE_DAYS = 1


with open(
    "gm_instructions.txt",
    "r",
    encoding="utf-8",
) as file:
    GM_INSTRUCTIONS = file.read()


class TransactionRecommendation(BaseModel):
    recommend_move: bool
    add_player: str | None = None
    drop_player: str | None = None
    rationale: str
    confidence: str


TRANSACTION_PLANNER_INSTRUCTIONS = GM_INSTRUCTIONS + """

You are evaluating whether my fantasy roster should make one
add/drop move.

Return a structured TransactionRecommendation.

Provider isolation requirements:

- Use only the fantasy provider selected for the current run.
- Do not mix roster, league, or available-player data between
  fantasy providers.
- The supplied provider data is authoritative for availability.
- Web research cannot establish fantasy-provider availability.

Requirements:

- Use my current roster and league settings.
- Use the supplied available-player data.
- Rank players by marginal value to MY roster, not standalone
  fantasy value.
- Research current-season player role, workload, depth-chart,
  and other material football information when useful.
- Do not force a transaction.
- recommend_move=false is valid when no move meaningfully
  improves the roster.
- If recommend_move=true, provide exactly one add player and
  one drop player.
- The transaction will be independently validated by Python
  after you respond.
- Do not state or imply that your proposed transaction has
  already been validated.
- Your rationale should explain football value only, not
  validation status.

Availability rules:

- Treat the selected provider's available-player snapshot as
  authoritative for the availability state it actually reports.
- Do not claim a player is currently available unless that
  player appears in the supplied available-player data.
- Do not translate UNROSTERED into free agent or waiver claim.
- Do not infer immediate addability unless provider data
  establishes it.
- Web research may establish football value, role, news,
  or upside.
- Web research does NOT establish fantasy-provider
  acquisition state.
"""


transaction_agent = Agent(
    name="Fantasy Transaction Planner",
    instructions=TRANSACTION_PLANNER_INSTRUCTIONS,
    model=MODEL_NAME,
    output_type=TransactionRecommendation,
    tools=[
        get_league_settings,
        get_my_roster,
        get_available_players,
        get_available_player_summary,
        validate_add_drop,
        WebSearchTool(),
    ],
)


def parse_snapshot_date(value):
    if not value:
        return None

    value = str(
        value
    ).strip()

    try:
        parsed_datetime = (
            datetime.fromisoformat(
                value.replace(
                    "Z",
                    "+00:00",
                )
            )
        )

        return (
            parsed_datetime.date()
        )

    except ValueError:
        pass

    try:
        return date.fromisoformat(
            value
        )

    except ValueError:
        return None


def get_available_player_freshness(
    max_age_days=MAX_AVAILABLE_PLAYER_AGE_DAYS,
):
    provider = get_current_provider()
    provider_name = get_provider_display_name()

    available_data = (
        load_available_players()
    )

    if not isinstance(
        available_data,
        dict,
    ):
        return {
            "provider": provider,
            "provider_name": provider_name,
            "is_fresh": False,
            "last_updated": None,
            "age_days": None,
            "max_age_days": max_age_days,
            "reason": (
                "Available-player data is not in the "
                "expected snapshot format."
            ),
        }

    last_updated = (
        available_data.get(
            "last_updated"
        )
    )

    snapshot_date = (
        parse_snapshot_date(
            last_updated
        )
    )

    if snapshot_date is None:
        return {
            "provider": provider,
            "provider_name": provider_name,
            "is_fresh": False,
            "last_updated": last_updated,
            "age_days": None,
            "max_age_days": max_age_days,
            "reason": (
                "Available-player snapshot has no valid "
                "last_updated date."
            ),
        }

    today = (
        datetime.now()
        .astimezone()
        .date()
    )

    age_days = (
        today
        - snapshot_date
    ).days

    if age_days < 0:
        return {
            "provider": provider,
            "provider_name": provider_name,
            "is_fresh": False,
            "last_updated": last_updated,
            "age_days": age_days,
            "max_age_days": max_age_days,
            "reason": (
                "Available-player snapshot date is "
                "in the future."
            ),
        }

    is_fresh = (
        age_days
        <= max_age_days
    )

    if is_fresh:
        reason = (
            f"{provider_name} available-player snapshot "
            "is fresh enough for evaluation."
        )

    else:
        reason = (
            f"{provider_name} available-player snapshot "
            f"is {age_days} days old. Maximum allowed "
            f"age is {max_age_days} day(s)."
        )

    return {
        "provider": provider,
        "provider_name": provider_name,
        "is_fresh": is_fresh,
        "last_updated": last_updated,
        "age_days": age_days,
        "max_age_days": max_age_days,
        "reason": reason,
    }


def build_blocked_recommendation(
    rationale,
):
    return TransactionRecommendation(
        recommend_move=False,
        add_player=None,
        drop_player=None,
        rationale=rationale,
        confidence="Blocked",
    )


def build_validated_transaction(
    max_attempts=3,
):
    provider = get_current_provider()
    provider_name = get_provider_display_name()

    freshness = (
        get_available_player_freshness()
    )

    # ---------------------------------------------------------
    # 1. Snapshot freshness gate
    # ---------------------------------------------------------

    if not freshness[
        "is_fresh"
    ]:
        recommendation = (
            build_blocked_recommendation(
                (
                    "Do not execute an add/drop transaction "
                    f"until {provider_name} availability is "
                    "refreshed. "
                    + freshness["reason"]
                )
            )
        )

        return {
            "provider": provider,
            "provider_name": provider_name,
            "recommend_move": False,
            "attempts": 0,
            "recommendation": (
                recommendation.model_dump()
            ),
            "validation": None,
            "availability_check": freshness,
            "transaction_blocked": True,
            "blocked_reason": (
                "stale_available_player_snapshot"
            ),
        }

    # ---------------------------------------------------------
    # 2. Provider acquisition-semantics gate
    # ---------------------------------------------------------

    if provider == "sleeper":
        recommendation = (
            build_blocked_recommendation(
                (
                    "Sleeper currently confirms which players "
                    "are unrostered, but it does not yet "
                    "establish whether each player is an "
                    "immediately addable free agent or subject "
                    "to waivers. Executable add/drop analysis "
                    "is therefore blocked until that acquisition "
                    "state is verified."
                )
            )
        )

        return {
            "provider": provider,
            "provider_name": provider_name,
            "recommend_move": False,
            "attempts": 0,
            "recommendation": (
                recommendation.model_dump()
            ),
            "validation": None,
            "availability_check": freshness,
            "acquisition_check": {
                "is_confirmed": False,
                "reported_state": "UNROSTERED",
                "immediate_addability_confirmed": False,
                "reason": (
                    "UNROSTERED does not establish immediate "
                    "addability versus waivers."
                ),
            },
            "transaction_blocked": True,
            "blocked_reason": (
                "unverified_sleeper_acquisition_state"
            ),
        }

    # ---------------------------------------------------------
    # 3. Normal transaction evaluation
    # ---------------------------------------------------------

    availability_summary = (
        build_available_player_summary()
    )

    prompt = f"""
Evaluate my current fantasy roster and currently represented
available players.

CURRENT FANTASY PROVIDER:
{provider_name} ({provider})

Determine the single best add/drop transaction I should make
right now.

Do not force a move. If standing pat is better, return
recommend_move=false.

The available-player snapshot passed deterministic freshness
validation.

AVAILABILITY FRESHNESS:

{json.dumps(freshness, indent=2)}

AVAILABLE-PLAYER SUMMARY:

{json.dumps(availability_summary, indent=2)}

Only recommend an add player who exists in the authoritative
{provider_name} available-player data.

Preserve the provider's actual availability state.

Do not use web search to determine fantasy-provider availability.
"""

    last_validation = None

    for attempt in range(
        1,
        max_attempts + 1,
    ):
        result = Runner.run_sync(
            transaction_agent,
            prompt,
        )

        recommendation = (
            result.final_output_as(
                TransactionRecommendation,
                raise_if_incorrect_type=True,
            )
        )

        if not recommendation.recommend_move:
            return {
                "provider": provider,
                "provider_name": provider_name,
                "recommend_move": False,
                "attempts": attempt,
                "recommendation": (
                    recommendation.model_dump()
                ),
                "validation": None,
                "availability_check": freshness,
                "transaction_blocked": False,
            }

        if (
            not recommendation.add_player
            or not recommendation.drop_player
        ):
            validation = {
                "provider": provider,
                "is_valid": False,
                "transaction_blocked": False,
                "errors": [
                    (
                        "A recommended transaction must "
                        "contain both an add player and "
                        "a drop player."
                    )
                ],
                "warnings": [],
            }

        else:
            validation = (
                validate_transaction(
                    recommendation.add_player,
                    recommendation.drop_player,
                )
            )

        # A deterministic provider restriction is a terminal
        # blocked result, not an invitation for the AI to retry.
        if validation.get(
            "transaction_blocked",
            False,
        ):
            return {
                "provider": provider,
                "provider_name": provider_name,
                "recommend_move": False,
                "attempts": attempt,
                "recommendation": (
                    recommendation.model_dump()
                ),
                "validation": validation,
                "availability_check": freshness,
                "transaction_blocked": True,
                "blocked_reason": (
                    validation.get(
                        "block_reason",
                        "provider_transaction_block",
                    )
                ),
            }

        if validation[
            "is_valid"
        ]:
            return {
                "provider": provider,
                "provider_name": provider_name,
                "recommend_move": True,
                "attempts": attempt,
                "recommendation": (
                    recommendation.model_dump()
                ),
                "validation": validation,
                "availability_check": freshness,
                "transaction_blocked": False,
            }

        last_validation = validation

        prompt = f"""
Your previous transaction failed deterministic Python
validation.

CURRENT FANTASY PROVIDER:
{provider_name} ({provider})

AUTHORITATIVE AVAILABILITY FRESHNESS:

{json.dumps(freshness, indent=2)}

PREVIOUS RECOMMENDATION:

{recommendation.model_dump_json(indent=2)}

VALIDATION ERRORS:

{json.dumps(validation["errors"], indent=2)}

Re-evaluate the roster and return either:

1. a corrected valid add/drop transaction, or
2. recommend_move=false if no valid worthwhile move exists.

Only recommend players contained in the selected provider's
authoritative available-player data.

Do not use web search to infer fantasy-provider availability.
"""

    last_errors = (
        last_validation["errors"]
        if last_validation
        else "unknown"
    )

    raise RuntimeError(
        "Unable to generate a valid transaction after "
        f"{max_attempts} attempts. "
        f"Last validation errors: {last_errors}"
    )
