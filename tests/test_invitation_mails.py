"""The emails about invitations: what Mailgun is sent, and what happens when it fails."""

from collections.abc import Iterator
from urllib.parse import parse_qs

import httpx2
import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from naezlo.config import Settings
from naezlo.mailer import Mail, Mailer, MailError, create_mailer
from naezlo.models import MembershipRole
from tests.helpers import add_member, sign_in
from tests.test_invitations import ada_org, invitation_count

API_URL = "https://api.eu.mailgun.net/v3/mg.example.com/messages"
SENDER = "Naezlo <no-reply@mg.example.com>"


class FakeMailgun:
    """Answers what the app posts to Mailgun and keeps the mails it was given."""

    def __init__(self) -> None:
        self.mails: list[dict[str, str]] = []
        self.requests: list[httpx2.Request] = []
        # Set to make the next sends fail: a status, or an exception to raise.
        self.status = 200
        self.error: Exception | None = None

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        if self.status != 200:
            return httpx2.Response(self.status, json={"message": "Forbidden"})
        fields = parse_qs(request.content.decode())
        self.mails.append({name: values[0] for name, values in fields.items()})
        return httpx2.Response(200, json={"id": "<1@mg.example.com>", "message": "Queued."})


@pytest.fixture
def mailgun(app: FastAPI) -> Iterator[FakeMailgun]:
    fake = FakeMailgun()
    app.state.mailer = Mailer(
        "key-test", API_URL, SENDER, transport=httpx2.MockTransport(fake.handler)
    )
    yield fake
    app.state.mailer = None


async def test_an_invitation_is_emailed_to_an_address_without_an_account(
    client: AsyncClient, mailgun: FakeMailgun, settings: Settings
) -> None:
    _, url = await ada_org(client)

    response = await client.post(url, json={"email": "Grace@Example.com", "role": "admin"})

    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == {"status", "message", "email_sent", "member", "invitation"}
    assert body["status"] == "invited"
    assert body["email_sent"] is True
    assert body["message"] == (
        "An invitation was emailed to grace@example.com. They join when they sign in."
    )

    [request] = mailgun.requests
    assert str(request.url) == API_URL
    # Basic authentication with the user "api" and the key.
    assert request.headers["authorization"] == httpx2.BasicAuth("api", "key-test")._auth_header  # pyright: ignore[reportPrivateUsage]
    [mail] = mailgun.mails
    assert mail["from"] == SENDER
    assert mail["to"] == "grace@example.com"
    assert mail["subject"] == "Ada invited you to Ada's organization on Naezlo"
    login = f"{settings.public_base_url}/login"
    assert (
        "Ada (ada@example.com) invited you to join Ada's organization on Naezlo as an admin."
        in (mail["text"])
    )
    assert f"Sign in: {login}" in mail["text"]
    assert "sign in with the Google account of grace@example.com" in mail["text"]
    assert f'href="{login}"' in mail["html"]


async def test_names_are_escaped_in_the_html_and_kept_on_one_line_in_the_subject(
    client: AsyncClient, mailgun: FakeMailgun
) -> None:
    ada = await sign_in(client, name="Ada <b>Bold</b>")
    org_id = ada["organizations"][0]["id"]
    renamed = await client.patch(f"/api/orgs/{org_id}", json={"name": "R&D <script>"})
    assert renamed.status_code == 200, renamed.text

    await client.post(f"/api/orgs/{org_id}/invitations", json={"email": "grace@example.com"})

    [mail] = mailgun.mails
    assert "\n" not in mail["subject"]
    assert "<script>" not in mail["html"]
    assert "<b>Bold</b>" not in mail["html"]
    assert "R&amp;D &lt;script&gt;" in mail["html"]
    # The text part is not HTML: it says the names as they are.
    assert "R&D <script>" in mail["text"]


async def test_someone_with_an_account_is_told_they_were_added(
    client: AsyncClient, other_client: AsyncClient, mailgun: FakeMailgun, settings: Settings
) -> None:
    _, url = await ada_org(client)
    await sign_in(other_client, "grace@example.com", "Grace")
    slug = (await client.get("/api/me")).json()["organizations"][0]["slug"]

    response = await client.post(url, json={"email": "grace@example.com", "role": "member"})

    body = response.json()
    assert body["status"] == "added"
    assert body["email_sent"] is True
    assert body["message"] == (
        "grace@example.com already has an account and is now a member. They were told by email."
    )
    [mail] = mailgun.mails
    assert mail["to"] == "grace@example.com"
    assert mail["subject"] == "Ada added you to Ada's organization on Naezlo"
    assert "as a member" in mail["text"]
    assert f"{settings.public_base_url}/o/{slug}" in mail["text"]


