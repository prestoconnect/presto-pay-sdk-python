from importlib.metadata import version

import presto_pay


def test_version_matches_package_metadata() -> None:
    assert presto_pay.__version__ == version("presto-pay-sdk")
