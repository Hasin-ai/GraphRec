"""The job queue.

D2: PostgreSQL `SELECT … FOR UPDATE SKIP LOCKED` over a `jobs` table, rather
than RabbitMQ + Celery + a transactional outbox + a publisher process. The
deciding argument is not throughput, it is duplication: job state is *already*
an API resource the console polls (`/training/:jobId`, `/submissions/:id`), so
it has to live in the database whatever else is true. A broker would store it a
second time and create two authorities over one fact. See ADR 0011.

Claiming is the interesting problem, and it is the same problem the three
pre-credential resolvers solve (ADR 0008) wearing different clothes.

A worker serves every tenant. It cannot bind `app.tenant_id` before it claims,
because *which tenant it is working for is the answer the claim produces*. Under
`FORCE`d row-level security an unbound connection sees nothing, so a worker that
tried to claim under its own tenant context would find an empty queue forever.

So the claim is one `SECURITY DEFINER` function, `job_queue.claim`, owned by a
`NOLOGIN` role that exists only to own it. It returns **two identifiers and
nothing else** — the job and the tenant it belongs to. The worker then binds
that tenant and reads the payload under the ordinary tenant policy, exactly as a
request handler would. Nothing about the job's contents crosses the boundary.

The function holds column-level `UPDATE` on the five lease columns and on
nothing else. It cannot touch a payload, a result, a failure or an attempt
count. `SELECT … FOR UPDATE` requires `UPDATE` privilege in PostgreSQL, so a
lock-free "return a candidate and let the caller claim it" design would have
needed the same grant while giving up atomicity; see ADR 0011 for why that
trade was refused.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from psycopg import sql
from sqlalchemy.dialects import postgresql as pg

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "graphrec_app"
PLATFORM_ROLE = "graphrec_platform"
QUEUE_ROLE = "graphrec_queue"
QUEUE_SCHEMA = "job_queue"
TENANT_GUC = "app.tenant_id"

#: `queued` and `running` are the only non-terminal statuses, and the claim
#: index is partial on exactly them. History can grow without bound; the index
#: the claim query walks stays the size of the backlog.
QUEUE_STATUSES = ("queued", "running", "succeeded", "failed", "cancelled")
TERMINAL_STATUSES = ("succeeded", "failed", "cancelled")


def _can_manage_roles(conn: sa.Connection) -> bool:
    return bool(
        conn.execute(
            sa.text("SELECT rolsuper OR rolcreaterole FROM pg_roles WHERE rolname = current_user")
        ).scalar()
    )


def upgrade() -> None:
    _table()
    _rls_and_grants()
    _queue_role()
    _claim_function()


def _table() -> None:
    op.create_table(
        "jobs",
        sa.Column(
            "job_id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("tenants.tenant_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("job_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'queued'")),
        # Higher runs sooner. Fair-share ordering (below) outranks it *across*
        # tenants, so a tenant cannot buy its way past another tenant's queue by
        # setting priority on everything — only past its own other work.
        sa.Column("priority", sa.Integer(), nullable=False, server_default=sa.text("5")),
        # Attempts *consumed*, not attempts started. Claiming does not increment
        # this; only a retryable failure and a lapsed lease do. That is what
        # makes "a deterministic failure consumes no attempts" true rather than
        # approximately true — see `graphrec/jobs/queue.py`.
        sa.Column("attempt", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default=sa.text("3")),
        sa.Column(
            "run_after", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column("lease_owner", sa.Text(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        # Cancellation is cooperative: this column is a *request*, and the
        # worker honours it at a stage boundary. Nothing kills a worker
        # mid-write, because a job interrupted between two statements is a job
        # whose partial effects nobody has described.
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        sa.Column("payload", pg.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("progress", pg.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        # A catalogue code, not an exception message (ADR 0004, NR-NF-06). A
        # worker's traceback can carry a row of somebody's data in it, and this
        # column is rendered in a console.
        sa.Column("failure_code", sa.Text(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN (" + ", ".join(f"'{value}'" for value in QUEUE_STATUSES) + ")",
            name="ck_jobs_status",
        ),
        sa.CheckConstraint("attempt >= 0", name="ck_jobs_attempt_non_negative"),
        sa.CheckConstraint("max_attempts BETWEEN 1 AND 10", name="ck_jobs_max_attempts_in_range"),
        sa.CheckConstraint("priority BETWEEN 1 AND 9", name="ck_jobs_priority_in_range"),
        # A terminal job has finished; a non-terminal one has not. Without this
        # a job can be `succeeded` with no completion time, and every duration
        # the console renders becomes a guess.
        sa.CheckConstraint(
            "(status IN (" + ", ".join(f"'{value}'" for value in TERMINAL_STATUSES) + ")) "
            "= (completed_at IS NOT NULL)",
            name="ck_jobs_terminal_has_completion",
        ),
        # A running job holds a lease; nothing else does. This is the invariant
        # the expiry sweeper depends on: a row that is `running` with no
        # `lease_expires_at` would be invisible to the sweeper and stuck forever.
        sa.CheckConstraint(
            "(status = 'running') = (lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_jobs_running_holds_a_lease",
        ),
    )

    # The claim index, partial on the two live statuses. BACKEND_PLAN §14.
    op.execute(
        "CREATE INDEX ix_jobs_claim ON jobs (status, job_type, run_after) "
        "WHERE status IN ('queued', 'running')"
    )
    # The sweeper's index. Also partial: an expired lease is only possible on a
    # running row.
    op.execute(
        "CREATE INDEX ix_jobs_lease_expiry ON jobs (lease_expires_at) WHERE status = 'running'"
    )
    # What the console lists.
    op.execute("CREATE INDEX ix_jobs_tenant_created ON jobs (tenant_id, created_at DESC)")
    op.execute("CREATE INDEX ix_jobs_tenant_id ON jobs (tenant_id)")


def _rls_and_grants() -> None:
    op.execute("ALTER TABLE jobs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE jobs FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY jobs_tenant_isolation ON jobs
            FOR ALL TO {APP_ROLE}
            USING (tenant_id = current_setting('{TENANT_GUC}', true)::uuid)
            WITH CHECK (tenant_id = current_setting('{TENANT_GUC}', true)::uuid)
        """
    )
    # No DELETE. A job that ran is what the console's submission and training
    # history is made of, and a queue you can delete from is a queue whose
    # failures can be made to disappear.
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON jobs TO {APP_ROLE}")

    # `/admin/status` renders queue depth across the platform (BACKEND_PLAN
    # §11.4). Read-only, and never the payload.
    op.execute(
        f"GRANT SELECT (job_id, tenant_id, job_type, status, priority, attempt, max_attempts, "
        f"run_after, lease_owner, lease_expires_at, created_at, updated_at, started_at, "
        f"completed_at, failure_code) ON jobs TO {PLATFORM_ROLE}"
    )
    op.execute(
        f"CREATE POLICY jobs_platform_access ON jobs FOR SELECT TO {PLATFORM_ROLE} USING (true)"
    )


