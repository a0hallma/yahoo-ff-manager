import os
import requests


YAHOO_API_BASE = "https://fantasysports.yahooapis.com/fantasy/v2"


class YahooFantasyClient:
    def __init__(self):
        self.client_id = os.getenv("YAHOO_CLIENT_ID")
        self.client_secret = os.getenv("YAHOO_CLIENT_SECRET")
        self.access_token = os.getenv("YAHOO_ACCESS_TOKEN")
        self.refresh_token = os.getenv("YAHOO_REFRESH_TOKEN")

    @property
    def configured(self):
        return bool(self.client_id and self.client_secret)

    @property
    def authenticated(self):
        return bool(self.access_token)

    def _headers(self):
        if not self.access_token:
            raise RuntimeError("Yahoo has not been authenticated yet.")

        return {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
        }

    def get(self, path, params=None):
        url = f"{YAHOO_API_BASE}/{path.lstrip('/')}"
        params = params or {}
        params["format"] = "json"

        response = requests.get(
            url,
            headers=self._headers(),
            params=params,
            timeout=30,
        )

        response.raise_for_status()
        return response.json()
