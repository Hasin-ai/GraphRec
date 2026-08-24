"""The artifact store's two promises: a digest that catches a swap, and a put
that is never half-done.

No database and no network. `LocalArtifactStore` is the shipped adapter for the
Compose deployment, not a stand-in, so testing it tests something that runs.
"""

from __future__ import annotations

import uuid

import pytest

from graphrec.storage import keys
from graphrec.storage.local import LocalArtifactStore
from graphrec.storage.store import DigestMismatchError, StorageError, digest_bytes


@pytest.fixture
def store(tmp_path) -> LocalArtifactStore:
    return LocalArtifactStore(tmp_path / "artifacts")


def test_a_stored_object_comes_back_byte_for_byte(store) -> None:
    payload = b"\x00\x01\x02 not text \xff"
    digest = store.put_bytes("a/b/c.bin", payload)

    assert store.get_bytes("a/b/c.bin") == payload
    assert digest == digest_bytes(payload)
    assert store.exists("a/b/c.bin")


def test_reading_with_the_wrong_digest_is_refused_rather_than_returned(store) -> None:
    """The check exists for the swapped-bundle case, so it must fail loudly.

    Returning the bytes and logging a warning would mean a tampered model
    version loads and serves, which is the outcome the digest was recorded to
    prevent.
    """
    store.put_bytes("model.bin", b"the real thing")

    with pytest.raises(DigestMismatchError):
        store.get_bytes("model.bin", expected_digest=f"sha256:{'0' * 64}")


def test_no_expected_digest_makes_no_claim(store) -> None:
    """`None` is "nobody said", not "anything is fine to assert".

    A snapshot read back by the job that just wrote it has no stored digest to
    check against yet, and forcing one would mean inventing it.
    """
    store.put_bytes("model.bin", b"the real thing")

    assert store.get_bytes("model.bin", expected_digest=None) == b"the real thing"


def test_a_file_is_verified_after_the_copy_not_before(store, tmp_path) -> None:
    """The copy is what the caller will load, so the copy is what is checked.

    Verifying the source and then copying would leave a window in which the
    copy is corrupt and the check has already passed.
    """
    source = tmp_path / "source.bin"
    source.write_bytes(b"checkpoint")
    digest = store.put_file("run/checkpoint.safetensors", source)

    destination = tmp_path / "restored.bin"
    store.get_file("run/checkpoint.safetensors", destination, expected_digest=digest)

    assert destination.read_bytes() == b"checkpoint"

    with pytest.raises(DigestMismatchError):
        store.get_file(
            "run/checkpoint.safetensors", destination, expected_digest=f"sha256:{'1' * 64}"
        )


def test_a_put_leaves_no_partial_object_behind(store, tmp_path, monkeypatch) -> None:
    """A write that dies before the rename leaves the previous object intact.

    Simulated by making `os.replace` fail, which is the last step and the only
    one that is meant to be atomic. The assertion is not that the new bytes are
    absent — it is that the *old* bytes are still readable, because a resume
    that finds a truncated checkpoint cannot tell it from a tampered one.
    """
    import os

    store.put_bytes("checkpoint.bin", b"epoch 7")

    def explode(*args: object, **kwargs: object) -> None:
        msg = "disk full"
        raise OSError(msg)

    monkeypatch.setattr(os, "replace", explode)
    with pytest.raises((OSError, StorageError)):
        store.put_bytes("checkpoint.bin", b"epoch 8 partially")

    assert store.get_bytes("checkpoint.bin") == b"epoch 7"


def test_a_key_that_escapes_the_root_is_refused(store) -> None:
    """The only way one arrives is a stored `uri` somebody edited.

    Refused rather than normalised: normalising would read a different object
    than the row names, quietly.
    """
    for key in ("../secrets", "a/../../secrets", "/etc/passwd"):
        with pytest.raises(StorageError):
            store.put_bytes(key, b"x")


def test_a_key_names_the_tenant_it_belongs_to() -> None:
    """Every artifact key is rooted at its tenant, and `belongs_to` says so.

    This is what makes Phase 10's foreign-manifest refusal checkable from the
    key alone, before anything is downloaded and parsed.
    """
    mine = uuid.uuid4()
    yours = uuid.uuid4()
    key = keys.checkpoint_key(mine, uuid.uuid4())

    assert keys.belongs_to(key, mine)
    assert not keys.belongs_to(key, yours)


def test_deleting_an_absent_object_is_not_an_error(store) -> None:
    """Cleanup runs on paths that may never have written anything.

    A `delete` that raised would make every teardown a conditional, and the
    condition would eventually be wrong.
    """
    store.delete("never/written.bin")


def test_probe_answers_where_exists_cannot(store, tmp_path) -> None:
    """The distinction `probe` exists to make.

    `exists` reports a missing key and an unreachable store identically — that
    is deliberate and documented, and it is exactly why a readiness check built
    on it would have called a dead store healthy. `probe` asks the store about
    itself instead.
    """
    assert store.exists("nothing/here") is False

    with pytest.raises(StorageError):
        store.probe()

    (tmp_path / "artifacts").mkdir()
    store.probe()


def test_a_root_that_is_not_a_directory_is_refused(tmp_path) -> None:
    """A file where the volume should be. Present is not the same as mounted."""
    occupied = tmp_path / "artifacts"
    occupied.write_bytes(b"not a directory")

    with pytest.raises(StorageError, match="not a directory"):
        LocalArtifactStore(occupied).probe()


def test_a_read_only_root_is_refused(tmp_path) -> None:
    """Readable is not enough: the next put will need to write.

    A volume mounted read-only is the failure this catches, and it is invisible
    to any probe that only stats the directory.
    """
    root = tmp_path / "artifacts"
    root.mkdir()
    root.chmod(0o500)
    try:
        with pytest.raises(StorageError, match="not writable"):
            LocalArtifactStore(root).probe()
    finally:
        root.chmod(0o700)
