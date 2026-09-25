from dotenv import load_dotenv
from agents import Agent, Runner

from usage_tracker import (
    record_run_usage,
    reset_usage,
    print_usage_report,
)

load_dotenv()

reset_usage()

agent = Agent(
    name="Fantasy GM Test",
    instructions="You are a concise fantasy football assistant.",
    model="gpt-5.6-luna",
)

result = Runner.run_sync(
    agent,
    "Reply exactly with: Fantasy agent is online."
)

record_run_usage(
    "Agent connectivity test",
    agent.model,
    result,
)

print(result.final_output)

print_usage_report()

