"""Event types streamed from a live RAPTOR build."""
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Literal, Optional

Stage = Literal[
    "chunked",
    "embedded",
    "cluster_formed",
    "node_summarized",
    "layer_complete",
    "done",
    "error",
]


@dataclass
class BuildEvent:
    stage: Stage
    layer: int = 0
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _preview(text: str, n: int = 120) -> str:
    text = text.strip().replace("\n", " ")
    return text if len(text) <= n else text[: n - 1] + "…"


def chunked(chunks: List[str]) -> BuildEvent:
    return BuildEvent(
        stage="chunked",
        layer=0,
        payload={
            "count": len(chunks),
            "chunks": [{"id": i, "preview": _preview(c)} for i, c in enumerate(chunks)],
        },
    )


def embedded(node_id: int, text: str) -> BuildEvent:
    return BuildEvent(
        stage="embedded",
        layer=0,
        payload={"node_id": node_id, "preview": _preview(text)},
    )


def cluster_formed(layer: int, cluster_index: int, child_ids: List[int]) -> BuildEvent:
    return BuildEvent(
        stage="cluster_formed",
        layer=layer,
        payload={"cluster_index": cluster_index, "child_ids": sorted(child_ids)},
    )


def node_summarized(layer: int, node_id: int, text: str, children: List[int]) -> BuildEvent:
    return BuildEvent(
        stage="node_summarized",
        layer=layer,
        payload={
            "node_id": node_id,
            "preview": _preview(text),
            "children": sorted(children),
        },
    )


def layer_complete(layer: int, node_count: int) -> BuildEvent:
    return BuildEvent(
        stage="layer_complete",
        layer=layer,
        payload={"node_count": node_count},
    )


def done(tree_json: Dict[str, Any]) -> BuildEvent:
    return BuildEvent(stage="done", payload={"tree": tree_json})


def error(message: str) -> BuildEvent:
    return BuildEvent(stage="error", payload={"message": message})
