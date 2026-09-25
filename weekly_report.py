import argparse
import json
from pathlib import Path

from dotenv import load_dotenv
from agents import Agent, Runner, WebSearchTool

from usage_tracker import (
    record_run_usage,
    reset_usage,
    print_usage_report,
    save_usage_report,
)

from provider_context import (
    set_current_provider,
    get_current_provider,
    get_provider_display_name,
)
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
from trade_planner import build_validated_trade_plan
from contingency_planner import build_all_validated_contingencies
from injury_researcher import build_injury_research_snapshot
from contingency_renderer import render_validated_contingencies
from trade_renderer import render_validated_trade_section
from sleeper.live_refresh import (
    refresh_sleeper_acquisition_snapshot,
)
from league_roster_tools import (
    build_league_roster_summary,
)



load_dotenv()


with open(
    "gm_instructions.txt",
    "r",
    encoding="utf-8",
) as file:
    GM_INSTRUCTIONS = file.read()


with open(
    "weekly_report_prompt.txt",
    "r",
    encoding="utf-8",
) as file:
    WEEKLY_REPORT_PROMPT = file.read()


VALIDATED_CONTINGENCY_FILES = {
    "yahoo": Path("data/validated_contingencies.json"),
    "sleeper": Path("data/sleeper_validated_contingencies.json"),
}


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Generate the weekly Fantasy GM report for "
            "the selected fantasy provider."
        )
    )

    parser.add_argument(
        "provider",
        choices=[
            "yahoo",
            "sleeper",
        ],
        help="Fantasy provider to analyze.",
    )

    return parser.parse_args()


def build_weekly_agent():
    provider = get_current_provider()
    provider_name = get_provider_display_name()

    tools = [
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
    ]

    # League-wide Sleeper rosters are available for
    # deterministic trade-partner analysis.

    return Agent(
        name=f"{provider_name} Fantasy Weekly GM",
        instructions=GM_INSTRUCTIONS,
        model="gpt-5.6-luna",
        tools=tools,
    )

def build_trade_context():
    """
    Build provider-specific league-wide roster context
    for trade analysis.

    Sleeper currently has live league-wide roster data.

    Yahoo trade analysis remains unavailable until equivalent
    Yahoo league-wide roster data is integrated.
    """

    provider = get_current_provider()
    provider_name = get_provider_display_name()

    if provider != "sleeper":
        return {
            "provider": provider,
            "provider_name": provider_name,
            "league_wide_rosters_available": False,
            "reason": (
                "Current league-wide opposing-team roster "
                "data has not yet been integrated for "
                f"{provider_name}."
            ),
        }

    try:
        summary = (
            build_league_roster_summary()
        )

    except Exception as exc:
        return {
            "provider": provider,
            "provider_name": provider_name,
            "league_wide_rosters_available": False,
            "reason": str(exc),
        }

    return {
        "provider": provider,
        "provider_name": provider_name,
        "league_wide_rosters_available": True,
        "league_id": summary.get(
            "league_id"
        ),
        "league_name": summary.get(
            "league_name"
        ),
        "generated_at": summary.get(
            "generated_at"
        ),
        "team_count": summary.get(
            "team_count"
        ),
        "teams": summary.get(
            "teams",
            [],
        ),
    }


