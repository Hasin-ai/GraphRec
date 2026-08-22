"""The training loop, checkpoints, negative sampling — and the Phase 8 criterion.

BUILD_PROMPT's exit criterion for this phase is two properties, and both are
asserted here as named tests:

* `test_the_model_beats_the_popularity_baseline`
* `test_the_same_seed_reproduces_the_metrics`

(the leakage half lives in `test_split.py`, where the split is.)

Training runs are kept small — a 60-user fixture, a handful of epochs — because
this is a per-PR suite. That is a real limitation and it is stated: these runs
demonstrate that the pipeline learns *something* reproducibly, not that the
hyper-parameters are good. `scripts/train_offline.py` is the larger run.
"""

from __future__ import annotations

import numpy as np
import pytest
import torch

from graphrec.ml.eval.baseline import evaluate_popularity
from graphrec.ml.eval.evaluate import evaluate_model, rank_users
from graphrec.ml.eval.split import leave_last_out
from graphrec.ml.fixtures import synthetic
from graphrec.ml.graph.build import build_graph
from graphrec.ml.model.dgsr import DGSR, DGSRConfig
from graphrec.ml.train.checkpoint import (
    FORMAT_VERSION,
    META_KEY,
    CheckpointError,
    TrainingState,
    load_checkpoint,
    save_checkpoint,
)
from graphrec.ml.train.loop import TrainingConfig, build_examples, train
from graphrec.ml.train.negatives import (
    MAX_REJECTION_RETRIES,
    NegativePolicy,
    NegativeSampler,
)

#: Small model, few epochs. Enough to move the loss and to reproduce a number.
FAST = TrainingConfig(epochs=3, batch_size=128, n_negatives=4, patience=0, seed=11)
SMALL_MODEL = {"embedding_dim": 16, "n_heads": 2}


@pytest.fixture(scope="module")
def trained(split, builder):
    """One short training run, shared by the tests that only need its output."""
    return train(split, builder, config=FAST, model_config=_model_config(split, builder))


def _model_config(split, builder) -> DGSRConfig:
    return DGSRConfig.for_dataset(
        split.train, max_sequence_length=builder.max_sequence_length, **SMALL_MODEL
    )


# ---------------------------------------------------------------- examples


def test_an_example_is_a_position_not_a_user(split) -> None:
    examples = build_examples(split)

    assert len(examples) == sum(max(len(s) - 1, 0) for s in split.train.sequences)


def test_position_zero_is_never_an_example(split) -> None:
    """Predicting a user's first interaction from an empty prefix is the
    popularity prior; training on it teaches the model to emit that prior."""
    assert all(example.position >= 1 for example in build_examples(split))


def test_every_example_targets_its_own_sequence(split) -> None:
    for example in build_examples(split):
        assert split.train.sequences[example.user][example.position] == example.target


def test_the_prefix_of_an_example_is_strictly_earlier_in_time(split) -> None:
    """The slice is what makes an example unable to leak into itself."""
    for example in build_examples(split):
        times = split.train.timestamps[example.user]
        assert all(when <= times[example.position] for when in times[: example.position])


def test_example_weights_are_positive(split) -> None:
    assert all(example.weight > 0 for example in build_examples(split))


# ----------------------------------------------------------------- the loop


def test_the_loss_falls_over_the_run(trained) -> None:
    losses = [report.loss for report in trained.history]

    assert losses[-1] < losses[0]


def test_a_report_is_produced_for_every_epoch(trained) -> None:
    assert [report.epoch for report in trained.history] == [1, 2, 3]
    assert all(report.validation is not None for report in trained.history)


def test_the_on_epoch_seam_is_called_once_per_epoch(split, builder) -> None:
    """The seam Phase 9's worker reports progress through."""
    seen: list[int] = []
    train(
        split,
        builder,
        config=FAST,
        model_config=_model_config(split, builder),
        on_epoch=lambda report: seen.append(report.epoch),
    )

    assert seen == [1, 2, 3]


def test_should_stop_ends_the_run_promptly(split, builder) -> None:
    """The seam a tenant's cancellation is honoured through."""
    result = train(
        split,
        builder,
        config=FAST,
        model_config=_model_config(split, builder),
        should_stop=lambda: True,
    )

    assert result.history == []


