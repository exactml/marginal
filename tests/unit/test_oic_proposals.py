from marginal.oic.domain.schema import Relation
from marginal.oic.services.proposals import (
    PROPOSAL_MARKER,
    ProposedClaim,
    extract_claims,
    render_proposal,
)


def _file(filename, patch=""):
    return {"filename": filename, "patch": patch}


def _triples(claims):
    return [(c.subject, c.relation, c.object) for c in claims]


def test_a_plain_code_change_proposes_nothing():
    patch = "@@ -1,1 +1,2 @@\n import os\n+print(os.getcwd())\n"

    assert extract_claims("widgets", [_file("app/a.py", patch), _file("README.md")]) == []


def test_added_codeowners_lines_give_one_owner_claim_per_owner():
    patch = (
        "@@ -1,1 +1,3 @@\n"
        " # owners\n"
        "+/billing/ @acme/payments @acme/platform\n"
        "+/docs/ @alice # docs\n"
    )

    claims = extract_claims("widgets", [_file(".github/CODEOWNERS", patch)])

    owners = [c for c in claims if c.relation is Relation.OWNED_BY]
    assert _triples(owners) == [
        ("/billing/", Relation.OWNED_BY, "@acme/payments"),
        ("/billing/", Relation.OWNED_BY, "@acme/platform"),
        ("/docs/", Relation.OWNED_BY, "@alice"),
    ]
    assert owners[0].source == ".github/CODEOWNERS:2"


def test_requirements_pins_are_installs_and_ranges_are_depends_on():
    patch = (
        "@@ -1,1 +1,4 @@\n"
        " flask\n"
        "+requests==2.31.0\n"
        "+pandas>=2 ; python_version>'3.9'\n"
        "+-r base.txt\n"
    )

    claims = extract_claims("widgets", [_file("requirements-dev.txt", patch)])

    assert _triples(claims) == [
        ("widgets", Relation.INSTALLS, "requests@2.31.0"),
        ("widgets", Relation.DEPENDS_ON, "pandas"),
    ]


def test_pyproject_version_bump_is_a_release_of_the_named_project():
    patch = (
        "@@ -1,3 +1,3 @@\n"
        " [project]\n"
        ' name = "widgets-lib"\n'
        '-version = "1.0.0"\n'
        '+version = "1.1.0"\n'
    )

    claims = extract_claims("widgets", [_file("pyproject.toml", patch)])

    assert _triples(claims) == [("widgets-lib@1.1.0", Relation.RELEASE_OF, "widgets-lib")]


def test_pyproject_reads_only_dependency_arrays():
    patch = (
        "@@ -10,4 +10,9 @@\n"
        " [project.optional-dependencies]\n"
        '+oic = ["sqlalchemy>=2", "alembic[tz]==1.13"]\n'
        " [tool.pytest.ini_options]\n"
        '+testpaths = ["tests"]\n'
        " [tool.towncrier]\n"
        '+name = "Fixes"\n'
        " [project]\n"
        " dependencies = [\n"
        '+  "requests>=2",\n'
    )

    claims = extract_claims("widgets", [_file("pyproject.toml", patch)])

    assert _triples(claims) == [
        ("widgets", Relation.DEPENDS_ON, "sqlalchemy"),
        ("widgets", Relation.INSTALLS, "alembic@1.13"),
        ("widgets", Relation.DEPENDS_ON, "requests"),
    ]


def test_claim_id_is_stable_and_depends_only_on_the_triple():
    a = ProposedClaim("x", Relation.DEPENDS_ON, "y", "a.txt:1")
    b = ProposedClaim("x", Relation.DEPENDS_ON, "y", "b.txt:9")

    assert a.id == b.id
    assert a.id != ProposedClaim("x", Relation.INSTALLS, "y").id


def test_render_says_what_state_the_pr_is_in():
    claim = ProposedClaim("widgets", Relation.DEPENDS_ON, "requests", "pyproject.toml:4")

    merged = render_proposal([claim], "merged")

    assert merged.startswith(PROPOSAL_MARKER)
    assert "Proposed for the knowledge graph" in merged and claim.id in merged
    assert "candidates" in merged
    assert "will propose" in render_proposal([claim], "open")
    assert "nothing is proposed" in render_proposal([claim], "closed")
    assert "No knowledge found" in render_proposal([], "merged")


def test_pyproject_tables_above_the_hunk_are_read_from_the_full_text():
    # Hunk starts below `[project.optional-dependencies]`, as in most dependency PRs.
    patch = (
        "@@ -2,1 +2,3 @@\n"
        ' ollama = ["openai>=1.40"]\n'
        '+oic = ["sqlalchemy>=2"]\n'
        '+testpaths = ["tests"]\n'
    )
    text = (
        "[project.optional-dependencies]\n"
        'ollama = ["openai>=1.40"]\n'
        'oic = ["sqlalchemy>=2"]\n'
        "[tool.pytest.ini_options]\n"
        'testpaths = ["tests"]\n'
    )

    without = extract_claims("widgets", [_file("pyproject.toml", patch)])
    with_text = extract_claims(
        "widgets", [_file("pyproject.toml", patch)], {"pyproject.toml": text}
    )

    assert _triples(without) == []
    assert _triples(with_text) == [("widgets", Relation.DEPENDS_ON, "sqlalchemy")]


def test_render_keeps_table_cells_intact():
    odd = ProposedClaim("a|b", Relation.OWNED_BY, "x`y")

    text = render_proposal([odd], "merged")

    assert "`a\\|b`" in text and "`x'y`" in text


def test_an_edited_line_proposes_only_what_it_adds():
    # Found on a real PR: a one-line array rewritten to add one dependency.
    patch = (
        "@@ -1,3 +1,3 @@\n"
        " [project]\n"
        ' name = "shop"\n'
        '-dependencies = ["pydantic>=2"]\n'
        '+dependencies = ["pydantic>=2", "requests==2.32.3"]\n'
    )
    owners = "@@ -1,1 +1,1 @@\n-/shop/ @alice\n+/shop/ @alice @bob\n"

    claims = extract_claims(
        "widgets", [_file("pyproject.toml", patch), _file("CODEOWNERS", owners)]
    )

    assert _triples(claims) == [
        ("shop", Relation.INSTALLS, "requests@2.32.3"),
        ("/shop/", Relation.OWNED_BY, "@bob"),
    ]
