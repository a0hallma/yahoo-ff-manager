import json
import os
from datetime import datetime
from pathlib import Path

from yahoo.client import YahooFantasyClient
from waiver_tools import (
    validate_available_player_snapshot,
)


DATA_DIR = (
    Path(__file__).resolve().parent.parent
    / "data"
)

LEAGUE_SETTINGS_FILE = (
    DATA_DIR
    / "league_settings.json"
)

ROSTER_FILE = (
    DATA_DIR
    / "roster.json"
)

AVAILABLE_PLAYERS_FILE = (
    DATA_DIR
    / "available_players.json"
)

LEAGUE_ROSTERS_FILE = (
    DATA_DIR
    / "yahoo_league_rosters.json"
)

SUPPORTED_POSITIONS = {
    "QB",
    "RB",
    "WR",
    "TE",
    "K",
    "DEF",
}

TEAM_CODE_ALIASES = {
    "JAC": "JAX",
    "WSH": "WAS",
}

LINEUP_SLOT_MAP = {
    "QB": "QB",
    "RB": "RB",
    "WR": "WR",
    "TE": "TE",
    "K": "K",
    "DEF": "DEF",
    "D/ST": "DEF",
    "DST": "DEF",
    "W/R": "FLEX",
    "W/T": "FLEX",
    "W/R/T": "FLEX",
    "RB/WR": "FLEX",
    "WR/TE": "FLEX",
    "RB/WR/TE": "FLEX",
    "Q/W/R/T": "SUPERFLEX",
    "QB/WR/RB/TE": "SUPERFLEX",
    "BN": "BENCH",
    "BENCH": "BENCH",
    "IR": "IR",
    "IR+": "IR",
}


def now_iso():
    return (
        datetime.now()
        .astimezone()
        .isoformat()
    )


def today_iso():
    return (
        datetime.now()
        .astimezone()
        .date()
        .isoformat()
    )


def find_text(
    element,
    path,
    default="",
):
    node = element.find(
        path
    )

    if (
        node is None
        or node.text is None
    ):
        return default

    return node.text.strip()


def parse_int(
    value,
    default=None,
):
    try:
        return int(
            value
        )

    except (
        TypeError,
        ValueError,
    ):
        return default


def parse_float(
    value,
    default=None,
):
    try:
        return float(
            value
        )

    except (
        TypeError,
        ValueError,
    ):
        return default


def normalize_team_code(
    value,
):
    code = (
        str(
            value
            or ""
        )
        .strip()
        .upper()
    )

    return TEAM_CODE_ALIASES.get(
        code,
        code,
    )


def normalize_position(
    value,
):
    raw = (
        str(
            value
            or ""
        )
        .strip()
        .upper()
    )

    if raw in {
        "DEF",
        "D/ST",
        "DST",
    }:
        return "DEF"

    # Yahoo can represent multiple eligible positions as a
    # comma-delimited display string. NFL players in this app use one
    # primary roster position, so prefer the first supported value.
    for part in raw.split(","):
        candidate = (
            part.strip()
        )

        if candidate in SUPPORTED_POSITIONS:
            return candidate

    return raw


def normalize_lineup_slot(
    value,
):
    raw = (
        str(
            value
            or ""
        )
        .strip()
        .upper()
    )

    return LINEUP_SLOT_MAP.get(
        raw,
        raw,
    )


def league_key_from_team_key(
    team_key,
):
    team_key = str(
        team_key
        or ""
    ).strip()

    marker = ".t."

    if marker not in team_key:
        raise ValueError(
            "YAHOO_TEAM_KEY must look like "
            "'470.l.412672.t.8'."
        )

    return team_key.split(
        marker,
        1,
    )[0]


def get_configured_team_key():
    team_key = (
        os.getenv(
            "YAHOO_TEAM_KEY",
            "",
        )
        .strip()
    )

    if not team_key:
        raise RuntimeError(
            "YAHOO_TEAM_KEY is required for the live Yahoo "
            "provider refresh. Example: 470.l.412672.t.8"
        )

    return team_key


