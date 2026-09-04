import importlib

import pytest

PACKAGES = [
    "marginal",
    "marginal.config",
    "marginal.providers",
    "marginal.context",
    "marginal.graph",
    "marginal.policy",
    "marginal.agent",
    "marginal.review",
    "marginal.github",
    "marginal.cli",
]


@pytest.mark.parametrize("package", PACKAGES)
def test_package_imports(package):
    importlib.import_module(package)
