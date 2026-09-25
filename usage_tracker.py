"""
Central AI usage and estimated-cost telemetry for Fantasy GM.

Pricing snapshot: 2026-09-23.

The OpenAI Agents SDK reports token usage for each Runner execution.
This module aggregates those runs, estimates model-token cost, detects
billable hosted web-search actions, prints a readable report, and can
save the raw telemetry to artifacts/.

The estimate is intended for personal cost management. OpenAI billing
is authoritative if pricing or billing behavior changes.
"""

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime
import json
from pathlib import Path
from typing import Any


PRICING_SNAPSHOT_DATE = "2026-09-23"

# USD per 1M tokens.
MODEL_PRICING = {
    "gpt-5.6-luna": {
        "input": 0.20,
        "cached_input": 0.02,
        "cache_write": 0.25,
        "output": 1.20,
    },
    "gpt-5.6-terra": {
        "input": 2.00,
        "cached_input": 0.20,
        "cache_write": 2.50,
        "output": 12.00,
    },
    "gpt-5.6-sol": {
        "input": 4.00,
        "cached_input": 0.40,
        "cache_write": 5.00,
        "output": 20.00,
    },
}

# GPT-5.6 requests above 272K input tokens use long-context pricing:
# 2x input-family rates and 1.5x output.
LONG_CONTEXT_INPUT_THRESHOLD = 272_000
LONG_CONTEXT_INPUT_MULTIPLIER = 2.0
LONG_CONTEXT_OUTPUT_MULTIPLIER = 1.5

# Hosted web search currently costs $10 / 1,000 search calls.
WEB_SEARCH_COST_PER_CALL = 0.01

# Current production model routing we want to compare against the
# Luna baseline.
PROPOSED_MIXED_ROUTING = {
    "Starting lineup": "gpt-5.6-terra",
    "Trade planner": "gpt-5.6-sol",
}

_records: list[dict[str, Any]] = []


def _field(
    value,
    name,
    default=None,
):
    if value is None:
        return default

    if isinstance(
        value,
        dict,
    ):
        return value.get(
            name,
            default,
        )

    return getattr(
        value,
        name,
        default,
    )


def _int_value(
    value,
):
    try:
        return int(
            value
            or 0
        )

    except (
        TypeError,
        ValueError,
    ):
        return 0


def normalize_model_name(
    model,
):
    """
    Normalize exact/versioned GPT-5.6 model IDs to the pricing key.
    """

    model_name = str(
        model
        or ""
    ).strip().lower()

    if model_name == "gpt-5.6":
        return "gpt-5.6-sol"

    for known_model in MODEL_PRICING:
        if model_name.startswith(
            known_model
        ):
            return known_model

    return model_name


def _usage_entry_to_dict(
    entry,
):
    input_details = _field(
        entry,
        "input_tokens_details",
    )

    output_details = _field(
        entry,
        "output_tokens_details",
    )

    input_tokens = _int_value(
        _field(
            entry,
            "input_tokens",
            0,
        )
    )

    cached_tokens = _int_value(
        _field(
            input_details,
            "cached_tokens",
            0,
        )
    )

    cache_write_tokens = _int_value(
        _field(
            input_details,
            "cache_write_tokens",
            0,
        )
    )

    # Be conservative if a provider reports detail counters that do
    # not reconcile perfectly with the aggregate input count.
    uncached_input_tokens = max(
        0,
        input_tokens
        - cached_tokens
        - cache_write_tokens,
    )

    output_tokens = _int_value(
        _field(
            entry,
            "output_tokens",
            0,
        )
    )

    reasoning_tokens = _int_value(
        _field(
            output_details,
            "reasoning_tokens",
            0,
        )
    )

    return {
        "input_tokens": input_tokens,
        "uncached_input_tokens": (
            uncached_input_tokens
        ),
        "cached_tokens": cached_tokens,
        "cache_write_tokens": (
            cache_write_tokens
        ),
        "output_tokens": output_tokens,
        "reasoning_tokens": (
            reasoning_tokens
        ),
    }


def _extract_request_usage(
    usage,
):
    entries = list(
        _field(
            usage,
            "request_usage_entries",
            [],
        )
        or []
    )

    if entries:
        return [
            _usage_entry_to_dict(
                entry
            )
            for entry in entries
        ]

    # Backward-compatible fallback if a future/older SDK gives us
    # aggregate usage but no per-request entries.
    return [
        _usage_entry_to_dict(
            usage
        )
    ]


def _raw_type(
    raw,
):
    return _field(
        raw,
        "type",
        "",
    )


def _web_action_type(
    raw,
):
    action = _field(
        raw,
        "action",
    )

    return str(
        _field(
            action,
            "type",
            "",
        )
        or ""
    ).lower()


