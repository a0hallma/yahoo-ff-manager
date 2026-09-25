import json
from datetime import (
    date,
    datetime,
)

from dotenv import load_dotenv
from pydantic import BaseModel, Field
from agents import (
    Agent,
    Runner,
    WebSearchTool,
)

from usage_tracker import record_run_usage

from provider_context import (
    get_current_provider,
    get_provider_display_name,
)
from league_tools import (
    get_league_settings,
)
from roster_tools import (
    get_my_roster,
    load_roster,
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


class OptimizedLineup(
    BaseModel
):
    qb: str
    rb1: str
    rb2: str
    wr1: str
    wr2: str
    te: str
    flex: str
    k: str
    defense: str


class DropCandidateAssessment(
    BaseModel
):
    player_name: str
    retain_case: str
    drop_case: str
    next_four_weeks_outlook: str
    rest_of_season_outlook: str
    temporary_unavailability: bool = False


class TransactionRecommendation(
    BaseModel
):
    recommend_move: bool
    add_player: str | None = None
    drop_player: str | None = None
    rationale: str
    confidence: str

    # Strategic context for the recommendation.
    priority: str = "None"
    move_category: str = "stand_pat"
    this_week_impact: str = ""
    next_four_weeks_impact: str = ""
    bye_week_impact: str = ""
    rest_of_season_outlook: str = ""

    # Explicitly separate "good acquisition" from "better starter".
    starts_this_week: bool = False
    starter_replaced: str | None = None
    starter_upgrade_rationale: str = ""

    # Make the drop decision auditable. A recommended move must
    # compare the selected drop with at least two alternatives.
    drop_candidates_considered: list[
        DropCandidateAssessment
    ] = Field(
        default_factory=list
    )

    # If the selected drop is currently unavailable, the model must
    # explicitly acknowledge that temporary status is not by itself
    # a reason to discard a valuable rest-of-season asset.
    temporary_unavailability_drop: bool = False
    temporary_unavailability_drop_justification: str = ""

    # Complete hypothetical lineup after the recommended transaction.
    # This is required for a recommended move and is independently
    # validated by Python before it can appear in the weekly report.
    optimized_lineup: OptimizedLineup | None = None
    optimized_lineup_rationale: str | None = None


HARD_START_BLOCK_STATUSES = {
    "NA",
    "O",
    "OUT",
    "IR",
    "PUP",
    "NFI",
    "SUS",
    "SUSP",
    "SUSPENDED",
}


OPTIMIZED_LINEUP_SLOT_POSITIONS = {
    "qb": {"QB"},
    "rb1": {"RB"},
    "rb2": {"RB"},
    "wr1": {"WR"},
    "wr2": {"WR"},
    "te": {"TE"},
    "flex": {"RB", "WR", "TE"},
    "k": {"K"},
    "defense": {"DEF"},
}


def normalize_name(
    name,
):
    return (
        str(name or "")
        .strip()
        .lower()
    )


def normalize_status(
    status,
):
    return (
        str(status or "")
        .strip()
        .upper()
    )


def get_available_player_index():
    data = load_available_players()

    return {
        normalize_name(
            player.get("name")
        ): player
        for player in data.get(
            "players",
            [],
        )
        if player.get("name")
    }


def validate_optimized_lineup(
    recommendation,
    transaction_validation,
    injury_snapshot=None,
):
    """
    Deterministically validate the hypothetical lineup after an
    add/drop transaction.

    This does not claim a waiver player has been acquired. It only
    proves that, if the validated transaction completes, the proposed
    nine-player lineup is legal against the resulting roster.
    """

    errors = []

    if not recommendation.optimized_lineup:
        return {
            "is_valid": False,
            "errors": [
                (
                    "A recommended transaction must include a "
                    "complete optimized post-move lineup."
                )
            ],
        }

    roster = load_roster()
    current_players = roster.get(
        "players",
        [],
    )

    add = transaction_validation.get(
        "add",
        {},
    )

    drop = transaction_validation.get(
        "drop",
        {},
    )

    add_name = add.get("name")
    drop_name = drop.get("name")

    available_index = (
        get_available_player_index()
    )

    add_record = available_index.get(
        normalize_name(add_name),
        {},
    )

    resulting_players = [
        dict(player)
        for player in current_players
        if normalize_name(
            player.get("name")
        )
        != normalize_name(drop_name)
    ]

    resulting_players.append(
        {
            "name": add_name,
            "position": (
                add_record.get("position")
                or add.get("position")
                or ""
            ),
            "nfl_team": (
                add_record.get("nfl_team")
                or add.get("nfl_team")
                or ""
            ),
            "status": (
                add_record.get("status")
                or ""
            ),
            "lineup_slot": "HYPOTHETICAL",
        }
    )

    roster_index = {
        normalize_name(
            player.get("name")
        ): player
        for player in resulting_players
        if player.get("name")
    }

    # Layer the authoritative injury snapshot over roster status so
    # the same hard-unavailable rule used by the normal lineup path
    # remains in force after a hypothetical transaction.
    status_index = {
        key: normalize_status(
            player.get("status")
        )
        for key, player
        in roster_index.items()
    }

    for player in (
        injury_snapshot
        or {}
    ).get(
        "players",
        [],
    ):
        player_name = player.get(
            "player_name"
        )

        if not player_name:
            continue

        status = normalize_status(
            player.get("provider_status")
            or player.get("roster_status")
        )

        if status:
            status_index[
                normalize_name(player_name)
            ] = status

    lineup = (
        recommendation
        .optimized_lineup
        .model_dump()
    )

    names = [
        normalize_name(name)
        for name in lineup.values()
    ]

    if any(
        not name
        for name in names
    ):
        errors.append(
            "Every optimized lineup slot must contain a player."
        )

    duplicates = sorted(
        {
            name
            for name in names
            if name
            and names.count(name) > 1
        }
    )

    if duplicates:
        errors.append(
            "Optimized lineup contains duplicate player(s): "
            + ", ".join(duplicates)
        )

    for (
        slot_name,
        player_name,
    ) in lineup.items():
        player_key = normalize_name(
            player_name
        )

        player = roster_index.get(
            player_key
        )

        if not player:
            errors.append(
                (
                    f"{player_name} is not on the hypothetical "
                    "post-transaction roster."
                )
            )
            continue

        position = str(
            player.get(
                "position",
                "",
            )
            or ""
        ).upper()

        allowed_positions = (
            OPTIMIZED_LINEUP_SLOT_POSITIONS[
                slot_name
            ]
        )

        if position not in allowed_positions:
            errors.append(
                (
                    f"{player_name} is position {position or 'UNKNOWN'} "
                    f"and is not eligible for {slot_name.upper()}."
                )
            )

        status = status_index.get(
            player_key,
            "",
        )

        if (
            status
            in HARD_START_BLOCK_STATUSES
        ):
            errors.append(
                (
                    f"{player_name} has provider status {status} "
                    f"and cannot be started in {slot_name.upper()}."
                )
            )

    return {
        "is_valid": not errors,
        "errors": errors,
        "resulting_roster_size": len(
            resulting_players
        ),
        "lineup": lineup,
    }


def build_current_status_index(
    injury_snapshot=None,
):
    roster = load_roster()

    status_index = {
        normalize_name(
            player.get("name")
        ): normalize_status(
            player.get("status")
        )
        for player in roster.get(
            "players",
            [],
        )
        if player.get("name")
    }

    for player in (
        injury_snapshot
        or {}
    ).get(
        "players",
        [],
    ):
        player_name = player.get(
            "player_name"
        )

        if not player_name:
            continue

        status = normalize_status(
            player.get("provider_status")
            or player.get("roster_status")
        )

        if status:
            status_index[
                normalize_name(player_name)
            ] = status

    return status_index


def validate_transaction_strategy(
    recommendation,
    current_lineup,
    transaction_validation,
    injury_snapshot=None,
):
    """
    Deterministically enforce the decision-quality contract.

    Python cannot decide whether one NFL player is better than
    another. It CAN require the model to:
    - compare multiple realistic drop candidates,
    - explicitly justify dropping a temporarily unavailable player,
    - distinguish an acquisition from a true current-week starter
      upgrade,
    - keep the current lineup unchanged when the acquisition is only
      for depth, bye coverage, or future value.
    """

    errors = []

    current_lineup = (
        current_lineup
        or {}
    )

    roster = load_roster()

    roster_index = {
        normalize_name(
            player.get("name")
        ): player
        for player in roster.get(
            "players",
            [],
        )
        if player.get("name")
    }

    add = transaction_validation.get(
        "add",
        {},
    )

    drop = transaction_validation.get(
        "drop",
        {},
    )

    add_name = add.get(
        "name"
    )

    drop_name = drop.get(
        "name"
    )

    assessments = list(
        recommendation
        .drop_candidates_considered
        or []
    )

    unique_assessments = {}

    for assessment in assessments:
        key = normalize_name(
            assessment.player_name
        )

        if not key:
            continue

        unique_assessments[
            key
        ] = assessment

        if key not in roster_index:
            errors.append(
                (
                    f"Drop candidate {assessment.player_name} "
                    "is not on the current roster."
                )
            )

    if len(
        unique_assessments
    ) < 3:
        errors.append(
            (
                "A recommended transaction must compare at least "
                "three unique current-roster drop candidates."
            )
        )

    selected_drop_key = normalize_name(
        drop_name
    )

    if (
        selected_drop_key
        not in unique_assessments
    ):
        errors.append(
            (
                f"The selected drop {drop_name} must appear in "
                "drop_candidates_considered."
            )
        )

    status_index = (
        build_current_status_index(
            injury_snapshot=(
                injury_snapshot
            )
        )
    )

    selected_drop_status = (
        status_index.get(
            selected_drop_key,
            "",
        )
    )

    if (
        selected_drop_status
        in HARD_START_BLOCK_STATUSES
    ):
        selected_assessment = (
            unique_assessments.get(
                selected_drop_key
            )
        )

        if (
            not recommendation
            .temporary_unavailability_drop
        ):
            errors.append(
                (
                    f"{drop_name} has provider status "
                    f"{selected_drop_status}. Dropping a currently "
                    "unavailable player requires an explicit "
                    "temporary-unavailability value comparison."
                )
            )

        justification = (
            recommendation
            .temporary_unavailability_drop_justification
            or ""
        ).strip()

        if len(
            justification
        ) < 40:
            errors.append(
                (
                    "Dropping a temporarily unavailable player "
                    "requires a substantive rest-of-season "
                    "justification."
                )
            )

        if (
            selected_assessment
            and not selected_assessment
            .temporary_unavailability
        ):
            errors.append(
                (
                    f"The selected drop assessment for {drop_name} "
                    "must mark temporary_unavailability=true."
                )
            )

        alternative_keys = {
            key
            for key in unique_assessments
            if key != selected_drop_key
        }

        if len(
            alternative_keys
        ) < 2:
            errors.append(
                (
                    "At least two alternative drop candidates must "
                    "be compared before dropping a temporarily "
                    "unavailable player."
                )
            )

    else:
        if (
            recommendation
            .temporary_unavailability_drop
        ):
            errors.append(
                (
                    "temporary_unavailability_drop=true was supplied "
                    "even though the selected drop does not have a "
                    "hard unavailable provider status."
                )
            )

    if not recommendation.optimized_lineup:
        errors.append(
            (
                "A recommended transaction must include a complete "
                "optimized post-move lineup."
            )
        )

        return {
            "is_valid": False,
            "errors": errors,
            "selected_drop_status": (
                selected_drop_status
            ),
        }

    optimized_lineup = (
        recommendation
        .optimized_lineup
        .model_dump()
    )

    current_names = {
        normalize_name(name)
        for name in current_lineup.values()
        if name
    }

    optimized_names = {
        normalize_name(name)
        for name in optimized_lineup.values()
        if name
    }

    add_key = normalize_name(
        add_name
    )

    starter_replaced_key = normalize_name(
        recommendation
        .starter_replaced
    )

    if recommendation.starts_this_week:
        if not recommendation.starter_replaced:
            errors.append(
                (
                    "starts_this_week=true requires starter_replaced "
                    "to identify the current starter being displaced."
                )
            )

        elif (
            starter_replaced_key
            not in current_names
        ):
            errors.append(
                (
                    f"{recommendation.starter_replaced} is not in "
                    "the current validated starting lineup."
                )
            )

        if add_key not in optimized_names:
            errors.append(
                (
                    f"{add_name} is marked as a current-week starter "
                    "upgrade but does not appear in the optimized "
                    "lineup."
                )
            )

        removed_starters = (
            current_names
            - optimized_names
        )

        added_starters = (
            optimized_names
            - current_names
        )

        if added_starters != {
            add_key
        }:
            errors.append(
                (
                    "A current-week starter upgrade must add exactly "
                    "the acquired player to the starting-player set."
                )
            )

        if removed_starters != {
            starter_replaced_key
        }:
            errors.append(
                (
                    "A current-week starter upgrade must remove "
                    "exactly the named starter_replaced from the "
                    "starting-player set."
                )
            )

        if len(
            (
                recommendation
                .starter_upgrade_rationale
                or ""
            ).strip()
        ) < 30:
            errors.append(
                (
                    "A claimed current-week starter upgrade requires "
                    "a direct football-value comparison explaining "
                    "why the add materially beats the displaced "
                    "starter this week."
                )
            )

    else:
        if recommendation.starter_replaced:
            errors.append(
                (
                    "starts_this_week=false requires "
                    "starter_replaced=null."
                )
            )

        if add_key in optimized_names:
            errors.append(
                (
                    f"{add_name} appears in the optimized lineup even "
                    "though starts_this_week=false."
                )
            )

        for slot_name, current_player in (
            current_lineup.items()
        ):
            optimized_player = (
                optimized_lineup.get(
                    slot_name
                )
            )

            if (
                normalize_name(
                    current_player
                )
                != normalize_name(
                    optimized_player
                )
            ):
                errors.append(
                    (
                        "A depth/bye/future acquisition must not "
                        "change the current validated starting lineup. "
                        f"Slot {slot_name.upper()} changed from "
                        f"{current_player} to {optimized_player}."
                    )
                )

    return {
        "is_valid": not errors,
        "errors": errors,
        "selected_drop_status": (
            selected_drop_status
        ),
        "drop_candidate_count": len(
            unique_assessments
        ),
        "starts_this_week": (
            recommendation
            .starts_this_week
        ),
    }



def build_lineup_changes(
    current_lineup,
    optimized_lineup,
):
    current_lineup = (
        current_lineup
        or {}
    )

    optimized_lineup = (
        optimized_lineup
        or {}
    )

    changes = []

    for slot in (
        "qb",
        "rb1",
        "rb2",
        "wr1",
        "wr2",
        "te",
        "flex",
        "k",
        "defense",
    ):
        before = current_lineup.get(
            slot
        )

        after = optimized_lineup.get(
            slot
        )

        if (
            before
            and after
            and normalize_name(before)
            != normalize_name(after)
        ):
            changes.append(
                {
                    "slot": slot,
                    "before": before,
                    "after": after,
                }
            )

    return changes


TRANSACTION_PLANNER_INSTRUCTIONS = (
    GM_INSTRUCTIONS
    + """

You are the roster-optimization portion of a fantasy football GM.

Return a structured TransactionRecommendation.

Your job is NOT merely to find any legal add/drop. Your job is to
decide whether one currently actionable acquisition materially
improves my probability of winning while also protecting the roster
over the near future.

Optimization priority:

1. Maximize this week's starting lineup and win probability.
2. Protect the next four fantasy weeks, including upcoming bye weeks,
   injuries, role volatility, and thin position groups.
3. Consider rest-of-season upside and roster efficiency.
4. Do not sacrifice a meaningful current-week advantage for a minor
   speculative future gain.

Provider isolation requirements:

- Use only the fantasy provider selected for the current run.
- Do not mix roster, league, or available-player data between
  fantasy providers.
- The supplied provider data is authoritative for availability.
- Web research cannot establish fantasy-provider availability.

Requirements:

- Use my current roster, league settings, and supplied current lineup.
- Use the supplied available-player data.
- Rank available players by marginal value to MY roster, not by
  standalone fantasy value.
- Research current player role, workload, depth chart, matchup,
  upcoming schedule, and bye-week implications when useful.
- Evaluate the current week plus approximately the next four weeks.
- Do not force a transaction.
- recommend_move=false is valid when standing pat is better.
- If recommend_move=true:
  - provide exactly one add player and one drop player,
  - compare AT LEAST THREE plausible current-roster drop candidates,
    including the selected drop and at least two alternatives,
  - for each drop candidate explain the retain case, drop case,
    next-four-weeks outlook, and rest-of-season outlook,
  - do NOT select a temporarily unavailable established player as the
    drop merely because the player is NA/O/IR/PUP/SUSPENDED,
  - if you still select a temporarily unavailable player, explicitly
    explain why that player's expected next-four-weeks and
    rest-of-season value is lower than the alternative drop
    candidates,
  - explicitly state starts_this_week=true or false,
  - set starts_this_week=true ONLY when the added player materially
    beats a current starter THIS WEEK based on role, expected
    workload, matchup, and current availability,
  - if starts_this_week=true, identify starter_replaced and directly
    compare the add against that starter,
  - if starts_this_week=false, starter_replaced must be null and the
    optimized lineup must remain exactly the current validated lineup,
  - provide a COMPLETE nine-player optimized lineup representing
    the roster AFTER that transaction,
  - explain current-week impact,
  - explain next-four-weeks impact,
  - explain bye-week impact,
  - explain rest-of-season outlook,
  - provide a priority and move category.
- A good acquisition is NOT automatically a better starter.
- Depth, bye-week coverage, injury insurance, and future upside may
  justify a move without changing this week's starting lineup.
- If recommend_move=false, optimized_lineup should be null.
- The transaction and post-move lineup will both be independently
  validated by Python after you respond.
- Do not state or imply that a proposed transaction has already
  completed or been validated.

Availability rules:

Yahoo:
- FA is a free agent.
- W is a waiver-claim candidate.

Sleeper:
- FA means the player is confirmed immediately addable.
- W means the player is confirmed to be on waivers and a waiver
  claim may be submitted.
- W does NOT mean immediate acquisition is guaranteed.
- LOCKED players must not be recommended.
- UNKNOWN players must not be recommended.

General:
- Only recommend an add player whose authoritative provider state
  is FA or W.
- If the add player is W, the optimized lineup is explicitly
  hypothetical and conditional on the claim clearing.
- Do not infer acquisition state from web research.
- Do not translate LOCKED or UNKNOWN into an actionable state.
- Web research may establish football value, role, news, workload,
  matchup, upcoming schedule, bye weeks, and upside.
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
    current_lineup=None,
    injury_snapshot=None,
    max_attempts=3,
):
    provider = (
        get_current_provider()
    )

    provider_name = (
        get_provider_display_name()
    )

    current_lineup = (
        current_lineup
        or {}
    )

    injury_snapshot = (
        injury_snapshot
        or {}
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
            "post_move_lineup_validation": None,
            "current_lineup": current_lineup,
            "lineup_changes": [],
            "optimization_horizon_weeks": 4,
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
            "post_move_lineup_validation": None,
            "current_lineup": current_lineup,
            "lineup_changes": [],
            "optimization_horizon_weeks": 4,
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
    # 3. Roster optimization
    # ---------------------------------------------------------

    prompt = f"""
Evaluate my current fantasy roster and all currently actionable
available players.

CURRENT FANTASY PROVIDER:
{provider_name} ({provider})

CURRENT VALIDATED STARTING LINEUP:

{json.dumps(current_lineup, indent=2)}

AUTHORITATIVE CURRENT-ROSTER INJURY/STATUS SNAPSHOT:

{json.dumps(injury_snapshot, indent=2)}

Determine the SINGLE best add/drop transaction I should make right
now, if any.

The objective is to maximize my opportunity to win THIS WEEK while
also improving or protecting the roster over the NEXT FOUR WEEKS.

Explicitly evaluate:
- whether an available player would enter my starting lineup now,
- whether an available player improves an injury contingency,
- upcoming bye-week exposure,
- current role and workload,
- near-term matchup/schedule quality,
- whether the drop creates a new weakness,
- rest-of-season upside.

Before selecting a drop, compare at least THREE plausible players
currently on my roster. Include the selected drop and at least two
alternatives.

TEMPORARY UNAVAILABILITY RULE:
A provider status such as NA, O, IR, PUP, or SUSPENDED does not by
itself make a player the correct drop. Treat temporary availability
separately from football value. Preserve an established/high-upside
asset when a lower-value bench player can be dropped instead. If you
still choose the unavailable player, make the rest-of-season value
case explicitly and compare that player against the alternatives.

STARTER-UPGRADE RULE:
A good free-agent or waiver acquisition does NOT automatically belong
in the starting lineup. Set starts_this_week=true only if the added
player materially beats a CURRENT validated starter this week based
on role, expected workload, matchup, and current availability. Name
that starter in starter_replaced and compare them directly.

If the move improves depth, bye coverage, injury insurance, or future
upside but does NOT materially improve a starter this week, set
starts_this_week=false, starter_replaced=null, and return the current
validated starting lineup UNCHANGED as optimized_lineup.

Current-week starting-lineup improvement is the first priority.
Near-term bye-week and depth planning are the second priority.
Rest-of-season upside is the third priority.

Do not force a move. If standing pat is better, return
recommend_move=false and optimized_lineup=null.

If you recommend a move, return a COMPLETE optimized nine-player
starting lineup for the hypothetical roster after the add/drop.

If the add player is on waivers (W), the optimized lineup is
conditional on the claim clearing. Do not imply the player has
already been acquired.

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

Do not use web search to determine fantasy-provider availability.
You MAY use web research for football value, role, workload,
matchups, upcoming schedule, and bye weeks.
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

        record_run_usage(
            "Roster optimization",
            MODEL_NAME,
            result,
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
                "post_move_lineup_validation": None,
                "current_lineup": current_lineup,
                "lineup_changes": [],
                "optimization_horizon_weeks": 4,
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
                "post_move_lineup_validation": None,
                "current_lineup": current_lineup,
                "lineup_changes": [],
                "optimization_horizon_weeks": 4,
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

        post_move_validation = None
        strategy_validation = None

        if validation.get(
            "is_valid",
            False,
        ):
            post_move_validation = (
                validate_optimized_lineup(
                    recommendation=(
                        recommendation
                    ),
                    transaction_validation=(
                        validation
                    ),
                    injury_snapshot=(
                        injury_snapshot
                    ),
                )
            )

            strategy_validation = (
                validate_transaction_strategy(
                    recommendation=(
                        recommendation
                    ),
                    current_lineup=(
                        current_lineup
                    ),
                    transaction_validation=(
                        validation
                    ),
                    injury_snapshot=(
                        injury_snapshot
                    ),
                )
            )

        combined_errors = list(
            validation.get(
                "errors",
                [],
            )
        )

        if (
            post_move_validation
            and not post_move_validation[
                "is_valid"
            ]
        ):
            combined_errors.extend(
                post_move_validation[
                    "errors"
                ]
            )

        if (
            strategy_validation
            and not strategy_validation[
                "is_valid"
            ]
        ):
            combined_errors.extend(
                strategy_validation[
                    "errors"
                ]
            )

        if (
            validation.get(
                "is_valid",
                False,
            )
            and post_move_validation
            and post_move_validation[
                "is_valid"
            ]
            and strategy_validation
            and strategy_validation[
                "is_valid"
            ]
        ):
            optimized_lineup = (
                recommendation
                .optimized_lineup
                .model_dump()
            )

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
                "post_move_lineup_validation": (
                    post_move_validation
                ),
                "strategy_validation": (
                    strategy_validation
                ),
                "current_lineup": current_lineup,
                "lineup_changes": (
                    build_lineup_changes(
                        current_lineup,
                        optimized_lineup,
                    )
                ),
                "optimization_horizon_weeks": 4,
                "availability_check": (
                    freshness
                ),
                "acquisition_check": (
                    acquisition_check
                ),
                "transaction_blocked": False,
            }

        last_validation = {
            "errors": combined_errors,
        }

        prompt = f"""
Your previous roster optimization failed deterministic Python
validation.

CURRENT FANTASY PROVIDER:
{provider_name} ({provider})

CURRENT VALIDATED STARTING LINEUP:

{json.dumps(current_lineup, indent=2)}

AUTHORITATIVE CURRENT-ROSTER INJURY/STATUS SNAPSHOT:

{json.dumps(injury_snapshot, indent=2)}

AUTHORITATIVE AVAILABILITY FRESHNESS:

{json.dumps(freshness, indent=2)}

AUTHORITATIVE ACQUISITION SUMMARY:

{json.dumps(acquisition_check, indent=2)}

PREVIOUS RECOMMENDATION:

{recommendation.model_dump_json(indent=2)}

VALIDATION ERRORS:

{json.dumps(combined_errors, indent=2)}

Re-evaluate the roster and return either:

1. a corrected valid add/drop transaction PLUS a complete legal
   optimized post-move lineup, or
2. recommend_move=false if no valid worthwhile move exists.

The objective remains:
1. maximize this week's lineup/win opportunity,
2. protect the next four weeks and upcoming bye weeks,
3. improve rest-of-season roster value.

You MUST:
- compare at least three drop candidates,
- avoid treating temporary unavailability as automatic drop value,
- explicitly justify any unavailable-player drop against alternatives,
- separate acquisition value from current-week starter value,
- set starts_this_week=true only for a material current-week upgrade,
- leave the current starting lineup unchanged when starts_this_week=false.

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
        "Unable to generate a valid roster optimization after "
        f"{max_attempts} attempts. "
        f"Last validation errors: {last_errors}"
    )

