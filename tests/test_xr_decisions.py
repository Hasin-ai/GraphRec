"""Unit tests for XR-F-02/03/04/07/08 decision logic (no database)."""
from datetime import datetime, timedelta, timezone

import pytest

from graphrec_core.capacity import decide_capacity, serving_slots
from graphrec_core.errors import ApiError
from graphrec_core.recommendation_rules import RuleSet, category_spread, rerank
from graphrec_core.retraining.service import decide
from graphrec_core.usage.trends import bucket_starts, floor_to, validate_range

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


# ---- XR-F-02 / XR-F-03 ---------------------------------------------------
def base(**kw):
    args = dict(schedule_enabled=False, next_run_at=None, event_trigger_enabled=False, event_threshold=100,
                new_events=0, last_job_marker="none", active_job=False, now=NOW)
    args.update(kw)
    return decide(**args)


def test_schedule_fires_only_when_due_and_is_slot_idempotent():
    assert base(schedule_enabled=True, next_run_at=NOW + timedelta(seconds=1)).trigger is None
    due = base(schedule_enabled=True, next_run_at=NOW - timedelta(seconds=1))
    again = base(schedule_enabled=True, next_run_at=NOW - timedelta(seconds=1))
    assert due.trigger == "schedule" and due.request_id == again.request_id


def test_event_trigger_threshold_and_condition_identity():
    assert base(event_trigger_enabled=True, new_events=99).trigger is None
    first = base(event_trigger_enabled=True, new_events=100, last_job_marker="A")
    assert first.trigger == "events"
    # same condition (same last job) -> same idempotent request id; new job -> new condition
    assert base(event_trigger_enabled=True, new_events=150, last_job_marker="A").request_id == first.request_id
    assert base(event_trigger_enabled=True, new_events=100, last_job_marker="B").request_id != first.request_id


def test_nothing_fires_while_training_is_running_or_disabled():
    assert base(schedule_enabled=True, next_run_at=NOW - timedelta(hours=1), event_trigger_enabled=True,
                new_events=10_000, active_job=True).reason == "training_in_progress"
    assert base(new_events=10_000).trigger is None


# ---- XR-F-04 -------------------------------------------------------------
META = {
    "a1": ("shoes", NOW - timedelta(days=400)), "a2": ("shoes", NOW - timedelta(days=400)),
    "a3": ("shoes", NOW - timedelta(days=400)), "a4": ("shoes", NOW - timedelta(days=400)),
    "b1": ("hats", NOW - timedelta(days=400)), "c1": ("bags", NOW - timedelta(days=1)),
    "n1": (None, NOW - timedelta(days=400)),
}
ORDER = ["a1", "a2", "a3", "a4", "b1", "n1", "c1"]


def rules(**kw):
    values = dict(version=3, diversity_enabled=False, max_per_category=2, freshness_enabled=False,
                  freshness_weight=0.0, freshness_half_life_days=30)
    values.update(kw)
    return RuleSet(**values)


def test_rules_off_keep_relevance_order():
    assert rerank(ORDER, META, rules(), top_n=4, now=NOW) == ORDER[:4]


def test_diversity_caps_categories_and_increases_spread():
    out = rerank(ORDER, META, rules(diversity_enabled=True, max_per_category=2), top_n=4, now=NOW)
    assert out == ["a1", "a2", "b1", "n1"]
    assert category_spread(out, META) > category_spread(ORDER[:4], META)


def test_diversity_relaxes_instead_of_returning_fewer_items():
    assert len(rerank(["a1", "a2", "a3"], META, rules(diversity_enabled=True, max_per_category=1), top_n=3, now=NOW)) == 3


def test_freshness_boost_is_bounded():
    fresh = rerank(ORDER, META, rules(freshness_enabled=True, freshness_weight=0.3), top_n=7, now=NOW)
    assert fresh.index("c1") == 4 < ORDER.index("c1")  # newer item moves up within the band
    assert fresh[:4] == ORDER[:4]                       # but cannot pass the top of the list
    capped = rerank(ORDER, META, rules(freshness_enabled=True, freshness_weight=9.0), top_n=7, now=NOW)
    assert capped == fresh                              # weight is clamped to 0.3


