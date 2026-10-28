#!/usr/bin/env python3
"""Verify one local image with two fixture configurations; does not call AWS."""
import argparse
import json
import os
from pathlib import Path

import release_common as common

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--image", required=True)
args = parser.parse_args()
builder = common.load("frontend_artifact_check", Path(__file__).with_name("build-release.py"))
record = common.workspace("navigan-image-portability-")
print(json.dumps(builder.image_runtime_check(args.image, record, dict(os.environ)), indent=2))
