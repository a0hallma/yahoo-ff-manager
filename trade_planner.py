import json
import os
from datetime import (
    date,
    datetime,
)
from typing import Literal
from urllib.parse import urlparse

from agents import (
    Agent,
    Runner,
    WebSearchTool,
)
from pydantic import (
    BaseModel,
    Field,
)
from dotenv import load_dotenv

from provider_context import (
    get_current_provider,
    get_provider_display_name,
)
from roster_tools import load_roster
from league_tools import load_league_settings
from league_roster_tools import (
    build_league_roster_summary,
)

from usage_tracker import record_run_usage


load_dotenv()


MODEL_NAME = os.getenv(
    "FANTASY_MODEL_TRADE",
    "gpt-5.6-sol",
)

MAX_VALUATION_AGE_DAYS = 14

# A 2-for-1 package is less valuable than the raw sum because the
# receiving manager must open another roster spot and is giving up the
# best single asset. The second-most-valuable asset is therefore
# discounted when Python measures the package.
SECOND_ASSET_PACKAGE_WEIGHT = 0.70

MIN_ADJUSTED_RATIO = 0.80
MAX_ADJUSTED_RATIO = 1.20

# Used only for the fallback ROS-rank valuation method.
ROS_INDEX_MAX_RANK = 1000


class TradeOfferAsset(BaseModel):
    player_name: str
    position: str

    # Exactly one of these valuation inputs is required according to
    # the idea's valuation_method.
    trade_value: float | None = None
    ros_rank: int | None = None


class TradeIdea(BaseModel):
    target_player: str
    target_team: str
    target_position: str

    target_team_position_count: int
    target_team_same_position_players: list[str]

    replacement_risk: Literal[
        "high",
        "medium",
        "low",
    ]

    attainability: Literal[
        "high",
        "medium",
        "low",
    ]

    offer_players: list[
        TradeOfferAsset
    ] = Field(
        min_length=1,
        max_length=2,
    )

    # Preferred method is a published numerical trade-value chart.
    # Fallback method is a current overall rest-of-season ranking from
    # one source, converted by Python into a common 0-100 GM Trade
    # Index so more players can be evaluated without inventing trade
    # values.
    valuation_method: Literal[
        "published_trade_value",
        "ros_rank_index",
    ]

    valuation_source: str
    valuation_source_url: str
    valuation_date: str
    valuation_format: str

    target_trade_value: float | None = None
    target_ros_rank: int | None = None

    upgrade_path: str
    partner_fit: str
    offer_rationale: str
    my_roster_impact: str
    negotiation_note: str
    value_note: str

    confidence: Literal[
        "high",
        "medium",
        "low",
    ]


class TradePlan(BaseModel):
    summary: str

    # This prevents the model from returning zero ideas after looking
    # at only one or two obvious targets.
    teams_evaluated: list[str]

    ideas: list[TradeIdea]


