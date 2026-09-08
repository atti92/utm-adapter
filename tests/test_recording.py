import json

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
