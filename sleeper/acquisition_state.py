from datetime import (
    datetime,
    timedelta,
    time,
    timezone,
)
from zoneinfo import ZoneInfo


UTC = timezone.utc
PACIFIC = ZoneInfo("America/Los_Angeles")


# Sleeper's waiver_day_of_week values behave like the
# JavaScript weekday convention:
#
# 0 = Sunday
# 1 = Monday
# 2 = Tuesday
# 3 = Wednesday
# 4 = Thursday
# 5 = Friday
# 6 = Saturday
#
# Python uses Monday=0 ... Sunday=6, so normalize here.
SLEEPER_WEEKDAY_TO_PYTHON = {
    0: 6,
    1: 0,
    2: 1,
    3: 2,
    4: 3,
    5: 4,
    6: 5,
}


def ensure_aware(value):
    if value is None:
        return None

    if value.tzinfo is None:
        return value.replace(
            tzinfo=UTC
        )

    return value


def epoch_ms_to_datetime(value):
    if value is None:
        return None

    return datetime.fromtimestamp(
        value / 1000,
        tz=UTC,
    )


def parse_kickoff(value):
    if value is None:
        return None

    if isinstance(
        value,
        datetime,
    ):
        return ensure_aware(
            value
        )

    return datetime.fromisoformat(
        value
    )


def build_team_kickoffs(games):
    """
    Convert normalized NFL schedule games into:

        {
            "BUF": kickoff_datetime,
            "DET": kickoff_datetime,
            ...
        }
    """

    result = {}

    for game in games or []:
        kickoff = parse_kickoff(
            game.get(
                "kickoff"
            )
        )

        if kickoff is None:
            continue

        away = game.get(
            "away"
        )

        home = game.get(
            "home"
        )

        if away:
            result[
                away
            ] = kickoff

        if home:
            result[
                home
            ] = kickoff

    return result


def next_weekly_clear_after(
    reference_time,
    waiver_day_of_week,
):
    """
    Calculate the Sleeper after-game waiver clearance
    following a specific event.

    Sleeper describes "Tue After" as processing just after
    Tuesday ends. We represent that boundary as 12:05 AM
    Pacific on the following calendar day.

    This function intentionally isolates the weekday mapping
    so it is easy to adjust if Sleeper changes its behavior.
    """

    if (
        waiver_day_of_week
        not in SLEEPER_WEEKDAY_TO_PYTHON
    ):
        return None

    reference_time = ensure_aware(
        reference_time
    )

    reference_pt = (
        reference_time.astimezone(
            PACIFIC
        )
    )

    target_weekday = (
        SLEEPER_WEEKDAY_TO_PYTHON[
            waiver_day_of_week
        ]
    )

    days_ahead = (
        target_weekday
        - reference_pt.weekday()
    ) % 7

    target_date = (
        reference_pt.date()
        + timedelta(
            days=days_ahead
        )
    )

    clear_date = (
        target_date
        + timedelta(
            days=1
        )
    )

    clear_pt = datetime.combine(
        clear_date,
        time(
            hour=0,
            minute=5,
        ),
        tzinfo=PACIFIC,
    )

    if clear_pt <= reference_pt:
        clear_pt = (
            clear_pt
            + timedelta(
                days=7
            )
        )

    return clear_pt.astimezone(
        UTC
    )


def completed_transactions(
    transactions,
):
    return [
        transaction
        for transaction in (
            transactions
            or []
        )
        if transaction.get(
            "status"
        )
        == "complete"
    ]


def transaction_time(
    transaction,
):
    timestamp = (
        transaction.get(
            "status_updated"
        )
        or transaction.get(
            "created"
        )
    )

    return epoch_ms_to_datetime(
        timestamp
    )


def latest_drop_transaction(
    player_id,
    transactions,
):
    player_id = str(
        player_id
    )

    matches = []

    for transaction in (
        completed_transactions(
            transactions
        )
    ):
        drops = (
            transaction.get(
                "drops"
            )
            or {}
        )

        if player_id not in {
            str(key)
            for key in drops
        }:
            continue

        when = transaction_time(
            transaction
        )

        if when is None:
            continue

        matches.append(
            (
                when,
                transaction,
            )
        )

    if not matches:
        return None

    matches.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    return matches[0][1]


def latest_add_before_drop(
    player_id,
    drop_time,
    transactions,
):
    player_id = str(
        player_id
    )

    matches = []

    for transaction in (
        completed_transactions(
            transactions
        )
    ):
        adds = (
            transaction.get(
                "adds"
            )
            or {}
        )

        if player_id not in {
            str(key)
            for key in adds
        }:
            continue

        when = transaction_time(
            transaction
        )

        if (
            when is None
            or when >= drop_time
        ):
            continue

        matches.append(
            (
                when,
                transaction,
            )
        )

    if not matches:
        return None

    matches.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    return matches[0][1]


def has_24_hour_free_agent_exception(
    player_id,
    drop_transaction,
    transactions,
):
    """
    Sleeper's 24-hour rule:

    A player acquired through free agency and held for less
    than 24 hours goes directly back to free agency when
    dropped.

    A waiver acquisition does not receive this exception.
    """

    if drop_transaction is None:
        return False

    drop_time = transaction_time(
        drop_transaction
    )

    if drop_time is None:
        return False

    add_transaction = (
        latest_add_before_drop(
            player_id=player_id,
            drop_time=drop_time,
            transactions=transactions,
        )
    )

    if add_transaction is None:
        return False

    if (
        add_transaction.get(
            "type"
        )
        != "free_agent"
    ):
        return False

    add_time = transaction_time(
        add_transaction
    )

    if add_time is None:
        return False

    held_for = (
        drop_time
        - add_time
    )

    return (
        timedelta(0)
        <= held_for
        < timedelta(
            hours=24
        )
    )


