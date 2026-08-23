"""The HTTP kernel both FastAPI applications are built on.

`control_api` and `inference` are separate deployable units — one is a control
plane a person signs into, the other a per-tenant data-plane process with a
model resident in memory — and the import-linter contract in `pyproject.toml`
forbids either from importing the other. They must nonetheless produce the *same*
error envelope and the *same* `X-Request-Id` behaviour, because a tenant
debugging a `429` should not have to know which process answered it.

This package is what makes that possible without a second copy. BACKEND_PLAN
§20 sketches `errors.py` and `middleware.py` inside `apps/control_api/`, which
was right while there was one app; a second app made the choice between shared
code here and two catalogues of error copy drifting apart. The Phase 11 report
records the move.

Nothing here knows about tenants, sessions or the database. It renders errors
raised by `graphrec.common.errors` and it stamps request ids — transport
concerns, and only transport concerns.
"""

from __future__ import annotations

from graphrec.http.errors import install_error_handlers, render_error
from graphrec.http.middleware import (
    REQUEST_ID_HEADER,
    BodyLimitMiddleware,
    RequestContextMiddleware,
)

__all__ = [
    "REQUEST_ID_HEADER",
    "BodyLimitMiddleware",
    "RequestContextMiddleware",
    "install_error_handlers",
    "render_error",
]
