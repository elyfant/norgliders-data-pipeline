"""Resolves the pyglider deployment config for a mission.

Open question, tracked in the planning repo's `dependencies.md` (OGDB <->
NRT/Delayed-Mode Processing): does the pyglider deployment YAML get
generated from OGDB mission/glider metadata, or maintained separately and
just cross-referenced by mission_id/glider_id? This module is where that
decision gets implemented once made -- not decided yet.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DeploymentConfig:
    """Placeholder shape -- fields TBD once the OGDB-generated-vs-separate
    question above is settled."""

    mission_id: int


def resolve(mission_id: int) -> DeploymentConfig:
    """Resolve the deployment config for a given OGDB mission_id.

    Placeholder -- raises until the generation strategy is decided.
    """
    raise NotImplementedError(
        "deployment config resolution not yet decided -- see dependencies.md, "
        "'OGDB <-> NRT/Delayed-Mode Processing'"
    )
