import hashlib
from types import SimpleNamespace
from unittest.mock import MagicMock

from navigan.modules.migration_management.models import CreateSourceCluster
from navigan.modules.migration_management.repository import Repository
from navigan.modules.migration_management.service import Service


class Access:
    def __init__(self, privileges):
        self.privileges = privileges

    def require(self, privilege):
        assert privilege in self.privileges

    def require_customer(self, customer_id, owner_id=None):
        assert customer_id == "CUS-demo"


class SourceRepository:
    def __init__(self):
        self.principal = SimpleNamespace(user_id="engineer-1")
        self.created = None
        self.source = {
            "source_cluster_id": "SRC-" + "a" * 32,
            "customer_id": "CUS-demo",
            "created_by": "engineer-1",
            "status": "PENDING_ENROLLMENT",
            "version": 1,
        }
        self.enrollment_token = None

    def require_customer_visible(self, customer_id):
        assert customer_id == "CUS-demo"

    def create_source_cluster(self, row, correlation):
        self.created = row
        return row

    def get_source_cluster(self, identifier, lock=False):
        assert identifier == self.source["source_cluster_id"]
        assert lock is True
        return self.source

    def create_source_enrollment(
        self,
        source_cluster,
        token,
        reason,
        correlation,
    ):
        self.enrollment_token = token
        return {
            "enrollment_id": "SCE-" + "b" * 32,
            "source_cluster_id": source_cluster["source_cluster_id"],
            "status": "ISSUED",
            "expires_at": "2026-10-06T12:15:00+00:00",
        }


def test_registers_cloud_neutral_customer_scoped_source_cluster():
    repository = SourceRepository()
    service = Service(
        repository,
        Access({"migration.create"}),
        "corr-register",
    )

    result = service.create_source_cluster(
        CreateSourceCluster.model_validate({
            "customerId": "CUS-demo",
            "name": "retailflow-source",
            "distribution": "kubeadm",
            "registrationMethod": "LOCAL_KUBECONFIG",
            "location": {
                "type": "ON_PREMISES",
                "region": "Chennai DC",
            },
        }).model_dump(mode="json")
    )

    assert result["sourceClusterId"].startswith("SRC-")
    assert repository.created["delivery_method"] == "MANUAL_HELM"
    assert repository.created["delivery_configuration"] == {}
    assert repository.created["cloud_provider"] is None
    assert repository.created["status"] == "PENDING_ENROLLMENT"


def test_enrollment_secret_is_returned_once_for_local_bootstrap():
    repository = SourceRepository()
    service = Service(
        repository,
        Access({"migration.edit"}),
        "corr-enroll",
    )

    result = service.create_source_enrollment(
        repository.source["source_cluster_id"],
        {"version": 1, "reason": "Install read-only connector"},
    )

    assert result["enrollmentToken"] == repository.enrollment_token
    assert len(result["enrollmentToken"]) >= 43
    assert "tokenSha256" not in result


def test_repository_persists_only_enrollment_token_hash():
    database = MagicMock()
    principal = SimpleNamespace(user_id="engineer-1")
    repository = Repository(database, principal)
    source = {"source_cluster_id": "SRC-" + "a" * 32}
    raw_token = "one-time-secret-that-must-never-be-stored"
    database.execute.return_value.fetchone.return_value = {
        "enrollment_id": "SCE-" + "b" * 32,
        "source_cluster_id": source["source_cluster_id"],
        "status": "ISSUED",
        "expires_at": "2026-10-06T12:15:00+00:00",
    }

    result = repository.create_source_enrollment(
        source,
        raw_token,
        "Install read-only connector",
        "corr-hash",
    )

    insert_params = database.execute.call_args_list[1].args[1]
    assert insert_params[2] == hashlib.sha256(raw_token.encode()).hexdigest()
    assert raw_token not in str(database.execute.call_args_list)
    assert "tokenSha256" not in result


def ssm_body(customer='CUS-demo'):
    return {'customerId': customer, 'name': 'lab', 'distribution': 'kubeadm',
            'registrationMethod': 'PROVIDER_AUTOMATION',
            'location': {'type': 'CLOUD', 'cloudProvider': 'AWS', 'region': 'ap-south-1'},
            'delivery': {'method': 'AWS_SSM', 'awsSsm': {
                'accountId': '905418045935', 'region': 'ap-south-1',
                'managedInstanceId': 'i-08e28d9b2242cbd53', 'kubeconfigPath': '/etc/kubernetes/admin.conf'}}}


def test_registering_same_customer_host_reuses_source_across_assessments():
    repo = MagicMock()
    repo.principal = SimpleNamespace(user_id='engineer-1')
    existing = {'source_cluster_id': 'SRC-' + 'a' * 32, 'customer_id': 'CUS-demo', 'status': 'CONNECTED'}
    repo.find_source_registration.return_value = existing
    result = Service(repo, Access({'migration.create'}), 'reuse').create_source_cluster(ssm_body())
    assert result['sourceClusterId'] == existing['source_cluster_id']
    repo.lock_source_installation.assert_called_once()
    repo.create_source_cluster.assert_not_called()
    repo.create_source_enrollment.assert_not_called()
    repo.audit_source_cluster.assert_called_once()


def test_new_customer_registration_is_created_when_no_customer_match_exists():
    repo = MagicMock()
    repo.principal = SimpleNamespace(user_id='engineer-1')
    repo.find_source_registration.return_value = None
    repo.create_source_cluster.side_effect = lambda row, correlation: row
    result = Service(repo, Access({'migration.create'}), 'new').create_source_cluster(ssm_body())
    assert result['customerId'] == 'CUS-demo'
    repo.create_source_cluster.assert_called_once()
    repo.create_source_enrollment.assert_not_called()


def test_registration_lookup_matches_physical_identity_and_customer_not_display_name():
    db = MagicMock()
    principal = SimpleNamespace(platform_scope=True)
    repo = Repository(db, principal)
    db.execute.return_value.fetchone.return_value = None
    body = ssm_body()
    assert repo.find_source_registration({'customer_id': body['customerId'],
        'delivery_configuration': body['delivery']['awsSsm']}) is None
    sql, params = db.execute.call_args.args
    assert 'customer_id=%s' in sql and "status<>'REVOKED'" in sql
    assert params == ['CUS-demo', '905418045935', 'ap-south-1', 'i-08e28d9b2242cbd53', '/etc/kubernetes/admin.conf']
    assert 'name=' not in sql
