"""Secure AWS Systems Manager delivery for source assessment connectors."""

import base64
import json
import os
import uuid

import boto3

from navigan.shared.errors import ApiError


INSTALLER = r'''
import base64
import json
import re
import subprocess
import sys
import urllib.request

path = sys.argv[1]
with open(path, encoding="utf-8") as handle:
    value = json.load(handle)

source_id = value["sourceClusterId"]
token = value["enrollmentToken"]
api = value["apiBaseUrl"].rstrip("/")
repository = value["imageRepository"]
digest = value["imageDigest"]
kubeconfig = value["kubeconfigPath"]

if not re.fullmatch(r"SRC-[a-f0-9]{32}", source_id):
    raise SystemExit("Invalid source cluster identity.")
if not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", token):
    raise SystemExit("Invalid enrollment credential.")
if not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
    raise SystemExit("Invalid connector image digest.")

body = json.dumps({
    "sourceClusterId": source_id,
    "enrollmentToken": token,
}).encode()
request = urllib.request.Request(
    api + "/source-connectors/enroll",
    data=body,
    method="POST",
    headers={"Content-Type": "application/json"},
)
with urllib.request.urlopen(request, timeout=30) as response:
    enrolled = json.load(response)

connector_id = enrolled["connectorId"]
connector_token = enrolled["connectorToken"]
if not re.fullmatch(r"SCC-[a-f0-9]{32}", connector_id):
    raise SystemExit("Invalid connector identity.")
if not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", connector_token):
    raise SystemExit("Invalid connector credential.")

secret = base64.b64encode(connector_token.encode()).decode()
image = repository + "@" + digest
manifest = f"""
apiVersion: v1
kind: Namespace
metadata:
  name: navigan-migration
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: navigan-source-connector
  namespace: navigan-migration
automountServiceAccountToken: false
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: navigan-source-connector
rules:
- nonResourceURLs: ["/version"]
  verbs: ["get"]
- apiGroups: [""]
  resources: ["nodes","namespaces","services","persistentvolumeclaims"]
  verbs: ["list"]
- apiGroups: ["apps"]
  resources: ["deployments","statefulsets","daemonsets"]
  verbs: ["list"]
- apiGroups: ["batch"]
  resources: ["jobs","cronjobs"]
  verbs: ["list"]
- apiGroups: ["networking.k8s.io"]
  resources: ["ingresses","networkpolicies"]
  verbs: ["list"]
- apiGroups: ["autoscaling"]
  resources: ["horizontalpodautoscalers"]
  verbs: ["list"]
- apiGroups: ["policy"]
  resources: ["poddisruptionbudgets"]
  verbs: ["list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: navigan-source-connector
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: navigan-source-connector
subjects:
- kind: ServiceAccount
  name: navigan-source-connector
  namespace: navigan-migration
---
apiVersion: v1
kind: Secret
metadata:
  name: navigan-source-connector-credentials
  namespace: navigan-migration
type: Opaque
data:
  connector-token: {secret}
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: navigan-source-connector
  namespace: navigan-migration
spec:
  replicas: 1
  strategy:
    type: Recreate
  selector:
    matchLabels:
      app.kubernetes.io/name: navigan-source-connector
  template:
    metadata:
      labels:
        app.kubernetes.io/name: navigan-source-connector
    spec:
      serviceAccountName: navigan-source-connector
      automountServiceAccountToken: false
      enableServiceLinks: false
      securityContext:
        runAsNonRoot: true
        runAsUser: 10001
        runAsGroup: 10001
        fsGroup: 10001
        seccompProfile:
          type: RuntimeDefault
      containers:
      - name: connector
        image: {json.dumps(image)}
        imagePullPolicy: IfNotPresent
        securityContext:
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: true
          runAsNonRoot: true
          capabilities:
            drop: ["ALL"]
        env:
        - name: NAVIGAN_API_BASE_URL
          value: {json.dumps(api)}
        - name: NAVIGAN_SOURCE_CONNECTOR_ID
          value: {json.dumps(connector_id)}
        - name: NAVIGAN_SOURCE_CONNECTOR_TOKEN
          valueFrom:
            secretKeyRef:
              name: navigan-source-connector-credentials
              key: connector-token
        - name: NAVIGAN_POLL_SECONDS
          value: "30"
        resources:
          requests:
            cpu: 25m
            memory: 64Mi
          limits:
            cpu: 250m
            memory: 256Mi
        volumeMounts:
        - name: kubernetes-api-access
          mountPath: /var/run/secrets/kubernetes.io/serviceaccount
          readOnly: true
        - name: temporary
          mountPath: /tmp
      volumes:
      - name: kubernetes-api-access
        projected:
          defaultMode: 420
          sources:
          - serviceAccountToken:
              path: token
              expirationSeconds: 3600
          - configMap:
              name: kube-root-ca.crt
              items:
              - key: ca.crt
                path: ca.crt
      - name: temporary
        emptyDir:
          sizeLimit: 16Mi
"""

subprocess.run(
    ["kubectl", "--kubeconfig", kubeconfig, "apply", "-f", "-"],
    input=manifest,
    text=True,
    check=True,
)
subprocess.run(
    [
        "kubectl", "--kubeconfig", kubeconfig, "-n", "navigan-migration",
        "rollout", "status", "deployment/navigan-source-connector",
        "--timeout=5m",
    ],
    check=True,
)
with open(path, "w", encoding="utf-8") as handle:
    handle.write("")
print("SUCCESS: Navigan source connector installed.")
'''


