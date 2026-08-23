"""The serving domain: what runs, what it answers, and what came back.

Five modules and one rule about the boundaries between them. `deployment` reads
and moves *desired* state; `activation` records an intention; `reconciler` is
the only thing that moves *active* state, and only on an observation. `funnel`
and `recommend` are the read path, and neither can see a deployment.

That split is ER-F-06 expressed as a package layout: a request may ask for a
version to serve, and nothing but a ready replica can make it so.
"""

from __future__ import annotations
