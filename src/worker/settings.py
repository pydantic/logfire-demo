from ..common import GeneralSettings


class Settings(GeneralSettings):
    github_app_id: int
    github_app_installation_id: int
    github_app_private_key: str


settings = Settings()  # type: ignore