class SourceConnectorInstaller:
    def __init__(self, client_factory=None):
        self.client_factory = client_factory or boto3.client

    def start(self, source_cluster, enrollment_token):
        configuration = source_cluster["delivery_configuration"]
        if source_cluster["delivery_method"] != "AWS_SSM":
            raise ApiError(
                409,
                "SOURCE_DELIVERY_NOT_AUTOMATED",
                "Configure AWS Systems Manager connector delivery first.",
            )
        role_arn = configuration.get("roleArn") or (
            "arn:aws:iam::"
            + configuration["accountId"]
            + ":role/NaviganSourceConnectorDeliveryRole"
        )
        approved_role = os.environ.get(
            "SOURCE_CONNECTOR_DELIVERY_ROLE_ARN",
            "",
        )
        if role_arn != approved_role:
            raise ApiError(
                403,
                "SOURCE_DELIVERY_ROLE_NOT_APPROVED",
                "The source AWS delivery role is not approved.",
            )

        assumed = self.client_factory("sts").assume_role(
            RoleArn=role_arn,
            RoleSessionName=(
                "NaviganSourceConnector-"
                + source_cluster["source_cluster_id"][-12:]
            ),
            ExternalId=source_cluster["source_cluster_id"],
            DurationSeconds=900,
        )
        credentials = assumed["Credentials"]
        options = {
            "region_name": configuration["region"],
            "aws_access_key_id": credentials["AccessKeyId"],
            "aws_secret_access_key": credentials["SecretAccessKey"],
            "aws_session_token": credentials["SessionToken"],
        }
        account = role_arn.split(":")[4]
        if configuration["accountId"] != account:
            raise ApiError(
                409,
                "SOURCE_ACCOUNT_ROLE_MISMATCH",
                "The delivery role does not belong to the source AWS account.",
            )

        repository = os.environ.get(
            "MIGRATION_CONNECTOR_IMAGE_REPOSITORY",
            "",
        )
        digest = os.environ.get("MIGRATION_CONNECTOR_IMAGE_DIGEST", "")
        api_base = os.environ.get("MIGRATION_CONNECTOR_API_BASE_URL", "")
        if not repository or not digest or not api_base:
            raise ApiError(
                503,
                "SOURCE_CONNECTOR_ARTIFACT_UNAVAILABLE",
                "The source connector artifact is not configured.",
            )

        ssm = self.client_factory("ssm", **options)
        parameter_name = (
            "/navigan/migration/source-connectors/"
            + source_cluster["source_cluster_id"]
            + "/"
            + uuid.uuid4().hex
        )
        bootstrap = {
            "apiBaseUrl": api_base,
            "sourceClusterId": source_cluster["source_cluster_id"],
            "enrollmentToken": enrollment_token,
            "imageRepository": repository,
            "imageDigest": digest,
            "kubeconfigPath": configuration["kubeconfigPath"],
        }
        try:
            ssm.put_parameter(
                Name=parameter_name,
                Description="Short-lived Navigan source connector bootstrap",
                Type="SecureString",
                Value=json.dumps(bootstrap, separators=(",", ":")),
                Overwrite=False,
                Tier="Standard",
            )
            script = base64.b64encode(INSTALLER.encode()).decode()
            command = ssm.send_command(
                InstanceIds=[configuration["managedInstanceId"]],
                DocumentName="AWS-RunShellScript",
                Comment="Install Navigan read-only source connector",
                TimeoutSeconds=600,
                Parameters={
                    "commands": [
                        "set -euo pipefail",
                        "work=$(mktemp -d /tmp/navigan-source.XXXXXX)",
                        "trap 'rm -rf \"$work\"' EXIT",
                        (
                            "aws ssm get-parameter --with-decryption "
                            f"--name '{parameter_name}' "
                            "--query Parameter.Value --output text "
                            '> \"$work/bootstrap.json\"'
                        ),
                        f"aws ssm delete-parameter --name '{parameter_name}'",
                        (
                            f"printf '%s' '{script}' | base64 -d "
                            '> \"$work/install.py\"'
                        ),
                        'chmod 600 "$work/bootstrap.json" "$work/install.py"',
                        'python3 "$work/install.py" "$work/bootstrap.json"',
                    ]
                },
            )
        except Exception:
            try:
                ssm.delete_parameter(Name=parameter_name)
            except Exception:
                pass
            raise

        return {
            "commandId": command["Command"]["CommandId"],
            "managedInstanceId": configuration["managedInstanceId"],
            "status": "INSTALLATION_STARTED",
        }