@pytest.mark.parametrize("failure", ["refused", "unreachable"])
async def test_an_invitation_stands_when_its_email_fails(
    client: AsyncClient, mailgun: FakeMailgun, db_session: AsyncSession, failure: str
) -> None:
    _, url = await ada_org(client)
    if failure == "refused":
        mailgun.status = 403
    else:
        mailgun.error = httpx2.ConnectError("no route")

    response = await client.post(url, json={"email": "grace@example.com"})

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "invited"
    assert body["email_sent"] is False
    assert body["message"] == (
        'The email could not be sent; use "Resend" to try again. '
        "grace@example.com joins Ada's organization the next time they sign in."
    )
    assert await invitation_count(db_session) == 1
    assert [invitation["email"] for invitation in (await client.get(url)).json()] == [
        "grace@example.com"
    ]


async def test_nothing_is_emailed_for_a_conflict(client: AsyncClient, mailgun: FakeMailgun) -> None:
    _, url = await ada_org(client)
    await client.post(url, json={"email": "grace@example.com"})

    again = await client.post(url, json={"email": "grace@example.com"})

    assert again.status_code == 409
    assert len(mailgun.mails) == 1


async def test_without_mailgun_nothing_is_sent_and_the_answer_says_so(
    client: AsyncClient,
) -> None:
    _, url = await ada_org(client)

    body = (await client.post(url, json={"email": "grace@example.com"})).json()

    assert body["email_sent"] is False
    assert body["message"].startswith("No email is sent.")


async def test_resend_emails_a_pending_invitation_again(
    client: AsyncClient, mailgun: FakeMailgun
) -> None:
    _, url = await ada_org(client)
    invitation = (await client.post(url, json={"email": "grace@example.com"})).json()["invitation"]

    response = await client.post(f"{url}/{invitation['id']}/send")

    assert response.status_code == 204, response.text
    assert [mail["to"] for mail in mailgun.mails] == ["grace@example.com", "grace@example.com"]
    assert mailgun.mails[0]["subject"] == mailgun.mails[1]["subject"]


async def test_resend_reports_a_failed_email(client: AsyncClient, mailgun: FakeMailgun) -> None:
    _, url = await ada_org(client)
    invitation = (await client.post(url, json={"email": "grace@example.com"})).json()["invitation"]
    mailgun.status = 500

    response = await client.post(f"{url}/{invitation['id']}/send")

    assert response.status_code == 502
    assert response.json() == {
        "detail": "The email could not be sent. Try again later.",
        "code": "email_failed",
    }


async def test_resend_without_mailgun_is_a_conflict(client: AsyncClient) -> None:
    _, url = await ada_org(client)
    invitation = (await client.post(url, json={"email": "grace@example.com"})).json()["invitation"]

    response = await client.post(f"{url}/{invitation['id']}/send")

    assert response.status_code == 409
    assert response.json()["code"] == "email_not_configured"


async def test_resend_is_for_admins_and_for_invitations_of_this_organization(
    client: AsyncClient,
    other_client: AsyncClient,
    mailgun: FakeMailgun,
    db_session: AsyncSession,
) -> None:
    org_id, url = await ada_org(client)
    invitation = (await client.post(url, json={"email": "kay@example.com"})).json()["invitation"]
    grace = await sign_in(other_client, "grace@example.com", "Grace")
    grace_url = f"/api/orgs/{grace['organizations'][0]['id']}/invitations"

    # Not a member of Ada's organization: it does not exist for her.
    assert (await other_client.post(f"{url}/{invitation['id']}/send")).status_code == 404
    # Her own organization has no such invitation.
    assert (await other_client.post(f"{grace_url}/{invitation['id']}/send")).status_code == 404
    # A plain member may not send invitations.
    await add_member(db_session, org_id, grace["user"]["id"], MembershipRole.MEMBER)
    assert (await other_client.post(f"{url}/{invitation['id']}/send")).status_code == 403
    assert len(mailgun.mails) == 1


async def test_config_says_whether_email_is_sent(client: AsyncClient, mailgun: FakeMailgun) -> None:
    assert (await client.get("/api/config")).json()["email_enabled"] is True


@pytest.mark.parametrize("missing", [None, "mailgun_api_key", "mailgun_api_url", "mail_from"])
def test_the_mailer_needs_a_key_an_endpoint_and_a_sender(missing: str | None) -> None:
    values: dict[str, str | None] = {
        "mailgun_api_key": "key",
        "mailgun_api_url": API_URL,
        "mail_from": SENDER,
    }
    if missing is not None:
        values[missing] = None
    settings = Settings(_env_file=None).model_copy(update=values)  # pyright: ignore[reportCallIssue]

    assert settings.email_enabled is (missing is None)
    assert (create_mailer(settings) is not None) is (missing is None)


async def test_the_mailer_raises_a_mail_error_without_the_key_in_it() -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(401, text="Forbidden")

    mailer = Mailer("key-secret", API_URL, SENDER, transport=httpx2.MockTransport(refuse))

    with pytest.raises(MailError) as raised:
        await mailer.send(Mail(to="a@example.com", subject="s", text="t", html="<p>t</p>"))

    assert "key-secret" not in str(raised.value)
    assert "401" in str(raised.value)
