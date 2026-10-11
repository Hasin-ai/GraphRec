"""Generate the Python SDK reference for the docs site from the SDK source itself.

    python scripts/build_sdk_docs.py          # write web/src/docs/sdkData.ts
    python scripts/build_sdk_docs.py --check  # exit 1 if sdkData.ts is out of date

Everything on the SDK page comes from ``sdks/python/src/graphrec_sdk``: the client
constructor, every namespace/resource/method signature and docstring, the HTTP route
and scope each method calls (resolved through ``_routes.ROUTES``), the error
hierarchy, enums, scope bundles, constants and the runnable examples in
``sdks/python/examples``. Nothing is hand-maintained except one-line descriptions of
the constructor arguments, and the build fails if those drift from the real signature.

Run with an interpreter that has the SDK's dependencies (httpx, pydantic), e.g.
``sdks/python/.venv``.
"""

from __future__ import annotations

import enum
import inspect
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
SDK_DIR = ROOT / "sdks" / "python"
OUT = ROOT / "web" / "src" / "docs" / "sdkData.ts"
sys.path.insert(0, str(SDK_DIR / "src"))

import graphrec_sdk as g  # noqa: E402
from graphrec_sdk import _constants as C  # noqa: E402
from graphrec_sdk import ecommerce, enums, errors, scopes  # noqa: E402
from graphrec_sdk._routes import ROUTES  # noqa: E402

try:
    from graphrec_sdk._base_client import OMIT
except ImportError:  # pragma: no cover
    OMIT = object()

# One-line descriptions of the constructor arguments. The build fails if the
# constructor gains, loses or renames an argument without updating this table.
CLIENT_PARAM_DOCS: Dict[str, str] = {
    "base_url": f"API origin. Falls back to ${C.ENV_BASE_URL}, then {C.DEFAULT_BASE_URL}.",
    "api_key": f"Storefront or integration API key ({C.API_KEY_PREFIX}…). Falls back to ${C.ENV_API_KEY}.",
    "access_token": f"Bearer token, e.g. a console access token or PLATFORM_ADMIN_TOKEN. Falls back to ${C.ENV_ACCESS_TOKEN}.",
    "email": "Tenant user email. With password, the SDK logs in and renews the token before it expires.",
    "password": "Tenant user password (used together with email).",
    "auth": "A custom Auth object (ApiKeyAuth, BearerTokenAuth, PasswordAuth) instead of the shortcuts above.",
    "timeout": "httpx timeout. Default: 30 s total, 5 s connect.",
    "max_retries": "Retries for transient failures (429, 5xx, timeouts) on idempotent requests, with exponential backoff that honours Retry-After.",
    "retry_policy": "A RetryPolicy for full control over retries; overrides max_retries.",
    "max_body_bytes": "Largest JSON body the bulk helpers send in one request (mirrors the server's 16 KiB limit).",
    "max_batch_items": "Most items the bulk helpers put in one request, independent of the byte budget.",
    "default_headers": "Extra headers sent on every request.",
    "http_client": "Bring your own httpx client (proxies, mTLS, transport mocks). The SDK does not close it.",
    "use_env": "Read GRAPHREC_* environment variables for omitted arguments.",
}


def clean_doc(text: Optional[str]) -> str:
    """Turn reST docstrings into the light markdown the page renders."""
    if not text:
        return ""
    text = re.sub(r":(?:class|meth|func|attr|data|exc|mod):`~?([^`]+)`", lambda m: "`" + m.group(1).split(".")[-1] + "`" if m.group(0).find("~") > 0 else "`" + m.group(1) + "`", text)
    text = text.replace("``", "`")
    return text.strip()


def ann(a: Any) -> str:
    if a is inspect.Parameter.empty or a is inspect.Signature.empty:
        return ""
    s = a if isinstance(a, str) else getattr(a, "__name__", str(a))
    return s.replace("typing.", "").replace("graphrec_sdk.models.", "").strip("'\"")


def default_repr(v: Any) -> Optional[str]:
    if v is inspect.Parameter.empty:
        return None
    if v is OMIT:
        return "unchanged"
    if isinstance(v, enum.Enum):
        return f"{type(v).__name__}.{v.name}"
    return repr(v)


