"""XR-F-02 / XR-F-03 / XR-NF-03: scheduled and event-triggered retraining.

A tenant administrator stores one policy per tenant. The scheduler process
(``graphrec_core.scheduler``) evaluates enabled policies inside each tenant's
row-level-security context and requests training through the same
``ModelRegistryService.create_training_job`` path as the API, so cooldown,
plan quota, the one-active-training rule and data sufficiency are enforced
identically. New versions are registered as ``eligible``; activation stays a
separate administrator decision.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from graphrec_core.database.tenancy import set_local_tenant
from graphrec_core.database.models import AuditLog, CustomerEvent, RetrainingPolicy, TrainingJob
from graphrec_core.errors import ApiError
from graphrec_core.schemas.retraining import RetrainingPolicyResource, RetrainingPolicyUpdate
from graphrec_core.settings import get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Decision:
    trigger: str | None  # "schedule", "events" or None
    request_id: str | None = None
    reason: str = ""


def decide(*, schedule_enabled: bool, next_run_at: datetime | None, event_trigger_enabled: bool,
           event_threshold: int, new_events: int, last_job_marker: str, active_job: bool,
           now: datetime) -> Decision:
    """Pure trigger decision (unit-tested).

    * Schedule fires once per slot: the deterministic request id embeds the
      slot time, so a repeated evaluation of the same slot is idempotent.
    * The event trigger fires once per condition: the counter is "events
      accepted since the latest training job was created", so it resets as
      soon as any job (manual or automatic) starts, and the request id embeds
      that job marker so a racing evaluation cannot start a second job.
    * Nothing fires while a job is queued or running (XR-NF-03).
    """
    if active_job:
        return Decision(None, reason="training_in_progress")
    if schedule_enabled and next_run_at is not None and now >= next_run_at:
        return Decision("schedule", f"retrain-schedule-{next_run_at.strftime('%Y%m%dT%H%M%S')}")
    if event_trigger_enabled and new_events >= event_threshold:
        return Decision("events", f"retrain-events-{last_job_marker}-{event_threshold}")
    return Decision(None, reason="not_due")


class RetrainingService:
    def __init__(self, db: Session, principal=None, correlation_id: UUID | None = None):
        self.db = db
        self.principal = principal
        self.correlation_id = correlation_id or uuid4()

    # ---- read model ----------------------------------------------------
    def _latest_job(self, tenant_id: UUID) -> TrainingJob | None:
        return self.db.scalar(select(TrainingJob).where(TrainingJob.tenant_id == tenant_id)
                              .order_by(TrainingJob.created_at.desc()).limit(1))

    def new_events_since_last_training(self, tenant_id: UUID) -> tuple[int, TrainingJob | None]:
        latest = self._latest_job(tenant_id)
        query = select(func.count(CustomerEvent.id)).where(CustomerEvent.tenant_id == tenant_id)
        if latest is not None:
            query = query.where(CustomerEvent.created_at > latest.created_at)
        return int(self.db.scalar(query) or 0), latest

    def _active_job(self, tenant_id: UUID) -> bool:
        return self.db.scalar(select(TrainingJob.id).where(
            TrainingJob.tenant_id == tenant_id, TrainingJob.status.in_(["queued", "running"])).limit(1)) is not None

    def _policy(self, tenant_id: UUID, *, lock: bool = False) -> RetrainingPolicy | None:
        query = select(RetrainingPolicy).where(RetrainingPolicy.tenant_id == tenant_id)
        if lock:
            query = query.with_for_update()
        return self.db.scalar(query)

    def get_policy(self, tenant_id: UUID) -> RetrainingPolicyResource:
        policy = self._policy(tenant_id)
        new_events, latest = self.new_events_since_last_training(tenant_id)
        settings = get_settings()
        base = dict(
            tenant_id=tenant_id, new_events_since_last_training=new_events,
            last_training_requested_at=latest.created_at if latest else None,
            training_in_progress=self._active_job(tenant_id),
            minimum_interval_minutes=settings.retraining_min_interval_minutes,
        )
        if policy is None:
            return RetrainingPolicyResource(**base, schedule_enabled=False, interval_minutes=1440,
                event_trigger_enabled=False, event_threshold=1000, epochs=3, configured=False)
        return RetrainingPolicyResource(**base, configured=True,
            schedule_enabled=policy.schedule_enabled, interval_minutes=policy.interval_minutes,
            next_run_at=policy.next_run_at if policy.schedule_enabled else None,
            event_trigger_enabled=policy.event_trigger_enabled, event_threshold=policy.event_threshold,
            epochs=policy.epochs, last_evaluated_at=policy.last_evaluated_at, last_trigger=policy.last_trigger,
            last_outcome=policy.last_outcome, last_outcome_detail=policy.last_outcome_detail,
            last_outcome_at=policy.last_outcome_at, last_job_id=policy.last_job_id, updated_at=policy.updated_at)

    # ---- write model ---------------------------------------------------
    def update_policy(self, tenant_id: UUID, payload: RetrainingPolicyUpdate) -> RetrainingPolicyResource:
        settings = get_settings()
        if payload.interval_minutes < settings.retraining_min_interval_minutes:
            raise ApiError(422, "validation_failed", "The retraining interval is below the configured minimum.",
                details={"fields": [{"field": "interval_minutes",
                    "message": f"Must be at least {settings.retraining_min_interval_minutes} minutes."}]})
        now = datetime.now(timezone.utc)
        policy = self._policy(tenant_id, lock=True)
        if policy is None:
            policy = RetrainingPolicy(tenant_id=tenant_id, updated_at=now)
            self.db.add(policy)
            previous = None
        else:
            previous = (policy.schedule_enabled, policy.interval_minutes)
        policy.schedule_enabled = payload.schedule_enabled
        policy.interval_minutes = payload.interval_minutes
        policy.event_trigger_enabled = payload.event_trigger_enabled
        policy.event_threshold = payload.event_threshold
        policy.epochs = payload.epochs
        policy.updated_at = now
        if not payload.schedule_enabled:
            policy.next_run_at = None
        elif previous != (True, payload.interval_minutes) or policy.next_run_at is None:
            # Newly enabled or re-timed schedules start one interval from now.
            policy.next_run_at = now + timedelta(minutes=payload.interval_minutes)
        self._audit(tenant_id, "retraining_policy_updated", outcome="succeeded", details={
            "schedule_enabled": payload.schedule_enabled, "interval_minutes": payload.interval_minutes,
            "event_trigger_enabled": payload.event_trigger_enabled, "event_threshold": payload.event_threshold,
            "epochs": payload.epochs})
        self.db.commit()
        set_local_tenant(self.db, tenant_id)  # RLS context is transaction-scoped
        return self.get_policy(tenant_id)

    # ---- scheduler -----------------------------------------------------
    def evaluate(self, tenant_id: UUID, now: datetime | None = None) -> Decision:
        """Evaluate one tenant's policy; caller has set the tenant RLS context."""
        from graphrec_core.models_reg.service import ModelRegistryService
        from graphrec_core.schemas.models import TrainingJobCreate

        now = now or datetime.now(timezone.utc)
        policy = self._policy(tenant_id, lock=True)
        if policy is None or not (policy.schedule_enabled or policy.event_trigger_enabled):
            self.db.rollback()
            return Decision(None, reason="disabled")
        new_events, latest = self.new_events_since_last_training(tenant_id)
        marker = latest.created_at.strftime('%Y%m%dT%H%M%S%f') if latest else "none"
        decision = decide(schedule_enabled=policy.schedule_enabled, next_run_at=policy.next_run_at,
            event_trigger_enabled=policy.event_trigger_enabled, event_threshold=policy.event_threshold,
            new_events=new_events, last_job_marker=marker, active_job=self._active_job(tenant_id), now=now)
        policy.last_evaluated_at = now
        slot_due = bool(policy.schedule_enabled and policy.next_run_at and now >= policy.next_run_at)
        if slot_due:
            # Advance the slot whether or not this evaluation can start a job,
            # so a missed or blocked slot is skipped instead of retried forever.
            slot = policy.next_run_at
            while slot <= now:
                slot += timedelta(minutes=policy.interval_minutes)
            policy.next_run_at = slot
        if decision.trigger is None:
            if slot_due:
                policy.last_trigger, policy.last_outcome_at = "schedule", now
                policy.last_outcome, policy.last_outcome_detail = f"skipped:{decision.reason}"[:48], "A scheduled slot passed while training was already in progress."
            self.db.commit()
            return decision
        tenant_policy = {"trigger": decision.trigger, "epochs": policy.epochs, "new_events": new_events}
        policy.last_trigger = decision.trigger
        policy.last_outcome_at = now
        self.db.flush()
        try:
            job = ModelRegistryService(self.db, None, self.correlation_id).create_training_job(
                tenant_id, TrainingJobCreate(request_id=decision.request_id,
                                             configuration={"mode": "train", "epochs": policy.epochs}))
        except ApiError as exc:
            self.db.rollback()
            set_local_tenant(self.db, tenant_id)
            policy = self._policy(tenant_id, lock=True)
            policy.last_evaluated_at, policy.last_trigger, policy.last_outcome_at = now, decision.trigger, now
            if decision.trigger == "schedule" and policy.next_run_at and policy.next_run_at <= now:
                slot = policy.next_run_at
                while slot <= now:
                    slot += timedelta(minutes=policy.interval_minutes)
                policy.next_run_at = slot
            policy.last_outcome, policy.last_outcome_detail = f"blocked:{exc.code}"[:48], str(exc)[:500]
            self._audit(tenant_id, "retraining_triggered", outcome="failed", details={**tenant_policy, "reason": exc.code})
            self.db.commit()
            logger.info("Retraining for tenant %s blocked by %s", tenant_id, exc.code)
            return Decision(None, reason=exc.code)
        # create_training_job commits; record the outcome in a new transaction.
        set_local_tenant(self.db, tenant_id)
        policy = self._policy(tenant_id, lock=True)
        policy.last_outcome, policy.last_outcome_detail = "training_requested", None
        policy.last_job_id, policy.last_trigger, policy.last_outcome_at = job.id, decision.trigger, now
        self._audit(tenant_id, "retraining_triggered", outcome="succeeded", details={**tenant_policy, "job_id": str(job.id)})
        self.db.commit()
        logger.info("Retraining for tenant %s requested job %s via %s", tenant_id, job.id, decision.trigger)
        return decision

    def _audit(self, tenant_id: UUID, action: str, *, outcome: str, details: dict) -> None:
        self.db.add(AuditLog(id=uuid4(), tenant_id=tenant_id,
            actor_type=self.principal.actor_type if self.principal else "system",
            actor_reference=self.principal.actor_reference if self.principal else None,
            action_type=action, resource_type="retraining_policy", resource_reference=tenant_id,
            outcome=outcome, correlation_reference=self.correlation_id,
            redacted_details=details, occurred_at=datetime.now(timezone.utc)))
