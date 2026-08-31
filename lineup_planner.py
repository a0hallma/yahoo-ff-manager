import json

from pydantic import BaseModel
from dotenv import load_dotenv
from agents import Agent, Runner, WebSearchTool

from league_tools import get_league_settings
from roster_tools import get_my_roster
from schedule_tools import get_roster_schedule, get_next_roster_lock
from lineup_tools import check_lineup, validate_lineup
from contingency_tools import get_lock_aware_player_pool

load_dotenv()

MODEL_NAME = "gpt-5.6-luna"


with open("gm_instructions.txt", "r", encoding="utf-8") as f:
    GM_INSTRUCTIONS = f.read()


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

You are generating the starting-lineup portion of the weekly report.

Return a structured LineupPlan.

Requirements:
- Use the current roster and league settings.
- Use the roster schedule tool for current opponents and kickoff times.
- Research current injuries, roles, and material player news.
- Select exactly one player for every required starting slot.
- Only use players currently on my roster.
- Do not place the same player in multiple slots.
- FLEX may contain RB, WR, or TE.
- The final lineup will be validated independently by Python after you respond.
- For any proposed starter with meaningful injury uncertainty who plays after the main Sunday 1:00 PM Eastern slate, call get_lock_aware_player_pool using the exact lineup slot you plan to use.
- Consider whether moving an RB, WR, or TE between a normal position slot and FLEX creates better late-game contingency options.
- When two lineup configurations are otherwise reasonably close, prefer the configuration that preserves more viable unlocked replacement options for the uncertain later-playing starter.
- Do not claim a late-game contingency exists unless the contingency tool identifies an actual unlocked roster player or current free agent who can legally fill that slot.
- For every injured or questionable player materially affecting the lineup, separate:
  1. Yahoo designation,
  2. latest reported injury,
  3. latest practice participation,
  4. official game status.



- Include the date of the latest supporting injury/practice information in your reasoning.
- Never invent, translate, or generalize an injury body part.
- If official Week injury reports have not started yet, say so and use older camp information only as background.
BREAKING NEWS EXCEPTION
- Search for any X.com post from Adam Schefter (@AdamSchefter) or Ian Rapoport (@RapSheet) published within the last 48 hours when researching injuries, player availability, transactions, depth-chart changes, or other time-sensitive player news.
- A verified recent Schefter or Rapoport post may be newer and more relevant than an older official team article.
- Treat these posts as breaking-news reporting, not as official NFL injury-report designations.
- Only use an X post if the actual post and its author can be directly verified. Do not rely on another website merely quoting or paraphrasing the post.
- When relying on one, explicitly state:
  1. Adam Schefter or Ian Rapoport
  2. X.com
  3. the post date
  4. the post time when available
  5. a concise description of what the post actually reports
- Never attribute information from a Schefter or Rapoport post to the player's NFL team, NFL.com, ESPN, FantasyPros, or another source.
- For every materially injured or questionable starter, search specifically for credible updates from the last 48 hours even if an older official team injury article has already been found.
- Distinguish newest official team information from newer credible reporter/beat-reporter information.

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


def validate_plan(plan):
    lineup = plan.lineup

    return check_lineup(
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


def build_validated_lineup(max_attempts=3):
    prompt = """
Build my best starting lineup for the current fantasy week.

Use my actual roster, league settings, current NFL schedule,
current injury information, and current player roles.

Return the best complete starting lineup.
"""

    last_validation = None

    for attempt in range(1, max_attempts + 1):
        result = Runner.run_sync(
            lineup_agent,
            prompt,
        )

        plan = result.final_output_as(
            LineupPlan,
            raise_if_incorrect_type=True,
        )

        validation = validate_plan(plan)

        if validation["is_legal"]:
            return {
                "is_legal": True,
                "attempts": attempt,
                "plan": plan.model_dump(),
                "validation": validation,
            }

        last_validation = validation

        prompt = f"""
Your previous proposed lineup failed deterministic Python validation.

Previous proposal:
{plan.model_dump_json(indent=2)}

Validation errors:
{json.dumps(validation["errors"], indent=2)}

Correct the lineup.

Use only current roster players.
Every required starting slot must be filled.
Do not duplicate a player.
Respect positional eligibility.

Return a corrected complete lineup.
"""

    raise RuntimeError(
        "Unable to generate a legal starting lineup after "
        f"{max_attempts} attempts. "
        f"Last validation errors: "
        f"{last_validation['errors'] if last_validation else 'unknown'}"
    )