def extract_player(
    player_element,
):
    name = find_text(
        player_element,
        "{*}name/{*}full",
    )

    player_key = find_text(
        player_element,
        "{*}player_key",
    )

    player_id = find_text(
        player_element,
        "{*}player_id",
    )

    nfl_team = normalize_team_code(
        find_text(
            player_element,
            "{*}editorial_team_abbr",
        )
    )

    position = normalize_position(
        find_text(
            player_element,
            "{*}display_position",
        )
    )

    selected_position = (
        normalize_lineup_slot(
            find_text(
                player_element,
                ".//{*}selected_position/{*}position",
            )
        )
    )

    provider_status = (
        find_text(
            player_element,
            "{*}status",
        )
        .strip()
        .upper()
    )

    eligible_positions = []

    for node in player_element.findall(
        ".//{*}eligible_positions/{*}position"
    ):
        if not node.text:
            continue

        normalized = normalize_lineup_slot(
            node.text
        )

        if (
            normalized
            and normalized
            not in eligible_positions
        ):
            eligible_positions.append(
                normalized
            )

    return {
        "player_key": player_key,
        "player_id": player_id,
        "name": name,
        "position": position,
        "nfl_team": nfl_team,
        "lineup_slot": selected_position,
        "status": provider_status,
        "provider_status": provider_status,
        "eligible_positions": (
            eligible_positions
        ),
    }


def extract_roster_players(
    roster_root,
):
    players = []

    seen = set()

    for player_element in roster_root.findall(
        ".//{*}player"
    ):
        player = extract_player(
            player_element
        )

        name = player.get(
            "name",
            "",
        ).strip()

        position = player.get(
            "position",
            "",
        )

        nfl_team = player.get(
            "nfl_team",
            "",
        )

        if (
            not name
            or position
            not in SUPPORTED_POSITIONS
            or not nfl_team
        ):
            continue

        identity = (
            player.get(
                "player_key"
            )
            or name.lower()
        )

        if identity in seen:
            continue

        seen.add(
            identity
        )

        players.append(
            player
        )

    return players


def build_league_metadata(
    league_root,
):
    league = league_root.find(
        ".//{*}league"
    )

    if league is None:
        raise RuntimeError(
            "Yahoo league metadata response did not contain "
            "a league resource."
        )

    league_key = find_text(
        league,
        "{*}league_key",
    )

    league_id = find_text(
        league,
        "{*}league_id",
    )

    league_name = find_text(
        league,
        "{*}name",
    )

    season = parse_int(
        find_text(
            league,
            "{*}season",
        )
    )

    current_week = parse_int(
        find_text(
            league,
            "{*}current_week",
        )
    )

    num_teams = parse_int(
        find_text(
            league,
            "{*}num_teams",
        )
    )

    if not league_key:
        raise RuntimeError(
            "Yahoo league metadata did not contain league_key."
        )

    if not league_name:
        raise RuntimeError(
            "Yahoo league metadata did not contain league name."
        )

    if not season:
        raise RuntimeError(
            "Yahoo league metadata did not contain season."
        )

    if not current_week:
        raise RuntimeError(
            "Yahoo league metadata did not contain current_week."
        )

    return {
        "league_key": league_key,
        "league_id": league_id,
        "league_name": league_name,
        "season": season,
        "current_week": current_week,
        "num_teams": num_teams,
    }


def build_league_settings_snapshot(
    metadata,
    settings_root,
):
    settings = settings_root.find(
        ".//{*}settings"
    )

    if settings is None:
        raise RuntimeError(
            "Yahoo settings response did not contain settings."
        )

    roster_slots = {}

    for roster_position in settings.findall(
        ".//{*}roster_positions/{*}roster_position"
    ):
        raw_position = find_text(
            roster_position,
            "{*}position",
        )

        count = parse_int(
            find_text(
                roster_position,
                "{*}count",
            ),
            0,
        )

        normalized = normalize_lineup_slot(
            raw_position
        )

        if (
            not normalized
            or count <= 0
        ):
            continue

        roster_slots[
            normalized
        ] = (
            roster_slots.get(
                normalized,
                0,
            )
            + count
        )

    if not roster_slots:
        raise RuntimeError(
            "Yahoo league settings did not contain roster positions."
        )

    stat_names = {}

    for stat in settings.findall(
        ".//{*}stat_categories/{*}stats/{*}stat"
    ):
        stat_id = find_text(
            stat,
            "{*}stat_id",
        )

        if not stat_id:
            continue

        stat_names[
            stat_id
        ] = {
            "name": find_text(
                stat,
                "{*}name",
            ),
            "display_name": find_text(
                stat,
                "{*}display_name",
            ),
        }

    scoring_rules = []

    for modifier in settings.findall(
        ".//{*}stat_modifiers/{*}stats/{*}stat"
    ):
        stat_id = find_text(
            modifier,
            "{*}stat_id",
        )

        value = parse_float(
            find_text(
                modifier,
                "{*}value",
            )
        )

        if not stat_id:
            continue

        names = stat_names.get(
            stat_id,
            {},
        )

        scoring_rules.append(
            {
                "stat_id": stat_id,
                "name": names.get(
                    "name",
                    "",
                ),
                "display_name": names.get(
                    "display_name",
                    "",
                ),
                "value": value,
            }
        )

    scoring_rules.sort(
        key=lambda item: (
            parse_int(
                item[
                    "stat_id"
                ],
                9999,
            )
        )
    )

    simple_setting_names = [
        "draft_type",
        "scoring_type",
        "uses_playoff",
        "has_playoff_consolation_games",
        "playoff_start_week",
        "uses_playoff_reseeding",
        "uses_lock_eliminated_teams",
        "waiver_type",
        "waiver_rule",
        "uses_faab",
        "trade_end_date",
        "trade_ratify_type",
        "trade_reject_time",
        "max_teams",
    ]

    yahoo_settings = {}

    for setting_name in simple_setting_names:
        value = find_text(
            settings,
            f"{{*}}{setting_name}",
        )

        if value != "":
            yahoo_settings[
                setting_name
            ] = value

    return {
        "provider": "yahoo",
        "source": (
            "Yahoo Fantasy Sports API"
        ),
        "generated_at": now_iso(),
        "season": metadata[
            "season"
        ],
        "league_id": metadata[
            "league_id"
        ],
        "league_key": metadata[
            "league_key"
        ],
        "league_name": metadata[
            "league_name"
        ],
        "num_teams": metadata.get(
            "num_teams"
        ),
        "current_week": metadata[
            "current_week"
        ],
        "roster_slots": roster_slots,
        "yahoo_settings": yahoo_settings,
        "scoring_rules": scoring_rules,
    }


