import json
import os
from typing import Literal

from pydantic import BaseModel, Field
from dotenv import load_dotenv
from agents import Agent, Runner, WebSearchTool

from usage_tracker import record_run_usage

from provider_context import (
    get_current_provider,
    get_provider_display_name,
)
from league_tools import get_league_settings
from roster_tools import (
    get_my_roster,
    load_roster,
)
from schedule_tools import (
    get_roster_schedule,
    get_next_roster_lock,
)
from lineup_tools import (
    check_lineup,
    validate_lineup,
)
from contingency_tools import (
    get_lock_aware_player_pool,
)
from injury_researcher import (
    build_injury_research_snapshot,
)


load_dotenv()


MODEL_NAME = os.getenv(
    "FANTASY_MODEL_LINEUP",
    "gpt-5.6-terra",
)


# Provider roster designations that mean a player must not be
# recommended as a starter. These are deliberately limited to
# clearly unavailable states. Questionable/Doubtful remain eligible
# for normal injury-risk and contingency handling.
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


with open(
    "gm_instructions.txt",
    "r",
    encoding="utf-8",
) as file:
    GM_INSTRUCTIONS = file.read()


class StartingLineup(BaseModel):
    qb: str
    rb1: str
    rb2: str
    wr1: str
    wr2: str
    te: str
    flex: str
    k: str
    defense: str


class KeyLineupDecision(BaseModel):
    decision_type: Literal[
        "start_over_bench",
        "slot_assignment",
    ]

    decision: str
    selected_player: str
    alternative_player: str

    selected_player_case: str
    alternative_player_case: str

    deciding_factors: list[str] = Field(
        min_length=1,
        max_length=5,
    )

    confidence: Literal[
        "high",
        "medium",
        "low",
    ]


class LineupPlan(BaseModel):
    lineup: StartingLineup
    rationale: str

    key_decisions: list[
        KeyLineupDecision
    ] = Field(
        min_length=1,
        max_length=3,
    )

    monitor: list[str]


