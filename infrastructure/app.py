import os
from pathlib import Path

from aws_cdk import (
    App,
    CfnOutput,
    Duration,
    Environment,
    RemovalPolicy,
    Stack,
    aws_ec2,
    aws_lambda,
    aws_rds,
)
from config import AppConfig
from constructs import Construct
from eoapi_cdk import (
    PgStacApiLambda,
    PgStacDatabase,
    TiPgApiLambda,
    TitilerPgstacApiLambda,
)


class eoAPIStack(Stack):
    def __init__(
        self,
        scope: Construct,
        id: str,
        app_config: AppConfig,
        **kwargs,
    ) -> None:
        super().__init__(
            scope,
            id=id,
            tags=app_config.tags,
            **kwargs,
        )

        vpc = aws_ec2.Vpc.from_lookup(
            self,
            f"{id}-vpc",
            vpc_id=app_config.vpc_id,
        )

        #######################################################################
        # PG database
        pgstac_db = PgStacDatabase(
            self,
            "pgstac-db",
            add_pgbouncer=True,
            vpc=vpc,
            engine=aws_rds.DatabaseInstanceEngine.postgres(
                version=aws_rds.PostgresEngineVersion.VER_17
            ),
            vpc_subnets=aws_ec2.SubnetSelection(
                subnet_type=(
                    aws_ec2.SubnetType.PUBLIC
                    if app_config.public_db_subnet
                    else aws_ec2.SubnetType.PRIVATE_ISOLATED
                )
            ),
            allocated_storage=app_config.db_allocated_storage,
            instance_type=aws_ec2.InstanceType(app_config.db_instance_type),
            removal_policy=RemovalPolicy.DESTROY,
            pgstac_version=app_config.pgstac_version,
        )

        assert pgstac_db.security_group
        pgstac_db.security_group.add_ingress_rule(
            aws_ec2.Peer.any_ipv4(), aws_ec2.Port.tcp(5432)
        )

        CfnOutput(
            self,
            "PgstacSecret",
            value=pgstac_db.pgstac_secret.secret_arn,
            description="ARN of the pgstac secret",
        )

        #######################################################################
        # STAC API service
        stac_api = PgStacApiLambda(
            self,
            "stac-api",
            api_env={
                "NAME": app_config.build_service_name("stac"),
                "description": f"{app_config.stage} STAC API",
            },
            db=pgstac_db.connection_target,
            db_secret=pgstac_db.pgstac_secret,
            # If the db is not in the public subnet then we need to put
            # the lambda within the VPC
            vpc=vpc if not app_config.public_db_subnet else None,
            subnet_selection=aws_ec2.SubnetSelection(
                subnet_type=aws_ec2.SubnetType.PRIVATE_WITH_EGRESS
            )
            if not app_config.public_db_subnet
            else None,
            enable_snap_start=True,
        )

        #######################################################################
        # Raster service
        titiler_pgstac_api = TitilerPgstacApiLambda(
            self,
            "raster-api",
            api_env={
                "NAME": app_config.build_service_name("raster"),
                "description": f"{app_config.stage} Raster API",
                "TITILER_PGSTAC_API_ENABLE_EXTERNAL_DATASET_ENDPOINTS": "True",
            },
            db=pgstac_db.connection_target,
            db_secret=pgstac_db.pgstac_secret,
            # If the db is not in the public subnet then we need to put
            # the lambda within the VPC
            vpc=vpc if not app_config.public_db_subnet else None,
            subnet_selection=aws_ec2.SubnetSelection(
                subnet_type=aws_ec2.SubnetType.PRIVATE_WITH_EGRESS
            )
            if not app_config.public_db_subnet
            else None,
            enable_snap_start=True,
            buckets=["*"],
        )

        #######################################################################
        # Vector Service
        tipg_api = TiPgApiLambda(
            self,
            "vector-api",
            db=pgstac_db.connection_target,
            db_secret=pgstac_db.pgstac_secret,
            api_env={
                "NAME": app_config.build_service_name("vector"),
                "description": f"{app_config.stage} tipg API",
                "TIPG_DB_SCHEMAS": '["features"]',
            },
            # If the db is not in the public subnet then we need to put
            # the lambda within the VPC
            vpc=vpc if not app_config.public_db_subnet else None,
            subnet_selection=aws_ec2.SubnetSelection(
                subnet_type=aws_ec2.SubnetType.PRIVATE_WITH_EGRESS
            )
            if not app_config.public_db_subnet
            else None,
            enable_snap_start=True,
        )

        for api in [stac_api, titiler_pgstac_api, tipg_api]:
            api.node.add_dependency(pgstac_db.secret_bootstrapper)

        #######################################################################
        # Workshop Config Lambda - provides credentials and endpoints to workshop users
        workshop_config_lambda = aws_lambda.Function(
            self,
            "workshop-config",
            runtime=aws_lambda.Runtime.PYTHON_3_12,
            handler="workshop_config.handler",
            code=aws_lambda.Code.from_asset(
                str(Path(__file__).parent / "lambda"),
            ),
            timeout=Duration.seconds(30),
            environment={
                "PGSTAC_SECRET_ARN": pgstac_db.pgstac_secret.secret_arn,
                "WORKSHOP_TOKEN": app_config.workshop_token,
                "STAC_API_ENDPOINT": stac_api.url,
                "TITILER_PGSTAC_API_ENDPOINT": titiler_pgstac_api.url,
                "TIPG_API_ENDPOINT": tipg_api.url,
            },
        )

        # Grant Lambda permission to read the secret
        pgstac_db.pgstac_secret.grant_read(workshop_config_lambda)

        # Create Function URL (public HTTPS endpoint)
        workshop_config_url = workshop_config_lambda.add_function_url(
            auth_type=aws_lambda.FunctionUrlAuthType.NONE,
            cors=aws_lambda.FunctionUrlCorsOptions(
                allowed_origins=["*"],
                allowed_methods=[aws_lambda.HttpMethod.GET],
                allowed_headers=["Authorization", "Content-Type"],
            ),
        )

        CfnOutput(
            self,
            "WorkshopConfigUrl",
            value=workshop_config_url.url,
            description="URL for workshop configuration endpoint",
        )

        CfnOutput(
            self,
            "WorkshopToken",
            value=app_config.workshop_token,
            description="Bearer token for workshop config endpoint",
        )


app = App()

app_config = AppConfig()

# Get AWS account and region from environment (uses AWS_PROFILE)
env = Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region=os.environ.get("CDK_DEFAULT_REGION"),
)

eoapi_stack = eoAPIStack(
    scope=app,
    app_config=app_config,
    id=app_config.project_id,
    env=env,
)

app.synth()
