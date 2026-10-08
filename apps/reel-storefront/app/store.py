"""Local, read-only film metadata and shopper state.

* ``Films``  - the 7,951 films of the DGSR vocabulary (real MovieLens metadata,
  built by scripts/build_data.py). Used for browsing and to hydrate ranked IDs.
* ``Shoppers`` - the demo personas (real training users) plus "anonymous".
* ``LiveLog`` - every event this storefront sent to GraphRec, persisted to
  ``state/live_events.jsonl`` so the Sequence tab survives restarts. It mirrors
  what the API's ``_stored_history`` reads: seeded training history + live events.
"""

from __future__ import annotations

from collections import OrderedDict

import json
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

#: Tags shown on a film's page but never promoted as storefront themes.
ADVISORY_PREFIXES = ("nudity", "sex", "rape", "gore", "violence", "suicide", "drugs", "incest", "torture")

#: DGSR's root window (``recent_items`` in the checkpoint config).
WINDOW = 20


@dataclass(frozen=True)
class Persona:
    key: str
    name: str
    blurb: str
    color: str
    user_id: Optional[str]
    history: Tuple[Tuple[str, int], ...]


ANONYMOUS = Persona("anon", "Anonymous visitor", "No account: session-based recommendations", "#6B6B6B", None, ())


class Films:
    def __init__(self, path: Path) -> None:
        self.items: List[dict] = json.loads(path.read_text(encoding="utf-8"))
        self.by_id: Dict[str, dict] = {f["id"]: f for f in self.items}
        counts: Dict[str, int] = {}
        for f in self.items:
            for g in f["genres"]:
                counts[g] = counts.get(g, 0) + 1
        self.genres = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        tag_counts: Dict[str, int] = {}
        for f in self.items:
            f.setdefault("tags", [])
            for t in f["tags"]:
                tag_counts[t] = tag_counts.get(t, 0) + 1
        # Catalogue-wide theme list: content advisories stay on the film page, not on the storefront.
        self.tags = sorted(((t, n) for t, n in tag_counts.items() if not t.startswith(ADVISORY_PREFIXES)),
                           key=lambda kv: (-kv[1], kv[0]))
        self.by_popularity = sorted(self.items, key=lambda f: f["popularityRank"])
        self._orders = {
            "popular": self.by_popularity,
            "newest": sorted(self.by_popularity, key=lambda f: -(f["year"] or 0)),
            "oldest": sorted(self.by_popularity, key=lambda f: f["year"] or 9999),
            "title": sorted(self.items, key=lambda f: _sort_title(f["title"])),
        }

    def get(self, film_id: str) -> Optional[dict]:
        return self.by_id.get(film_id)

    def browse(self, *, genre: Optional[str], query: Optional[str], offset: int, limit: int,
               tag: Optional[str] = None, sort: str = "popular") -> Tuple[List[dict], int]:
        """Filter by genre, tag and a free-text query; the query matches titles and tags."""

        rows = self._orders.get(sort, self.by_popularity)
        if genre:
            rows = [f for f in rows if genre in f["genres"]]
        if tag:
            t = tag.lower()
            rows = [f for f in rows if t in f["tags"]]
        if query:
            q = query.lower()
            title_hits = [f for f in rows if q in f["title"].lower()]
            seen = {f["id"] for f in title_hits}
            # Title matches first, then films whose tags match (e.g. "kubrick", "pixar", "time travel").
            rows = title_hits + [f for f in rows if f["id"] not in seen and any(q in t for t in f["tags"])]
        return rows[offset : offset + limit], len(rows)


_ARTICLE = re.compile(r"^(.*), (The|A|An|Les|La|Le|L'|Il|Das|Der|Die|El)$")


def display_title(title: str) -> str:
    """MovieLens stores "Shining, The"; shoppers read "The Shining"."""

    m = _ARTICLE.match(title)
    return f"{m.group(2)}{'' if m.group(2).endswith(chr(39)) else ' '}{m.group(1)}" if m else title


