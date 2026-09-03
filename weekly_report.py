import json

from dotenv import load_dotenv
from agents import Agent, Runner, WebSearchTool

from league_tools import get_league_settings
from roster_tools import get_my_roster
from waiver_tools import (
    get_available_players,
    get_available_player_summary,
)
from schedule_tools import (
    get_roster_schedule,
    get_next_roster_lock,
)
from lineup_tools import validate_lineup
from health_tools import build_data_health_report
from lineup_planner import build_validated_lineup
from contingency_tools import get_lock_aware_player_pool
from transaction_tools import validate_add_drop
from transaction_planner import build_validated_transaction
from contingency_planner import build_all_validated_contingencies
from injury_researcher import build_injury_research_snapshot
from contingency_renderer import render_validated_contingencies


load_dotenv()


with open(
    "gm_instructions.txt",
    "r",
    encoding="utf-8",
) as f:
    gm_instructions = f.read()


with open(
    "weekly_report_prompt.txt",
    "r",
    encoding="utf-8",
) as f:
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
        validate_add_drop,
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

    monitor = plan.get(
        "monitor",
        [],
    )

    if monitor:
        lines.extend(
            [
                "",
                "**Monitor:**",
            ]
        )

        for item in monitor:
            lines.append(
                f"- {item}"
            )

    lines.extend(
        [
            "",
            "**Python validation:** PASS",
        ]
    )

    return "\n".join(lines)


def render_validated_transaction_section(validated):
    recommendation = validated[
        "recommendation"
    ]

    lines = [
        "## 5. ROSTER MOVES",
        "",
    ]

    if validated.get(
        "transaction_blocked",
        False,
    ):
        freshness = validated.get(
            "availability_check",
            {},
        )

        age_days = freshness.get(
            "age_days"
        )

        last_updated = freshness.get(
            "last_updated"
        )

        lines.extend(
            [
                "**STATUS: BLOCKED — REFRESH YAHOO AVAILABILITY**",
                "",
            ]
        )

        if age_days is not None:
            lines.append(
                f"Available-player data is **{age_days} day(s) old**."
            )

        if last_updated:
            lines.append(
                f"Last Yahoo availability snapshot: "
                f"**{last_updated}**."
            )

        lines.extend(
            [
                "",
                "Do not execute an add/drop transaction until "
                "Yahoo availability is refreshed.",
                "",
                "The Fantasy GM did not evaluate or recommend an "
                "executable roster move because current player "
                "availability could not be verified.",
                "",
                "**Python transaction validation:** BLOCKED — "
                "stale available-player data.",
            ]
        )

        return "\n".join(lines)

    if not validated["recommend_move"]:
        lines.extend(
            [
                "**Recommendation:** Stand pat.",
                "",
                recommendation["rationale"],
                "",
                f"**Confidence:** "
                f"{recommendation['confidence']}",
                "",
                "**Python transaction validation:** "
                "No transaction required.",
            ]
        )

        return "\n".join(lines)

    validation = validated[
        "validation"
    ]

    add = validation[
        "add"
    ]

    drop = validation[
        "drop"
    ]

    if add["availability"] == "FA":
        availability_text = (
            "Free agent (FA)"
        )
    else:
        availability_text = (
            "Waivers"
        )

    lines.extend(
        [
            f"**ADD:** {add['name']} — "
            f"{add['position']}, "
            f"{add['nfl_team']}",
            "",
            f"**DROP:** {drop['name']} — "
            f"{drop['position']}, "
            f"{drop['nfl_team']}",
            "",
            f"**Availability:** "
            f"{availability_text}",
        ]
    )

    if add.get(
        "waiver_date"
    ):
        lines.append(
            f"**Waiver date:** "
            f"{add['waiver_date']}"
        )

    lines.extend(
        [
            "",
            "**Why:**",
            recommendation["rationale"],
            "",
            f"**Confidence:** "
            f"{recommendation['confidence']}",
            "",
            "**Resulting roster:**",
        ]
    )

    position_counts = validation.get(
        "resulting_position_counts",
        {},
    )

    position_text = ", ".join(
        f"{position}: {count}"
        for position, count
        in position_counts.items()
    )

    lines.append(
        position_text
    )

    warnings = validation.get(
        "warnings",
        [],
    )

    if warnings:
        lines.extend(
            [
                "",
                "**Validation warnings:**",
            ]
        )

        for warning in warnings:
            lines.append(
                f"- {warning}"
            )

    lines.extend(
        [
            "",
            "**Python transaction validation:** PASS",
        ]
    )

    return "\n".join(lines)


