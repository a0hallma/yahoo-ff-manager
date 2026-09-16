import os

from league_tools import (
    load_league_settings,
)
from roster_tools import (
    load_roster,
)

from sleeper.client import (
    SleeperClient,
)
from sleeper.normalizer import (
    build_normalized_roster,
    save_normalized_roster,
)
from sleeper.league_settings import (
    build_normalized_league_settings,
    save_normalized_league_settings,
)
from sleeper.league_rosters import (
    build_league_rosters,
    save_league_rosters,
)
from sleeper.available_players import (
    build_available_player_snapshot,
    save_available_player_snapshot,
)


def get_env_value(name):
    value = os.getenv(
        name
    )

    if value is None:
        return None

    value = value.strip()

    return value or None


def safe_load(loader):
    """
    Existing normalized snapshots may be used only to discover
    stable identifiers such as league_id or roster_id.

    They are NOT treated as current fantasy data.
    """

    try:
        data = loader()

        if isinstance(
            data,
            dict,
        ):
            return data

    except Exception:
        pass

    return {}


def resolve_league_id(
    seed_league,
    seed_roster,
):
    """
    Resolve the Sleeper league to refresh.

    Preferred:
      SLEEPER_LEAGUE_ID environment variable.

    Local fallback:
      existing normalized league/roster snapshot.

    The fallback is only an identifier bootstrap. All actual
    fantasy data is subsequently refreshed from Sleeper.
    """

    league_id = (
        get_env_value(
            "SLEEPER_LEAGUE_ID"
        )
        or seed_league.get(
            "league_id"
        )
        or seed_roster.get(
            "league_id"
        )
    )

    if not league_id:
        raise RuntimeError(
            "Unable to determine Sleeper league_id. "
            "Set SLEEPER_LEAGUE_ID or provide an existing "
            "Sleeper league/roster snapshot."
        )

    return str(
        league_id
    )


def resolve_user_id(
    client,
    league_id,
    seed_roster,
):
    """
    Resolve the Sleeper user whose team should be analyzed.

    Preferred:
      SLEEPER_USER_ID
      SLEEPER_USERNAME

    Local fallback:
      map the existing normalized roster_id back to the live
      Sleeper league roster and use its owner_id.

    No stale roster contents are reused.
    """

    user_identifier = (
        get_env_value(
            "SLEEPER_USER_ID"
        )
        or get_env_value(
            "SLEEPER_USERNAME"
        )
    )

    if user_identifier:
        user = client.get_user(
            user_identifier
        )

        if not user:
            raise RuntimeError(
                "Configured Sleeper user could not be found."
            )

        user_id = user.get(
            "user_id"
        )

        if not user_id:
            raise RuntimeError(
                "Sleeper user response did not contain user_id."
            )

        return str(
            user_id
        )

    roster_id = seed_roster.get(
        "roster_id"
    )

    if roster_id is None:
        raise RuntimeError(
            "Unable to determine the Sleeper user. "
            "Set SLEEPER_USER_ID or SLEEPER_USERNAME."
        )

    live_rosters = (
        client.get_league_rosters(
            league_id
        )
    )

    target_roster = next(
        (
            roster
            for roster
            in live_rosters
            if str(
                roster.get(
                    "roster_id"
                )
            )
            == str(
                roster_id
            )
        ),
        None,
    )

    if target_roster is None:
        raise RuntimeError(
            "The existing Sleeper roster_id could not be "
            "found in the live league."
        )

    owner_id = target_roster.get(
        "owner_id"
    )

    if not owner_id:
        co_owners = (
            target_roster.get(
                "co_owners"
            )
            or []
        )

        if co_owners:
            owner_id = (
                co_owners[0]
            )

    if not owner_id:
        raise RuntimeError(
            "Unable to determine the Sleeper owner/user ID "
            "for the selected roster."
        )

    return str(
        owner_id
    )


def assert_league_id(
    data,
    expected_league_id,
    label,
):
    actual = data.get(
        "league_id"
    )

    if (
        actual is None
        or str(
            actual
        )
        != str(
            expected_league_id
        )
    ):
        raise RuntimeError(
            f"{label} resolved unexpected league_id. "
            f"Expected {expected_league_id}, got {actual}."
        )


