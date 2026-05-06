# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

#!/usr/bin/env python3
"""Read backend stack outputs and generate frontend/public/runtime-config.json."""

import json
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUTS_FILE = os.path.join(SCRIPT_DIR, "cdk", "backend-outputs.json")
CONFIG_FILE = os.path.join(SCRIPT_DIR, "frontend", "public", "runtime-config.json")


def main():
    with open(OUTPUTS_FILE) as f:
        outputs = json.load(f)["BackendStack"]

    config = {
        "userPoolId": outputs["UserPoolId"],
        "userPoolClientId": outputs["UserPoolClientId"],
        "awsRegion": "us-east-1",
        "agentRuntimeArn": outputs["AgentRuntimeArn"],
    }

    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")

    print(f"Generated {CONFIG_FILE}")
    for k, v in config.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