def test_freshness_reorders_items_tied_on_upstream_score():
    # Fallback pool: equal popularity, tie broken by external id (oldest first).
    aged = {f"f{i:02d}": (None, NOW - timedelta(days=58 - 2 * i)) for i in range(30)}
    pool = sorted(aged)
    tied = {item: 0.0 for item in pool}
    off = rerank(pool, aged, rules(), top_n=10, now=NOW, scores=tied)
    on = rerank(pool, aged, rules(freshness_enabled=True, freshness_weight=0.3), top_n=10, now=NOW, scores=tied)
    age = lambda items: sum((NOW - aged[i][1]).days for i in items) / len(items)
    assert off == pool[:10]
    assert age(on) < age(off)          # freshness must measurably lower average age
    assert on[0] == "f29"              # newest item wins a pure tie


def test_freshness_does_not_override_real_score_gaps():
    aged = {"pop": (None, NOW - timedelta(days=400)), "new": (None, NOW)}
    out = rerank(["pop", "new"], aged, rules(freshness_enabled=True, freshness_weight=0.3), top_n=2, now=NOW,
                 scores={"pop": 50.0, "new": 0.0})
    assert out == ["pop", "new"]


def test_rerank_never_adds_unknown_items():
    assert rerank(["x", "a1"], META, rules(diversity_enabled=True), top_n=5, now=NOW) == ["a1"]


# ---- XR-F-07 -------------------------------------------------------------
def test_buckets_align_to_utc_and_weeks_start_monday():
    assert floor_to(datetime(2026, 10, 1, 13, 45, tzinfo=timezone.utc), "hour").hour == 13
    assert floor_to(datetime(2026, 10, 1, 13, 45, tzinfo=timezone.utc), "week").weekday() == 0
    starts = bucket_starts(NOW - timedelta(days=3), NOW, "day")
    assert len(starts) == 4 and starts[0] == datetime(2026, 9, 28, tzinfo=timezone.utc)


@pytest.mark.parametrize("start,end,gran", [(NOW, NOW, "day"), (NOW - timedelta(days=40), NOW, "hour"),
                                             (NOW.replace(tzinfo=None), NOW.replace(tzinfo=None), "day")])
def test_invalid_ranges_are_rejected(start, end, gran):
    with pytest.raises(ApiError) as exc:
        validate_range(start, end, gran)
    assert exc.value.status_code == 422


# ---- XR-F-08 -------------------------------------------------------------
def cap(**kw):
    args = dict(current=1, max_capacity=3, rpm_last_minute=0, peak_rpm_window=0, target_rpm_per_replica=60,
                seconds_since_last_change=None, stabilization_seconds=120)
    args.update(kw)
    return decide_capacity(**args)


def test_scale_up_immediately_and_clamp_to_plan_maximum():
    assert cap(rpm_last_minute=130) == type(cap())(3, "scale_up")
    assert cap(rpm_last_minute=10_000).target == 3


def test_scale_down_waits_for_stabilization_and_uses_window_peak():
    assert cap(current=3, rpm_last_minute=0, peak_rpm_window=0, seconds_since_last_change=30).reason is None
    assert cap(current=3, rpm_last_minute=0, peak_rpm_window=70, seconds_since_last_change=300).target == 2
    assert cap(current=3, rpm_last_minute=0, peak_rpm_window=0, seconds_since_last_change=300).target == 1


def test_capacity_above_new_plan_limit_is_clamped():
    assert cap(current=3, max_capacity=2) == type(cap())(2, "limit_clamp")


def test_serving_slots_follow_ready_capacity():
    limits = {"concurrent_recommendation_requests": 12, "maximum_inference_replicas": 2}
    assert serving_slots(limits, 1) == 6 and serving_slots(limits, 2) == 12 and serving_slots(limits, 5) == 12
    assert serving_slots({"concurrent_recommendation_requests": 4, "maximum_inference_replicas": 1}, 1) == 4


def test_xr_f_06_training_budget_is_the_smaller_of_plan_and_worker_cap():
    """D-11: maximum_training_duration_minutes is enforced, capped by the local worker budget."""
    from graphrec_core.dgsr.worker import LOCAL_TRAINING_BUDGET_SECONDS, training_budget_seconds
    assert training_budget_seconds(None) == LOCAL_TRAINING_BUDGET_SECONDS
    assert training_budget_seconds(30) == LOCAL_TRAINING_BUDGET_SECONDS
    assert training_budget_seconds(1) == 60
    assert training_budget_seconds(0) == 1
