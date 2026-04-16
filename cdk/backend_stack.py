"""Backend stack: DynamoDB, S3, CloudFront, Cognito, AgentCore Runtime, seed data."""

import json
import os
import aws_cdk as cdk
from aws_cdk import (
    Stack,
    RemovalPolicy,
    aws_dynamodb as dynamodb,
    aws_lambda as lambda_,
    aws_s3 as s3,
    aws_s3_deployment as s3deploy,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_cognito as cognito,
    aws_iam as iam,
    custom_resources as cr,
)
import aws_cdk.aws_bedrock_agentcore_alpha as agentcore
from constructs import Construct


class BackendStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- DynamoDB Tables ---

        self.menu_table = dynamodb.Table(
            self, "DriveThruMenu",
            table_name="DriveThruMenu",
            partition_key=dynamodb.Attribute(name="PK", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="SK", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        self.orders_table = dynamodb.Table(
            self, "DriveThruOrders",
            table_name="DriveThruOrders",
            partition_key=dynamodb.Attribute(name="orderId", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # --- S3 Buckets ---

        self.images_bucket = s3.Bucket(
            self, "FoodImagesBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        self.hosting_bucket = s3.Bucket(
            self, "FrontendHostingBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # --- Seed Menu Data ---

        seed_lambda_path = os.path.join(os.path.dirname(__file__), "seed_lambda")
        data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
        with open(os.path.join(data_dir, "menu_items.json")) as f:
            menu_data = json.load(f)

        seed_fn = lambda_.Function(
            self, "SeedMenuFunction",
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="index.handler",
            code=lambda_.Code.from_asset(seed_lambda_path),
            timeout=cdk.Duration.minutes(2),
            environment={"TABLE_NAME": self.menu_table.table_name},
        )
        self.menu_table.grant_write_data(seed_fn)

        seed_provider = cr.Provider(self, "SeedMenuProvider", on_event_handler=seed_fn)
        cdk.CustomResource(
            self, "SeedMenuData",
            service_token=seed_provider.service_token,
            properties={"DataHash": str(hash(json.dumps(menu_data)))},
        )

        # --- Upload Food Images ---
        # Deploy to the hosting bucket so images are served via CloudFront
        # at relative paths like /images/classic-burger.svg
        images_dir = os.path.join(data_dir, "images")
        if os.path.isdir(images_dir):
            s3deploy.BucketDeployment(
                self, "DeployFoodImages",
                sources=[s3deploy.Source.asset(images_dir)],
                destination_bucket=self.hosting_bucket,
                destination_key_prefix="images",
                prune=False,
            )

        # --- CloudFront Distribution ---

        self.oai = cloudfront.OriginAccessIdentity(
            self, "HostingOAI",
            comment="OAI for Drive-Thru frontend hosting bucket",
        )
        self.hosting_bucket.grant_read(self.oai)

        self.distribution = cloudfront.Distribution(
            self, "FrontendDistribution",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_identity(
                    self.hosting_bucket, origin_access_identity=self.oai,
                ),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            ),
            default_root_object="index.html",
            error_responses=[
                cloudfront.ErrorResponse(http_status=403, response_http_status=200, response_page_path="/index.html"),
                cloudfront.ErrorResponse(http_status=404, response_http_status=200, response_page_path="/index.html"),
            ],
        )

        # --- Cognito ---

        self.user_pool = cognito.UserPool(
            self, "DriveThruUserPool",
            user_pool_name="DriveThruUserPool",
            self_sign_up_enabled=True,
            sign_in_aliases=cognito.SignInAliases(email=True),
            auto_verify=cognito.AutoVerifiedAttrs(email=True),
            standard_attributes=cognito.StandardAttributes(
                email=cognito.StandardAttribute(required=True, mutable=True),
            ),
            password_policy=cognito.PasswordPolicy(
                min_length=8, require_lowercase=True, require_uppercase=True,
                require_digits=True, require_symbols=False,
            ),
            removal_policy=RemovalPolicy.DESTROY,
        )

        self.user_pool_client = self.user_pool.add_client(
            "DriveThruUserPoolClient",
            user_pool_client_name="DriveThruWebClient",
            auth_flows=cognito.AuthFlow(user_password=True, user_srp=True),
            generate_secret=False,
        )

        self.identity_pool = cognito.CfnIdentityPool(
            self, "DriveThruIdentityPool",
            identity_pool_name="DriveThruIdentityPool",
            allow_unauthenticated_identities=False,
            cognito_identity_providers=[
                cognito.CfnIdentityPool.CognitoIdentityProviderProperty(
                    client_id=self.user_pool_client.user_pool_client_id,
                    provider_name=self.user_pool.user_pool_provider_name,
                )
            ],
        )

        # --- Authenticated IAM Role ---

        self.authenticated_role = iam.Role(
            self, "CognitoAuthenticatedRole",
            assumed_by=iam.FederatedPrincipal(
                "cognito-identity.amazonaws.com",
                conditions={
                    "StringEquals": {"cognito-identity.amazonaws.com:aud": self.identity_pool.ref},
                    "ForAnyValue:StringLike": {"cognito-identity.amazonaws.com:amr": "authenticated"},
                },
                assume_role_action="sts:AssumeRoleWithWebIdentity",
            ),
        )
        self.authenticated_role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=["dynamodb:GetItem", "dynamodb:Query", "dynamodb:Scan", "dynamodb:BatchGetItem"],
            resources=[self.menu_table.table_arn, f"{self.menu_table.table_arn}/index/*"],
        ))
        self.authenticated_role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=["s3:GetObject"],
            resources=[f"{self.images_bucket.bucket_arn}/*"],
        ))
        cognito.CfnIdentityPoolRoleAttachment(
            self, "IdentityPoolRoleAttachment",
            identity_pool_id=self.identity_pool.ref,
            roles={"authenticated": self.authenticated_role.role_arn},
        )

        # --- AgentCore Runtime ---

        # Build the agent Docker image and deploy to AgentCore Runtime.
        # The Dockerfile installs all Python dependencies (strands-agents, boto3, etc.)
        agent_code_path = os.path.join(os.path.dirname(__file__), "..", "agent")

        self.agent_runtime = agentcore.Runtime(
            self, "DriveThruAgentRuntimeV4",
            runtime_name="DriveThruVoiceAgentV4",
            agent_runtime_artifact=agentcore.AgentRuntimeArtifact.from_asset(agent_code_path),
            authorizer_configuration=agentcore.RuntimeAuthorizerConfiguration.using_cognito(
                self.user_pool, [self.user_pool_client],
            ),
            environment_variables={
                "MENU_TABLE_NAME": self.menu_table.table_name,
                "ORDERS_TABLE_NAME": self.orders_table.table_name,
                "IMAGES_BUCKET_NAME": self.images_bucket.bucket_name,
                "AWS_REGION": self.region,
            },
            description="Drive-thru voice ordering agent powered by Nova Sonic",
        )

        self.agent_runtime.role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
            resources=[
                f"arn:aws:bedrock:us-east-1:{self.account}:inference-profile/us.amazon.nova-sonic-v1:0",
                "arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-sonic-v1:0",
            ],
        ))
        self.orders_table.grant_read_write_data(self.agent_runtime)
        self.menu_table.grant_read_data(self.agent_runtime)
        self.images_bucket.grant_read(self.agent_runtime)

        # Grant authenticated users permission to invoke the agent via WebSocket
        self.authenticated_role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "bedrock-agentcore:InvokeAgentRuntime",
                "bedrock-agentcore:InvokeAgentRuntimeWithWebSocketStream",
            ],
            resources=[self.agent_runtime.agent_runtime_arn],
        ))

        # --- Outputs ---

        cdk.CfnOutput(self, "MenuTableName", value=self.menu_table.table_name)
        cdk.CfnOutput(self, "OrdersTableName", value=self.orders_table.table_name)
        cdk.CfnOutput(self, "ImagesBucketName", value=self.images_bucket.bucket_name)
        cdk.CfnOutput(self, "HostingBucketName", value=self.hosting_bucket.bucket_name)
        cdk.CfnOutput(self, "DistributionId", value=self.distribution.distribution_id)
        cdk.CfnOutput(self, "DistributionDomainName", value=self.distribution.distribution_domain_name)
        cdk.CfnOutput(self, "UserPoolId", value=self.user_pool.user_pool_id)
        cdk.CfnOutput(self, "UserPoolClientId", value=self.user_pool_client.user_pool_client_id)
        cdk.CfnOutput(self, "IdentityPoolId", value=self.identity_pool.ref)
        cdk.CfnOutput(self, "AgentRuntimeId", value=self.agent_runtime.agent_runtime_id)
        cdk.CfnOutput(self, "AgentRuntimeArn", value=self.agent_runtime.agent_runtime_arn)
