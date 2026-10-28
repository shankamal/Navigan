#!/usr/bin/env python3
"""Stage a minimal DEV migration update from deployed processed CFN templates.

Never reconstructs API Gateway routes or infrastructure from a local SAM
template. Changes are limited to two Lambda packages, one inline IAM grant,
and an image/environment pin. Existing API routes are preserved.
"""

import argparse
import copy
import json
from pathlib import Path

ROOT_RESOURCE = "MigrationManagement"
BUCKET = "aws-sam-cli-managed-default-samclisourcebucket-xj9yzigmdgri"
ROLE = "arn:aws:iam::905418045935:role/NaviganSourceConnectorDeliveryRole"
ALLOWED = {
    "MigrationFunction",
    "MigrationConnectorFunction",
    "MigrationFunctionRole",
}
# CloudFormation also reports integrations that reference the updated Lambda
# ARNs as indirect modifications, even though their template definitions are
# byte-for-byte unchanged. Require a reference-only cause for these two.
INDIRECT_INTEGRATIONS = {
    "MigrationIntegration": "MigrationFunction",
    "MigrationConnectorIntegration": "MigrationConnectorFunction",
}


def _template(response):
    body = response.get("TemplateBody")
    if not isinstance(body, dict) or not isinstance(body.get("Resources"), dict):
        raise ValueError("Expected the deployed PROCESSED CloudFormation JSON template")
    return body


def stage_templates(root_response, child_response, template_url, code_key, repo, digest, api_id):
    root = copy.deepcopy(_template(root_response))
    original_child = _template(child_response)
    child = copy.deepcopy(original_child)
    root_nested = root["Resources"].get(ROOT_RESOURCE)
    if not isinstance(root_nested, dict) or root_nested.get("Type") != "AWS::CloudFormation::Stack":
        raise ValueError("Deployed root is missing MigrationManagement nested stack")
    url_prefix = f"https://s3.ap-south-1.amazonaws.com/{BUCKET}/"
    if not root_nested.get("Properties", {}).get("TemplateURL", "").startswith(url_prefix):
        raise ValueError("Unexpected deployed MigrationManagement template URL")
    if not template_url.startswith(url_prefix) or template_url == root_nested["Properties"]["TemplateURL"]:
        raise ValueError("Invalid new nested template URL")
    if not code_key.startswith("navigan-ashok-dev/migration-only/e62378a0e5f1/"):
        raise ValueError("Unexpected previously built Lambda artifact location")
    if repo != "905418045935.dkr.ecr.ap-south-1.amazonaws.com/navigan/migration-source-connector":
        raise ValueError("Unexpected DEV connector repository")
    if len(digest) != 71 or not digest.startswith("sha256:") or any(
        ch not in "0123456789abcdef" for ch in digest[7:]
    ):
        raise ValueError("Invalid immutable connector digest")
    if not api_id or not api_id.replace("-", "").isalnum():
        raise ValueError("Invalid API identifier")

    resources = child["Resources"]
    for function in ("MigrationFunction", "MigrationConnectorFunction"):
        definition = resources.get(function, {})
        if definition.get("Type") != "AWS::Lambda::Function":
            raise ValueError(f"Expected deployed Lambda function {function}")
        old_code = definition["Properties"].get("Code", {})
        if "S3Bucket" not in old_code or "S3Key" not in old_code:
            raise ValueError(f"Cannot safely replace code on {function}")
        definition["Properties"]["Code"] = {"S3Bucket": BUCKET, "S3Key": code_key}

    env = resources["MigrationFunction"]["Properties"].setdefault("Environment", {}).setdefault("Variables", {})
    env.update({
        "MIGRATION_CONNECTOR_IMAGE_REPOSITORY": repo,
        "MIGRATION_CONNECTOR_IMAGE_DIGEST": digest,
        "SOURCE_CONNECTOR_DELIVERY_ROLE_ARN": ROLE,
        "MIGRATION_CONNECTOR_API_BASE_URL": f"https://{api_id}.execute-api.ap-south-1.amazonaws.com/v1/api/v1",
    })

    role = resources.get("MigrationFunctionRole", {})
    if role.get("Type") != "AWS::IAM::Role":
        raise ValueError("Expected the deployed MigrationFunctionRole")
    policies = role["Properties"].setdefault("Policies", [])
    if not isinstance(policies, list) or any(
        entry.get("PolicyName") == "NaviganDevSourceConnectorAssumeRole" for entry in policies
    ):
        raise ValueError("Unexpected existing source delivery policy")
    policies.append({
        "PolicyName": "NaviganDevSourceConnectorAssumeRole",
        "PolicyDocument": {
            "Version": "2012-10-17",
            "Statement": [{"Effect": "Allow", "Action": ["sts:AssumeRole"], "Resource": ROLE}],
        },
    })

    modified = {
        name for name in resources if resources.get(name) != original_child["Resources"].get(name)
    }
    removed = set(original_child["Resources"]) - set(resources)
    if modified != ALLOWED or removed:
        raise ValueError("Refusing unexpected nested stack changes")

    root_nested["Properties"]["TemplateURL"] = template_url
    if root_nested["Properties"].get("Parameters") != _template(root_response)["Resources"][ROOT_RESOURCE]["Properties"].get("Parameters"):
        raise ValueError("Refusing to change existing nested parameters")
    return root, child