def describe_params(func: Any, skip_self: bool = True) -> List[Dict[str, Any]]:
    sig = inspect.signature(func)
    out = []
    for i, (name, p) in enumerate(sig.parameters.items()):
        if skip_self and i == 0 and name in ("self", "cls"):
            continue
        kind = {
            p.POSITIONAL_ONLY: "positional",
            p.POSITIONAL_OR_KEYWORD: "positional",
            p.KEYWORD_ONLY: "keyword",
            p.VAR_POSITIONAL: "varargs",
            p.VAR_KEYWORD: "kwargs",
        }[p.kind]
        d = default_repr(p.default)
        out.append({
            "name": ("*" if kind == "varargs" else "**" if kind == "kwargs" else "") + name,
            "type": ann(p.annotation),
            "default": d,
            "required": d is None and kind in ("positional", "keyword"),
            "kind": kind,
        })
    return out


def pretty_signature(call: str, func: Any, skip_self: bool = True) -> str:
    sig = inspect.signature(func)
    parts: List[str] = []
    star_done = False
    for i, (name, p) in enumerate(sig.parameters.items()):
        if skip_self and i == 0 and name in ("self", "cls"):
            continue
        if p.kind == p.KEYWORD_ONLY and not star_done:
            parts.append("*")
            star_done = True
        if p.kind == p.VAR_POSITIONAL:
            star_done = True
            prefix = "*"
        elif p.kind == p.VAR_KEYWORD:
            prefix = "**"
        else:
            prefix = ""
        s = prefix + name
        t = ann(p.annotation)
        if t:
            s += f": {t}"
        d = default_repr(p.default)
        if d is not None:
            s += f" = {d}"
        parts.append(s)
    ret = ann(sig.return_annotation)
    head = f"{'async ' if inspect.iscoroutinefunction(func) else ''}{call}"
    if len(parts) <= 2 and sum(len(x) for x in parts) < 60:
        body = f"{head}({', '.join(parts)})"
    else:
        body = head + "(\n" + "".join(f"    {x},\n" for x in parts) + ")"
    return body + (f" -> {ret}" if ret else "")


_REQUEST_KEY = re.compile(r"""\.request\(\s*["']([\w.]+)["']""")
_SELF_CALL = re.compile(r"self\.(\w+)\(")


def routes_for(cls: type, method: str, depth: int = 0) -> List[str]:
    """Route keys a method calls, following calls to sibling methods once."""
    fn = getattr(cls, method, None)
    try:
        src = inspect.getsource(fn)
    except (OSError, TypeError):
        return []
    keys = _REQUEST_KEY.findall(src)
    if depth == 0:
        for sib in _SELF_CALL.findall(src):
            if sib != method and not sib.startswith("_") and hasattr(cls, sib):
                keys += routes_for(cls, sib, depth + 1)
    return list(dict.fromkeys(keys))


def route_info(key: str) -> Dict[str, Any]:
    r = ROUTES[key]
    return {
        "key": key,
        "method": r.method,
        "path": r.path,
        "auth": r.auth,
        "scopes": list(r.required_scopes),
        "idempotent": r.idempotent,
    }


def public_methods(cls: type) -> List[str]:
    names = []
    for name, fn in inspect.getmembers(cls, inspect.isfunction):
        if name.startswith("_") or not fn.__module__.startswith("graphrec_sdk"):
            continue
        names.append((inspect.getsourcelines(fn)[1], name))
    return [n for _, n in sorted(names)]


def method_doc(cls: type, name: str, call_prefix: str) -> Dict[str, Any]:
    fn = getattr(cls, name)
    keys = routes_for(cls, name)
    unknown = [k for k in keys if k not in ROUTES]
    if unknown:
        raise SystemExit(f"{cls.__name__}.{name} calls unknown route(s): {unknown}")
    return {
        "name": name,
        "call": f"{call_prefix}.{name}",
        "signature": pretty_signature(f"{call_prefix}.{name}", fn),
        "doc": clean_doc(inspect.getdoc(fn)),
        "params": describe_params(fn),
        "returns": ann(inspect.signature(fn).return_annotation),
        "routes": [route_info(k) for k in keys],
    }


def async_twin(cls: type) -> Optional[str]:
    mod = sys.modules[cls.__module__]
    twin = getattr(mod, "Async" + cls.__name__, None)
    if twin is None:
        return None
    missing = set(public_methods(cls)) - set(public_methods(twin))
    if missing:
        raise SystemExit(f"Async{cls.__name__} lacks {sorted(missing)}")
    return twin.__name__


