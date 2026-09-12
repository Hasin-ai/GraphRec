"""Contract tests: the SDK route table and models against the FastAPI source.

The backend is parsed with :mod:`ast`, so these tests need no server
dependencies. They run when the SDK lives inside the GraphRec repository
(``sdks/python``) and are skipped otherwise.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Type

import pytest
from pydantic import BaseModel

import graphrec_sdk as g
from graphrec_sdk import models as m
from graphrec_sdk.resources import api_keys as api_keys_resource
from graphrec_sdk.resources import datasets as datasets_resource
from graphrec_sdk.resources import ml as ml_resource
from graphrec_sdk.resources import platform as platform_resource
from graphrec_sdk.resources import recommendations as rec_resource
from graphrec_sdk.resources import tenants as tenants_resource

REPO_ROOT = Path(__file__).resolve().parents[3]
ROUTES_DIR = REPO_ROOT / "apps" / "api" / "routes"
SCHEMAS_DIR = REPO_ROOT / "graphrec_core" / "schemas"

pytestmark = pytest.mark.skipif(
    not ROUTES_DIR.is_dir() or not SCHEMAS_DIR.is_dir(),
    reason="GraphRec backend source not found next to the SDK",
)

HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
#: Router/endpoint dependencies that authenticate with an ``Authorization: Bearer`` secret.
BEARER_DEPENDENCIES = {"platform_administrator"}
NON_BODY_ANNOTATIONS = {
    "Request",
    "Response",
    "Session",
    "UUID",
    "str",
    "int",
    "AuthenticatedPrincipal",
    "Settings",
}


@dataclass
class ServerRoute:
    method: str
    path: str
    body: str = "none"
    authenticated: bool = False
    bearer_only: bool = False
    scopes: Set[str] = field(default_factory=set)


def _const_str(node: Optional[ast.AST]) -> Optional[str]:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _calls_in(node: ast.AST) -> List[ast.Call]:
    return [n for n in ast.walk(node) if isinstance(n, ast.Call)]


def _call_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _parse_router_file(path: Path, decorator_target: str) -> List[ServerRoute]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    prefix = ""
    router_dependencies: Set[str] = set()
    helpers: Dict[str, ast.FunctionDef] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            if _call_name(node.value) == "APIRouter":
                for kw in node.value.keywords:
                    if kw.arg == "prefix":
                        prefix = _const_str(kw.value) or ""
                    if kw.arg == "dependencies":
                        for call in _calls_in(kw.value):
                            if _call_name(call) == "Depends" and call.args:
                                router_dependencies.add(ast.unparse(call.args[0]))
        if isinstance(node, ast.FunctionDef):
            helpers[node.name] = node

    routes: List[ServerRoute] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and isinstance(decorator.func.value, ast.Name)
                and decorator.func.value.id == decorator_target
                and decorator.func.attr in HTTP_METHODS
            ):
                continue
            route = ServerRoute(
                decorator.func.attr.upper(), prefix + (_const_str(decorator.args[0]) or "")
            )
            if router_dependencies:
                route.authenticated = True
                route.bearer_only = bool(router_dependencies & BEARER_DEPENDENCIES)
            arguments = node.args.args + node.args.kwonlyargs
            defaults = (
                dict(
                    zip(
                        [a.arg for a in node.args.args[-len(node.args.defaults) :]],
                        node.args.defaults,
                    )
                )
                if node.args.defaults
                else {}
            )
            for arg in arguments:
                annotation = ast.unparse(arg.annotation) if arg.annotation else ""
                default = defaults.get(arg.arg)
                default_call = _call_name(default) if isinstance(default, ast.Call) else ""
                if annotation == "AuthenticatedPrincipal":
                    route.authenticated = True
                elif default_call == "File":
                    route.body = "multipart"
                elif default_call in {"Depends", "Header"}:
                    continue
                elif annotation and annotation.split("[")[0] not in NON_BODY_ANNOTATIONS:
                    route.body = "json"
            bodies = [node] + [
                helpers[_call_name(c)] for c in _calls_in(node) if _call_name(c) in helpers
            ]
            for body in bodies:
                for call in _calls_in(body):
                    if _call_name(call) == "require_bearer":
                        route.bearer_only = True
                    if _call_name(call) == "require_scope" and call.args:
                        scope = _const_str(call.args[0])
                        if scope:
                            route.scopes.add(scope)
            routes.append(route)
    return routes


def server_routes() -> Dict[Tuple[str, str], ServerRoute]:
    found: Dict[Tuple[str, str], ServerRoute] = {}
    for path in sorted(ROUTES_DIR.glob("*.py")):
        for route in _parse_router_file(path, "router"):
            found[(route.method, route.path)] = route
    for route in _parse_router_file(REPO_ROOT / "apps" / "api" / "main.py", "app"):
        found[(route.method, route.path)] = route
    return found


@dataclass
class SchemaField:
    name: str
    required: bool


def _schema_classes() -> Dict[str, Tuple[List[str], List[SchemaField]]]:
    classes: Dict[str, Tuple[List[str], List[SchemaField]]] = {}
    for path in [*SCHEMAS_DIR.glob("*.py"), *ROUTES_DIR.glob("*.py")]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            fields: List[SchemaField] = []
            for statement in node.body:
                if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
                    name = statement.target.id
                    if name == "model_config":
                        continue
                    value = statement.value
                    if value is None:
                        required = True
                    elif isinstance(value, ast.Call) and _call_name(value) == "Field":
                        has_default = any(
                            kw.arg in {"default", "default_factory"} for kw in value.keywords
                        )
                        first = value.args[0] if value.args else None
                        required = (
                            isinstance(first, ast.Constant) and first.value is Ellipsis
                        ) or (first is None and not has_default)
                    else:
                        required = False
                    fields.append(SchemaField(name, required))
            bases = [ast.unparse(base) for base in node.bases]
            classes[node.name] = (bases, fields)
    return classes


def schema_fields(name: str) -> Dict[str, SchemaField]:
    classes = _schema_classes()
    bases, own = classes[name]
    merged: Dict[str, SchemaField] = {}
    for base in bases:
        if base in classes:
            merged.update(schema_fields(base))
    merged.update({f.name: f for f in own})
    return merged


# -- routes -------------------------------------------------------------------------


def test_sdk_covers_exactly_the_server_routes() -> None:
    server = set(server_routes())
    sdk = {(route.method, route.path) for route in g.ROUTES.values()}
    assert sdk - server == set(), "SDK calls routes the server does not define"
    assert server - sdk == set(), "Server routes missing from the SDK"


@pytest.mark.parametrize("key", sorted(g.ROUTES), ids=str)
def test_route_semantics_match_server(key: str) -> None:
    sdk = g.ROUTES[key]
    server = server_routes()[(sdk.method, sdk.path)]
    assert sdk.body == server.body, f"body kind for {key}"
    if server.authenticated:
        assert sdk.auth in {"any", "bearer"}, f"{key} requires credentials on the server"
    else:
        assert sdk.auth in {"none", "optional"}, f"{key} is public on the server"
    assert (sdk.auth == "bearer") == server.bearer_only, f"bearer-only mismatch for {key}"
    if server.scopes:
        assert sdk.scope_enforced and set(sdk.required_scopes) == server.scopes, f"scope for {key}"
    else:
        assert not sdk.scope_enforced, f"{key} is marked enforced but the server has no scope check"


# -- response models ------------------------------------------------------------------

RESPONSE_MODELS: List[Tuple[str, Type[BaseModel]]] = [
    ("TenantRegistrationResponse", m.TenantRegistration),
    ("AuthTokenPair", m.AuthTokenPair),
    ("ApiKeyResponse", m.ApiKey),
    ("ApiKeySecretResponse", m.ApiKeyWithSecret),
    ("ApiKeyListResponse", m.ApiKeyList),
    ("SubscriptionResponse", m.Subscription),
    ("UsageDimension", m.UsageDimension),
    ("UsageSummaryResponse", m.UsageSummary),
    ("ProductResource", m.Product),
    ("ProductListResponse", m.ProductList),
    ("ProductBulkFailure", m.BulkUpsertFailure),
    ("ProductBulkUpsertResponse", m.ProductBulkUpsertResult),
    ("EventBatchResponse", m.EventBatch),
    ("DatasetSnapshotResource", m.DatasetSnapshot),
    ("DatasetSnapshotListResponse", m.DatasetSnapshotList),
    ("DatasetUploadResponse", m.DatasetUploadResult),
    ("ModelVersionResource", m.ModelVersion),
    ("ModelVersionListResponse", m.ModelVersionList),
    ("TrainingJobResource", m.TrainingJob),
    ("TrainingJobListResponse", m.TrainingJobList),
    ("DeploymentStatus", m.DeploymentStatus),
    ("ReplicaItem", m.Replica),
    ("ReplicaStatusResponse", m.ReplicaStatus),
    ("AutoscalingStatus", m.AutoscalingStatus),
    ("QualitySummary", m.QualitySummary),
    ("MetricsSummary", m.MetricsSummary),
    ("RecommendationItem", m.RecommendationItem),
    ("RecommendationResponse", m.Recommendations),
    ("FeedbackResponse", m.FeedbackReceipt),
    ("PlatformTenantResource", m.PlatformTenant),
    ("PlatformTenantListResponse", m.PlatformTenantList),
    ("PlatformPlanResource", m.PricingPlan),
    ("PlatformQuotaOverride", m.QuotaOverride),
    ("PlatformFailureItem", m.PlatformFailure),
    ("PlatformFailureListResponse", m.PlatformFailureList),
    ("PlatformAuditItem", m.AuditRecord),
    ("PlatformAuditListResponse", m.AuditRecordList),
]

#: Fields the SDK computes itself and never expects from the server.
SDK_ONLY_FIELDS = {"request_count"}


@pytest.mark.parametrize(("schema", "model"), RESPONSE_MODELS, ids=[s for s, _ in RESPONSE_MODELS])
def test_response_models_match_server_schemas(schema: str, model: Type[BaseModel]) -> None:
    server = schema_fields(schema)
    sdk = model.model_fields
    missing = set(server) - set(sdk)
    assert not missing, f"{model.__name__} lacks server fields {missing}"
    unexpected_required = {
        name for name, info in sdk.items() if info.is_required() and name not in server
    }
    assert not unexpected_required
    assert set(sdk) - set(server) <= SDK_ONLY_FIELDS


# -- request payloads -------------------------------------------------------------------

REQUEST_BODIES = [
    ("ProductUpsert", lambda: g.ProductInput(external_id="a", title="b").model_dump()),
    ("EventSubmit", lambda: g.EventInput(event_type="view").model_dump()),
    (
        "ModelVersionCreate",
        lambda: ml_resource._version_body("v1", "simplified_dgsr", {"a": 1}, "uri"),
    ),
    (
        "TrainingJobCreate",
        lambda: ml_resource._job_body(
            "simplified_dgsr", "3f0e2b8e-9c1d-4c1e-8e2a-000000000001", {"a": 1}
        ),
    ),
    ("DatasetSnapshotCreate", lambda: datasets_resource._snapshot_body(None, "weekly")),
    ("ApiKeyCreateRequest", lambda: api_keys_resource._create_body("k", ["catalog:read"], None)),
    ("ApiKeyRotateRequest", lambda: api_keys_resource._rotate_body("reason", 0)),
    (
        "RecommendationRequest",
        lambda: rec_resource._recommendation_body(
            user_id="u", top_n=5, context={}, exclude_product_ids=["x"]
        ),
    ),
    (
        "ImpressionFeedback",
        lambda: rec_resource._feedback_body(
            "rec-1", None, None, None, items=rec_resource._items("rec-1", ["a"])
        ),
    ),
    (
        "ClickFeedback",
        lambda: rec_resource._feedback_body(
            "rec-1", None, None, None, external_product_id="a", position=1, impression_event_id="i"
        ),
    ),
    (
        "ConversionFeedback",
        lambda: rec_resource._feedback_body(
            "rec-1", None, None, None, external_product_id="a", position=1, value=1
        ),
    ),
    ("TenantStatusUpdate", lambda: platform_resource._status_body("suspended")),
    ("QuotaOverrideUpdate", lambda: platform_resource._quota_body({"accepted_events": 1})),
    ("LoginRequest", lambda: {"email": "a@b.test", "password": "x"}),
    ("SetupPasswordRequest", lambda: tenants_resource._setup_body("t" * 43, "x" * 8, "a@b.test")),
    ("TenantRegistrationRequest", lambda: {"name": "n", "admin_email": "a@b.test"}),
]


@pytest.mark.parametrize(("schema", "build"), REQUEST_BODIES, ids=[s for s, _ in REQUEST_BODIES])
def test_request_bodies_fit_server_schemas(schema: str, build) -> None:  # type: ignore[no-untyped-def]
    server = schema_fields(schema)
    body = build()
    unknown = set(body) - set(server)
    assert not unknown, f"SDK sends fields {unknown} that {schema} does not declare"
    required = {name for name, f in server.items() if f.required}
    assert required <= set(body), f"SDK omits required {schema} fields {required - set(body)}"


# -- scopes -----------------------------------------------------------------------------


def _module_assignments(path: Path) -> Dict[str, ast.AST]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: Dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value:
            found[node.target.id] = node.value
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    found[target.id] = node.value
    return found


def _string_set(node: ast.AST, names: Dict[str, ast.AST]) -> Set[str]:
    if isinstance(node, ast.Name):
        return _string_set(names[node.id], names)
    if isinstance(node, ast.Call) and node.args:  # frozenset({...}) / frozenset([...])
        return _string_set(node.args[0], names)
    if isinstance(node, (ast.Set, ast.List, ast.Tuple)):
        return {str(_const_str(element)) for element in node.elts}
    raise AssertionError(f"Unsupported scope expression: {ast.unparse(node)}")


def test_role_and_delegation_scopes_match_server() -> None:
    service = _module_assignments(REPO_ROOT / "graphrec_core" / "auth" / "service.py")
    role_node = service["ROLE_SCOPES"]
    assert isinstance(role_node, ast.Dict)
    server_roles = {
        str(_const_str(key)): _string_set(value, service)
        for key, value in zip(role_node.keys, role_node.values)
        if key is not None
    }
    assert server_roles == {role: set(scopes) for role, scopes in g.ROLE_SCOPES.items()}

    api_key_scopes = _module_assignments(REPO_ROOT / "graphrec_core" / "api_keys" / "scopes.py")
    assert _string_set(api_key_scopes["API_KEY_COMPATIBLE_SCOPES"], api_key_scopes) == set(
        g.API_KEY_SCOPES
    )
    assert _string_set(api_key_scopes["ADMIN_DELEGATED_SCOPES"], api_key_scopes) == set(
        g.DELEGATABLE_SCOPES["tenant_administrator"]
    )
    assert _string_set(api_key_scopes["DEVELOPER_DELEGATED_SCOPES"], api_key_scopes) == set(
        g.DELEGATABLE_SCOPES["tenant_developer"]
    )
