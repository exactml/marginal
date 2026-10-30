from importlib.resources import files

import pytest

from marginal.review.prompt import load_prompt

PROMPTS = sorted(
    p.name.removesuffix(".md")
    for p in (files("marginal.review") / "prompts").iterdir()
    if p.name.endswith(".md")
)


def test_every_prompt_the_code_loads_is_shipped():
    assert PROMPTS == ["finding", "recheck"]


@pytest.mark.parametrize("name", PROMPTS)
def test_prompt_loads_from_the_installed_package(name):
    text = load_prompt(name)

    assert text.strip()
    assert not text.endswith("\n")
