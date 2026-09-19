import json
from datetime import datetime, timezone

from utm_connector.recording import JsonlRecorder, JsonlReplay


def test_jsonl_recorder_redaction_is_applied_by_backend_layer(tmp_path) -> None:
    path = tmp_path / "events.jsonl"
    recorder = JsonlRecorder(str(path))
    recorder.record("connector_event", {"event_type": "TEST", "value": 1})
    recorder.close()

    replayed: list[tuple[str, dict]] = []
    assert JsonlReplay(str(path)).replay(lambda kind, payload: replayed.append((kind, payload))) == 1
    assert replayed == [("connector_event", {"event_type": "TEST", "value": 1})]
    assert json.loads(path.read_text())["record_type"] == "connector_event"


def test_jsonl_recorder_round_trips_raw_mavlink_frames(tmp_path) -> None:
    path = tmp_path / "events.jsonl"
    recorder = JsonlRecorder(str(path))
    recorder.record_mavlink_frame(
        "sitl-1",
        b"\xfe\x03\x01\x02",
        received_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    recorder.close()

    frames: list[tuple[str, bytes]] = []
    assert JsonlReplay(str(path)).replay_mavlink(lambda vehicle_id, frame: frames.append((vehicle_id, frame))) == 1
    assert frames == [("sitl-1", b"\xfe\x03\x01\x02")]
    record = json.loads(path.read_text())
    assert record["record_type"] == "mavlink_frame"
    assert record["payload"]["vehicle_id"] == "sitl-1"
    assert record["payload"]["frame_b64"]
