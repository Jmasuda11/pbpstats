"""Fetch one NBA or WNBA game from the stats API, parse possessions, save JSON.

The V3 loaders take a game ID and a source loader, as the original's do; their
file and web sources supply the play-by-play, the box score and, only when the
parse asks for it, recorded evidence. This module parses a game from responses
already in hand through the same loaders. ``load_game`` binds the context to
the exact play-by-play and box score bytes, and records any period-start box
score that the original's starter recovery asks for. A jump ball V3 leaves
undecided is completed from the league's live play-by-play, also recorded.
Reviewed corrections reach the parse as V3Overrides, only for the exact bytes
they were reviewed against. Possessions come from the unchanged original
engine.

    python -m pbpstats.data_loader.stats_nba_v3.web 0022500001 -o game.json
"""

import argparse
import hashlib
import json
from pathlib import Path

import requests

from pbpstats import REQUEST_TIMEOUT

from .enhanced_pbp.loader import boxscore_context, load_boxscore, with_evidence
from .file_loader import SavedResponse
from .overrides import REVIEWED_CORRECTIONS, reviewed_overrides
from .possessions.loader import StatsNbaV3PossessionLoader
from .web_loader import HEADERS, get, stats_url


class RecordedResponse:
    """A response already in hand, as a source loader."""

    file_directory = None

    def __init__(self, content):
        self.content = content

    def load_data(self, game_id):
        return self.content


class RecordedGame(RecordedResponse):
    """A game's responses already in hand, as the source loader of
    StatsNbaV3PossessionLoader and StatsNbaV3EnhancedPbpLoader (see load_game).

    ``fetch_boxscore`` and ``fetch_live`` supply recorded evidence; None means
    the parse rejects a game that needs it.
    """

    def __init__(
        self,
        pbp_bytes,
        box_bytes,
        source,
        fetch_boxscore=None,
        aliases=None,
        overrides=None,
        fetch_live=None,
    ):
        super().__init__(pbp_bytes)
        self.source = source
        self.boxscore_source_loader = RecordedResponse(box_bytes)
        self.enhanced_pbp_source_loader = self
        self.load_starter_boxscore = fetch_boxscore
        self.load_live = fetch_live
        self.aliases, self.overrides = aliases, overrides

    def load_overrides(self, game_id, pbp_bytes):
        return self.overrides

    def load_aliases(self, boxscore):
        return self.aliases


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
    """The context StatsNbaV3EnhancedPbpLoader takes from a box score response.

    Teams and the named roster from the official box score, bound to the PBP;
    see boxscore_context.
    """
    boxscore = load_boxscore(game_id, RecordedResponse(box_bytes))
    return boxscore_context(game_id, pbp_bytes, boxscore, source, aliases)


def parse_possessions(
    pbp_bytes, context, fetch_boxscore=None, overrides=None, fetch_live=None
):
    """Parse V3 bytes into possessions with the original engine, for a given context.

    When the original's starter inference falls back to its period-start box
    score request, ``fetch_boxscore(period, url, params)`` must return that
    response; it is recorded as V3StarterBoxscore evidence. Without it, the
    V3EvidenceRequired error names the exact request instead. A jump ball V3
    leaves undecided likewise needs ``fetch_live(url)`` to return the live
    play-by-play, recorded as V3JumpBallEvidence.
    ``overrides`` supplies reviewed corrections (see reviewed_overrides).
    """
    return with_evidence(
        lambda boxscores, jump_balls: StatsNbaV3PossessionLoader.from_context(
            pbp_bytes,
            context,
            overrides=overrides,
            starter_boxscores=boxscores,
            jump_balls=jump_balls,
        ),
        context,
        fetch_boxscore,
        fetch_live,
    )


def load_game(
    game_id,
    pbp_bytes,
    box_bytes,
    source,
    fetch_boxscore=None,
    aliases=None,
    overrides=None,
    fetch_live=None,
):
    """Possessions from a game's play-by-play and box score responses.

    StatsNbaV3PossessionLoader reads them as its source loader's. Starters
    come from the original's own inference. Only if a name is ambiguous, such
    as a tip to one of two same-named players, are the box score's
    first-period starter markers supplied as recorded on-court evidence; the
    loader checks each such resolution against the original's lineup. The
    loader's context then lists those starters. A jump ball that stays
    undecided, including a team-won one, is completed from the live
    play-by-play that ``fetch_live(url)`` returns.
    """
    return StatsNbaV3PossessionLoader(
        game_id,
        RecordedGame(
            pbp_bytes, box_bytes, source, fetch_boxscore, aliases, overrides, fetch_live
        ),
    )


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


