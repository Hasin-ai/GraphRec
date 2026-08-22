"""DGSR: shapes, the padding defence, and that both pathways actually matter.

The interesting failures in a two-pathway model are silent. A padding index that
gathers the last embedding row instead of nothing produces a model that trains
happily and is wrong; a gate that saturates produces a model where one pathway
is dead weight and nobody notices until a tenant reports that recommendations
ignore their session. Both are tested directly.
"""

from __future__ import annotations

import numpy as np
import pytest
import torch

from graphrec.ml.eval.evaluate import pad_sequences
from graphrec.ml.graph.sample import sample_two_hop
from graphrec.ml.model.dgsr import DGSR, DGSRConfig, GatedFusion
from graphrec.ml.model.loss import LOGIT_CLAMP, bpr_loss


@pytest.fixture
def config() -> DGSRConfig:
    return DGSRConfig(n_items=20, n_categories=3, n_static_features=3, embedding_dim=16, n_heads=2)


@pytest.fixture
def model(config: DGSRConfig) -> DGSR:
    torch.manual_seed(0)
    built = DGSR(config)
    built.eval()
    return built


@pytest.fixture
def fixture_model(dataset) -> DGSR:
    """A model sized to the suite's fixture, for the tests that feed it a real
    sampled neighbourhood. The small `model` above has twenty items and the
    fixture graph has a hundred, so the two are not interchangeable."""
    torch.manual_seed(0)
    built = DGSR(DGSRConfig.for_dataset(dataset, embedding_dim=16, n_heads=2))
    built.load_catalogue(dataset)
    built.eval()
    return built


# ------------------------------------------------------------ configuration


def test_the_head_count_must_divide_the_embedding_dimension() -> None:
    with pytest.raises(ValueError, match="not divisible"):
        DGSRConfig(n_items=4, n_categories=2, n_static_features=3, embedding_dim=10, n_heads=3)


def test_the_config_is_sized_from_the_dataset(dataset) -> None:
    """Taking the sizes from the dataset is what stops the embedding table being
    one row short of the catalogue."""
    config = DGSRConfig.for_dataset(dataset)

    assert config.n_items == dataset.n_items
    assert config.n_categories == dataset.n_categories
    assert config.n_static_features == dataset.item_features.shape[1]


# --------------------------------------------------------------- the padding


def test_a_padded_index_encodes_to_zero(model: DGSR) -> None:
    """`-1` is a valid index in PyTorch and silently reads the *last* embedding
    row. Clamp, then mask."""
    encoded = model.encode_items(torch.tensor([[-1, 0]]))

    assert torch.all(encoded[0, 0] == 0.0)
    assert torch.any(encoded[0, 1] != 0.0)


def test_a_padded_slot_does_not_borrow_the_last_item_s_embedding(model: DGSR) -> None:
    last = model.encode_items(torch.tensor([model.config.n_items - 1]))
    padded = model.encode_items(torch.tensor([-1]))

    assert not torch.allclose(padded, last)


def test_sequences_are_padded_on_the_left() -> None:
    """So the last column is always the user's most recent item, and both the
    read-out and the graph seed are a fixed column."""
    padded = pad_sequences([[1, 2], [7]], length=4)

    assert padded.tolist() == [[-1, -1, 1, 2], [-1, -1, -1, 7]]


def test_a_sequence_longer_than_the_window_keeps_its_tail() -> None:
    padded = pad_sequences([[1, 2, 3, 4, 5]], length=3)

    assert padded.tolist() == [[3, 4, 5]]


def test_an_empty_neighbourhood_gives_a_finite_representation(model: DGSR) -> None:
    """The masked mean divides by `clamp(min=1)`, so an empty neighbourhood is
    exactly zero rather than a NaN or an exploding vector."""
    sequence = pad_sequences([[3, 4]], length=model.config.max_sequence_length)
    hop2 = torch.full((1, 4, 4), -1, dtype=torch.long)
    mask1 = torch.zeros((1, 4), dtype=torch.bool)
    mask2 = torch.zeros((1, 4, 4), dtype=torch.bool)

    state = model.user_representation(sequence, hop2, mask1, mask2)

    assert torch.isfinite(state).all()


def test_a_user_with_no_history_at_all_does_not_produce_nan(model: DGSR) -> None:
    """An all-padding row would make every attention key invalid; the pathway
    gives such rows a visible mask and zeroes the read-out afterwards."""
    sequence = torch.full((1, model.config.max_sequence_length), -1, dtype=torch.long)
    hop2 = torch.full((1, 2, 2), -1, dtype=torch.long)

    state = model.user_representation(
        sequence,
        hop2,
        torch.zeros((1, 2), dtype=torch.bool),
        torch.zeros((1, 2, 2), dtype=torch.bool),
    )

    assert torch.isfinite(state).all()


# ---------------------------------------------------------------- the shapes


def test_the_user_representation_has_the_embedding_shape(fixture_model: DGSR, graph, rng) -> None:
    model = fixture_model
    sequences = pad_sequences([[1, 2, 3], [4]], length=model.config.max_sequence_length)
    sample = sample_two_hop(graph, np.array([3, 4]), rng, fanouts=(3, 3))

    state = model.user_representation(
        sequences,
        torch.as_tensor(sample.hop2, dtype=torch.long),
        torch.as_tensor(sample.hop1_mask),
        torch.as_tensor(sample.hop2_mask),
    )

    assert state.shape == (2, model.config.embedding_dim)


