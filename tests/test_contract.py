import json
from pathlib import Path
from navigan.modules.customer_management.workflow import TRANSITIONS


def test_all_routes_documented():
    spec = json.loads((Path(__file__).resolve().parents[1] / "docs/openapi.json").read_text())
    assert sum(len(operations) for operations in spec["paths"].values()) == 18
    base = "/api/v1/customers/{customerId}/"
    for action in TRANSITIONS:
        operation = spec["paths"][base + action]["post"]
        assert any(p["name"] == "If-Match" and p.get("required") for p in operation["parameters"])
    assert spec["security"] == [{"BearerAuth": []}]