print(
    "Checking fantasy data..."
)

health = (
    build_data_health_report()
)

print(
    f"DATA HEALTH: "
    f"{health['overall_status']}"
)

problems = [
    check
    for check in health["checks"]
    if check["status"]
    in {
        "WARN",
        "FAIL",
    }
]

for check in problems:
    print(
        f"{check['status']}: "
        f"{check['name']} — "
        f"{check['detail']}"
    )

if (
    health["overall_status"]
    == "FAIL"
):
    print()
    print(
        "Weekly report cancelled because required "
        "fantasy data failed validation."
    )

    raise SystemExit(1)

print()


print(
    "Researching current injury facts..."
)

try:
    injury_snapshot = (
        build_injury_research_snapshot()
    )

except Exception as exc:
    print()
    print(
        f"INJURY RESEARCH: FAIL — "
        f"{exc}"
    )
    print(
        "Weekly report cancelled."
    )

    raise SystemExit(1)

print(
    f"INJURY RESEARCH: PASS "
    f"({injury_snapshot['player_count']} player(s), "
    f"{injury_snapshot.get('research_attempts', 0)} "
    f"attempt(s))"
)

print()


print(
    "Building validated starting lineup..."
)

try:
    validated_lineup = (
        build_validated_lineup(
            injury_snapshot=injury_snapshot
        )
    )

except Exception as exc:
    print()
    print(
        f"LINEUP VALIDATION: FAIL — "
        f"{exc}"
    )
    print(
        "Weekly report cancelled."
    )

    raise SystemExit(1)

print(
    f"LINEUP VALIDATION: PASS "
    f"({validated_lineup['attempts']} "
    f"attempt(s))"
)

print()


print(
    "Building validated contingencies..."
)

try:
    validated_contingencies = (
        build_all_validated_contingencies(
            validated_lineup[
                "plan"
            ][
                "lineup"
            ]
        )
    )

except Exception as exc:
    import traceback

    print()
    traceback.print_exc()
    print()

    print(
        f"CONTINGENCY VALIDATION: FAIL — "
        f"{exc}"
    )
    print(
        "Weekly report cancelled."
    )

    raise SystemExit(1)

print(
    f"CONTINGENCY VALIDATION: PASS "
    f"({validated_contingencies['candidate_count']} "
    f"candidate(s))"
)

print()


with open(
    "data/validated_contingencies.json",
    "w",
    encoding="utf-8",
) as f:
    json.dump(
        validated_contingencies,
        f,
        indent=2,
    )


print(
    "Evaluating roster move..."
)

try:
    validated_transaction = (
        build_validated_transaction()
    )

except Exception as exc:
    print()
    print(
        f"TRANSACTION VALIDATION: FAIL — "
        f"{exc}"
    )
    print(
        "Weekly report cancelled."
    )

    raise SystemExit(1)


if validated_transaction.get(
    "transaction_blocked",
    False,
):
    freshness = (
        validated_transaction.get(
            "availability_check",
            {},
        )
    )

    age_days = freshness.get(
        "age_days"
    )

    if age_days is not None:
        print(
            "TRANSACTION VALIDATION: BLOCKED "
            f"(available-player snapshot is "
            f"{age_days} day(s) old)"
        )

    else:
        print(
            "TRANSACTION VALIDATION: BLOCKED "
            "(available-player data is not current)"
        )

elif validated_transaction[
    "recommend_move"
]:
    print(
        f"TRANSACTION VALIDATION: PASS "
        f"({validated_transaction['attempts']} "
        f"attempt(s))"
    )

else:
    print(
        "TRANSACTION VALIDATION: PASS "
        "(standing pat recommended)"
    )

print()


print(
    "Generating weekly Fantasy GM report..."
)

print(
    "This may take a minute because current NFL "
    "information is being researched.\n"
)


validated_plan_json = json.dumps(
    validated_lineup[
        "plan"
    ],
    indent=2,
)

injury_snapshot_json = json.dumps(
    injury_snapshot,
    indent=2,
)

validated_transaction_json = json.dumps(
    validated_transaction,
    indent=2,
)

