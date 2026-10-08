import copy

import pytest

from navigan.modules.migration_management.service import Service
from navigan.shared.errors import ApiError


class Principal:
    def __init__(self, user_id):
        self.user_id = user_id


class Access:
    def __init__(self, user_id, privileges):
        self.user_id = user_id
        self.privileges = set(privileges)

    def require(self, privilege):
        if privilege not in self.privileges:
            raise ApiError(403, "FORBIDDEN", "Not permitted.")

    def require_customer(self, customer_id, owner_id=None):
        if customer_id != "CUS-demo":
            raise ApiError(403, "FORBIDDEN", "Outside scope.")


class Repository:
    def __init__(self, user_id="creator"):
        self.principal = Principal(user_id)
        self.rows = {}
        self.saved = []

    def require_customer_visible(self, customer_id):
        if customer_id != "CUS-demo":
            raise ApiError(404, "CUSTOMER_NOT_FOUND", "Missing.")

    def get(self, identifier, lock=False):
        return copy.deepcopy(self.rows[identifier])

    def get_source_cluster(self, identifier, lock=False):
        return {
            "source_cluster_id": identifier,
            "customer_id": "CUS-demo",
            "created_by": self.principal.user_id,
            "status": "PENDING_ENROLLMENT",
            "version": 1,
        }

    def update_source_cluster_delivery(
        self,
        source_cluster,
        delivery,
        reason,
        correlation,
    ):
        return {
            **source_cluster,
            "delivery_method": delivery["method"],
            "delivery_configuration": delivery.get("awsSsm") or {},
            "version": source_cluster["version"] + 1,
        }

    def create_source_enrollment(
        self,
        source_cluster,
        token,
        reason,
        correlation,
    ):
        self.enrollment_token = token
        return {
            "enrollment_id": "SCE-" + "e" * 32,
            "source_cluster_id": source_cluster["source_cluster_id"],
            "status": "ISSUED",
        }

    def audit_source_cluster(
        self,
        identifier,
        action,
        correlation,
        details,
    ):
        self.source_audit = (identifier, action, correlation, details)

    def save(self, row, old, action, correlation, create=False):
        self.rows[row["migration_id"]] = copy.deepcopy(row)
        self.saved.append((action, correlation, create))

    def create_discovery_connector(self, identifier, token):
        self.connector_token = token
        return {
            "connector_id": "MGC-" + "c" * 32,
            "migration_id": identifier,
            "status": "ENROLLED",
            "expires_at": "2026-10-05T08:30:00+00:00",
        }


def create_body():
    return {
        "customerId": "CUS-demo",
        "name": "RetailFlow migration",
        "description": "Assessment only.",
        "source": {
            "platform": "SELF_MANAGED_KUBERNETES",
            "clusterName": "migration-lab",
            "accessMode": "READ_ONLY_CONNECTOR",
        },
        "target": {
            "platform": "EKS",
            "environmentId": "ENV-demo",
            "environmentApprovedVersion": 1,
            "awsRegion": "ap-south-1",
            "clusterId": "CLU-demo",
            "clusterName": "retailflow-eks",
            "endpointAccess": "PRIVATE",
        },
        "scope": {
            "namespaces": ["retailflow"],
            "excludeNamespaces": [
                "kube-node-lease",
                "kube-public",
                "kube-system",
            ],
            "includeClusterScopedResources": False,
            "includePersistentData": False,
        },
    }


def test_creates_assessment_only_migration():
    repo = Repository()
    access = Access("creator", {"migration.create"})

    result = Service(repo, access, "corr-1").create(create_body())

    assert result["migrationId"].startswith("MIG-")
    assert result["executionMode"] == "ASSESSMENT_ONLY"
    assert result["status"] == "DRAFT"
    assert repo.saved == [("MIGRATION_CREATED", "corr-1", True)]


def test_configures_aws_ssm_source_connector_delivery():
    repo = Repository()
    access = Access("creator", {"migration.edit"})

    result = Service(repo, access, "corr-source").update_source_cluster_delivery(
        "SRC-" + "a" * 32,
        {
            "version": 1,
            "delivery": {
                "method": "AWS_SSM",
                "awsSsm": {
                    "accountId": "905418045935",
                    "region": "ap-south-1",
                    "managedInstanceId": "i-08e28d9b2242cbd53",
                    "kubeconfigPath": "/etc/kubernetes/admin.conf",
                },
            },
            "reason": "Configure secure delivery",
        },
    )

    assert result["deliveryMethod"] == "AWS_SSM"
    assert result["version"] == 2


def test_starts_automatic_source_connector_installation():
    repo = Repository()
    access = Access("creator", {"migration.edit"})

    class Installer:
        def start(self, source_cluster, token):
            assert source_cluster["source_cluster_id"].startswith("SRC-")
            assert token == repo.enrollment_token
            return {
                "commandId": "11111111-2222-3333-4444-555555555555",
                "managedInstanceId": "i-08e28d9b2242cbd53",
                "status": "INSTALLATION_STARTED",
            }

    result = Service(repo, access, "corr-install").install_source_connector(
        "SRC-" + "a" * 32,
        {
            "version": 1,
            "reason": "Install read-only connector",
        },
        Installer(),
    )

    assert result["status"] == "INSTALLATION_STARTED"
    assert result["enrollmentId"] == "SCE-" + "e" * 32
    assert repo.source_audit[1] == "SOURCE_CONNECTOR_INSTALLATION_STARTED"


