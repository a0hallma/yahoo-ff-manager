import json

from pydantic import BaseModel
from dotenv import load_dotenv
from agents import Agent, Runner, WebSearchTool

from provider_context import (
    get_current_provider,
    get_provider_display_name,
)
from league_tools import get_league_settings
from roster_tools import get_my_roster
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


MODEL_NAME = "gpt-5.6-luna"


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


class LineupPlan(BaseModel):
    lineup: StartingLineup
    rationale: str
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


def validate_plan(
    plan,
    injury_snapshot=None,
):
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

    injury_player_count = (
        injury_snapshot.get(
            "player_count",
            0,
        )
    )

    if injury_player_count == 0:
        rationale = (
            plan.rationale
            or ""
        ).lower()

        timing_terms = [
            "kickoff",
            "lock",
            "late game",
            "late-game",
            "contingency",
            "monday",
            "sunday night",
        ]

        if any(
            term in rationale
            for term in timing_terms
        ):
            errors.append(
                "Lineup rationale used kickoff, lock, or "
                "contingency timing even though the "
                "authoritative injury snapshot contains "
                "zero injury/status concerns."
            )

        if plan.monitor:
            errors.append(
                "Monitor list must be empty when the "
                "authoritative injury snapshot contains "
                "zero injury/status concerns."
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

Use exact_reported_injury exactly as supplied.

Use latest_practice_participation exactly as supplied.

Use official_game_status exactly as supplied.

If official_game_status is "Not yet available", do not invent
an official designation.

You may research current non-injury role, workload, matchup,
or depth-chart information when useful.

Do not use data from another fantasy provider or league.

Return the best complete starting lineup.
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

Continue using the authoritative injury snapshot exactly as
supplied.

Do not rename injuries or infer practice participation.

Do not use data from another fantasy provider or league.

Return a corrected complete lineup.
"""

    raise RuntimeError(
        "Unable to generate a legal starting lineup after "
        f"{max_attempts} attempts. "
        f"Last validation errors: "
        f"{last_validation['errors'] if last_validation else 'unknown'}"
    )