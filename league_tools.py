import json
from pathlib import Path

from agents import function_tool

from provider_context import (
    get_current_provider,
    normalize_provider,
)


DATA_DIR = Path(__file__).parent / "data"

LEAGUE_SETTINGS_FILES = {
    "yahoo": DATA_DIR / "league_settings.json",
    "sleeper": DATA_DIR / "sleeper_league_settings.json",
}


def resolve_provider(provider=None):
    """
    Determine which fantasy provider to use.

    If a provider is explicitly supplied, use it.

    Otherwise, use the provider selected for the current
    Fantasy GM run.
    """

    if provider is None:
        return get_current_provider()

    return normalize_provider(provider)


def load_league_settings(provider=None) -> dict:
    """
    Load normalized league settings for the requested provider.

    If no provider is supplied, use the provider selected
    in provider_context.py.
    """

    provider = resolve_provider(provider)

    settings_file = LEAGUE_SETTINGS_FILES[provider]

    if not settings_file.exists():
        raise FileNotFoundError(
            f"No league settings snapshot exists for provider "
            f"'{provider}': {settings_file}"
        )

    with settings_file.open(
        "r",
        encoding="utf-8",
    ) as file:
        data = json.load(file)

    data.setdefault(
        "provider",
        provider,
    )

    return data


@function_tool
def get_league_settings(
    provider: str | None = None,
) -> str:
    """
    Return the fantasy football league's scoring, roster,
    waiver, playoff, and other configuration settings.

    If provider is omitted, use the provider selected for
    the current Fantasy GM run.

    Supported providers:
      yahoo
      sleeper
    """

    data = load_league_settings(provider)

    return json.dumps(
        data,
        indent=2,
    )