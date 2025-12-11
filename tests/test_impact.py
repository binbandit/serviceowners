from serviceowners.impact import compute_impact
from serviceowners.ownership import OwnershipIndex
from serviceowners.serviceowners_file import parse_serviceowners_text


def test_compute_impact_groups_by_service_and_unmapped():
    rules = parse_serviceowners_text(
        """

        apps/api/** api
        apps/web/** web
        """
    )
    idx = OwnershipIndex(rules)
    report = compute_impact(idx, ["apps/api/a.py", "apps/web/b.ts", "README.md"])
    assert set(report.services_to_files.keys()) == {"api", "web"}
    assert report.unmapped_files == ["README.md"]
