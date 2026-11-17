"""Public configuration the frontend needs: what the login page offers, the MCP address and
whether email is sent."""

from fastapi import APIRouter
from pydantic import BaseModel

from naezlo.config import SettingsDep
from naezlo.mailer import MailerDep

router = APIRouter(tags=["config"])


class ConfigOut(BaseModel):
    dev_login_enabled: bool
    google_login_enabled: bool
    # The address an MCP client connects to (PUBLIC_BASE_URL + /mcp).
    mcp_url: str
    # Whether invitations are emailed (Mailgun is configured).
    email_enabled: bool


@router.get("/config")
async def get_config(settings: SettingsDep, mailer: MailerDep) -> ConfigOut:
    return ConfigOut(
        dev_login_enabled=settings.dev_login,
        google_login_enabled=settings.google_login_enabled,
        mcp_url=settings.mcp_resource_url,
        email_enabled=mailer is not None,
    )