TRADE_PLANNER_INSTRUCTIONS = """
You are the trade-analysis and offer-construction component of a
season-long fantasy football GM system.

You will receive:

- my current fantasy roster,
- league settings,
- authoritative league-wide roster data,
- current fantasy provider information.

The league-wide roster data is authoritative for fantasy ownership
and roster construction.

CORE OBJECTIVE

Find concrete trades that improve MY roster while also giving the
other manager a plausible roster-construction reason to consider the
offer.

Do not begin with famous target names and then try to force a package.

Instead:

1. Identify the positions where MY roster has depth that could be
   traded without damaging the starting lineup.
2. Evaluate EVERY opposing fantasy roster.
3. Identify opposing managers whose roster construction could benefit
   from one or two of my realistically tradable players.
4. On those teams, identify targets who would materially improve my
   starting lineup, flexibility, bye-week coverage, or overall
   rest-of-season value.
5. Construct the concrete offer only after both sides of the roster
   fit make sense.

OWNERSHIP AND ROSTER RULES

- Never invent which fantasy team owns a player.
- Every proposed target must currently appear on the named opposing
  team's authoritative roster.
- Never propose trading for a player already on my roster.
- Every player in offer_players must currently be on MY authoritative
  fantasy roster.
- Never invent positional depth for another fantasy team.
- target_team_position_count must exactly match the number of players
  at the target's position on that team's authoritative roster.
- target_team_same_position_players must list every player at that
  position on the target team, including the target.
- target_position must match the authoritative roster data.
- Each idea must contain a concrete one-player or two-player offer.
- Avoid giving away an elite cornerstone merely to fill a bench need.

PARTNER-FIT RULES

- Evaluate what the OTHER manager actually gains from the proposed
  package based on that manager's authoritative roster.
- Do not assume another manager would accept a trade.
- Do not call a player surplus merely because the manager has depth at
  an unrelated position.
- Positional replacement risk is based on the target team's depth at
  the target's own position.

Use these deterministic replacement-risk definitions:

- high:
  The target is the only player at that position.

- medium:
  The opposing roster has exactly two players at that position.

- low:
  The opposing roster has three or more players at that position.

If replacement_risk is high:

- Explicitly acknowledge that moving the target creates a position
  hole.
- attainability cannot be high.
- The offered package should provide enough value and roster help to
  make the discussion plausible.

If replacement_risk is medium:

- Identify the other player at the position.
- Do not assume either player is expendable merely because there are
  two.

If replacement_risk is low:

- Depth may improve trade plausibility, but player quality and
  starting requirements still matter.

ATTAINABILITY

Use:

- high:
  Strong roster-construction reason exists for the other manager to
  consider moving the target.

- medium:
  A plausible path exists, but meaningful value would be required.

- low:
  The target is difficult to acquire because of elite value,
  positional scarcity, role, or the hole created for the partner.

Do not confuse target quality with attainability.

VALUATION METHOD

Every idea must include a CURRENT quantitative market reference.

Use the following methods in order:

METHOD 1 - published_trade_value

Prefer a current published numeric REDRAFT trade-value chart from an
established fantasy-football source.

Requirements:

- Use ONE source and ONE scoring format for the target and every
  offered player in that idea.
- valuation_source must name the source.
- valuation_source_url must be the specific HTTP/HTTPS source page.
- valuation_date must be the publication/update date in YYYY-MM-DD.
- valuation_format must identify the applicable format, for example
  "redraft, 1QB, full PPR".
- target_trade_value must contain the target's published numeric value.
- Every offer_players.trade_value must contain the offered player's
  published numeric value.
- target_ros_rank and offer_players.ros_rank should be null.
- Never invent a published trade value.
- If the chart does not cover enough players to create a credible
  offer, DO NOT immediately abandon the target. Use METHOD 2.

METHOD 2 - ros_rank_index

If a numerical trade-value chart does not cover enough players, use a
current reputable OVERALL REST-OF-SEASON REDRAFT ranking that includes
the target and every player in the proposed offer.

Requirements:

- Use ONE source and ONE scoring format for all players in the idea.
- valuation_source, URL, date, and format are still required.
- target_ros_rank must contain the target's overall ROS rank.
- Every offer_players.ros_rank must contain the offered player's
  overall ROS rank.
- target_trade_value and offer_players.trade_value should be null.
- Python will convert the ranks into a deterministic 0-100 GM Trade
  Index. Do NOT invent that index yourself.
- Do not use positional-only ranks. They must be comparable OVERALL
  ranks from the same source and format.

The quantitative measurement is a market reference, not proof of
fairness or acceptance.

The hard maximum package-adjusted offer is 120% of the target
measurement. Python will calculate the authoritative package-adjusted
ratio. Do not perform or narrate that arithmetic yourself.

OFFER CONSTRUCTION

- offer_players must contain one or two current players from my team.
- Prefer a 1-for-1 when it solves both teams' needs.
- Use 2-for-1 consolidation when my depth can buy a better single
  starter without damaging my lineup.
- Explain why the partner may want the actual players being offered.
- Explain what I lose and what I gain.
- Do NOT calculate, quote, or paraphrase package totals, value ratios,
  percentage deltas, ceilings, or value bands in offer_rationale,
  negotiation_note, value_note, partner_fit, or my_roster_impact.
- Python owns all trade-value arithmetic and will render the
  authoritative ratio, delta, value band, and negotiation tier.
- Your negotiation_note should discuss football leverage and how much
  willingness I should have to increase the offer, without performing
  your own arithmetic.
- Do not force arithmetic equality if roster construction makes the
  deal bad.
- Do not return a target without a concrete offer.

PLAYER-VALUE RULES

- Use current research for role, workload, recent performance,
  injuries, depth-chart changes, and other material context when
  useful.
- Fantasy ownership always comes from the supplied league data.
- In a one-QB and one-TE league, do not pursue a backup QB or TE merely
  because my roster has only one.
- A TE trade is worthwhile only if it is a material starting-lineup
  upgrade or otherwise creates meaningful roster value.
- Prefer trades that consolidate replaceable depth into stronger
  starters.
- Consider preserving strong starters and scarce RB depth.
- Do not trade away an elite starter merely because the other manager
  would accept.

ZERO-IDEA RULE

You may return zero ideas, but ONLY after evaluating every opposing
fantasy team and attempting BOTH valuation methods where appropriate.

teams_evaluated must list every opposing fantasy team exactly once.

If zero ideas remain after that work, the summary must explain the
specific roster-fit/value reasons no credible package exists.

Return at most three concrete trade proposals.
"""


