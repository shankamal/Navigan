from types import SimpleNamespace
import pytest
from pydantic import ValidationError
from navigan.shared.auth import Principal
from navigan.shared.errors import ApiError
from navigan.modules.customer_management.models import CreateCustomer, UpdateCustomer, ProviderSet
from navigan.modules.customer_management.workflow import (
    check_transition,
    check_edit,
    check_version,
    TRANSITIONS,
    STATUSES,
)
from navigan.modules.customer_management.handler import lambda_handler, body_json, parse_version, parse_query

ENGINEER = Principal("maker", frozenset({"CLOUD_ENGINEER"}), frozenset(), False, True)
ARCHITECT = Principal("reviewer", frozenset({"PLATFORM_ARCHITECT"}), frozenset(), True)


@pytest.mark.parametrize("action", list(TRANSITIONS))
@pytest.mark.parametrize("status", sorted(STATUSES))
def test_complete_state_matrix(action, status):
    sources, target, role, _, _ = TRANSITIONS[action]
    principal = ENGINEER if role == "CLOUD_ENGINEER" else ARCHITECT
    customer = {"status": status, "created_by": "maker"}
    if status in sources:
        assert check_transition(customer, action, principal, {"reason": "test"})[0] == target
    else:
        with pytest.raises(ApiError) as error:
            check_transition(customer, action, principal, {"reason": "test"})
        assert error.value.status == 422


@pytest.mark.parametrize("action", list(TRANSITIONS))
def test_role_denial(action):
    sources, _, role, _, _ = TRANSITIONS[action]
    wrong = ARCHITECT if role == "CLOUD_ENGINEER" else ENGINEER
    with pytest.raises(ApiError) as error:
        check_transition(
            {"status": next(iter(sources)), "created_by": "someone"}, action, wrong, {"reason": "test"}
        )
    assert error.value.status == 403


@pytest.mark.parametrize("action", ["review/start", "approve", "reject"])
def test_self_review_denied(action):
    principal = Principal("maker", frozenset({"PLATFORM_ARCHITECT", "CLOUD_ENGINEER"}), frozenset(), True)
    with pytest.raises(ApiError, match="independent"):
        check_transition(
            {"status": next(iter(TRANSITIONS[action][0])), "created_by": "maker"},
            action,
            principal,
            {"reason": "test"},
        )


@pytest.mark.parametrize(
    "field",
    ["accountId", "subscriptionId", "region", "clusterId", "credentials", "status", "customerId", "version"],
)
def test_out_of_scope_and_server_fields_rejected(field):
    with pytest.raises(ValidationError):
        CreateCustomer.model_validate({"name": "Acme", field: "forbidden"})


def test_provider_duplicates_and_name_normalization():
    with pytest.raises(ValidationError):
        ProviderSet(cloudProviders=["AWS", "AWS"])
    assert CreateCustomer(name="  Acme  ").name == "Acme"
    with pytest.raises(ValidationError):
        UpdateCustomer(name="   ")
    with pytest.raises(ValidationError):
        CreateCustomer(name="Acme", contacts=[{"type": "PRIMARY", "name": "Contact", "email": "bad"}])


@pytest.mark.parametrize("body", ["[]", "{", "null", '"text"'])
def test_invalid_json(body):
    with pytest.raises(ApiError):
        body_json({"body": body})


@pytest.mark.parametrize("value", ["*", "0", "-1", 'W/"3"', "1 OR 1=1", "", '"3', '3"'])
def test_invalid_version(value):
    with pytest.raises(ApiError):
        parse_version({"if-match": value})


def test_version_and_query_validation():
    assert parse_version({"if-match": '"5"'}) == 5
    with pytest.raises(ApiError):
        check_version({"version": 5}, 4)
    for query in [{"page": "-1"}, {"pageSize": "101"}, {"sort": "name;DROP TABLE,asc"}, {"status": "BAD"}]:
        with pytest.raises(ApiError):
            parse_query(query)


def test_only_verified_identity_claims():
    event = {"headers": {"Authorization": "Bearer fake", "X-Role": "PLATFORM_ARCHITECT"}}
    result = lambda_handler(event, SimpleNamespace(aws_request_id="test"))
    assert result["statusCode"] == 401
    claims = {"sub": "svc", "roles": ["SERVICE"], "platform_scope": "true"}
    with pytest.raises(ApiError):
        Principal.from_event({"requestContext": {"authorizer": {"jwt": {"claims": claims}}}})


def test_scoped_creation_visibility():
    assert ENGINEER.visible({"customer_id": "CUS-new", "created_by": "maker"})
    assert not ENGINEER.visible({"customer_id": "CUS-other", "created_by": "other"})
    principal = Principal("user", frozenset({"CLOUD_ENGINEER"}), frozenset({"CUS-one"}))
    assert principal.visible({"customer_id": "CUS-one", "created_by": "other"})
    assert not principal.visible({"customer_id": "CUS-two", "created_by": "user"})


@pytest.mark.parametrize("status", sorted(STATUSES))
def test_edit_matrix(status):
    if status in {"DRAFT", "REJECTED"}:
        check_edit({"status": status}, ENGINEER)
    else:
        with pytest.raises(ApiError):
            check_edit({"status": status}, ENGINEER)
