import json
from datetime import (
    date,
    datetime,
)

from dotenv import load_dotenv
from pydantic import BaseModel
from agents import (
    Agent,
    Runner,
    WebSearchTool,
)

from provider_context import (
    get_current_provider,
    get_provider_display_name,
)
from league_tools import (
    get_league_settings,
)
from roster_tools import (
    get_my_roster,
)
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

# Sleeper acquisition state can change intraday when
# waivers clear, so date-only freshness is not sufficient.
MAX_SLEEPER_SNAPSHOT_AGE_MINUTES = 60


with open(
    "gm_instructions.txt",
    "r",
    encoding="utf-8",
) as file:
    GM_INSTRUCTIONS = (
        file.read()
    )


class TransactionRecommendation(
    BaseModel
):
    recommend_move: bool
    add_player: str | None = None
    drop_player: str | None = None
    rationale: str
    confidence: str


TRANSACTION_PLANNER_INSTRUCTIONS = (
    GM_INSTRUCTIONS
    + """

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
- Your rationale should explain football value rather than
  deterministic validation mechanics.

Availability rules:

Yahoo:
- FA is a free agent.
- W is a waiver-claim candidate.

Sleeper:
- FA means the player is confirmed immediately addable.
- W means the player is confirmed to be on waivers and a
  waiver claim may be submitted.
- W does NOT mean immediate acquisition is guaranteed.
- LOCKED players must not be recommended.
- UNKNOWN players must not be recommended.

General:
- Only recommend an add player whose authoritative provider
  state is FA or W.
- Do not infer acquisition state from web research.
- Do not translate LOCKED or UNKNOWN into an actionable state.
- Web research may establish football value, role, news,
  workload, depth chart, or upside.
"""
)


transaction_agent = Agent(
    name=(
        "Fantasy Transaction Planner"
    ),
    instructions=(
        TRANSACTION_PLANNER_INSTRUCTIONS
    ),
    model=MODEL_NAME,
    output_type=(
        TransactionRecommendation
    ),
    tools=[
        get_league_settings,
        get_my_roster,
        get_available_players,
        get_available_player_summary,
        validate_add_drop,
        WebSearchTool(),
    ],
)


def parse_snapshot_date(
    value,
):
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


def parse_snapshot_datetime(
    value,
):
    if not value:
        return None

    try:
        parsed = (
            datetime.fromisoformat(
                str(
                    value
                )
                .strip()
                .replace(
                    "Z",
                    "+00:00",
                )
            )
        )

    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = (
            parsed.astimezone()
        )

    return parsed


