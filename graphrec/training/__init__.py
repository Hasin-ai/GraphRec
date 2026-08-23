"""The training run's own vocabulary: the pipeline rail and where a run stops.

Separate from `graphrec.domain.training`, which holds the service, the
admission checks and the pipeline itself. This package holds only what both the
ORM model and the domain need to agree on — the same split
`graphrec.jobs.states` and `graphrec.catalog.eligibility` make, and for the same
mechanical reason: `graphrec.db.models.training` needs the rail, the domain
service needs the ORM model, and a package that re-exported both would close
that into a cycle.

Re-exports nothing. Import the submodule you want.
"""

from __future__ import annotations