def _queue_role() -> None:
    conn = op.get_bind()
    exists = conn.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = :name"), {"name": QUEUE_ROLE}
    ).scalar()

    if not exists:
        if not _can_manage_roles(conn):
            raise RuntimeError(
                f"the migration role needs CREATEROLE (or superuser) to provision "
                f"{QUEUE_ROLE!r}, which owns the job claim function. "
                "Create it out of band as NOLOGIN and re-run."
            )
        driver = conn.connection.driver_connection
        driver.execute(
            sql.SQL("CREATE ROLE {} NOLOGIN NOINHERIT NOCREATEDB NOCREATEROLE").format(
                sql.Identifier(QUEUE_ROLE)
            )
        )

    # `INHERIT FALSE` for the same reason as `graphrec_lookup` in 0003: the
    # migration role must not silently acquire the ability to write another
    # tenant's lease columns. Reaching them takes a deliberate `SET ROLE`.
    op.execute(f"GRANT {QUEUE_ROLE} TO CURRENT_USER WITH INHERIT FALSE, SET TRUE")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {QUEUE_ROLE}")

    # Exactly what the claim needs to choose a row, and nothing that would let
    # it read one. `payload`, `progress`, `failure_reason` and `cancel_reason`
    # are absent: the claim answers *which* job, never *what* job.
    op.execute(
        f"GRANT SELECT (job_id, tenant_id, job_type, status, priority, run_after, created_at, "
        f"started_at, lease_expires_at) ON jobs TO {QUEUE_ROLE}"
    )
    # Five columns. A lease is all this role may write.
    op.execute(
        f"GRANT UPDATE (status, lease_owner, lease_expires_at, started_at, updated_at) "
        f"ON jobs TO {QUEUE_ROLE}"
    )
    op.execute(f"CREATE POLICY jobs_queue_claim ON jobs FOR SELECT TO {QUEUE_ROLE} USING (true)")
    op.execute(
        f"CREATE POLICY jobs_queue_lease ON jobs FOR UPDATE TO {QUEUE_ROLE} "
        f"USING (true) WITH CHECK (true)"
    )
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {QUEUE_SCHEMA} AUTHORIZATION {QUEUE_ROLE}")


