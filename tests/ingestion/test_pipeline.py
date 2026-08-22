"""The full ingestion path, against a real database and the real worker.

Phase 6's exit criteria, stated in `BUILD_PROMPT.md`:

* the same `event_id` twice yields one row and two successes;
* an oversize batch returns `413`  (`test_bounds.py`, which needs no database);
* a partial failure keeps the accepted remainder.

Each has a test below named after it. The rest of the module is the invariants
those three depend on and would otherwise pass without: that counts partition
rather than tally, that the payload does not outlive the job, and that a foreign
submission is invisible rather than forbidden.
"""

from __future__ import annotations

import datetime as dt

import pytest
import sqlalchemy as sa

from graphrec.common.enums import SubmissionKind, SubmissionStatus
from graphrec.common.errors import GraphRecError
from graphrec.domain.ingestion import IngestionService

pytestmark = [pytest.mark.db, pytest.mark.anyio]

NOW = dt.datetime(2026, 8, 14, 9, 41, 2, tzinfo=dt.UTC)


def _service() -> IngestionService:
    return IngestionService(job_lease_seconds=60, job_max_attempts=3)


def _event(event_id: str, product: str = "SKU-6002", **overrides) -> dict:
    item = {
        "event_id": event_id,
        "customer_id": "cus-9931",
        "external_product_id": product,
        "event_type": "purchase",
        "occurred_at": "2026-08-14T09:41:02Z",
        "value": "129.00",
    }
    item.update(overrides)
    return item


def _product(external_id: str, **overrides) -> dict:
    item = {"external_id": external_id, "title": f"Product {external_id}", "price": "8.40"}
    item.update(overrides)
    return item


async def _submission(bound, tenant_id, submission_id):
    async with bound(tenant_id) as session:
        row = (
            await session.execute(
                sa.text(
                    "SELECT status, received_count, accepted_count, updated_count, "
                    "       skipped_count, failed_count, error_count, failure_code, "
                    "       raw_payload, completed_at "
                    "FROM submissions WHERE submission_id = :sid"
                ),
                {"sid": submission_id},
            )
        ).mappings()
        return row.one_or_none()


async def _open(bound, tenant_id, kind, reference, items, options=None):
    async with bound(tenant_id) as session:
        outcome = await _service().open_submission(
            session,
            tenant_id=tenant_id,
            kind=kind,
            external_reference=reference,
            items=items,
            options=options,
            now=NOW,
        )
        return outcome.submission.submission_id, outcome.created


# ------------------------------------------------- exit criterion 1: repeats


async def test_the_same_event_id_twice_yields_one_row_and_two_successes(
    bound, tenant, seed_products
) -> None:
    """The prototype's own words: "a success outcome, not an error" (L1622)."""
    await seed_products(tenant, "SKU-6002")
    service = _service()

    async with bound(tenant) as session:
        first = await service.record_event(
            session, tenant_id=tenant, raw=_event("ev-33810"), now=NOW
        )
    async with bound(tenant) as session:
        second = await service.record_event(
            session, tenant_id=tenant, raw=_event("ev-33810"), now=NOW
        )

    assert first.status == "accepted"
    assert second.status == "duplicate_confirmed"
    # Two successes, and neither raised.
    assert first.event.event_id == second.event.event_id

    async with bound(tenant) as session:
        stored = await session.scalar(
            sa.text("SELECT count(*) FROM interaction_events WHERE external_event_id = 'ev-33810'")
        )
    assert stored == 1


async def test_a_duplicate_confirmation_says_when_it_was_first_received(
    bound, tenant, seed_products
) -> None:
    """L1622 renders "First received 2026-08-14 09:41:02" beside the badge.

    Without it the answer is "you already sent this" with no way to find out
    when, which is exactly the question a caller reconciling a retry has.
    """
    await seed_products(tenant, "SKU-6002")
    service = _service()
    async with bound(tenant) as session:
        await service.record_event(session, tenant_id=tenant, raw=_event("ev-33810"), now=NOW)
    async with bound(tenant) as session:
        repeat = await service.record_event(
            session, tenant_id=tenant, raw=_event("ev-33810"), now=NOW
        )
    assert repeat.first_received_at == NOW


