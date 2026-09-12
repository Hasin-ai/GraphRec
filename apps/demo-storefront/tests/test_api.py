from __future__ import annotations

import httpx
import pytest
from graphrec_sdk import ServiceUnavailableError, deterministic_id

from app.proof import gate, pairwise_similarity, proof_status
from app.routes.recommendations import order_id_for
from fixtures.personas import PERSONAS, SEED_HISTORY
from fixtures.products import BY_ID, PRODUCTS
from tests.conftest import MODEL_VERSION, Harness, as_persona, build_harness, status_error

API = "/api/demo"


# -- identity -------------------------------------------------------------------------


async def test_session_defaults_to_new_visitor_and_sets_cookies(api: httpx.AsyncClient) -> None:
    r = await api.get(f"{API}/session")
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["persona"]["key"] == "guest"
    assert body["data"]["persona"]["userId"] is None
    assert body["data"]["sessionId"].startswith("sess_")
    assert body["meta"]["freshSession"] is True
    assert r.cookies["facet_demo_user"] == "guest"
    assert r.cookies["facet_demo_session"] == body["data"]["sessionId"]
    assert [p["key"] for p in body["data"]["personas"]] == ["maya", "noah", "lina", "guest"]


async def test_two_browsers_keep_separate_personas(api: httpx.AsyncClient, harness: Harness) -> None:
    maya = as_persona("maya", "sess_maya_window_0001")
    noah = as_persona("noah", "sess_noah_window_0002")
    await api.post(f"{API}/recommendations", json={"topN": 3}, cookies=maya)
    await api.post(f"{API}/recommendations", json={"topN": 3}, cookies=noah)
    calls = harness.client.recommendations.calls
    assert [c["user_id"] for c in calls] == ["demo-maya", "demo-noah"]
    assert [c["context"]["demo_persona"] for c in calls] == ["maya", "noah"]


async def test_persona_switch_validates_and_rewrites_cookie(api: httpx.AsyncClient) -> None:
    ok = await api.post(f"{API}/session/persona", json={"persona": "Lina"}, cookies=as_persona("maya"))
    assert ok.status_code == 200
    assert ok.json()["data"]["persona"]["key"] == "lina"
    assert ok.json()["meta"]["previous"] == "maya"
    assert ok.cookies["facet_demo_user"] == "lina"
    bad = await api.post(f"{API}/session/persona", json={"persona": "admin"})
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "unknown_persona"
    extra = await api.post(f"{API}/session/persona", json={"persona": "maya", "userId": "demo-noah"})
    assert extra.status_code == 422  # unknown fields are refused, so identity cannot be smuggled in


async def test_forged_persona_cookie_falls_back_to_new_visitor(api: httpx.AsyncClient, harness: Harness) -> None:
    await api.post(f"{API}/recommendations", json={"topN": 3}, cookies=as_persona("demo-admin; drop"))
    assert harness.client.recommendations.calls[0]["kind"] == "session"


# -- catalog --------------------------------------------------------------------------


async def test_products_list_hides_unavailable_and_filters_by_category(api: httpx.AsyncClient) -> None:
    r = await api.get(f"{API}/products")
    assert r.status_code == 200
    ids = [p["externalId"] for p in r.json()["data"]]
    assert len(ids) == 23 and PRODUCTS[2]["external_id"] not in ids
    assert r.json()["data"][0]["price"] == "24.00"
    assert r.json()["data"][0]["accent"] == "#C9D8CD"
    skin = await api.get(f"{API}/products", params={"category": "skincare"})
    assert {p["category"] for p in skin.json()["data"]} == {"skincare"}
    bad = await api.get(f"{API}/products", params={"category": "toys"})
    assert bad.status_code == 422


async def test_product_detail_and_404(api: httpx.AsyncClient) -> None:
    r = await api.get(f"{API}/products/skin-cream-01")
    assert r.status_code == 200
    assert r.json()["data"]["title"] == "Barrier Repair Cream"
    assert r.json()["data"]["brand"] == "Northstar"
    disabled = await api.get(f"{API}/products/{PRODUCTS[2]['external_id']}")
    assert disabled.status_code == 200 and disabled.json()["data"]["available"] is False
    missing = await api.get(f"{API}/products/nope")
    assert missing.status_code == 404
    assert missing.json()["error"] == {"code": "not_found", "message": "That product does not exist in this store.", "correlationId": "cid-404"}


# -- events ---------------------------------------------------------------------------