def _claim_function() -> None:
    op.execute(f"SET LOCAL ROLE {QUEUE_ROLE}")
    op.execute(f"GRANT USAGE ON SCHEMA {QUEUE_SCHEMA} TO {APP_ROLE}")

    # Fair share, in one window function.
    #
    # The rank is computed over each tenant's **live** jobs — queued *and*
    # running — with running ones ranked first, and the outer query then takes
    # the lowest-ranked queued row in the system. So a tenant with one job
    # already in flight has its next job ranked second, behind the first job of
    # a tenant with nothing running. A tenant that enqueues ten thousand rows
    # therefore waits behind every other tenant's next job rather than in front
    # of it, which is the difference between a shared queue and a queue one
    # customer owns.
    #
    # Ranking only the queued rows does not work, and the failure is quiet: a
    # job leaves the queued set the instant it is claimed, so the tenant's
    # second job is promoted straight back to rank 1 and the tie-break — which
    # is arrival order — hands it the next worker too. The backlog wins every
    # round while appearing to be fairly ranked each time.
    #
    # `SKIP LOCKED` is what makes two workers claim disjoint jobs without either
    # of them blocking: a row another transaction has locked is not contended
    # for, it is passed over.
    #
    # `status` and `run_after` are repeated in the **outer** `WHERE` and not left
    # to the subquery alone, and that repetition is the difference between a
    # correct claim and one that hands the same job to two workers. When a row
    # it wanted becomes unlocked because the holder committed, PostgreSQL
    # re-reads the new version and re-checks the qualification — but only the
    # qualification at the locking query's own level. A predicate hidden inside
    # a subquery is evaluated once, against a snapshot taken before the other
    # worker committed, and so the row still looks queued. The claim then locks
    # a row that is already running.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {QUEUE_SCHEMA}.claim(
            p_owner text,
            p_job_types text[],
            p_lease_seconds integer
        )
        RETURNS TABLE (claimed_job_id uuid, claimed_tenant_id uuid)
        LANGUAGE plpgsql
        VOLATILE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        DECLARE
            v_job_id uuid;
        BEGIN
            SELECT j.job_id INTO v_job_id
            FROM public.jobs AS j
            JOIN (
                SELECT c.job_id,
                       c.status,
                       row_number() OVER (
                           PARTITION BY c.tenant_id
                           ORDER BY (c.status = 'running') DESC,
                                    c.priority DESC, c.run_after, c.created_at
                       ) AS tenant_rank
                FROM public.jobs AS c
                WHERE c.status IN ('queued', 'running')
                  AND (c.status = 'running' OR c.run_after <= now())
                  AND (p_job_types IS NULL OR c.job_type = ANY (p_job_types))
            ) AS r ON r.job_id = j.job_id AND r.status = 'queued'
            WHERE j.status = 'queued'
              AND j.run_after <= now()
            ORDER BY r.tenant_rank, j.priority DESC, j.run_after, j.created_at
            FOR UPDATE OF j SKIP LOCKED
            LIMIT 1;

            IF v_job_id IS NULL THEN
                RETURN;
            END IF;

            -- Guarded on `status` a second time. Between the lock above and
            -- this statement the row cannot change — it is locked — but the
            -- guard costs nothing and means a future edit that separates the
            -- two cannot quietly reintroduce a double claim.
            RETURN QUERY
            UPDATE public.jobs AS j
            SET status = 'running',
                lease_owner = p_owner,
                lease_expires_at = now() + make_interval(secs => p_lease_seconds),
                started_at = COALESCE(j.started_at, now()),
                updated_at = now()
            WHERE j.job_id = v_job_id AND j.status = 'queued'
            RETURNING j.job_id, j.tenant_id;
        END
        $$
        """
    )

    # Read-only, and returns identifiers only. The requeue itself happens in the
    # application, bound to the tenant the job belongs to and under that
    # tenant's own policy — so the decision to spend an attempt or to give up is
    # taken in a context that can be audited, not by a function nobody can see
    # into.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {QUEUE_SCHEMA}.expired_leases(p_limit integer)
        RETURNS TABLE (expired_job_id uuid, expired_tenant_id uuid)
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            SELECT j.job_id, j.tenant_id
            FROM public.jobs AS j
            WHERE j.status = 'running'
              AND j.lease_expires_at < now()
            ORDER BY j.lease_expires_at
            LIMIT p_limit
        $$
        """
    )

    for signature in ("claim(text, text[], integer)", "expired_leases(integer)"):
        op.execute(f"REVOKE ALL ON FUNCTION {QUEUE_SCHEMA}.{signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {QUEUE_SCHEMA}.{signature} TO {APP_ROLE}")

    op.execute("RESET ROLE")


