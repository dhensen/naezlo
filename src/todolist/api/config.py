"""Public configuration the frontend needs: what the login page offers, and the MCP address."""

from fastapi import APIRouter
from pydantic import BaseModel

from todolist.config import SettingsDep

router = APIRouter(tags=["config"])


class ConfigOut(BaseModel):
    dev_login_enabled: bool
    google_login_enabled: bool
    # The address an MCP client connects to (PUBLIC_BASE_URL + /mcp).
    mcp_url: str


@router.get("/config")
async def get_config(settings: SettingsDep) -> ConfigOut:
    return ConfigOut(
        dev_login_enabled=settings.dev_login,
        google_login_enabled=settings.google_login_enabled,
        mcp_url=settings.mcp_resource_url,
    )
