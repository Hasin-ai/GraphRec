# Phase 8 — DGSR, offline

**Scope (BUILD_PROMPT L650):** `FeatureBuilder` · graph construction + bounded
2-hop sampling · DGSR: GNN pathway, sequence pathway, gated fusion · training
loop, negative sampling, BPR, checkpointing · temporal leave-last-out split ·
Recall@10 / HR@10 / NDCG@10 / coverage · popularity baseline · fixture dataset
with a deterministic seed.

**Gate:** none. The next gate is D4/D8 before Phase 10.

**Run offline-first**, as BUILD_PROMPT asks: nothing in this phase touches the
database, the job queue or object storage. There is no `AsyncSession` anywhere
under `graphrec/ml/`, and that is a property Phase 9 has to preserve when it
wraps the loop in a worker.

## 1. Built

`graphrec/ml/`, 20 modules, ~2,650 lines, in the layout BACKEND_PLAN L1745 sets
out:

* **`features/builder.py`** — `Interaction`, `Product`, `Dataset`,
  `FeatureBuilder`. The one place raw rows become model input, shared by
  snapshot generation, evaluation replay and (from Phase 11) inference. Pure,
  deterministic, numpy-only. Index assignment is by first appearance in a
  deterministically sorted stream, so two runs over the same rows produce the
  same integers and a checkpoint means something. Event weights
  (`purchase` 5, `add_to_cart` 3, `view` 1, `remove_from_cart` −2), price
  buckets, ordinal availability, exponential recency against a *supplied*
  reference time rather than the clock.
* **`graph/build.py`** — `InteractionGraph`, both directions in CSR, edges
  carrying time and weight, each node's edges oldest-first. Built from a
  training `Dataset` and nothing else; there is no parameter that would let the
  held-out rows in.
* **`graph/sample.py`** — bounded 2-hop sampling, item → user → item, fixed
  shape `(n, f1)` and `(n, f1, f2)` with `-1` padding and boolean masks. Recency
  bias by default, uniform available, every draw through a caller-supplied
  `numpy.random.Generator`.
* **`model/dgsr.py`** — `ItemEncoder`, `GraphPathway` (two masked means),
  `SequencePathway` (self-attention, left-padded, read out at the last
  position), `GatedFusion` (per-element sigmoid gate), and `DGSR` scoring by dot
  product so that Phase 10 can export an item matrix and Phase 11 can do top-K
  as one matrix multiply.
* **`model/loss.py`** — BPR via `softplus(-Δ)`, interaction-weighted, negatives
  averaged rather than summed; batch-local L2.
* **`train/negatives.py`** — uniform and popularity-biased (`count ** 0.75`,
  `+1` so cold items are reachable), history rejection bounded at four retries.
* **`train/loop.py`** — examples are *positions*, not users; shuffle, sample,
  score, step; validation each epoch; early stopping on validation NDCG; the
  best model returned rather than the last. Two seams and only two:
  `on_epoch` (Phase 9's progress) and `should_stop` (Phase 9's cancellation).
* **`train/checkpoint.py`** — safetensors, atomic rename, weights + Adam state +
  both RNGs, config checked against the model rather than used to build it.
* **`eval/split.py`** — the temporal leave-last-out split and
  `Split.assert_no_leakage`.
* **`eval/metrics.py`**, **`eval/baseline.py`**, **`eval/evaluate.py`** — the four
  metrics, the popularity ranker, and full-catalogue ranking under one shared
  protocol.
* **`fixtures/synthetic.py`** — a seeded tenant with latent per-user category
  affinity.
* **`scripts/train_offline.py`** — the whole pipeline end to end, exiting `1`
  when the model fails to beat the baseline, so it is usable as a gate.

Dependencies added to `pyproject.toml`: `torch>=2.5,<3` (2.13.0 installed),
`numpy>=1.26` (2.5.2), `safetensors>=0.4,<1` (0.8.0). **Not** added:
PyTorch Geometric — ADR 0023.

## 2. Verified

* `ruff format --check` (175 files), `ruff check`, `mypy graphrec apps`
  (100 source files) and `lint-imports` (3/3 contracts) all clean.
* **775 tests pass** against a real PostgreSQL 18 with `GRAPHREC_REQUIRE_DB=1`,
  157 of them new in `tests/ml/`. The modelling suite alone runs in 9.4 s.
* **The exit criteria, each as a named test:**
  * `tests/ml/test_training.py::test_the_model_beats_the_popularity_baseline` —
    both accuracy metrics strictly better, and coverage asserted alongside.
  * `tests/ml/test_split.py::test_the_fixture_split_has_no_leakage`, with
    `test_a_target_left_in_training_is_caught` and
    `test_a_target_before_a_training_row_is_caught` proving the check can fail.
    A leakage check that has never been shown to fail is not worth trusting.
  * `tests/ml/test_training.py::test_the_same_seed_reproduces_the_metrics`, with
    `test_a_different_seed_gives_a_different_model` beside it so the first
    cannot pass on a model that ignores its input.
