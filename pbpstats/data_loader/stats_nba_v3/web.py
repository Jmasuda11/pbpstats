"""Fetch one NBA or WNBA game from the stats API, parse possessions, save JSON.

The adapter never touches the network. This module requests the V3
play-by-play and box score, binds the adapter's context to those exact bytes,
and records any period-start box score that the original's starter recovery
asks for. Possessions come from the unchanged original engine.

    python -m pbpstats.data_loader.stats_nba_v3.web 0022500001 -o game.json
"""

import argparse
import hashlib
import json
from pathlib import Path

import requests

from pbpstats import REQUEST_TIMEOUT

from .decoder import V3Context, V3DecodeError
from .names import add_actor_aliases, add_unaccented_names, require
from .possessions import StatsNbaV3PossessionLoader
from .starters import V3EvidenceRequired, V3StarterBoxscore

# The original's own league hosts, keyed by game ID prefix.
STATS_URLS = {"00": "https://stats.nba.com/stats/", "10": "https://stats.wnba.com/stats/"}
# The stats API rejects pbpstats' older default headers; these follow nba_api.
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Referer": "https://www.nba.com/",
    "Pragma": "no-cache",
    "Cache-Control": "no-cache",
    "Sec-Ch-Ua": '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Fetch-Dest": "empty",
}


def get(url, params, session=None):
    """One stats.nba.com request; the caller decides how to treat its status."""
    return (session or requests).get(
        url, params=sorted(params.items()), headers=HEADERS, timeout=REQUEST_TIMEOUT
    )


def stats_url(game_id):
    """Stats API base URL for a supported league; nothing is requested otherwise."""
    if not isinstance(game_id, str) or game_id[:2] not in STATS_URLS:
        raise V3DecodeError("Only NBA and WNBA game IDs are supported")
    return STATS_URLS[game_id[:2]]


def fetch_game(game_id, session=None):
    """Raw V3 play-by-play and box score responses for one game."""
    base = stats_url(game_id)
    pbp = get(
        base + "playbyplayv3",
        dict(GameID=game_id, StartPeriod=0, EndPeriod=0),
        session,
    )
    box = get(
        base + "boxscoretraditionalv3",
        dict(
            GameID=game_id,
            StartPeriod=0,
            EndPeriod=0,
            StartRange=0,
            EndRange=0,
            RangeType=0,
        ),
        session,
    )
    for response in (pbp, box):
        response.raise_for_status()
    return dict(
        pbp=pbp.content, boxscore=box.content, pbp_url=pbp.url, boxscore_url=box.url
    )


def context_from_boxscore(game_id, pbp_bytes, box_bytes, source, aliases=None):
    """Teams and the named roster from the official box score, bound to the PBP.

    Names come from the box score, the play-by-play's own ID-bound actor
    names and descriptions, and unaccented variants; nobody is guessed from a
    name. ``aliases`` maps a box-score person ID to reviewed extra names, for
    descriptions that use a name the box score does not (for example a given
    name). Period starters are left to the original's inference.
    """
    try:
        box = json.loads(box_bytes)["boxScoreTraditional"]
        rows = json.loads(pbp_bytes)["game"]["actions"]
        teams = (box["homeTeamId"], box["awayTeamId"])
        players = [
            (team, p)
            for side, team in zip(("homeTeam", "awayTeam"), teams)
            for p in box[side]["players"]
        ]
    except (ValueError, KeyError, TypeError) as error:
        raise V3DecodeError("Unexpected box score or play-by-play response") from error
    roster = {}
    for team, player in players:
        names = [player.get("familyName"), player.get("nameI")]
        if player.get("firstName") and player.get("familyName"):
            names.append(player["firstName"] + " " + player["familyName"])
        roster[player["personId"]] = {
            "team_id": team,
            "names": sorted({n for n in names if n}),
        }
    for row in rows:
        facts = roster.get(row.get("personId"))
        if facts is None:
            continue
        require(
            row.get("teamId") in (0, facts["team_id"]),
            "roster_identity",
            "Play-by-play actor contradicts the box score team",
        )
        for key in ("playerName", "playerNameI"):
            name = row.get(key)
            if isinstance(name, str) and name.strip() and name not in facts["names"]:
                facts["names"].append(name)
    for identity, names in (aliases or {}).items():
        require(identity in roster, "alias", "Alias for a player not in the box score")
        roster[identity]["names"] += [
            n for n in names if n not in roster[identity]["names"]
        ]
    add_actor_aliases(rows, roster)
    add_unaccented_names(roster)
    return V3Context(
        game_id, teams, roster, {}, source, hashlib.sha256(pbp_bytes).hexdigest()
    )


