"""CDK snapshot and resource verification tests for DriveThruVoiceOrderingStack.

Validates Requirements 7.1–7.11:
- DynamoDB tables (menu + orders)
- S3 buckets (images + hosting)
- CloudFront distribution with OAI
- Cognito User Pool, User Pool Client, Identity Pool
- IAM roles (authenticated + agent)
"""

import json
import pytest
import aws_cdk as cdk
from aws_cdk.assertions import Template, Match

import sys
import os

# Add the cdk directory to the path so we can import the stack
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from drive_thru_voice_ordering_stack import DriveThruVoiceOrderingStack


@pytest.fixture(scope="module")
def template():
    """Synthesize the stack and return the CloudFormation template."""
    app = cdk.App()
    stack = DriveThruVoiceOrderingStack(app, "TestStack")
    return Template.from_stack(stack)


@pytest.fixture(scope="module")
def template_json(template):
    """Return the raw CloudFormation template as a dict for snapshot comparison."""
    return template.to_json()


class TestSnapshotStructure:
    """Snapshot-style tests verifying the template has expected top-level structure."""

    def test_template_has_resources(self, template_json):
        """Template should contain a Resources section."""
        assert "Resources" in template_json

    def test_template_has_outputs(self, template_json):
        """Template should contain Outputs for key resource identifiers."""
        assert "Outputs" in template_json
        outputs = template_json["Outputs"]
        expected_output_keys = [
            "MenuTableName",
            "OrdersTableName",
            "ImagesBucketName",
            "HostingBucketName",
            "DistributionDomainName",
            "UserPoolId",
            "UserPoolClientId",
            "IdentityPoolId",
            "AgentRoleArn",
        ]
        for key in expected_output_keys:
            assert key in outputs, f"Missing output: {key}"


class TestDynamoDBTables:
    """Verify DynamoDB tables — Requirements 7.1, 7.2."""

    def test_has_two_dynamodb_tables(self, template):
        template.resource_count_is("AWS::DynamoDB::Table", 2)

    def test_menu_table_schema(self, template):
        """Menu table has PK (String) partition key and SK (String) sort key."""
        template.has_resource_properties(
            "AWS::DynamoDB::Table",
            {
                "TableName": "DriveThruMenu",
                "KeySchema": Match.array_with(
                    [
                        {"AttributeName": "PK", "KeyType": "HASH"},
                        {"AttributeName": "SK", "KeyType": "RANGE"},
                    ]
                ),
            },
        )

    def test_orders_table_schema(self, template):
        """Orders table has orderId (String) partition key."""
        template.has_resource_properties(
            "AWS::DynamoDB::Table",
            {
                "TableName": "DriveThruOrders",
                "KeySchema": Match.array_with(
                    [
                        {"AttributeName": "orderId", "KeyType": "HASH"},
                    ]
                ),
            },
        )

    def test_tables_use_pay_per_request(self, template):
        """Both tables use PAY_PER_REQUEST billing mode."""
        template.has_resource_properties(
            "AWS::DynamoDB::Table",
            {"BillingMode": "PAY_PER_REQUEST"},
        )


class TestS3Buckets:
    """Verify S3 buckets — Requirements 7.3, 7.4."""

    def test_has_two_s3_buckets(self, template):
        template.resource_count_is("AWS::S3::Bucket", 2)

    def test_buckets_block_public_access(self, template):
        """Both buckets should block all public access."""
        template.has_resource_properties(
            "AWS::S3::Bucket",
            {
                "PublicAccessBlockConfiguration": {
                    "BlockPublicAcls": True,
                    "BlockPublicPolicy": True,
                    "IgnorePublicAcls": True,
                    "RestrictPublicBuckets": True,
                },
            },
        )


class TestCloudFront:
    """Verify CloudFront distribution — Requirements 7.5, 7.11."""

    def test_has_one_distribution(self, template):
        template.resource_count_is("AWS::CloudFront::Distribution", 1)

    def test_has_origin_access_identity(self, template):
        """OAI exists for restricting direct S3 access (Req 7.11)."""
        template.resource_count_is(
            "AWS::CloudFront::CloudFrontOriginAccessIdentity", 1
        )

    def test_distribution_has_default_root_object(self, template):
        template.has_resource_properties(
            "AWS::CloudFront::Distribution",
            {
                "DistributionConfig": Match.object_like(
                    {"DefaultRootObject": "index.html"}
                ),
            },
        )

    def test_distribution_redirects_to_https(self, template):
        template.has_resource_properties(
            "AWS::CloudFront::Distribution",
            {
                "DistributionConfig": Match.object_like(
                    {
                        "DefaultCacheBehavior": Match.object_like(
                            {"ViewerProtocolPolicy": "redirect-to-https"}
                        ),
                    }
                ),
            },
        )


class TestCognito:
    """Verify Cognito resources — Requirements 7.6, 7.7."""

    def test_has_one_user_pool(self, template):
        template.resource_count_is("AWS::Cognito::UserPool", 1)

    def test_has_one_user_pool_client(self, template):
        template.resource_count_is("AWS::Cognito::UserPoolClient", 1)

    def test_has_one_identity_pool(self, template):
        template.resource_count_is("AWS::Cognito::IdentityPool", 1)

    def test_user_pool_has_email_sign_in(self, template):
        template.has_resource_properties(
            "AWS::Cognito::UserPool",
            {
                "UsernameAttributes": Match.array_with(["email"]),
            },
        )

    def test_identity_pool_disallows_unauthenticated(self, template):
        template.has_resource_properties(
            "AWS::Cognito::IdentityPool",
            {
                "AllowUnauthenticatedIdentities": False,
            },
        )


class TestIAMRoles:
    """Verify IAM roles — Requirements 7.9, 7.10."""

    def test_has_at_least_two_iam_roles(self, template):
        """At least authenticated role + agent role."""
        resources = template.to_json()["Resources"]
        role_count = sum(
            1
            for r in resources.values()
            if r["Type"] == "AWS::IAM::Role"
        )
        assert role_count >= 2, f"Expected at least 2 IAM roles, found {role_count}"

    def test_agent_role_assumed_by_bedrock(self, template):
        """Agent role should be assumable by bedrock.amazonaws.com (Req 7.9)."""
        template.has_resource_properties(
            "AWS::IAM::Role",
            {
                "AssumeRolePolicyDocument": Match.object_like(
                    {
                        "Statement": Match.array_with(
                            [
                                Match.object_like(
                                    {
                                        "Principal": Match.object_like(
                                            {"Service": "bedrock.amazonaws.com"}
                                        ),
                                    }
                                )
                            ]
                        ),
                    }
                ),
            },
        )

    def test_authenticated_role_assumed_by_cognito(self, template):
        """Authenticated role should be assumable via cognito-identity (Req 7.10)."""
        template.has_resource_properties(
            "AWS::IAM::Role",
            {
                "AssumeRolePolicyDocument": Match.object_like(
                    {
                        "Statement": Match.array_with(
                            [
                                Match.object_like(
                                    {
                                        "Principal": Match.object_like(
                                            {
                                                "Federated": "cognito-identity.amazonaws.com"
                                            }
                                        ),
                                    }
                                )
                            ]
                        ),
                    }
                ),
            },
        )


class TestIdentityPoolRoleAttachment:
    """Verify Identity Pool role attachment — Requirement 7.7."""

    def test_has_identity_pool_role_attachment(self, template):
        template.resource_count_is(
            "AWS::Cognito::IdentityPoolRoleAttachment", 1
        )
