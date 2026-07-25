"""Unit tests for the record/replay mechanics (Phase 2).

Selection is by request signature, not call order, and a missing fixture must be
loud — both are load-bearing for the offline demo + test suite.
"""

from __future__ import annotations

import pytest

from blastradar.datahub.replay import (
    Recorder,
    ReplayClient,
    ReplayMiss,
    call_signature,
    load_recording,
)


def test_signature_is_order_independent() -> None:
    a = call_signature("get_lineage", {"urn": "u", "column": "c", "max_hops": 1})
    b = call_signature("get_lineage", {"max_hops": 1, "column": "c", "urn": "u"})
    assert a == b


def test_recorder_dedups_by_signature() -> None:
    r = Recorder()
    r("get_tags", {"urn": "u"}, ["t1"])
    r("get_tags", {"urn": "u"}, ["t1"])   # identical call -> deduped
    r("get_tags", {"urn": "v"}, [])       # different signature
    assert len(r) == 2


def _mapping(recorder: Recorder) -> dict:
    return {call_signature(c["method"], c["kwargs"]): c["result"]
            for c in recorder.calls()}


def test_replay_serves_recorded_result() -> None:
    r = Recorder()
    r("get_tags", {"urn": "u"}, ["urn:li:tag:Tier1", "urn:li:tag:x"])
    client = ReplayClient(_mapping(r))
    assert client.get_tags("u") == ["urn:li:tag:Tier1", "urn:li:tag:x"]


def test_replay_is_order_independent() -> None:
    # Two independent reads recorded in one order, replayed in the other.
    r = Recorder()
    r("get_ml_model", {"urn": "m1"}, {"name": "m1"})
    r("get_ml_model", {"urn": "m2"}, {"name": "m2"})
    client = ReplayClient(_mapping(r))
    assert client.get_ml_model("m2") == {"name": "m2"}
    assert client.get_ml_model("m1") == {"name": "m1"}


def test_replay_miss_is_loud() -> None:
    client = ReplayClient({}, source="empty")
    with pytest.raises(ReplayMiss) as exc:
        client.get_tags("never-recorded")
    assert "record-fixtures" in str(exc.value)  # points the operator at the fix


def test_replay_never_connects() -> None:
    # _ensure is a no-op; a bogus server must not matter because nothing connects.
    client = ReplayClient({}, source="empty")
    client._ensure()  # would raise/hang if it tried to build the SDK
    assert client._sdk is None


def test_recording_roundtrips_to_disk(tmp_path) -> None:
    r = Recorder()
    r("get_ml_model", {"urn": "m"}, {"name": "m", "version": "3"})
    r("test_connection", {}, None)
    path = tmp_path / "rec.json"
    n = r.save(path, description="unit test")
    assert n == 2
    client = ReplayClient(load_recording(path), source=str(path))
    assert client.get_ml_model("m") == {"name": "m", "version": "3"}
    assert client.test_connection() is None
