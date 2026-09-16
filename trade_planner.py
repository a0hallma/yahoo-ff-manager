import json

from agents import (
    Agent,
    Runner,
    WebSearchTool,
)
from pydantic import BaseModel

from provider_context import (
    get_current_provider,
    get_provider_display_name,
)
from roster_tools import load_roster
from league_tools import load_league_settings
from league_roster_tools import (
    build_league_roster_summary,
)


MODEL_NAME = "gpt-5.6-luna"


class TradeIdea(BaseModel):
    target_player: str
    target_team: str
    target_position: str
    upgrade_path: str
    partner_fit: str
    value_note: str
    confidence: str


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
ownership.

TRADE ANALYSIS RULES

- Never invent which fantasy team owns a player.
- Every proposed target must currently appear on the named
  opposing team's authoritative roster.
- Never propose trading for a player already on my roster.
- Do not assume another manager would accept a trade.
- Do not claim another manager "needs" a position unless their
  roster construction reasonably supports that observation.
- Use current external research when necessary to understand
  player role, workload, market value, recent performance,
  depth-chart changes, or other material non-roster context.
- Separate current fantasy ownership from external player-value
  research. Ownership always comes from the supplied league data.
- Do not recommend a backup QB or TE merely because my roster
  contains only one.
- In one-QB and one-TE leagues, consider replacement value and
  positional scarcity before recommending bench depth.
- Prefer targets that could materially improve:
  - starting-lineup quality,
  - meaningful injury or bye-week insurance,
  - positional strength,
  - roster flexibility,
  - or overall expected fantasy value.
- Consider the value of preserving strong starters.
- Do not recommend giving away an elite starter merely to fill a
  theoretical bench need.
- Do not construct a specific player-for-player offer yet.
- This stage identifies realistic targets and trade partners.
- Offer construction will be handled separately after worthwhile
  targets are identified.
- Return at most three trade ideas.
- It is acceptable to return zero ideas when no trade target is
  sufficiently compelling.
- When returning zero ideas, explain why in summary.
- Confidence must be one of:
  high
  medium
  low
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

        for position, names in team.get(
            "players_by_position",
            {},
        ).items():
            for name in names:
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

        if (
            target_player
            not in ownership[
                target_team
            ][
                "players"
            ]
        ):
            errors.append(
                f"{target_player} is not rostered by "
                f"{target_team} in the authoritative "
                "league snapshot."
            )

        else:
            actual_position = (
                ownership[
                    target_team
                ][
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

        if idea.confidence not in {
            "high",
            "medium",
            "low",
        }:
            errors.append(
                f"Invalid confidence for "
                f"{target_player}: "
                f"{idea.confidence}"
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
for which fantasy team currently owns each player.

Research current fantasy value, player role, workload,
performance context, and other material information when
useful.

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

Every target player must actually be rostered by the named
opposing fantasy team.

The target position must match the authoritative roster data.

Do not propose one of my own players as a trade target.

Return at most three targets.

Do not construct a specific trade offer yet.
"""

    raise RuntimeError(
        "Unable to generate a valid trade plan after "
        f"{max_attempts} attempts. "
        f"Last validation errors: "
        f"{last_validation['errors'] if last_validation else 'unknown'}"
    )