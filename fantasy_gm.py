from dotenv import load_dotenv
from agents import (
    Agent,
    Runner,
    WebSearchTool,
    SQLiteSession,
    RunConfig,
    SessionSettings,
)

from league_tools import get_league_settings
from roster_tools import get_my_roster
from waiver_tools import get_available_players, get_available_player_summary
from schedule_tools import get_roster_schedule, get_next_roster_lock
from lineup_tools import validate_lineup
from contingency_tools import get_lock_aware_player_pool


load_dotenv()

with open("gm_instructions.txt", "r", encoding="utf-8") as f:
    FANTASY_GM_INSTRUCTIONS = f.read()

agent = Agent(
    name="Yahoo Fantasy GM",
    instructions=FANTASY_GM_INSTRUCTIONS,
    model="gpt-5.6-luna",
    tools=[
        get_league_settings,
        get_my_roster,
        get_available_players,
        get_available_player_summary,
        get_roster_schedule,
        get_next_roster_lock,
        get_lock_aware_player_pool,
        validate_lineup,
        WebSearchTool(),
    ],
)

session = SQLiteSession(
    session_id="fantasy_gm_2026",
    db_path="data/fantasy_gm_history.db",
)

print("Yahoo Fantasy GM is online.")
print("Type 'quit' to exit.\n")

while True:
    print("\nYou:")
    print("(Enter your request. Type END on its own line when finished.)")

    lines = []

    while True:
        line = input()

        if line.strip().upper() == "END":
            break

        lines.append(line)

    user_input = "\n".join(lines).strip()

    if user_input.lower() in {"quit", "exit"}:
        break

    if not user_input:
        continue

    result = Runner.run_sync(
    agent,
    user_input,
    session=session,
    run_config=RunConfig(
        session_settings=SessionSettings(
            limit=12
        )
    ),
)

    print(f"\nFantasy GM:\n{result.final_output}\n")