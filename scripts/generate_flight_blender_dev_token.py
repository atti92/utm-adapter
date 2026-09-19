"""Generate an unsigned JWT accepted by Flight Blender's local auth bypass."""

from __future__ import annotations

import argparse
import base64
import json


def _encode(value: dict[str, str]) -> str:
    raw = json.dumps(value, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def generate_token(
    *,
    audience: str = "testflight.flightblender.com",
    scope: str = "flightblender.write flightblender.read",
) -> str:
    """Return a development-only unsigned JWT for Flight Blender's local bypass."""

    header = _encode({"alg": "none", "typ": "JWT"})
    claims = _encode({"iss": "dummy", "aud": audience, "scope": scope})
    return f"{header}.{claims}."


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audience", default="testflight.flightblender.com")
    parser.add_argument("--scope", default="flightblender.write flightblender.read")
    args = parser.parse_args()

    print(generate_token(audience=args.audience, scope=args.scope))


if __name__ == "__main__":
    main()