trade_agent = Agent(
    name="Fantasy Trade Planner",
    instructions=TRADE_PLANNER_INSTRUCTIONS,
    model=MODEL_NAME,
    output_type=TradePlan,
    tools=[
        WebSearchTool(),
    ],
)


def normalize_name(
    name,
):
    return (
        str(name or "")
        .strip()
        .lower()
    )


def normalize_position(
    position,
):
    return (
        str(position or "")
        .strip()
        .upper()
    )


def parse_valuation_date(
    value,
):
    try:
        return date.fromisoformat(
            str(value).strip()
        )

    except (
        TypeError,
        ValueError,
    ):
        return None


def ros_rank_to_index(
    rank,
):
    """
    Convert an overall ROS rank to a nonlinear 0-100 internal index.

    This intentionally supports deep overall rankings. The previous
    top-200 cutoff caused otherwise usable same-source ROS rankings to
    fail validation simply because a player ranked outside the first
    200.

    The logarithmic curve keeps elite players meaningfully separated
    from replacement-level depth while remaining comparable for
    players ranked well beyond 200.

    This is an internal comparison index, not a published trade value.
    """

    import math

    try:
        rank = int(
            rank
        )

    except (
        TypeError,
        ValueError,
    ):
        return None

    if (
        rank < 1
        or rank > ROS_INDEX_MAX_RANK
    ):
        return None

    if rank == 1:
        return 100.0

    max_log = math.log(
        ROS_INDEX_MAX_RANK
    )

    rank_log = math.log(
        rank
    )

    remaining_fraction = max(
        0.0,
        1.0
        - (
            rank_log
            / max_log
        ),
    )

    return round(
        100
        * (
            remaining_fraction ** 2
        ),
        2,
    )


def get_asset_measurement_value(
    asset,
    method,
):
    if method == "published_trade_value":
        value = asset.trade_value

        if value is None:
            return None

        try:
            value = float(
                value
            )

        except (
            TypeError,
            ValueError,
        ):
            return None

        if value <= 0:
            return None

        return round(
            value,
            2,
        )

    return ros_rank_to_index(
        asset.ros_rank
    )


def get_target_measurement_value(
    idea,
):
    if (
        idea.valuation_method
        == "published_trade_value"
    ):
        value = (
            idea.target_trade_value
        )

        if value is None:
            return None

        try:
            value = float(
                value
            )

        except (
            TypeError,
            ValueError,
        ):
            return None

        if value <= 0:
            return None

        return round(
            value,
            2,
        )

    return ros_rank_to_index(
        idea.target_ros_rank
    )


def calculate_package_values(
    asset_values,
):
    values = sorted(
        (
            float(value)
            for value in asset_values
        ),
        reverse=True,
    )

    raw_total = round(
        sum(
            values
        ),
        2,
    )

    if len(values) <= 1:
        adjusted_total = (
            raw_total
        )

    else:
        adjusted_total = round(
            values[0]
            + (
                values[1]
                * SECOND_ASSET_PACKAGE_WEIGHT
            ),
            2,
        )

    return (
        raw_total,
        adjusted_total,
    )


def classify_value_ratio(
    ratio,
):
    if ratio < 0.90:
        return "opening_offer_discount"

    if ratio <= 1.05:
        return "near_fair_value"

    if ratio <= 1.15:
        return "reasonable_premium"

    return "maximum_offer"


