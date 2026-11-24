"""Fetch a player's recent games from the public Chess.com and Lichess APIs.

Both are open, read-only and need no login. Only the username goes out, in the URL. Every function
takes `get` so tests run without a network: get(url, accept) -> text.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from datetime import UTC, datetime

import chess.pgn

PLATFORMS = ("chesscom", "lichess")
USERNAME = re.compile(r"^[A-Za-z0-9_-]{2,30}$")
USER_AGENT = "chess-coach (personal, non-commercial)"
MAX_GAMES = 1000  # a safety cap on one sync

Get = Callable[[str, str], str]


class SourceError(RuntimeError):
    """The platform could not be reached or answered with something unusable."""


class NoSuchUser(SourceError):
    pass


def http_get(url: str, accept: str = "application/json") -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise NoSuchUser(url) from e
        raise SourceError(f"{e.code} from {urllib.parse.urlsplit(url).netloc}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise SourceError(f"could not reach {urllib.parse.urlsplit(url).netloc}") from e


def check_username(platform: str, username: str) -> str:
    if platform not in PLATFORMS:
        raise ValueError("platform must be chesscom or lichess")
    if not USERNAME.match(username):
        raise ValueError("usernames are 2 to 30 letters, digits, underscores or hyphens")
    return username


def verify(platform: str, username: str, get: Get = http_get) -> None:
    """Raise NoSuchUser if the account does not exist."""
    u = urllib.parse.quote(check_username(platform, username))
    url = (f"https://api.chess.com/pub/player/{u}" if platform == "chesscom"
           else f"https://lichess.org/api/user/{u}")
    get(url, "application/json")


def chesscom_pgns(username: str, since: datetime, get: Get = http_get) -> Iterator[str]:
    """Standard-chess games since `since`, one PGN each, with clock comments."""
    u = urllib.parse.quote(check_username("chesscom", username))
    try:
        archives = json.loads(get(f"https://api.chess.com/pub/player/{u}/games/archives",
                                  "application/json"))["archives"]
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        raise SourceError("unexpected answer from Chess.com") from e
    floor = (since.year, since.month)
    count = 0
    for url in sorted(archives):
        m = re.search(r"/(\d{4})/(\d{2})$", url)
        if not m or (int(m[1]), int(m[2])) < floor:
            continue
        try:
            games = json.loads(get(url, "application/json"))["games"]
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            raise SourceError("unexpected answer from Chess.com") from e
        for g in games:
            if g.get("rules", "chess") != "chess" or not g.get("pgn"):
                continue
            if g.get("end_time", 0) < since.timestamp():
                continue
            yield g["pgn"]
            count += 1
            if count >= MAX_GAMES:
                return


def lichess_pgns(username: str, since: datetime, get: Get = http_get) -> Iterator[str]:
    u = urllib.parse.quote(check_username("lichess", username))
    query = urllib.parse.urlencode({
        "since": int(since.timestamp() * 1000), "max": MAX_GAMES, "clocks": "true",
        "opening": "true", "moves": "true", "tags": "true",
        "perfType": "ultraBullet,bullet,blitz,rapid,classical,correspondence",  # no variants
    })
    text = get(f"https://lichess.org/api/games/user/{u}?{query}", "application/x-chess-pgn")
    yield from split_pgns(text)


def split_pgns(text: str) -> Iterator[str]:
    import io
    handle = io.StringIO(text)
    while (game := chess.pgn.read_game(handle)) is not None:
        yield game.accept(chess.pgn.StringExporter(headers=True, variations=False, comments=False))


def fetch(platform: str, username: str, since: datetime, get: Get = http_get) -> list[str]:
    fn = chesscom_pgns if platform == "chesscom" else lichess_pgns
    return list(fn(username, since, get))


def months_ago(months: int, now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    y, m = divmod(now.year * 12 + now.month - 1 - months, 12)
    return now.replace(year=y, month=m + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