def test_creator_cannot_review_own_request():
    repo = Repository()
    access = Access("creator", {"migration.create", "migration.review"})
    created = Service(repo, access, "corr-1").create(create_body())

    repo.rows[created["migrationId"]]["status"] = "SUBMITTED"

    with pytest.raises(ApiError) as error:
        Service(repo, access, "corr-2").change(
            created["migrationId"],
            "review",
            {"version": 1, "reason": "Review request"},
        )

    assert error.value.code == "SEPARATION_OF_DUTIES_REQUIRED"


def test_independent_reviewer_can_review_request():
    repo = Repository()
    creator = Access("creator", {"migration.create"})
    created = Service(repo, creator, "corr-1").create(create_body())
    identifier = created["migrationId"]
    repo.rows[identifier]["status"] = "SUBMITTED"

    repo.principal = Principal("reviewer")
    reviewer = Access("reviewer", {"migration.review"})

    result = Service(repo, reviewer, "corr-2").change(
        identifier,
        "review",
        {"version": 1, "reason": "Assessment reviewed"},
    )

    assert result["status"] == "UNDER_REVIEW"
    assert result["version"] == 2


def test_rejects_stale_version():
    repo = Repository()
    access = Access("creator", {"migration.create", "migration.edit"})
    created = Service(repo, access, "corr-1").create(create_body())

    with pytest.raises(ApiError) as error:
        Service(repo, access, "corr-2").update(
            created["migrationId"],
            {
                "version": 99,
                "name": "Updated migration",
                "changeReason": "Rename request",
            },
        )

    assert error.value.code == "CONCURRENT_UPDATE"


def test_no_execution_transition_exists():
    assert "execute" not in __import__(
        "navigan.modules.migration_management.service",
        fromlist=["TRANSITIONS"],
    ).TRANSITIONS
def test_discovery_can_be_requested_from_draft():
    repo = Repository()
    access = Access(
        "creator",
        {"migration.create", "migration.edit"},
    )
    created = Service(repo, access, "corr-1").create(create_body())

    result = Service(repo, access, "corr-2").change(
        created["migrationId"],
        "discover",
        {
            "version": 1,
            "reason": "Begin read-only source discovery",
            "connectorToken": (
                "migration-connector-token-value-with-"
                "sufficient-length"
            ),
        },
    )

    assert result["status"] == "SOURCE_ENROLLMENT_PENDING"
    assert result["discoveryConnector"]["connectorId"].startswith(
        "MGC-"
    )
    assert "connectorToken" not in str(result)
    assert result["version"] == 2
    assert repo.saved[-1] == (
        "MIGRATION_DISCOVER",
        "corr-2",
        False,
    )


def test_draft_cannot_be_submitted_without_assessment():
    repo = Repository()
    access = Access(
        "creator",
        {"migration.create", "migration.submit"},
    )
    created = Service(repo, access, "corr-1").create(create_body())

    with pytest.raises(ApiError) as error:
        Service(repo, access, "corr-2").change(
            created["migrationId"],
            "submit",
            {
                "version": 1,
                "reason": "Submit without assessment",
            },
        )

    assert error.value.code == "INVALID_MIGRATION_TRANSITION"


def test_assessment_ready_migration_can_be_submitted():
    repo = Repository()
    access = Access(
        "creator",
        {"migration.create", "migration.submit"},
    )
    created = Service(repo, access, "corr-1").create(create_body())
    identifier = created["migrationId"]
    repo.rows[identifier]["status"] = "ASSESSMENT_READY"

    result = Service(repo, access, "corr-2").change(
        identifier,
        "submit",
        {
            "version": 1,
            "reason": "Sanitized assessment is ready",
        },
    )

    assert result["status"] == "SUBMITTED"
    assert result["version"] == 2


def minimal_create_body():
    return {
        "customerId": "CUS-demo",
        "name": "RetailFlow staged assessment",
        "source": {
            "platform": "SELF_MANAGED_KUBERNETES",
            "accessMode": "READ_ONLY_CONNECTOR",
        },
        "target": {
            "platform": "EKS",
            "targetType": "EXISTING_CLUSTER",
            "environmentId": "ENV-demo",
            "environmentApprovedVersion": 1,
            "endpointAccess": "PRIVATE",
        },
        "scope": {
            "namespaces": [],
            "excludeNamespaces": [
                "kube-node-lease",
                "kube-public",
                "kube-system",
            ],
            "includeClusterScopedResources": False,
            "includePersistentData": False,
        },
    }


