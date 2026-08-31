from dotenv import load_dotenv
from agents import Agent, Runner

load_dotenv()

agent = Agent(
    name="Fantasy GM Test",
    instructions="You are a concise fantasy football assistant.",
    model="gpt-5.6-luna",
)

result = Runner.run_sync(
    agent,
    "Reply exactly with: Fantasy agent is online."
)

print(result.final_output)
