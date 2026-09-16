import json
from typing import Literal

from agents import (
    Agent,
    Runner,
    WebSearchTool,
)
from pydantic import BaseModel
from dotenv import load_dotenv

from provider_context import (
    get_current_provider,
    get_provider_display_name,
)
from roster_tools import load_roster
from league_tools import load_league_settings
from league_roster_tools import (
    build_league_roster_summary,
)


load_dotenv()


MODEL_NAME = "gpt-5.6-luna"


class TradeIdea(BaseModel):
    target_player: str
    target_team: str
    target_position: str

    target_team_position_count: int
    target_team_same_position_players: list[str]

    replacement_risk: Literal[
        "high",
        "medium",
        "low",
    ]

    attainability: Literal[
        "high",
        "medium",
        "low",
    ]

    upgrade_path: str
    partner_fit: str
    value_note: str

    confidence: Literal[
        "high",
        "medium",
        "low",
    ]


class TradePlan(BaseModel):
    summary: str
    ideas: list[TradeIdea]


TRADE_PLANNER_INSTRUCTIONS = """
You are the trade-analysis component of a season-long
fantasy football GM system.

You will receive:

- my current fantasy roster,
- league settings,
- authoritative league-wide roster data,
- current fantasy provider information.

The league-wide roster data is authoritative for fantasy
ownership and roster construction.

TRADE ANALYSIS RULES

- Never invent which fantasy team owns a player.
- Every proposed target must currently appear on the named
  opposing team's authoritative roster.
- Never propose trading for a player already on my roster.
- Never invent positional depth for another fantasy team.
- target_team_position_count must exactly match the number
  of players at the target's position on that team's
  authoritative roster.
- target_team_same_position_players must list every player
  at that position on the target team, including the target.
- target_position must match the authoritative roster data.

PARTNER-FIT RULES

- Evaluate whether the other manager could reasonably absorb
  losing the target.
- Do not assume another manager would accept a trade.
- Do not describe a player as surplus merely because the
  manager has depth at unrelated positions.
- Positional replacement risk is based on the target team's
  current depth at the target's own position.

Use these replacement-risk definitions:

- high:
  The target is the only player at that position on the
  opposing roster.

- medium:
  The opposing roster has exactly two players at that
  position.

- low:
  The opposing roster has three or more players at that
  position.

- replacement_risk must follow those definitions exactly.

If replacement_risk is high:

- Explicitly acknowledge in partner_fit that trading the
  target would create a hole at that position for the
  opposing manager.
- Do not describe the player as positional surplus.
- attainability cannot be high.
- A trade may still be worth exploring if the target is a
  meaningful upgrade, but acknowledge that the partner would
  likely need compensation that helps solve the resulting
  roster problem.

If replacement_risk is medium:

- Identify the other player at that position when explaining
  why a trade might be plausible.
- Do not automatically assume that having two players makes
  either one expendable.

If replacement_risk is low:

- Positional depth may support a stronger partner-fit case,
  but still consider player quality and starting requirements.

ATTAINABILITY RULES

attainability represents how plausible it is that the other
manager could consider moving the target, not how good the
player is.

Use:

- high:
  Strong roster-construction reason exists for the other
  manager to consider moving the player.

- medium:
  A plausible path exists, but meaningful value would be
  required.

- low:
  The player would be difficult to acquire because of role,
  elite value, positional scarcity, or the hole created on
  the opposing roster.

Do not confuse target quality with attainability.

PLAYER-VALUE RULES

- Use current external research when necessary to understand
  player role, workload, market value, recent performance,
  depth-chart changes, or other material non-roster context.
- Separate external player-value research from fantasy
  ownership. Ownership always comes from the supplied league
  data.
- Do not recommend a backup QB or TE merely because my roster
  contains only one.
- In one-QB and one-TE leagues, consider replacement value,
  positional scarcity, and starting-lineup improvement.
- Prefer targets that could materially improve:
  - starting-lineup quality,
  - meaningful injury or bye-week insurance,
  - positional strength,
  - roster flexibility,
  - or overall expected fantasy value.
- Consider the value of preserving strong starters.
- Do not recommend giving away an elite starter merely to
  fill a theoretical bench need.

TRADE-STAGE BOUNDARY

- Do not construct a specific player-for-player offer yet.
- This stage identifies realistic targets and trade partners.
- Offer construction will be handled separately after
  worthwhile targets are identified.
- Return at most three trade ideas.
- It is acceptable to return zero ideas when no target is
  sufficiently compelling.
- When returning zero ideas, explain why in summary.
"""


