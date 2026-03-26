"""CDK Stack for the Drive-Thru Voice Ordering system.

Provisions DynamoDB tables, S3 buckets, CloudFront distribution,
Cognito User Pool, Identity Pool, AgentCore Runtime, and deploys
the frontend SPA with runtime configuration.
"""

import json
import os
import aws_cdk as cdk
from aws_cdk import (
    Stack,
    RemovalPolicy,
    aws_dynamodb as dynamodb,
    aws_s3 as s3,
    aws_s3_deployment as s3deploy,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_cognito as cognito,
    aws_iam as iam,
)
import aws_cdk.aws_bedrock_agentcore_alpha as agentcore
from constructs import Construct


class DriveThruVoiceOrderingStack(Stack):
    """Provisions all infrastructure for the drive-thru voice ordering system."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- DynamoDB Tables ---

        # Menu table: PK = CATEGORY#<categoryId>, SK = ITEM#<itemId> or METADATA
        self.menu_table = dynamodb.Table(
            self,
            "DriveThruMenu",
            table_name="DriveThruMenu",
            partition_key=dynamodb.Attribute(
                name="PK", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="SK", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # Orders table: partition key = orderId (String)
        self.orders_table = dynamodb.Table(
            self,
            "DriveThruOrders",
            table_name="DriveThruOrders",
            partition_key=dynamodb.Attribute(
                name="orderId", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # --- S3 Buckets ---

        # Food images bucket
        self.images_bucket = s3.Bucket(
            self,
            "FoodImagesBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # Frontend static hosting bucket
        self.hosting_bucket = s3.Bucket(
            self,
            "FrontendHostingBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # --- CloudFront Distribution ---

        # Origin Access Identity for restricting direct S3 access
        self.oai = cloudfront.OriginAccessIdentity(
            self,
            "HostingOAI",
            comment="OAI for Drive-Thru frontend hosting bucket",
        )

        # Grant the OAI read access to the hosting bucket
        self.hosting_bucket.grant_read(self.oai)

        # CloudFront distribution serving frontend from S3 hosting bucket
        self.distribution = cloudfront.Distribution(
            self,
            "FrontendDistribution",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_identity(
                    self.hosting_bucket,
                    origin_access_identity=self.oai,
                ),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            ),
            default_root_object="index.html",
            error_responses=[
                cloudfront.ErrorResponse(
                    http_status=403,
                    response_http_status=200,
                    response_page_path="/index.html",
                ),
                cloudfront.ErrorResponse(
                    http_status=404,
                    response_http_status=200,
                    response_page_path="/index.html",
                ),
            ],
        )

        # --- Cognito User Pool ---

        self.user_pool = cognito.UserPool(
            self,
            "DriveThruUserPool",
            user_pool_name="DriveThruUserPool",
            self_sign_up_enabled=True,
            sign_in_aliases=cognito.SignInAliases(email=True),
            auto_verify=cognito.AutoVerifiedAttrs(email=True),
            standard_attributes=cognito.StandardAttributes(
                email=cognito.StandardAttribute(required=True, mutable=True),
            ),
            password_policy=cognito.PasswordPolicy(
                min_length=8,
                require_lowercase=True,
                require_uppercase=True,
                require_digits=True,
                require_symbols=False,
            ),
            removal_policy=RemovalPolicy.DESTROY,
        )

        # User Pool Client
        self.user_pool_client = self.user_pool.add_client(
            "DriveThruUserPoolClient",
            user_pool_client_name="DriveThruWebClient",
            auth_flows=cognito.AuthFlow(
                user_password=True,
                user_srp=True,
            ),
            generate_secret=False,
        )

        # --- Cognito Identity Pool ---

        self.identity_pool = cognito.CfnIdentityPool(
            self,
            "DriveThruIdentityPool",
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

        # Trust policy allowing Cognito Identity Pool to assume this role
        self.authenticated_role = iam.Role(
            self,
            "CognitoAuthenticatedRole",
            assumed_by=iam.FederatedPrincipal(
                "cognito-identity.amazonaws.com",
                conditions={
                    "StringEquals": {
                        "cognito-identity.amazonaws.com:aud": self.identity_pool.ref,
                    },
                    "ForAnyValue:StringLike": {
                        "cognito-identity.amazonaws.com:amr": "authenticated",
                    },
                },
                assume_role_action="sts:AssumeRoleWithWebIdentity",
            ),
        )

        # Least-privilege: read-only access to DynamoDB menu table
        self.authenticated_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "dynamodb:GetItem",
                    "dynamodb:Query",
                    "dynamodb:Scan",
                    "dynamodb:BatchGetItem",
                ],
                resources=[
                    self.menu_table.table_arn,
                    f"{self.menu_table.table_arn}/index/*",
                ],
            )
        )

        # Least-privilege: read access to S3 food images bucket
        self.authenticated_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "s3:GetObject",
                ],
                resources=[
                    f"{self.images_bucket.bucket_arn}/*",
                ],
            )
        )

        # Attach the authenticated role to the Identity Pool
        cognito.CfnIdentityPoolRoleAttachment(
            self,
            "IdentityPoolRoleAttachment",
            identity_pool_id=self.identity_pool.ref,
            roles={"authenticated": self.authenticated_role.role_arn},
        )

        # --- AgentCore Runtime ---

        # Package and upload agent code to S3 as a zip asset.
        agent_code_path = os.path.join(os.path.dirname(__file__), "..", "agent")
        agent_code_asset = cdk.aws_s3_assets.Asset(
            self,
            "AgentCodeAsset",
            path=agent_code_path,
        )

        self.agent_runtime = agentcore.Runtime(
            self,
            "DriveThruAgentRuntime",
            runtime_name="DriveThruVoiceAgent",
            agent_runtime_artifact=agentcore.AgentRuntimeArtifact.from_s3(
                s3.Location(
                    bucket_name=agent_code_asset.s3_bucket_name,
                    object_key=agent_code_asset.s3_object_key,
                ),
                agentcore.AgentCoreRuntime.PYTHON_3_13,
                ["main.py"],
            ),
            authorizer_configuration=agentcore.RuntimeAuthorizerConfiguration.using_cognito(
                self.user_pool,
                [self.user_pool_client],
            ),
            environment_variables={
                "MENU_TABLE_NAME": self.menu_table.table_name,
                "ORDERS_TABLE_NAME": self.orders_table.table_name,
                "IMAGES_BUCKET_NAME": self.images_bucket.bucket_name,
            },
            description="Drive-thru voice ordering agent powered by Nova Sonic",
        )

        # Grant the runtime permissions to invoke Nova Sonic
        self.agent_runtime.role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                ],
                resources=[
                    f"arn:aws:bedrock:us-east-1:{self.account}:inference-profile/us.amazon.nova-sonic-v1:0",
                    "arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-sonic-v1:0",
                ],
            )
        )

        # DynamoDB: read/write access to orders table
        self.orders_table.grant_read_write_data(self.agent_runtime)

        # DynamoDB: read-only access to menu table
        self.menu_table.grant_read_data(self.agent_runtime)

        # S3: read access to food images bucket
        self.images_bucket.grant_read(self.agent_runtime)

        # --- Frontend Deployment ---

        # Deploy the pre-built frontend to S3.
        # Before running `cdk deploy`, build the frontend:
        #   cd frontend && npm ci && npm run build
        # CDK then uploads the dist/ directory to S3 and invalidates CloudFront.
        frontend_dist_path = os.path.join(
            os.path.dirname(__file__), "..", "frontend", "dist"
        )

        self.frontend_deployment = s3deploy.BucketDeployment(
            self,
            "DeployFrontend",
            sources=[s3deploy.Source.asset(frontend_dist_path)],
            destination_bucket=self.hosting_bucket,
            distribution=self.distribution,
            distribution_paths=["/*"],
        )

        # Deploy runtime-config.json with resource IDs the frontend needs.
        # This is a separate deployment so it can reference CDK token values
        # (Cognito IDs, agent endpoint) that are resolved at deploy time.
        self.config_deployment = s3deploy.BucketDeployment(
            self,
            "DeployRuntimeConfig",
            sources=[
                s3deploy.Source.json_data(
                    "runtime-config.json",
                    {
                        "userPoolId": self.user_pool.user_pool_id,
                        "userPoolClientId": self.user_pool_client.user_pool_client_id,
                        "identityPoolId": self.identity_pool.ref,
                        "menuTableName": self.menu_table.table_name,
                        "awsRegion": self.region,
                        "agentEndpointUrl": f"wss://bedrock-agentcore.{self.region}.amazonaws.com/runtimes/{self.agent_runtime.agent_runtime_arn}/ws",
                    },
                ),
            ],
            destination_bucket=self.hosting_bucket,
            distribution=self.distribution,
            distribution_paths=["/runtime-config.json"],
            # Don't delete existing files (the frontend build is already there)
            prune=False,
        )

        # --- Stack Outputs ---

        cdk.CfnOutput(self, "MenuTableName", value=self.menu_table.table_name)
        cdk.CfnOutput(self, "OrdersTableName", value=self.orders_table.table_name)
        cdk.CfnOutput(self, "ImagesBucketName", value=self.images_bucket.bucket_name)
        cdk.CfnOutput(self, "HostingBucketName", value=self.hosting_bucket.bucket_name)
        cdk.CfnOutput(
            self,
            "DistributionDomainName",
            value=self.distribution.distribution_domain_name,
        )
        cdk.CfnOutput(
            self,
            "UserPoolId",
            value=self.user_pool.user_pool_id,
        )
        cdk.CfnOutput(
            self,
            "UserPoolClientId",
            value=self.user_pool_client.user_pool_client_id,
        )
        cdk.CfnOutput(
            self,
            "IdentityPoolId",
            value=self.identity_pool.ref,
        )
        cdk.CfnOutput(
            self,
            "AgentRuntimeId",
            value=self.agent_runtime.agent_runtime_id,
        )
        cdk.CfnOutput(
            self,
            "AgentEndpointUrl",
            value=f"wss://bedrock-agentcore.{self.region}.amazonaws.com/runtimes/{self.agent_runtime.agent_runtime_arn}/ws",
        )