validated_contingencies_json = json.dumps(
    validated_contingencies,
    indent=2,
)


report_input = f"""
{weekly_report_prompt}

AUTHORITATIVE VALIDATED LINEUP

The following starting lineup has already been generated and
independently validated by Python.

Use it as the authoritative starting lineup for every recommendation
in sections 2 through 9.

Do not generate or print another WEEKLY LINEUP section.

Do not substitute different starters unless discussing an explicit
independently validated injury contingency.

{validated_plan_json}


AUTHORITATIVE INJURY SNAPSHOT

The following injury research has already been researched,
source-validated, and used by the lineup planner.

This is the single authoritative source for injury facts in this
report.

Rules:

- Use yahoo_status exactly as supplied.
- Use exact_reported_injury exactly as supplied.
- Do not rename, translate, or generalize an injury.
- Do not convert psoas soreness into groin injury.
- Use latest_practice_participation exactly as supplied.
- If participation is "Not specified", do not infer Full or Limited.
- Use official_game_status exactly as supplied.
- If it is "Not yet available", do not invent an official
  designation.
- Reporter expectations are not official game statuses.
- Do not independently research or replace these injury facts.
- You may still research non-injury role, workload, matchup, or
  depth-chart information when useful.

{injury_snapshot_json}


AUTHORITATIVE VALIDATED CONTINGENCIES

The following contingency data has already been generated and
independently validated by Python.

Do not invent or reconstruct different contingency lineup changes.

Python will render the exact contingency changes in Section 3.

{validated_contingencies_json}


AUTHORITATIVE TRANSACTION ANALYSIS

The following transaction analysis has already been generated by the
transaction planner and checked by Python.

{validated_transaction_json}

Transaction rules:

- If transaction_blocked=true, current Yahoo availability could not
  be verified.
- If transaction_blocked=true, do NOT describe the result as
  "standing pat."
- If transaction_blocked=true, state that roster-move analysis is
  blocked until Yahoo availability is refreshed.
- If transaction_blocked=true, do not claim any player is currently
  available based on the stale snapshot.
- If transaction_blocked=true, do not recommend an executable
  add/drop elsewhere in the report.
- If transaction_blocked=true, do not present a stale free-agent
  candidate as a confirmed current free agent.
- If transaction_blocked=false and recommend_move=false, standing
  pat is the authoritative transaction decision.
- If transaction_blocked=false and recommend_move=true, use the exact
  validated add player and drop player.
- Do not generate a different specific add/drop transaction.
"""


result = Runner.run_sync(
    agent,
    report_input,
)


contingency_marker = (
    "[[VALIDATED_CONTINGENCIES]]"
)

transaction_marker = (
    "[[ROSTER_MOVES_SECTION]]"
)


contingency_marker_count = (
    result.final_output.count(
        contingency_marker
    )
)

if contingency_marker_count != 1:
    print()
    print(
        "REPORT ASSEMBLY: FAIL — expected exactly one "
        "VALIDATED_CONTINGENCIES marker, "
        f"found {contingency_marker_count}."
    )

    raise SystemExit(1)


transaction_marker_count = (
    result.final_output.count(
        transaction_marker
    )
)

if transaction_marker_count != 1:
    print()
    print(
        "REPORT ASSEMBLY: FAIL — expected exactly one "
        "ROSTER_MOVES_SECTION marker, "
        f"found {transaction_marker_count}."
    )

    raise SystemExit(1)


report_text = (
    result.final_output
)


duplicate_heading = (
    "## 5. ROSTER MOVES\n\n"
    + transaction_marker
)

if duplicate_heading in report_text:
    report_text = (
        report_text.replace(
            duplicate_heading,
            transaction_marker,
            1,
        )
    )


contingency_section = (
    render_validated_contingencies(
        validated_contingencies,
        validated_lineup[
            "plan"
        ][
            "lineup"
        ],
        availability_check=validated_transaction.get(
            "availability_check",
            {},
        ),
    )
)


transaction_section = (
    render_validated_transaction_section(
        validated_transaction
    )
)


report_body = (
    report_text.replace(
        contingency_marker,
        contingency_section,
    )
)

report_body = (
    report_body.replace(
        transaction_marker,
        transaction_section,
    )
)


print()

print(
    render_validated_lineup_section(
        validated_lineup
    )
)

print()

print(
    report_body
)