async def test_browser_actions_map_to_tracker_events_with_server_identity(api: httpx.AsyncClient, harness: Harness) -> None:
    cookies = as_persona("noah", "sess_noah_000000000001")
    r = await api.post(f"{API}/events", json={"action": "view", "productId": "hair-curl-01", "surface": "product_detail"}, cookies=cookies)
    assert r.status_code == 202
    assert r.json()["data"]["eventType"] == "view"
    await api.post(f"{API}/events", json={"action": "add_to_cart", "productId": "hair-curl-01", "quantity": 2, "price": "26.00", "surface": "cart"}, cookies=cookies)
    await api.post(f"{API}/events", json={"action": "search", "query": " curl cream "}, cookies=cookies)
    guest = await api.post(f"{API}/events", json={"action": "view", "productId": "hair-oil-01"})
    assert guest.status_code == 202
    view, cart, search, anon = harness.tracker.events
    assert view.user_id == "demo-noah" and view.external_product_id == "hair-curl-01"
    assert view.context["session_id"] == "sess_noah_000000000001"
    assert view.context["surface"] == "product_detail" and view.context["demo_persona"] == "noah"
    assert cart.event_type == "add_to_cart" and cart.context["quantity"] == 2 and cart.context["price"] == "26.00"
    assert search.event_type == "search" and search.context["query"] == "curl cream"
    assert anon.user_id is None and anon.context["demo_persona"] == "guest"


async def test_event_validation(api: httpx.AsyncClient) -> None:
    assert (await api.post(f"{API}/events", json={"action": "view"})).status_code == 422
    assert (await api.post(f"{API}/events", json={"action": "purchase", "productId": "x"})).status_code == 422
    assert (await api.post(f"{API}/events", json={"action": "view", "productId": "x", "userId": "demo-lina"})).status_code == 422
    assert (await api.post(f"{API}/events", json={"action": "search", "query": "   "})).status_code == 422


# -- recommendations ------------------------------------------------------------------


async def test_recommendations_hydrate_in_rank_order_and_record_impression(api: httpx.AsyncClient, harness: Harness) -> None:
    harness.client.recommendations.default_ranking = ["frag-edp-01", PRODUCTS[2]["external_id"], "ghost-sku", "skin-cream-01", "hair-oil-01"]
    r = await api.post(f"{API}/recommendations", json={"topN": 5, "excludeProductIds": ["hair-oil-01", "hair-oil-01"], "surface": "product_detail"}, cookies=as_persona("maya"))
    assert r.status_code == 200
    data = r.json()["data"]
    assert [(i["externalId"], i["position"]) for i in data["items"]] == [("frag-edp-01", 1), ("skin-cream-01", 4)]
    prov = data["provenance"]
    assert prov["proofStatus"] == "serving_preview"
    assert prov["rawStrategy"] == "personalized"
    assert prov["modelVersionId"] == MODEL_VERSION
    assert prov["excludedCount"] == 1 and prov["omittedProductCount"] == 2
    assert prov["impressionEventId"] == "imp_" + prov["requestId"]
    call = harness.client.recommendations.calls[0]
    assert call["exclude"] == ["hair-oil-01"] and call["context"]["surface"] == "product_detail"
    assert harness.client.feedback.impressions[0]["request_id"] == prov["requestId"]


async def test_new_visitor_uses_session_recommendations_and_is_labelled_fallback(api: httpx.AsyncClient, harness: Harness) -> None:
    r = await api.post(f"{API}/recommendations", json={"topN": 4, "recentProductIds": ["skin-mist-01"]}, cookies=as_persona("guest", "sess_guest_00000000001"))
    prov = r.json()["data"]["provenance"]
    assert prov["proofStatus"] == "catalog_fallback" and prov["fallbackUsed"] is True and prov["modelVersionId"] is None
    call = harness.client.recommendations.calls[0]
    assert call["kind"] == "session" and call["session_id"] == "sess_guest_00000000001" and call["recent"] == ["skin-mist-01"]


async def test_placeholder_serving_is_never_called_verified_by_default(api: httpx.AsyncClient) -> None:
    r = await api.post(f"{API}/recommendations", json={"topN": 3}, cookies=as_persona("maya"))
    assert r.json()["data"]["provenance"]["proofStatus"] == "serving_preview"


async def test_verified_only_for_the_exact_configured_version() -> None:
    assert proof_status(fallback_used=False, model_version_id="v1", verified=True, verified_version_id="v1") == "model_verified"
    assert proof_status(fallback_used=False, model_version_id="v2", verified=True, verified_version_id="v1") == "serving_preview"
    assert proof_status(fallback_used=False, model_version_id="v1", verified=False, verified_version_id="v1") == "serving_preview"
    assert proof_status(fallback_used=False, model_version_id=None, verified=True, verified_version_id="") == "serving_preview"
    assert proof_status(fallback_used=True, model_version_id="v1", verified=True, verified_version_id="v1") == "catalog_fallback"


