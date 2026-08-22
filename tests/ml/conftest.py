"""Fixtures for the modelling suite.

Everything here is session-scoped and pure. There is no database in this suite
and there must not be one: Phase 8 is specified as offline-first precisely so
that a modelling failure cannot be confused with a storage failure, and a
fixture that reached for a session would undo that.

The corpus is small on purpose — 60 users rather than the script's 160 — because
the whole suite trains a model several times and a per-PR run has to stay in
seconds. The one test that asserts the exit criterion uses its own, larger
corpus and says so.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pytest

from graphrec.ml.eval.split import leave_last_out
from graphrec.ml.features.builder import FeatureBuilder
from graphrec.ml.fixtures import synthetic
from graphrec.ml.graph.build import build_graph

if TYPE_CHECKING:
    from graphrec.ml.eval.split import Split
    from graphrec.ml.features.builder import Dataset
    from graphrec.ml.graph.build import InteractionGraph

#: The seed every fixture in this suite is generated from. One constant, so a
#: test that reproduces a number can be pointed at the run that produced it.
SEED = 20260101


@pytest.fixture(scope="session")
def builder() -> FeatureBuilder:
    return FeatureBuilder()


@pytest.fixture(scope="session")
def tenant() -> synthetic.SyntheticTenant:
    return synthetic.generate(seed=SEED, n_users=60)


@pytest.fixture(scope="session")
def dataset(builder: FeatureBuilder, tenant: synthetic.SyntheticTenant) -> Dataset:
    return builder.build(tenant.interactions, tenant.products)


@pytest.fixture(scope="session")
def split(dataset: Dataset) -> Split:
    return leave_last_out(dataset)


@pytest.fixture(scope="session")
def graph(split: Split) -> InteractionGraph:
    """Built from the *training* view, which is the only graph anything in this
    suite is allowed to see."""
    return build_graph(split.train)


@pytest.fixture
def rng() -> np.random.Generator:
    """A fresh, seeded generator per test, so one test's draws cannot move
    another's."""
    return np.random.default_rng(SEED)