def validate_valuation_source(
    idea,
):
    errors = []

    if not (
        idea.valuation_source
        or ""
    ).strip():
        errors.append(
            (
                f"{idea.target_player}: "
                "valuation_source is required."
            )
        )

    url = (
        idea.valuation_source_url
        or ""
    ).strip()

    parsed_url = urlparse(
        url
    )

    if (
        parsed_url.scheme
        not in {
            "http",
            "https",
        }
        or not parsed_url.netloc
    ):
        errors.append(
            (
                f"{idea.target_player}: valuation_source_url "
                "must be a specific HTTP/HTTPS source URL."
            )
        )

    valuation_date = (
        parse_valuation_date(
            idea.valuation_date
        )
    )

    if valuation_date is None:
        errors.append(
            (
                f"{idea.target_player}: valuation_date must "
                "be YYYY-MM-DD."
            )
        )

    else:
        today = (
            datetime.now()
            .astimezone()
            .date()
        )

        age_days = (
            today
            - valuation_date
        ).days

        if age_days < 0:
            errors.append(
                (
                    f"{idea.target_player}: valuation date "
                    "is in the future."
                )
            )

        elif (
            age_days
            > MAX_VALUATION_AGE_DAYS
        ):
            errors.append(
                (
                    f"{idea.target_player}: valuation source "
                    f"is {age_days} days old; maximum allowed "
                    f"age is {MAX_VALUATION_AGE_DAYS} days."
                )
            )

    if not (
        idea.valuation_format
        or ""
    ).strip():
        errors.append(
            (
                f"{idea.target_player}: valuation_format "
                "is required."
            )
        )

    if (
        idea.valuation_method
        == "published_trade_value"
    ):
        if (
            idea.target_trade_value
            is None
            or idea.target_trade_value
            <= 0
        ):
            errors.append(
                (
                    f"{idea.target_player}: published trade-value "
                    "method requires a positive target_trade_value."
                )
            )

        if (
            idea.target_ros_rank
            is not None
        ):
            errors.append(
                (
                    f"{idea.target_player}: target_ros_rank must "
                    "be null for published_trade_value."
                )
            )

        for asset in idea.offer_players:
            if (
                asset.trade_value
                is None
                or asset.trade_value
                <= 0
            ):
                errors.append(
                    (
                        f"{idea.target_player}: "
                        f"{asset.player_name} requires a positive "
                        "trade_value for published_trade_value."
                    )
                )

    else:
        if (
            ros_rank_to_index(
                idea.target_ros_rank
            )
            is None
        ):
            errors.append(
                (
                    f"{idea.target_player}: ros_rank_index requires "
                    f"a target overall ROS rank from 1 to "
                    f"{ROS_INDEX_MAX_RANK}."
                )
            )

        if (
            idea.target_trade_value
            is not None
        ):
            errors.append(
                (
                    f"{idea.target_player}: target_trade_value must "
                    "be null for ros_rank_index."
                )
            )

        for asset in idea.offer_players:
            if (
                ros_rank_to_index(
                    asset.ros_rank
                )
                is None
            ):
                errors.append(
                    (
                        f"{idea.target_player}: "
                        f"{asset.player_name} requires an overall "
                        f"ROS rank from 1 to {ROS_INDEX_MAX_RANK}."
                    )
                )

    return errors


def get_expected_replacement_risk(
    position_count,
):
    if position_count <= 1:
        return "high"

    if position_count == 2:
        return "medium"

    return "low"