def test_the_returned_model_is_the_best_one_and_not_the_last(split, builder) -> None:
    """Otherwise the patience window is trained into the registered model and
    the metric recorded against a version is one it no longer has."""
    result = train(
        split,
        builder,
        config=TrainingConfig(epochs=4, batch_size=128, n_negatives=4, patience=0, seed=3),
        model_config=_model_config(split, builder),
    )
    graph = build_graph(split.train)
    scored = evaluate_model(result.model, graph, builder, split.train, split.validation, seed=3)

    assert result.best_epoch <= len(result.history)
    assert scored.ndcg == pytest.approx(result.best_metric, abs=1e-9)


def test_early_stopping_fires_when_validation_stops_improving(split, builder) -> None:
    result = train(
        split,
        builder,
        config=TrainingConfig(epochs=40, batch_size=128, n_negatives=4, patience=1, seed=5),
        model_config=_model_config(split, builder),
    )

    assert result.stopped_early
    assert len(result.history) < 40


# ------------------------------------------------------------- determinism


def test_the_same_seed_reproduces_the_metrics(split, builder) -> None:
    """The second half of the Phase 8 exit criterion for reproducibility: a
    seeded run repeated gives the same numbers, which is the only way to tell a
    real improvement from a lucky one."""
    graph = build_graph(split.train)
    scores = []
    for _ in range(2):
        result = train(split, builder, config=FAST, model_config=_model_config(split, builder))
        scores.append(
            evaluate_model(result.model, graph, builder, split.train, split.test).as_dict()
        )

    assert scores[0] == scores[1]


def test_a_different_seed_gives_a_different_model(split, builder) -> None:
    """Otherwise the previous test would pass on a model that ignores its
    input."""
    graph = build_graph(split.train)
    first = train(split, builder, config=FAST, model_config=_model_config(split, builder))
    second = train(
        split,
        builder,
        config=TrainingConfig(epochs=3, batch_size=128, n_negatives=4, patience=0, seed=99),
        model_config=_model_config(split, builder),
    )

    left = evaluate_model(first.model, graph, builder, split.train, split.test).as_dict()
    right = evaluate_model(second.model, graph, builder, split.train, split.test).as_dict()
    assert left != right


def test_evaluation_does_not_depend_on_dropout(trained, split, builder) -> None:
    """Dropout left on during evaluation makes the metric depend on the RNG, and
    a floor applied to a moving number rejects models at random."""
    graph = build_graph(split.train)
    trained.model.train()

    first = evaluate_model(trained.model, graph, builder, split.train, split.test)
    second = evaluate_model(trained.model, graph, builder, split.train, split.test)

    assert first == second
    assert trained.model.training, "the evaluator restores the mode it found"


# ---------------------------------------------------------------- ranking


def test_a_ranking_never_contains_an_item_the_user_has_seen(trained, split, builder) -> None:
    graph = build_graph(split.train)
    rankings = rank_users(trained.model, graph, builder, split.test)

    for ranked, row in zip(rankings, split.test, strict=True):
        assert not set(ranked) & set(row.history)


def test_a_ranking_is_ten_distinct_items(trained, split, builder) -> None:
    graph = build_graph(split.train)

    for ranked in rank_users(trained.model, graph, builder, split.test):
        assert len(ranked) == 10
        assert len(set(ranked)) == 10


def test_an_empty_holdout_scores_zero_users(trained, split, builder) -> None:
    graph = build_graph(split.train)

    assert evaluate_model(trained.model, graph, builder, split.train, []).n_users == 0


# ------------------------------------------------------- negative sampling


def test_negatives_have_the_requested_shape(rng) -> None:
    sampler = NegativeSampler(50, policy=NegativePolicy.UNIFORM)

    assert sampler.draw([set(), set()], rng, count=6).shape == (2, 6)


def test_negatives_are_inside_the_catalogue(rng) -> None:
    sampler = NegativeSampler(50, policy=NegativePolicy.UNIFORM)
    drawn = sampler.draw([set() for _ in range(20)], rng, count=8)

    assert drawn.min() >= 0
    assert drawn.max() < 50


