"""Design test 6: nothing after the separator is ever rendered.

The prefix is public — the console prints it, the server logs it as the actor —
and everything after the `.` is 256 bits shown once and never again. The failure
this guards against is silent: nobody notices a credential in a log line until
somebody else does. That is why the secret is a name-mangled slot behind
`__slots__` rather than a documented convention, and why this file exists to
keep it one.
"""

from __future__ import annotations

import copy
import json
import logging
import pickle
import pprint

import pytest

from graphrec_sdk import ConfigurationError, Credential, GraphRec
from tests.sdk.conftest import DOMAIN, KEY, SECRET, TENANT, Recorder, Reply, envelope, make_client


def _renderings(value: object) -> list[str]:
    return [repr(value), str(value), pprint.pformat(value), f"{value}", format(value)]


@pytest.mark.parametrize("rendering", _renderings(Credential(KEY)))
def test_the_credential_renders_its_prefix_and_not_its_secret(rendering: str) -> None:
    assert SECRET not in rendering
    assert "gr_live_7Kq4" in rendering


def test_the_client_renders_its_hosts_and_not_its_secret() -> None:
    client = make_client(Recorder(replies=[Reply()]))
    for rendering in _renderings(client):
        assert SECRET not in rendering
    assert "gr_live_7Kq4" in repr(client)


def test_the_secret_is_not_on_any_attribute_a_logger_would_walk() -> None:
    # A structured logger does not call `__repr__`; it walks `__dict__`. The
    # secret is a name-mangled slot on a `__slots__` class, which is invisible to
    # that walk — which is the entire reason for the slots.
    credential = Credential(KEY)
    assert not hasattr(credential, "__dict__")
    assert SECRET not in str(vars(make_client(Recorder(replies=[Reply()]))))


def test_the_secret_survives_neither_pickling_nor_copying() -> None:
    # Pickling a client into a task queue, or deep-copying it into a fixture, is
    # how a credential ends up in a payload nobody thought was a payload.
    credential = Credential(KEY)
    for attempt in (lambda: pickle.dumps(credential), lambda: copy.deepcopy(credential)):
        with pytest.raises(TypeError, match="cannot be pickled or copied"):
            attempt()


def test_the_secret_is_not_in_a_logging_record(caplog: pytest.LogCaptureFixture) -> None:
    client = make_client(Recorder(replies=[Reply()]))
    with caplog.at_level(logging.INFO):
        logging.getLogger("test").info("starting up with %s", client, extra={"client": client})

    rendered = "\n".join(record.getMessage() for record in caplog.records)
    assert SECRET not in rendered
    assert SECRET not in str(caplog.text)


def test_the_secret_is_reachable_exactly_once_by_the_header_that_carries_it() -> None:
    assert Credential(KEY).authorization == f"Bearer {KEY}"


def test_a_configuration_error_about_the_credential_does_not_quote_it() -> None:
    # A message that echoes the value puts it in the one place people paste most
    # freely, which is a bug report.
    with pytest.raises(ConfigurationError) as caught:
        Credential("sk_live_something.secret-looking-value")
    assert "secret-looking-value" not in str(caught.value)


def test_the_secret_is_not_in_an_error_raised_from_a_failed_call() -> None:
    recorder = Recorder(replies=[Reply(status=401, body=envelope("auth", "invalid_credentials"))])
    with make_client(recorder) as client, pytest.raises(Exception) as caught:  # noqa: PT011
        client.recommendations.for_customer(request_id="r-1", customer_id="c-1")

    rendered = " ".join([str(caught.value), repr(caught.value), pprint.pformat(caught.value.args)])
    assert SECRET not in rendered


def test_the_secret_is_not_in_json_of_anything_the_client_exposes() -> None:
    client = make_client(Recorder(replies=[Reply()]))
    assert SECRET not in json.dumps({"hosts": client.hosts, "key": client.credential_prefix})


def test_the_prefix_is_exposed_deliberately_because_support_needs_it() -> None:
    client: GraphRec = make_client(Recorder(replies=[Reply()]))
    assert client.credential_prefix == "gr_live_7Kq4"


@pytest.mark.parametrize(
    ("value", "why"),
    [
        ("", "an empty string"),
        ("gr_live_7Kq4", "no separator"),
        ("gr_live_7Kq4.", "nothing after the separator"),
        ("live_7Kq4.secret", "the wrong namespace"),
        ("grk_live_7Kq4.secret", "the prefix the /integration page prints, which is wrong"),
    ],
)
def test_the_credential_is_validated_by_shape_before_a_request_is_built(
    value: str, why: str
) -> None:
    with pytest.raises(ConfigurationError):
        Credential(value)
    # And through the constructor, which is where a caller actually meets it.
    with pytest.raises(ConfigurationError):
        GraphRec(api_key=value, tenant_id=TENANT, domain=DOMAIN)