def downgrade() -> None:
    conn = op.get_bind()
    present = bool(
        conn.execute(
            sa.text("SELECT 1 FROM pg_roles WHERE rolname = :name"), {"name": QUEUE_ROLE}
        ).scalar()
    )

    if present:
        # As the queue role. It owns both the schema and the functions, and the
        # migration owner deliberately holds neither — that is the point of the
        # arrangement, and `WITH SET TRUE` above is what makes this the one
        # explicit way through.
        op.execute(f"SET LOCAL ROLE {QUEUE_ROLE}")
        op.execute(f"DROP FUNCTION IF EXISTS {QUEUE_SCHEMA}.claim(text, text[], integer)")
        op.execute(f"DROP FUNCTION IF EXISTS {QUEUE_SCHEMA}.expired_leases(integer)")
        op.execute(f"DROP SCHEMA IF EXISTS {QUEUE_SCHEMA} CASCADE")
        op.execute("RESET ROLE")

    op.execute("DROP POLICY IF EXISTS jobs_queue_lease ON jobs")
    op.execute("DROP POLICY IF EXISTS jobs_queue_claim ON jobs")
    op.execute("DROP POLICY IF EXISTS jobs_platform_access ON jobs")
    op.execute("DROP POLICY IF EXISTS jobs_tenant_isolation ON jobs")

    if present:
        # Guarded: `REVOKE … FROM <role>` errors outright if the role is absent,
        # and a downgrade has to work against a database where this migration's
        # role provisioning never ran.
        op.execute(f"REVOKE ALL ON jobs FROM {QUEUE_ROLE}")
        op.execute(f"REVOKE ALL ON SCHEMA public FROM {QUEUE_ROLE}")

    op.drop_table("jobs")
    # The role itself stays. Dropping it would fail on any dependency elsewhere
    # in the cluster, and a NOLOGIN role with no grants left is inert.
