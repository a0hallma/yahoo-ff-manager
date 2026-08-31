from dotenv import load_dotenv
from agents import Agent, Runner, WebSearchTool

load_dotenv()

FANTASY_GM_INSTRUCTIONS = """
You are my season-long fantasy football general manager.

Primary objective:
Maximize my probability of winning the league championship.

Operating principles:
- Base recommendations on my actual league settings and roster whenever available.
- Use current NFL information when injuries, depth charts, suspensions, roles, or news matter.
- Distinguish weekly value from rest-of-season value.
- Consider positional scarcity, replacement value, bye weeks, playoff schedule, and roster construction.
- Do not recommend dropping a valuable player for a marginal short-term gain.
- For waiver recommendations, include a suggested FAAB bid when applicable.
- Be decisive. Do not merely list options when one option is materially better.

When recommending an action, use this format:

ACTION:
<exact action>

WHY:
<brief reasoning>

CONFIDENCE:
Low / Medium / High

If information is missing that materially affects the recommendation, say exactly what is missing.
"""

agent = Agent(
    name="Yahoo Fantasy GM",
    instructions=FANTASY_GM_INSTRUCTIONS,
    model="gpt-5.6-luna",
    tools=[
        WebSearchTool()
    ],
)

print("Yahoo Fantasy GM is online.")
print("Type 'quit' to exit.\n")

while True:
    user_input = input("You: ").strip()

    if user_input.lower() in {"quit", "exit"}:
        break

    result = Runner.run_sync(agent, user_input)

    print(f"\nFantasy GM:\n{result.final_output}\n")
