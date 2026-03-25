"""CDK Stack for the Drive-Thru Voice Ordering system.

Provisions DynamoDB tables, S3 buckets, CloudFront distribution,
Cognito User Pool, Identity Pool, and IAM policies.
"""

import aws_cdk as cdk
from aws_cdk import (
    Stack,
    RemovalPolicy,
    aws_dynamodb as dynamodb,
    aws_s3 as s3,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_cognito as cognito,
    aws_iam as iam,
)
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

        # --- AgentCore Runtime Agent IAM Role ---
        # Note: AgentCore Runtime does not yet have a native CDK L2 construct.
        # The AgentCore endpoint should be configured via the AWS CLI, console,
        # or a CfnResource (custom resource) once available. This role is
        # intended to be associated with the AgentCore Runtime agent.

        self.agent_role = iam.Role(
            self,
            "AgentCoreAgentRole",
            assumed_by=iam.ServicePrincipal("bedrock.amazonaws.com"),
            description="IAM role for the AgentCore Runtime drive-thru voice ordering agent",
        )

        # Bedrock: invoke Nova Sonic model in us-east-1
        self.agent_role.add_to_policy(
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
        self.orders_table.grant_read_write_data(self.agent_role)

        # DynamoDB: read-only access to menu table
        self.menu_table.grant_read_data(self.agent_role)

        # S3: read access to food images bucket
        self.images_bucket.grant_read(self.agent_role)

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
            "AgentRoleArn",
            value=self.agent_role.role_arn,
        )