def boxscore_players(box_bytes):
    """Official personIds in a box score; empty if malformed, which parsing reports."""
    try:
        box = json.loads(box_bytes)["boxScoreTraditional"]
        return {
            p["personId"] for side in ("homeTeam", "awayTeam") for p in box[side]["players"]
        }
    except (ValueError, KeyError, TypeError):
        return set()


def save_game(
    game_id,
    output,
    *,
    raw=None,
    session=None,
    responses=None,
    aliases=None,
    skip_absent_aliases=False,
    indent=4,
):
    """Parse one game into possessions and write them to ``output`` as JSON.

    ``raw`` reuses saved responses in fetch_game's shape; otherwise they are
    fetched with ``session``, as is any period-start box score the original's
    starter recovery requests and any live play-by-play an undecided jump ball
    needs. Offline, ``raw["live"]`` (with ``raw["live_url"]``) supplies a saved
    live response. ``responses`` keeps the raw responses in that directory,
    also for a rejected game. An alias for a player outside the box score is an
    error unless ``skip_absent_aliases``, which batches use. Reviewed
    corrections apply only to their reviewed bytes. Returns the loader.
    """
    offline = raw is not None
    if not offline:
        raw = fetch_game(game_id, session)
    aliases = dict(aliases or {})
    if skip_absent_aliases:
        present = boxscore_players(raw["boxscore"])
        aliases = {person: names for person, names in aliases.items() if person in present}
    fetched, live = {}, []

    def fetch_boxscore(period, url, params):
        fetched[period] = get(url, params, session)
        return fetched[period]

    def fetch_live(url):
        if offline:
            response = SavedResponse(raw["live"], raw.get("live_url") or url)
        else:
            response = (session or requests).get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
        live.append(response)
        return response

    overrides = None
    try:
        overrides = reviewed_overrides(game_id, raw["pbp"])
        loader = load_game(
            game_id,
            raw["pbp"],
            raw["boxscore"],
            raw["pbp_url"] + " ; " + raw["boxscore_url"],
            fetch_boxscore=None if offline else fetch_boxscore,
            aliases=aliases,
            overrides=overrides,
            fetch_live=fetch_live if not offline or raw.get("live") else None,
        )
    finally:
        if responses:
            responses.mkdir(parents=True, exist_ok=True)
            (responses / "playbyplayv3.json").write_bytes(raw["pbp"])
            (responses / "boxscoretraditionalv3.json").write_bytes(raw["boxscore"])
            for period, response in fetched.items():
                name = "boxscoretraditionalv2_period_{}.json".format(period)
                (responses / name).write_bytes(response.content)
            if live:
                (responses / "playbyplay_live.json").write_bytes(live[0].content)

    def digest(data):
        return hashlib.sha256(data).hexdigest()

    sources = dict(
        pbp=dict(url=raw["pbp_url"], sha256=digest(raw["pbp"])),
        boxscore=dict(url=raw["boxscore_url"], sha256=digest(raw["boxscore"])),
        starter_boxscores={
            str(period): dict(url=r.url, status=r.status_code, sha256=digest(r.content))
            for period, r in fetched.items()
        },
        live_play_by_play=(
            dict(url=live[0].url, sha256=digest(live[0].content)) if live else None
        ),
        reviewed_aliases={str(k): v for k, v in aliases.items()},
        reviewed_correction=overrides.source if overrides else None,
    )
    temporary = output.with_name(output.name + ".tmp")  # never a partial file
    # Bytes keep LF line endings on every platform and Python version.
    temporary.write_bytes(
        json.dumps(possessions_json(loader, sources), indent=indent).encode("utf-8")
    )
    temporary.replace(output)
    return loader


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
        "--live", type=Path, help="Saved live play-by-play response, used offline"
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
    raw = None
    if args.pbp or args.boxscore:
        if not (args.pbp and args.boxscore):
            parser.error("--pbp and --boxscore are used together")
        raw = dict(
            pbp=args.pbp.read_bytes(),
            boxscore=args.boxscore.read_bytes(),
            pbp_url=str(args.pbp),
            boxscore_url=str(args.boxscore),
        )
        if args.live:
            raw.update(live=args.live.read_bytes(), live_url=str(args.live))
    elif args.live:
        parser.error("--live is used with --pbp and --boxscore")
    output = args.output or Path(args.game_id + ".possessions.json")
    loader = save_game(
        args.game_id,
        output,
        raw=raw,
        session=requests.Session(),
        responses=args.save_responses,
        aliases=aliases,
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
