"""Community tags for each film, from MovieLens ``tags.csv`` (nothing invented).

A tag is kept for a film when at least ``MIN_USERS`` different people applied it.
Tags are ranked by how many people used them. Dropped:

* bookkeeping tags people use for their own lists ("dvd", "in netflix queue", "seen it"),
* bare verdicts that describe the viewer more than the film ("boring", "overrated"),
* exact repeats of the film's MovieLens genres (the genre chips already show those),
* tags that are numbers or longer than ``MAX_LEN`` characters.

Usage (patches data/films.json in place, keeps every other field):
    python scripts/film_tags.py [--movielens ../../movielens/ml-32m/ml-32m]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Set

HERE = Path(__file__).resolve().parents[1]
DEFAULT_ML = HERE.parents[1] / "movielens" / "ml-32m" / "ml-32m"

MIN_USERS = 2
MAX_TAGS = 8
MAX_LEN = 30

NOISE = {
    # personal bookkeeping
    "dvd", "on dvd", "owned", "own", "seen", "seen it", "seen more than once", "watched", "to see", "to watch",
    "netflix", "in netflix queue", "netflix queue", "netflix finland", "tivo", "my movies", "dvd-video", "bd-r",
    "imdb top 250", "afi 100", "criterion", "library", "watch again", "want to see again", "clv", "betamax",
    "erlend's dvds", "might like", "need to see", "have", "should see", "re-watch", "favorite", "favorites",
    "my favorite", "my favorites", "r", "pg", "pg-13", "1001 movies you must see before you die",
    # verdicts about the viewer, not the film
    "boring", "overrated", "predictable", "bad", "awful", "stupid", "terrible", "waste of time", "bad acting",
    "not funny", "bad plot", "bad movie", "worst movie ever", "disappointing", "slow", "long", "too long",
    "pointless", "good", "great", "great movie", "excellent", "masterpiece", "good movie", "ok", "meh",
    "underrated", "must see", "classic", "seen at the cinema",
}
NUMERIC = re.compile(r"^[\d\s.,:/-]+$")


def keep(tag: str, genres: Set[str]) -> bool:
    return bool(tag) and len(tag) <= MAX_LEN and tag not in NOISE and tag not in genres and not NUMERIC.match(tag)


def genre_words(genres: Iterable[str]) -> Set[str]:
    """Lower-case genre labels plus their common spellings ("Sci-Fi" -> "sci-fi", "sci fi", "scifi")."""

    words = {g.lower() for g in genres}
    for g in list(words):
        words |= {g.replace("-", " "), g.replace("-", "")}
    return words


def film_tags(tags_csv: Path, films: Iterable[dict]) -> Dict[str, List[str]]:
    """{movieId: [tag, ...]} ranked by distinct taggers, for the given films only."""

    genres = {f["id"]: genre_words(f.get("genres", [])) for f in films}
    people: Dict[str, Dict[str, Set[str]]] = defaultdict(lambda: defaultdict(set))
    with tags_csv.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            movie = row["movieId"]
            if movie in genres:
                people[movie][" ".join(row["tag"].lower().split())].add(row["userId"])
    out: Dict[str, List[str]] = {}
    for movie, by_tag in people.items():
        ranked = sorted(((len(users), tag) for tag, users in by_tag.items()
                         if len(users) >= MIN_USERS and keep(tag, genres[movie])), key=lambda t: (-t[0], t[1]))
        if ranked:
            out[movie] = [tag for _, tag in ranked[:MAX_TAGS]]
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--movielens", type=Path, default=DEFAULT_ML)
    parser.add_argument("--films", type=Path, default=HERE / "data" / "films.json")
    args = parser.parse_args()
    films = json.loads(args.films.read_text(encoding="utf-8"))
    tags = film_tags(args.movielens / "tags.csv", films)
    for f in films:
        f["tags"] = tags.get(f["id"], [])
    args.films.write_text(json.dumps(films, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tagged = sum(1 for f in films if f["tags"])
    print(f"tags: {tagged:,} of {len(films):,} films have at least one community tag")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
