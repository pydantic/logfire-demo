from pydantic import Field

from ..common import GeneralSettings


class Settings(GeneralSettings):
    github_app_id: int
    github_app_installation_id: int
    github_app_private_key: str
    vector_distance_threshold: float = Field(0.4, ge=0.0, le=1.0)
    ai_similarity_threshold: int = Field(85, ge=0, le=100)


settings = Settings()  # type: ignore
