import requests


SLEEPER_API_BASE = "https://api.sleeper.app/v1"


class SleeperClient:
    """
    Small read-only client for the Sleeper Fantasy API.

    This file talks to Sleeper and provides a few convenience
    methods for locating the user's league and roster.
    """

    def __init__(self, timeout=30):
        self.timeout = timeout
        self.session = requests.Session()

    def get(self, path):
        url = f"{SLEEPER_API_BASE}/{path.lstrip('/')}"

        response = self.session.get(
            url,
            timeout=self.timeout,
        )

        response.raise_for_status()
        return response.json()

    def get_user(self, username_or_user_id):
        return self.get(f"user/{username_or_user_id}")

    def get_user_leagues(self, user_id, season=2026):
        return self.get(
            f"user/{user_id}/leagues/nfl/{season}"
        )

    def get_league(self, league_id):
        return self.get(f"league/{league_id}")

    def get_league_users(self, league_id):
        return self.get(f"league/{league_id}/users")

    def get_league_rosters(self, league_id):
        return self.get(f"league/{league_id}/rosters")

    def get_matchups(self, league_id, week):
        return self.get(
            f"league/{league_id}/matchups/{week}"
        )

    def get_transactions(self, league_id, week):
        return self.get(
            f"league/{league_id}/transactions/{week}"
        )

    def get_nfl_state(self):
        return self.get("state/nfl")

    def get_players(self, position=None, active=None):
        path = "players/nfl"

        params = []

        if position:
            params.append(f"position={position}")

        if active is not None:
            params.append(
                f"active={'true' if active else 'false'}"
            )

        if params:
            path += "?" + "&".join(params)

        return self.get(path)

    def get_trending_players(
        self,
        trend_type="add",
        lookback_hours=24,
        limit=25,
    ):
        return self.get(
            "players/nfl/trending/"
            f"{trend_type}"
            f"?lookback_hours={lookback_hours}"
            f"&limit={limit}"
        )

    def find_user_league(
        self,
        user_id,
        season=2026,
        league_name=None,
    ):
        """
        Find one of the user's Sleeper leagues.

        If league_name is provided, require an exact
        case-insensitive league-name match.
        """

        leagues = self.get_user_leagues(
            user_id=user_id,
            season=season,
        )

        if league_name is None:
            if len(leagues) == 1:
                return leagues[0]

            return leagues

        matches = [
            league
            for league in leagues
            if league.get("name", "").lower()
            == league_name.lower()
        ]

        if not matches:
            raise ValueError(
                f"Could not find Sleeper league: {league_name}"
            )

        if len(matches) > 1:
            raise ValueError(
                f"More than one Sleeper league is named: {league_name}"
            )

        return matches[0]

    def get_user_roster(self, league_id, user_id):
        """
        Find the roster owned or co-owned by the specified user.
        """

        rosters = self.get_league_rosters(league_id)

        user_id = str(user_id)

        for roster in rosters:
            owner_id = roster.get("owner_id")

            co_owners = roster.get("co_owners") or []

            if str(owner_id) == user_id:
                return roster

            if user_id in [str(x) for x in co_owners]:
                return roster

        raise ValueError(
            f"Could not find a roster for user {user_id} "
            f"in league {league_id}"
        )