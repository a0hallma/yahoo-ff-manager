import json

from contingency_validator import validate_contingency


base = {
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


backup = {
    "qb": "Baker Mayfield",
    "rb1": "Cam Skattebo",
    "rb2": "Kenneth Walker III",
    "wr1": "Garrett Wilson",
    "wr2": "Wan'Dale Robinson",
    "te": "Dalton Kincaid",
    "flex": "David Montgomery",
    "k": "Tyler Loop",
    "defense": "Seattle Seahawks",
}

result = validate_contingency(
    unavailable_player="DK Metcalf",
    base_lineup=base,
    contingency_lineup=backup,
)


print(json.dumps(result, indent=2))