def test_scoring_is_one_number_per_candidate(model: DGSR) -> None:
    state = torch.randn(3, model.config.embedding_dim)

    assert model.score(state, torch.zeros((3, 7), dtype=torch.long)).shape == (3, 7)


def test_the_item_matrix_covers_the_whole_catalogue(model: DGSR) -> None:
    """This is the artifact Phase 10 writes into the bundle and Phase 11
    searches, so a row per item is the contract."""
    matrix = model.item_matrix()

    assert matrix.shape == (model.config.n_items, model.config.embedding_dim)


def test_the_item_matrix_does_not_depend_on_which_users_were_sampled(model: DGSR) -> None:
    """An item's exported vector must not change with the moment of export."""
    assert torch.allclose(model.item_matrix(), model.item_matrix())


def test_the_catalogue_buffers_travel_with_the_model(dataset) -> None:
    model = DGSR(DGSRConfig.for_dataset(dataset, embedding_dim=8, n_heads=2))
    model.load_catalogue(dataset)

    assert model.item_categories.tolist() == dataset.item_categories.tolist()
    assert model.item_features.shape == dataset.item_features.shape
    assert "item_categories" in dict(model.named_buffers())


# ------------------------------------------------------------------ the gate


def test_the_gate_is_per_element_and_within_the_unit_interval(config: DGSRConfig) -> None:
    torch.manual_seed(0)
    fusion = GatedFusion(config)
    left, right = torch.randn(4, config.embedding_dim), torch.randn(4, config.embedding_dim)

    gate = fusion.gate_value(left, right)

    assert gate.shape == (4, config.embedding_dim), "per element, not a scalar per user"
    assert bool(((gate >= 0) & (gate <= 1)).all())


def test_both_pathways_reach_the_output(fixture_model: DGSR, graph, rng) -> None:
    """If changing the sequence alone leaves the representation untouched, the
    sequence pathway is dead weight and the gate has collapsed."""
    model = fixture_model
    sample = sample_two_hop(graph, np.array([3]), rng, fanouts=(3, 3))
    hop2 = torch.as_tensor(sample.hop2, dtype=torch.long)
    mask1 = torch.as_tensor(sample.hop1_mask)
    mask2 = torch.as_tensor(sample.hop2_mask)

    first = model.user_representation(
        pad_sequences([[1, 2, 3]], model.config.max_sequence_length), hop2, mask1, mask2
    )
    second = model.user_representation(
        pad_sequences([[7, 8, 3]], model.config.max_sequence_length), hop2, mask1, mask2
    )

    assert not torch.allclose(first, second), "the sequence pathway changed nothing"


def test_the_graph_pathway_reaches_the_output(model: DGSR) -> None:
    sequence = pad_sequences([[1, 2, 3]], model.config.max_sequence_length)
    mask1 = torch.ones((1, 2), dtype=torch.bool)
    mask2 = torch.ones((1, 2, 2), dtype=torch.bool)

    first = model.user_representation(sequence, torch.tensor([[[0, 1], [2, 3]]]), mask1, mask2)
    second = model.user_representation(sequence, torch.tensor([[[9, 8], [7, 6]]]), mask1, mask2)

    assert not torch.allclose(first, second), "the graph pathway changed nothing"


# ------------------------------------------------------------------ the loss


def test_bpr_is_lower_when_the_positive_outscores_the_negative() -> None:
    good = bpr_loss(torch.tensor([2.0]), torch.tensor([[0.0]]))
    bad = bpr_loss(torch.tensor([0.0]), torch.tensor([[2.0]]))

    assert float(good) < float(bad)


def test_bpr_depends_only_on_the_difference() -> None:
    """Absolute score is left unconstrained, which is what lets the dot product
    rank without ever being calibrated as a probability."""
    near = bpr_loss(torch.tensor([1.0]), torch.tensor([[0.0]]))
    far = bpr_loss(torch.tensor([101.0]), torch.tensor([[100.0]]))

    assert float(near) == pytest.approx(float(far))


def test_bpr_stays_finite_at_an_extreme_difference() -> None:
    """`softplus(-x)`, not `-log(sigmoid(x))`."""
    loss = bpr_loss(torch.tensor([1e6]), torch.tensor([[-1e6]]))

    assert torch.isfinite(loss)
    assert float(loss) == pytest.approx(
        float(torch.nn.functional.softplus(torch.tensor(-LOGIT_CLAMP)))
    )


def test_a_purchase_moves_the_loss_more_than_a_view() -> None:
    """`FeatureBuilder` says a purchase is worth five views; that has to reach
    the gradient or it is a comment."""
    positives = torch.tensor([0.0, 0.0])
    negatives = torch.tensor([[5.0], [0.0]])

    weighted = bpr_loss(positives, negatives, torch.tensor([5.0, 1.0]))
    unweighted = bpr_loss(positives, negatives, torch.tensor([1.0, 1.0]))

    assert float(weighted) > float(unweighted), "the badly-ranked purchase dominates"


def test_more_negatives_do_not_inflate_the_loss() -> None:
    """Averaging, not summing — otherwise raising the negative count silently
    raises the effective learning rate."""
    one = bpr_loss(torch.tensor([1.0]), torch.tensor([[0.0]]))
    eight = bpr_loss(torch.tensor([1.0]), torch.zeros((1, 8)))

    assert float(one) == pytest.approx(float(eight))