def get_available_player_freshness(
    max_age_days=(
        MAX_AVAILABLE_PLAYER_AGE_DAYS
    ),
    max_sleeper_age_minutes=(
        MAX_SLEEPER_SNAPSHOT_AGE_MINUTES
    ),
):
    provider = (
        get_current_provider()
    )

    provider_name = (
        get_provider_display_name()
    )

    available_data = (
        load_available_players()
    )

    if not isinstance(
        available_data,
        dict,
    ):
        return {
            "provider": provider,
            "provider_name": (
                provider_name
            ),
            "is_fresh": False,
            "reason": (
                "Available-player data is not in the "
                "expected snapshot format."
            ),
        }

    # ---------------------------------------------------------
    # Sleeper requires intraday freshness.
    # ---------------------------------------------------------

    if provider == "sleeper":
        generated_at = (
            available_data.get(
                "generated_at"
            )
        )

        snapshot_datetime = (
            parse_snapshot_datetime(
                generated_at
            )
        )

        if snapshot_datetime is None:
            return {
                "provider": provider,
                "provider_name": (
                    provider_name
                ),
                "is_fresh": False,
                "generated_at": (
                    generated_at
                ),
                "age_minutes": None,
                "max_age_minutes": (
                    max_sleeper_age_minutes
                ),
                "reason": (
                    "Sleeper acquisition data has no valid "
                    "generated_at timestamp."
                ),
            }

        now = (
            datetime.now()
            .astimezone()
        )

        snapshot_datetime = (
            snapshot_datetime.astimezone(
                now.tzinfo
            )
        )

        age_seconds = (
            now
            - snapshot_datetime
        ).total_seconds()

        age_minutes = (
            age_seconds
            / 60
        )

        if age_minutes < 0:
            return {
                "provider": provider,
                "provider_name": (
                    provider_name
                ),
                "is_fresh": False,
                "generated_at": (
                    generated_at
                ),
                "age_minutes": (
                    round(
                        age_minutes,
                        1,
                    )
                ),
                "max_age_minutes": (
                    max_sleeper_age_minutes
                ),
                "reason": (
                    "Sleeper available-player snapshot "
                    "timestamp is in the future."
                ),
            }

        is_fresh = (
            age_minutes
            <= max_sleeper_age_minutes
        )

        if is_fresh:
            reason = (
                "Sleeper acquisition-state snapshot "
                "is fresh enough for evaluation."
            )

        else:
            reason = (
                "Sleeper acquisition-state snapshot "
                f"is {age_minutes:.1f} minutes old. "
                "Maximum allowed age is "
                f"{max_sleeper_age_minutes} minutes."
            )

        return {
            "provider": provider,
            "provider_name": (
                provider_name
            ),
            "is_fresh": (
                is_fresh
            ),
            "generated_at": (
                generated_at
            ),
            "last_updated": (
                available_data.get(
                    "last_updated"
                )
            ),
            "age_minutes": (
                round(
                    age_minutes,
                    1,
                )
            ),
            "max_age_minutes": (
                max_sleeper_age_minutes
            ),
            "reason": reason,
        }

    # ---------------------------------------------------------
    # Yahoo retains date-based freshness.
    # ---------------------------------------------------------

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
            "provider_name": (
                provider_name
            ),
            "is_fresh": False,
            "last_updated": (
                last_updated
            ),
            "age_days": None,
            "max_age_days": (
                max_age_days
            ),
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
            "provider_name": (
                provider_name
            ),
            "is_fresh": False,
            "last_updated": (
                last_updated
            ),
            "age_days": (
                age_days
            ),
            "max_age_days": (
                max_age_days
            ),
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
        "provider_name": (
            provider_name
        ),
        "is_fresh": is_fresh,
        "last_updated": (
            last_updated
        ),
        "age_days": (
            age_days
        ),
        "max_age_days": (
            max_age_days
        ),
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


def build_acquisition_check(
    availability_summary,
):
    provider = (
        get_current_provider()
    )

    counts = (
        availability_summary.get(
            "availability_counts",
            {},
        )
    )

    free_agents = int(
        counts.get(
            "FA",
            0,
        )
        or 0
    )

    waivers = int(
        counts.get(
            "W",
            0,
        )
        or 0
    )

    locked = int(
        counts.get(
            "LOCKED",
            0,
        )
        or 0
    )

    unknown = int(
        counts.get(
            "UNKNOWN",
            0,
        )
        or 0
    )

    actionable = (
        free_agents
        + waivers
    )

    return {
        "provider": provider,
        "free_agents": (
            free_agents
        ),
        "waivers": (
            waivers
        ),
        "locked": (
            locked
        ),
        "unknown": (
            unknown
        ),
        "actionable_players": (
            actionable
        ),
        "has_actionable_players": (
            actionable > 0
        ),
    }


def build_validated_transaction(
    max_attempts=3,
):
    provider = (
        get_current_provider()
    )

    provider_name = (
        get_provider_display_name()
    )

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
                    + freshness[
                        "reason"
                    ]
                )
            )
        )

        return {
            "provider": provider,
            "provider_name": (
                provider_name
            ),
            "recommend_move": False,
            "attempts": 0,
            "recommendation": (
                recommendation.model_dump()
            ),
            "validation": None,
            "availability_check": (
                freshness
            ),
            "transaction_blocked": True,
            "blocked_reason": (
                "stale_available_player_snapshot"
            ),
        }

    availability_summary = (
        build_available_player_summary()
    )

    acquisition_check = (
        build_acquisition_check(
            availability_summary
        )
    )

    # ---------------------------------------------------------
    # 2. Confirm at least one actionable Sleeper acquisition.
    # ---------------------------------------------------------

    if (
        provider == "sleeper"
        and not acquisition_check[
            "has_actionable_players"
        ]
    ):
        if (
            acquisition_check[
                "locked"
            ]
            > 0
            and acquisition_check[
                "unknown"
            ]
            == 0
        ):
            blocked_reason = (
                "sleeper_acquisitions_locked"
            )

            rationale = (
                "Sleeper acquisition data is current, "
                "but no FA or waiver-claim candidates are "
                "currently actionable."
            )

        elif (
            acquisition_check[
                "unknown"
            ]
            > 0
        ):
            blocked_reason = (
                "unverified_sleeper_acquisition_state"
            )

            rationale = (
                "Sleeper acquisition data does not currently "
                "contain a deterministically confirmed FA or "
                "waiver-claim candidate."
            )

        else:
            blocked_reason = (
                "no_actionable_sleeper_players"
            )

            rationale = (
                "No actionable Sleeper acquisition candidate "
                "is currently available."
            )

        recommendation = (
            build_blocked_recommendation(
                rationale
            )
        )

        return {
            "provider": provider,
            "provider_name": (
                provider_name
            ),
            "recommend_move": False,
            "attempts": 0,
            "recommendation": (
                recommendation.model_dump()
            ),
            "validation": None,
            "availability_check": (
                freshness
            ),
            "acquisition_check": (
                acquisition_check
            ),
            "transaction_blocked": True,
            "blocked_reason": (
                blocked_reason
            ),
        }

    # ---------------------------------------------------------
    # 3. Normal transaction evaluation
    # ---------------------------------------------------------

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