def boxscore_starters(box_bytes):
    """First-period starters marked in the box score, when each team has five."""
    box = json.loads(box_bytes)["boxScoreTraditional"]
    starters = {
        box[side]["teamId"]: [
            p["personId"] for p in box[side]["players"] if p.get("position")
        ]
        for side in ("homeTeam", "awayTeam")
    }
    return starters if all(len(p) == 5 for p in starters.values()) else None


def parse_possessions(pbp_bytes, context, fetch_boxscore=None):
    """Parse V3 bytes into possessions with the original engine.

    When the original's starter inference falls back to its period-start box
    score request, ``fetch_boxscore(period, url, params)`` must return that
    response; it is recorded as V3StarterBoxscore evidence. Without it, the
    adapter's V3EvidenceRequired error names the exact request instead.
    """
    boxscores = {}
    while True:
        try:
            return StatsNbaV3PossessionLoader(
                pbp_bytes, context, starter_boxscores=boxscores
            )
        except V3EvidenceRequired as needed:
            if fetch_boxscore is None or needed.period in boxscores:
                raise
            response = fetch_boxscore(needed.period, needed.url, needed.params)
            boxscores[needed.period] = V3StarterBoxscore(
                response.content,
                response.url,
                context.pbp_sha256,
                needed.params,
                response.status_code,
                response.reason or "",
            )


def load_game(game_id, pbp_bytes, box_bytes, source, fetch_boxscore=None, aliases=None):
    """Context from the box score, then possessions from the original engine.

    Starters come from the original's own inference. Only if a name is
    ambiguous, such as a tip to one of two same-named players, are the box
    score's first-period starter markers supplied as recorded on-court
    evidence; the adapter checks each such resolution against the original's
    lineup. The loader's context then lists those starters.
    """
    context = context_from_boxscore(game_id, pbp_bytes, box_bytes, source, aliases)
    try:
        return parse_possessions(pbp_bytes, context, fetch_boxscore)
    except V3DecodeError as error:
        starters = boxscore_starters(box_bytes)
        if "is unresolved or ambiguous" not in str(error) or starters is None:
            raise
        context.period_starters = {1: starters}
        return parse_possessions(pbp_bytes, context, fetch_boxscore)


def _event(event, teams):
    return dict(
        event_num=event.event_num,
        type=type(event).__name__.replace("Stats", "", 1),
        period=event.period,
        clock=event.clock,
        description=event.description,
        team_id=getattr(event, "team_id", None),
        player1_id=getattr(event, "player1_id", None),
        player2_id=getattr(event, "player2_id", None),
        player3_id=getattr(event, "player3_id", None),
        score={str(team): event.score.get(team, 0) for team in teams},
        lineups={
            str(team): sorted(players)
            for team, players in event.current_players.items()
        },
        source_indices=list(event.v3_source_indices),
    )


def _possession(possession, teams):
    end = possession.events[-1]
    offense = possession.offense_team_id
    try:
        start_type = possession.possession_start_type
    except Exception:  # depends on optional facts such as shot coordinates
        start_type = None
    return dict(
        period=possession.period,
        number=possession.number,
        offense_team_id=offense,
        defense_team_id=next(t for t in teams if t != offense),
        start_clock=possession.start_time,
        end_clock=possession.end_time,
        start_score_margin=possession.start_score_margin,
        start_type=start_type,
        counted=bool(end.count_as_possession),
        # Lineups the original credits with this possession (counted only).
        credited_lineups={
            str(row["team_id"]): row["lineup_id"]
            for row in end.base_stats
            if row["stat_key"] in ("OffPoss", "DefPoss")
        },
        events=[_event(event, teams) for event in possession.events],
    )