def test_creates_minimal_staged_draft():
    repo = Repository()
    access = Access("creator", {"migration.create"})

    result = Service(repo, access, "corr-draft").create(
        minimal_create_body()
    )

    assert result["status"] == "DRAFT"
    assert result["sourceConfiguration"].get("clusterName") is None
    assert result["targetConfiguration"].get("clusterId") is None
    assert result["migrationScope"]["namespaces"] == []


def test_minimal_draft_can_start_source_enrollment():
    repo = Repository()
    access = Access(
        "creator",
        {"migration.create", "migration.edit"},
    )
    created = Service(repo, access, "corr-draft").create(
        minimal_create_body()
    )

    result = Service(repo, access, "corr-discover").change(
        created["migrationId"],
        "discover",
        {
            "version": 1,
            "reason": "Enroll read-only source connector",
            "connectorToken": (
                "migration-connector-token-value-with-"
                "sufficient-length"
            ),
        },
    )

    assert result["status"] == "SOURCE_ENROLLMENT_PENDING"
    assert result["discoveryConnector"]["status"] == "ENROLLED"
    assert repo.connector_token.startswith("migration-connector-")

def test_inventory_ready_can_save_scope_and_target_selection():
    repo = Repository()
    access = Access(
        "creator",
        {"migration.create", "migration.edit"},
    )
    created = Service(repo, access, "corr-create").create(
        minimal_create_body()
    )
    identifier = created["migrationId"]
    repo.rows[identifier]["status"] = "INVENTORY_READY"
    repo.rows[identifier]["version"] = 4

    result = Service(repo, access, "corr-update").update(
        identifier,
        {
            "version": 4,
            "source": {
                "platform": "SELF_MANAGED_KUBERNETES",
                "clusterName": "migration-lab",
                "accessMode": "READ_ONLY_CONNECTOR",
            },
            "target": {
                "platform": "EKS",
                "targetType": "EXISTING_CLUSTER",
                "environmentId": "ENV-demo",
                "environmentApprovedVersion": 1,
                "clusterId": "CLU-demo",
                "clusterName": "target-eks",
                "endpointAccess": "PRIVATE",
            },
            "scope": {
                "namespaces": ["retailflow"],
                "excludeNamespaces": [
                    "kube-node-lease",
                    "kube-public",
                    "kube-system",
                ],
                "includeClusterScopedResources": False,
                "includePersistentData": False,
            },
            "changeReason": (
                "Save discovered workload scope and target cluster"
            ),
        },
    )

    assert result["status"] == "INVENTORY_READY"
    assert result["version"] == 5
    assert result["migrationScope"]["namespaces"] == [
        "retailflow"
    ]
    assert result["targetConfiguration"]["clusterId"] == (
        "CLU-demo"
    )


def test_pending_migration_can_recover_missing_source_registration():
    repo = Repository()
    access = Access("creator", {"migration.create", "migration.edit"})
    created = Service(repo, access, "corr-create").create(
        minimal_create_body()
    )
    identifier = created["migrationId"]
    repo.rows[identifier]["status"] = "SOURCE_ENROLLMENT_PENDING"
    repo.rows[identifier]["source_configuration"].pop(
        "sourceClusterId",
        None,
    )

    result = Service(repo, access, "corr-recover").update(
        identifier,
        {
            "version": 1,
            "source": {
                "platform": "SELF_MANAGED_KUBERNETES",
                "sourceClusterId": "SRC-" + "a" * 32,
                "clusterName": "migration-lab",
                "accessMode": "READ_ONLY_CONNECTOR",
            },
            "changeReason": "Attach registered source cluster",
        },
    )

    assert result["status"] == "SOURCE_ENROLLMENT_PENDING"
    assert result["version"] == 2
    assert result["sourceConfiguration"]["sourceClusterId"] == (
        "SRC-" + "a" * 32
    )


def test_starts_detailed_inventory_after_catalogue():
    repo = Repository()
    access = Access("creator", {"migration.create", "migration.edit"})
    service = Service(repo, access, "corr-assess")

    created = service.create(create_body())
    identifier = created["migrationId"]
    repo.rows[identifier]["status"] = "INVENTORY_READY"

    result = service.change(
        identifier,
        "assess",
        {
            "version": 1,
            "reason": "Collect detailed source inventory",
            "connectorToken": "a" * 43,
        },
    )

    assert result["status"] == "DISCOVERY_PENDING"
    assert result["version"] == 2
    assert result["assessmentConnector"]["status"] == "ENROLLED"
    assert repo.connector_token == "a" * 43


def test_refreshes_rejected_assessment_with_connected_source():
    repo = Repository()
    access = Access("creator", {"migration.create", "migration.edit"})
    service = Service(repo, access, "corr-refresh")

    created = service.create(create_body())
    identifier = created["migrationId"]
    repo.rows[identifier]["status"] = "REJECTED"

    result = service.change(
        identifier,
        "assess",
        {
            "version": 1,
            "reason": "Refresh detailed source inventory",
        },
    )

    assert result["status"] == "DISCOVERY_PENDING"
    assert result["version"] == 2