def build_my_roster_snapshot(
    metadata,
    team_key,
    roster_root,
):
    team = roster_root.find(
        ".//{*}team"
    )

    if team is None:
        raise RuntimeError(
            "Yahoo roster response did not contain a team."
        )

    returned_team_key = find_text(
        team,
        "{*}team_key",
    )

    team_name = find_text(
        team,
        "{*}name",
    )

    if (
        returned_team_key
        and returned_team_key != team_key
    ):
        raise RuntimeError(
            "Yahoo returned a roster for an unexpected team: "
            f"{returned_team_key}"
        )

    players = extract_roster_players(
        roster_root
    )

    if not players:
        raise RuntimeError(
            "Yahoo returned an empty roster for the configured team."
        )

    names = [
        player[
            "name"
        ].strip().lower()
        for player in players
    ]

    if len(names) != len(
        set(
            names
        )
    ):
        raise RuntimeError(
            "Yahoo roster contains duplicate player names."
        )

    return {
        "provider": "yahoo",
        "source": (
            "Yahoo Fantasy Sports API"
        ),
        "generated_at": now_iso(),
        "last_updated": today_iso(),
        "season": metadata[
            "season"
        ],
        "week": metadata[
            "current_week"
        ],
        "league_id": metadata[
            "league_id"
        ],
        "league_key": metadata[
            "league_key"
        ],
        "league_name": metadata[
            "league_name"
        ],
        "team_key": team_key,
        "team_name": (
            team_name
            or team_key
        ),
        "players": players,
    }


def fetch_available_players(
    client,
    league_key,
    page_size=25,
    max_pages_per_state=80,
):
    """
    Fetch Yahoo-confirmed FA and waiver players separately.

    This is intentionally provider authoritative:
      status=FA -> FA
      status=W  -> W

    Web research is never used to infer acquisition state.
    """

    all_players = {}

    for availability in (
        "FA",
        "W",
    ):
        for page_number in range(
            max_pages_per_state
        ):
            start = (
                page_number
                * page_size
            )

            root = (
                client
                .get_league_players_xml(
                    league_key=league_key,
                    status=availability,
                    start=start,
                    count=page_size,
                )
            )

            page_players = []

            for player_element in root.findall(
                ".//{*}player"
            ):
                player = extract_player(
                    player_element
                )

                name = (
                    player.get(
                        "name",
                        "",
                    )
                    .strip()
                )

                position = player.get(
                    "position",
                    "",
                )

                nfl_team = player.get(
                    "nfl_team",
                    "",
                )

                if (
                    not name
                    or position
                    not in SUPPORTED_POSITIONS
                    or not nfl_team
                ):
                    continue

                normalized = {
                    "player_key": player.get(
                        "player_key"
                    ),
                    "player_id": player.get(
                        "player_id"
                    ),
                    "name": name,
                    "position": position,
                    "nfl_team": nfl_team,
                    "availability": availability,
                    "provider_status": player.get(
                        "provider_status",
                        "",
                    ),
                    "status": player.get(
                        "status",
                        "",
                    ),
                    "acquisition_state_confirmed": True,
                    "immediately_addable": (
                        availability
                        == "FA"
                    ),
                    "acquisition_reason": (
                        "Yahoo API status=FA"
                        if availability == "FA"
                        else "Yahoo API status=W"
                    ),
                    "waiver_date": None,
                }

                page_players.append(
                    normalized
                )

                identity = (
                    normalized.get(
                        "player_key"
                    )
                    or name.lower()
                )

                all_players[
                    identity
                ] = normalized

            # Yahoo's historical player-collection page size is 25.
            # A short page means the current status pool is exhausted.
            if len(
                root.findall(
                    ".//{*}player"
                )
            ) < page_size:
                break

        else:
            raise RuntimeError(
                "Yahoo available-player pagination exceeded "
                f"{max_pages_per_state} pages for status "
                f"{availability}."
            )

    players = list(
        all_players.values()
    )

    players.sort(
        key=lambda player: (
            player[
                "position"
            ],
            player[
                "name"
            ].lower(),
        )
    )

    return players


