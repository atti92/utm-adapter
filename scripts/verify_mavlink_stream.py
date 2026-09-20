"""Passively verify that a vehicle MAVLink stream reaches a GCS endpoint."""

from __future__ import annotations

import time
from dataclasses import dataclass

from pymavlink import mavutil


class MavlinkStreamVerificationError(RuntimeError):
    """Raised when a configured GCS endpoint does not receive a vehicle heartbeat."""


@dataclass(frozen=True)
class MavlinkStreamResult:
    """Identity observed on the passive GCS-side MAVLink stream."""

    host: str
    port: int
    system_id: int
    component_id: int


def verify_mavlink_stream(
    host: str,
    port: int,
    *,
    timeout_s: float = 10.0,
) -> MavlinkStreamResult:
    """Wait for a vehicle heartbeat without sending any MAVLink command.

    The receiver is intentionally opened only for the duration of the check.
    This keeps the normal GCS as the long-lived consumer and exercises the
    exact UDP endpoint that QGroundControl or Mission Planner will use.
    """

    if not 1 <= port <= 65535:
        raise ValueError("MAVLink stream port must be between 1 and 65535")
    if timeout_s <= 0:
        raise ValueError("MAVLink stream timeout must be positive")

    connection = None
    try:
        try:
            connection = mavutil.mavlink_connection(
                f"udpin:{host}:{port}",
                autoreconnect=False,
                udp_timeout=min(1.0, timeout_s),
            )
        except OSError as exc:
            raise MavlinkStreamVerificationError(
                f"could not listen on GCS MAVLink endpoint {host}:{port}: {exc}"
            ) from exc

        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            remaining = max(0.05, min(1.0, deadline - time.monotonic()))
            message = connection.recv_match(
                type="HEARTBEAT",
                blocking=True,
                timeout=remaining,
            )
            if message is None:
                continue
            return MavlinkStreamResult(
                host=host,
                port=port,
                system_id=int(message.get_srcSystem()),
                component_id=int(message.get_srcComponent()),
            )
    except MavlinkStreamVerificationError:
        raise
    except (OSError, AttributeError, TypeError, ValueError) as exc:
        raise MavlinkStreamVerificationError(
            f"could not read a vehicle heartbeat from GCS MAVLink endpoint "
            f"{host}:{port}: {exc}"
        ) from exc
    finally:
        if connection is not None:
            connection.close()

    raise MavlinkStreamVerificationError(
        f"no vehicle heartbeat reached GCS MAVLink endpoint {host}:{port} "
        f"within {timeout_s:.0f}s"
    )


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=14550)
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()
    try:
        result = verify_mavlink_stream(args.host, args.port, timeout_s=args.timeout)
    except (MavlinkStreamVerificationError, ValueError) as exc:
        print(f"[fail] GCS MAVLink stream: {exc}")
        return 1
    print(
        "[ok] GCS MAVLink stream verified: "
        f"{result.host}:{result.port} system={result.system_id} "
        f"component={result.component_id}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
