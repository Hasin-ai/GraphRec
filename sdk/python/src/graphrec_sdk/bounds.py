"""The published bounds, named where the server's copy lives.

They are the defaults of a standard estate — several are settings
(`recommendation_max_top_n`, `max_products_per_sync`) and a self-hosted
deployment could raise them — which is why nothing here invents a bound the
schema does not publish. The server remains the authority; checking locally only
shortens the loop on the mistakes that are certain, and turns a per-item
rejection that arrives inside a submission minutes later into a `ValidationError`
at the caller's desk.

The two planes do **not** agree on identifier length, and that is not an
oversight to smooth over. The data plane takes ``maxLength: 200``
(`frontend/openapi.json`); a bulk ingestion item is refused above 120
(`MAX_EXTERNAL_ID_LENGTH`, `graphrec/domain/ingestion/validation.py`), which
matches the `ck_*_external_id_length` constraints in migrations 0007 and 0008. A
single shared constant would have to be one of the two and would be wrong about
the other.
"""

from __future__ import annotations

#: `frontend/openapi.json` — `request_id`, `customer_id`, `session_id`, feedback ids.
MAX_DATA_PLANE_ID = 200
#: `graphrec/domain/ingestion/validation.py` — and the DB check constraints.
MAX_EXTERNAL_ID = 120
MAX_TITLE = 500
MAX_CATEGORY = 120
MAX_DESCRIPTION = 4_000

#: `recommendation_max_top_n`, `recommendation_max_recent_events`, `..._exclusions`.
MAX_TOP_N = 100
MAX_RECENT_EVENTS = 50
MAX_EXCLUSIONS = 200

#: `max_products_per_sync`, `max_events_per_batch`.
MAX_PRODUCTS_PER_SYNC = 5_000
MAX_EVENTS_PER_BATCH = 5_000

#: No published ceiling on a feedback batch; the 16 KB body limit is the real
#: bound. This is the SDK's own, chosen to fail before the request does.
MAX_FEEDBACK_EVENTS = 1_000
