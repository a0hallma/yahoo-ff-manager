def render_validated_trade_section(
    validated,
):
    """
    Render deterministic concrete trade proposals.

    The report writer must not independently change targets, offer
    assets, ownership, or quantitative trade measurements.
    """

    if not validated:
        return (
            "**Trade analysis unavailable.**\n\n"
            "No validated trade-plan data was supplied."
        )

    status = validated.get(
        "status"
    )

    if status == "blocked":
        reason = (
            validated.get(
                "reason"
            )
            or validated.get(
                "blocked_reason"
            )
            or "Trade analysis is unavailable."
        )

        return (
            "**STATUS: BLOCKED**\n\n"
            f"{reason}"
        )

    if status != "pass":
        return (
            "**Trade analysis unavailable.**\n\n"
            "The trade planner did not return a "
            "validated result."
        )

    plan = (
        validated.get(
            "plan"
        )
        or {}
    )

    validation = (
        validated.get(
            "validation"
        )
        or {}
    )

    summary = (
        plan.get(
            "summary"
        )
        or ""
    )

    ideas = (
        plan.get(
            "ideas"
        )
        or []
    )

    teams_evaluated = (
        plan.get(
            "teams_evaluated"
        )
        or []
    )

    measurements = {
        (
            item.get(
                "target_team"
            ),
            item.get(
                "target_player"
            ),
        ): item
        for item in validation.get(
            "idea_measurements",
            [],
        )
    }

    lines = []

    if summary:
        lines.append(
            summary
        )
        lines.append(
            ""
        )

    if teams_evaluated:
        lines.append(
            f"**Opponents evaluated:** "
            f"{len(teams_evaluated)}"
        )
        lines.append(
            ""
        )

    if not ideas:
        lines.append(
            "No validated concrete trade proposal survived "
            "the roster-fit and quantitative value checks."
        )
        lines.append(
            ""
        )
        lines.append(
            "**Python trade validation:** PASS"
        )

        return "\n".join(
            lines
        )

    lines.append(
        "**Validated concrete trade proposals:**"
    )
    lines.append(
        ""
    )

    for index, idea in enumerate(
        ideas,
        start=1,
    ):
        target_player = (
            idea.get(
                "target_player",
                "Unknown player",
            )
        )

        target_team = (
            idea.get(
                "target_team",
                "Unknown team",
            )
        )

        target_position = (
            idea.get(
                "target_position",
                "Unknown",
            )
        )

        offer_players = (
            idea.get(
                "offer_players",
                [],
            )
        )

        measurement = (
            measurements.get(
                (
                    target_team,
                    target_player,
                ),
                {},
            )
        )

        lines.append(
            f"### {index}. Acquire {target_player}"
        )

        lines.append(
            f"- **From:** {target_team}"
        )

        if offer_players:
            offer_text = " + ".join(
                (
                    f"{asset.get('player_name')} "
                    f"({asset.get('position')})"
                )
                for asset in offer_players
            )

            lines.append(
                f"- **Offer:** {offer_text}"
            )

        lines.append(
            f"- **Target position:** {target_position}"
        )

        lines.append(
            f"- **Attainability:** "
            f"{idea.get('attainability', 'unknown')}"
        )

        lines.append(
            f"- **Partner replacement risk:** "
            f"{idea.get('replacement_risk', 'unknown')}"
        )

        lines.append(
            ""
        )

        lines.append(
            "**Quantitative trade check:**"
        )

        valuation_method = (
            measurement.get(
                "valuation_method"
            )
            or idea.get(
                "valuation_method"
            )
        )

        readable_method = {
            "published_trade_value": (
                "Published trade-value chart"
            ),
            "ros_rank_index": (
                "Overall ROS rank -> GM Trade Index"
            ),
        }.get(
            valuation_method,
            valuation_method,
        )

        lines.append(
            f"- **Method:** {readable_method}"
        )

        lines.append(
            f"- **Source:** "
            f"{idea.get('valuation_source', 'Unknown')}"
        )

        lines.append(
            f"- **Source date:** "
            f"{idea.get('valuation_date', 'Unknown')}"
        )

        lines.append(
            f"- **Format:** "
            f"{idea.get('valuation_format', 'Unknown')}"
        )

        source_url = (
            idea.get(
                "valuation_source_url"
            )
        )

        if source_url:
            lines.append(
                f"- **Source URL:** {source_url}"
            )

        target_measurement = (
            measurement.get(
                "target_measurement_value"
            )
        )

        if (
            valuation_method
            == "published_trade_value"
        ):
            lines.append(
                f"- **{target_player} published value:** "
                f"{measurement.get('target_source_trade_value')}"
            )

        elif (
            valuation_method
            == "ros_rank_index"
        ):
            lines.append(
                f"- **{target_player} overall ROS rank:** "
                f"{measurement.get('target_source_ros_rank')}"
            )

            lines.append(
                f"- **{target_player} GM Trade Index:** "
                f"{target_measurement}"
            )

        for asset in measurement.get(
            "offer_assets",
            [],
        ):
            if (
                valuation_method
                == "published_trade_value"
            ):
                lines.append(
                    (
                        f"- **{asset.get('player_name')} "
                        f"published value:** "
                        f"{asset.get('source_trade_value')}"
                    )
                )

            else:
                lines.append(
                    (
                        f"- **{asset.get('player_name')} "
                        f"overall ROS rank:** "
                        f"{asset.get('source_ros_rank')}"
                    )
                )

                lines.append(
                    (
                        f"- **{asset.get('player_name')} "
                        f"GM Trade Index:** "
                        f"{asset.get('measurement_value')}"
                    )
                )

        raw_offer = (
            measurement.get(
                "raw_offer_value"
            )
        )

        adjusted_offer = (
            measurement.get(
                "package_adjusted_offer_value"
            )
        )

        if raw_offer is not None:
            lines.append(
                f"- **Raw offer measurement:** "
                f"{raw_offer}"
            )

        if adjusted_offer is not None:
            lines.append(
                f"- **Package-adjusted offer measurement:** "
                f"{adjusted_offer}"
            )

        second_weight = (
            measurement.get(
                "second_asset_weight"
            )
        )

        if second_weight is not None:
            lines.append(
                (
                    f"- **2-for-1 consolidation adjustment:** "
                    f"second asset counted at "
                    f"{second_weight * 100:.0f}%"
                )
            )

        ratio = (
            measurement.get(
                "offer_to_target_ratio"
            )
        )

        if ratio is not None:
            lines.append(
                (
                    f"- **Adjusted offer / target:** "
                    f"{ratio * 100:.1f}%"
                )
            )

        delta = (
            measurement.get(
                "value_delta"
            )
        )

        delta_pct = (
            measurement.get(
                "value_delta_pct"
            )
        )

        if (
            delta is not None
            and delta_pct is not None
        ):
            lines.append(
                (
                    f"- **Adjusted value delta:** "
                    f"{delta:+.2f} "
                    f"({delta_pct:+.1f}%)"
                )
            )

        band = (
            measurement.get(
                "value_band"
            )
        )

        if band:
            lines.append(
                (
                    f"- **Value band:** "
                    f"{band.replace('_', ' ')}"
                )
            )

        negotiation_tier = (
            measurement.get(
                "negotiation_tier"
            )
        )

        if negotiation_tier:
            lines.append(
                (
                    f"- **Python offer guidance:** "
                    f"{negotiation_tier}"
                )
            )

        if measurement.get(
            "do_not_increase_offer",
            False,
        ):
            lines.append(
                "- **Ceiling:** Do not increase this offer."
            )

        lines.append(
            ""
        )

        if idea.get(
            "upgrade_path"
        ):
            lines.append(
                "**Why I want the target:**"
            )
            lines.append(
                idea[
                    "upgrade_path"
                ]
            )
            lines.append(
                ""
            )

        if idea.get(
            "partner_fit"
        ):
            lines.append(
                "**Why the other manager may consider it:**"
            )
            lines.append(
                idea[
                    "partner_fit"
                ]
            )
            lines.append(
                ""
            )

        if idea.get(
            "offer_rationale"
        ):
            lines.append(
                "**Why this package:**"
            )
            lines.append(
                idea[
                    "offer_rationale"
                ]
            )
            lines.append(
                ""
            )

        if idea.get(
            "my_roster_impact"
        ):
            lines.append(
                "**Impact on my roster:**"
            )
            lines.append(
                idea[
                    "my_roster_impact"
                ]
            )
            lines.append(
                ""
            )

        if idea.get(
            "negotiation_note"
        ):
            lines.append(
                "**Qualitative negotiation approach:**"
            )
            lines.append(
                idea[
                    "negotiation_note"
                ]
            )
            lines.append(
                ""
            )

        if idea.get(
            "value_note"
        ):
            lines.append(
                "**Value context:**"
            )
            lines.append(
                idea[
                    "value_note"
                ]
            )
            lines.append(
                ""
            )

        lines.append(
            f"**Confidence:** "
            f"{idea.get('confidence', 'unknown')}"
        )

        lines.append(
            ""
        )

    lines.append(
        "**Python trade validation:** PASS"
    )

    lines.append(
        ""
    )

    lines.append(
        (
            "The quantitative score is a market-reference check, "
            "not a prediction that the other manager will accept."
        )
    )

    return "\n".join(
        lines
    )