async def test_the_same_event_id_twice_inside_one_batch_is_one_row(
    bound, tenant, seed_products, drain
) -> None:
    """Idempotency has to hold *within* a collection, not only across calls.

    A tenant's exporter that emits a row twice is the common case, and a batch
    that inserted both would put two purchases in the training data for one
    purchase in the world.
    """
    await seed_products(tenant, "SKU-6002")
    submission_id, _ = await _open(
        bound,
        tenant,
        SubmissionKind.EVENT_BATCH,
        "batch-dupe",
        [_event("ev-1"), _event("ev-1"), _event("ev-2")],
    )
    await drain()

    row = await _submission(bound, tenant, submission_id)
    assert row["status"] == SubmissionStatus.COMPLETED.value
    assert row["received_count"] == 3
    assert row["accepted_count"] == 2
    assert row["skipped_count"] == 1

    async with bound(tenant) as session:
        stored = await session.scalar(sa.text("SELECT count(*) FROM interaction_events"))
    assert stored == 2


async def test_repeating_a_batch_identifier_returns_the_original_submission(
    bound, tenant, seed_products, drain
) -> None:
    """ "Repeating the same identifier is confirmed as a duplicate rather than
    applied twice." (L1355) — and the second call must not enqueue a second job.
    """
    await seed_products(tenant, "SKU-6002")
    first_id, created_first = await _open(
        bound, tenant, SubmissionKind.EVENT_BATCH, "batch-4471", [_event("ev-1")]
    )
    second_id, created_second = await _open(
        bound, tenant, SubmissionKind.EVENT_BATCH, "batch-4471", [_event("ev-9")]
    )

    assert created_first is True
    assert created_second is False
    assert first_id == second_id

    async with bound(tenant) as session:
        jobs = await session.scalar(sa.text("SELECT count(*) FROM jobs"))
    assert jobs == 1, "the collection is drained once, not once per retry"

    await drain()
    row = await _submission(bound, tenant, first_id)
    # The *first* collection was applied. The second call's items were never
    # looked at, which is what "not applied twice" has to mean.
    assert row["received_count"] == 1
    async with bound(tenant) as session:
        assert (
            await session.scalar(
                sa.text("SELECT count(*) FROM interaction_events WHERE external_event_id = 'ev-9'")
            )
            == 0
        )


# ----------------------------------- exit criterion 3: the accepted remainder


async def test_a_partial_failure_keeps_the_accepted_remainder(
    bound, tenant, seed_products, drain
) -> None:
    """ "Failures are reported per item; the accepted remainder is not
    discarded." (L1353)

    Four items, three distinct fates: two good, one refused by the validator,
    one refused by the catalog. The two good ones must be in the database when
    it is over.
    """
    await seed_products(tenant, "SKU-6002")
    submission_id, _ = await _open(
        bound,
        tenant,
        SubmissionKind.EVENT_BATCH,
        "batch-partial",
        [
            _event("ev-1"),
            _event("ev-2", occurred_at="not a timestamp"),
            _event("ev-3", product="SKU-NOWHERE"),
            _event("ev-4"),
        ],
    )
    await drain()

    row = await _submission(bound, tenant, submission_id)
    assert row["status"] == SubmissionStatus.COMPLETED.value
    assert row["received_count"] == 4
    assert row["accepted_count"] == 2
    assert row["failed_count"] == 2

    async with bound(tenant) as session:
        kept = list(
            await session.execute(
                sa.text(
                    "SELECT external_event_id FROM interaction_events ORDER BY external_event_id"
                )
            )
        )
    assert [r[0] for r in kept] == ["ev-1", "ev-4"]


async def test_each_reported_failure_names_the_item_and_a_safe_reason(
    bound, tenant, seed_products, drain
) -> None:
    """L1391: "Errors identify the offending item and a safe reason. Raw
    payloads are never echoed back."
    """
    await seed_products(tenant, "SKU-6002")
    submission_id, _ = await _open(
        bound,
        tenant,
        SubmissionKind.EVENT_BATCH,
        "batch-reasons",
        [_event("ev-40012", product="SKU-NOWHERE", context={"card": "4111111111111111"})],
    )
    await drain()

    async with bound(tenant) as session:
        errors = list(
            await session.execute(
                sa.text(
                    "SELECT item_reference, code, reason FROM submission_errors "
                    "WHERE submission_id = :sid ORDER BY ordinal"
                ),
                {"sid": submission_id},
            )
        )

    assert len(errors) == 1
    reference, code, reason = errors[0]
    assert reference == "ev-40012"
    assert code == "item_unknown_product"
    # L1629's approved wording, verbatim.
    assert reason == "unknown external product identifier"
    assert "4111111111111111" not in reason