def possessions_json(loader, sources=None):
    """Possessions as plain JSON data; detailed statistics stay gated."""
    teams = loader.decoded.context.team_ids
    return dict(
        game_id=loader.game_id,
        home_team_id=teams[0],
        away_team_id=teams[1],
        final_score={str(t): loader.events[-1].score.get(t, 0) for t in teams},
        credited_possessions={str(t): n for t, n in loader.counts_by_team.items()},
        capabilities=loader.capabilities,
        diagnostics=loader.diagnostics,
        # Starters supplied as recorded evidence; all others were inferred.
        supplied_period_starters={
            str(period): {str(t): players for t, players in by_team.items()}
            for period, by_team in loader.decoded.context.period_starters.items()
        },
        sources=sources or {},
        possessions=[_possession(p, teams) for p in loader.items],
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "game_id", help="Ten-character NBA or WNBA game ID, e.g. 0022500001"
    )
    parser.add_argument("-o", "--output", type=Path, help="JSON file to write")
    parser.add_argument("--pbp", type=Path, help="Saved playbyplayv3 response")
    parser.add_argument(
        "--boxscore", type=Path, help="Saved boxscoretraditionalv3 response"
    )
    parser.add_argument(
        "--save-responses", type=Path, help="Directory for the raw responses used"
    )
    parser.add_argument(
        "--alias",
        action="append",
        default=[],
        metavar="PERSON_ID=NAME",
        help="Reviewed extra name for a box-score player (repeatable)",
    )
    args = parser.parse_args(argv)
    aliases = {}
    for item in args.alias:
        identity, _, name = item.partition("=")
        if not identity.isdigit() or not name.strip():
            parser.error("--alias expects PERSON_ID=NAME")
        aliases.setdefault(int(identity), []).append(name.strip())
    session = requests.Session()
    if args.pbp or args.boxscore:
        if not (args.pbp and args.boxscore):
            parser.error("--pbp and --boxscore are used together")
        raw = dict(
            pbp=args.pbp.read_bytes(),
            boxscore=args.boxscore.read_bytes(),
            pbp_url=str(args.pbp),
            boxscore_url=str(args.boxscore),
        )
    else:
        raw = fetch_game(args.game_id, session)
    fetched = {}

    def fetch_boxscore(period, url, params):
        fetched[period] = get(url, params, session)
        return fetched[period]

    loader = load_game(
        args.game_id,
        raw["pbp"],
        raw["boxscore"],
        raw["pbp_url"] + " ; " + raw["boxscore_url"],
        fetch_boxscore=None if args.pbp else fetch_boxscore,
        aliases=aliases,
    )
    sources = dict(
        pbp=dict(url=raw["pbp_url"], sha256=hashlib.sha256(raw["pbp"]).hexdigest()),
        boxscore=dict(
            url=raw["boxscore_url"], sha256=hashlib.sha256(raw["boxscore"]).hexdigest()
        ),
        starter_boxscores={
            str(period): dict(
                url=r.url,
                status=r.status_code,
                sha256=hashlib.sha256(r.content).hexdigest(),
            )
            for period, r in fetched.items()
        },
        reviewed_aliases={str(k): v for k, v in aliases.items()},
    )
    if args.save_responses:
        args.save_responses.mkdir(parents=True, exist_ok=True)
        (args.save_responses / "playbyplayv3.json").write_bytes(raw["pbp"])
        (args.save_responses / "boxscoretraditionalv3.json").write_bytes(
            raw["boxscore"]
        )
        for period, response in fetched.items():
            name = "boxscoretraditionalv2_period_{}.json".format(period)
            (args.save_responses / name).write_bytes(response.content)
    output = args.output or Path(args.game_id + ".possessions.json")
    output.write_text(
        json.dumps(possessions_json(loader, sources), indent=2), encoding="utf-8"
    )
    print(
        "{}: {} possessions, credited {}, final score {} -> {}".format(
            args.game_id,
            len(loader.items),
            loader.counts_by_team,
            dict(loader.events[-1].score),
            output,
        )
    )


if __name__ == "__main__":
    main()
