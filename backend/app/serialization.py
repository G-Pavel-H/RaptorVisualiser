"""Serialize a RAPTOR Tree into a JSON-safe dict for the frontend.

Kept dependency-free of the raptor package (duck-typed) so it can be unit
tested without an OpenAI key or the heavy ML stack.
"""
from typing import Any, Dict, Iterable, List


def _iter_nodes(container: Any) -> Iterable[Any]:
    """RAPTOR stores root/leaf/all nodes as Dict[int, Node]; iterate values."""
    if hasattr(container, "values"):
        return container.values()
    return iter(container)


def _node_to_layer(tree: Any) -> Dict[int, int]:
    mapping: Dict[int, int] = {}
    for layer, nodes in tree.layer_to_nodes.items():
        for node in _iter_nodes(nodes):
            mapping[node.index] = layer
    return mapping


def serialize_node(node: Any, layer: int, *, include_embeddings: bool = False) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "id": node.index,
        "layer": layer,
        "text": node.text,
        "children": sorted(node.children),
    }
    if include_embeddings:
        payload["embeddings"] = {
            name: list(vec) for name, vec in (node.embeddings or {}).items()
        }
    return payload


def serialize_tree(tree: Any, *, include_embeddings: bool = False) -> Dict[str, Any]:
    """Walk a RAPTOR Tree and produce a JSON-safe dict of nodes + edges.

    Edges run from parent (higher layer) to child (lower layer), matching how
    RAPTOR stores `Node.children`.
    """
    layer_of = _node_to_layer(tree)

    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, int]] = []
    for node in _iter_nodes(tree.all_nodes):
        layer = layer_of.get(node.index, 0)
        nodes.append(serialize_node(node, layer, include_embeddings=include_embeddings))
        for child_index in node.children:
            edges.append({"parent": node.index, "child": child_index})

    nodes.sort(key=lambda n: (n["layer"], n["id"]))
    edges.sort(key=lambda e: (e["parent"], e["child"]))

    return {
        "num_layers": tree.num_layers,
        "root_ids": sorted(n.index for n in _iter_nodes(tree.root_nodes)),
        "leaf_ids": sorted(n.index for n in _iter_nodes(tree.leaf_nodes)),
        "nodes": nodes,
        "edges": edges,
    }
