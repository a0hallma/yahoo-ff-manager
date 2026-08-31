import json
from pathlib import Path
from agents import function_tool


ROSTER_FILE = Path(__file__).parent / "data" / "roster.json"


@function_tool
def get_my_roster() -> str:
    """
    Return the players currently on my fantasy football roster,
    including lineup position and player status when available.
    """
    with open(ROSTER_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    return json.dumps(data, indent=2)
