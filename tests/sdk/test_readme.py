"""Design test 7: the README's examples compile and run.

Three checks, because each catches a different way documentation rots. The text
of every fenced block equals the matching region of `examples.py`, so an example
cannot be edited in one place only. Every block has a region and every region
has a block, so neither half can be deleted quietly. And every example is
executed against the real client over a mock transport, so a snippet that no
longer type-checks or calls a method that was renamed fails here rather than in
somebody's first hour with the SDK.
"""

from __future__ import annotations

import inspect
import re
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from tests.sdk import examples
from tests.sdk.conftest import CONTROL, DATA, KEY, TENANT, Recorder, Reply
from tests.sdk.fixtures import ACCEPTED, FAILED, FEEDBACK, RECEIPT, RECOMMENDATION, SUCCEEDED

if TYPE_CHECKING:
    from collections.abc import Iterator

README = (Path(__file__).resolve().parents[2] / "sdk" / "python" / "README.md").read_text()
SOURCE = Path(inspect.getfile(examples)).read_text()

BLOCK = re.compile(r"<!-- example: (\S+) -->\n```python\n(.*?)\n```", re.DOTALL)
REGION = re.compile(r"# region (\S+)\n(.*?)\n\s*# endregion \1", re.DOTALL)

BLOCKS = {name: body.strip("\n") for name, body in BLOCK.findall(README)}
REGIONS = {name: textwrap.dedent(body).strip("\n") for name, body in REGION.findall(SOURCE)}


def test_the_extraction_found_something() -> None:
    # A floor. A regex that silently matched nothing would make every comparison
    # below a comparison of two empty strings.
    assert len(BLOCKS) >= 9, sorted(BLOCKS)


def test_every_block_has_a_region_and_every_region_has_a_block() -> None:
    assert BLOCKS.keys() == REGIONS.keys()


def test_no_python_block_escaped_annotation() -> None:
    # Counting fences catches the snippet added without a marker, which is the
    # one that would never be executed and so would never be caught drifting.
    assert README.count("```python\n") == len(BLOCKS)


@pytest.mark.parametrize("name", sorted(BLOCKS))
def test_the_readme_block_is_the_code_that_runs(name: str) -> None:
    assert BLOCKS[name] == REGIONS[name]


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch) -> Iterator[Recorder]:
    """Every client the examples build talks to this recorder.

    The examples construct their own clients — that is the point of them — so the
    transport is substituted underneath rather than injected, and the credentials
    come from the environment the README tells a reader to set.
    """
    recorder = Recorder(replies=[Reply()])
    real_sync, real_async = httpx.Client, httpx.AsyncClient

    def sync_client(*args: Any, **kwargs: Any) -> httpx.Client:
        kwargs.setdefault("transport", httpx.MockTransport(recorder.handle))
        return real_sync(*args, **kwargs)

    def async_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs.setdefault("transport", httpx.MockTransport(recorder.handle))
        return real_async(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", sync_client)
    monkeypatch.setattr(httpx, "AsyncClient", async_client)
    monkeypatch.setenv("GRAPHREC_API_KEY", KEY)
    monkeypatch.setenv("GRAPHREC_TENANT_ID", TENANT)
    return recorder


def _paths(recorder: Recorder) -> list[str]:
    return [str(call.url) for call in recorder.calls]


def test_the_constructor_example_derives_the_two_hosts(wired: Recorder) -> None:
    with examples.construct() as gr:
        assert gr.hosts == {"control": CONTROL, "data": DATA}
        assert gr.credential_prefix == "gr_live_7Kq4"


def test_the_import_example_imports_the_client(wired: Recorder) -> None:
    from graphrec_sdk import GraphRec

    assert examples.importing() is GraphRec


def test_the_recommendation_example_calls_the_data_plane(
    wired: Recorder, capsys: pytest.CaptureFixture[str]
) -> None:
    wired.replies = [Reply(body=RECOMMENDATION)]
    with examples.construct() as gr:
        answer = examples.recommend(gr)

    assert _paths(wired) == [f"{DATA}/v1/recommendations"]
    body = wired.bodies[0]
    assert body["customer_id"] == "customer-1"
    assert body["top_n"] == 10
    assert body["exclude_product_ids"] == ["sku-9"]
    assert answer.items[0].external_product_id == "sku-1"
    assert capsys.readouterr().out.strip() == "1 sku-1 0.91"


def test_the_feedback_example_reports_against_the_request_it_was_given(
    wired: Recorder,
) -> None:
    wired.replies = [Reply(body=RECOMMENDATION), Reply(body=FEEDBACK), Reply(body=FEEDBACK)]
    with examples.construct() as gr:
        answer = examples.recommend(gr)
        examples.report(gr, answer)

    assert _paths(wired)[1:] == [
        f"{DATA}/v1/feedback/impressions",
        f"{DATA}/v1/feedback/conversions",
    ]
    impressions, conversions = wired.bodies[1], wired.bodies[2]
    # The tie between a recommendation and what happened to it is `request_id`.
    # Reporting under a fresh one loses the join the ranker learns from.
    assert impressions["request_id"] == RECOMMENDATION["request_id"]
    assert impressions["events"][0]["event_id"] == "req-1:sku-1"
    assert conversions["events"][0]["value"] == 19.99


def test_the_catalogue_example_submits_then_polls(
    wired: Recorder, capsys: pytest.CaptureFixture[str]
) -> None:
    wired.replies = [Reply(status=202, body=ACCEPTED), Reply(body=SUCCEEDED)]
    with examples.construct() as gr:
        examples.sync(gr)

    assert _paths(wired) == [
        f"{CONTROL}/v1/products:bulk-upsert",
        f"{CONTROL}/v1/submissions/{ACCEPTED['submission_id']}",
    ]
    assert wired.bodies[0]["sync_id"] == "2026-08-24-nightly"
    # The submission is accepted, not applied: the counts only exist after the poll.
    assert "accepted=1" in capsys.readouterr().out


def test_the_event_example_sends_an_aware_timestamp(wired: Recorder) -> None:
    wired.replies = [Reply(body=RECEIPT)]
    with examples.construct() as gr:
        receipt = examples.ingest(gr)

    assert _paths(wired) == [f"{CONTROL}/v1/events"]
    assert wired.bodies[0]["occurred_at"].endswith("+00:00")
    # A repeat is a success, not a 409. The receipt says which it was.
    assert receipt.status == "duplicate_confirmed"


def test_the_error_example_returns_none_rather_than_failing_the_page(
    wired: Recorder,
) -> None:
    from tests.sdk.conftest import envelope

    wired.replies = [Reply(status=429, body=envelope("limit", "recommendation_quota_exhausted"))]
    with examples.construct() as gr:
        assert examples.handle(gr) is None

    assert len(wired.calls) == 1, "an exhausted quota is attempted exactly once"


def test_the_submission_failure_example_reports_the_per_item_reasons(
    wired: Recorder,
) -> None:
    wired.replies = [Reply(status=202, body=ACCEPTED), Reply(body=FAILED)]
    with examples.construct() as gr:
        assert examples.failed(gr) == ["sku-1: Title is required."]


async def test_the_async_example_makes_the_same_call(wired: Recorder) -> None:
    wired.replies = [Reply(body=RECOMMENDATION)]
    answer = await examples.asynchronous()

    assert _paths(wired) == [f"{DATA}/v1/recommendations"]
    assert answer.request_id == RECOMMENDATION["request_id"]