def render_validated_lineup_section(validated):
    plan = validated["plan"]
    lineup = plan["lineup"]

    lines = [
        "## 1. WEEKLY LINEUP",
        "",
        "**Best lineup using players currently on your roster**",
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

    key_decisions = plan.get(
        "key_decisions",
        [],
    )

    if key_decisions:
        lines.extend(
            [
                "",
                "**Key lineup decisions:**",
            ]
        )

        for decision in key_decisions:
            decision_type = (
                decision.get(
                    "decision_type",
                    "",
                )
            )

            type_label = (
                "Start/sit"
                if decision_type
                == "start_over_bench"
                else "Slot assignment"
            )

            lines.extend(
                [
                    "",
                    f"- **{type_label}: "
                    f"{decision.get('decision', '')}**",
                    f"  - Selected case: "
                    f"{decision.get('selected_player_case', '')}",
                    f"  - Alternative case: "
                    f"{decision.get('alternative_player_case', '')}",
                ]
            )

            factors = decision.get(
                "deciding_factors",
                [],
            )

            if factors:
                lines.append(
                    "  - Deciding factors: "
                    + "; ".join(
                        factors
                    )
                )

            confidence = (
                decision.get(
                    "confidence",
                    "",
                )
                or ""
            ).strip()

            if confidence:
                lines.append(
                    f"  - Confidence: "
                    f"{confidence.capitalize()}"
                )

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
    provider = validated.get(
        "provider",
        get_current_provider(),
    )

    provider_name = validated.get(
        "provider_name",
        get_provider_display_name(),
    )

    recommendation = validated[
        "recommendation"
    ]

    lines = [
        "## 5. ROSTER OPTIMIZATION",
        "",
    ]

    if validated.get(
        "transaction_blocked",
        False,
    ):
        blocked_reason = validated.get(
            "blocked_reason",
            "transaction_blocked",
        )

        freshness = validated.get(
            "availability_check",
            {},
        )

        lines.extend(
            [
                "**STATUS: BLOCKED**",
                "",
            ]
        )

        if blocked_reason == "stale_available_player_snapshot":
            age_days = freshness.get(
                "age_days"
            )

            age_minutes = freshness.get(
                "age_minutes"
            )

            last_updated = freshness.get(
                "last_updated"
            )

            if age_minutes is not None:
                lines.append(
                    f"{provider_name} available-player data is "
                    f"**{age_minutes} minute(s) old**."
                )

            elif age_days is not None:
                lines.append(
                    f"{provider_name} available-player data is "
                    f"**{age_days} day(s) old**."
                )

            if last_updated:
                lines.append(
                    f"Last {provider_name} availability snapshot: "
                    f"**{last_updated}**."
                )

            lines.extend(
                [
                    "",
                    "Executable roster optimization is blocked "
                    f"until {provider_name} availability is refreshed.",
                ]
            )

        elif blocked_reason == "unverified_sleeper_acquisition_state":
            lines.extend(
                [
                    "Sleeper confirms which players are unrostered, "
                    "but the current data does not establish whether "
                    "each player is immediately addable or subject "
                    "to waivers.",
                    "",
                    "No specific Sleeper add/drop is presented as "
                    "executable until that acquisition state is verified.",
                ]
            )

        else:
            rationale = recommendation.get(
                "rationale"
            )

            if rationale:
                lines.append(
                    rationale
                )

            validation = validated.get(
                "validation"
            )

            if validation:
                validation_reason = validation.get(
                    "block_reason"
                )

                if validation_reason:
                    lines.extend(
                        [
                            "",
                            str(validation_reason),
                        ]
                    )

        lines.extend(
            [
                "",
                "**Python transaction validation:** BLOCKED",
            ]
        )

        return "\n".join(lines)

    if not validated[
        "recommend_move"
    ]:
        lines.extend(
            [
                "**Recommendation:** Stand pat.",
                "",
                recommendation["rationale"],
            ]
        )

        if recommendation.get(
            "this_week_impact"
        ):
            lines.extend(
                [
                    "",
                    "**This week:**",
                    recommendation[
                        "this_week_impact"
                    ],
                ]
            )

        if recommendation.get(
            "next_four_weeks_impact"
        ):
            lines.extend(
                [
                    "",
                    "**Next four weeks:**",
                    recommendation[
                        "next_four_weeks_impact"
                    ],
                ]
            )

        if recommendation.get(
            "bye_week_impact"
        ):
            lines.extend(
                [
                    "",
                    "**Bye-week planning:**",
                    recommendation[
                        "bye_week_impact"
                    ],
                ]
            )

        lines.extend(
            [
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

    post_move_validation = validated.get(
        "post_move_lineup_validation",
        {},
    )

    add = validation[
        "add"
    ]

    drop = validation[
        "drop"
    ]

    availability = add.get(
        "availability"
    )

    if availability == "FA":
        availability_text = (
            "Free agent (FA) - immediately addable"
        )

    elif availability == "W":
        availability_text = (
            "Waivers (W) - conditional on claim clearing"
        )

    else:
        availability_text = (
            str(availability)
            if availability
            else "Unknown"
        )

    lines.extend(
        [
            "**Primary recommended move**",
            "",
            f"**ADD:** {add['name']} - "
            f"{add['position']}, "
            f"{add['nfl_team']}",
            "",
            f"**DROP:** {drop['name']} - "
            f"{drop['position']}, "
            f"{drop['nfl_team']}",
            "",
            f"**Availability:** "
            f"{availability_text}",
            "",
            f"**Priority:** "
            f"{recommendation.get('priority', 'Not specified')}",
            "",
            f"**Move type:** "
            f"{recommendation.get('move_category', 'Not specified')}",
            "",
            f"**Starts this week:** "
            + (
                "Yes"
                if recommendation.get(
                    "starts_this_week"
                )
                else "No"
            ),
        ]
    )

    if recommendation.get(
        "starts_this_week"
    ):
        lines.extend(
            [
                "",
                f"**Starter displaced:** "
                f"{recommendation.get('starter_replaced')}",
                "",
                "**Why the add earns a start this week:**",
                recommendation.get(
                    "starter_upgrade_rationale",
                    "",
                ),
            ]
        )

    if add.get(
        "waiver_date"
    ):
        lines.append(
            f"**Waiver date:** "
            f"{add['waiver_date']}"
        )

    drop_candidates = recommendation.get(
        "drop_candidates_considered",
        [],
    )

    if drop_candidates:
        lines.extend(
            [
                "",
                "**Drop candidates considered:**",
            ]
        )

        selected_drop_name = (
            drop.get(
                "name",
                "",
            )
        )

        for candidate in drop_candidates:
            selected_marker = (
                " **(SELECTED DROP)**"
                if candidate.get(
                    "player_name"
                ) == selected_drop_name
                else ""
            )

            lines.extend(
                [
                    "",
                    f"- **{candidate.get('player_name')}**"
                    f"{selected_marker}",
                    f"  - Keep case: "
                    f"{candidate.get('retain_case', '')}",
                    f"  - Drop case: "
                    f"{candidate.get('drop_case', '')}",
                    f"  - Next four weeks: "
                    f"{candidate.get('next_four_weeks_outlook', '')}",
                    f"  - Rest of season: "
                    f"{candidate.get('rest_of_season_outlook', '')}",
                ]
            )

    if recommendation.get(
        "temporary_unavailability_drop"
    ):
        lines.extend(
            [
                "",
                "**Temporary-unavailability drop justification:**",
                recommendation.get(
                    "temporary_unavailability_drop_justification",
                    "",
                ),
            ]
        )

    lines.extend(
        [
            "",
            "**Why this move:**",
            recommendation["rationale"],
        ]
    )

    if recommendation.get(
        "this_week_impact"
    ):
        lines.extend(
            [
                "",
                "**This week's impact:**",
                recommendation[
                    "this_week_impact"
                ],
            ]
        )

    if recommendation.get(
        "next_four_weeks_impact"
    ):
        lines.extend(
            [
                "",
                "**Next four weeks:**",
                recommendation[
                    "next_four_weeks_impact"
                ],
            ]
        )

    if recommendation.get(
        "bye_week_impact"
    ):
        lines.extend(
            [
                "",
                "**Bye-week planning:**",
                recommendation[
                    "bye_week_impact"
                ],
            ]
        )

    if recommendation.get(
        "rest_of_season_outlook"
    ):
        lines.extend(
            [
                "",
                "**Rest-of-season outlook:**",
                recommendation[
                    "rest_of_season_outlook"
                ],
            ]
        )

    optimized_lineup = (
        recommendation.get(
            "optimized_lineup"
        )
        or {}
    )

    if optimized_lineup:
        lines.extend(
            [
                "",
                (
                    "**Conditional optimized lineup if waiver claim "
                    "clears**"
                    if availability == "W"
                    else "**Optimized lineup after the move**"
                ),
                "",
                f"- **QB:** {optimized_lineup['qb']}",
                f"- **RB:** {optimized_lineup['rb1']}",
                f"- **RB:** {optimized_lineup['rb2']}",
                f"- **WR:** {optimized_lineup['wr1']}",
                f"- **WR:** {optimized_lineup['wr2']}",
                f"- **TE:** {optimized_lineup['te']}",
                f"- **FLEX:** {optimized_lineup['flex']}",
                f"- **K:** {optimized_lineup['k']}",
                f"- **DEF:** {optimized_lineup['defense']}",
            ]
        )

        if recommendation.get(
            "optimized_lineup_rationale"
        ):
            lines.extend(
                [
                    "",
                    "**Why this optimized lineup:**",
                    recommendation[
                        "optimized_lineup_rationale"
                    ],
                ]
            )

    lineup_changes = validated.get(
        "lineup_changes",
        [],
    )

    lines.extend(
        [
            "",
            "**Current-week lineup changes after move:**",
        ]
    )

    if lineup_changes:
        for change in lineup_changes:
            lines.append(
                (
                    f"- **{change['slot'].upper()}:** "
                    f"{change['before']} -> {change['after']}"
                )
            )

    else:
        lines.append(
            "- No starting-slot change; the move improves depth, "
            "bye-week coverage, or future value."
        )

    position_counts = validation.get(
        "resulting_position_counts",
        {},
    )

    if position_counts:
        position_text = ", ".join(
            f"{position}: {count}"
            for position, count
            in position_counts.items()
        )

        lines.extend(
            [
                "",
                "**Resulting roster composition:**",
                position_text,
            ]
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
            f"**Confidence:** "
            f"{recommendation['confidence']}",
            "",
            "**Python transaction validation:** PASS",
            "**Python post-move lineup validation:** "
            + (
                "PASS"
                if post_move_validation.get(
                    "is_valid"
                )
                else "FAIL"
            ),
            "**Python optimization-strategy validation:** "
            + (
                "PASS"
                if validated.get(
                    "strategy_validation",
                    {},
                ).get(
                    "is_valid"
                )
                else "FAIL"
            ),
        ]
    )

    return "\n".join(lines)


def save_validated_contingencies(
    validated_contingencies,
):
    provider = get_current_provider()

    output_file = (
        VALIDATED_CONTINGENCY_FILES[
            provider
        ]
    )

    output_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with output_file.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            validated_contingencies,
            file,
            indent=2,
        )

    return output_file

def validate_final_report_safety(
    report_text,
    validated_contingencies,
    trade_context,
):
    """
    Catch report statements that contradict authoritative
    deterministic data.

    This is intentionally conservative. A generated report
    should fail validation rather than present fabricated
    lineup-lock, contingency, or trade conclusions.
    """

    errors = []

    text = (
        report_text
        or ""
    )

    lower_text = text.lower()

    forbidden_lock_phrases = [
        "sunday slate lock",
        "sunday lineup lock",
        "all sunday starters lock at 1",
        "all sunday players lock at 1",
    ]

    for phrase in forbidden_lock_phrases:
        if phrase in lower_text:
            errors.append(
                "Report invented a global Sunday lineup lock: "
                f"{phrase}"
            )

    candidate_count = validated_contingencies.get(
        "candidate_count",
        0,
    )

    if candidate_count == 0:
        contingency_phrases = [
            "follow the validated contingency",
            "follow validated contingency",
            "validated contingency in section 3",
        ]

        for phrase in contingency_phrases:
            if phrase in lower_text:
                errors.append(
                    "Report referenced a validated contingency "
                    "even though candidate_count=0."
                )
                break

    league_rosters_available = trade_context.get(
        "league_wide_rosters_available",
        False,
    )

    if not league_rosters_available:
        unsafe_trade_phrases = [
            "no trades are worth exploring",
            "no trade is worth exploring",
        ]

        for phrase in unsafe_trade_phrases:
            if phrase in lower_text:
                errors.append(
                    "Report made a trade conclusion without "
                    "league-wide opposing rosters."
                )
                break

    return {
        "is_valid": not errors,
        "errors": errors,
    }


def insert_validated_trade_section(
    report_text,
    trade_section,
):
    """
    Deterministically own Section 8.

    Replace any AI-generated Section 8 with the validated
    Python-rendered trade section.

    If Section 8 is missing, insert it immediately before
    Section 9.
    """

    section_8_heading = (
        "## 8. TRADE OPPORTUNITIES"
    )

    section_9_heading = (
        "## 9. ACTION PLAN"
    )

    if section_9_heading not in report_text:
        raise RuntimeError(
            "Unable to insert validated trade section because "
            "the report is missing the Section 9 heading."
        )

    replacement = (
        f"{section_8_heading}\n\n"
        f"{trade_section.strip()}\n\n"
    )

    section_8_index = report_text.find(
        section_8_heading
    )

    section_9_index = report_text.find(
        section_9_heading
    )

    if (
        section_8_index != -1
        and section_8_index < section_9_index
    ):
        return (
            report_text[:section_8_index]
            + replacement
            + report_text[section_9_index:]
        )

    return (
        report_text[:section_9_index]
        + replacement
        + report_text[section_9_index:]
    )

def main():
    reset_usage()

    args = parse_args()

    provider = set_current_provider(
        args.provider
    )

    provider_name = (
        get_provider_display_name()
    )

    print(
        f"Fantasy provider: "
        f"{provider_name} ({provider})"
    )

    if provider == "sleeper":
        print()
        print(
            "Refreshing live Sleeper data..."
        )

        try:
            sleeper_refresh = (
                refresh_sleeper_acquisition_snapshot()
            )

        except Exception as exc:
            print(
                "SLEEPER REFRESH: FAIL - "
                f"{exc}"
            )
            print(
                "Weekly report cancelled because live "
                "Sleeper acquisition data could not be "
                "refreshed."
            )
            raise SystemExit(1)

        counts = (
            sleeper_refresh.get(
                "availability_counts",
                {},
            )
        )

        print(
            "SLEEPER REFRESH: PASS "
            f"(FA={counts.get('FA', 0)}, "
            f"W={counts.get('W', 0)}, "
            f"LOCKED={counts.get('LOCKED', 0)}, "
            f"UNKNOWN={counts.get('UNKNOWN', 0)})"
        )

        schedule_errors = (
            sleeper_refresh.get(
                "schedule_errors",
                [],
            )
        )

        transaction_errors = (
            sleeper_refresh.get(
                "transaction_errors",
                [],
            )
        )

        if schedule_errors:
            print(
                "SLEEPER REFRESH WARNING: "
                f"schedule errors: {schedule_errors}"
            )

        if transaction_errors:
            print(
                "SLEEPER REFRESH WARNING: "
                f"transaction errors: {transaction_errors}"
            )

    print()
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
            f"{check['name']} - "
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
            f"INJURY RESEARCH: FAIL - "
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
            f"LINEUP VALIDATION: FAIL - "
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
            f"CONTINGENCY VALIDATION: FAIL - "
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

    contingency_file = (
        save_validated_contingencies(
            validated_contingencies
        )
    )

    print(
        f"Validated contingencies saved to "
        f"{contingency_file}."
    )

    print()
    print(
        "Optimizing roster and post-move lineup..."
    )

    try:
        validated_transaction = (
            build_validated_transaction(
                current_lineup=validated_lineup[
                    "plan"
                ][
                    "lineup"
                ],
                injury_snapshot=injury_snapshot,
            )
        )

    except Exception as exc:
        print()
        print(
            f"TRANSACTION VALIDATION: FAIL - "
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
        print(
            "TRANSACTION VALIDATION: BLOCKED "
            f"({validated_transaction.get('blocked_reason', 'unknown')})"
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
        "Evaluating trade opportunities..."
    )

    try:
        validated_trade_plan = (
            build_validated_trade_plan()
        )

    except Exception as exc:
        print()
        print(
            f"TRADE VALIDATION: FAIL - {exc}"
        )
        print(
            "Weekly report cancelled."
        )

        raise SystemExit(1)

    if (
        validated_trade_plan.get(
            "status"
        )
        == "blocked"
    ):
        print(
            "TRADE VALIDATION: BLOCKED "
            f"({validated_trade_plan.get('blocked_reason', 'unknown')})"
        )

    else:
        trade_ideas = (
            validated_trade_plan.get(
                "plan",
                {},
            ).get(
                "ideas",
                [],
            )
        )

        print(
            "TRADE VALIDATION: PASS "
            f"({validated_trade_plan.get('attempts', 0)} "
            f"attempt(s), {len(trade_ideas)} "
            "idea(s))"
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

    trade_context = (
        build_trade_context()
    )

    trade_context_json = json.dumps(
        trade_context,
        indent=2,
)

    report_input = f"""
{WEEKLY_REPORT_PROMPT}

CURRENT FANTASY PROVIDER

Provider: {provider_name}
Provider key: {provider}

Use only data belonging to this provider and its selected league.


AUTHORITATIVE VALIDATED LINEUP

The following starting lineup has already been generated and
independently validated by Python.

This is the authoritative lineup using players CURRENTLY on the
roster.

Use it as the actual executable lineup unless and until a validated
roster move completes.

Do not generate or print another WEEKLY LINEUP section.

The validated lineup may include key_decisions. Those are the
authoritative concise explanations for the important lineup close
calls. Do not contradict or independently rewrite those decisions in
later sections of the report.

Section 5 may contain an independently validated hypothetical
post-transaction optimized lineup. That lineup must remain clearly
conditional until the validated add/drop completes. A waiver player
must never be described as already acquired.

{validated_plan_json}


AUTHORITATIVE INJURY SNAPSHOT

The following injury research has already been researched,
source-validated, and used by the lineup planner.

This is the single authoritative source for injury facts in this
report.

Rules:

- Use provider_status and roster_status exactly as supplied.
- Do not treat provider roster status as an official NFL injury report.
- Use exact_reported_injury exactly as supplied.
- Do not rename, translate, or generalize an injury.
- Do not convert psoas soreness into groin injury.
- Use latest_practice_participation exactly as supplied.
- If participation is "Not specified", do not infer Full or Limited.
- Use official_game_status exactly as supplied.
- If it is "Not yet available", do not invent an official designation.
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

- If transaction_blocked=true, do NOT describe the result as
  "standing pat."
- If transaction_blocked=true, do not claim any specific add/drop is
  executable.
- If transaction_blocked=true, preserve the supplied blocked reason.
- If transaction_blocked=false and recommend_move=false, standing
  pat is the authoritative transaction decision.
- If transaction_blocked=false and recommend_move=true, use the exact
  validated add player and drop player.
- Treat the supplied post-move optimized lineup as authoritative for
  the hypothetical roster after that exact transaction.
- If the add availability is W, every reference to the optimized
  lineup must remain conditional on the waiver claim clearing.
- Preserve the provider's acquisition state exactly.
- Do not translate UNROSTERED into free agent or waiver claim.
- Do not generate a different specific add/drop transaction.
- Use the supplied current-week, next-four-weeks, bye-week, and
  rest-of-season analysis rather than inventing a conflicting
  roster-optimization conclusion.
"""

    agent = build_weekly_agent()

    result = Runner.run_sync(
        agent,
        report_input,
    )

    record_run_usage(
        "Weekly report writer",
        agent.model,
        result,
    )

    contingency_marker = (
        "[[VALIDATED_CONTINGENCIES]]"
    )

    transaction_marker = (
        "[[ROSTER_MOVES_SECTION]]"
    )

    trade_marker = (
        "[[VALIDATED_TRADE_PLAN]]"
    )

    contingency_marker_count = (
        result.final_output.count(
            contingency_marker
        )
    )

    if contingency_marker_count != 1:
        print()
        print(
            "REPORT ASSEMBLY: FAIL - expected exactly one "
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
            "REPORT ASSEMBLY: FAIL - expected exactly one "
            "ROSTER_MOVES_SECTION marker, "
            f"found {transaction_marker_count}."
        )

        raise SystemExit(1)

    report_text = (
        result.final_output
    )

    duplicate_headings = [
        (
            "## 5. ROSTER MOVES\n\n"
            + transaction_marker
        ),
        (
            "## 5. ROSTER OPTIMIZATION\n\n"
            + transaction_marker
        ),
    ]

    for duplicate_heading in duplicate_headings:
        if duplicate_heading in report_text:
            report_text = (
                report_text.replace(
                    duplicate_heading,
                    transaction_marker,
                    1,
                )
            )
            break

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

    trade_section = (
        render_validated_trade_section(
            validated_trade_plan
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


    report_body = (
        insert_validated_trade_section(
            report_text=report_body,
            trade_section=trade_section,
        )
    )


    safety_check = (
        validate_final_report_safety(
            report_text=report_body,
            validated_contingencies=(
                validated_contingencies
            ),
            trade_context=trade_context,
        )
    )



    if not safety_check[
        "is_valid"
    ]:
        print()
        print(
            "REPORT SAFETY: FAIL"
        )

        for error in safety_check[
            "errors"
        ]:
            print(
                f"- {error}"
            )

        raise SystemExit(1)

    print()
    print(
        "REPORT SAFETY: PASS"
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

    usage_summary = (
        print_usage_report()
    )

    usage_file = (
        save_usage_report(
            provider=provider
        )
    )

    print()
    print(
        f"AI usage telemetry saved to "
        f"{usage_file}."
    )


if __name__ == "__main__":
    main()
