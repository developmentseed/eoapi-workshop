import secrets

from pydantic import Field, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)


class AppConfig(BaseSettings):
    # Tags
    name: str = "eoapi-workshop"
    owner: str = "eoapi"
    project: str = "workshop"
    release: str = "dev"

    @property
    def tags(self) -> dict[str, str]:
        return {
            "Project": self.project,
            "Owner": self.owner,
            "Name": self.name,
            "Release": self.release,
        }

    domain_name: str = Field(
        description="Base domain for custom domains", default="eoapi.dev"
    )

    hosted_zone_id: str = Field(
        description="Route53 Hosted Zone ID for the domain",
    )

    certificate_arn: str = Field(
        description="ARN of the ACM certificate for *.eoapi.dev or *.{project}.eoapi.dev",
    )

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

    workshop_users: list[str] = Field(
        description="Cognito users created for the workshop",
        default=["alice", "bob"],
    )

    workshop_user_password: str = Field(
        description=(
            "Password shared by the Cognito workshop users. Auto-generated if not "
            "provided, which means it rotates on every deploy — set it in "
            "config.yaml to keep it stable."
        ),
        default="",
    )

    workshop_token: str = Field(
        description="Bearer token for workshop config Lambda. Auto-generated if not provided.",
        default="",
    )

    model_config = SettingsConfigDict(
        env_file=".env", yaml_file="config.yaml", extra="allow"
    )

    @field_validator("workshop_token")
    def generate_token(cls, v):
        """Generate a random workshop token if not provided."""
        return v or secrets.token_urlsafe(32)

    @field_validator("workshop_user_password")
    def generate_password(cls, v):
        """Generate a random workshop user password if not provided."""
        return v or secrets.token_urlsafe(16)

    def build_service_name(self, service_id: str) -> str:
        return f"{self.project}-{service_id}"

    def build_service_url(self, service: str) -> str:
        """Build service URL from project and service name."""
        return f"https://{self.project}-{service}.{self.domain_name}"

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            file_secret_settings,
            YamlConfigSettingsSource(settings_cls),
        )