async def test_the_counts_partition_the_collection(bound, tenant, seed_products, drain) -> None:
    """received = accepted + updated + skipped + failed, for every submission.

    The console divides their sum by `received` to draw the progress rail
    (L1380). An item counted in two buckets renders as a rail past 100%, and an
    item counted in none renders as a submission that never finishes.
    """
    await seed_products(tenant, "SKU-1", "SKU-2")
    submission_id, _ = await _open(
        bound,
        tenant,
        SubmissionKind.EVENT_BATCH,
        "batch-partition",
        [
            _event("ev-1", product="SKU-1"),
            _event("ev-1", product="SKU-1"),
            _event("ev-2", product="SKU-2"),
            _event("ev-3", product="SKU-MISSING"),
            _event("ev-4", event_type="wishlist"),
        ],
    )
    await drain()

    row = await _submission(bound, tenant, submission_id)
    total = (
        row["accepted_count"] + row["updated_count"] + row["skipped_count"] + row["failed_count"]
    )
    assert total == row["received_count"] == 5


# ------------------------------------------------------------ product syncs


async def test_a_sync_distinguishes_created_from_updated(bound, tenant, drain) -> None:
    """The console labels the third stat "Updated" for a product sync (L1389).

    It is a distinct number from `accepted`, not a synonym: a tenant re-running
    a nightly file wants to know how much of it actually changed anything.
    """
    await _open(
        bound,
        tenant,
        SubmissionKind.PRODUCT_SYNC,
        "req-first",
        [_product("SKU-4471"), _product("SKU-4472")],
    )
    await drain()

    second_id, _ = await _open(
        bound,
        tenant,
        SubmissionKind.PRODUCT_SYNC,
        "req-second",
        [_product("SKU-4471", title="Brass hinge, 90mm"), _product("SKU-9999")],
    )
    await drain()

    row = await _submission(bound, tenant, second_id)
    assert row["accepted_count"] == 1, "SKU-9999 is new"
    assert row["updated_count"] == 1, "SKU-4471 already existed"

    async with bound(tenant) as session:
        title = await session.scalar(
            sa.text("SELECT title FROM products WHERE external_product_id = 'SKU-4471'")
        )
    assert title == "Brass hinge, 90mm"


async def test_a_sync_item_targeting_a_disabled_product_fails_rather_than_re_enabling_it(
    bound, tenant, drain
) -> None:
    """L689: "external identifier already disabled".

    Re-enabling is a deliberate act with an audited reason (L1340) and `PATCH`
    is the route for it. A bulk file quietly resurrecting a product somebody
    disabled on purpose is the failure this refusal exists to prevent.
    """
    await _open(bound, tenant, SubmissionKind.PRODUCT_SYNC, "req-a", [_product("SKU-4471")])
    await drain()
    async with bound(tenant) as session:
        await session.execute(
            sa.text(
                "UPDATE products SET is_active = false, disabled_at = now(), "
                "    disabled_reason = 'Discontinued by supplier' "
                "WHERE external_product_id = 'SKU-4471'"
            )
        )

    submission_id, _ = await _open(
        bound, tenant, SubmissionKind.PRODUCT_SYNC, "req-b", [_product("SKU-4471")]
    )
    await drain()

    row = await _submission(bound, tenant, submission_id)
    assert row["failed_count"] == 1
    assert row["accepted_count"] == 0

    async with bound(tenant) as session:
        active, reason = (
            await session.execute(
                sa.text(
                    "SELECT is_active, disabled_reason FROM products "
                    "WHERE external_product_id = 'SKU-4471'"
                )
            )
        ).one()
    assert active is False
    assert reason == "Discontinued by supplier", "the hand-written reason survived"


async def test_disable_missing_mode_retires_what_the_collection_omits(bound, tenant, drain) -> None:
    """L1357's second mode, and it writes an audited reason like any disable."""
    await _open(
        bound,
        tenant,
        SubmissionKind.PRODUCT_SYNC,
        "req-full",
        [_product("SKU-1"), _product("SKU-2")],
    )
    await drain()

    await _open(
        bound,
        tenant,
        SubmissionKind.PRODUCT_SYNC,
        "req-partial",
        [_product("SKU-1")],
        options={"mode": "upsert_and_disable_missing"},
    )
    await drain()

    async with bound(tenant) as session:
        rows = dict(
            (
                await session.execute(
                    sa.text("SELECT external_product_id, is_active FROM products")
                )
            ).all()
        )
        reason = await session.scalar(
            sa.text("SELECT disabled_reason FROM products WHERE external_product_id = 'SKU-2'")
        )

    assert rows == {"SKU-1": True, "SKU-2": False}
    assert "req-partial" in reason, "a disable is audited with why, even in bulk"


