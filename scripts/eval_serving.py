"""Offline replay: glass-box serving vs a plain DGSR Top-K baseline on an artifact.

For a sample of users, each user's last interaction is held out. Both pipelines
receive the same DGSR query vector (built from the earlier interactions) and
rank the FULL catalogue (no sampled negatives), excluding items already seen:

* baseline  - DGSR Top-K in score order (the single-source funnel the
              glass-box pipeline replaced);
* glassbox  - the four sources, blended score and MMR from
              ``graphrec_core.serving`` (popularity = interaction counts in the
              artifact, category = first genre from films.json when given).

Reported per pipeline: Hit/Recall@K, NDCG@K, catalogue coverage, intra-list
diversity (1 - mean pairwise cosine of item embeddings) and, with --films,
distinct genres per list. Both lists come from the same model; differences are
the pipeline's.

    python scripts/eval_serving.py model_artifacts/dgsr_movielens_32m \
        --films apps/reel-storefront/data/films.json --users 500 --diversity 0.25
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from graphrec_core.dgsr.serving import HistoryEvent, load_artifact  # noqa: E402
from graphrec_core.serving.ranking import (  # noqa: E402
    NEIGHBOR_ANCHORS, QUOTA_CATEGORY, QUOTA_NEIGHBORS, QUOTA_PERSONALIZED, QUOTA_TRENDING,
    Candidate, combine_scores, mmr_order, relevance_order,
)


def ndcg(rank: int | None) -> float:
    return 0.0 if rank is None else 1.0 / math.log2(rank + 1)


def ild(ids: list[int], table: np.ndarray) -> float:
    if len(ids) < 2:
        return 0.0
    v = table[ids]
    sims = v @ v.T
    n = len(ids)
    return float(1.0 - (sims.sum() - np.trace(sims)) / (n * (n - 1)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("artifact")
    ap.add_argument("--films", default=None)
    ap.add_argument("--users", type=int, default=500)
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--diversity", type=float, default=0.25)
    ap.add_argument("--min-history", type=int, default=5)
    ap.add_argument("--seed", type=int, default=13)
    ap.add_argument("--out", default=None, help="write the summary JSON here")
    args = ap.parse_args()

    art = load_artifact(args.artifact)
    data = art.data
    k = args.k
    raw = art.item_embeddings()
    table = raw / np.maximum(np.linalg.norm(raw, axis=1, keepdims=True), 1e-12)
    popularity = np.bincount(data.items, minlength=data.num_items).astype(np.float64)
    trending_order = np.lexsort((np.arange(data.num_items), -popularity))
    category: dict[int, str] = {}
    if args.films:
        for f in json.loads(Path(args.films).read_text(encoding="utf-8")):
            idx = art.item_index(str(f["id"]))
            if idx is not None and f.get("genres"):
                category[idx] = f["genres"][0]
    by_category: dict[str, np.ndarray] = {}
    for cat in set(category.values()):
        members = np.array([i for i, c in category.items() if c == cat], dtype=np.int64)
        by_category[cat] = members[np.lexsort((members, -popularity[members]))]

    rng = np.random.default_rng(args.seed)
    eligible_users = [u for u in range(data.num_users) if len(data.by_user[u]) > args.min_history]
    users = rng.choice(eligible_users, size=min(args.users, len(eligible_users)), replace=False)

    stats = {name: {"hit": 0, "ndcg": 0.0, "ild": 0.0, "genres": 0.0, "items": set()} for name in ("baseline", "glassbox")}
    started = time.perf_counter()
    for u in users:
        rows = data.by_user[int(u)]
        items, times = data.items[rows], data.times[rows]
        target = int(items[-1])
        history = [HistoryEvent(int(i), int(t)) for i, t in zip(items[:-1], times[:-1])]
        query = art.encode_history(history, user=None).query
        seen = list(dict.fromkeys(int(i) for i in items[:-1]))
        scores = art.score(query)
        masked = scores.copy()
        masked[seen] = -np.inf
        seen_set = set(seen)

        # baseline: Top-K by score
        baseline = [int(i) for i in np.lexsort((np.arange(len(masked)), -masked))[:k]]

        # glassbox: same sources and maths as graphrec_core.serving.pipeline
        cands: dict[int, Candidate] = {}

        def add(source: str, ids, anchors=None) -> None:
            for rank, i in enumerate(ids, start=1):
                c = cands.setdefault(int(i), Candidate(external_id=str(int(i)), item_index=int(i)))
                c.add_source(source, rank, anchors[rank - 1] if anchors else None)

        add("dgsr_personalized", np.lexsort((np.arange(len(masked)), -masked))[:QUOTA_PERSONALIZED])
        anchors = []
        for i in reversed(items[:-1].tolist()):
            if i not in anchors:
                anchors.append(i)
            if len(anchors) == NEIGHBOR_ANCHORS:
                break
        per = QUOTA_NEIGHBORS // len(anchors)
        pairs = []
        lists = []
        for a in anchors:
            sims = table @ table[a]
            sims[seen] = -np.inf
            lists.append([(int(i), a) for i in np.lexsort((np.arange(len(sims)), -sims))[:per]])
        got = set()
        for r in range(per):
            for lst in lists:
                if r < len(lst) and lst[r][0] not in got:
                    got.add(lst[r][0])
                    pairs.append(lst[r])
        add("session_neighbors", [p for p, _ in pairs], [str(a) for _, a in pairs])
        cats = list(dict.fromkeys(category[a] for a in anchors if a in category))[:NEIGHBOR_ANCHORS]
        cat_pool = [i for c in cats for i in by_category.get(c, [])]
        cat_pool = sorted(set(cat_pool) - seen_set, key=lambda i: (-popularity[i], i))[:QUOTA_CATEGORY]
        add("popular_in_category", cat_pool)
        add("trending", [i for i in trending_order[: QUOTA_TRENDING + len(seen)] if i not in seen_set][:QUOTA_TRENDING])
        for c in cands.values():
            c.model_score = float(scores[c.item_index])
            c.popularity = float(popularity[c.item_index])
        combine_scores(list(cands.values()))
        ordered = relevance_order(list(cands.values()))
        vectors = {c.external_id: table[c.item_index] for c in ordered}
        glass = [int(c.external_id) for c in mmr_order(ordered, vectors, diversity=args.diversity, limit=k)]

        for name, ranked in (("baseline", baseline), ("glassbox", glass)):
            s = stats[name]
            rank = ranked.index(target) + 1 if target in ranked else None
            s["hit"] += rank is not None
            s["ndcg"] += ndcg(rank)
            s["ild"] += ild(ranked, table)
            s["genres"] += len({category[i] for i in ranked if i in category})
            s["items"].update(ranked)

    n = len(users)
    summary = {"artifact": str(args.artifact), "users": n, "k": k, "diversity": args.diversity,
               "catalogue": data.num_items, "seconds": round(time.perf_counter() - started, 1), "pipelines": {}}
    for name, s in stats.items():
        summary["pipelines"][name] = {
            f"Recall@{k}": round(s["hit"] / n, 4),
            f"NDCG@{k}": round(s["ndcg"] / n, 4),
            "coverage": round(len(s["items"]) / data.num_items, 4),
            "intra_list_diversity": round(s["ild"] / n, 4),
            **({"genres_per_list": round(s["genres"] / n, 2)} if category else {}),
        }
    text = json.dumps(summary, indent=2)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