def _sort_title(title: str) -> str:
    """Sort on the MovieLens form ("Shining, The"), so leading articles are ignored like in a shop."""

    return title.lower()


class Shoppers:
    def __init__(self, path: Path) -> None:
        raw = json.loads(path.read_text(encoding="utf-8"))
        self.personas: Dict[str, Persona] = {"anon": ANONYMOUS}
        for p in raw:
            self.personas[p["key"]] = Persona(
                p["key"], p["name"], p["blurb"], p["color"], p["user_id"],
                tuple((h["filmId"], int(h["time"])) for h in p["history"]),
            )

    def get(self, key: Optional[str], session_id: Optional[str] = None) -> Persona:
        k = (key or "").strip().lower()
        if not k or k == "anon":
            return ANONYMOUS
        if k in self.personas:
            return self.personas[k]
        if k == "new":
            uid = f"user_new_{session_id[-8:]}" if session_id else f"user_new_{int(time.time())}"
            return Persona(
                "new", "New visitor", "Cold start: brand-new user id on demand",
                "#8B5CF6", uid, (),
            )
        if k.startswith("user:") or (k.isdigit() and len(k) <= 10):
            uid = k.split(":")[-1]
            return Persona(
                f"user:{uid}", f"User {uid}", f"MovieLens user {uid}",
                "#2F6690", uid, (),
            )
        return ANONYMOUS


class LiveLog:
    """Append-only record of events this storefront submitted, keyed by shopper."""

    def __init__(self, state_dir: Path) -> None:
        state_dir.mkdir(parents=True, exist_ok=True)
        self.path = state_dir / "live_events.jsonl"
        self._lock = threading.Lock()
        self._rows: List[dict] = []
        if self.path.is_file():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self._rows.append(json.loads(line))

    def add(self, row: dict) -> None:
        with self._lock:
            self._rows.append(row)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row) + "\n")

    def for_shopper(self, shopper: str) -> List[dict]:
        return [r for r in self._rows if r["shopper"] == shopper]

    def last(self, shopper: str) -> Optional[dict]:
        rows = self.for_shopper(shopper)
        return rows[-1] if rows else None


def shopper_key(persona: Persona, session_id: str) -> str:
    """Identified personas share one history across sessions; anonymous history is per session."""

    return persona.user_id and f"user:{persona.user_id}" or f"session:{session_id}"


def history_for(persona: Persona, live: Sequence[dict]) -> List[dict]:
    """Chronological history as the API will read it: seeded training events, then live ones.

    Only positive product events count (mirrors HISTORY_EVENT_TYPES in the API).
    """

    rows = [{"filmId": f, "time": t, "origin": "training", "eventType": "rating"} for f, t in persona.history]
    for r in live:
        if r.get("counted", True) and not r.get("duplicate"):
            rows.append({"filmId": r["filmId"], "time": r["time"], "origin": "live", "eventType": r["eventType"], "eventId": r["eventId"]})
    rows.sort(key=lambda r: r["time"])
    return rows


class BoundedDict(OrderedDict):
    """A dict that forgets its least recently written keys beyond ``limit``.

    Per-visitor state (previous lists, impression ids) is created by every anonymous
    session and every film page; without a bound it grows for the life of the process.
    """

    def __init__(self, limit: int = 10_000) -> None:
        super().__init__()
        self.limit = limit

    def __setitem__(self, key, value) -> None:  # noqa: ANN001
        if key in self:
            self.move_to_end(key)
        super().__setitem__(key, value)
        while len(self) > self.limit:
            self.popitem(last=False)


class LastLists:
    """The previous ranked list per (shopper, shelf), for the before/after diff."""

    def __init__(self, limit: int = 10_000) -> None:
        self._lists: Dict[Tuple[str, str], List[str]] = BoundedDict(limit)

    def swap(self, shopper: str, shelf: str, ids: List[str]) -> Optional[List[str]]:
        previous = self._lists.get((shopper, shelf))
        self._lists[(shopper, shelf)] = ids
        return previous


def now_seconds() -> int:
    return int(time.time())
