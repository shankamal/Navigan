import json

import pytest

from navigan.modules.migration_management.handler import (
    BASE,
    SOURCE_CLUSTERS_BASE,
    body_of,
    query_of,
    response,
    route_of,
)
from navigan.shared.errors import ApiError


def test_allows_only_assessment_lifecycle_routes():
    identifier = "MIG-" + "a" * 32

    assert route_of("GET", BASE) == ("list", None, None)
    assert route_of("POST", BASE) == ("create", None, None)
    assert route_of("GET", f"{BASE}/{identifier}") == (
        "get",
        identifier,
        None,
    )
    assert route_of("POST", f"{BASE}/{identifier}/discover") == (
        "action",
        identifier,
        "discover",
    )
    assert route_of("POST", f"{BASE}/{identifier}/submit") == (
        "action",
        identifier,
        "submit",
    )


def test_rejects_execution_route():
    identifier = "MIG-" + "b" * 32

    with pytest.raises(ApiError) as error:
        route_of("POST", f"{BASE}/{identifier}/execute")

    assert error.value.code == "ROUTE_NOT_FOUND"


def test_rejects_unknown_query_parameter():
    with pytest.raises(ApiError) as error:
        query_of(
            {
                "queryStringParameters": {
                    "includeSecrets": "true",
                }
            }
        )

    assert error.value.code == "INVALID_QUERY"


def test_rejects_non_object_body():
    with pytest.raises(ApiError) as error:
        body_of({"body": json.dumps(["not", "an", "object"])})

    assert error.value.code == "INVALID_JSON"


def test_response_disables_caching():
    result = response(200, {"status": "ok"}, "corr-1")

    assert result["headers"]["Cache-Control"] == "no-store"
    assert result["headers"]["X-Correlation-ID"] == "corr-1"

def test_routes_authenticated_source_catalogue_read():
    identifier = "MIG-" + "c" * 32

    assert route_of(
        "GET",
        f"{BASE}/{identifier}/source-catalogue",
    ) == (
        "source_catalogue",
        identifier,
        None,
    )


def test_routes_to_latest_trusted_assessment():
    identifier = "MIG-" + "c" * 32

    assert route_of(
        "GET",
        f"{BASE}/{identifier}/assessment",
    ) == ("assessment", identifier, None)


def test_routes_authenticated_source_cluster_registration():
    identifier = "SRC-" + "d" * 32

    assert route_of("GET", SOURCE_CLUSTERS_BASE) == (
        "source_cluster_list",
        None,
        None,
    )
    assert route_of("POST", SOURCE_CLUSTERS_BASE) == (
        "source_cluster_create",
        None,
        None,
    )
    assert route_of("GET", f"{SOURCE_CLUSTERS_BASE}/{identifier}") == (
        "source_cluster_get",
        identifier,
        None,
    )
    assert route_of("PUT", f"{SOURCE_CLUSTERS_BASE}/{identifier}") == (
        "source_cluster_update",
        identifier,
        None,
    )
    assert route_of(
        "POST",
        f"{SOURCE_CLUSTERS_BASE}/{identifier}/enrollments",
    ) == ("source_cluster_enrollment", identifier, None)
    assert route_of(
        "POST",
        f"{SOURCE_CLUSTERS_BASE}/{identifier}/install",
    ) == ("source_cluster_install", identifier, None)
