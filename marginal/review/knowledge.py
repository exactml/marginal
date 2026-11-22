"""Business knowledge a review found, carried to `marginal propose` in its body.

The review already reads the diff, so it reports rules and decisions in the
same model call; a hidden marker in the posted review body hands them to the
proposal a merged PR posts, with no second call.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable

from marginal.review.schema import Knowledge

_MARKER = re.compile(r"<!-- marginal:knowledge (\[.*?\]) -->")


def knowledge_marker(knowledge: list[Knowledge]) -> str:
    """A hidden HTML comment holding `knowledge`, or `""` for none."""
    if not knowledge:
        return ""
    # `>` escaped so a statement can't end the HTML comment early.
    payload = json.dumps([k.model_dump() for k in knowledge]).replace(">", "\\u003e")
    return f"<!-- marginal:knowledge {payload} -->"


def posted_knowledge(bodies: Iterable[str | None]) -> list[Knowledge]:
    """Every piece of knowledge in the markers of `bodies`, oldest first.
    A marker that doesn't parse is skipped: anyone can edit text into a body."""
    knowledge = []
    for body in bodies:
        for payload in _MARKER.findall(body or ""):
            try:
                knowledge += [Knowledge.model_validate(item) for item in json.loads(payload)]
            except ValueError:  # bad JSON or a bad item: pydantic's errors are ValueErrors
                continue
    return knowledge
