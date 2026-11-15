import importlib

import pytest

PACKAGES = [
    "marginal",
    "marginal.config",
    "marginal.providers",
    "marginal.context",
    "marginal.graph",
    "marginal.policy",
    "marginal.review",
    "marginal.github",
    "marginal.cli",
    "marginal.oic.domain.schema",
    "marginal.oic.domain.status",
]


@pytest.mark.parametrize("package", PACKAGES)
def test_package_imports(package):
    importlib.import_module(package)
