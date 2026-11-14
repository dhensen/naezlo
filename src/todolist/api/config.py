"""Public configuration the login page needs before anyone is signed in."""

from fastapi import APIRouter
from pydantic import BaseModel

from todolist.config import SettingsDep

router = APIRouter(tags=["config"])


class ConfigOut(BaseModel):
    dev_login_enabled: bool
    google_login_enabled: bool


@router.get("/config")
async def get_config(settings: SettingsDep) -> ConfigOut:
    return ConfigOut(
        dev_login_enabled=settings.dev_login,
        google_login_enabled=settings.google_login_enabled,
    )