trade_agent = Agent(
    name="Fantasy Trade Planner",
    instructions=TRADE_PLANNER_INSTRUCTIONS,
    model=MODEL_NAME,
    output_type=TradePlan,
    tools=[
        WebSearchTool(),
    ],
)


def get_expected_replacement_risk(
    position_count,
):
    if position_count <= 1:
        return "high"

    if position_count == 2:
        return "medium"

    return "low"


def validate_trade_plan(
    plan,
    league_summary,
):
    errors = []

    my_team = None
    ownership = {}

    for team in league_summary.get(
        "teams",
        [],
    ):
        team_name = team.get(
            "team_name"
        )

        if team.get(
            "is_my_team"
        ):
            my_team = team_name

        players = set()
        player_positions = {}
        players_by_position = {}

        for position, names in team.get(
            "players_by_position",
            {},
        ).items():
            normalized_names = sorted(
                names
            )

            players_by_position[
                position
            ] = normalized_names

            for name in normalized_names:
                players.add(
                    name
                )

                player_positions[
                    name
                ] = position

        ownership[
            team_name
        ] = {
            "players": players,
            "positions": player_positions,
            "players_by_position": (
                players_by_position
            ),
        }

    seen_targets = set()

    for idea in plan.ideas:
        target_team = (
            idea.target_team
        )

        target_player = (
            idea.target_player
        )

        if target_team == my_team:
            errors.append(
                f"{target_player} was proposed from "
                "my own fantasy team."
            )

        if target_team not in ownership:
            errors.append(
                f"Unknown target team: {target_team}"
            )
            continue

        team_ownership = (
            ownership[
                target_team
            ]
        )

        if (
            target_player
            not in team_ownership[
                "players"
            ]
        ):
            errors.append(
                f"{target_player} is not rostered by "
                f"{target_team} in the authoritative "
                "league snapshot."
            )
            continue

        actual_position = (
            team_ownership[
                "positions"
            ].get(
                target_player
            )
        )

        if (
            actual_position
            and idea.target_position
            != actual_position
        ):
            errors.append(
                f"{target_player} position mismatch: "
                f"plan says {idea.target_position}, "
                f"authoritative roster says "
                f"{actual_position}."
            )

        actual_same_position_players = (
            team_ownership[
                "players_by_position"
            ].get(
                actual_position,
                [],
            )
        )

        actual_position_count = len(
            actual_same_position_players
        )

        if (
            idea.target_team_position_count
            != actual_position_count
        ):
            errors.append(
                f"{target_player} target-team "
                f"{actual_position} depth mismatch: "
                f"plan says "
                f"{idea.target_team_position_count}, "
                f"authoritative roster says "
                f"{actual_position_count}."
            )

        proposed_same_position_players = (
            sorted(
                idea.target_team_same_position_players
            )
        )

        if (
            proposed_same_position_players
            != actual_same_position_players
        ):
            errors.append(
                f"{target_player} same-position roster "
                "list does not match authoritative data. "
                f"Plan says "
                f"{proposed_same_position_players}; "
                f"authoritative roster says "
                f"{actual_same_position_players}."
            )

        expected_replacement_risk = (
            get_expected_replacement_risk(
                actual_position_count
            )
        )

        if (
            idea.replacement_risk
            != expected_replacement_risk
        ):
            errors.append(
                f"{target_player} replacement-risk "
                f"mismatch: plan says "
                f"{idea.replacement_risk}, "
                f"deterministic value is "
                f"{expected_replacement_risk}."
            )

        if (
            expected_replacement_risk
            == "high"
            and idea.attainability
            == "high"
        ):
            errors.append(
                f"{target_player} cannot have high "
                "attainability when trading him would "
                "leave the opposing team with no other "
                f"{actual_position}."
            )

        target_key = (
            target_team,
            target_player,
        )

        if target_key in seen_targets:
            errors.append(
                f"Duplicate trade target: "
                f"{target_player} from "
                f"{target_team}."
            )

        seen_targets.add(
            target_key
        )

    if len(plan.ideas) > 3:
        errors.append(
            "Trade planner returned more than "
            "three trade ideas."
        )

    return {
        "is_valid": not errors,
        "errors": errors,
    }


