import json
from datetime import datetime

from dotenv import load_dotenv
from pydantic import BaseModel
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
    build_roster_schedule,
)
from contingency_tools import (
    get_lock_aware_player_pool,
    build_lock_aware_player_pool,
)
from contingency_validator import validate_contingency


load_dotenv()


MODEL_NAME = "gpt-5.6-luna"


with open(
    "gm_instructions.txt",
    "r",
    encoding="utf-8",
) as file:
    GM_INSTRUCTIONS = file.read()


class ContingencyLineup(BaseModel):
    qb: str
    rb1: str
    rb2: str
    wr1: str
    wr2: str
    te: str
    flex: str
    k: str
    defense: str


class ContingencyProposal(BaseModel):
    unavailable_player: str
    can_build_on_roster_contingency: bool
    contingency_lineup: ContingencyLineup | None = None
    rationale: str


CONTINGENCY_INSTRUCTIONS = GM_INSTRUCTIONS + """

You are building an injury contingency for one player in an
already validated fantasy starting lineup.

Provider isolation requirements:

- Use only the fantasy provider selected for the current run.
- Do not use roster, league, schedule, or availability data
  from another fantasy provider.
- The supplied base lineup belongs to the selected provider
  and is authoritative.

Requirements:

- Use the supplied base lineup as authoritative.
- Assume the named player becomes unavailable immediately
  before that player's NFL kickoff.
- Use my actual selected-provider roster and current NFL
  schedule.
- Use get_lock_aware_player_pool to determine which players
  are still changeable at that decision time.
- If an on-roster contingency is possible, return a COMPLETE
  nine-player contingency lineup.
- Do not return only a one-for-one substitution.
- Do not move a player whose NFL game has already locked.
- Do not use the same player in multiple lineup slots.
- Only use players currently on my selected-provider roster.
- If there is genuinely no possible on-roster contingency,
  set can_build_on_roster_contingency=false and
  contingency_lineup=null.
- Do not claim your proposed contingency has been validated.
  Python validates it after your response.
- Do not describe an unrostered acquisition candidate as a
  confirmed free agent unless provider data establishes that
  the player is immediately addable.
"""


contingency_agent = Agent(
    name="Fantasy Injury Contingency Planner",
    instructions=CONTINGENCY_INSTRUCTIONS,
    model=MODEL_NAME,
    output_type=ContingencyProposal,
    tools=[
        get_league_settings,
        get_my_roster,
        get_roster_schedule,
        get_lock_aware_player_pool,
        WebSearchTool(),
    ],
)


SLOT_MAP = {
    "qb": "QB",
    "rb1": "RB",
    "rb2": "RB",
    "wr1": "WR",
    "wr2": "WR",
    "te": "TE",
    "flex": "FLEX",
    "k": "K",
    "defense": "DEF",
}


def normalize_name(name):
    return name.strip().lower()


def find_contingency_candidates(
    base_lineup,
):
    """
    Find starting players with a nonblank roster status
    on the currently selected fantasy provider.
    """

    provider = get_current_provider()
    provider_name = get_provider_display_name()

    roster = load_roster()

    roster_by_name = {
        normalize_name(
            player["name"]
        ): player
        for player in roster.get(
            "players",
            [],
        )
    }

    candidates = []

    for (
        lineup_slot,
        player_name,
    ) in base_lineup.items():

        player = roster_by_name.get(
            normalize_name(
                player_name
            )
        )

        if not player:
            continue

        status = (
            player.get(
                "status"
            )
            or ""
        ).strip().upper()

        if not status:
            continue

        candidate = {
            "provider": provider,
            "provider_name": provider_name,
            "name": player["name"],
            "position": player["position"],
            "lineup_slot": lineup_slot,
            "provider_status": status,
            "roster_status": status,
        }

        # Preserve this legacy field only for Yahoo.
        if provider == "yahoo":
            candidate[
                "yahoo_status"
            ] = status

        candidates.append(
            candidate
        )

    return candidates


