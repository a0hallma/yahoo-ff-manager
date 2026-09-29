from schedule_tools import (
    fetch_nflverse_schedule,
    fetch_espn_schedule,
)


def fetch_week_schedule(
    season,
    week,
):
    """
    Fetch a specific NFL week for Sleeper acquisition-state
    calculations.

    Primary:
      nflverse structured schedule data.

    Secondary:
      ESPN structured scoreboard data.

    This intentionally does not depend on the currently
    selected fantasy provider because Sleeper needs both the
    current and previous NFL weeks when determining waiver
    and free-agent state.
    """

    errors = []

    try:
        return fetch_nflverse_schedule(
            int(season),
            int(week),
        )

    except Exception as exc:
        errors.append(
            f"nflverse: {exc}"
        )

    try:
        return fetch_espn_schedule(
            int(season),
            int(week),
        )

    except Exception as exc:
        errors.append(
            f"ESPN: {exc}"
        )

    raise RuntimeError(
        (
            f"Unable to retrieve NFL schedule for "
            f"{season} Week {week}: "
            + " | ".join(errors)
        )
    )
