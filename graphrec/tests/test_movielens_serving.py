"""Integrity regressions for the user's actual MovieLens v4 checkpoint."""
import json
import os
from pathlib import Path
import shutil

import numpy as np
import pytest
import torch

from graphrec_core.dgsr.serving import ArtifactError, DGSRArtifact

ARTIFACT = Path(os.environ.get('DGSR_MOVIELENS_ARTIFACT', 'model_artifacts/dgsr_movielens_32m'))
pytestmark = pytest.mark.skipif(not (ARTIFACT / 'best.pt').exists(), reason='MovieLens artifact not mounted')


def test_real_v4_checkpoint_identity_and_finite_serving():
    artifact = DGSRArtifact(ARTIFACT)
    assert artifact.engine_version == 'dgsr-multidata-v4'
    assert artifact.data.num_users == 3011
    assert artifact.data.num_items == 7951
    assert artifact.checkpoint_sha256 == '98aa3f2487daf20b8366869cda984802cfb0d47eb48a0f7548a31167222b13e0'
    assert artifact.data_fingerprint == '74721b465b7a7afbe6a3ddb2e0a7fd8e1311702da3af122aa562c140184731b2'
    assert np.isfinite(artifact.encode_known(0).query).all()


def test_changed_configuration_is_rejected(tmp_path):
    shutil.copytree(ARTIFACT, tmp_path, dirs_exist_ok=True)
    config = json.loads((tmp_path / 'config.json').read_text())
    config['layers'] += 1
    (tmp_path / 'config.json').write_text(json.dumps(config))
    with pytest.raises(ArtifactError, match='configuration'):
        DGSRArtifact(tmp_path)


def test_changed_split_is_rejected_by_v4_fingerprint(tmp_path):
    shutil.copytree(ARTIFACT, tmp_path, dirs_exist_ok=True)
    with np.load(tmp_path / 'interactions.npz', allow_pickle=False) as source:
        arrays = {key: source[key].copy() for key in source.files}
    arrays['examples_validation'][0, 2] += 1
    np.savez_compressed(tmp_path / 'interactions.npz', **arrays)
    with pytest.raises(ArtifactError, match='fingerprint'):
        DGSRArtifact(tmp_path)


def test_nonfinite_weights_cannot_become_ready(tmp_path):
    shutil.copytree(ARTIFACT, tmp_path, dirs_exist_ok=True)
    checkpoint = torch.load(tmp_path / 'best.pt', map_location='cpu', weights_only=True)
    next(iter(checkpoint['model'].values())).flatten()[0] = float('nan')
    torch.save(checkpoint, tmp_path / 'best.pt')
    with pytest.raises(ArtifactError, match='non-finite'):
        DGSRArtifact(tmp_path)
