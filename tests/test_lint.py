from serviceowners.lint import lint_rules
from serviceowners.serviceowners_file import parse_serviceowners_text
from serviceowners.services_file import parse_services_obj


def test_lint_unknown_service_warns_when_services_present():
    rules = parse_serviceowners_text("src/** api\n")
    services = parse_services_obj({"services": {"web": {}}}, source="services.yaml")
    res = lint_rules(rules, services=services, strict=False)
    assert any(i.code == "UNKNOWN_SERVICE" for i in res.issues)


def test_lint_duplicate_pattern_warns():
    rules = parse_serviceowners_text(
        """

        src/** api
        src/** web
        """
    )
    res = lint_rules(rules, services={}, strict=False)
    assert any(i.code == "DUPLICATE_PATTERN" for i in res.issues)