def build_validated_trade_plan(
    max_attempts=3,
):
    provider = (
        get_current_provider()
    )

    provider_name = (
        get_provider_display_name()
    )

    try:
        league_summary = (
            build_league_roster_summary()
        )

    except Exception as exc:
        return {
            "provider": provider,
            "provider_name": provider_name,
            "status": "blocked",
            "blocked_reason": (
                "league_wide_rosters_unavailable"
            ),
            "reason": str(exc),
            "attempts": 0,
            "plan": None,
            "validation": None,
        }

    roster = load_roster()

    league_settings = (
        load_league_settings()
    )

    roster_json = json.dumps(
        roster,
        indent=2,
    )

    settings_json = json.dumps(
        league_settings,
        indent=2,
    )

    league_json = json.dumps(
        league_summary,
        indent=2,
    )

    prompt = f"""
Evaluate realistic trade targets for my current fantasy team.

CURRENT FANTASY PROVIDER

{provider_name} ({provider})

MY CURRENT ROSTER

{roster_json}

LEAGUE SETTINGS

{settings_json}

AUTHORITATIVE LEAGUE-WIDE ROSTERS

{league_json}

Use the league-wide roster data as the only source of truth
for:

- fantasy ownership,
- target position,
- same-position depth,
- and whether moving a target creates a positional hole.

Research current fantasy value, role, workload, performance
context, and other material information when useful.

For every target:

1. Identify the correct opposing fantasy team.
2. Identify the target's correct position.
3. Count exactly how many players that team has at the target
   position.
4. List every same-position player on that roster.
5. Assign replacement_risk using the deterministic rules in
   your instructions.
6. Separately assess attainability.
7. Explain partner_fit from both sides of the roster
   construction, not merely why I want the player.

Identify zero to three realistic targets.

Do not create a specific trade offer yet.

Return a structured TradePlan.
"""

    last_validation = None

    for attempt in range(
        1,
        max_attempts + 1,
    ):
        result = Runner.run_sync(
            trade_agent,
            prompt,
        )

        plan = (
            result.final_output_as(
                TradePlan,
                raise_if_incorrect_type=True,
            )
        )

        validation = (
            validate_trade_plan(
                plan,
                league_summary,
            )
        )

        if validation[
            "is_valid"
        ]:
            return {
                "provider": provider,
                "provider_name": (
                    provider_name
                ),
                "status": "pass",
                "attempts": attempt,
                "plan": plan.model_dump(),
                "validation": validation,
                "league_summary": (
                    league_summary
                ),
            }

        last_validation = (
            validation
        )

        prompt = f"""
Your previous trade plan failed deterministic validation.

CURRENT FANTASY PROVIDER

{provider_name} ({provider})

AUTHORITATIVE LEAGUE-WIDE ROSTERS

{league_json}

VALIDATION ERRORS

{json.dumps(validation["errors"], indent=2)}

Correct the trade plan.

Requirements:

- Every target must actually be rostered by the named
  opposing fantasy team.
- target_position must match authoritative roster data.
- target_team_position_count must exactly match the
  authoritative roster.
- target_team_same_position_players must contain the exact
  authoritative same-position player list.
- replacement_risk must follow the deterministic position
  count rules.
- A target who is the opposing team's only player at his
  position cannot have high attainability.
- Do not describe a sole player at a position as surplus.
- Do not propose one of my own players as a trade target.
- Return at most three targets.
- Do not construct a specific trade offer yet.

Return a corrected TradePlan.
"""

    raise RuntimeError(
        "Unable to generate a valid trade plan after "
        f"{max_attempts} attempts. "
        f"Last validation errors: "
        f"{last_validation['errors'] if last_validation else 'unknown'}"
    )
