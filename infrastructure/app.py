from aws_cdk import (
    App,
    CfnOutput,
    RemovalPolicy,
    Stack,
    aws_ec2,
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

PGSTAC_VERSION = "0.9.8"


class VpcStack(Stack):
    def __init__(
        self, scope: Construct, app_config: AppConfig, id: str, **kwargs
    ) -> None:
        super().__init__(scope, id=id, tags=app_config.tags, **kwargs)

        self.vpc = aws_ec2.Vpc(
            self,
            "vpc",
            subnet_configuration=[
                aws_ec2.SubnetConfiguration(
                    name="ingress", subnet_type=aws_ec2.SubnetType.PUBLIC, cidr_mask=24
                ),
                aws_ec2.SubnetConfiguration(
                    name="application",
                    subnet_type=aws_ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24,
                ),
                aws_ec2.SubnetConfiguration(
                    name="rds",
                    subnet_type=aws_ec2.SubnetType.PRIVATE_ISOLATED,
                    cidr_mask=24,
                ),
            ],
            nat_gateways=app_config.nat_gateway_count,
        )

        self.vpc.add_interface_endpoint(
            "SecretsManagerEndpoint",
            service=aws_ec2.InterfaceVpcEndpointAwsService.SECRETS_MANAGER,
        )

        self.vpc.add_interface_endpoint(
            "CloudWatchEndpoint",
            service=aws_ec2.InterfaceVpcEndpointAwsService.CLOUDWATCH_LOGS,
        )

        self.vpc.add_gateway_endpoint(
            "S3", service=aws_ec2.GatewayVpcEndpointAwsService.S3
        )

        self.export_value(
            self.vpc.select_subnets(subnet_type=aws_ec2.SubnetType.PUBLIC)
            .subnets[0]
            .subnet_id
        )
        self.export_value(
            self.vpc.select_subnets(subnet_type=aws_ec2.SubnetType.PUBLIC)
            .subnets[1]
            .subnet_id
        )


class eoAPIStack(Stack):
    def __init__(
        self,
        scope: Construct,
        vpc: aws_ec2.Vpc,
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

        #######################################################################
        # PG database
        pgstac_db = PgStacDatabase(
            self,
            "pgstac-db",
            add_pgbouncer=True,
            vpc=vpc,
            engine=aws_rds.DatabaseInstanceEngine.postgres(
                version=aws_rds.PostgresEngineVersion.VER_16
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
            pgstac_version=PGSTAC_VERSION,
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


app = App()

app_config = AppConfig()

vpc_stack = VpcStack(
    scope=app,
    app_config=app_config,
    id=f"vpc{app_config.project_id}",
)

eoapi_stack = eoAPIStack(
    scope=app, vpc=vpc_stack.vpc, app_config=app_config, id=app_config.project_id
)

app.synth()
