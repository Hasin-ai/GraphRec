"""Glass-box recommendation serving pipeline.

Stages (see ``pipeline.run``):

0. admission            - in the route (Redis slots / RPM / quota)
1. query building       - DGSR encodes stored history + session clicks
2. candidate retrieval  - dgsr_personalized, session_neighbors,
                          popular_in_category, trending (each optional)
3. eligibility          - one SQL query against the servable catalog
4. scoring              - exact DGSR score + popularity prior + agreement
5. re-ranking           - MMR diversity, then the tenant's policy rules
6. guarantee            - top-up from trending / last good list, explain trace
"""
from graphrec_core.serving.ranking import (  # noqa: F401
    Candidate,
    WEIGHTS,
    combine_scores,
    mmr_order,
    percentile_ranks,
    primary_reason,
)
