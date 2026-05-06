# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

#!/usr/bin/env python3
"""CDK app with two stacks: BackendStack and FrontendStack.

Deploy flow:
  1. cdk deploy BackendStack
  2. python deploy_frontend.py   (generates runtime-config.json, builds frontend)
  3. cdk deploy FrontendStack
"""
import os
import aws_cdk as cdk
from cdk_nag import AwsSolutionsChecks, NagSuppressions, NagReportFormat
from backend_stack import BackendStack
from frontend_stack import FrontendStack

app = cdk.App()

# Apply CDK Nag AWS Solutions checks to all stacks
cdk.Aspects.of(app).add(AwsSolutionsChecks(
    verbose=True,
    reports=True,
    report_formats=[NagReportFormat.CSV, NagReportFormat.JSON],
))

backend = BackendStack(app, "BackendStack")

# Frontend stack reads bucket name and distribution ID from CDK context
# (set by deploy_frontend.py after the backend deploys)
hosting_bucket_name = app.node.try_get_context("hostingBucketName") or "placeholder"
distribution_id = app.node.try_get_context("distributionId") or "placeholder"

frontend = FrontendStack(
    app, "FrontendStack",
    hosting_bucket_name=hosting_bucket_name,
    distribution_id=distribution_id,
)
frontend.add_dependency(backend)

# --- CDK Nag Suppressions for FrontendStack ---
# FrontendStack only contains a CDK BucketDeployment (managed construct)
NagSuppressions.add_stack_suppressions(
    frontend,
    [
        {
            "id": "AwsSolutions-L1",
            "reason": "Lambda runtime version is controlled by the CDK BucketDeployment construct.",
        },
        {
            "id": "AwsSolutions-IAM4",
            "reason": "AWSLambdaBasicExecutionRole is the standard managed policy for Lambda CloudWatch Logs access.",
            "applies_to": [
                "Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
            ],
        },
        {
            "id": "AwsSolutions-IAM5",
            "reason": "Wildcard permissions are required by CDK BucketDeployment for S3 operations on deployment assets and destination bucket.",
            "applies_to": [
                "Action::s3:GetObject*",
                "Action::s3:GetBucket*",
                "Action::s3:List*",
                "Action::s3:DeleteObject*",
                "Action::s3:Abort*",
                "Resource::arn:<AWS::Partition>:s3:::cdk-hnb659fds-assets-<AWS::AccountId>-<AWS::Region>/*",
                "Resource::arn:<AWS::Partition>:s3:::placeholder/*",
                "Resource::*",
            ],
        },
    ],
)

app.synth()