async def test_plain_upsert_mode_leaves_omitted_products_alone(bound, tenant, drain) -> None:
    """The default must be the safe one.

    A tenant syncing one department's file should not retire the rest of the
    catalogue because it was not mentioned.
    """
    await _open(
        bound, tenant, SubmissionKind.PRODUCT_SYNC, "req-1", [_product("SKU-1"), _product("SKU-2")]
    )
    await drain()
    await _open(bound, tenant, SubmissionKind.PRODUCT_SYNC, "req-2", [_product("SKU-1")])
    await drain()

    async with bound(tenant) as session:
        active = await session.scalar(
            sa.text("SELECT is_active FROM products WHERE external_product_id = 'SKU-2'")
        )
    assert active is True


async def test_the_last_occurrence_wins_within_one_sync(bound, tenant, drain) -> None:
    """`ON CONFLICT DO UPDATE` cannot touch a row twice in one statement, so the
    winner is picked before the merge runs. The later item is the tenant's later
    intent, so it is the one that lands; the earlier is `skipped`, not `failed`
    — nothing was wrong with it, it was simply superseded.
    """
    submission_id, _ = await _open(
        bound,
        tenant,
        SubmissionKind.PRODUCT_SYNC,
        "req-dupe",
        [_product("SKU-1", title="First"), _product("SKU-1", title="Second")],
    )
    await drain()

    row = await _submission(bound, tenant, submission_id)
    assert row["skipped_count"] == 1
    assert row["failed_count"] == 0

    async with bound(tenant) as session:
        title = await session.scalar(
            sa.text("SELECT title FROM products WHERE external_product_id = 'SKU-1'")
        )
    assert title == "Second"


# -------------------------------------------------------------- the account


async def test_the_payload_does_not_outlive_the_job(bound, tenant, seed_products, drain) -> None:
    """A tenant's raw business data is kept for exactly as long as it is needed.

    `raw_payload` exists so the worker can stream the collection without a
    second copy in `jobs.payload`. Once the merge has committed, nothing reads
    it again, and the shortest-lived copy is the safest one (migration 0008).
    """
    await seed_products(tenant, "SKU-6002")
    submission_id, _ = await _open(
        bound, tenant, SubmissionKind.EVENT_BATCH, "batch-payload", [_event("ev-1")]
    )
    before = await _submission(bound, tenant, submission_id)
    assert before["raw_payload"] is not None

    await drain()

    after = await _submission(bound, tenant, submission_id)
    assert after["raw_payload"] is None
    assert after["completed_at"] is not None


async def test_the_staging_table_is_empty_when_the_job_is_done(
    bound, tenant, seed_products, drain
) -> None:
    """Staging is scratch. A staged row that survives its submission is a third
    copy of the tenant's data with nobody's name on it.
    """
    await seed_products(tenant, "SKU-6002")
    await _open(bound, tenant, SubmissionKind.EVENT_BATCH, "batch-staging", [_event("ev-1")])
    await drain()

    async with bound(tenant) as session:
        left = await session.scalar(sa.text("SELECT count(*) FROM ingest_staging_items"))
    assert left == 0


async def test_error_samples_are_capped_while_the_failed_count_stays_exact(
    bound, tenant, drain
) -> None:
    """`failed_count` and `error_count` are separate columns for this reason.

    A tenant whose 400-item file was entirely malformed needs to be told it was
    400 — not 100, which is merely how many rows we kept to show them.
    """
    items = [_product(f"SKU-{n}", price="not a price") for n in range(400)]
    submission_id, _ = await _open(bound, tenant, SubmissionKind.PRODUCT_SYNC, "req-cap", items)
    await drain()

    row = await _submission(bound, tenant, submission_id)
    assert row["failed_count"] == 400
    assert row["error_count"] == 100

    async with bound(tenant) as session:
        kept = await session.scalar(
            sa.text("SELECT count(*) FROM submission_errors WHERE submission_id = :sid"),
            {"sid": submission_id},
        )
    assert kept == 100


async def test_the_kept_samples_are_the_first_ones_sent(bound, tenant, drain) -> None:
    """Order matters: a tenant debugging a file starts at the top of it."""
    items = [_product(f"SKU-{n:04d}", price="not a price") for n in range(150)]
    submission_id, _ = await _open(bound, tenant, SubmissionKind.PRODUCT_SYNC, "req-order", items)
    await drain()

    async with bound(tenant) as session:
        ordinals = [
            r[0]
            for r in await session.execute(
                sa.text(
                    "SELECT ordinal FROM submission_errors WHERE submission_id = :sid "
                    "ORDER BY ordinal"
                ),
                {"sid": submission_id},
            )
        ]
    assert ordinals == list(range(100))


