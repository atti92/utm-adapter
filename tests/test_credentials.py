import sys
from types import SimpleNamespace

import pytest

from utm_connector.credentials import CredentialStoreError, resolve_client_secret


def test_explicit_secret_takes_precedence_without_loading_keyring() -> None:
    assert (
        resolve_client_secret(
            client_secret="direct-secret",
            keyring_service="service",
            keyring_account="account",
        )
        == "direct-secret"
    )


def test_keyring_secret_is_resolved_without_returning_coordinates_as_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []
    fake_keyring = SimpleNamespace(
        get_password=lambda service, account: calls.append((service, account)) or "stored-secret"
    )
    monkeypatch.setitem(sys.modules, "keyring", fake_keyring)

    assert (
        resolve_client_secret(
            client_secret=None,
            keyring_service="utm-connector",
            keyring_account="flight-blender",
        )
        == "stored-secret"
    )
    assert calls == [("utm-connector", "flight-blender")]


def test_missing_keyring_secret_is_actionable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "keyring", SimpleNamespace(get_password=lambda *_: None))

    with pytest.raises(CredentialStoreError, match="no credential is stored"):
        resolve_client_secret(
            client_secret=None,
            keyring_service="utm-connector",
            keyring_account="flight-blender",
        )
