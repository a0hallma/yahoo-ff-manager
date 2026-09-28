import os
import xml.etree.ElementTree as ET

import requests
from dotenv import load_dotenv


# Explicit path avoids python-dotenv's stdin auto-discovery edge case.
# In GitHub Actions the environment variables are already present, so
# a missing local .env file is harmless.
load_dotenv(
    dotenv_path=".env",
)

# Local Windows TLS inspection can require the OS trust store.
# GitHub-hosted runners do not require this dependency, so keep it
# optional instead of making the Yahoo provider depend on it.
try:
    import truststore

    truststore.inject_into_ssl()

except ImportError:
    pass


YAHOO_API_BASE = (
    "https://fantasysports.yahooapis.com/fantasy/v2"
)

YAHOO_TOKEN_URL = (
    "https://api.login.yahoo.com/oauth2/get_token"
)


class YahooFantasyClient:
    def __init__(self):
        self.client_id = os.getenv(
            "YAHOO_CLIENT_ID"
        )

        self.client_secret = os.getenv(
            "YAHOO_CLIENT_SECRET"
        )

        self.access_token = os.getenv(
            "YAHOO_ACCESS_TOKEN"
        )

        self.refresh_token = os.getenv(
            "YAHOO_REFRESH_TOKEN"
        )

        self.session = requests.Session()

    @property
    def configured(self):
        return bool(
            self.client_id
            and self.client_secret
        )

    @property
    def authenticated(self):
        return bool(
            self.access_token
        )

    @property
    def can_refresh(self):
        return bool(
            self.client_id
            and self.client_secret
            and self.refresh_token
        )

    def _headers(
        self,
        accept,
    ):
        if not self.access_token:
            raise RuntimeError(
                "Yahoo has not been authenticated yet."
            )

        return {
            "Authorization": (
                f"Bearer {self.access_token}"
            ),
            "Accept": accept,
        }

    def _build_url(
        self,
        path,
    ):
        return (
            f"{YAHOO_API_BASE}/"
            f"{path.lstrip('/')}"
        )

    def refresh_access_token(self):
        if not self.can_refresh:
            raise RuntimeError(
                "Yahoo token refresh is not configured. "
                "YAHOO_CLIENT_ID, YAHOO_CLIENT_SECRET, and "
                "YAHOO_REFRESH_TOKEN are required."
            )

        response = self.session.post(
            YAHOO_TOKEN_URL,
            auth=(
                self.client_id,
                self.client_secret,
            ),
            data={
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
            },
            timeout=30,
        )

        try:
            response.raise_for_status()

        except requests.HTTPError as exc:
            response_text = (
                response.text[:500]
                if response.text
                else "No response body"
            )

            raise RuntimeError(
                "Yahoo access-token refresh failed. "
                f"HTTP {response.status_code}. "
                f"Response: {response_text}"
            ) from exc

        try:
            token_data = response.json()

        except ValueError as exc:
            raise RuntimeError(
                "Yahoo token refresh returned invalid JSON."
            ) from exc

        new_access_token = token_data.get(
            "access_token"
        )

        if not new_access_token:
            raise RuntimeError(
                "Yahoo token refresh succeeded but did not "
                "return an access token."
            )

        self.access_token = (
            new_access_token
        )

        # Yahoo may return a refresh token in the refresh response.
        # Keep it for the current process, but never print it.
        if token_data.get(
            "refresh_token"
        ):
            self.refresh_token = (
                token_data[
                    "refresh_token"
                ]
            )

        return token_data

    def ensure_authenticated(self):
        """
        Refresh before an unattended Fantasy GM run.

        If refresh credentials are not present, an existing access
        token may still be used for ad-hoc testing.
        """

        if self.can_refresh:
            self.refresh_access_token()

        elif not self.authenticated:
            raise RuntimeError(
                "Yahoo authentication is not configured. "
                "Provide refresh credentials or an access token."
            )

        return True

    def _get_response(
        self,
        path,
        accept,
        params=None,
    ):
        if not self.access_token:
            self.ensure_authenticated()

        url = self._build_url(
            path
        )

        response = self.session.get(
            url,
            headers=self._headers(
                accept
            ),
            params=(
                dict(
                    params or {}
                )
            ),
            timeout=30,
        )

        # One safe retry handles an access token that expires between
        # refresh and a later paginated request.
        if (
            response.status_code == 401
            and self.can_refresh
        ):
            self.refresh_access_token()

            response = self.session.get(
                url,
                headers=self._headers(
                    accept
                ),
                params=(
                    dict(
                        params or {}
                    )
                ),
                timeout=30,
            )

        try:
            response.raise_for_status()

        except requests.HTTPError as exc:
            response_text = (
                response.text[:1000]
                if response.text
                else "No response body"
            )

            raise RuntimeError(
                "Yahoo API request failed. "
                f"HTTP {response.status_code}. "
                f"Path: {path}. "
                f"Response: {response_text}"
            ) from exc

        return response

    # ----------------------------------------------------------------
    # JSON support retained for existing code.
    # ----------------------------------------------------------------

    def get(
        self,
        path,
        params=None,
    ):
        request_params = dict(
            params or {}
        )

        request_params["format"] = "json"

        response = self._get_response(
            path=path,
            accept="application/json",
            params=request_params,
        )

        try:
            return response.json()

        except ValueError as exc:
            raise RuntimeError(
                "Yahoo returned a response that was not valid JSON."
            ) from exc

    # ----------------------------------------------------------------
    # XML support used by the live provider refresh.
    #
    # Yahoo's XML resource model maps cleanly to league/team/roster
    # resources and avoids the irregular numeric-key structure of the
    # JSON representation.
    # ----------------------------------------------------------------

    def get_xml(
        self,
        path,
        params=None,
    ):
        response = self._get_response(
            path=path,
            accept="application/xml",
            params=params,
        )

        try:
            return ET.fromstring(
                response.text
            )

        except ET.ParseError as exc:
            raise RuntimeError(
                "Yahoo returned a response that was not valid XML. "
                f"Path: {path}."
            ) from exc

    def get_league_xml(
        self,
        league_key,
    ):
        if not league_key:
            raise ValueError(
                "league_key is required."
            )

        return self.get_xml(
            f"league/{league_key}"
        )

    def get_league_settings_xml(
        self,
        league_key,
    ):
        if not league_key:
            raise ValueError(
                "league_key is required."
            )

        return self.get_xml(
            f"league/{league_key}/settings"
        )

    def get_league_teams_xml(
        self,
        league_key,
    ):
        if not league_key:
            raise ValueError(
                "league_key is required."
            )

        return self.get_xml(
            f"league/{league_key}/teams"
        )

    def get_team_roster_xml(
        self,
        team_key,
        week=None,
    ):
        if not team_key:
            raise ValueError(
                "team_key is required."
            )

        path = (
            f"team/{team_key}/roster"
        )

        if week is not None:
            path += (
                f";week={int(week)}"
            )

        return self.get_xml(
            path
        )

    def get_league_players_xml(
        self,
        league_key,
        status,
        start=0,
        count=25,
    ):
        """
        Fetch a page of league-context players.

        Yahoo's supported status filters include:
          FA = free agents
          W  = waivers
          A  = all available
          T  = taken
        """

        if not league_key:
            raise ValueError(
                "league_key is required."
            )

        status = str(
            status
        ).strip().upper()

        if status not in {
            "FA",
            "W",
            "A",
            "T",
        }:
            raise ValueError(
                f"Unsupported Yahoo player status filter: {status}"
            )

        if start < 0:
            raise ValueError(
                "start cannot be negative."
            )

        if count < 1:
            raise ValueError(
                "count must be at least 1."
            )

        path = (
            f"league/{league_key}/players"
            f";status={status}"
            f";start={int(start)}"
            f";count={int(count)}"
        )

        return self.get_xml(
            path
        )

    # ----------------------------------------------------------------
    # Existing raw JSON helpers retained.
    # ----------------------------------------------------------------

    def get_my_nfl_leagues_raw(self):
        return self.get(
            "users;use_login=1/"
            "games;game_codes=nfl/"
            "leagues"
        )

    def get_league_raw(
        self,
        league_key,
    ):
        if not league_key:
            raise ValueError(
                "league_key is required."
            )

        return self.get(
            f"league/{league_key}"
        )

    def get_league_players_raw(
        self,
        league_key,
        status=None,
        start=0,
        count=25,
    ):
        if not league_key:
            raise ValueError(
                "league_key is required."
            )

        if start < 0:
            raise ValueError(
                "start cannot be negative."
            )

        if count < 1:
            raise ValueError(
                "count must be at least 1."
            )

        path = (
            f"league/{league_key}/players"
        )

        if status:
            path += (
                f";status={status}"
            )

        path += (
            f";start={start}"
            f";count={count}"
        )

        return self.get(
            path
        )

    def get_available_players_raw(
        self,
        league_key,
        start=0,
        count=25,
    ):
        return self.get_league_players_raw(
            league_key=league_key,
            status="A",
            start=start,
            count=count,
        )
