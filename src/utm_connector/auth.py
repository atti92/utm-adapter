"""Provider authentication helpers.

The connector can use a supplied bearer token for local development or obtain
and refresh an OAuth2 client-credentials token for a real provider deployment.
Secrets are kept in memory only and are never included in connector recordings.
"""

from __future__ import annotations

from threading import RLock
from time import monotonic
from typing import Optional

import httpx


class OAuthError(RuntimeError):
    """Raised when an OAuth token cannot be acquired."""


class OAuthClientCredentials:
    """Small OAuth2 client-credentials token cache.

    The token endpoint is called with HTTP Basic client authentication, which
    is the interoperable OAuth2 default. A short expiry skew avoids sending a
    token that is about to expire while a provider request is in flight.
    """

    def __init__(
        self,
        token_url: str,
        client_id: str,
        client_secret: str,
        *,
        scope: Optional[str] = None,
        client: httpx.Client,
        expiry_skew_s: float = 30.0,
    ) -> None:
        if not token_url:
            raise ValueError("OAuth token_url must not be empty")
        if not client_id:
            raise ValueError("OAuth client_id must not be empty")
        if not client_secret:
            raise ValueError("OAuth client_secret must not be empty")
        self.token_url = token_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.scope = scope
        self.client = client
        self.expiry_skew_s = max(0.0, expiry_skew_s)
        self._lock = RLock()
        self._access_token: Optional[str] = None
        self._expires_at = 0.0

    def get_token(self, *, force_refresh: bool = False) -> str:
        with self._lock:
            now = monotonic()
            if not force_refresh and self._access_token and now < self._expires_at:
                return self._access_token

            form = {"grant_type": "client_credentials"}
            if self.scope:
                form["scope"] = self.scope
            try:
                response = self.client.post(
                    self.token_url,
                    data=form,
                    auth=(self.client_id, self.client_secret),
                    headers={"Accept": "application/json"},
                )
                response.raise_for_status()
                body = response.json()
            except httpx.HTTPStatusError as exc:
                self.invalidate()
                raise OAuthError(
                    f"OAuth token endpoint returned HTTP {exc.response.status_code}"
                ) from exc
            except (httpx.RequestError, ValueError) as exc:
                self.invalidate()
                raise OAuthError(f"OAuth token request failed: {exc}") from exc

            if not isinstance(body, dict) or not isinstance(body.get("access_token"), str):
                self.invalidate()
                raise OAuthError("OAuth token response did not include an access_token")
            token = body["access_token"].strip()
            if not token:
                self.invalidate()
                raise OAuthError("OAuth token response included an empty access_token")

            expires_in = body.get("expires_in", 300)
            try:
                lifetime_s = float(expires_in)
            except (TypeError, ValueError) as exc:
                self.invalidate()
                raise OAuthError("OAuth token response included an invalid expires_in") from exc
            if lifetime_s <= 0:
                self.invalidate()
                raise OAuthError("OAuth token response included a non-positive expires_in")

            self._access_token = token
            self._expires_at = monotonic() + max(1.0, lifetime_s - self.expiry_skew_s)
            return token

    def invalidate(self) -> None:
        """Forget the cached token so the next request obtains a fresh one."""

        with self._lock:
            self._access_token = None
            self._expires_at = 0.0