def get_team_kickoff(
    nfl_team,
    games,
):
    if not nfl_team:
        return None

    return (
        build_team_kickoffs(
            games
        ).get(
            nfl_team
        )
    )


def resolve_acquisition_state(
    player_id,
    nfl_team,
    league_settings,
    transactions,
    current_week_games=None,
    previous_week_games=None,
    now=None,
):
    """
    Determine the Sleeper acquisition state for one
    currently-unrostered player.

    Returned availability values:

        FA
        W
        LOCKED
        UNKNOWN

    The resolver combines:

    - league-wide add lock,
    - custom daily waiver safety,
    - after-drop waiver duration,
    - Sleeper's 24-hour FA exception,
    - previous-week after-game waivers,
    - current-week after-game waivers.

    If multiple waiver restrictions overlap, the latest
    applicable clearance time wins.
    """

    now = ensure_aware(
        now
        or datetime.now(
            UTC
        )
    )

    settings = (
        league_settings
        or {}
    )

    if int(
        settings.get(
            "disable_adds",
            0,
        )
        or 0
    ) == 1:
        return {
            "availability": "LOCKED",
            "acquisition_state_confirmed": True,
            "immediately_addable": False,
            "reason_code": "LEAGUE_ADDS_DISABLED",
            "waiver_clear_at": None,
            "drop_24h_exception": False,
        }

    if int(
        settings.get(
            "daily_waivers",
            0,
        )
        or 0
    ) != 0:
        return {
            "availability": "UNKNOWN",
            "acquisition_state_confirmed": False,
            "immediately_addable": False,
            "reason_code": (
                "CUSTOM_DAILY_WAIVERS_UNSUPPORTED"
            ),
            "waiver_clear_at": None,
            "drop_24h_exception": False,
        }

    waiver_constraints = []

    drop_transaction = (
        latest_drop_transaction(
            player_id=player_id,
            transactions=transactions,
        )
    )

    drop_24h_exception = (
        has_24_hour_free_agent_exception(
            player_id=player_id,
            drop_transaction=drop_transaction,
            transactions=transactions,
        )
    )

    if (
        drop_transaction is not None
        and not drop_24h_exception
    ):
        drop_time = transaction_time(
            drop_transaction
        )

        clear_days = int(
            settings.get(
                "waiver_clear_days",
                0,
            )
            or 0
        )

        if (
            drop_time is not None
            and clear_days > 0
        ):
            drop_clear = (
                drop_time
                + timedelta(
                    days=clear_days
                )
            )

            if now < drop_clear:
                waiver_constraints.append(
                    {
                        "reason_code": (
                            "WAIVER_AFTER_DROP"
                        ),
                        "clear_at": (
                            drop_clear
                        ),
                    }
                )

    waiver_day = settings.get(
        "waiver_day_of_week"
    )

    if waiver_day is not None:
        try:
            waiver_day = int(
                waiver_day
            )
        except (
            TypeError,
            ValueError,
        ):
            waiver_day = None

    schedule_sources = [
        (
            "WAIVER_AFTER_PREVIOUS_GAME",
            previous_week_games,
        ),
        (
            "WAIVER_AFTER_CURRENT_GAME",
            current_week_games,
        ),
    ]

    if waiver_day is not None:
        for (
            reason_code,
            games,
        ) in schedule_sources:
            kickoff = get_team_kickoff(
                nfl_team=nfl_team,
                games=games,
            )

            if (
                kickoff is None
                or kickoff > now
            ):
                continue

            clear_at = (
                next_weekly_clear_after(
                    reference_time=kickoff,
                    waiver_day_of_week=(
                        waiver_day
                    ),
                )
            )

            if (
                clear_at is not None
                and now < clear_at
            ):
                waiver_constraints.append(
                    {
                        "reason_code": (
                            reason_code
                        ),
                        "clear_at": (
                            clear_at
                        ),
                    }
                )

    if waiver_constraints:
        controlling_constraint = max(
            waiver_constraints,
            key=lambda item: item[
                "clear_at"
            ],
        )

        return {
            "availability": "W",
            "acquisition_state_confirmed": True,
            "immediately_addable": False,
            "reason_code": (
                controlling_constraint[
                    "reason_code"
                ]
            ),
            "waiver_clear_at": (
                controlling_constraint[
                    "clear_at"
                ].isoformat()
            ),
            "drop_24h_exception": (
                drop_24h_exception
            ),
            "waiver_constraints": [
                {
                    "reason_code": item[
                        "reason_code"
                    ],
                    "clear_at": item[
                        "clear_at"
                    ].isoformat(),
                }
                for item
                in waiver_constraints
            ],
        }

    return {
        "availability": "FA",
        "acquisition_state_confirmed": True,
        "immediately_addable": True,
        "reason_code": "FREE_AGENT",
        "waiver_clear_at": None,
        "drop_24h_exception": (
            drop_24h_exception
        ),
        "waiver_constraints": [],
    }