async def test_verified_flag_flows_through_the_api_when_versions_match() -> None:
    h = build_harness(model_proof_verified=True, model_proof_version_id=MODEL_VERSION)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=h.app), base_url="http://t") as api:
        async with h.app.router.lifespan_context(h.app):
            r = await api.post(f"{API}/recommendations", json={"topN": 3}, cookies=as_persona("maya"))
            assert r.json()["data"]["provenance"]["proofStatus"] == "model_verified"
            h.client.recommendations.model_version = "3f0e2b8e-9c1d-4c1e-8e2a-000000000002"
            r = await api.post(f"{API}/recommendations", json={"topN": 3}, cookies=as_persona("maya"))
            assert r.json()["data"]["provenance"]["proofStatus"] == "serving_preview"


async def test_recommendation_failure_degrades_to_an_unavailable_shelf(api: httpx.AsyncClient, harness: Harness) -> None:
    harness.client.recommendations.fail_with = status_error(ServiceUnavailableError, 503, "service_unavailable", "cid-rec")
    r = await api.post(f"{API}/recommendations", json={"topN": 3}, cookies=as_persona("maya"))
    assert r.status_code == 200
    assert r.json()["data"] == {"available": False, "reason": "GraphRec answered 503 service_unavailable.", "correlationId": "cid-rec"}
    assert r.json()["meta"]["code"] == "upstream_error"
    products = await api.get(f"{API}/products")
    assert products.status_code == 200  # the catalog is unaffected


async def test_click_feedback_links_the_remembered_impression(api: httpx.AsyncClient, harness: Harness) -> None:
    recs = (await api.post(f"{API}/recommendations", json={"topN": 3}, cookies=as_persona("lina"))).json()["data"]
    rid = recs["provenance"]["requestId"]
    r = await api.post(f"{API}/feedback/click", json={"requestId": rid, "productId": recs["items"][1]["externalId"], "position": 2}, cookies=as_persona("lina"))
    assert r.status_code == 200 and r.json()["data"]["accepted"] is True
    click = harness.client.feedback.clicks[0]
    assert click["request_id"] == rid and click["position"] == 2 and click["impression_event_id"] == "imp_" + rid
    unknown = await api.post(f"{API}/feedback/click", json={"requestId": "rec_unknown", "productId": "skin-mist-01", "position": 1})
    assert unknown.status_code == 200 and harness.client.feedback.clicks[1]["impression_event_id"] is None


# -- purchase -------------------------------------------------------------------------


async def test_purchase_emits_deterministic_order_lines_and_reports_duplicates(api: httpx.AsyncClient, harness: Harness) -> None:
    body = {"lines": [{"productId": "skin-cream-01", "quantity": 1}, {"productId": "skin-serum-01", "quantity": 2}], "clientOrderKey": "order-key-abc123"}
    first = await api.post(f"{API}/purchase", json=body, cookies=as_persona("maya"))
    assert first.status_code == 200
    data = first.json()["data"]
    assert data["orderId"] == order_id_for("maya", "order-key-abc123")
    assert data["total"] == "96.00" and data["lines"][1]["lineTotal"] == "58.00"
    assert data["acceptedCount"] == 2 and data["duplicateCount"] == 0
    events = harness.client.events.batches[0]
    assert [e.event_type for e in events] == ["purchase", "purchase"]
    assert events[0].user_id == "demo-maya" and events[0].context["order_id"] == data["orderId"]
    assert events[0].event_id == deterministic_id("purchase", data["orderId"], 1, prefix="evt")
    assert events[1].context == {**events[1].context, "quantity": 2, "price": "29.00", "currency": "USD"}
    replay = await api.post(f"{API}/purchase", json=body, cookies=as_persona("maya"))
    assert replay.json()["data"]["orderId"] == data["orderId"]
    assert replay.json()["data"]["duplicateCount"] == 2 and replay.json()["data"]["acceptedCount"] == 0