LINEUP_PLANNER_INSTRUCTIONS = GM_INSTRUCTIONS + """

You are generating the starting-lineup portion of the weekly
fantasy football report.

Return a structured LineupPlan.

The program will provide an AUTHORITATIVE INJURY SNAPSHOT.

That snapshot is the single source of truth for:
- fantasy-provider roster status/designation,
- exact reported injury,
- latest practice date,
- latest practice participation,
- official weekly NFL game status,
- newest credible injury/availability update,
- Schefter or Rapoport injury/availability reporting.

Do NOT independently reinterpret, rename, or replace those
injury facts.

Do NOT use web research to contradict the authoritative injury
snapshot.

You may still use web research for non-injury football
information, including:
- player role,
- depth-chart position,
- workload expectations,
- offensive usage,
- matchup information,
- coaching comments unrelated to injury status,
- transactions or NFL roster changes.

If non-injury research also happens to mention an injury,
do not use that wording to replace the injury facts in the
supplied snapshot.

Provider isolation requirements:

- Use only the fantasy provider selected for the current run.
- Do not request or use roster, league, availability, or
  schedule data from another fantasy provider.
- Do not mix players between fantasy leagues.
- The provider and league supplied by the program are
  authoritative for this run.

Lineup requirements:

- Use the current roster and league settings.
- Use the roster schedule tool for current opponents and
  kickoff times.
- Use the supplied authoritative injury snapshot.
- Research current non-injury roles and material player news
  when useful.
- Select exactly one player for every required starting slot.
- Only use players currently on my selected fantasy roster.
- Do not place the same player in multiple slots.
- Respect positional eligibility.
- Do NOT start a player whose selected-provider roster status is
  NA, O, OUT, IR, PUP, NFI, SUS, SUSP, or SUSPENDED.
- Questionable and Doubtful players are not automatically excluded;
  evaluate them using the authoritative injury snapshot and normal
  contingency logic.
- The final lineup will be validated independently by Python
  after you respond.

LINEUP-SELECTION SAFETY RULES:

- Select the best starting players based on expected fantasy performance, role, matchup, league scoring, and authoritative injury information.
- A later kickoff is NOT a negative factor when choosing between healthy players.
- Never bench an otherwise preferred healthy player merely because that player plays Sunday afternoon, Sunday night, or Monday.
- Do not prefer an earlier-playing player simply because the earlier kickoff occurs first.
- Kickoff timing may affect contingency planning only when the authoritative injury snapshot shows meaningful uncertainty for that specific player.
- If the authoritative injury snapshot shows no injury or status concern for a player, do not use lock timing as a reason to bench, monitor, downgrade, or replace that player.
- Use get_lock_aware_player_pool only for a player with meaningful authoritative injury uncertainty, not merely because the player has a late kickoff.
- FLEX positioning may be adjusted for contingency flexibility only after the preferred set of starters has been selected and only when an actual injury/status uncertainty makes that flexibility relevant.
- If the authoritative injury snapshot contains zero relevant injury/status concerns, lineup selection must not be altered for contingency or lock-timing reasons.

Late-game contingency requirements:

- For any proposed starter with meaningful injury uncertainty
  who plays after the main Sunday 1:00 PM Eastern slate, call
  get_lock_aware_player_pool using the exact lineup slot you
  plan to use.
- Consider whether moving an RB, WR, or TE between a normal
  position slot and FLEX creates better late-game contingency
  options when league rules allow it.
- When two lineup configurations are otherwise reasonably
  close, prefer the configuration that preserves more viable
  unlocked replacement options for the uncertain later-playing
  starter.
- Use get_lock_aware_player_pool to understand whether an
  on-roster contingency exists.
- You may state that no on-roster contingency exists.
- Do NOT name, recommend, or describe emergency unrostered
  player options in the lineup rationale or monitor list.
- Emergency acquisition options are handled separately by
  deterministic transaction and contingency logic.
- Do not describe an unrostered player as a confirmed free
  agent, waiver claim, or immediately addable player unless
  current provider data establishes that state.

KEY LINEUP DECISION EXPLANATIONS:

The user must be able to understand WHY a close lineup choice was made
without receiving a long internal reasoning trace.

Return 1 to 3 key_decisions.

Focus on the decisions that are genuinely useful to audit, especially:
- a starter selected over the strongest eligible bench alternative,
- a close RB/WR/FLEX decision,
- starting a questionable player over a healthy alternative,
- a slot assignment that materially improves contingency flexibility.

For decision_type="start_over_bench":
- selected_player MUST be in the proposed starting lineup.
- alternative_player MUST be an eligible player on the current roster
  who is NOT in the proposed starting lineup.
- Compare the selected starter directly against the strongest relevant
  excluded alternative.

For decision_type="slot_assignment":
- both players MUST be in the proposed starting lineup.
- Use this only when the exact slot assignment materially matters for
  contingency flexibility or positional eligibility.
- Do NOT imply that one starter is being benched in favor of the other.

For every key decision:
- decision must state the actual choice in plain language.
- selected_player_case should concisely state the football case for
  the selected player.
- alternative_player_case should concisely state the football case for
  the alternative.
- deciding_factors should contain 1 to 5 concise observable factors.
- Relevant factors include role/workload, target or touch opportunity,
  full-PPR receiving value, matchup, red-zone/scoring opportunity,
  recent role trend, and authoritative injury/availability status.
- Do not invent a numerical projection, probability, ranking, or
  expected-points figure unless a real researched source provides it.
- Do not use kickoff time as a performance tiebreaker for healthy
  players.
- Do not compare against a player who is hard-unavailable under the
  provider-status rules.
- Keep this concise and evidence-based. Provide an audit explanation,
  not hidden chain-of-thought or a long reasoning transcript.
- If the choice is close, use medium or low confidence rather than
  overstating certainty.

Injury reporting requirements:

- Use roster_status exactly as supplied in the injury snapshot.
- provider_status represents the selected fantasy provider's
  roster designation.
- Do not treat provider_status as an NFL injury report.
- Use exact_reported_injury exactly as supplied.
- Never translate or generalize an injury body part.
- Never convert psoas soreness into groin injury.
- Use latest_practice_participation exactly as supplied.
- If it says "Not specified", do not infer Full or Limited.
- Use official_game_status exactly as supplied.
- If it says "Not yet available", do not replace it with a
  reporter expectation or fantasy projection.
- Use the newest credible update from the snapshot when
  discussing current availability.
- Reporter expectations are not official game-status
  designations.
- Any Schefter or Rapoport injury information must come from
  the supplied injury snapshot rather than being independently
  reconstructed.

Contingency reporting boundary:

- The lineup rationale and monitor list may discuss timing risk
  created by an injured starter.
- They may state whether an on-roster replacement exists.
- They must not describe exact contingency lineup changes.
- They must not name emergency acquisition candidates.
- Exact validated contingency actions are rendered separately
  by Python.

The monitor list should contain concise actionable items for
players whose status materially affects the recommended lineup.

When describing an injured or questionable player in rationale
or monitor, remain consistent with the authoritative injury
snapshot.
"""


