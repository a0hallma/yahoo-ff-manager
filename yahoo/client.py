import os

import requests
from dotenv import load_dotenv


load_dotenv()


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

    def _headers(self):
        if not self.access_token:
            raise RuntimeError(
                "Yahoo has not been authenticated yet."
            )

        return {
            "Authorization": (
                f"Bearer {self.access_token}"
            ),
            "Accept": "application/json",
        }

    def _build_url(
        self,
        path,
    ):
        return (
            f"{YAHOO_API_BASE}/"
            f"{path.lstrip('/')}"
        )

    def _handle_response(
        self,
        response,
    ):
        if response.status_code == 401:
            raise RuntimeError(
                "Yahoo authentication failed or the "
                "access token has expired."
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
                "Yahoo API request failed. "
                f"HTTP {response.status_code}. "
                f"Response: {response_text}"
            ) from exc

        try:
            return response.json()

        except ValueError as exc:
            raise RuntimeError(
                "Yahoo returned a response that was "
                "not valid JSON."
            ) from exc

    def get(
        self,
        path,
        params=None,
    ):
        url = self._build_url(
            path
        )

        request_params = dict(
            params or {}
        )

        request_params["format"] = "json"

        response = self.session.get(
            url,
            headers=self._headers(),
            params=request_params,
            timeout=30,
        )

        return self._handle_response(
            response
        )

    def refresh_access_token(self):
        if not self.can_refresh:
            raise RuntimeError(
                "Yahoo token refresh is not configured. "
                "Client ID, client secret, and refresh "
                "token are required."
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
            raise RuntimeError(
                "Yahoo access-token refresh failed. "
                f"HTTP {response.status_code}."
            ) from exc

        try:
            token_data = response.json()

        except ValueError as exc:
            raise RuntimeError(
                "Yahoo token refresh returned "
                "invalid JSON."
            ) from exc

        new_access_token = token_data.get(
            "access_token"
        )

        if not new_access_token:
            raise RuntimeError(
                "Yahoo token refresh succeeded but "
                "did not return an access token."
            )

        self.access_token = (
            new_access_token
        )

        if token_data.get(
            "refresh_token"
        ):
            self.refresh_token = (
                token_data[
                    "refresh_token"
                ]
            )

        return token_data

    def get_my_nfl_leagues_raw(self):
        """
        Return the raw Yahoo response containing NFL
        fantasy leagues associated with the authenticated
        Yahoo account.

        We will later use this to discover the Yahoo
        league key instead of hard-coding it.
        """

        return self.get(
            "users;use_login=1/"
            "games;game_codes=nfl/"
            "leagues"
        )

    def get_league_raw(
        self,
        league_key,
    ):
        """
        Return raw metadata for one Yahoo fantasy league.
        """

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
        """
        Return a raw Yahoo players collection for the
        supplied league.

        This method intentionally returns Yahoo's raw
        response. Normalization into the Fantasy GM's
        common available-player format will happen in a
        separate layer.
        """

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
        """
        Return Yahoo's raw available-player collection.

        Yahoo status=A is used for the available-player
        pool. We will later normalize individual Yahoo
        player availability into FA or W for the rest of
        the Fantasy GM.
        """

        return self.get_league_players_raw(
            league_key=league_key,
            status="A",
            start=start,
            count=count,
        )