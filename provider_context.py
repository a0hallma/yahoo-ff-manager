SUPPORTED_PROVIDERS = {
    "yahoo",
    "sleeper",
}

_current_provider = "yahoo"


def normalize_provider(provider):
    """
    Validate and normalize a fantasy provider name.
    """

    provider = str(
        provider or "yahoo"
    ).strip().lower()

    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(
            f"Unsupported fantasy provider: {provider}. "
            f"Expected one of: "
            f"{', '.join(sorted(SUPPORTED_PROVIDERS))}"
        )

    return provider


def set_current_provider(provider):
    """
    Set the fantasy provider for the current program run.
    """

    global _current_provider

    _current_provider = normalize_provider(
        provider
    )

    return _current_provider


def get_current_provider():
    """
    Return the fantasy provider selected for this run.
    """

    return _current_provider


def get_provider_display_name():
    """
    Return a friendly provider name for reports.
    """

    names = {
        "yahoo": "Yahoo",
        "sleeper": "Sleeper",
    }

    return names[get_current_provider()]