"""Sign in with Google: a small typed wrapper around Authlib's OpenID Connect client.

Authlib ships no type information, so it is kept behind this module. The rest of the app
sees `GoogleClient`, `GoogleIdentity` and `GoogleLoginError` only.
"""

from dataclasses import dataclass
from typing import Any

import httpx2
from authlib.common.errors import AuthlibBaseError  # pyright: ignore[reportMissingTypeStubs]
from authlib.integrations.starlette_client import OAuth  # pyright: ignore[reportMissingTypeStubs]
from joserfc.errors import JoseError
from starlette.requests import Request
from starlette.responses import Response

GOOGLE_METADATA_URL = "https://accounts.google.com/.well-known/openid-configuration"


class GoogleLoginError(Exception):
    """The sign-in could not be completed: bad state, a refusal by Google, an invalid ID token."""


class GoogleUnavailableError(GoogleLoginError):
    """Google could not be reached or answered with an HTTP error."""


@dataclass(frozen=True)
class GoogleIdentity:
    """What the ID token says about the person who signed in."""

    sub: str
    email: str
    email_verified: bool
    name: str | None
    picture: str | None


def _text(claims: dict[str, Any], key: str) -> str | None:
    value = claims.get(key)
    return value.strip() or None if isinstance(value, str) else None


class GoogleClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        """`transport` replaces the network; tests pass an `httpx2.MockTransport`."""
        client_kwargs: dict[str, Any] = {
            "scope": "openid email profile",
            "code_challenge_method": "S256",
        }
        if transport is not None:
            client_kwargs["transport"] = transport
        oauth: Any = OAuth()
        # The endpoints and signing keys come from Google's discovery document, which is
        # fetched on first use and kept for the lifetime of the client.
        self._client: Any = oauth.register(
            name="google",
            client_id=client_id,
            client_secret=client_secret,
            server_metadata_url=GOOGLE_METADATA_URL,
            client_kwargs=client_kwargs,
        )

    async def authorize_redirect(self, request: Request, redirect_uri: str) -> Response:
        """A redirect to Google's consent page. State, nonce and PKCE verifier go in the session."""
        try:
            return await self._client.authorize_redirect(request, redirect_uri)
        except httpx2.HTTPError as exc:
            raise GoogleUnavailableError(str(exc)) from exc

    async def fetch_identity(self, request: Request) -> GoogleIdentity:
        """Finish the flow on the callback request and return the verified ID token's claims.

        Authlib checks the state against the session, exchanges the code for tokens and
        validates the ID token (signature, issuer, audience, expiry, nonce).
        """
        try:
            token: dict[str, Any] = await self._client.authorize_access_token(request)
        except httpx2.HTTPError as exc:
            raise GoogleUnavailableError(str(exc)) from exc
        except (AuthlibBaseError, JoseError) as exc:
            raise GoogleLoginError(str(exc)) from exc

        userinfo: Any = token.get("userinfo")
        if userinfo is None:
            raise GoogleLoginError("Google returned no ID token")
        claims: dict[str, Any] = dict(userinfo)
        sub = _text(claims, "sub")
        email = _text(claims, "email")
        if sub is None or email is None:
            raise GoogleLoginError("The ID token has no sub or email")
        return GoogleIdentity(
            sub=sub,
            email=email,
            # Only a real `true` counts; a missing claim or the string "false" does not.
            email_verified=claims.get("email_verified") is True,
            name=_text(claims, "name"),
            picture=_text(claims, "picture"),
        )