def count_web_search_calls(
    result,
):
    """
    Count billable web-search `search` actions.

    The same hosted-tool item can appear in more than one SDK result
    surface, so explicit item IDs are deduplicated.
    """

    discovered: dict[
        str,
        tuple[str, str],
    ] = {}

    synthetic_counter = 0

    def inspect_raw(
        raw,
    ):
        nonlocal synthetic_counter

        if (
            str(
                _raw_type(
                    raw
                )
            ).lower()
            != "web_search_call"
        ):
            return

        action_type = (
            _web_action_type(
                raw
            )
        )

        # Open-page/find-in-page actions are not counted as new search
        # actions here. An empty action type is counted conservatively
        # because older SDK snapshots may not expose the nested action.
        if action_type not in {
            "",
            "search",
        }:
            return

        raw_id = (
            _field(
                raw,
                "id",
            )
            or _field(
                raw,
                "call_id",
            )
        )

        if raw_id:
            key = str(
                raw_id
            )

        else:
            synthetic_counter += 1
            key = (
                f"synthetic:"
                f"{synthetic_counter}"
            )

        discovered[
            key
        ] = (
            "web_search_call",
            action_type,
        )

    for item in (
        getattr(
            result,
            "new_items",
            [],
        )
        or []
    ):
        inspect_raw(
            getattr(
                item,
                "raw_item",
                None,
            )
        )

    for response in (
        getattr(
            result,
            "raw_responses",
            [],
        )
        or []
    ):
        for raw in (
            getattr(
                response,
                "output",
                [],
            )
            or []
        ):
            inspect_raw(
                raw
            )

    return len(
        discovered
    )


def estimate_request_cost(
    model,
    request_usage,
):
    normalized_model = (
        normalize_model_name(
            model
        )
    )

    pricing = MODEL_PRICING.get(
        normalized_model
    )

    if not pricing:
        return None

    input_tokens = (
        request_usage[
            "input_tokens"
        ]
    )

    long_context = (
        input_tokens
        > LONG_CONTEXT_INPUT_THRESHOLD
    )

    input_multiplier = (
        LONG_CONTEXT_INPUT_MULTIPLIER
        if long_context
        else 1.0
    )

    output_multiplier = (
        LONG_CONTEXT_OUTPUT_MULTIPLIER
        if long_context
        else 1.0
    )

    cost = (
        request_usage[
            "uncached_input_tokens"
        ]
        * pricing[
            "input"
        ]
        * input_multiplier
        + request_usage[
            "cached_tokens"
        ]
        * pricing[
            "cached_input"
        ]
        * input_multiplier
        + request_usage[
            "cache_write_tokens"
        ]
        * pricing[
            "cache_write"
        ]
        * input_multiplier
        + request_usage[
            "output_tokens"
        ]
        * pricing[
            "output"
        ]
        * output_multiplier
    ) / 1_000_000

    return cost


def estimate_record_cost(
    record,
    model_override=None,
):
    model = (
        model_override
        or record[
            "model"
        ]
    )

    request_costs = [
        estimate_request_cost(
            model,
            request_usage,
        )
        for request_usage
        in record[
            "request_usage"
        ]
    ]

    if any(
        cost is None
        for cost in request_costs
    ):
        model_cost = None

    else:
        model_cost = sum(
            request_costs
        )

    web_search_cost = (
        record[
            "web_search_calls"
        ]
        * WEB_SEARCH_COST_PER_CALL
    )

    if model_cost is None:
        total_cost = None

    else:
        total_cost = (
            model_cost
            + web_search_cost
        )

    return {
        "model_cost": model_cost,
        "web_search_cost": (
            web_search_cost
        ),
        "total_cost": total_cost,
    }


def record_run_usage(
    stage,
    model,
    result,
):
    """
    Record one completed Runner execution.

    Retries are intentionally recorded separately and later aggregated
    by stage so failed model attempts remain part of the true cost.
    """

    usage = (
        result
        .context_wrapper
        .usage
    )

    request_usage = (
        _extract_request_usage(
            usage
        )
    )

    record = {
        "recorded_at": (
            datetime.now()
            .astimezone()
            .isoformat()
        ),
        "stage": str(
            stage
        ),
        "model": (
            normalize_model_name(
                model
            )
        ),
        "requests": _int_value(
            _field(
                usage,
                "requests",
                len(
                    request_usage
                ),
            )
        ),
        "input_tokens": _int_value(
            _field(
                usage,
                "input_tokens",
                sum(
                    item[
                        "input_tokens"
                    ]
                    for item
                    in request_usage
                ),
            )
        ),
        "cached_tokens": sum(
            item[
                "cached_tokens"
            ]
            for item
            in request_usage
        ),
        "cache_write_tokens": sum(
            item[
                "cache_write_tokens"
            ]
            for item
            in request_usage
        ),
        "output_tokens": _int_value(
            _field(
                usage,
                "output_tokens",
                sum(
                    item[
                        "output_tokens"
                    ]
                    for item
                    in request_usage
                ),
            )
        ),
        "reasoning_tokens": sum(
            item[
                "reasoning_tokens"
            ]
            for item
            in request_usage
        ),
        "web_search_calls": (
            count_web_search_calls(
                result
            )
        ),
        "request_usage": (
            request_usage
        ),
    }

    record.update(
        estimate_record_cost(
            record
        )
    )

    _records.append(
        record
    )

    return record


