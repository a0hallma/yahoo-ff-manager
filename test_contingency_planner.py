import json

from contingency_planner import build_validated_contingency


base_lineup = {
    "qb": "Matthew Stafford",
    "rb1": "Cam Skattebo",
    "rb2": "Kenneth Walker III",
    "wr1": "Garrett Wilson",
    "wr2": "DK Metcalf",
    "te": "Dalton Kincaid",
    "flex": "David Montgomery",
    "k": "Tyler Loop",
    "defense": "Seattle Seahawks",
}


result = build_validated_contingency(
    unavailable_player="Kenneth Walker III",
    base_lineup=base_lineup,
)


print(json.dumps(result, indent=2))