SLOT_LABELS = {
    "qb": "QB",
    "rb1": "RB",
    "rb2": "RB",
    "wr1": "WR",
    "wr2": "WR",
    "te": "TE",
    "flex": "FLEX",
    "k": "K",
    "defense": "DEF",
}


def describe_lineup_changes(
    base_lineup,
    contingency_lineup,
):
    changes = []

    for slot, base_player in base_lineup.items():
        contingency_player = contingency_lineup.get(
            slot
        )

        if contingency_player == base_player:
            continue

        changes.append(
            {
                "slot": SLOT_LABELS.get(
                    slot,
                    slot.upper(),
                ),
                "from": base_player,
                "to": contingency_player,
            }
        )

    return changes


def render_validated_contingencies(
    validated_contingencies,
    base_lineup,
    availability_check=None,
):
    lines = []

    availability_check = availability_check or {}

    availability_is_fresh = availability_check.get(
        "is_fresh",
        True,
    )

    snapshot_age_days = availability_check.get(
        "age_days"
    )

    snapshot_last_updated = availability_check.get(
        "last_updated"
    )

    for contingency in validated_contingencies[
        "contingencies"
    ]:
        player = contingency[
            "unavailable_player"
        ]

        yahoo_status = contingency.get(
            "yahoo_status",
            "",
        )

        lines.append(
            f"**{player} — Yahoo {yahoo_status}**"
        )

        if contingency[
            "has_on_roster_contingency"
        ]:
            validated_lineup = contingency[
                "validation"
            ]["contingency_lineup"]

            changes = describe_lineup_changes(
                base_lineup,
                validated_lineup,
            )

            lines.append(
                "- **Validated on-roster contingency:**"
            )

            for change in changes:
                lines.append(
                    f"  - {change['slot']}: "
                    f"{change['from']} → "
                    f"{change['to']}"
                )

            lines.append(
                "- **Python contingency validation:** PASS"
            )

        else:
            lines.append(
                "- **No on-roster contingency exists "
                "at this player's kickoff.**"
            )

            emergency_options = contingency.get(
                "emergency_free_agents",
                [],
            )

            direct_options = [
                option
                for option in emergency_options
                if option.get(
                    "direct_replacement_for_current_slot"
                )
            ]

            if direct_options:
                if availability_is_fresh:
                    lines.append(
                        "- **Confirmed emergency free-agent options:**"
                    )

                    for option in direct_options:
                        lines.append(
                            f"  - {option['name']} — "
                            f"{option['position']}, "
                            f"{option['nfl_team']} vs. "
                            f"{option['opponent']}"
                        )

                else:
                    lines.append(
                        "- **Emergency candidates from the "
                        "last Yahoo snapshot:**"
                    )

                    for option in direct_options:
                        lines.append(
                            f"  - {option['name']} — "
                            f"{option['position']}, "
                            f"{option['nfl_team']} vs. "
                            f"{option['opponent']}"
                        )

                    lines.append(
                        "- **Availability not confirmed:** "
                        "Refresh Yahoo before relying on "
                        "or adding any candidate above."
                    )

                    if snapshot_age_days is not None:
                        lines.append(
                            f"- Snapshot age: "
                            f"{snapshot_age_days} day(s)."
                        )

                    if snapshot_last_updated:
                        lines.append(
                            f"- Snapshot last updated: "
                            f"{snapshot_last_updated}."
                        )

            else:
                lines.append(
                    "- **Emergency free-agent options:** "
                    "None identified in the available-player snapshot."
                )

        lines.append("")

    return "\n".join(lines).rstrip()