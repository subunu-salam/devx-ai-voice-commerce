#!/usr/bin/env python3
import aws_cdk as cdk
from drive_thru_voice_ordering_stack import DriveThruVoiceOrderingStack

app = cdk.App()
DriveThruVoiceOrderingStack(app, "DriveThruVoiceOrderingStack")
app.synth()
