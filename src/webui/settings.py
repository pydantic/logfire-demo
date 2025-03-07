from pydantic import SecretStr

from ..common import GeneralSettings


class Settings(GeneralSettings):
    create_database: bool = True
    tiling_server: str = 'http://localhost:8001'
    github_webhook_secret: SecretStr = 'test-github-secret'
    slack_signing_secret: SecretStr = 'test-slack-signing-secret'
    slack_channel: dict[str, str] = {}  # mapping between Slack channel IDs and names


settings = Settings()  # type: ignore
