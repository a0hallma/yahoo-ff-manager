import json

from dotenv import load_dotenv
from agents import Agent, Runner, WebSearchTool

from league_tools import get_league_settings
from roster_tools import get_my_roster
from waiver_tools import get_available_players, get_available_player_summary
from schedule_tools import get_roster_schedule, get_next_roster_lock
from lineup_tools import validate_lineup
from health_tools import build_data_health_report
from lineup_planner import build_validated_lineup
from contingency_tools import get_lock_aware_player_pool

load_dotenv()

with open("gm_instructions.txt", "r", encoding="utf-8") as f:
    gm_instructions = f.read()

with open("weekly_report_prompt.txt", "r", encoding="utf-8") as f:
    weekly_report_prompt = f.read()

agent = Agent(
    name="Yahoo Fantasy Weekly GM",
    instructions=gm_instructions,
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

def render_validated_lineup_section(validated):
    plan = validated["plan"]
    lineup = plan["lineup"]

    lines = [
        "## 1. WEEKLY LINEUP",
        "",
        "**Validated recommended lineup**",
        "",
        f"- **QB:** {lineup['qb']}",
        f"- **RB:** {lineup['rb1']}",
        f"- **RB:** {lineup['rb2']}",
        f"- **WR:** {lineup['wr1']}",
        f"- **WR:** {lineup['wr2']}",
        f"- **TE:** {lineup['te']}",
        f"- **FLEX:** {lineup['flex']}",
        f"- **K:** {lineup['k']}",
        f"- **DEF:** {lineup['defense']}",
        "",
        "**Why:**",
        plan["rationale"],
    ]

    monitor = plan.get("monitor", [])

    if monitor:
        lines.extend(
            [
                "",
                "**Monitor:**",
            ]
        )

        for item in monitor:
            lines.append(f"- {item}")

    lines.extend(
        [
            "",
            "**Python validation:** PASS",
        ]
    )

    return "\n".join(lines)

print("Checking fantasy data...")

health = build_data_health_report()

print(f"DATA HEALTH: {health['overall_status']}")

problems = [
    check
    for check in health["checks"]
    if check["status"] in {"WARN", "FAIL"}
]

for check in problems:
    print(
        f"{check['status']}: "
        f"{check['name']} — {check['detail']}"
    )

if health["overall_status"] == "FAIL":
    print()
    print(
        "Weekly report cancelled because required fantasy data "
        "failed validation."
    )
    raise SystemExit(1)

print()

print("Building validated starting lineup...")

try:
    validated_lineup = build_validated_lineup()
except Exception as exc:
    print()
    print(f"LINEUP VALIDATION: FAIL — {exc}")
    print("Weekly report cancelled.")
    raise SystemExit(1)

print(
    f"LINEUP VALIDATION: PASS "
    f"({validated_lineup['attempts']} attempt(s))"
)

print()

print("Generating weekly Fantasy GM report...")
print("This may take a minute because current NFL information is being researched.\n")

validated_plan_json = json.dumps(
    validated_lineup["plan"],
    indent=2,
)

report_input = f"""
{weekly_report_prompt}

AUTHORITATIVE VALIDATED LINEUP

The following starting lineup has already been generated and independently
validated by Python.

Use it as the authoritative starting lineup for every recommendation in
sections 2 through 8.

Do not generate or print another WEEKLY LINEUP section.
Do not substitute different starters unless discussing an explicit injury
contingency.

{validated_plan_json}
"""

result = Runner.run_sync(
    agent,
    report_input,
)

print()
print(render_validated_lineup_section(validated_lineup))
print()
print(result.final_output)