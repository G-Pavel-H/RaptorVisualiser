from app import events


def test_chunked_event_payload():
    e = events.chunked(["alpha", "beta"])
    assert e.stage == "chunked"
    assert e.layer == 0
    assert e.payload["count"] == 2
    assert e.payload["chunks"][0] == {"id": 0, "preview": "alpha"}


def test_preview_truncates_long_text():
    long = "x" * 500
    e = events.embedded(0, long)
    assert len(e.payload["preview"]) <= 120
    assert e.payload["preview"].endswith("…")


def test_event_to_dict_is_json_safe():
    e = events.node_summarized(1, 5, "hello", [0, 1, 2])
    d = e.to_dict()
    assert d == {
        "stage": "node_summarized",
        "layer": 1,
        "payload": {"node_id": 5, "preview": "hello", "children": [0, 1, 2]},
    }


def test_error_event_default_kind():
    e = events.error("boom")
    assert e.stage == "error"
    assert e.payload == {"message": "boom", "kind": "generic"}


def test_error_event_with_kind():
    e = events.error("dry", kind="out_of_funds")
    assert e.payload["kind"] == "out_of_funds"
