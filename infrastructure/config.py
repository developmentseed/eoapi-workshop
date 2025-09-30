from typing import Dict, Optional, Tuple, Type

from pydantic import Field, ValidationInfo, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)
from typing_extensions import Self


class AppConfig(BaseSettings):
    project_id: str = Field(description="Project ID", default="eoapi-template-demo")
    stage: str = Field(description="Stage of deployment", default="test")
    # because of its validator, `tags` should always come after `project_id` and `stage`
    tags: Optional[Dict[str, str]] = Field(
        description="""Tags to apply to resources. If none provided,
        will default to the defaults defined in `default_tags`.
        Note that if tags are passed to the CDK CLI via `--tags`,
        they will override any tags defined here.""",
        default=None,
    )
    db_instance_type: str = Field(
        description="Database instance type", default="t3.small"
    )
    db_allocated_storage: int = Field(
        description="Allocated storage for the database", default=5
    )
    public_db_subnet: bool = Field(
        description="Whether to put the database in a public subnet", default=True
    )
    nat_gateway_count: int = Field(
        description="Number of NAT gateways to create",
        default=0,
    )

    model_config = SettingsConfigDict(
        env_file=".env", yaml_file="config.yaml", extra="allow"
    )

    @field_validator("tags")
    def default_tags(cls, v, info: ValidationInfo):
        return v or {"project_id": info.data["project_id"], "stage": info.data["stage"]}

    @model_validator(mode="after")
    def validate_model(self) -> Self:
        if not self.public_db_subnet and (
            self.nat_gateway_count is not None and self.nat_gateway_count <= 0
        ):
            raise ValueError(
                """if the database and its associated services instances
                             are to be located in the private subnet of the VPC, NAT
                             gateways are needed to allow egress from the services
                             and therefore `nat_gateway_count` has to be > 0."""
            )

        return self

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
