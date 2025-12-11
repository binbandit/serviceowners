from serviceowners.ownership import OwnershipIndex
from serviceowners.serviceowners_file import parse_serviceowners_text


def test_last_match_wins():
    rules = parse_serviceowners_text(
        """

        *.py core
        src/** platform
        """
    )
    idx = OwnershipIndex(rules)
    m = idx.match("src/main.py")
    assert m.service == "platform"
    assert len(m.matches) == 2