async def test_purchase_rejects_unknown_or_unavailable_products(api: httpx.AsyncClient, harness: Harness) -> None:
    r = await api.post(f"{API}/purchase", json={"lines": [{"productId": PRODUCTS[2]["external_id"], "quantity": 1}], "clientOrderKey": "order-key-abc123"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "unknown_product"
    assert harness.client.events.batches == []


# -- compare --------------------------------------------------------------------------


async def test_compare_reports_identical_rankings_honestly(api: httpx.AsyncClient, harness: Harness) -> None:
    r = await api.get(f"{API}/compare", params={"topN": 4, "exclude": ["skin-mist-01"]})
    assert r.status_code == 200
    data = r.json()["data"]
    assert [c["persona"]["key"] for c in data["columns"]] == ["maya", "noah", "lina", "guest"]
    maya = data["columns"][0]
    assert maya["repeatable"] is True and maya["provenance"]["proofStatus"] == "serving_preview"
    assert all(i["shared"] for i in maya["items"])  # every persona got the same list
    assert data["columns"][3]["provenance"]["proofStatus"] == "catalog_fallback"
    s = data["summary"]
    assert s["knownPersonasIdentical"] is True and s["distinctOrderings"] == 1 and s["gatePassed"] is False
    assert "not yet user-specific" in s["gateReason"]
    assert s["excludedProductIds"] == ["skin-mist-01"]
    assert all(c["exclude"] == ["skin-mist-01"] and c["top_n"] == 4 for c in harness.client.recommendations.calls)
    assert len(harness.client.recommendations.calls) == 8  # 4 personas x 2 (repeatability)
    assert harness.client.feedback.impressions == []  # the lab never records impressions
    pair = next(p for p in data["pairs"] if {p["a"], p["b"]} == {"Maya", "Noah"})
    assert pair["overlap"] == 4 and pair["jaccard"] == 1.0


async def test_compare_detects_per_user_rankings_but_still_requires_verification(api: httpx.AsyncClient, harness: Harness) -> None:
    harness.client.recommendations.rankings = {
        "demo-maya": ["skin-cream-01", "skin-serum-01", "skin-mist-01"],
        "demo-noah": ["hair-curl-01", "hair-oil-01", "skin-mist-01"],
        "demo-lina": ["frag-edp-01", "frag-solid-01", "skin-mist-01"],
    }
    data = (await api.get(f"{API}/compare", params={"topN": 3})).json()["data"]
    s = data["summary"]
    assert s["knownPersonasIdentical"] is False and s["distinctOrderings"] == 4
    assert s["gatePassed"] is False and "not been recorded as verified" in s["gateReason"]
    maya_noah = next(p for p in data["pairs"] if {p["a"], p["b"]} == {"Maya", "Noah"})
    assert maya_noah["overlap"] == 1 and maya_noah["jaccard"] == 0.2
    assert data["columns"][3]["items"] and not any(i["shared"] for i in data["columns"][0]["items"][:2])


async def test_compare_survives_one_failing_persona(api: httpx.AsyncClient, harness: Harness) -> None:
    harness.client.recommendations.fail_with = status_error(ServiceUnavailableError, 503, "service_unavailable")
    data = (await api.get(f"{API}/compare")).json()["data"]
    assert all(c["error"] and c["items"] == [] for c in data["columns"])
    assert data["summary"]["gatePassed"] is False and data["pairs"] == []


def test_gate_logic() -> None:
    same = {"maya": ["a", "b"], "noah": ["a", "b"]}
    diff = {"maya": ["a", "b"], "noah": ["b", "c"]}
    assert gate(known_rankings=same, any_model_version=True, all_repeatable=True, any_fallback_for_known=False, verified_status_everywhere=False)[0] is False
    assert gate(known_rankings=diff, any_model_version=False, all_repeatable=True, any_fallback_for_known=False, verified_status_everywhere=True)[0] is False
    assert gate(known_rankings=diff, any_model_version=True, all_repeatable=False, any_fallback_for_known=False, verified_status_everywhere=True)[0] is False
    assert gate(known_rankings=diff, any_model_version=True, all_repeatable=True, any_fallback_for_known=True, verified_status_everywhere=True)[0] is False
    assert gate(known_rankings=diff, any_model_version=True, all_repeatable=True, any_fallback_for_known=False, verified_status_everywhere=True)[0] is True
    pairs = pairwise_similarity({"a": ["x", "y"], "b": ["y", "z"], "c": []}, {"a": "A", "b": "B", "c": "C"})
    assert [(p.overlap, p.jaccard) for p in pairs] == [(1, 0.33), (0, 0.0), (0, 0.0)]


# -- health & hygiene -----------------------------------------------------------------


async def test_health_and_error_envelopes(api: httpx.AsyncClient, harness: Harness) -> None:
    ok = await api.get(f"{API}/health")
    assert ok.json()["data"] == {"storefront": "ok", "graphrec": "ok", "graphrecBaseUrl": "http://graphrec.test", "proofConfigured": False, "proofVersionId": None, "catalogProducts": 23, "correlationId": None}
    harness.client.healthy = False
    down = await api.get(f"{API}/health")
    assert down.json()["data"]["graphrec"] == "unreachable" and down.json()["data"]["correlationId"] == "cid-503"
    unknown = await api.get(f"{API}/nothing")
    assert unknown.status_code == 404 and unknown.json()["error"]["code"] == "not_found"
    big = await api.post(f"{API}/events", content=b"x" * 40_000, headers={"content-type": "application/json"})
    assert big.status_code == 413


def test_seed_fixtures_are_consistent() -> None:
    for persona, history in SEED_HISTORY.items():
        assert PERSONAS[persona].user_id
        assert 10 <= len(history) <= 16
        assert {e[0] for e in history} >= {"view", "click", "add_to_cart", "purchase"}
        for _, product_id, _ in history:
            assert product_id in BY_ID, f"{persona} history references unknown {product_id}"
