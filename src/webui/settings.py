from typing import Annotated

from fastapi import Depends, Request
from pydantic import SecretStr

from ..common import GeneralSettings


class Settings(GeneralSettings):
    create_database: bool = True
    tiling_server: str = 'http://localhost:8001'
    github_webhook_secret: SecretStr = 'test-github-secret'
    slack_signing_secret: SecretStr = 'test-slack-signing-secret'
    slack_channel_ids: list[str] = ['']


settings = Settings()  # type: ignore


def _get_settings(request: Request) -> Settings:
    return request.app.state.settings


AppSettings = Annotated[Settings, Depends(_get_settings)]