* **The full offline run** (`scripts/train_offline.py`, 160 users, 100 items,
  1,794 interactions, seed 1337, stopped early at epoch 10 with the best model
  from epoch 5):

  | metric      | popularity | DGSR   | delta   |
  |-------------|-----------:|-------:|--------:|
  | Recall@10   | 0.2062     | 0.5188 | +0.3125 |
  | HR@10       | 0.2062     | 0.5188 | +0.3125 |
  | NDCG@10     | 0.1067     | 0.2344 | +0.1277 |
  | coverage    | 0.1800     | 1.0000 | +0.8200 |

  The fixture's ceiling is around 0.85 by construction (`AFFINITY`), so 0.52 is
  a real result rather than a saturated one.
* Also held: the hand-computed metric values (`1/log2(3)`, `1/log2(4)` and the
  two-relevant-item normalisation are written as arithmetic, not read off a
  run); padding never borrows the last embedding row; an all-padding sequence
  does not produce NaN; both pathways demonstrably reach the output; a
  checkpoint round-trips, resumes at epoch 4 rather than 1, refuses a truncated
  file, refuses a foreign file, refuses another format version, and an
  interrupted write leaves the previous checkpoint byte-identical.

## 3. Defects found and fixed

* **The fixture made the exit criterion nearly unmeetable.** The first version
  let a user interact with the same item repeatedly. Because both the evaluator
  and Phase 11's funnel exclude items the user has already seen, the held-out
  target was usually already in the excluded history, and Recall@10 was capped
  at the non-repeat rate — 0.28 for the model against a ceiling it could not
  reach. The metric was measuring the protocol rather than the model. Fixed in
  the fixture, not in the protocol: each user now draws distinct items, and the
  reason is written into the module docstring.
* **The without-replacement draw biased the target.** Drawing without
  replacement in probability order put popular items first, so the last
  interaction — the test target — was systematically the user's *least* popular
  item, which would have made the popularity baseline look worse than it is and
  the comparison meaningless. The drawn set is now permuted before timestamps
  are assigned.
* **`TrainingConfig.seed` read as a `member_descriptor`.** `slots=True` means
  the class attribute is a descriptor, not the default value; argparse passed it
  straight to `torch.manual_seed`. The script builds an instance for its
  defaults, with the reason in a comment.
* **The connectivity assertion on the fixture graph was too strong.** At 60
  users the split strands exactly one long-tail product whose only two touches
  were both held out. That is what happens to a real catalogue, so the test now
  asserts a fraction rather than zero and says why.
* **The partial-write test proved nothing.** It provoked the failure during JSON
  encoding, which happens before the temporary file is created, so the "the
  temporary file is cleaned up" assertion passed vacuously. It now interrupts
  `save_file` itself.

## 4. Decisions recorded

* **ADR 0023 — the GNN pathway is plain PyTorch.** PyG's value is ragged message
  passing; the bounded sampler means there is nothing ragged. Avoids two
  compiled extensions pinned to a torch ABI in the inference image. Voided if
  the fan-out bound is ever removed, which is stated in the ADR.
* **ADR 0024 — evaluation ranks the whole catalogue.** Not 100 sampled
  negatives. The numbers are lower and comparable to production, which matters
  because Phase 10 turns them into an eligibility floor. Recall@10 and HR@10 are
  identical under leave-one-out; that is stated and pinned by a test rather than
  left to be rediscovered as a suspected bug.
* **ADR 0025 — checkpoints are safetensors.** BACKEND_PLAN already forbids
  `pickle` for bundles; a checkpoint is the same artifact one stage earlier and
  crosses the same trust boundary. `torch.save` appears nowhere in the codebase.

## 5. Not done

* **No storage, no jobs, no tenant.** Deliberate — `graphrec/storage/` and
  `apps/training_worker/` are still empty. Phase 9's nine stages wrap this loop;
  the `on_epoch` and `should_stop` seams are the whole interface it needs.
* **No `CandidateIndex`.** D4 is a Phase 10 gate and the port is not written
  here. `DGSR.item_matrix()` is the artifact it will consume, and it exists.
* **No bundle export or manifest.** Phase 10. The checkpoint format and its
  header discipline are the thing it will extend.
* **CPU only.** No device placement, no `.cuda()`, no mixed precision. Every
  tensor is on the default device. Adding a device is a constructor argument and
  a `.to()` in three places, and doing it before there is a GPU to test on would
  be untested code.
* **Hyper-parameters are not tuned.** The defaults produce a model that clearly
  beats the baseline on the fixture; they are not claimed to be good. Tuning
  against a synthetic corpus would tune to the generator.
* **`FeatureBuilder.VERSION` is not yet checked anywhere.** It exists so Phase
  10's manifest can record it and Phase 11 can refuse a mismatch. Until then it
  is a constant with a purpose and no enforcement.
* **The 15-minute training cooldown** (ADR README open question 2) is still
  unanswered and still unenforced. It becomes real in Phase 9.

## 6. New conflicts

* **BACKEND_PLAN §8.4 names PyTorch Geometric and this phase does not use it.**
  Recorded as ADR 0023 rather than silently diverged. The plan's *reason* for
  naming it — graph message passing — is satisfied; the library is not needed to
  satisfy it once the sampler bounds the fan-out.
* **A metric floor calibrated from published figures would be about three times
  too high.** ADR 0024's protocol produces production-comparable numbers, and
  Phase 10's `eligible`/`rejected` boundary must be written against numbers from
  the same protocol. Flagged here so it is a decision in Phase 10 rather than a
  surprise.