def find_player_slot(
    player_name,
    lineup,
):
    target = normalize_name(
        player_name
    )

    for slot, name in lineup.items():
        if (
            normalize_name(name)
            == target
        ):
            return slot

    return None


def build_immutable_locked_slots(
    unavailable_player,
    base_lineup,
):
    """
    Determine which existing starters have already kicked off
    before the unavailable player's decision time.

    These players must remain in their exact original lineup
    slots. This mirrors the deterministic validator rule so
    the AI receives the lock constraints before proposing a
    contingency rather than learning them only after failure.
    """

    schedule = build_roster_schedule()

    schedule_by_name = {
        normalize_name(
            player["name"]
        ): player
        for player in schedule.get(
            "players",
            [],
        )
    }

    unavailable_key = normalize_name(
        unavailable_player
    )

    unavailable_schedule = (
        schedule_by_name.get(
            unavailable_key
        )
    )

    if (
        not unavailable_schedule
        or not unavailable_schedule.get(
            "kickoff"
        )
    ):
        return {}

    decision_time = datetime.fromisoformat(
        unavailable_schedule["kickoff"]
    )

    locked_slots = {}

    for slot, player_name in (
        base_lineup.items()
    ):
        player_key = normalize_name(
            player_name
        )

        if player_key == unavailable_key:
            continue

        player_schedule = (
            schedule_by_name.get(
                player_key
            )
        )

        if (
            not player_schedule
            or not player_schedule.get(
                "kickoff"
            )
        ):
            continue

        kickoff = datetime.fromisoformat(
            player_schedule["kickoff"]
        )

        if kickoff < decision_time:
            locked_slots[
                slot
            ] = player_name

    return locked_slots


def build_lock_constraints_text(
    locked_slots,
):
    """
    Render deterministic locked-slot constraints for the
    contingency agent.
    """

    if not locked_slots:
        return (
            "None. No other starter has kicked off before "
            "this decision time."
        )

    lines = []

    for slot, player_name in (
        locked_slots.items()
    ):
        slot_label = SLOT_MAP.get(
            slot,
            slot.upper(),
        )

        lines.append(
            f"- {slot} ({slot_label}): "
            f"{player_name}"
        )

    return "\n".join(
        lines
    )


def enforce_immutable_locked_slots(
    contingency_lineup,
    locked_slots,
):
    """
    Enforce already-locked starters in Python before validation.

    The AI may propose a lineup that moves a locked player despite
    explicit prompt instructions. Locked slots are not a suggestion:
    once a player's NFL game has kicked off, that player must remain
    in the exact original fantasy slot.

    When the model merely swaps a locked player with another player,
    repair that swap deterministically.

    Example:
      locked FLEX = Josh Jacobs
      model proposes WR2 = Josh Jacobs, FLEX = Garrett Wilson

    Python repairs it to:
      WR2 = Garrett Wilson, FLEX = Josh Jacobs

    This prevents model compliance from being part of the safety
    boundary. The deterministic validator still checks the repaired
    lineup afterward.
    """

    repaired = dict(contingency_lineup)
    repairs = []

    for locked_slot, locked_player in locked_slots.items():
        current_player = repaired.get(locked_slot)

        if (
            current_player
            and normalize_name(current_player)
            == normalize_name(locked_player)
        ):
            continue

        moved_to_slot = None

        for slot, player_name in repaired.items():
            if slot == locked_slot:
                continue

            if (
                player_name
                and normalize_name(player_name)
                == normalize_name(locked_player)
            ):
                moved_to_slot = slot
                break

        displaced_player = current_player

        repaired[locked_slot] = locked_player

        if (
            moved_to_slot
            and displaced_player
        ):
            repaired[moved_to_slot] = displaced_player

        repairs.append(
            {
                "locked_slot": locked_slot,
                "locked_player": locked_player,
                "model_player_in_locked_slot": current_player,
                "locked_player_was_moved_to": moved_to_slot,
                "displaced_player_relocated_to": (
                    moved_to_slot
                    if moved_to_slot
                    else None
                ),
            }
        )

    return repaired, repairs