def reset_usage():
    _records.clear()


def get_usage_records():
    return [
        dict(
            record
        )
        for record in _records
    ]


def _aggregate_records():
    grouped = OrderedDict()

    for record in _records:
        key = (
            record[
                "stage"
            ],
            record[
                "model"
            ],
        )

        if key not in grouped:
            grouped[
                key
            ] = {
                "stage": (
                    record[
                        "stage"
                    ]
                ),
                "model": (
                    record[
                        "model"
                    ]
                ),
                "runner_executions": 0,
                "requests": 0,
                "input_tokens": 0,
                "cached_tokens": 0,
                "cache_write_tokens": 0,
                "output_tokens": 0,
                "reasoning_tokens": 0,
                "web_search_calls": 0,
                "model_cost": 0.0,
                "web_search_cost": 0.0,
                "total_cost": 0.0,
                "cost_available": True,
            }

        target = grouped[
            key
        ]

        target[
            "runner_executions"
        ] += 1

        for field in (
            "requests",
            "input_tokens",
            "cached_tokens",
            "cache_write_tokens",
            "output_tokens",
            "reasoning_tokens",
            "web_search_calls",
        ):
            target[
                field
            ] += record[
                field
            ]

        for field in (
            "model_cost",
            "web_search_cost",
            "total_cost",
        ):
            if (
                record[
                    field
                ]
                is None
            ):
                target[
                    "cost_available"
                ] = False

            else:
                target[
                    field
                ] += record[
                    field
                ]

    return list(
        grouped.values()
    )


def _scenario_cost(
    routing,
):
    total = 0.0

    for record in _records:
        override = routing.get(
            record[
                "stage"
            ],
            record[
                "model"
            ],
        )

        estimate = (
            estimate_record_cost(
                record,
                model_override=override,
            )
        )

        if (
            estimate[
                "total_cost"
            ]
            is None
        ):
            return None

        total += (
            estimate[
                "total_cost"
            ]
        )

    return total


def _all_model_scenario(
    model,
):
    routing = {
        record[
            "stage"
        ]: model
        for record in _records
    }

    return _scenario_cost(
        routing
    )


def build_usage_summary():
    stage_summary = (
        _aggregate_records()
    )

    total_requests = sum(
        row[
            "requests"
        ]
        for row in stage_summary
    )

    total_input = sum(
        row[
            "input_tokens"
        ]
        for row in stage_summary
    )

    total_cached = sum(
        row[
            "cached_tokens"
        ]
        for row in stage_summary
    )

    total_cache_write = sum(
        row[
            "cache_write_tokens"
        ]
        for row in stage_summary
    )

    total_output = sum(
        row[
            "output_tokens"
        ]
        for row in stage_summary
    )

    total_reasoning = sum(
        row[
            "reasoning_tokens"
        ]
        for row in stage_summary
    )

    total_web_searches = sum(
        row[
            "web_search_calls"
        ]
        for row in stage_summary
    )

    if all(
        row[
            "cost_available"
        ]
        for row in stage_summary
    ):
        actual_cost = sum(
            row[
                "total_cost"
            ]
            for row in stage_summary
        )

    else:
        actual_cost = None

    scenarios = {
        "all_luna_same_usage": (
            _all_model_scenario(
                "gpt-5.6-luna"
            )
        ),
        "all_terra_same_usage": (
            _all_model_scenario(
                "gpt-5.6-terra"
            )
        ),
        "all_sol_same_usage": (
            _all_model_scenario(
                "gpt-5.6-sol"
            )
        ),
        "proposed_mixed_same_usage": (
            _scenario_cost(
                PROPOSED_MIXED_ROUTING
            )
        ),
    }

    return {
        "pricing_snapshot_date": (
            PRICING_SNAPSHOT_DATE
        ),
        "generated_at": (
            datetime.now()
            .astimezone()
            .isoformat()
        ),
        "stages": stage_summary,
        "totals": {
            "runner_executions": len(
                _records
            ),
            "requests": (
                total_requests
            ),
            "input_tokens": (
                total_input
            ),
            "cached_tokens": (
                total_cached
            ),
            "cache_write_tokens": (
                total_cache_write
            ),
            "output_tokens": (
                total_output
            ),
            "reasoning_tokens": (
                total_reasoning
            ),
            "web_search_calls": (
                total_web_searches
            ),
            "estimated_actual_cost": (
                actual_cost
            ),
        },
        "same_usage_hypotheticals": (
            scenarios
        ),
        "raw_records": (
            get_usage_records()
        ),
    }


