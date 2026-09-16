from provider_context import (
    get_provider_display_name,
)


def render_validated_trade_section(
    validated,
):
    """
    Render deterministic trade analysis from the
    validated trade planner output.

    The weekly report writer should not independently
    create or modify trade targets.
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

    lines = []

    if summary:
        lines.append(
            summary
        )
        lines.append(
            ""
        )

    if not ideas:
        lines.append(
            "No validated trade targets were identified "
            "for this week."
        )

        return "\n".join(
            lines
        )

    lines.append(
        "**Validated exploratory targets:**"
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

        upgrade_path = (
            idea.get(
                "upgrade_path",
                ""
            )
        )

        partner_fit = (
            idea.get(
                "partner_fit",
                ""
            )
        )

        value_note = (
            idea.get(
                "value_note",
                ""
            )
        )

        confidence = (
            idea.get(
                "confidence",
                "unknown",
            )
        )

        lines.append(
            f"### {index}. {target_player}"
        )

        lines.append(
            f"- **Fantasy team:** {target_team}"
        )

        lines.append(
            f"- **Position:** {target_position}"
        )

        if upgrade_path:
            lines.append(
                f"- **Why target them:** {upgrade_path}"
            )

        if partner_fit:
            lines.append(
                f"- **Why the partner may fit:** "
                f"{partner_fit}"
            )

        if value_note:
            lines.append(
                f"- **Value context:** {value_note}"
            )

        lines.append(
            f"- **Confidence:** {confidence}"
        )

        lines.append(
            ""
        )

    lines.append(
        "These are exploratory trade targets, not "
        "validated or executable trade offers."
    )

    return "\n".join(
        lines
    )