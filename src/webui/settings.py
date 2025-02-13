from pydantic import SecretStr

from ..common import GeneralSettings


class Settings(GeneralSettings):
    create_database: bool = True
    tiling_server: str = 'http://localhost:8001'
    github_webhook_secret: SecretStr = 'test-github-secret'
    slack_signing_secret: SecretStr = '92384818aa0d7bcd369dde8d9d519c75'
    slack_channel_ids: list[str] = ['C07AV5SDFFT']


settings = Settings()  # type: ignore
