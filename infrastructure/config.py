import secrets
from typing import Dict, Optional, Tuple, Type

from pydantic import Field, ValidationInfo, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)


class AppConfig(BaseSettings):
    project_id: str = Field(description="Project ID", default="eoapi-workshop")
    stage: str = Field(description="Stage of deployment", default="dev")

    # because of its validator, `tags` should always come after `project_id` and `stage`
    tags: Optional[Dict[str, str]] = Field(
        description="""Tags to apply to resources. If none provided,
        will default to the defaults defined in `default_tags`.
        Note that if tags are passed to the CDK CLI via `--tags`,
        they will override any tags defined here.""",
        default=None,
    )

    vpc_id: str = Field(description="VPC ID")

    pgstac_version: str = Field(description="pgstac version", default="0.9.8")

    db_instance_type: str = Field(
        description="Database instance type", default="t4g.small"
    )
    db_allocated_storage: int = Field(
        description="Allocated storage for the database", default=5
    )
    public_db_subnet: bool = Field(
        description="Whether to put the database in a public subnet", default=True
    )

    workshop_token: str = Field(
        description="Bearer token for workshop config Lambda. Auto-generated if not provided.",
        default="",
    )

    model_config = SettingsConfigDict(
        env_file=".env", yaml_file="config.yaml", extra="allow"
    )

    @field_validator("tags")
    def default_tags(cls, v, info: ValidationInfo):
        return v or {"project_id": info.data["project_id"], "stage": info.data["stage"]}

    @field_validator("workshop_token")
    def generate_token(cls, v):
        """Generate a random workshop token if not provided."""
        return v or secrets.token_urlsafe(32)

    def build_service_name(self, service_id: str) -> str:
        return f"{self.project_id}-{self.stage}-{service_id}"

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            file_secret_settings,
            YamlConfigSettingsSource(settings_cls),
        )