AUTHORITATIVE AVAILABLE-PLAYER SUMMARY:

{json.dumps(availability_summary, indent=2)}

AUTHORITATIVE ACQUISITION SUMMARY:

{json.dumps(acquisition_check, indent=2)}

Only recommend an add player who exists in the authoritative
{provider_name} available-player data.

Only FA and W acquisition states are actionable.

For Sleeper:
- FA means immediately addable.
- W means a waiver claim may be submitted.
- W does not guarantee the player will be awarded.
- Never recommend LOCKED or UNKNOWN players.

Preserve the provider's actual availability state.

Do not use web search to determine fantasy-provider
availability.
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

        if (
            not recommendation
            .recommend_move
        ):
            return {
                "provider": provider,
                "provider_name": (
                    provider_name
                ),
                "recommend_move": False,
                "attempts": attempt,
                "recommendation": (
                    recommendation.model_dump()
                ),
                "validation": None,
                "availability_check": (
                    freshness
                ),
                "acquisition_check": (
                    acquisition_check
                ),
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
                    recommendation
                    .add_player,
                    recommendation
                    .drop_player,
                )
            )

        if validation.get(
            "transaction_blocked",
            False,
        ):
            return {
                "provider": provider,
                "provider_name": (
                    provider_name
                ),
                "recommend_move": False,
                "attempts": attempt,
                "recommendation": (
                    recommendation.model_dump()
                ),
                "validation": (
                    validation
                ),
                "availability_check": (
                    freshness
                ),
                "acquisition_check": (
                    acquisition_check
                ),
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
                "provider_name": (
                    provider_name
                ),
                "recommend_move": True,
                "attempts": attempt,
                "recommendation": (
                    recommendation.model_dump()
                ),
                "validation": (
                    validation
                ),
                "availability_check": (
                    freshness
                ),
                "acquisition_check": (
                    acquisition_check
                ),
                "transaction_blocked": False,
            }

        last_validation = (
            validation
        )

        prompt = f"""
Your previous transaction failed deterministic Python
validation.

CURRENT FANTASY PROVIDER:
{provider_name} ({provider})

AUTHORITATIVE AVAILABILITY FRESHNESS:

{json.dumps(freshness, indent=2)}

AUTHORITATIVE ACQUISITION SUMMARY:

{json.dumps(acquisition_check, indent=2)}

PREVIOUS RECOMMENDATION:

{recommendation.model_dump_json(indent=2)}

VALIDATION ERRORS:

{json.dumps(validation["errors"], indent=2)}

Re-evaluate the roster and return either:

1. a corrected valid add/drop transaction, or
2. recommend_move=false if no valid worthwhile move exists.

Only recommend players contained in the selected provider's
authoritative available-player data.

Only FA and W players are actionable.

Do not recommend LOCKED or UNKNOWN players.

Do not use web search to infer fantasy-provider availability.
"""

    last_errors = (
        last_validation[
            "errors"
        ]
        if last_validation
        else "unknown"
    )

    raise RuntimeError(
        "Unable to generate a valid transaction after "
        f"{max_attempts} attempts. "
        f"Last validation errors: {last_errors}"
    )