def verify_change_set(response):
    if response.get("Status") != "CREATE_COMPLETE":
        raise ValueError("Change set is not ready")
    changes = {item.get("ResourceChange", {}).get("LogicalResourceId"): item.get("ResourceChange", {}) for item in response.get("Changes", [])}
    expected = ALLOWED | set(INDIRECT_INTEGRATIONS)
    if set(changes) != expected or len(response.get("Changes", [])) != len(expected):
        raise ValueError("Unsafe DEV change set: unexpected resources")
    for name, change in changes.items():
        if change.get("Action") != "Modify" or change.get("Replacement") not in (None, False, "False"):
            raise ValueError(f"Unsafe action or resource replacement for {name}")
    for integration, function in INDIRECT_INTEGRATIONS.items():
        change = changes[integration]
        if change.get("ResourceType") != "AWS::ApiGatewayV2::Integration":
            raise ValueError(f"Unexpected resource type for {integration}")
        details = change.get("Details") or []
        if not details:
            raise ValueError(f"Cannot verify indirect-only change for {integration}: no details")
        for detail in details:
            source = detail.get("ChangeSource")
            cause = detail.get("CausingEntity", "")
            if source not in ("ResourceAttribute", "ResourceReference") or not (
                cause == function or cause.startswith(f"{function}.")
            ):
                raise ValueError(
                    f"Unsafe change to {integration}: expected only references to {function}; "
                    f"got {source}: {cause}"
                )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-changeset", type=Path)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--child", type=Path)
    parser.add_argument("--root-output", type=Path)
    parser.add_argument("--child-output", type=Path)
    parser.add_argument("--template-url")
    parser.add_argument("--code-key")
    parser.add_argument("--repository")
    parser.add_argument("--digest")
    parser.add_argument("--api-id")
    args = parser.parse_args()
    if args.verify_changeset:
        verify_change_set(json.loads(args.verify_changeset.read_text()))
        print("Verified: nested change set contains only approved changes, with no replacements.")
        return
    needed = (args.root, args.child, args.root_output, args.child_output,
              args.template_url, args.code_key, args.repository, args.digest, args.api_id)
    if any(value is None for value in needed):
        parser.error("All template input, output, and image flags are required when staging")
    root, child = stage_templates(
        json.loads(args.root.read_text()), json.loads(args.child.read_text()),
        args.template_url, args.code_key, args.repository, args.digest, args.api_id,
    )
    args.root_output.write_text(json.dumps(root, indent=2) + "\n")
    args.child_output.write_text(json.dumps(child, indent=2) + "\n")
    print("Prepared deployed-template update: 2 Lambda packages, 1 IAM grant, image env; routes untouched.")


if __name__ == "__main__":
    main()