def validate_trade_plan(
    plan,
    league_summary,
):
    errors = []

    my_team = None
    ownership = {}
    opposing_team_names = []

    for team in league_summary.get(
        "teams",
        [],
    ):
        team_name = team.get(
            "team_name"
        )

        players = set()
        player_positions = {}
        players_by_position = {}

        for position, names in team.get(
            "players_by_position",
            {},
        ).items():
            normalized_names = sorted(
                names
            )

            players_by_position[
                position
            ] = normalized_names

            for name in normalized_names:
                players.add(
                    name
                )

                player_positions[
                    name
                ] = position

        ownership[
            team_name
        ] = {
            "players": players,
            "positions": player_positions,
            "players_by_position": (
                players_by_position
            ),
        }

        if team.get(
            "is_my_team"
        ):
            my_team = team_name

        else:
            opposing_team_names.append(
                team_name
            )

    if (
        not my_team
        or my_team
        not in ownership
    ):
        errors.append(
            (
                "Unable to identify my team in the "
                "authoritative league-wide roster snapshot."
            )
        )

        return {
            "is_valid": False,
            "errors": errors,
            "idea_measurements": [],
        }

    expected_teams = {
        name
        for name in opposing_team_names
        if name
    }

    supplied_teams = {
        name
        for name in (
            plan.teams_evaluated
            or []
        )
        if name
    }

    if supplied_teams != expected_teams:
        missing = sorted(
            expected_teams
            - supplied_teams
        )

        extras = sorted(
            supplied_teams
            - expected_teams
        )

        if missing:
            errors.append(
                (
                    "Trade planner did not evaluate every opponent. "
                    "Missing: "
                    + ", ".join(
                        missing
                    )
                )
            )

        if extras:
            errors.append(
                (
                    "Trade planner listed unknown/non-opponent "
                    "teams as evaluated: "
                    + ", ".join(
                        extras
                    )
                )
            )

    if len(
        plan.teams_evaluated
    ) != len(
        supplied_teams
    ):
        errors.append(
            (
                "teams_evaluated contains duplicate team names."
            )
        )

    my_ownership = (
        ownership[
            my_team
        ]
    )

    seen_targets = set()
    idea_measurements = []

    for idea in plan.ideas:
        target_team = (
            idea.target_team
        )

        target_player = (
            idea.target_player
        )

        if target_team == my_team:
            errors.append(
                f"{target_player} was proposed from "
                "my own fantasy team."
            )

        if target_team not in ownership:
            errors.append(
                f"Unknown target team: {target_team}"
            )
            continue

        team_ownership = (
            ownership[
                target_team
            ]
        )

        if (
            target_player
            not in team_ownership[
                "players"
            ]
        ):
            errors.append(
                f"{target_player} is not rostered by "
                f"{target_team} in the authoritative "
                "league snapshot."
            )
            continue

        actual_position = (
            team_ownership[
                "positions"
            ].get(
                target_player
            )
        )

        if (
            actual_position
            and normalize_position(
                idea.target_position
            )
            != normalize_position(
                actual_position
            )
        ):
            errors.append(
                f"{target_player} position mismatch: "
                f"plan says {idea.target_position}, "
                f"authoritative roster says "
                f"{actual_position}."
            )

        actual_same_position_players = (
            team_ownership[
                "players_by_position"
            ].get(
                actual_position,
                [],
            )
        )

        actual_position_count = len(
            actual_same_position_players
        )

        if (
            idea.target_team_position_count
            != actual_position_count
        ):
            errors.append(
                f"{target_player} target-team "
                f"{actual_position} depth mismatch: "
                f"plan says "
                f"{idea.target_team_position_count}, "
                f"authoritative roster says "
                f"{actual_position_count}."
            )

        if (
            sorted(
                idea.target_team_same_position_players
            )
            != actual_same_position_players
        ):
            errors.append(
                f"{target_player} same-position roster list "
                "does not match authoritative data."
            )

        expected_replacement_risk = (
            get_expected_replacement_risk(
                actual_position_count
            )
        )

        if (
            idea.replacement_risk
            != expected_replacement_risk
        ):
            errors.append(
                f"{target_player} replacement-risk mismatch: "
                f"plan says {idea.replacement_risk}, "
                f"deterministic value is "
                f"{expected_replacement_risk}."
            )

        if (
            expected_replacement_risk
            == "high"
            and idea.attainability
            == "high"
        ):
            errors.append(
                f"{target_player} cannot have high "
                "attainability when trading him would "
                "leave the opposing team with no other "
                f"{actual_position}."
            )

        target_key = (
            target_team,
            target_player,
        )

        if target_key in seen_targets:
            errors.append(
                f"Duplicate trade target: "
                f"{target_player} from "
                f"{target_team}."
            )

        seen_targets.add(
            target_key
        )

        if len(
            idea.offer_players
        ) not in {
            1,
            2,
        }:
            errors.append(
                (
                    f"{target_player}: offer must contain "
                    "one or two players."
                )
            )

        seen_offer_players = set()

        for asset in idea.offer_players:
            offer_key = normalize_name(
                asset.player_name
            )

            if offer_key in seen_offer_players:
                errors.append(
                    (
                        f"{target_player}: duplicate offered "
                        f"player {asset.player_name}."
                    )
                )

            seen_offer_players.add(
                offer_key
            )

            authoritative_name = next(
                (
                    name
                    for name in my_ownership[
                        "players"
                    ]
                    if normalize_name(
                        name
                    )
                    == offer_key
                ),
                None,
            )

            if not authoritative_name:
                errors.append(
                    (
                        f"{target_player}: offered player "
                        f"{asset.player_name} is not on my "
                        "authoritative roster."
                    )
                )
                continue

            authoritative_position = (
                my_ownership[
                    "positions"
                ].get(
                    authoritative_name
                )
            )

            if (
                authoritative_position
                and normalize_position(
                    asset.position
                )
                != normalize_position(
                    authoritative_position
                )
            ):
                errors.append(
                    (
                        f"{target_player}: offered player "
                        f"{asset.player_name} position mismatch. "
                        f"Plan says {asset.position}; "
                        f"authoritative roster says "
                        f"{authoritative_position}."
                    )
                )

        errors.extend(
            validate_valuation_source(
                idea
            )
        )

        target_value = (
            get_target_measurement_value(
                idea
            )
        )

        asset_values = [
            get_asset_measurement_value(
                asset,
                idea.valuation_method,
            )
            for asset in (
                idea.offer_players
            )
        ]

        if (
            target_value is None
            or any(
                value is None
                for value in asset_values
            )
        ):
            continue

        (
            raw_offer_value,
            adjusted_offer_value,
        ) = calculate_package_values(
            asset_values
        )

        ratio = round(
            adjusted_offer_value
            / target_value,
            4,
        )

        value_delta = round(
            adjusted_offer_value
            - target_value,
            2,
        )

        value_delta_pct = round(
            (
                value_delta
                / target_value
            )
            * 100,
            1,
        )

        value_band = (
            classify_value_ratio(
                ratio
            )
        )

        if (
            ratio
            < MIN_ADJUSTED_RATIO
        ):
            errors.append(
                (
                    f"{target_player}: package-adjusted value "
                    f"ratio {ratio:.2f} is below the minimum "
                    f"credible threshold of "
                    f"{MIN_ADJUSTED_RATIO:.2f}."
                )
            )

        if (
            ratio
            > MAX_ADJUSTED_RATIO
        ):
            errors.append(
                (
                    f"{target_player}: package-adjusted value "
                    f"ratio {ratio:.2f} exceeds the maximum "
                    f"overpay threshold of "
                    f"{MAX_ADJUSTED_RATIO:.2f}."
                )
            )

        asset_measurements = []

        for (
            asset,
            value,
        ) in zip(
            idea.offer_players,
            asset_values,
        ):
            asset_measurements.append(
                {
                    "player_name": (
                        asset.player_name
                    ),
                    "position": (
                        asset.position
                    ),
                    "source_trade_value": (
                        asset.trade_value
                    ),
                    "source_ros_rank": (
                        asset.ros_rank
                    ),
                    "measurement_value": (
                        value
                    ),
                }
            )

        idea_measurements.append(
            {
                "target_player": (
                    target_player
                ),
                "target_team": (
                    target_team
                ),
                "valuation_method": (
                    idea.valuation_method
                ),
                "valuation_source": (
                    idea.valuation_source
                ),
                "valuation_source_url": (
                    idea.valuation_source_url
                ),
                "valuation_date": (
                    idea.valuation_date
                ),
                "valuation_format": (
                    idea.valuation_format
                ),
                "target_source_trade_value": (
                    idea.target_trade_value
                ),
                "target_source_ros_rank": (
                    idea.target_ros_rank
                ),
                "target_measurement_value": (
                    target_value
                ),
                "offer_assets": (
                    asset_measurements
                ),
                "raw_offer_value": (
                    raw_offer_value
                ),
                "package_adjusted_offer_value": (
                    adjusted_offer_value
                ),
                "second_asset_weight": (
                    SECOND_ASSET_PACKAGE_WEIGHT
                    if len(asset_values) == 2
                    else None
                ),
                "offer_to_target_ratio": (
                    ratio
                ),
                "value_delta": (
                    value_delta
                ),
                "value_delta_pct": (
                    value_delta_pct
                ),
                "value_band": (
                    value_band
                ),
                "negotiation_tier": (
                    "OPENING OFFER"
                    if ratio < 0.90
                    else (
                        "FAIR OFFER"
                        if ratio <= 1.05
                        else (
                            "REASONABLE PREMIUM"
                            if ratio <= 1.15
                            else "MAXIMUM OFFER"
                        )
                    )
                ),
                "do_not_increase_offer": (
                    ratio > 1.15
                ),
            }
        )

    if len(
        plan.ideas
    ) > 3:
        errors.append(
            "Trade planner returned more than "
            "three trade ideas."
        )

    return {
        "is_valid": not errors,
        "errors": errors,
        "idea_measurements": (
            idea_measurements
        ),
        "opponents_expected": sorted(
            expected_teams
        ),
        "opponents_evaluated": sorted(
            supplied_teams
        ),
    }


