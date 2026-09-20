"""Inspect and replay a connector JSONL recording without opening a vehicle link.

This tool is intentionally offline and read-only. It never opens a MAVLink
transport or sends a vehicle command; decoded frames are passed through the
same canonical normalizer used by the live connector.
"""

from __future__ import annotations

import argparse
import base64
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any, Sequence

from pymavlink import mavutil

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utm_connector.mavlink import MavlinkMessageNormalizer
from utm_connector.recording import JsonlReplay


def _timestamp(record: dict[str, Any]) -> datetime:
    payload = record.get("payload")
    candidate = payload.get("received_at") if isinstance(payload, dict) else None
    if not isinstance(candidate, str):
        candidate = record.get("recorded_at")
    if not isinstance(candidate, str):
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def replay_mavlink(
    replay: JsonlReplay,
    *,
    vehicle_id: str | None = None,
) -> tuple[
    Counter[str],
    dict[str, MavlinkMessageNormalizer],
    dict[str, datetime],
    int,
    int,
]:
    """Decode recorded frames into normalizers and return replay statistics."""

    frame_counts: Counter[str] = Counter()
    normalizers: dict[str, MavlinkMessageNormalizer] = {}
    parsers: dict[str, Any] = {}
    latest_timestamps: dict[str, datetime] = {}
    decoded_messages = 0
    decode_errors = 0

    for record in replay.records():
        if record.get("record_type") != "mavlink_frame":
            continue
        payload = record.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("MAVLink record payload must be an object")
        current_vehicle_id = payload.get("vehicle_id")
        if not isinstance(current_vehicle_id, str) or not current_vehicle_id:
            raise ValueError("MAVLink record vehicle_id must be a non-empty string")
        if vehicle_id is not None and current_vehicle_id != vehicle_id:
            continue
        frame_b64 = payload.get("frame_b64")
        if not isinstance(frame_b64, str):
            raise ValueError("MAVLink record frame_b64 must be a string")
        try:
            frame = base64.b64decode(frame_b64, validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError("MAVLink record frame_b64 is not valid base64") from exc
        frame_counts[current_vehicle_id] += 1
        parser = parsers.setdefault(current_vehicle_id, mavutil.mavlink.MAVLink(None))
        normalizer = normalizers.setdefault(
            current_vehicle_id, MavlinkMessageNormalizer(current_vehicle_id)
        )
        received_at = _timestamp(record)
        latest_timestamps[current_vehicle_id] = received_at
        for byte in frame:
            try:
                message = parser.parse_char(bytes([byte]))
            except Exception:
                decode_errors += 1
                break
            if message is not None:
                normalizer.ingest(message, received_at)
                decoded_messages += 1
    return frame_counts, normalizers, latest_timestamps, decoded_messages, decode_errors


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="connector JSONL recording")
    parser.add_argument("--vehicle-id", help="only replay one recorded vehicle")
    parser.add_argument(
        "--decode-mavlink",
        action="store_true",
        help="decode raw MAVLink frames through the canonical telemetry normalizer",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="fail if a decoded frame cannot be parsed or a vehicle has no heartbeat",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        records = list(JsonlReplay(str(args.input)).records())
        record_counts = Counter(str(record["record_type"]) for record in records)
        print(f"[ok] recording: {args.input}")
        print(f"  records: {len(records)}")
        for record_type, count in sorted(record_counts.items()):
            print(f"  {record_type}: {count}")
        if not args.decode_mavlink:
            return 0

        frame_counts, normalizers, latest_timestamps, decoded_messages, decode_errors = replay_mavlink(
            JsonlReplay(str(args.input)), vehicle_id=args.vehicle_id
        )
        print(f"  MAVLink frames: {sum(frame_counts.values())}")
        print(f"  decoded messages: {decoded_messages}")
        if decode_errors:
            print(f"[warn] frames with decode errors: {decode_errors}")
        missing_heartbeats = []
        for current_vehicle_id in sorted(frame_counts):
            normalizer = normalizers.get(current_vehicle_id)
            if normalizer is None:
                continue
            try:
                snapshot = normalizer.snapshot(now=latest_timestamps[current_vehicle_id])
            except ValueError:
                missing_heartbeats.append(current_vehicle_id)
                print(f"  vehicle {current_vehicle_id}: no heartbeat decoded")
                continue
            telemetry = snapshot.telemetry
            location = "no position"
            if telemetry is not None:
                location = f"{telemetry.latitude:.6f},{telemetry.longitude:.6f}"
            print(
                f"  vehicle {current_vehicle_id}: system={snapshot.identity.mavlink_system_id} "
                f"connection={snapshot.connection_state.value} quality={snapshot.quality.value} "
                f"position={location}"
            )
        if args.strict and (decode_errors or missing_heartbeats):
            return 1
    except (OSError, ValueError) as exc:
        print(f"[error] {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