lineup_agent = Agent(
    name="Fantasy Lineup Planner",
    instructions=LINEUP_PLANNER_INSTRUCTIONS,
    model=MODEL_NAME,
    output_type=LineupPlan,
    tools=[
        get_league_settings,
        get_my_roster,
        get_roster_schedule,
        get_next_roster_lock,
        get_lock_aware_player_pool,
        validate_lineup,
        WebSearchTool(),
    ],
)


def normalize_name(name):
    return (name or "").strip().lower()


def normalize_provider_status(status):
    return (status or "").strip().upper()


def build_authoritative_status_index(
    injury_snapshot=None,
):
    """
    Build the deterministic selected-provider roster-status index.

    The current normalized roster is the primary source. The
    authoritative injury snapshot is then layered on top so the
    validator also honors the exact provider status supplied to the
    lineup agent for this run.

    This keeps lineup availability enforcement independent of whether
    the model notices a status in its prompt.
    """

    status_index = {}

    roster = load_roster()

    for player in roster.get(
        "players",
        [],
    ):
        player_name = player.get(
            "name"
        )

        if not player_name:
            continue

        status = normalize_provider_status(
            player.get("status")
        )

        if status:
            status_index[
                normalize_name(player_name)
            ] = {
                "name": player_name,
                "status": status,
                "source": "selected-provider roster",
            }

    snapshot = injury_snapshot or {}

    for player in snapshot.get(
        "players",
        [],
    ):
        player_name = player.get(
            "player_name"
        )

        if not player_name:
            continue

        status = normalize_provider_status(
            player.get("provider_status")
            or player.get("roster_status")
        )

        if status:
            status_index[
                normalize_name(player_name)
            ] = {
                "name": player_name,
                "status": status,
                "source": "authoritative injury snapshot",
            }

    return status_index


def validate_hard_start_statuses(
    lineup,
    injury_snapshot=None,
):
    """
    Reject starters whose provider roster designation represents a
    clearly unavailable state.

    This is a lineup-safety rule, not an interpretation of an NFL
    injury report. The provider status is used only to determine
    whether the fantasy platform itself marks the player unavailable.
    """

    status_index = build_authoritative_status_index(
        injury_snapshot=injury_snapshot
    )

    errors = []

    for slot_name, player_name in (
        lineup.model_dump().items()
    ):
        status_record = status_index.get(
            normalize_name(player_name)
        )

        if not status_record:
            continue

        status = status_record["status"]

        if status not in HARD_START_BLOCK_STATUSES:
            continue

        errors.append(
            (
                f"{player_name} has provider status {status} "
                f"and cannot be started in {slot_name.upper()}."
            )
        )

    return errors


