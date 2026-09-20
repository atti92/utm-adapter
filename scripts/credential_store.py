"""Store or inspect a provider secret using the host OS credential store."""

from __future__ import annotations

import argparse
from getpass import getpass


def _keyring_module():
    try:
        import keyring
    except ImportError as exc:
        raise SystemExit(
            "keyring support is not installed; run `uv sync --extra credentials` first"
        ) from exc
    return keyring


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("set", "check", "delete"))
    parser.add_argument("--service", default="utm-operations-connector")
    parser.add_argument("--account", default="flight-blender-client-secret")
    args = parser.parse_args()
    keyring = _keyring_module()

    if args.action == "set":
        secret = getpass(f"Secret for {args.service}/{args.account}: ")
        if not secret:
            raise SystemExit("refusing to store an empty secret")
        keyring.set_password(args.service, args.account, secret)
        print(f"[ok] stored credential for {args.service}/{args.account}")
    elif args.action == "check":
        present = bool(keyring.get_password(args.service, args.account))
        print(
            f"[{'ok' if present else 'info'}] {'credential is present' if present else 'credential is missing'} "
            f"for {args.service}/{args.account}"
        )
        return 0 if present else 1
    else:
        keyring.delete_password(args.service, args.account)
        print(f"[ok] deleted credential for {args.service}/{args.account}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