def build_available_players_snapshot(
    metadata,
    client,
):
    players = fetch_available_players(
        client=client,
        league_key=metadata[
            "league_key"
        ],
    )

    if not players:
        raise RuntimeError(
            "Yahoo returned no FA or waiver players."
        )

    snapshot = {
        "provider": "yahoo",
        "source": (
            "Yahoo Fantasy Sports API"
        ),
        "generated_at": now_iso(),
        "last_updated": today_iso(),
        "league_id": metadata[
            "league_id"
        ],
        "league_key": metadata[
            "league_key"
        ],
        "league_name": metadata[
            "league_name"
        ],
        "players": players,
    }

    validate_available_player_snapshot(
        snapshot,
        provider="yahoo",
    )

    return snapshot


def build_league_rosters_snapshot(
    metadata,
    team_key,
    client,
):
    teams_root = (
        client
        .get_league_teams_xml(
            metadata[
                "league_key"
            ]
        )
    )

    teams = []

    seen_team_keys = set()

    for team_element in teams_root.findall(
        ".//{*}team"
    ):
        current_team_key = find_text(
            team_element,
            "{*}team_key",
        )

        if (
            not current_team_key
            or current_team_key
            in seen_team_keys
        ):
            continue

        seen_team_keys.add(
            current_team_key
        )

        team_name = find_text(
            team_element,
            "{*}name",
        )

        manager_name = find_text(
            team_element,
            ".//{*}manager/{*}nickname",
        )

        roster_root = (
            client
            .get_team_roster_xml(
                team_key=current_team_key,
                week=metadata[
                    "current_week"
                ],
            )
        )

        players = extract_roster_players(
            roster_root
        )

        teams.append(
            {
                "roster_id": (
                    current_team_key
                ),
                "team_key": (
                    current_team_key
                ),
                "team_name": (
                    team_name
                    or current_team_key
                ),
                "manager_name": (
                    manager_name
                ),
                "is_my_team": (
                    current_team_key
                    == team_key
                ),
                "players": players,
            }
        )

    if not teams:
        raise RuntimeError(
            "Yahoo league-wide team retrieval returned no teams."
        )

    my_team_matches = [
        team
        for team in teams
        if team[
            "is_my_team"
        ]
    ]

    if len(
        my_team_matches
    ) != 1:
        raise RuntimeError(
            "Configured Yahoo team was not found exactly once in "
            "the selected league."
        )

    expected_team_count = metadata.get(
        "num_teams"
    )

    if (
        expected_team_count
        and len(
            teams
        )
        != expected_team_count
    ):
        raise RuntimeError(
            "Yahoo league-wide roster retrieval is incomplete: "
            f"expected {expected_team_count} teams, "
            f"received {len(teams)}."
        )

    return {
        "provider": "yahoo",
        "source": (
            "Yahoo Fantasy Sports API"
        ),
        "generated_at": now_iso(),
        "season": metadata[
            "season"
        ],
        "week": metadata[
            "current_week"
        ],
        "league_id": metadata[
            "league_id"
        ],
        "league_key": metadata[
            "league_key"
        ],
        "league_name": metadata[
            "league_name"
        ],
        "team_count": len(
            teams
        ),
        "teams": teams,
    }


