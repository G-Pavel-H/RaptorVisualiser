"""Unit tests for serialize_tree. Uses duck-typed fakes — no RAPTOR import."""
from dataclasses import dataclass, field
from typing import Dict, List, Set

from app.serialization import serialize_tree


@dataclass
class FakeNode:
    index: int
    text: str
    children: Set[int] = field(default_factory=set)
    embeddings: Dict[str, List[float]] = field(default_factory=dict)


@dataclass
class FakeTree:
    all_nodes: Dict[int, FakeNode]
    root_nodes: Dict[int, FakeNode]
    leaf_nodes: Dict[int, FakeNode]
    num_layers: int
    layer_to_nodes: Dict[int, List[FakeNode]]


def _build_two_layer_tree() -> FakeTree:
    # layer 0: leaves 0,1,2. layer 1: root 3 with children {0,1,2}.
    n0 = FakeNode(0, "chunk a", embeddings={"OpenAI": [0.1, 0.2]})
    n1 = FakeNode(1, "chunk b", embeddings={"OpenAI": [0.3, 0.4]})
    n2 = FakeNode(2, "chunk c", embeddings={"OpenAI": [0.5, 0.6]})
    n3 = FakeNode(3, "summary", children={0, 1, 2}, embeddings={"OpenAI": [0.7, 0.8]})
    all_nodes = {n.index: n for n in (n0, n1, n2, n3)}
    return FakeTree(
        all_nodes=all_nodes,
        root_nodes={3: n3},
        leaf_nodes={0: n0, 1: n1, 2: n2},
        num_layers=1,
        layer_to_nodes={0: [n0, n1, n2], 1: [n3]},
    )


def test_serialize_basic_shape():
    tree = _build_two_layer_tree()
    out = serialize_tree(tree)

    assert out["num_layers"] == 1
    assert out["root_ids"] == [3]
    assert out["leaf_ids"] == [0, 1, 2]
    assert len(out["nodes"]) == 4
    assert len(out["edges"]) == 3


def test_serialize_layer_assignment():
    tree = _build_two_layer_tree()
    out = serialize_tree(tree)
    by_id = {n["id"]: n for n in out["nodes"]}
    assert by_id[0]["layer"] == 0
    assert by_id[3]["layer"] == 1


def test_serialize_edges_parent_to_child():
    tree = _build_two_layer_tree()
    out = serialize_tree(tree)
    assert {(e["parent"], e["child"]) for e in out["edges"]} == {(3, 0), (3, 1), (3, 2)}


def test_serialize_omits_embeddings_by_default():
    tree = _build_two_layer_tree()
    out = serialize_tree(tree)
    assert "embeddings" not in out["nodes"][0]


def test_serialize_includes_embeddings_when_asked():
    tree = _build_two_layer_tree()
    out = serialize_tree(tree, include_embeddings=True)
    assert out["nodes"][0]["embeddings"] == {"OpenAI": [0.1, 0.2]}


def test_serialize_node_ordering_stable():
    tree = _build_two_layer_tree()
    out = serialize_tree(tree)
    layers = [n["layer"] for n in out["nodes"]]
    assert layers == sorted(layers)


def test_serialize_handles_list_layer_to_nodes():
    """RAPTOR stores layer_to_nodes values as lists — exercise that path."""
    tree = _build_two_layer_tree()
    # layer_to_nodes is already a List[Node] in our fake — assert nothing breaks
    out = serialize_tree(tree)
    assert out["nodes"][0]["id"] == 0
