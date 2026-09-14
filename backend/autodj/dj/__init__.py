"""Pure decision logic: candidate retrieval criteria, ranking, transition planning.

Takes feature dataclasses, returns decisions. No database, no HTTP, no filesystem.
"""

from autodj.dj.plan import plan_transition
from autodj.dj.rank import rank_candidates
from autodj.dj.retrieve import retrieve_candidates
from autodj.dj.types import RankedCandidate, RegionInfo, TrackCandidate, TransitionPlan

__all__ = [
    "RankedCandidate",
    "RegionInfo",
    "TrackCandidate",
    "TransitionPlan",
    "plan_transition",
    "rank_candidates",
    "retrieve_candidates",
]
