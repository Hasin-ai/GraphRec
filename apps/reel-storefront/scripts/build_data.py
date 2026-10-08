"""Build the storefront's local data files from the real MovieLens artifacts.

Outputs (all derived, nothing invented):

* ``data/films.json``    - the 7,951 films in the DGSR vocabulary: movieId, title,
  year, genres (MovieLens labels), community tags (``tags.csv``, see film_tags.py),
  tmdb/imdb ids, popularity = interactions in the training cohort. ``poster_url`` is copied only if an enriched file provides one.
* ``data/personas.json`` - the demo shoppers: real training users, their full
  chronological history (movieId, unix time) exactly as in ``interactions.npz``.
* ``data/model_card.json`` - checkpoint identity and offline metrics with their protocol.

Run from this folder:  python scripts/build_data.py
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path

import numpy as np

from film_tags import film_tags

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[1]
DEFAULT_ARTIFACT = REPO / "model_artifacts" / "dgsr_movielens_32m"
DEFAULT_ML = REPO / "movielens" / "ml-32m" / "ml-32m"

#: Real training users chosen for coherent recent histories (see the design doc, section 4.5).
PERSONAS = [
    {"key": "maya", "name": "Maya", "user_id": "184387", "color": "#C8553D",
     "blurb": "Classic Disney and family animation (MovieLens user 184387)"},
    {"key": "theo", "name": "Theo", "user_id": "48173", "color": "#2F6690",
     "blurb": "Modern sci-fi and superhero films (MovieLens user 48173)"},
    {"key": "sam", "name": "Sam", "user_id": "150751", "color": "#3A7D44",
     "blurb": "1990s action thrillers (MovieLens user 150751)"},
]

YEAR = re.compile(r"\((\d{4})\)\s*$")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument("--movielens", type=Path, default=DEFAULT_ML)
    parser.add_argument("--posters", type=Path, default=None, help="optional JSON {movieId: poster_url}")
    args = parser.parse_args()

    maps = json.loads((args.artifact / "id_maps.json").read_text(encoding="utf-8"))
    arrays = np.load(args.artifact / "interactions.npz", allow_pickle=False)
    users, items, times = arrays["users"], arrays["items"], arrays["times"]
    item_ids, user_ids = maps["item_ids"], maps["user_ids"]

    movies = {r["movieId"]: r for r in csv.DictReader((args.movielens / "movies.csv").open(encoding="utf-8"))}
    links = {r["movieId"]: r for r in csv.DictReader((args.movielens / "links.csv").open(encoding="utf-8"))}
    posters = json.loads(args.posters.read_text(encoding="utf-8")) if args.posters else {}
    popularity = Counter(int(i) for i in items)

    films = []
    for index, movie_id in enumerate(item_ids):
        row = movies[movie_id]
        title = row["title"].strip()
        match = YEAR.search(title)
        link = links.get(movie_id, {})
        films.append({
            "id": movie_id,
            "title": YEAR.sub("", title).strip() if match else title,
            "year": int(match.group(1)) if match else None,
            "genres": [g for g in row["genres"].split("|") if g and g != "(no genres listed)"],
            "popularity": popularity[index],
            "tmdbId": link.get("tmdbId") or None,
            "imdbId": link.get("imdbId") or None,
            "posterUrl": posters.get(movie_id),
        })
    tags = film_tags(args.movielens / "tags.csv", films)
    for f in films:
        f["tags"] = tags.get(f["id"], [])
    rank = {f["id"]: r for r, f in enumerate(sorted(films, key=lambda f: (-f["popularity"], f["id"])), start=1)}
    for f in films:
        f["popularityRank"] = rank[f["id"]]

    by_user = {u: i for i, u in enumerate(user_ids)}
    personas = []
    for p in PERSONAS:
        idx = by_user[p["user_id"]]
        rows = np.flatnonzero(users == idx)
        # Same order the API uses: occurred_at, then insertion (row) order.
        rows = rows[np.lexsort((rows, times[rows]))]
        history = [{"filmId": item_ids[int(items[r])], "time": int(times[r])} for r in rows]
        personas.append({**p, "history": history})

    final = json.loads((args.artifact / "final_metrics.json").read_text(encoding="utf-8"))["validation"]
    identity = json.loads((args.artifact / "tenant_identity.json").read_text(encoding="utf-8"))
    config = json.loads((args.artifact / "config.json").read_text(encoding="utf-8"))
    card = {
        "dataset": identity.get("public_reference_dataset", "MovieLens 32M"),
        "checkpointSha256": identity.get("checkpoint_sha256"),
        "users": len(user_ids),
        "films": len(item_ids),
        "interactions": int(len(users)),
        "embeddingDim": config["embedding_dim"],
        "layers": config["layers"],
        "recentItems": config["recent_items"],
        "itemNeighborLimit": config["item_neighbor_limit"],
        "metrics": [
            {"protocol": "Sampled: 1 target vs 100 random negatives", "source": "final_metrics.json",
             "hit10": round(final["Hit@10"], 4), "ndcg10": round(final["NDCG@10"], 4),
             "note": "Popularity alone reaches 0.576 Hit@10 on this protocol."},
            {"protocol": "Full catalogue (~7,803 candidates)", "source": "DGSR_MovieLens_inference_report.md section 5.1",
             "recall10": 0.1245, "mrr": 0.0582,
             "note": "Popularity baseline 3.35% Recall@10."},
        ],
    }

    out = HERE / "data"
    out.mkdir(exist_ok=True)
    (out / "films.json").write_text(json.dumps(films, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (out / "personas.json").write_text(json.dumps(personas, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "model_card.json").write_text(json.dumps(card, indent=2), encoding="utf-8")
    print(f"films {len(films)} | personas " + ", ".join(f"{p['name']} ({len(p['history'])} events)" for p in personas))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
