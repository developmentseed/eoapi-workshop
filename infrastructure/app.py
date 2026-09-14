import json
from pathlib import Path

from aws_cdk import (
    App,
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
    aws_cognito,
    aws_ec2,
    aws_lambda,
    aws_rds,
)
from aws_cdk import (
    custom_resources as cr,
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
    StacAuthProxyLambda,
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
            # Pin the pgbouncer AMI. eoapi-cdk's default is a dated Ubuntu SSM path,
            # but ours must stay on the image the instance has run since 2025-10-29 --
            # any change to ImageId replaces the instance, and the replacement's health
            # check aborts against the still-booting box (eoapi-cdk #255, still open).
            # This path resolves to ami-00f46ccd1cbfb363e in us-west-2. Bump it
            # deliberately, never on the rolling `current` alias (eoapi-cdk #234).
            pgbouncer_ami_ssm_parameter=(
                "/aws/service/canonical/ubuntu/server/noble/stable/20251022"
                "/amd64/hvm/ebs-gp3/ami-id"
            ),
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
        # Cognito - the workshop's OIDC provider, standing in for the local
        # mock-oidc container. Throwaway pool: relaxed password policy, no
        # self-signup, destroyed with the stack.
        user_pool = aws_cognito.UserPool(
            self,
            "user-pool",
            self_sign_up_enabled=False,
            sign_in_aliases=aws_cognito.SignInAliases(username=True, email=True),
            password_policy=aws_cognito.PasswordPolicy(
                min_length=8,
                require_uppercase=False,
                require_digits=False,
                require_symbols=False,
            ),
            removal_policy=RemovalPolicy.DESTROY,
        )

        # Hosted UI, needed for the authorization code flow the Swagger UI and
        # STAC Manager use.
        user_pool_domain = user_pool.add_domain(
            "user-pool-domain",
            cognito_domain=aws_cognito.CognitoDomainOptions(
                domain_prefix=f"{app_config.project}-{self.account}"
            ),
        )

        # Cognito joins resource server + scope with a `/`, so these are
        # `stac/read` and `stac/write` rather than the `stac:read`/`stac:write`
        # that mock-oidc issues locally.
        read_scope = aws_cognito.ResourceServerScope(
            scope_name="read", scope_description="Read STAC metadata"
        )
        write_scope = aws_cognito.ResourceServerScope(
            scope_name="write", scope_description="Write STAC metadata"
        )
        resource_server = user_pool.add_resource_server(
            "resource-server",
            identifier="stac",
            scopes=[read_scope, write_scope],
        )
        write_scope_name = "stac/write"

        auth_subdomain = f"{app_config.project}-protected-stac"
        auth_domain_name = f"{auth_subdomain}.{app_config.domain_name}"

        stac_api_client = user_pool.add_client(
            "stac-api-client",
            user_pool_client_name="stac-api",
            generate_secret=False,
            o_auth=aws_cognito.OAuthSettings(
                flows=aws_cognito.OAuthFlows(authorization_code_grant=True),
                scopes=[
                    aws_cognito.OAuthScope.OPENID,
                    aws_cognito.OAuthScope.PROFILE,
                    aws_cognito.OAuthScope.resource_server(resource_server, read_scope),
                    aws_cognito.OAuthScope.resource_server(
                        resource_server, write_scope
                    ),
                ],
                callback_urls=[
                    f"https://{auth_domain_name}/docs/oauth2-redirect",
                    "http://localhost:8086",
                ],
            ),
        )

        # Two workshop identities sharing one password. Cognito creates users in
        # FORCE_CHANGE_PASSWORD, so a follow-up AdminSetUserPassword is what
        # actually makes them usable.
        for username in app_config.workshop_users:
            user = aws_cognito.CfnUserPoolUser(
                self,
                f"user-{username}",
                user_pool_id=user_pool.user_pool_id,
                username=username,
                message_action="SUPPRESS",
                user_attributes=[
                    aws_cognito.CfnUserPoolUser.AttributeTypeProperty(
                        name="email", value=f"{username}@example.com"
                    ),
                    aws_cognito.CfnUserPoolUser.AttributeTypeProperty(
                        name="email_verified", value="true"
                    ),
                ],
            )

            set_password = cr.AwsCustomResource(
                self,
                f"user-{username}-password",
                on_update=cr.AwsSdkCall(
                    service="CognitoIdentityServiceProvider",
                    action="adminSetUserPassword",
                    parameters={
                        "UserPoolId": user_pool.user_pool_id,
                        "Username": username,
                        "Password": app_config.workshop_user_password,
                        "Permanent": True,
                    },
                    physical_resource_id=cr.PhysicalResourceId.of(
                        f"{username}-password"
                    ),
                ),
                policy=cr.AwsCustomResourcePolicy.from_sdk_calls(
                    resources=[user_pool.user_pool_arn]
                ),
            )
            set_password.node.add_dependency(user)

        oidc_discovery_url = (
            f"https://cognito-idp.{self.region}.amazonaws.com/"
            f"{user_pool.user_pool_id}/.well-known/openid-configuration"
        )

        #######################################################################
        # STAC Auth Proxy - authenticated front door to the STAC API
        auth_domain = DomainName(
            self,
            "stac-auth-proxy-domain-name",
            domain_name=auth_domain_name,
            certificate=certificate,
        )

        StacAuthProxyLambda(
            self,
            "stac-auth-proxy",
            # execute-api endpoint rather than the custom domain, so the proxy
            # doesn't depend on DNS records created in this same stack
            upstream_url=stac_api.url,
            oidc_discovery_url=oidc_discovery_url,
            stac_api_client_id=stac_api_client.user_pool_client_id,
            domain_name=auth_domain,
            # eoapi-cdk 11.6.4's bundled handler calls `app.router.startup()`, which
            # Starlette removed in 1.0, so the stock proxy raises at import and 500s
            # on every request. Build the runtime here instead, with the same deps
            # pinned exactly. Fixed upstream in developmentseed/eoapi-cdk on
            # `fix/stac-auth-proxy-lifespan`; delete this override and
            # infrastructure/stac-auth-proxy-runtime/ once that is in a release.
            lambda_function_options={
                # Repo root as context so the Dockerfile can copy in
                # docs/workshop_filters.py, the same module the compose stack mounts.
                "code": aws_lambda.Code.from_docker_build(
                    str(Path(__file__).parent.parent),
                    file="infrastructure/stac-auth-proxy-runtime/Dockerfile",
                ),
                "handler": "handler.handler",
            },
            api_env={
                "DEFAULT_PUBLIC": "true",
                # Writes require a token carrying the write scope, not merely a
                # valid token. Mirrors docker-compose.yml.
                "PRIVATE_ENDPOINTS": json.dumps(
                    {
                        r"^/collections$": [["POST", write_scope_name]],
                        r"^/collections/([^/]+)$": [
                            ["PUT", write_scope_name],
                            ["PATCH", write_scope_name],
                            ["DELETE", write_scope_name],
                        ],
                        r"^/collections/([^/]+)/items$": [["POST", write_scope_name]],
                        r"^/collections/([^/]+)/items/([^/]+)$": [
                            ["PUT", write_scope_name],
                            ["PATCH", write_scope_name],
                            ["DELETE", write_scope_name],
                        ],
                        r"^/collections/([^/]+)/bulk_items$": [
                            ["POST", write_scope_name]
                        ],
                    }
                ),
                # Row-level authorization (chapter 7). `private-<owner>-*` records are
                # visible only to their owner; everything else is public.
                #
                # The owner comes from the `username` claim, which TenantFilter defaults
                # to. Cognito issues it in every access token and the notebooks ask
                # mock-oidc to mint the same claim, so this configuration is identical to
                # the one in docker-compose.yml -- no per-environment override.
                #
                # Note the upstream STAC API is read-only here -- the transaction
                # extension is deliberately not enabled, since `{project}-stac` is
                # public and unauthenticated -- so this filters reads only.
                "ITEMS_FILTER_CLS": "workshop_filters:TenantFilter",
                "ITEMS_FILTER_KWARGS": json.dumps({"field": "collection"}),
                "COLLECTIONS_FILTER_CLS": "workshop_filters:TenantFilter",
                "COLLECTIONS_FILTER_KWARGS": json.dumps({"field": "id"}),
            },
        )

        route53.ARecord(
            self,
            "StacAuthProxyDnsRecord",
            zone=hosted_zone,
            record_name=auth_subdomain,
            target=route53.RecordTarget.from_alias(
                ApiGatewayv2DomainProperties(
                    auth_domain.regional_domain_name,
                    auth_domain.regional_hosted_zone_id,
                )
            ),
        )

        for name, value, description in [
            (
                "StacAuthProxyUrl",
                f"https://{auth_domain_name}",
                "Authenticated STAC API endpoint",
            ),
            (
                "OidcDiscoveryUrl",
                oidc_discovery_url,
                "OIDC discovery endpoint for the workshop Cognito user pool",
            ),
            (
                "OidcClientId",
                stac_api_client.user_pool_client_id,
                "OAuth client ID for the STAC API",
            ),
            (
                "OidcAuthority",
                user_pool_domain.base_url(),
                "Cognito hosted UI base URL",
            ),
            (
                "WorkshopUserPassword",
                app_config.workshop_user_password,
                f"Password for workshop users: {', '.join(app_config.workshop_users)}",
            ),
        ]:
            CfnOutput(self, name, value=value, description=description)

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
                "STAC_AUTH_PROXY_ENDPOINT": f"https://{auth_domain_name}",
                "OIDC_DISCOVERY_URL": oidc_discovery_url,
                "OIDC_CLIENT_ID": stac_api_client.user_pool_client_id,
                "WORKSHOP_USER_PASSWORD": app_config.workshop_user_password,
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