def resource_doc(obj: Any, path: str, title: str, own_only: bool = False) -> Dict[str, Any]:
    cls = type(obj)
    names = public_methods(cls)
    if own_only:
        names = [n for n in names if n in vars(cls) or any(n in vars(b) for b in cls.__mro__[1:] if b.__module__.endswith("platform"))]
    return {
        "id": path.replace(".", "-"),
        "path": path,
        "title": title,
        "className": cls.__name__,
        "asyncClass": async_twin(cls),
        "doc": clean_doc(inspect.getdoc(cls)) if cls.__doc__ else "",
        "methods": [method_doc(cls, n, path) for n in names],
    }


def build() -> Dict[str, Any]:
    client = g.GraphRec(api_key=C.API_KEY_PREFIX + "docs", base_url="http://docs.invalid", use_env=False)

    ctor = describe_params(g.GraphRec.__init__)
    names = {p["name"] for p in ctor}
    if names != set(CLIENT_PARAM_DOCS):
        raise SystemExit(f"CLIENT_PARAM_DOCS out of sync. missing={names - set(CLIENT_PARAM_DOCS)} stale={set(CLIENT_PARAM_DOCS) - names}")
    for p in ctor:
        p["description"] = CLIENT_PARAM_DOCS[p["name"]]
        if p["name"] == "timeout":
            p["default"] = "30 s (connect 5 s)"

    client_methods = [method_doc(g.GraphRec, n, "client") for n in ("health", "ready", "meta", "plans", "with_credentials", "close")]

    namespaces = []
    ns_docs = {
        "storefront": "Calls your shop's site or backend makes with a storefront API key.",
        "tenant": "Administration of one tenant, chosen by the credential (usually email + password).",
        "platform": "Cross-tenant operations for the platform operator.",
    }
    for ns_name in ("storefront", "tenant", "platform"):
        ns = getattr(client, ns_name)
        resources = []
        if ns_name == "platform":
            ops = {"id": "client-platform", "path": "client.platform", "title": "platform (operations)", "className": "PlatformOperations",
                   "asyncClass": "AsyncPlatformOperations", "doc": clean_doc(inspect.getdoc(type(ns))),
                   "methods": [method_doc(type(ns), n, "client.platform") for n in public_methods(g.resources.platform.PlatformOperations)]}
            resources.append(ops)
        for attr in type(ns).__annotations__:
            resources.append(resource_doc(getattr(ns, attr), f"client.{ns_name}.{attr}", attr))
        namespaces.append({"name": ns_name, "path": f"client.{ns_name}", "doc": ns_docs[ns_name], "resources": resources})

    helpers = []
    for cls_name in ("EventBuilder", "EventTracker", "CatalogSync", "RecommendationSession"):
        cls = getattr(ecommerce, cls_name)
        var = {"EventBuilder": "builder", "EventTracker": "tracker", "CatalogSync": "sync", "RecommendationSession": "session"}[cls_name]
        methods = []
        for n in public_methods(cls):
            fn = getattr(cls, n)
            methods.append({"name": n, "call": f"{var}.{n}", "signature": pretty_signature(f"{var}.{n}", fn),
                            "doc": clean_doc(inspect.getdoc(fn)), "params": describe_params(fn),
                            "returns": ann(inspect.signature(fn).return_annotation), "routes": []})
        helpers.append({
            "id": "ecommerce-" + cls_name.lower(), "path": f"graphrec_sdk.ecommerce.{cls_name}", "title": cls_name,
            "className": cls_name, "asyncClass": ("Async" + cls_name) if hasattr(ecommerce, "Async" + cls_name) else None,
            "ctor": pretty_signature(cls_name, cls.__init__), "doc": clean_doc(inspect.getdoc(cls)),
            "contextManager": hasattr(cls, "__enter__"), "methods": methods,
        })

    err_classes = [c for _, c in inspect.getmembers(errors, inspect.isclass) if issubclass(c, g.GraphRecError) and c.__module__ == errors.__name__]
    err_classes.sort(key=lambda c: (len(c.__mro__), c.__name__))
    code_map = getattr(errors, "_CODE_MAP", {})
    status_map = getattr(errors, "_STATUS_MAP", {})
    error_list = []
    for c in err_classes:
        error_list.append({
            "name": c.__name__,
            "base": c.__bases__[0].__name__,
            "doc": clean_doc((inspect.getdoc(c) or "").split("\n\n")[0]),
            "statuses": sorted(s for s, k in status_map.items() if k is c),
            "codes": sorted(code for code, k in code_map.items() if k is c),
        })

    enum_list = [{"name": n, "values": [m.value for m in e]} for n, e in inspect.getmembers(enums, inspect.isclass)
                 if issubclass(e, enum.Enum) and e.__module__ == enums.__name__ and not n.startswith("_") and len(e)]

    def scope_vals(v: Any) -> Any:
        if isinstance(v, dict):
            return {str(getattr(k, "value", k)): scope_vals(x) for k, x in v.items()}
        return sorted(str(getattr(x, "value", x)) for x in v)

    scope_sets = {n: scope_vals(getattr(scopes, n)) for n in ("STOREFRONT_KEY_SCOPES", "CATALOG_SYNC_KEY_SCOPES", "API_KEY_SCOPES", "DELEGATABLE_SCOPES", "ROLE_SCOPES") if hasattr(scopes, n)}

    examples = []
    for f in sorted((SDK_DIR / "examples").glob("*.py")):
        code = f.read_text(encoding="utf-8").replace("\r\n", "\n")
        first = (code.split('"""')[1].strip().split("\n")[0]) if code.lstrip().startswith('"""') else f.stem
        examples.append({"file": f"sdks/python/examples/{f.name}", "title": first, "code": code})

    pyproject = (SDK_DIR / "pyproject.toml").read_text(encoding="utf-8")
    deps = re.search(r"dependencies = \[(.*?)\]", pyproject, re.S)
    req_py = re.search(r'requires-python = "([^"]+)"', pyproject)

    total = len(client_methods) + sum(len(r["methods"]) for ns in namespaces for r in ns["resources"])
    covered = {rt["key"] for ns in namespaces for r in ns["resources"] for m in r["methods"] for rt in m["routes"]}
    covered |= {rt["key"] for m in client_methods for rt in m["routes"]}
    uncovered = sorted(set(ROUTES) - covered)

    return {
        "version": g.__version__,
        "package": "graphrec-sdk",
        "requiresPython": req_py.group(1) if req_py else "",
        "dependencies": re.findall(r'"([^"]+)"', deps.group(1)) if deps else [],
        "constants": {
            "DEFAULT_BASE_URL": C.DEFAULT_BASE_URL, "DEFAULT_MAX_RETRIES": C.DEFAULT_MAX_RETRIES,
            "DEFAULT_MAX_BODY_BYTES": C.DEFAULT_MAX_BODY_BYTES, "DEFAULT_MAX_BATCH_ITEMS": C.DEFAULT_MAX_BATCH_ITEMS,
            "MAX_RETRY_AFTER_SECONDS": C.MAX_RETRY_AFTER_SECONDS, "TOKEN_EXPIRY_SKEW_SECONDS": C.TOKEN_EXPIRY_SKEW_SECONDS,
            "API_KEY_PREFIX": C.API_KEY_PREFIX, "ENV_BASE_URL": C.ENV_BASE_URL, "ENV_API_KEY": C.ENV_API_KEY,
            "ENV_ACCESS_TOKEN": C.ENV_ACCESS_TOKEN, "HEADER_CORRELATION_ID": C.HEADER_CORRELATION_ID,
            "HEADER_IDEMPOTENCY_KEY": C.HEADER_IDEMPOTENCY_KEY,
        },
        "clientDoc": clean_doc(inspect.getdoc(g.GraphRec)),
        "clientParams": ctor,
        "clientMethods": client_methods,
        "namespaces": namespaces,
        "helpers": helpers,
        "errors": error_list,
        "enums": enum_list,
        "scopeSets": scope_sets,
        "examples": examples,
        "stats": {"methods": total, "routes": len(ROUTES), "routesCovered": len(ROUTES) - len(uncovered), "uncoveredRoutes": uncovered},
    }


def render(data: Dict[str, Any]) -> str:
    body = json.dumps(data, indent=1, ensure_ascii=False)
    return (
        "// AUTO-GENERATED by scripts/build_sdk_docs.py from sdks/python/src/graphrec_sdk.\n"
        "// Do not edit by hand: change the SDK (docstrings, signatures, routes) and regenerate.\n"
        'import type { SdkReference } from "./sdkTypes";\n\n'
        f"export const SDK_REFERENCE: SdkReference = {body};\n"
    )


if __name__ == "__main__":
    text = render(build())
    if "--check" in sys.argv:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            print(f"{OUT.relative_to(ROOT)} is out of date; run python scripts/build_sdk_docs.py")
            sys.exit(1)
        print("sdkData.ts is up to date")
    else:
        OUT.write_text(text, encoding="utf-8", newline="\n")
        d = json.loads(text.split("= ", 1)[1].rstrip(";\n"))
        print(f"SDK {d['version']}: {d['stats']['methods']} methods, {d['stats']['routesCovered']}/{d['stats']['routes']} routes covered; uncovered: {d['stats']['uncoveredRoutes']}")
