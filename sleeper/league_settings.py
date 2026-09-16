import json
from collections import Counter
from pathlib import Path


SLEEPER_LEAGUE_SETTINGS_FILE = Path(
    "data/sleeper_league_settings.json"
)


def yards_per_point(points_per_yard):
    """
    Convert a scoring rate such as 0.04 points per passing yard
    into the more readable 25 yards per point.
    """

    if not points_per_yard:
        return None

    return round(1 / points_per_yard, 4)


def get_scoring_format(reception_points):
    """
    Convert points per reception into a readable description.
    """

    if reception_points == 1:
        return "Full PPR"

    if reception_points == 0.5:
        return "Half PPR"

    if reception_points == 0:
        return "Standard"

    return f"{reception_points} PPR"


def build_normalized_league_settings(
    client,
    league_id,
    season=2026,
):
    """
    Pull live Sleeper league settings and translate them into
    approximately the same structure used by the Yahoo league.

    Sleeper-specific raw values are also retained so we do not
    lose information or guess about undocumented numeric codes.
    """

    league = client.get_league(league_id)

    settings = league.get("settings") or {}
    scoring = league.get("scoring_settings") or {}
    roster_positions = league.get("roster_positions") or []

    slot_counts = Counter(roster_positions)

    reception_points = scoring.get("rec", 0)

    normalized = {
        "provider": "sleeper",
        "season": int(league.get("season") or season),
        "league_id": league.get("league_id"),
        "league_name": league.get("name"),

        "league_format": {
            "number_of_teams": (
                settings.get("num_teams")
                or league.get("total_rosters")
            ),
            "scoring_type": "Head-to-Head",
            "scoring_format": get_scoring_format(
                reception_points
            ),
            "start_scoring_week": settings.get(
                "start_week"
            ),
            "divisions": None,
            "play_against_median": bool(
                settings.get("league_average_match", 0)
            ),
            "second_opponent": bool(
                settings.get("league_average_match", 0)
            ),
        },

        "roster_slots": {
            "QB": slot_counts.get("QB", 0),
            "RB": slot_counts.get("RB", 0),
            "WR": slot_counts.get("WR", 0),
            "TE": slot_counts.get("TE", 0),
            "FLEX": slot_counts.get("FLEX", 0),
            "FLEX_ELIGIBILITY": [
                "WR",
                "RB",
                "TE",
            ],
            "SUPERFLEX": (
                slot_counts.get("SUPER_FLEX", 0)
                + slot_counts.get("SUPERFLEX", 0)
            ),
            "K": slot_counts.get("K", 0),
            "DEF": slot_counts.get("DEF", 0),
            "BENCH": slot_counts.get("BN", 0),
            "IR": settings.get("reserve_slots", 0),
        },

        "waivers": {
            "system": (
                f"Sleeper waiver_type="
                f"{settings.get('waiver_type')}"
            ),
            "waiver_time_days": settings.get(
                "waiver_clear_days"
            ),
            "weekly_waivers": None,
            "waiver_day_of_week_code": settings.get(
                "waiver_day_of_week"
            ),
            "faab": None,
            "faab_starting_budget": settings.get(
                "waiver_budget"
            ),
            "faab_minimum_bid": settings.get(
                "waiver_bid_min"
            ),
            "max_acquisitions_season": None,
            "max_acquisitions_week": None,
            "injured_players_can_be_added_directly_to_ir": None,
            "post_draft_players": None,
        },

        "trades": {
            "max_trades": None,
            "trade_deadline": None,
            "trade_deadline_week": settings.get(
                "trade_deadline"
            ),
            "draft_pick_trades": bool(
                settings.get("pick_trading", 0)
            ),
            "review_method": None,
            "review_period_days": settings.get(
                "trade_review_days"
            ),
        },

        "playoffs": {
            "teams": settings.get("playoff_teams"),
            "start_week": settings.get(
                "playoff_week_start"
            ),
            "weeks": None,
            "reseeding": None,
            "tiebreaker": None,
            "lock_eliminated_teams": None,
        },

        "scoring": {
            "passing": {
                "yards_per_point": yards_per_point(
                    scoring.get("pass_yd")
                ),
                "touchdown": scoring.get("pass_td"),
                "interception": scoring.get(
                    "pass_int"
                ),
                "two_point_conversion": scoring.get(
                    "pass_2pt"
                ),
            },

            "rushing": {
                "yards_per_point": yards_per_point(
                    scoring.get("rush_yd")
                ),
                "touchdown": scoring.get("rush_td"),
                "two_point_conversion": scoring.get(
                    "rush_2pt"
                ),
            },

            "receiving": {
                "reception": scoring.get("rec"),
                "yards_per_point": yards_per_point(
                    scoring.get("rec_yd")
                ),
                "touchdown": scoring.get("rec_td"),
                "two_point_conversion": scoring.get(
                    "rec_2pt"
                ),
            },

            "misc_offense": {
                "return_touchdown": scoring.get(
                    "st_td"
                ),
                "fumble_lost": scoring.get(
                    "fum_lost"
                ),
                "offensive_fumble_return_touchdown": (
                    scoring.get("fum_rec_td")
                ),
            },

            "kicking": {
                "field_goal_0_19": scoring.get(
                    "fgm_0_19"
                ),
                "field_goal_20_29": scoring.get(
                    "fgm_20_29"
                ),
                "field_goal_30_39": scoring.get(
                    "fgm_30_39"
                ),
                "field_goal_40_49": scoring.get(
                    "fgm_40_49"
                ),
                "field_goal_50_59": scoring.get(
                    "fgm_50_59"
                ),
                "field_goal_60_plus": scoring.get(
                    "fgm_60p"
                ),
                "field_goal_missed": scoring.get(
                    "fgmiss"
                ),
                "extra_point_made": scoring.get(
                    "xpm"
                ),
                "extra_point_missed": scoring.get(
                    "xpmiss"
                ),
            },

            "defense": {
                "sack": scoring.get("sack"),
                "interception": scoring.get("int"),
                "forced_fumble": scoring.get("ff"),
                "fumble_recovery": scoring.get(
                    "fum_rec"
                ),
                "touchdown": scoring.get("def_td"),
                "safety": scoring.get("safe"),
                "blocked_kick": scoring.get(
                    "blk_kick"
                ),
                "special_teams_touchdown": (
                    scoring.get("def_st_td")
                ),
                "special_teams_forced_fumble": (
                    scoring.get("def_st_ff")
                ),
                "special_teams_fumble_recovery": (
                    scoring.get("def_st_fum_rec")
                ),

                "points_allowed": {
                    "0": scoring.get(
                        "pts_allow_0"
                    ),
                    "1-6": scoring.get(
                        "pts_allow_1_6"
                    ),
                    "7-13": scoring.get(
                        "pts_allow_7_13"
                    ),
                    "14-20": scoring.get(
                        "pts_allow_14_20"
                    ),
                    "21-27": scoring.get(
                        "pts_allow_21_27"
                    ),
                    "28-34": scoring.get(
                        "pts_allow_28_34"
                    ),
                    "35+": scoring.get(
                        "pts_allow_35p"
                    ),
                },
            },
        },

        "other_rules": {
            "cant_cut_list_provider": None,
            "fractional_points": True,
            "negative_points": any(
                value < 0
                for value in scoring.values()
                if isinstance(value, (int, float))
            ),
            "lock_benched_players": bool(
                settings.get("bench_lock", 0)
            ),
        },

        "provider_raw": {
            "status": league.get("status"),
            "settings": settings,
            "scoring_settings": scoring,
            "roster_positions": roster_positions,
        },
    }

    return normalized


def save_normalized_league_settings(settings):
    """
    Save Sleeper league settings separately from Yahoo settings.
    """

    SLEEPER_LEAGUE_SETTINGS_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with SLEEPER_LEAGUE_SETTINGS_FILE.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            settings,
            file,
            indent=2,
            ensure_ascii=False,
        )

    return SLEEPER_LEAGUE_SETTINGS_FILE