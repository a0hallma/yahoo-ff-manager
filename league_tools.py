import json
from pathlib import Path
from agents import function_tool


DATA_FILE = Path(__file__).parent / "data" / "league_settings.json"


@function_tool
def get_league_settings() -> str:
    """
    Return the fantasy football league's scoring, roster, waiver,
    playoff, and other configuration settings.
    """
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    return json.dumps(data, indent=2)
