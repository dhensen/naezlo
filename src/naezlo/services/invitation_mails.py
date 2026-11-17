"""The emails about an invitation: what they say, and sending one without failing the request."""

import html
import logging

from naezlo.config import Settings
from naezlo.mailer import Mail, Mailer, MailError
from naezlo.models import InvitationRole, MembershipRole, Organization, User

logger = logging.getLogger(__name__)

ROLE_PHRASES = {"member": "a member", "admin": "an admin", "owner": "an owner"}

# The blue of the logo (`brand-600` in the frontend).
BUTTON_STYLE = (
    "display:inline-block;background:#1f1bb5;color:#ffffff;text-decoration:none;"
    "font-weight:600;padding:10px 18px;border-radius:8px"
)


def _one_line(value: str) -> str:
    """A name as part of a subject: no line breaks, whatever someone called themselves."""
    return " ".join(value.split())


def _html_page(paragraphs: list[str], button: tuple[str, str], footer: str) -> str:
    """A plain message: paragraphs, one button and a note below it. All of it escaped here."""
    body = "".join(f'<p style="margin:0 0 16px">{html.escape(text)}</p>' for text in paragraphs)
    label, url = button
    return (
        '<div style="font-family:Arial,Helvetica,sans-serif;font-size:16px;line-height:1.5;'
        'color:#15171f;max-width:520px">'
        f"{body}"
        f'<p style="margin:0 0 24px"><a href="{html.escape(url, quote=True)}" '
        f'style="{BUTTON_STYLE}">{html.escape(label)}</a></p>'
        f'<p style="margin:0;font-size:13px;color:#6c7389">{html.escape(footer)}</p>'
        "</div>"
    )


def _sign_in_url(settings: Settings) -> str:
    return f"{settings.public_base_url.rstrip('/')}/login"


def invitation_mail(
    settings: Settings,
    organization: Organization,
    invited_by: User,
    email: str,
    role: InvitationRole,
) -> Mail:
    """For an address without an account: they join when they sign in with that address."""
    app_name = settings.app_name
    inviter = _one_line(invited_by.name)
    org_name = _one_line(organization.name)
    url = _sign_in_url(settings)
    paragraphs = [
        f"{inviter} ({invited_by.email}) invited you to join {org_name} on {app_name} "
        f"as {ROLE_PHRASES[role.value]}.",
        f"{app_name} is a task list that people and AI agents share.",
        f"To accept, sign in with the Google account of {email}. "
        f"You are a member of {org_name} from that moment.",
    ]
    footer = "If you did not expect this invitation, you can ignore this email."
    return Mail(
        to=email,
        subject=f"{inviter} invited you to {org_name} on {app_name}",
        text="\n\n".join([*paragraphs, f"Sign in: {url}", footer]) + "\n",
        html=_html_page(paragraphs, (f"Sign in to {app_name}", url), footer),
    )


def added_mail(
    settings: Settings,
    organization: Organization,
    invited_by: User,
    user: User,
    role: MembershipRole,
) -> Mail:
    """For someone who has an account already: they are a member, nothing to accept."""
    app_name = settings.app_name
    inviter = _one_line(invited_by.name)
    org_name = _one_line(organization.name)
    url = f"{settings.public_base_url.rstrip('/')}/o/{organization.slug}"
    paragraphs = [
        f"{inviter} ({invited_by.email}) added you to {org_name} on {app_name} "
        f"as {ROLE_PHRASES[role.value]}.",
        "There is nothing to accept: you find it under your organizations.",
    ]
    footer = f"You get this email because you have an account on {app_name}."
    return Mail(
        to=user.email,
        subject=f"{inviter} added you to {org_name} on {app_name}",
        text="\n\n".join([*paragraphs, f"Open {org_name}: {url}", footer]) + "\n",
        html=_html_page(paragraphs, (f"Open {org_name}", url), footer),
    )


async def try_send(mailer: Mailer | None, mail: Mail) -> bool:
    """Send the mail and say whether it went out. Never raises: what the mail is about
    (an invitation, a membership) stands with or without it."""
    if mailer is None:
        return False
    try:
        await mailer.send(mail)
    except MailError:
        logger.warning("A mail about an invitation was not sent")
        return False
    return True
