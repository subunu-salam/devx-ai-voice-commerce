#!/usr/bin/env python3
"""CDK app with two stacks: BackendStack and FrontendStack.

Deploy flow:
  1. cdk deploy BackendStack
  2. python deploy_frontend.py   (generates runtime-config.json, builds frontend)
  3. cdk deploy FrontendStack
"""
import os
import aws_cdk as cdk
from backend_stack import BackendStack
from frontend_stack import FrontendStack

app = cdk.App()

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

app.synth()