def salvage_valid_trade_ideas(
    plan,
    league_summary,
):
    """
    Keep individually valid trade ideas and discard invalid ones.

    Trade analysis should be fail-closed at the idea level rather than
    all-or-nothing at the report level. A hallucinated target name or a
    bad valuation on one proposal must not erase other proposals that
    independently pass every ownership, roster-fit, and value check.
    """

    valid_ideas = []
    rejected_ideas = []
    combined_measurements = []

    for idea in plan.ideas:
        single_plan = TradePlan(
            summary=plan.summary,
            teams_evaluated=(
                plan.teams_evaluated
            ),
            ideas=[
                idea
            ],
        )

        validation = (
            validate_trade_plan(
                single_plan,
                league_summary,
            )
        )

        if validation[
            "is_valid"
        ]:
            valid_ideas.append(
                idea
            )

            combined_measurements.extend(
                validation.get(
                    "idea_measurements",
                    [],
                )
            )

        else:
            rejected_ideas.append(
                {
                    "target_player": (
                        idea.target_player
                    ),
                    "target_team": (
                        idea.target_team
                    ),
                    "errors": (
                        validation.get(
                            "errors",
                            [],
                        )
                    ),
                }
            )

    if not valid_ideas:
        return None

    salvaged_plan = TradePlan(
        summary=(
            plan.summary
            + (
                " Invalid candidate proposals were omitted "
                "because they failed deterministic ownership, "
                "roster-fit, or valuation validation."
                if rejected_ideas
                else ""
            )
        ),
        teams_evaluated=(
            plan.teams_evaluated
        ),
        ideas=valid_ideas,
    )

    final_validation = (
        validate_trade_plan(
            salvaged_plan,
            league_summary,
        )
    )

    if not final_validation[
        "is_valid"
    ]:
        return None

    final_validation[
        "rejected_ideas"
    ] = rejected_ideas

    return {
        "plan": salvaged_plan,
        "validation": (
            final_validation
        ),
    }



