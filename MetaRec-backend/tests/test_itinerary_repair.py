import pytest

from langgraph_metarec.itinerary_repair import parse_repair_directive

pytestmark = pytest.mark.backend_unit


def test_repair_directive_accepts_search_only_allowlist():
    directive = parse_repair_directive({
        "domain_queries": {"attraction": "museums and landmarks in Sentosa"},
        "required_roles": ["experience"],
        "excluded_types": ["lodging", "food"],
        "provider_hints": {"attraction": ["tourist attraction", "museum"]},
    })
    assert directive is not None
    assert directive.domain_queries == {"attraction": "museums and landmarks in Sentosa"}
    assert directive.required_roles == ("experience",)


@pytest.mark.parametrize("field", ["location", "date", "budget", "anchors", "style", "pace"])
def test_repair_directive_rejects_hard_constraint_injection(field):
    assert parse_repair_directive({
        "domain_queries": {"attraction": "museums"},
        field: "changed",
    }) is None


def test_repair_directive_rejects_unknown_domains_and_invented_roles():
    assert parse_repair_directive({"domain_queries": {"hotel": "new hotel"}}) is None
    assert parse_repair_directive({
        "domain_queries": {"attraction": "museums"},
        "required_roles": ["lodging"],
    }) is None