async def test_a_rerun_of_a_finished_submission_changes_nothing(
    bound, tenant, seed_products, drain, ingest_sessionmaker
) -> None:
    """A lease that lapsed while a worker was merely slow delivers the job twice.

    The submission — not the job row — is the record of whether the work
    happened, so a second delivery reports the finished state instead of merging
    the collection again.
    """
    await seed_products(tenant, "SKU-6002")
    submission_id, _ = await _open(
        bound, tenant, SubmissionKind.EVENT_BATCH, "batch-rerun", [_event("ev-1")]
    )
    await drain()
    first = await _submission(bound, tenant, submission_id)

    # Re-enqueue the same submission, as a redelivery would.
    from graphrec.jobs.queue import JobQueue
    from graphrec.jobs.states import JobType

    async with bound(tenant) as session:
        await JobQueue(lease_seconds=60, max_attempts=3, owner="test").enqueue(
            session,
            tenant_id=tenant,
            job_type=JobType.EVENT_BATCH,
            payload={"submission_id": str(submission_id)},
        )
    await drain()

    assert await _submission(bound, tenant, submission_id) == first
    async with bound(tenant) as session:
        assert await session.scalar(sa.text("SELECT count(*) FROM interaction_events")) == 1


# ------------------------------------------------------------- gate 4, again


async def test_another_tenants_submission_is_invisible_not_forbidden(
    bound, ingest_tenants, seed_products, drain
) -> None:
    """Gate 4 — a foreign submission and an absent one are the same 404.

    Read through the *other* tenant's binding, so the row is not filtered out
    after being fetched; it is never a candidate.
    """
    alpha, beta = ingest_tenants["alpha"], ingest_tenants["beta"]
    await seed_products(alpha, "SKU-6002")
    submission_id, _ = await _open(
        bound, alpha, SubmissionKind.EVENT_BATCH, "batch-private", [_event("ev-1")]
    )

    async with bound(beta) as session:
        with pytest.raises(GraphRecError) as caught:
            await _service().submission(session, submission_id=submission_id)
    assert caught.value.status_code == 404
    assert "submission" not in caught.value.reason().lower()


async def test_the_same_identifier_in_two_tenants_is_two_submissions(
    bound, ingest_tenants, seed_products
) -> None:
    """`batch-4471` is a name the tenant chose, and two tenants may choose it.

    Uniqueness is per tenant, enforced by the composite constraint in migration
    0008 rather than by anything the request path checks.
    """
    alpha, beta = ingest_tenants["alpha"], ingest_tenants["beta"]
    await seed_products(alpha, "SKU-6002")
    await seed_products(beta, "SKU-6002")

    alpha_id, alpha_created = await _open(
        bound, alpha, SubmissionKind.EVENT_BATCH, "batch-4471", [_event("ev-1")]
    )
    beta_id, beta_created = await _open(
        bound, beta, SubmissionKind.EVENT_BATCH, "batch-4471", [_event("ev-1")]
    )

    assert alpha_created is True
    assert beta_created is True
    assert alpha_id != beta_id


async def test_a_sync_id_and_a_batch_id_are_separate_namespaces(
    bound, tenant, seed_products
) -> None:
    """Migration 0008 puts `kind` in the unique constraint deliberately.

    A tenant numbering both kinds from a single counter must not have their
    hundredth batch confirmed as a duplicate of their hundredth sync.
    """
    await seed_products(tenant, "SKU-6002")
    sync_id, sync_created = await _open(
        bound, tenant, SubmissionKind.PRODUCT_SYNC, "req-100", [_product("SKU-1")]
    )
    batch_id, batch_created = await _open(
        bound, tenant, SubmissionKind.EVENT_BATCH, "req-100", [_event("ev-1")]
    )

    assert sync_created is True
    assert batch_created is True
    assert sync_id != batch_id


# ------------------------------------------------------------ the grants


async def test_an_interaction_event_cannot_be_updated_or_deleted(
    bound, tenant, seed_products, drain
) -> None:
    """Migration 0008 grants `interaction_events` only SELECT and INSERT.

    An event is a historical fact. A correction to one is a different event, not
    an edit of this one — and a training set built from mutable history is a
    training set nobody can reproduce.
    """
    await seed_products(tenant, "SKU-6002")
    await _open(bound, tenant, SubmissionKind.EVENT_BATCH, "batch-grants", [_event("ev-1")])
    await drain()

    for statement in (
        "UPDATE interaction_events SET event_type = 'view'",
        "DELETE FROM interaction_events",
    ):
        with pytest.raises(Exception, match="permission denied"):
            async with bound(tenant) as session:
                await session.execute(sa.text(statement))
