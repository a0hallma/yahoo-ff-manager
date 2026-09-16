import json
from pathlib import Path

from agents import function_tool

from provider_context import (
    get_current_provider,
    normalize_provider,
)


DATA_DIR = Path(__file__).parent / "data"

ROSTER_FILES = {
    "yahoo": DATA_DIR / "roster.json",
    "sleeper": DATA_DIR / "sleeper_roster.json",
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


def load_roster(provider=None) -> dict:
    """
    Load the normalized roster for the requested provider.

    If no provider is supplied, use the provider selected
    in provider_context.py.
    """

    provider = resolve_provider(provider)

    roster_file = ROSTER_FILES[provider]

    if not roster_file.exists():
        raise FileNotFoundError(
            f"No roster snapshot exists for provider "
            f"'{provider}': {roster_file}"
        )

    with roster_file.open(
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
def get_my_roster(provider: str | None = None) -> str:
    """
    Return the players currently on my fantasy football roster.

    If provider is omitted, use the provider selected for the
    current Fantasy GM run.

    Supported providers:
      yahoo
      sleeper
    """

    data = load_roster(provider)

    return json.dumps(
        data,
        indent=2,
    )