"""Optional OS credential-store integration for provider secrets."""

from __future__ import annotations


class CredentialStoreError(RuntimeError):
    """Raised when a configured OS credential cannot be read."""


def resolve_client_secret(
    *,
    client_secret: str | None,
    keyring_service: str | None,
    keyring_account: str | None,
) -> str | None:
    """Return an explicitly configured secret or resolve one from keyring.

    ``keyring`` is optional so the default local development install stays
    usable on headless CI and simulator hosts. Production deployments that
    use the credential-store mode install the ``credentials`` extra.
    """

    if client_secret:
        return client_secret
    if not keyring_service and not keyring_account:
        return None
    if not keyring_service or not keyring_account:
        raise CredentialStoreError(
            "both keyring service and keyring account must be configured"
        )

    try:
        import keyring
    except ImportError as exc:
        raise CredentialStoreError(
            "keyring support is not installed; run `uv sync --extra credentials`"
        ) from exc

    try:
        stored_secret = keyring.get_password(keyring_service, keyring_account)
    except Exception as exc:  # keyring backends expose different exception types
        raise CredentialStoreError(
            f"unable to read the OS credential store for {keyring_service}/{keyring_account}"
        ) from exc
    if not stored_secret:
        raise CredentialStoreError(
            f"no credential is stored for {keyring_service}/{keyring_account}"
        )
    return stored_secret