def validate_key_lineup_decisions(
    plan,
    injury_snapshot=None,
):
    """
    Validate the factual structure of the model's concise lineup
    explanations.

    Python does not judge whether the football opinion is correct, but
    it does ensure the explanation compares real roster players and
    accurately describes whether they are starters or bench options.
    """

    errors = []

    lineup_players = {
        normalize_name(
            player_name
        )
        for player_name
        in plan.lineup.model_dump().values()
    }

    roster = load_roster()

    roster_by_name = {
        normalize_name(
            player.get(
                "name"
            )
        ): player
        for player in roster.get(
            "players",
            [],
        )
        if player.get(
            "name"
        )
    }

    status_index = (
        build_authoritative_status_index(
            injury_snapshot=injury_snapshot
        )
    )

    seen_pairs = set()

    for decision in plan.key_decisions:
        selected_key = normalize_name(
            decision.selected_player
        )

        alternative_key = normalize_name(
            decision.alternative_player
        )

        if not selected_key:
            errors.append(
                "Key lineup decision has no selected_player."
            )
            continue

        if not alternative_key:
            errors.append(
                (
                    f"{decision.selected_player}: key lineup "
                    "decision has no alternative_player."
                )
            )
            continue

        if selected_key == alternative_key:
            errors.append(
                (
                    f"{decision.selected_player}: selected and "
                    "alternative player cannot be the same."
                )
            )

        if selected_key not in lineup_players:
            errors.append(
                (
                    f"{decision.selected_player}: key decision "
                    "selected_player is not in the proposed lineup."
                )
            )

        if selected_key not in roster_by_name:
            errors.append(
                (
                    f"{decision.selected_player}: key decision "
                    "selected_player is not on the current roster."
                )
            )

        if alternative_key not in roster_by_name:
            errors.append(
                (
                    f"{decision.alternative_player}: key decision "
                    "alternative_player is not on the current roster."
                )
            )
            continue

        alternative_status = (
            status_index.get(
                alternative_key,
                {},
            ).get(
                "status",
                "",
            )
        )

        if (
            alternative_status
            in HARD_START_BLOCK_STATUSES
        ):
            errors.append(
                (
                    f"{decision.alternative_player}: key decision "
                    f"alternative has provider status "
                    f"{alternative_status} and is not an eligible "
                    "close-call comparison."
                )
            )

        if (
            decision.decision_type
            == "start_over_bench"
        ):
            if alternative_key in lineup_players:
                errors.append(
                    (
                        f"{decision.decision}: start_over_bench "
                        f"alternative {decision.alternative_player} "
                        "is also in the starting lineup."
                    )
                )

        elif (
            decision.decision_type
            == "slot_assignment"
        ):
            if alternative_key not in lineup_players:
                errors.append(
                    (
                        f"{decision.decision}: slot_assignment "
                        f"alternative {decision.alternative_player} "
                        "is not in the starting lineup."
                    )
                )

        if not (
            decision.decision
            or ""
        ).strip():
            errors.append(
                "Key lineup decision text cannot be blank."
            )

        if not (
            decision.selected_player_case
            or ""
        ).strip():
            errors.append(
                (
                    f"{decision.selected_player}: selected-player "
                    "case cannot be blank."
                )
            )

        if not (
            decision.alternative_player_case
            or ""
        ).strip():
            errors.append(
                (
                    f"{decision.alternative_player}: alternative-"
                    "player case cannot be blank."
                )
            )

        if not decision.deciding_factors:
            errors.append(
                (
                    f"{decision.decision}: at least one deciding "
                    "factor is required."
                )
            )

        pair_key = (
            decision.decision_type,
            selected_key,
            alternative_key,
        )

        if pair_key in seen_pairs:
            errors.append(
                (
                    f"Duplicate key lineup decision: "
                    f"{decision.selected_player} vs "
                    f"{decision.alternative_player}."
                )
            )

        seen_pairs.add(
            pair_key
        )

    return errors


def validate_plan(
    plan,
    injury_snapshot=None,
):
    """
    Deterministically validate lineup legality and injury-monitor
    consistency.

    Kickoff timing may be mentioned factually in a rationale.
    We do not reject a lineup merely because words such as
    "Monday", "kickoff", or "contingency" appear.

    When there are zero authoritative injury/status concerns,
    however, the lineup planner must not create a monitor item.
    """
    lineup = plan.lineup

    validation = check_lineup(
        qb=lineup.qb,
        rb1=lineup.rb1,
        rb2=lineup.rb2,
        wr1=lineup.wr1,
        wr2=lineup.wr2,
        te=lineup.te,
        flex=lineup.flex,
        k=lineup.k,
        defense=lineup.defense,
    )

    errors = list(
        validation.get(
            "errors",
            [],
        )
    )

    injury_snapshot = (
        injury_snapshot
        or {}
    )

    errors.extend(
        validate_hard_start_statuses(
            lineup=lineup,
            injury_snapshot=injury_snapshot,
        )
    )

    errors.extend(
        validate_key_lineup_decisions(
            plan=plan,
            injury_snapshot=injury_snapshot,
        )
    )

    injury_player_count = int(
        injury_snapshot.get(
            "player_count",
            0,
        )
        or 0
    )

    if (
        injury_player_count == 0
        and plan.monitor
    ):
        errors.append(
            (
                "Monitor list must be empty when the "
                "authoritative injury snapshot contains "
                "zero injury/status concerns."
            )
        )

    validation[
        "errors"
    ] = errors

    validation[
        "is_legal"
    ] = (
        validation.get(
            "is_legal",
            False,
        )
        and not errors
    )

    return validation