def build_validated_trade_plan(
    max_attempts=3,
):
    provider = (
        get_current_provider()
    )

    provider_name = (
        get_provider_display_name()
    )

    try:
        league_summary = (
            build_league_roster_summary()
        )

    except Exception as exc:
        return {
            "provider": provider,
            "provider_name": provider_name,
            "status": "blocked",
            "blocked_reason": (
                "league_wide_rosters_unavailable"
            ),
            "reason": str(exc),
            "attempts": 0,
            "plan": None,
            "validation": None,
        }

    roster = load_roster()

    league_settings = (
        load_league_settings()
    )

    roster_json = json.dumps(
        roster,
        indent=2,
    )

    settings_json = json.dumps(
        league_settings,
        indent=2,
    )

    league_json = json.dumps(
        league_summary,
        indent=2,
    )

    prompt = f"""
Evaluate EVERY opposing fantasy roster and construct up to three
concrete trade proposals that improve my team.

CURRENT FANTASY PROVIDER

{provider_name} ({provider})

MY CURRENT ROSTER

{roster_json}

LEAGUE SETTINGS

{settings_json}

AUTHORITATIVE LEAGUE-WIDE ROSTERS

{league_json}

Use the authoritative league data as the only source of truth for
ownership and roster construction.

WORK FROM BOTH SIDES OF THE TRADE:

1. Identify which of MY players are genuinely tradable depth without
   materially weakening my current lineup.
2. Evaluate every opponent.
3. Identify which opponents could actually use those players.
4. Identify targets on those same teams who improve my roster.
5. Construct a 1-for-1 or 2-for-1 offer.
6. Quantitatively measure the proposal.

VALUATION:

First try a current published numeric redraft trade-value chart.

If that chart does not contain enough of the relevant players, DO NOT
abandon the trade. Use a current reputable OVERALL rest-of-season
redraft ranking for all players in that idea and set
valuation_method=ros_rank_index. Python will calculate the GM Trade
Index and package-adjusted comparison.

Do not mix sources within one idea.

Do not invent values or ranks.

A target without a concrete package is not a trade idea.

Before returning zero ideas, you must evaluate every opponent and try
the ROS-rank fallback where a published trade chart is incomplete.

teams_evaluated must contain every opposing fantasy team exactly once.

Return a structured TradePlan with zero to three concrete proposals.
"""

    last_validation = None

    for attempt in range(
        1,
        max_attempts + 1,
    ):
        result = Runner.run_sync(
            trade_agent,
            prompt,
        )

        record_run_usage(
            "Trade planner",
            MODEL_NAME,
            result,
        )

        plan = (
            result.final_output_as(
                TradePlan,
                raise_if_incorrect_type=True,
            )
        )

        validation = (
            validate_trade_plan(
                plan,
                league_summary,
            )
        )

        if validation[
            "is_valid"
        ]:
            return {
                "provider": provider,
                "provider_name": (
                    provider_name
                ),
                "status": "pass",
                "attempts": attempt,
                "plan": plan.model_dump(),
                "validation": validation,
                "league_summary": (
                    league_summary
                ),
            }

        salvaged = (
            salvage_valid_trade_ideas(
                plan,
                league_summary,
            )
        )

        if salvaged:
            return {
                "provider": provider,
                "provider_name": (
                    provider_name
                ),
                "status": "pass",
                "attempts": attempt,
                "plan": (
                    salvaged[
                        "plan"
                    ].model_dump()
                ),
                "validation": (
                    salvaged[
                        "validation"
                    ]
                ),
                "league_summary": (
                    league_summary
                ),
            }

        last_validation = (
            validation
        )

        prompt = f"""
Your previous trade plan failed deterministic Python validation.

CURRENT FANTASY PROVIDER

{provider_name} ({provider})

MY CURRENT ROSTER

{roster_json}

LEAGUE SETTINGS

{settings_json}

AUTHORITATIVE LEAGUE-WIDE ROSTERS

{league_json}

VALIDATION ERRORS

{json.dumps(validation["errors"], indent=2)}

Correct the plan.

Requirements:

- Evaluate EVERY opposing team and list each exactly once in
  teams_evaluated.
- Every target must be on the named opposing roster.
- Every offered player must be on my roster.
- Offer one or two players only.
- target position/depth and replacement risk must match authoritative
  data.
- Do not force a TE merely because my roster has one TE.
- Use published_trade_value when a current chart covers the target and
  offer players.
- If a current trade-value chart is incomplete, use ros_rank_index
  with one current OVERALL ROS redraft ranking source for all players
  in that idea.
- Do not mix valuation sources within an idea.
- Do not invent values or rankings.
- Keep the package inside the deterministic value-ratio bounds stated
  in the validation errors.
- The hard maximum package-adjusted offer is 120% of the target
  measurement. A proposal above that is too expensive to recommend.
- Do not perform or narrate the trade-value arithmetic yourself;
  Python will calculate and render it.
- Player names and team ownership must exactly match the authoritative
  league snapshot. Do not approximate, abbreviate, or "correct" names
  from memory.
- An overall ROS rank may be anywhere from 1 through
  {ROS_INDEX_MAX_RANK}; do not discard a usable same-source rank merely
  because it is outside the top 200.
- If a candidate cannot be supported by exact ownership and a valid
  same-source measurement, OMIT that candidate instead of repeatedly
  forcing it into the plan.
- Return at most three concrete proposals.

Return a corrected TradePlan.
"""

    return {
        "provider": provider,
        "provider_name": (
            provider_name
        ),
        "status": "blocked",
        "blocked_reason": (
            "no_valid_trade_proposals_after_retries"
        ),
        "reason": (
            "Trade analysis could not produce a concrete proposal "
            "that passed deterministic ownership, roster-fit, and "
            f"valuation validation after {max_attempts} attempts."
        ),
        "attempts": (
            max_attempts
        ),
        "plan": None,
        "validation": (
            last_validation
        ),
        "league_summary": (
            league_summary
        ),
    }