def validate_cross_snapshot_consistency(
    roster_snapshot,
    available_snapshot,
    league_rosters_snapshot,
):
    my_roster_names = {
        player[
            "name"
        ].strip().lower()
        for player in roster_snapshot[
            "players"
        ]
    }

    available_names = {
        player[
            "name"
        ].strip().lower()
        for player in available_snapshot[
            "players"
        ]
    }

    overlap = (
        my_roster_names
        & available_names
    )

    if overlap:
        raise RuntimeError(
            "Yahoo snapshot inconsistency: players appear on both "
            "my roster and the available-player pool: "
            + ", ".join(
                sorted(
                    overlap
                )
            )
        )

    league_my_team = next(
        (
            team
            for team
            in league_rosters_snapshot[
                "teams"
            ]
            if team.get(
                "is_my_team"
            )
        ),
        None,
    )

    if not league_my_team:
        raise RuntimeError(
            "Yahoo league-wide roster snapshot has no my-team marker."
        )

    league_my_names = {
        player[
            "name"
        ].strip().lower()
        for player in league_my_team.get(
            "players",
            [],
        )
    }

    if (
        league_my_names
        != my_roster_names
    ):
        missing = (
            my_roster_names
            - league_my_names
        )

        extra = (
            league_my_names
            - my_roster_names
        )

        raise RuntimeError(
            "Yahoo my-roster and league-wide roster snapshots "
            "do not match. "
            f"Missing from league-wide view: {sorted(missing)}. "
            f"Unexpected in league-wide view: {sorted(extra)}."
        )


def atomic_write_json(
    path,
    data,
):
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp_path = path.with_suffix(
        path.suffix
        + ".tmp"
    )

    with temp_path.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            data,
            file,
            indent=2,
        )

    temp_path.replace(
        path
    )


def refresh_yahoo_snapshot(
    team_key=None,
):
    """
    Refresh every Yahoo provider snapshot required by the Fantasy GM.

    The refresh is read-only against Yahoo. It writes only local JSON
    snapshots after every API call and cross-snapshot validation has
    succeeded.
    """

    team_key = (
        str(
            team_key
            or get_configured_team_key()
        )
        .strip()
    )

    league_key = (
        league_key_from_team_key(
            team_key
        )
    )

    client = YahooFantasyClient()

    client.ensure_authenticated()

    league_root = (
        client.get_league_xml(
            league_key
        )
    )

    metadata = (
        build_league_metadata(
            league_root
        )
    )

    if (
        metadata[
            "league_key"
        ]
        != league_key
    ):
        raise RuntimeError(
            "Yahoo returned an unexpected league key: "
            f"{metadata['league_key']}"
        )

    settings_root = (
        client
        .get_league_settings_xml(
            league_key
        )
    )

    league_settings = (
        build_league_settings_snapshot(
            metadata=metadata,
            settings_root=settings_root,
        )
    )

    roster_root = (
        client
        .get_team_roster_xml(
            team_key=team_key,
            week=metadata[
                "current_week"
            ],
        )
    )

    roster_snapshot = (
        build_my_roster_snapshot(
            metadata=metadata,
            team_key=team_key,
            roster_root=roster_root,
        )
    )

    available_snapshot = (
        build_available_players_snapshot(
            metadata=metadata,
            client=client,
        )
    )

    league_rosters_snapshot = (
        build_league_rosters_snapshot(
            metadata=metadata,
            team_key=team_key,
            client=client,
        )
    )

    validate_cross_snapshot_consistency(
        roster_snapshot=roster_snapshot,
        available_snapshot=available_snapshot,
        league_rosters_snapshot=(
            league_rosters_snapshot
        ),
    )

    # Commit only after the full provider refresh validates.
    atomic_write_json(
        LEAGUE_SETTINGS_FILE,
        league_settings,
    )

    atomic_write_json(
        ROSTER_FILE,
        roster_snapshot,
    )

    atomic_write_json(
        AVAILABLE_PLAYERS_FILE,
        available_snapshot,
    )

    atomic_write_json(
        LEAGUE_ROSTERS_FILE,
        league_rosters_snapshot,
    )

    availability_counts = {
        state: sum(
            1
            for player
            in available_snapshot[
                "players"
            ]
            if player[
                "availability"
            ]
            == state
        )
        for state in (
            "FA",
            "W",
        )
    }

    return {
        "provider": "yahoo",
        "league_key": league_key,
        "league_name": metadata[
            "league_name"
        ],
        "team_key": team_key,
        "team_name": roster_snapshot[
            "team_name"
        ],
        "season": metadata[
            "season"
        ],
        "week": metadata[
            "current_week"
        ],
        "roster_count": len(
            roster_snapshot[
                "players"
            ]
        ),
        "team_count": (
            league_rosters_snapshot[
                "team_count"
            ]
        ),
        "available_count": len(
            available_snapshot[
                "players"
            ]
        ),
        "availability_counts": (
            availability_counts
        ),
        "generated_at": now_iso(),
    }
