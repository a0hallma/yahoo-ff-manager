import json

from dotenv import load_dotenv
from pydantic import BaseModel
from agents import Agent, Runner, WebSearchTool

from league_tools import get_league_settings
from roster_tools import get_my_roster, ROSTER_FILE
from schedule_tools import get_roster_schedule
from contingency_tools import (
    get_lock_aware_player_pool,
    build_lock_aware_player_pool,
)
from contingency_validator import validate_contingency


load_dotenv()


MODEL_NAME = "gpt-5.6-luna"


with open("gm_instructions.txt", "r", encoding="utf-8") as f:
    GM_INSTRUCTIONS = f.read()


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

You are building an injury contingency for one player in an already
validated fantasy starting lineup.

Requirements:
- Use the supplied base lineup as authoritative.
- Assume the named player becomes unavailable immediately before
  that player's NFL kickoff.
- Use my actual roster and current NFL schedule.
- Use get_lock_aware_player_pool to determine which players are
  still changeable at that decision time.
- If an on-roster contingency is possible, return a COMPLETE
  nine-player contingency lineup.
- Do not return only a one-for-one substitution.
- Do not move a player whose NFL game has already locked.
- Do not use the same player in multiple lineup slots.
- Only use players currently on my roster.
- If there is genuinely no possible on-roster contingency, set
  can_build_on_roster_contingency=false and contingency_lineup=null.
- Do not claim your proposed contingency has been validated.
  Python validates it after your response.
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


def find_contingency_candidates(base_lineup):
    with open(ROSTER_FILE, "r", encoding="utf-8") as f:
        roster = json.load(f)

    roster_by_name = {
        normalize_name(player["name"]): player
        for player in roster.get("players", [])
    }

    candidates = []

    for lineup_slot, player_name in base_lineup.items():
        player = roster_by_name.get(
            normalize_name(player_name)
        )

        if not player:
            continue

        status = (
            player.get("status")
            or ""
        ).strip().upper()

        if not status:
            continue

        candidates.append(
            {
                "name": player["name"],
                "position": player["position"],
                "lineup_slot": lineup_slot,
                "yahoo_status": status,
            }
        )

    return candidates


def find_player_slot(player_name, lineup):
    target = normalize_name(player_name)

    for slot, name in lineup.items():
        if normalize_name(name) == target:
            return slot

    return None


def build_validated_contingency(
    unavailable_player,
    base_lineup,
    max_attempts=3,
):
    base_slot_key = find_player_slot(
        unavailable_player,
        base_lineup,
    )

    if not base_slot_key:
        raise ValueError(
            f"{unavailable_player} is not in the supplied "
            "starting lineup."
        )

    fantasy_slot = SLOT_MAP[base_slot_key]

    prompt = f"""
Build an injury contingency for:

UNAVAILABLE PLAYER:
{unavailable_player}

AUTHORITATIVE BASE LINEUP:
{json.dumps(base_lineup, indent=2)}

Assume the player becomes unavailable immediately before that
player's NFL kickoff.

Return either:
1. a complete legal on-roster contingency lineup, or
2. can_build_on_roster_contingency=false if no on-roster
   contingency can actually be made at that time.
"""

    last_validation = None

    for attempt in range(1, max_attempts + 1):
        result = Runner.run_sync(
            contingency_agent,
            prompt,
        )

        proposal = result.final_output_as(
            ContingencyProposal,
            raise_if_incorrect_type=True,
        )

        if not proposal.can_build_on_roster_contingency:
            pool = build_lock_aware_player_pool(
                unavailable_player,
                lineup_slot=fantasy_slot,
            )

            unlocked_roster = pool.get(
                "unlocked_roster_players",
                [],
            )

            if not unlocked_roster:
                return {
                    "is_valid": True,
                    "attempts": attempt,
                    "has_on_roster_contingency": False,
                    "unavailable_player": unavailable_player,
                    "original_slot": fantasy_slot,
                    "proposal": proposal.model_dump(),
                    "validation": None,
                    "emergency_free_agents": pool.get(
                        "current_free_agent_emergency_options",
                        [],
                    ),
                }

            last_validation = {
                "is_valid": False,
                "errors": [
                    "The planner claimed no on-roster contingency "
                    "exists, but unlocked roster players remain."
                ],
            }

            prompt = f"""
Your previous response said no on-roster contingency exists.

However, deterministic schedule analysis found unlocked roster
players at the decision time.

Previous proposal:
{proposal.model_dump_json(indent=2)}

Re-evaluate the COMPLETE lineup.

If a legal contingency can be constructed, return it.
Do not move already-locked players.
"""

            continue

        if proposal.contingency_lineup is None:
            last_validation = {
                "is_valid": False,
                "errors": [
                    "A contingency was claimed to exist but no "
                    "contingency lineup was supplied."
                ],
            }

            prompt = """
You said an on-roster contingency exists but did not provide
the required complete lineup.

Return all nine starting lineup slots.
"""

            continue

        contingency_lineup = (
            proposal.contingency_lineup.model_dump()
        )

        validation = validate_contingency(
            unavailable_player=unavailable_player,
            base_lineup=base_lineup,
            contingency_lineup=contingency_lineup,
        )

        if validation["is_valid"]:
            return {
                "is_valid": True,
                "attempts": attempt,
                "has_on_roster_contingency": True,
                "unavailable_player": unavailable_player,
                "original_slot": fantasy_slot,
                "proposal": proposal.model_dump(),
                "validation": validation,
            }

        last_validation = validation

        prompt = f"""
Your previous injury contingency failed deterministic Python
validation.

UNAVAILABLE PLAYER:
{unavailable_player}

AUTHORITATIVE BASE LINEUP:
{json.dumps(base_lineup, indent=2)}

PREVIOUS PROPOSAL:
{proposal.model_dump_json(indent=2)}

VALIDATION ERRORS:
{json.dumps(validation["errors"], indent=2)}

Correct the COMPLETE contingency lineup.

Do not move players whose games have already locked.
Do not duplicate players.
Do not leave the unavailable player in the lineup.
"""

    raise RuntimeError(
        "Unable to generate a valid injury contingency after "
        f"{max_attempts} attempts. "
        f"Last errors: "
        f"{last_validation['errors'] if last_validation else 'unknown'}"
    )


def build_all_validated_contingencies(base_lineup):
    candidates = find_contingency_candidates(
        base_lineup
    )

    contingencies = []

    for candidate in candidates:
        result = build_validated_contingency(
            unavailable_player=candidate["name"],
            base_lineup=base_lineup,
        )

        result["yahoo_status"] = (
            candidate["yahoo_status"]
        )

        result["lineup_slot_key"] = (
            candidate["lineup_slot"]
        )

        contingencies.append(result)

    return {
        "candidate_count": len(candidates),
        "candidates": candidates,
        "contingencies": contingencies,
    }