def test_the_popularity_policy_needs_a_popularity_vector() -> None:
    with pytest.raises(ValueError, match="needs a popularity vector"):
        NegativeSampler(10, policy=NegativePolicy.POPULARITY)


def test_a_cold_item_can_still_be_drawn_as_a_negative(rng) -> None:
    """Without the `+ 1` a cold item is never pushed down and drifts to whatever
    initialisation left it at — which is how cold items rank randomly high."""
    popularity = np.array([100, 0, 0], dtype=np.int64)
    sampler = NegativeSampler(3, popularity)

    drawn = sampler.draw([set() for _ in range(400)], rng, count=4)

    assert set(np.unique(drawn).tolist()) == {0, 1, 2}


def test_the_popular_item_is_drawn_more_often(rng) -> None:
    popularity = np.array([1000, 0, 0], dtype=np.int64)
    sampler = NegativeSampler(3, popularity)

    drawn = sampler.draw([set() for _ in range(500)], rng, count=4)
    counts = np.bincount(drawn.ravel(), minlength=3)

    assert counts[0] > counts[1]
    assert counts[0] > counts[2]


def test_the_user_s_history_is_usually_avoided(rng) -> None:
    sampler = NegativeSampler(20, policy=NegativePolicy.UNIFORM)
    history = set(range(10))

    drawn = sampler.draw([history for _ in range(200)], rng, count=4)
    inside = sum(1 for value in drawn.ravel() if int(value) in history)

    assert inside / drawn.size < 0.5**MAX_REJECTION_RETRIES + 0.02


def test_the_rejection_loop_is_bounded_on_an_exhausted_catalogue(rng) -> None:
    """A user holding the whole catalogue must not hang the step. The draw is
    accepted after the retries run out, and that is a decision, not a
    surprise."""
    sampler = NegativeSampler(3, policy=NegativePolicy.UNIFORM)

    drawn = sampler.draw([{0, 1, 2}], rng, count=5)

    assert drawn.shape == (1, 5)


# ---------------------------------------------------------------- checkpoints


def test_a_checkpoint_round_trips(split, builder, tmp_path) -> None:
    path = tmp_path / "model.safetensors"
    config = _model_config(split, builder)
    result = train(split, builder, config=FAST, model_config=config, checkpoint_path=path)

    restored = DGSR(config)
    before = restored.encoder.item.weight.detach().clone()
    state, restored_config = load_checkpoint(path, restored)

    assert restored_config == config
    assert state.epoch == 3
    assert not torch.allclose(restored.encoder.item.weight, before), "the weights moved"
    assert restored.encoder.item.weight.shape == result.model.encoder.item.weight.shape


def test_a_resume_continues_from_the_recorded_epoch(split, builder, tmp_path) -> None:
    """Phase 9's exit criterion in miniature: a crash mid-training resumes from
    the last checkpoint rather than restarting."""
    path = tmp_path / "model.safetensors"
    config = _model_config(split, builder)
    train(split, builder, config=FAST, model_config=config, checkpoint_path=path)

    longer = TrainingConfig(epochs=5, batch_size=128, n_negatives=4, patience=0, seed=11)
    resumed = train(
        split,
        builder,
        config=longer,
        model_config=config,
        checkpoint_path=path,
        resume=True,
    )

    assert [report.epoch for report in resumed.history] == [4, 5], "not 1 through 5"


def test_the_checkpoint_is_safetensors_and_not_a_pickle(split, builder, tmp_path) -> None:
    """`torch.save` pickles, and unpickling is arbitrary code execution across a
    trust boundary the worker and the inference process both sit on."""
    path = tmp_path / "model.safetensors"
    train(
        split,
        builder,
        config=FAST,
        model_config=_model_config(split, builder),
        checkpoint_path=path,
    )

    head = path.read_bytes()[:512]
    assert b"__pickle__" not in head
    assert META_KEY.encode() in head, "the safetensors header carries our metadata"