def build_validated_contingency(
    unavailable_player,
    base_lineup,
    max_attempts=3,
):
    provider = get_current_provider()
    provider_name = get_provider_display_name()

    base_slot_key = find_player_slot(
        unavailable_player,
        base_lineup,
    )

    if not base_slot_key:
        raise ValueError(
            (
                f"{unavailable_player} is not "
                "in the supplied starting lineup."
            )
        )

    fantasy_slot = SLOT_MAP[
        base_slot_key
    ]

    locked_slots = (
        build_immutable_locked_slots(
            unavailable_player=(
                unavailable_player
            ),
            base_lineup=base_lineup,
        )
    )

    lock_constraints = (
        build_lock_constraints_text(
            locked_slots
        )
    )

    prompt = f"""
Build an injury contingency for the currently selected
fantasy provider.

CURRENT PROVIDER:
{provider_name} ({provider})

UNAVAILABLE PLAYER:
{unavailable_player}

AUTHORITATIVE BASE LINEUP:
{json.dumps(base_lineup, indent=2)}

IMMUTABLE LOCKED STARTERS AT DECISION TIME:
{lock_constraints}

Every player listed above is already locked. Each one MUST
remain in the exact same lineup slot shown above. Do not move,
swap, replace, or re-slot any of them.

Assume the player becomes unavailable immediately before that
player's NFL kickoff.

Use only the selected provider's roster.

Return either:

1. a complete legal on-roster contingency lineup, or

2. can_build_on_roster_contingency=false if no on-roster
   contingency can actually be made at that time.
"""

    last_validation = None

    for attempt in range(
        1,
        max_attempts + 1,
    ):
        result = Runner.run_sync(
            contingency_agent,
            prompt,
        )

        record_run_usage(
            "Injury contingencies",
            MODEL_NAME,
            result,
        )

        proposal = (
            result.final_output_as(
                ContingencyProposal,
                raise_if_incorrect_type=True,
            )
        )

        if not (
            proposal
            .can_build_on_roster_contingency
        ):
            pool = (
                build_lock_aware_player_pool(
                    unavailable_player,
                    lineup_slot=fantasy_slot,
                )
            )

            unlocked_roster = (
                pool.get(
                    "unlocked_roster_players",
                    [],
                )
            )

            if not unlocked_roster:
                return {
                    "provider": provider,
                    "provider_name": provider_name,
                    "is_valid": True,
                    "attempts": attempt,
                    "has_on_roster_contingency": False,
                    "unavailable_player": (
                        unavailable_player
                    ),
                    "original_slot": fantasy_slot,
                    "proposal": (
                        proposal.model_dump()
                    ),
                    "validation": None,
                    "acquisition_candidates": (
                        pool.get(
                            "current_acquisition_candidates",
                            [],
                        )
                    ),
                    "acquisition_warning": (
                        pool.get(
                            "acquisition_warning"
                        )
                    ),
                    # Preserve the existing Yahoo-oriented
                    # field for downstream compatibility.
                    "emergency_free_agents": (
                        pool.get(
                            "current_free_agent_emergency_options",
                            [],
                        )
                    ),
                }

            last_validation = {
                "is_valid": False,
                "errors": [
                    (
                        "The planner claimed no "
                        "on-roster contingency exists, "
                        "but unlocked roster players "
                        "remain."
                    )
                ],
            }

            prompt = f"""
Your previous response said no on-roster contingency exists.

CURRENT PROVIDER:
{provider_name} ({provider})

However, deterministic schedule analysis found unlocked
roster players at the decision time.

Previous proposal:

{proposal.model_dump_json(indent=2)}

IMMUTABLE LOCKED STARTERS AT DECISION TIME:
{lock_constraints}

Every player listed above MUST remain in the exact same slot.

Re-evaluate the COMPLETE lineup.

Use only the selected provider's roster.

If a legal contingency can be constructed, return it.

Do not move already-locked players.
"""

            continue

        if (
            proposal.contingency_lineup
            is None
        ):
            last_validation = {
                "is_valid": False,
                "errors": [
                    (
                        "A contingency was claimed "
                        "to exist but no contingency "
                        "lineup was supplied."
                    )
                ],
            }

            prompt = f"""
You said an on-roster contingency exists but did not provide
the required complete lineup.

CURRENT PROVIDER:
{provider_name} ({provider})

IMMUTABLE LOCKED STARTERS AT DECISION TIME:
{lock_constraints}

Every player listed above MUST remain in the exact same slot.

Return all nine starting lineup slots.

Use only the selected provider's roster.
"""

            continue

        raw_contingency_lineup = (
            proposal
            .contingency_lineup
            .model_dump()
        )

        (
            contingency_lineup,
            lock_repairs,
        ) = enforce_immutable_locked_slots(
            contingency_lineup=(
                raw_contingency_lineup
            ),
            locked_slots=locked_slots,
        )

        validation = (
            validate_contingency(
                unavailable_player=(
                    unavailable_player
                ),
                base_lineup=base_lineup,
                contingency_lineup=(
                    contingency_lineup
                ),
            )
        )

        if validation["is_valid"]:
            proposal_data = (
                proposal.model_dump()
            )

            proposal_data[
                "contingency_lineup"
            ] = contingency_lineup

            return {
                "provider": provider,
                "provider_name": provider_name,
                "is_valid": True,
                "attempts": attempt,
                "has_on_roster_contingency": True,
                "unavailable_player": (
                    unavailable_player
                ),
                "original_slot": fantasy_slot,
                "proposal": proposal_data,
                "validation": validation,
                "lock_repairs": lock_repairs,
            }

        last_validation = validation

        prompt = f"""
Your previous injury contingency failed deterministic Python
validation.

CURRENT PROVIDER:
{provider_name} ({provider})

UNAVAILABLE PLAYER:
{unavailable_player}

AUTHORITATIVE BASE LINEUP:
{json.dumps(base_lineup, indent=2)}

RAW PREVIOUS PROPOSAL:
{proposal.model_dump_json(indent=2)}

PYTHON-ENFORCED LINEUP:
{json.dumps(contingency_lineup, indent=2)}

PYTHON LOCK REPAIRS:
{json.dumps(lock_repairs, indent=2)}

VALIDATION ERRORS AFTER LOCK ENFORCEMENT:
{json.dumps(validation["errors"], indent=2)}

IMMUTABLE LOCKED STARTERS AT DECISION TIME:
{lock_constraints}

Python will always restore every locked starter to the exact same
slot before validation. Do not attempt to move, swap, replace, or
re-slot any locked player.

Correct the remaining validation errors in the COMPLETE
contingency lineup.

Use only the selected provider's roster.

Do not duplicate players.

Do not leave the unavailable player in the lineup.
"""

    last_errors = (
        last_validation["errors"]
        if last_validation
        else "unknown"
    )

    raise RuntimeError(
        "Unable to generate a valid injury contingency "
        f"after {max_attempts} attempts. "
        f"Last errors: {last_errors}"
)


def build_all_validated_contingencies(
    base_lineup,
):
    provider = get_current_provider()
    provider_name = get_provider_display_name()

    candidates = (
        find_contingency_candidates(
            base_lineup
        )
    )

    contingencies = []

    for candidate in candidates:
        result = (
            build_validated_contingency(
                unavailable_player=(
                    candidate["name"]
                ),
                base_lineup=base_lineup,
            )
        )

        result[
            "provider_status"
        ] = candidate[
            "provider_status"
        ]

        result[
            "roster_status"
        ] = candidate[
            "roster_status"
        ]

        if provider == "yahoo":
            result[
                "yahoo_status"
            ] = candidate[
                "provider_status"
            ]

        result[
            "lineup_slot_key"
        ] = candidate[
            "lineup_slot"
        ]

        contingencies.append(
            result
        )

    return {
        "provider": provider,
        "provider_name": provider_name,
        "candidate_count": len(
            candidates
        ),
        "candidates": candidates,
        "contingencies": contingencies,
    }

