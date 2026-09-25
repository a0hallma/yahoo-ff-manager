from datetime import datetime

from lineup_tools import check_lineup
from schedule_tools import build_roster_schedule


LINEUP_KEYS = [
    "qb",
    "rb1",
    "rb2",
    "wr1",
    "wr2",
    "te",
    "flex",
    "k",
    "defense",
]


def normalize_name(name):
    return name.strip().lower()


def validate_contingency(
    unavailable_player,
    base_lineup,
    contingency_lineup,
):
    errors = []
    warnings = []

    # ---------------------------------------------------------
    # 1. Make sure both lineup dictionaries are complete
    # ---------------------------------------------------------

    for label, lineup in [
        ("base lineup", base_lineup),
        ("contingency lineup", contingency_lineup),
    ]:
        missing = [
            key
            for key in LINEUP_KEYS
            if key not in lineup
        ]

        if missing:
            errors.append(
                f"{label} is missing slots: "
                + ", ".join(missing)
            )

    if errors:
        return {
            "is_valid": False,
            "errors": errors,
            "warnings": warnings,
        }

    # ---------------------------------------------------------
    # 2. Validate the proposed backup lineup normally
    # ---------------------------------------------------------

    legality = check_lineup(
        qb=contingency_lineup["qb"],
        rb1=contingency_lineup["rb1"],
        rb2=contingency_lineup["rb2"],
        wr1=contingency_lineup["wr1"],
        wr2=contingency_lineup["wr2"],
        te=contingency_lineup["te"],
        flex=contingency_lineup["flex"],
        k=contingency_lineup["k"],
        defense=contingency_lineup["defense"],
    )

    if not legality["is_legal"]:
        errors.extend(legality["errors"])

    # ---------------------------------------------------------
    # 3. Confirm unavailable player was actually starting
    # ---------------------------------------------------------

    unavailable_key = normalize_name(
        unavailable_player
    )

    base_slot = None

    for slot, player_name in base_lineup.items():
        if normalize_name(player_name) == unavailable_key:
            base_slot = slot
            break

    if not base_slot:
        errors.append(
            f"{unavailable_player} is not in the base starting lineup."
        )

        return {
            "is_valid": False,
            "errors": errors,
            "warnings": warnings,
        }

    # ---------------------------------------------------------
    # 4. Unavailable player cannot remain in contingency
    # ---------------------------------------------------------

    contingency_names = [
        normalize_name(name)
        for name in contingency_lineup.values()
    ]

    if unavailable_key in contingency_names:
        errors.append(
            f"{unavailable_player} is unavailable but remains "
            "in the contingency lineup."
        )

    # ---------------------------------------------------------
    # 5. Determine decision time from NFL schedule
    # ---------------------------------------------------------

    roster_schedule = build_roster_schedule()

    schedule_by_name = {
        normalize_name(player["name"]): player
        for player in roster_schedule["players"]
    }

    unavailable_schedule = schedule_by_name.get(
        unavailable_key
    )

    if (
        not unavailable_schedule
        or not unavailable_schedule.get("kickoff")
    ):
        errors.append(
            f"No kickoff was found for {unavailable_player}."
        )

        return {
            "is_valid": False,
            "errors": errors,
            "warnings": warnings,
        }

    decision_time = datetime.fromisoformat(
        unavailable_schedule["kickoff"]
    )

    # ---------------------------------------------------------
    # 6. Players already locked must stay in their exact slots
    # ---------------------------------------------------------

    for slot, player_name in base_lineup.items():
        player_key = normalize_name(player_name)

        if player_key == unavailable_key:
            continue

        player_schedule = schedule_by_name.get(
            player_key
        )

        if (
            not player_schedule
            or not player_schedule.get("kickoff")
        ):
            continue

        kickoff = datetime.fromisoformat(
            player_schedule["kickoff"]
        )

        if kickoff < decision_time:
            contingency_player = contingency_lineup.get(
                slot
            )

            if (
                normalize_name(contingency_player)
                != player_key
            ):
                errors.append(
                    f"{player_name} is already locked in "
                    f"{slot.upper()} and cannot be moved."
                )

    # ---------------------------------------------------------
    # 7. Newly inserted starters must still be unlocked
    # ---------------------------------------------------------

    base_names = {
        normalize_name(name)
        for name in base_lineup.values()
    }

    for slot, player_name in contingency_lineup.items():
        player_key = normalize_name(player_name)

        if player_key in base_names:
            continue

        player_schedule = schedule_by_name.get(
            player_key
        )

        if (
            not player_schedule
            or not player_schedule.get("kickoff")
        ):
            errors.append(
                f"No kickoff was found for replacement "
                f"{player_name}."
            )
            continue

        kickoff = datetime.fromisoformat(
            player_schedule["kickoff"]
        )

        if kickoff < decision_time:
            errors.append(
                f"{player_name} already locked before the "
                f"{unavailable_player} decision time."
            )

    return {
        "is_valid": len(errors) == 0,
        "unavailable_player": unavailable_player,
        "original_slot": base_slot,
        "decision_time": decision_time.isoformat(),
        "errors": errors,
        "warnings": warnings,
        "contingency_lineup": contingency_lineup,
    }