def refresh_sleeper_live_data():
    """
    Refresh the complete Sleeper data plane used by the
    Fantasy GM before any analysis occurs.

    Refreshes:

      1. league settings,
      2. my roster,
      3. every league roster,
      4. acquisition-aware available players.

    All four datasets are built from live Sleeper data before
    any of them are saved.
    """

    client = (
        SleeperClient()
    )

    # ---------------------------------------------------------
    # Bootstrap stable identifiers.
    # ---------------------------------------------------------

    seed_league = safe_load(
        load_league_settings
    )

    seed_roster = safe_load(
        load_roster
    )

    league_id = resolve_league_id(
        seed_league=seed_league,
        seed_roster=seed_roster,
    )

    live_league = (
        client.get_league(
            league_id
        )
    )

    if not live_league:
        raise RuntimeError(
            f"Sleeper league not found: {league_id}"
        )

    live_league_id = str(
        live_league.get(
            "league_id"
        )
        or league_id
    )

    if (
        live_league_id
        != league_id
    ):
        raise RuntimeError(
            "Sleeper returned an unexpected league ID."
        )

    league_name = (
        live_league.get(
            "name"
        )
    )

    if not league_name:
        raise RuntimeError(
            "Live Sleeper league has no league name."
        )

    nfl_state = (
        client.get_nfl_state()
    )

    season = int(
        nfl_state.get(
            "season"
        )
        or live_league.get(
            "season"
        )
        or seed_league.get(
            "season"
        )
        or 2026
    )

    user_id = resolve_user_id(
        client=client,
        league_id=league_id,
        seed_roster=seed_roster,
    )

    # ---------------------------------------------------------
    # Build ALL live datasets in memory first.
    #
    # Nothing is saved until every required build succeeds.
    # ---------------------------------------------------------

    normalized_league = (
        build_normalized_league_settings(
            client=client,
            league_id=league_id,
            season=season,
        )
    )

    normalized_roster = (
        build_normalized_roster(
            client=client,
            username=user_id,
            league_name=league_name,
            season=season,
        )
    )

    league_rosters = (
        build_league_rosters(
            client=client,
            username=user_id,
            league_name=league_name,
            season=season,
        )
    )

    available_players = (
        build_available_player_snapshot(
            client=client,
            league_id=league_id,
        )
    )

    # ---------------------------------------------------------
    # Cross-dataset consistency checks before writing anything.
    # ---------------------------------------------------------

    assert_league_id(
        normalized_league,
        league_id,
        "League settings",
    )

    assert_league_id(
        normalized_roster,
        league_id,
        "Personal roster",
    )

    assert_league_id(
        league_rosters,
        league_id,
        "League rosters",
    )

    assert_league_id(
        available_players,
        league_id,
        "Available players",
    )

    roster_player_count = len(
        normalized_roster.get(
            "players",
            [],
        )
    )

    if roster_player_count == 0:
        raise RuntimeError(
            "Live Sleeper roster contains zero players."
        )

    league_team_count = int(
        league_rosters.get(
            "team_count",
            0,
        )
        or 0
    )

    expected_team_count = int(
        normalized_league.get(
            "league_format",
            {},
        ).get(
            "number_of_teams",
            0,
        )
        or 0
    )

    if league_team_count == 0:
        raise RuntimeError(
            "Live Sleeper league-roster snapshot contains "
            "zero teams."
        )

    if (
        expected_team_count
        and league_team_count
        != expected_team_count
    ):
        raise RuntimeError(
            "Sleeper team-count mismatch. "
            f"League settings report {expected_team_count}; "
            f"league-roster snapshot contains "
            f"{league_team_count}."
        )

    my_team_count = sum(
        1
        for team
        in league_rosters.get(
            "teams",
            [],
        )
        if team.get(
            "is_my_team"
        )
    )

    if my_team_count != 1:
        raise RuntimeError(
            "Expected exactly one Sleeper league roster to "
            f"be identified as my team; found {my_team_count}."
        )

    # ---------------------------------------------------------
    # Save only after every live build and consistency check
    # above has passed.
    # ---------------------------------------------------------

    league_path = (
        save_normalized_league_settings(
            normalized_league
        )
    )

    roster_path = (
        save_normalized_roster(
            normalized_roster
        )
    )

    league_rosters_path = (
        save_league_rosters(
            league_rosters
        )
    )

    available_path = (
        save_available_player_snapshot(
            available_players
        )
    )

    acquisition_context = (
        available_players.get(
            "acquisition_context",
            {},
        )
    )

    return {
        "provider": "sleeper",
        "league_id": league_id,
        "league_name": league_name,
        "season": season,
        "user_id": user_id,
        "week": (
            normalized_roster.get(
                "week"
            )
        ),
        "roster_id": (
            normalized_roster.get(
                "roster_id"
            )
        ),
        "team_name": (
            normalized_roster.get(
                "team_name"
            )
        ),
        "roster_player_count": (
            roster_player_count
        ),
        "league_team_count": (
            league_team_count
        ),
        "generated_at": (
            available_players.get(
                "generated_at"
            )
        ),
        "availability_counts": (
            available_players.get(
                "availability_counts",
                {},
            )
        ),
        "schedule_errors": (
            acquisition_context.get(
                "schedule_errors",
                [],
            )
        ),
        "transaction_errors": (
            acquisition_context.get(
                "transaction_errors",
                [],
            )
        ),
        "paths": {
            "league_settings": str(
                league_path
            ),
            "roster": str(
                roster_path
            ),
            "league_rosters": str(
                league_rosters_path
            ),
            "available_players": str(
                available_path
            ),
        },
    }


def refresh_sleeper_acquisition_snapshot():
    """
    Backward-compatible entry point used by weekly_report.py.

    This now refreshes the entire Sleeper data plane, not only
    acquisition state.
    """

    return (
        refresh_sleeper_live_data()
    )
