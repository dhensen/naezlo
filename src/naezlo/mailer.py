"""Sending email through Mailgun's HTTP API.

The rest of the app sees `Mailer`, `Mail` and `MailError` only. `app.state.mailer` is None
while Mailgun is not configured: the app then works as before and sends nothing.
"""

import logging
from dataclasses import dataclass
from typing import Annotated

import httpx2
from fastapi import Depends, Request

from naezlo.config import Settings

logger = logging.getLogger(__name__)

# One request per mail, made while the person who caused it waits for their answer.
TIMEOUT_SECONDS = 10.0


class MailError(Exception):
    """The mail was not accepted: Mailgun could not be reached or refused it."""


@dataclass(frozen=True)
class Mail:
    to: str
    subject: str
    text: str
    html: str


class Mailer:
    def __init__(
        self,
        api_key: str,
        api_url: str,
        sender: str,
        *,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        """`api_url` is the messages endpoint of the sending domain, `sender` the From line.

        `transport` replaces the network; tests pass an `httpx2.MockTransport`.
        """
        self._api_key = api_key
        self._api_url = api_url
        self._sender = sender
        self._transport = transport

    async def send(self, mail: Mail) -> None:
        """Hand the mail to Mailgun; raises `MailError` when it is not accepted."""
        data = {
            "from": self._sender,
            "to": mail.to,
            "subject": mail.subject,
            "text": mail.text,
            "html": mail.html,
        }
        try:
            async with httpx2.AsyncClient(
                timeout=TIMEOUT_SECONDS, transport=self._transport
            ) as client:
                response = await client.post(self._api_url, auth=("api", self._api_key), data=data)
                response.raise_for_status()
        except httpx2.HTTPStatusError as error:
            # The status, never the request: its headers carry the API key.
            logger.warning("Mailgun refused a mail with status %s", error.response.status_code)
            raise MailError(f"Mailgun answered {error.response.status_code}") from error
        except httpx2.HTTPError as error:
            logger.warning("Mailgun could not be reached: %s", type(error).__name__)
            raise MailError("Mailgun could not be reached") from error


def create_mailer(settings: Settings) -> Mailer | None:
    """The mailer of these settings, or None while Mailgun is not configured."""
    if settings.mailgun_api_key and settings.mailgun_api_url and settings.mail_from:
        return Mailer(settings.mailgun_api_key, settings.mailgun_api_url, settings.mail_from)
    return None


def _app_mailer(request: Request) -> Mailer | None:
    return request.app.state.mailer


# Use this in route signatures: `mailer: MailerDep` (None when no email can be sent).
MailerDep = Annotated[Mailer | None, Depends(_app_mailer)]