def _format_money(
    value,
):
    if value is None:
        return "unavailable"

    return f"${value:.4f}"


def print_usage_report():
    summary = (
        build_usage_summary()
    )

    print()
    print(
        "AI USAGE / ESTIMATED API COST"
    )
    print(
        "=" * 31
    )
    print(
        f"Pricing snapshot: "
        f"{PRICING_SNAPSHOT_DATE}"
    )

    stages = summary[
        "stages"
    ]

    if not stages:
        print(
            "No AI usage was recorded."
        )

        return summary

    for row in stages:
        print()
        print(
            f"{row['stage']} — "
            f"{row['model']}"
        )

        print(
            f"  Runner executions: "
            f"{row['runner_executions']}"
        )

        print(
            f"  API requests: "
            f"{row['requests']}"
        )

        print(
            f"  Input tokens: "
            f"{row['input_tokens']:,}"
        )

        print(
            f"  Cached input: "
            f"{row['cached_tokens']:,}"
        )

        print(
            f"  Cache-write input: "
            f"{row['cache_write_tokens']:,}"
        )

        print(
            f"  Output tokens: "
            f"{row['output_tokens']:,}"
        )

        print(
            f"  Reasoning tokens "
            f"(included in output): "
            f"{row['reasoning_tokens']:,}"
        )

        print(
            f"  Web searches detected: "
            f"{row['web_search_calls']}"
        )

        print(
            f"  Estimated cost: "
            f"{_format_money(row['total_cost'])}"
        )

    totals = summary[
        "totals"
    ]

    print()
    print(
        "TOTAL"
    )

    print(
        f"  Runner executions: "
        f"{totals['runner_executions']}"
    )

    print(
        f"  API requests: "
        f"{totals['requests']}"
    )

    print(
        f"  Input tokens: "
        f"{totals['input_tokens']:,}"
    )

    print(
        f"  Cached input: "
        f"{totals['cached_tokens']:,}"
    )

    print(
        f"  Cache-write input: "
        f"{totals['cache_write_tokens']:,}"
    )

    print(
        f"  Output tokens: "
        f"{totals['output_tokens']:,}"
    )

    print(
        f"  Reasoning tokens "
        f"(included in output): "
        f"{totals['reasoning_tokens']:,}"
    )

    print(
        f"  Web searches detected: "
        f"{totals['web_search_calls']}"
    )

    print(
        f"  Estimated actual API cost: "
        f"{_format_money(totals['estimated_actual_cost'])}"
    )

    scenarios = summary[
        "same_usage_hypotheticals"
    ]

    print()
    print(
        "SAME OBSERVED USAGE — MODEL COMPARISON"
    )

    print(
        "  These are what-if estimates using the exact "
        "token/search volume from this run."
    )

    print(
        "  Actual usage may change when a different model "
        "makes different tool/retry decisions."
    )

    print(
        f"  All Luna: "
        f"{_format_money(scenarios['all_luna_same_usage'])}"
    )

    print(
        f"  All Terra: "
        f"{_format_money(scenarios['all_terra_same_usage'])}"
    )

    print(
        f"  All Sol: "
        f"{_format_money(scenarios['all_sol_same_usage'])}"
    )

    print(
        "  Proposed mix "
        "(lineup=Terra, trade=Sol, rest=Luna): "
        f"{_format_money(scenarios['proposed_mixed_same_usage'])}"
    )

    return summary


def save_usage_report(
    provider=None,
):
    summary = (
        build_usage_summary()
    )

    output_dir = Path(
        "artifacts"
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    timestamp = (
        datetime.now()
        .astimezone()
        .strftime(
            "%Y%m%d_%H%M%S"
        )
    )

    provider_part = (
        f"_{provider}"
        if provider
        else ""
    )

    output_file = (
        output_dir
        / (
            "ai_usage"
            f"{provider_part}"
            f"_{timestamp}.json"
        )
    )

    with output_file.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            summary,
            file,
            indent=2,
        )

    return output_file
