"""Application configuration.

The full configuration surface of BACKEND_PLAN.md §22.4. Every user-facing bound
the console quotes back to a tenant — 5,000 products, 5,000 events, 1,000
sequences, the training cooldown, embedding dimension — is a named setting here
rather than a literal at its point of use (BUILD_PROMPT §13.22). Error copy
interpolates these values, so a limit that changed in code but not in the message
would produce a message that lies.
"""

from __future__ import annotations

# Runtime import, not a type-checking one: pydantic resolves these
# annotations at class-construction time to build the validators.
import uuid  # noqa: TCH003
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, PostgresDsn, RedisDsn, SecretStr, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    LOCAL = "local"
    CI = "ci"
    STAGING = "staging"
    PRODUCTION = "production"


class ServingDriverKind(StrEnum):
    """D3 — Compose is the default; k3s is added for the XR-F-08 scaling demonstration."""

    COMPOSE = "compose"
    K3S = "k3s"


class ArtifactStoreKind(StrEnum):
    """Where bundles, snapshots and checkpoints live."""

    S3 = "s3"
    LOCAL = "local"


class CandidateIndexKind(StrEnum):
    """D4 — in-process exact top-K by default; Qdrant when SRS §6.3 must be demonstrated."""

    INPROCESS = "inprocess"
    QDRANT = "qdrant"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    environment: Environment = Environment.LOCAL

    # ------------------------------------------------------------ database
    #
    # Two roles, deliberately. Migrations run as the owner; the application
    # connects as a non-owner, non-superuser so that RLS FORCE actually binds
    # it (BUILD_PROMPT §7.1). alembic.ini already carries the owner URL.

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "graphrec"
    postgres_app_user: str = "graphrec_app"
    postgres_app_password: SecretStr = SecretStr("graphrec_app_local_only")
    postgres_owner_user: str = "graphrec_owner"
    postgres_owner_password: SecretStr = SecretStr("graphrec_owner_local_only")
    # A third role, for `/v1/platform/*`. It is granted only the tables the
    # platform console renders, so a platform administrator cannot read a
    # tenant's catalogue or its customers' behaviour even by mistake — there is
    # no privilege to misuse (migration 0002).
    postgres_platform_user: str = "graphrec_platform"
    postgres_platform_password: SecretStr = SecretStr("graphrec_platform_local_only")

    db_pool_size: int = 10
    db_max_overflow: int = 5
    db_pool_timeout_seconds: int = 30
    # Bounds how long a pooled connection carrying stale session state can live.
    db_pool_recycle_seconds: int = 1_800
    db_statement_timeout_ms: int = 15_000
    #: Workers get their own bound. See `create_worker_engine`.
    worker_statement_timeout_ms: int = 900_000

    # ------------------------------------------------------------ redis
    #
    # Nothing authoritative lives here: rate limits, locks, session context and
    # the jti denylist only.

    redis_url: RedisDsn = RedisDsn("redis://localhost:6379/0")

    # ------------------------------------------------------------ object storage

    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: SecretStr = SecretStr("graphrec_local")
    s3_secret_key: SecretStr = SecretStr("graphrec_local_secret")
    s3_bucket: str = "graphrec"
    s3_region: str = "us-east-1"
    s3_use_path_style: bool = True

    # Which adapter the factory builds. `local` is a directory on disk and is
    # what the test suite and a laptop use; `s3` is MinIO in Compose and the
    # object store in a real deployment. A flag rather than an inference from
    # `s3_endpoint`, because "no MinIO running" and "deliberately on disk" are
    # different situations and only one of them should start quietly.
    artifact_store: ArtifactStoreKind = ArtifactStoreKind.S3
    artifact_local_root: str = "var/artifacts"

    # ------------------------------------------------------------ service

    api_port: int = 8010
    frontend_port: int = 5180
    cors_allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5180"])

    # ------------------------------------------------------------ tokens (D5)
    #
    # EdDSA, not HS256. A per-tenant inference process must verify a token
    # locally without a control-plane round trip, and a shared secret would let
    # every one of those processes mint tokens.

    jwt_private_key_path: Path = Path("secrets/jwt_ed25519_private.pem")
    jwt_public_key_path: Path = Path("secrets/jwt_ed25519_public.pem")
    jwt_key_id: str = "graphrec-local-1"
    jwt_issuer: str = "https://api.graphrec.example"
    access_token_ttl_seconds: int = 900
    refresh_token_ttl_seconds: int = 604_800
    # Neither the SRS nor the prototype names a validity period for an
    # invitation, so seven days is a derived default (ADR-0007). It is a setting
    # rather than a literal because it is the kind of number an operator will
    # want to shorten, and because "the earlier link stops working" (dc.html
    # L1247) is a promise about revocation, not about expiry.
    invitation_ttl_seconds: int = 604_800
    # An hour, and deliberately far shorter than an invitation's week. An
    # invitation is an arrangement between two people who already know each
    # other; a recovery proof is the answer to somebody claiming to have lost
    # control of an account, and the window in which a stolen one is useful is
    # the thing to keep small. Neither the SRS nor the prototype names a
    # figure, so this is derived and stated here rather than buried.
    recovery_ttl_seconds: int = 3_600

    # ------------------------------------------------------------ credentials

    audit_hash_secret: SecretStr = SecretStr("replace-with-a-long-random-local-secret")
    api_key_hmac_pepper: SecretStr = SecretStr("local-api-key-hmac-pepper-change-me")
    api_key_hash_version: int = 1
    max_active_api_keys_per_tenant: int = 25
    max_api_key_name_length: int = 100
    max_api_key_scopes: int = 12
    max_api_key_rotation_reason_length: int = 500
    max_api_key_grace_seconds: int = 86_400

    # ------------------------------------------------------------ request bounds (D7)
    #
    # Per-endpoint, not global. The inherited single MAX_REQUEST_BODY_BYTES=16384
    # is 37x too small for the 5,000-product sync the console offers.

    max_request_body_bytes: int = 16_384
    max_bulk_body_bytes: int = 2_097_152
    max_tenant_name_length: int = 200
    max_password_length: int = 1024
    max_idempotency_key_length: int = 255
    idempotency_key_ttl_seconds: int = 86_400
    min_reason_length: int = 4

    # ------------------------------------------------------------ rate limits

    login_rate_limit: int = 8
    login_rate_window_seconds: int = 60
    registration_rate_limit: int = 5
    registration_rate_window_seconds: int = 60
    api_key_rate_limit: int = 10
    api_key_rate_window_seconds: int = 60
    usage_rate_limit: int = 30
    usage_rate_window_seconds: int = 60
    subscription_rate_limit: int = 30
    subscription_rate_window_seconds: int = 60

    # ------------------------------------------------------------ jobs

    worker_concurrency: int = 2
    #: How long a claim loop waits before asking again when the queue is
    #: empty. Polling, not listening: at tens of jobs a day (ASM-03) the
    #: latency this costs is invisible and it removes a LISTEN/NOTIFY
    #: dependency that would need its own reconnection handling.
    job_poll_interval_seconds: float = 2.0
    job_sweep_interval_seconds: float = 30.0
    job_sweep_batch: int = 50
    job_lease_seconds: int = 120
    job_heartbeat_seconds: int = 30
    job_max_attempts: int = 3

    # ------------------------------------------------------------ training
    #
    # training_cooldown_seconds is provisional: it appears only on a stat card in
    # the prototype and nowhere in the SRS. Pending confirmation (BUILD_PROMPT §2).

    training_global_concurrency: int = 1
    training_cooldown_seconds: int = 900
    training_min_sequences: int = 1_000

    # ------------------------------------------------------------ ingestion

    max_products_per_sync: int = 5_000
    max_events_per_batch: int = 5_000
    event_future_window_hours: int = 24
    event_past_window_days: int = 90
    max_submission_error_samples: int = 100

    # ------------------------------------------------------------ serving

    recommendation_max_top_n: int = 100
    recommendation_max_recent_events: int = 50
    recommendation_max_exclusions: int = 200
    session_ttl_seconds: int = 1_800
    serving_driver: ServingDriverKind = ServingDriverKind.COMPOSE
    candidate_index: CandidateIndexKind = CandidateIndexKind.INPROCESS

    # SRS §6.4 pins an inference process to one tenant, and this is the pin.
    # `None` in every other process: a control API that had a tenant id would
    # have a default scope, which is the thing RLS exists to make impossible.
    # The inference app refuses to start without it.
    tenant_id: uuid.UUID | None = None

    # How often the inference process asks whether desired state moved. Ten
    # seconds because the reconciler's own loop is five: a poller slower than
    # the thing it follows adds its interval to every activation, and one
    # slower than an operator's patience is what makes a deploy feel stuck.
    inference_poll_seconds: float = 10.0

    # The reconciler's loop and the leader lock it holds while it runs. A
    # deployment that has been `progressing` for longer than the timeout has
    # failed to load, and ER-F-06 says what happens then: the previous version
    # keeps serving and the new one is marked `failed_deployment`.
    reconcile_interval_seconds: float = 5.0
    activation_timeout_seconds: float = 600.0
    #: Prefixed, because `COMPOSE_FILE` is Docker Compose's own variable and
    #: the reconciler runs `docker compose` in a process that inherits its
    #: environment. A setting named `compose_file` would silently become the
    #: default `-f` for every command the driver spawns.
    serving_compose_file: str = "deploy/single/docker-compose.serving.yml"

    # ------------------------------------------------------------ candidate index adapter

    qdrant_url: str = "http://qdrant:6334"
    qdrant_collection_prefix: str = "graphrec"
    qdrant_embedding_dim: int = 128
    qdrant_top_k: int = 100

    # ------------------------------------------------------------ observability

    log_level: str = "INFO"
    log_format: str = "json"
    prometheus_url: str = "http://localhost:9090"

    # ------------------------------------------------------------ email
    #
    # Invitations and account recovery both need out-of-band token delivery. When
    # smtp_host is unset the application falls back to the admin CLI, which
    # prints the token — see scripts/ and the Phase 2 report.

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from_address: str = "no-reply@graphrec.example"
    smtp_use_tls: bool = True

    # ------------------------------------------------------------ demo bootstrap

    demo_tenant_name: str = "GraphRec Local Demo"
    demo_registration_email: str = "owner-demo@example.org"
    demo_login_email: str = "demo-admin@example.org"
    demo_login_password: SecretStr = SecretStr("local-demo-password-change-me")

    # ------------------------------------------------------------ derived

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        """Runtime URL — the non-owner role that RLS binds."""
        return str(
            PostgresDsn.build(
                scheme="postgresql+psycopg",
                username=self.postgres_app_user,
                password=self.postgres_app_password.get_secret_value(),
                host=self.postgres_host,
                port=self.postgres_port,
                path=self.postgres_db,
            )
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def platform_database_url(self) -> str:
        """The `/v1/platform/*` connection. See `postgres_platform_user`."""
        return str(
            PostgresDsn.build(
                scheme="postgresql+psycopg",
                username=self.postgres_platform_user,
                password=self.postgres_platform_password.get_secret_value(),
                host=self.postgres_host,
                port=self.postgres_port,
                path=self.postgres_db,
            )
        )

    @property
    def owner_database_url(self) -> str:
        """Migration URL — the owner role. Never used to serve a request."""
        return str(
            PostgresDsn.build(
                scheme="postgresql+psycopg",
                username=self.postgres_owner_user,
                password=self.postgres_owner_password.get_secret_value(),
                host=self.postgres_host,
                port=self.postgres_port,
                path=self.postgres_db,
            )
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def email_delivery_available(self) -> bool:
        return self.smtp_host is not None

    @model_validator(mode="after")
    def _production_requires_real_secrets(self) -> Settings:
        """Refuse to start in production carrying a shipped default secret.

        A placeholder pepper in production would make every stored credential
        hash forgeable by anyone holding this repository.
        """
        if self.environment is not Environment.PRODUCTION:
            return self

        placeholders = {
            "api_key_hmac_pepper": "local-api-key-hmac-pepper-change-me",
            "audit_hash_secret": "replace-with-a-long-random-local-secret",
            "demo_login_password": "local-demo-password-change-me",
            "postgres_app_password": "graphrec_app_local_only",
            "postgres_owner_password": "graphrec_owner_local_only",
        }
        carried = [
            name
            for name, default in placeholders.items()
            if getattr(self, name).get_secret_value() == default
        ]
        if carried:
            raise ValueError(
                "refusing to start in production with default secrets for: "
                + ", ".join(sorted(carried))
            )
        return self

    @model_validator(mode="after")
    def _bulk_limit_exceeds_default_limit(self) -> Settings:
        """D7 — the bulk ceiling must actually be a raise on the default."""
        if self.max_bulk_body_bytes <= self.max_request_body_bytes:
            raise ValueError(
                "max_bulk_body_bytes must exceed max_request_body_bytes; "
                "bulk endpoints carry up to max_products_per_sync items"
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