def test_a_truncated_checkpoint_is_refused(split, builder, tmp_path) -> None:
    path = tmp_path / "model.safetensors"
    config = _model_config(split, builder)
    train(split, builder, config=FAST, model_config=config, checkpoint_path=path)
    path.write_bytes(path.read_bytes()[: len(path.read_bytes()) // 2])

    with pytest.raises(CheckpointError):
        load_checkpoint(path, DGSR(config))


def test_a_file_without_our_header_is_refused(tmp_path) -> None:
    from safetensors.torch import save_file

    path = tmp_path / "foreign.safetensors"
    save_file({"weight": torch.zeros(2, 2)}, str(path))

    with pytest.raises(CheckpointError, match="was not written by this code"):
        load_checkpoint(path, DGSR(DGSRConfig(n_items=2, n_categories=2, n_static_features=3)))


def test_a_checkpoint_from_another_format_version_is_refused(split, builder, tmp_path) -> None:
    """Better than a silently-ignored optimiser state, which looks like a
    training instability and cannot be diagnosed from the loss curve."""
    import json

    from safetensors import safe_open
    from safetensors.torch import save_file

    path = tmp_path / "model.safetensors"
    config = _model_config(split, builder)
    train(split, builder, config=FAST, model_config=config, checkpoint_path=path)

    with safe_open(str(path), framework="pt") as handle:
        tensors = {name: handle.get_tensor(name) for name in handle.keys()}  # noqa: SIM118
        header = json.loads((handle.metadata() or {})[META_KEY])
    header["format_version"] = FORMAT_VERSION + 1
    save_file(tensors, str(path), metadata={META_KEY: json.dumps(header)})

    with pytest.raises(CheckpointError, match="checkpoint format"):
        load_checkpoint(path, DGSR(config))


def test_a_partial_write_never_replaces_a_good_checkpoint(
    split, builder, tmp_path, monkeypatch
) -> None:
    """The crash a checkpoint exists to survive can happen during the write that
    creates it, and a half-written checkpoint that loads is worse than none.

    The write is interrupted by monkeypatching `save_file`, because the failure
    being defended against is a process dying mid-`write()` and there is no
    honest way to provoke that from inside the process.
    """
    path = tmp_path / "model.safetensors"
    config = _model_config(split, builder)
    result = train(split, builder, config=FAST, model_config=config, checkpoint_path=path)
    good = path.read_bytes()

    def die(*_args: object, **_kwargs: object) -> None:
        msg = "the host went away"
        raise OSError(msg)

    monkeypatch.setattr("graphrec.ml.train.checkpoint.save_file", die)

    optimizer = torch.optim.Adam(result.model.parameters())
    with pytest.raises(OSError, match="the host went away"):
        save_checkpoint(
            path,
            result.model,
            optimizer,
            TrainingState(epoch=9, step=9, best_metric=0.0, numpy_state={}),
            config,
        )

    assert path.read_bytes() == good, "the previous checkpoint is untouched"
    assert not list(tmp_path.glob("*.partial")), "and the temporary file is cleaned up"


# ------------------------------------------------------- the exit criterion


def test_the_model_beats_the_popularity_baseline(builder) -> None:
    """**Phase 8's exit criterion.**

    Its own corpus, larger than the shared fixture and trained for longer,
    because the criterion is about the modelling and not about how quickly the
    suite runs. Both sides are scored under the identical protocol: full
    catalogue, history excluded, the same held-out users.
    """
    tenant = synthetic.generate(seed=20260101, n_users=160)
    dataset = builder.build(tenant.interactions, tenant.products)
    split = leave_last_out(dataset)
    split.assert_no_leakage()

    result = train(
        split,
        builder,
        config=TrainingConfig(epochs=10, patience=0, seed=1337),
        model_config=DGSRConfig.for_dataset(
            split.train, max_sequence_length=builder.max_sequence_length
        ),
    )

    graph = build_graph(split.train)
    model_metrics = evaluate_model(result.model, graph, builder, split.train, split.test)
    baseline_metrics = evaluate_popularity(split.train, split.test)

    assert model_metrics.beats(
        baseline_metrics
    ), f"model {model_metrics.as_dict()} does not beat popularity {baseline_metrics.as_dict()}"
    assert (
        model_metrics.coverage > baseline_metrics.coverage
    ), "and it surfaces more of the catalogue while doing it"
