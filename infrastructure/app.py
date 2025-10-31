from pathlib import Path

from aws_cdk import (
    App,
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
    aws_ec2,
    aws_lambda,
    aws_rds,
)
from aws_cdk import (
    aws_certificatemanager as acm,
)
from aws_cdk import (
    aws_route53 as route53,
)
from aws_cdk.aws_apigatewayv2 import ApiMapping, DomainName, HttpApi
from aws_cdk.aws_apigatewayv2_integrations import HttpLambdaIntegration
from aws_cdk.aws_route53_targets import ApiGatewayv2DomainProperties
from config import AppConfig
from constructs import Construct
from eoapi_cdk import (
    PgStacApiLambda,
    PgStacDatabase,
    TiPgApiLambda,
    TitilerPgstacApiLambda,
)


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
            nat_gateways=0,
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
        id: str,
        vpc: aws_ec2.Vpc,
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
        # Route53 Hosted Zone and Certificate
        hosted_zone = route53.HostedZone.from_hosted_zone_attributes(
            self,
            "HostedZone",
            hosted_zone_id=app_config.hosted_zone_id,
            zone_name=app_config.domain_name,
        )

        # Use existing wildcard certificate
        certificate = acm.Certificate.from_certificate_arn(
            self,
            "Certificate",
            certificate_arn=app_config.certificate_arn,
        )

        #######################################################################
        # Custom Domain Names for APIs
        stac_domain = DomainName(
            self,
            "stac-api-domain-name",
            domain_name=f"{app_config.project}-stac.{app_config.domain_name}",
            certificate=certificate,
        )

        raster_domain = DomainName(
            self,
            "raster-api-domain-name",
            domain_name=f"{app_config.project}-raster.{app_config.domain_name}",
            certificate=certificate,
        )

        vector_domain = DomainName(
            self,
            "vector-api-domain-name",
            domain_name=f"{app_config.project}-vector.{app_config.domain_name}",
            certificate=certificate,
        )

        config_domain = DomainName(
            self,
            "config-api-domain-name",
            domain_name=f"{app_config.project}-config.{app_config.domain_name}",
            certificate=certificate,
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
                "description": f"{app_config.project} STAC API",
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
            domain_name=stac_domain,
        )

        #######################################################################
        # Raster service
        titiler_pgstac_api = TitilerPgstacApiLambda(
            self,
            "raster-api",
            api_env={
                "NAME": app_config.build_service_name("raster"),
                "description": f"{app_config.project} Raster API",
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
            domain_name=raster_domain,
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
                "description": f"{app_config.project} tipg API",
                "TIPG_DB_SCHEMAS": '["features"]',
                "TIPG_DB_SPATIAL_EXTENT": "FALSE",
                "TIPG_DB_DATETIME_EXTENT": "FALSE",
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
            domain_name=vector_domain,
        )

        for api in [stac_api, titiler_pgstac_api, tipg_api]:
            api.node.add_dependency(pgstac_db.secret_bootstrapper)

        #######################################################################
        # DNS Records for API custom domains
        route53.ARecord(
            self,
            "StacDnsRecord",
            zone=hosted_zone,
            record_name=f"{app_config.project}-stac",
            target=route53.RecordTarget.from_alias(
                ApiGatewayv2DomainProperties(
                    stac_domain.regional_domain_name,
                    stac_domain.regional_hosted_zone_id,
                )
            ),
        )

        route53.ARecord(
            self,
            "RasterDnsRecord",
            zone=hosted_zone,
            record_name=f"{app_config.project}-raster",
            target=route53.RecordTarget.from_alias(
                ApiGatewayv2DomainProperties(
                    raster_domain.regional_domain_name,
                    raster_domain.regional_hosted_zone_id,
                )
            ),
        )

        route53.ARecord(
            self,
            "VectorDnsRecord",
            zone=hosted_zone,
            record_name=f"{app_config.project}-vector",
            target=route53.RecordTarget.from_alias(
                ApiGatewayv2DomainProperties(
                    vector_domain.regional_domain_name,
                    vector_domain.regional_hosted_zone_id,
                )
            ),
        )

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
                "STAC_API_ENDPOINT": app_config.build_service_url("stac"),
                "TITILER_PGSTAC_API_ENDPOINT": app_config.build_service_url("raster"),
                "TIPG_API_ENDPOINT": app_config.build_service_url("vector"),
            },
        )

        # Grant Lambda permission to read the secret
        pgstac_db.pgstac_secret.grant_read(workshop_config_lambda)

        # Create HTTP API Gateway integration for the workshop config Lambda
        workshop_config_integration = HttpLambdaIntegration(
            "WorkshopConfigIntegration",
            workshop_config_lambda,
        )

        workshop_config_api = HttpApi(
            self,
            "workshop-config-api",
            default_integration=workshop_config_integration,
        )

        # Map the custom domain to the API
        ApiMapping(
            self,
            "ConfigApiMapping",
            api=workshop_config_api,
            domain_name=config_domain,
        )

        # Add DNS record for workshop config API
        config_domain_name = f"{app_config.project}-config.{app_config.domain_name}"

        route53.ARecord(
            self,
            "ConfigDnsRecord",
            zone=hosted_zone,
            record_name=f"{app_config.project}-config",
            target=route53.RecordTarget.from_alias(
                ApiGatewayv2DomainProperties(
                    config_domain.regional_domain_name,
                    config_domain.regional_hosted_zone_id,
                )
            ),
        )

        CfnOutput(
            self,
            "WorkshopConfigUrl",
            value=f"https://{config_domain_name}",
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

vpc_stack = VpcStack(
    scope=app,
    app_config=app_config,
    id=f"vpc{app_config.project}",
)

eoapi_stack = eoAPIStack(
    scope=app,
    app_config=app_config,
    id=app_config.project,
    vpc=vpc_stack.vpc,
)

app.synth()