def build_validated_lineup(
    injury_snapshot=None,
    max_attempts=3,
):
    provider = get_current_provider()
    provider_name = get_provider_display_name()

    if injury_snapshot is None:
        injury_snapshot = (
            build_injury_research_snapshot()
        )

    snapshot_provider = injury_snapshot.get(
        "provider"
    )

    if (
        snapshot_provider
        and snapshot_provider != provider
    ):
        raise RuntimeError(
            "Injury snapshot provider does not match "
            f"the current run. Current provider: "
            f"{provider}; snapshot provider: "
            f"{snapshot_provider}."
        )

    injury_snapshot_json = json.dumps(
        injury_snapshot,
        indent=2,
    )

    prompt = f"""
Build my best starting lineup for the current fantasy week.

CURRENT FANTASY PROVIDER:
{provider_name} ({provider})

Use only data belonging to this selected fantasy provider.

Use:
- my actual selected-provider roster,
- selected-provider league settings,
- current NFL schedule,
- current player roles,
- the authoritative injury snapshot below.

AUTHORITATIVE INJURY SNAPSHOT

{injury_snapshot_json}

Important:

The injury snapshot above has already been researched and
source-validated.

Do not independently replace or reinterpret its injury facts.

Use roster_status and provider_status exactly as supplied.

A player with provider status NA, O, OUT, IR, PUP, NFI, SUS,
SUSP, or SUSPENDED is not eligible to be recommended as a starter.

Use exact_reported_injury exactly as supplied.

Use latest_practice_participation exactly as supplied.

Use official_game_status exactly as supplied.

If official_game_status is "Not yet available", do not invent
an official designation.

You may research current non-injury role, workload, matchup,
or depth-chart information when useful.

Also return 1 to 3 concise key_decisions explaining the most important
close lineup choices. At least one should compare a selected starter
against the strongest relevant eligible bench alternative.

Use observable football factors such as workload, role, full-PPR
receiving opportunity, matchup, scoring opportunity, recent role
trend, and authoritative availability status.

Do not invent numeric projections or probabilities.

Do not provide a long internal reasoning transcript. The goal is a
short audit explanation of the decision.

Do not use data from another fantasy provider or league.

Return the best complete starting lineup with key_decisions.
"""

    last_validation = None

    for attempt in range(
        1,
        max_attempts + 1,
    ):
        result = Runner.run_sync(
            lineup_agent,
            prompt,
        )

        record_run_usage(
            "Starting lineup",
            MODEL_NAME,
            result,
        )

        plan = result.final_output_as(
            LineupPlan,
            raise_if_incorrect_type=True,
        )

        validation = validate_plan(
            plan,
            injury_snapshot=injury_snapshot,
        )

        if validation["is_legal"]:
            return {
                "provider": provider,
                "provider_name": provider_name,
                "is_legal": True,
                "attempts": attempt,
                "plan": plan.model_dump(),
                "validation": validation,
                "injury_snapshot": injury_snapshot,
            }

        last_validation = validation

        prompt = f"""
Your previous proposed lineup failed deterministic Python
validation.

CURRENT FANTASY PROVIDER:
{provider_name} ({provider})

AUTHORITATIVE INJURY SNAPSHOT:

{injury_snapshot_json}

PREVIOUS PROPOSAL:

{plan.model_dump_json(indent=2)}

VALIDATION ERRORS:

{json.dumps(validation["errors"], indent=2)}

Correct the lineup.

Use only players on the current selected-provider roster.

Every required starting slot must be filled.

Do not duplicate a player.

Respect positional eligibility.

Do not start any player whose provider status is NA, O, OUT, IR,
PUP, NFI, SUS, SUSP, or SUSPENDED.

Continue using the authoritative injury snapshot exactly as
supplied.

Do not rename injuries or infer practice participation.

Do not use data from another fantasy provider or league.

Also correct key_decisions so every comparison uses real current-roster
players and accurately distinguishes starters from bench alternatives.

Return a corrected complete lineup with 1 to 3 key_decisions.
"""

    raise RuntimeError(
        "Unable to generate a legal starting lineup after "
        f"{max_attempts} attempts. "
        f"Last validation errors: "
        f"{last_validation['errors'] if last_validation else 'unknown'}"
    )

