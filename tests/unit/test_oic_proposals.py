from marginal.oic.domain.schema import Relation
from marginal.oic.services.proposals import (
    PROPOSAL_MARKER,
    ProposedClaim,
    extract_claims,
    render_proposal,
    requested_drops,
)


def _file(filename, patch=""):
    return {"filename": filename, "patch": patch}


def _triples(claims):
    return [(c.subject, c.relation, c.object) for c in claims]


def test_each_changed_directory_gets_one_changes_claim():
    claims = extract_claims(
        "widgets", 7, [_file("app/a.py"), _file("app/b.py"), _file("README.md")]
    )

    assert _triples(claims) == [
        ("PR #7", Relation.CHANGES, "app"),
        ("PR #7", Relation.CHANGES, "widgets"),
    ]


def test_added_codeowners_lines_give_one_owner_claim_per_owner():
    patch = (
        "@@ -1,1 +1,3 @@\n"
        " # owners\n"
        "+/billing/ @acme/payments @acme/platform\n"
        "+/docs/ @alice # docs\n"
    )

    claims = extract_claims("widgets", 7, [_file(".github/CODEOWNERS", patch)])

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

    claims = extract_claims("widgets", 7, [_file("requirements-dev.txt", patch)])

    assert _triples(claims[1:]) == [
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

    claims = extract_claims("widgets", 7, [_file("pyproject.toml", patch)])

    assert _triples(claims[1:]) == [("widgets-lib@1.1.0", Relation.RELEASE_OF, "widgets-lib")]


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

    claims = extract_claims("widgets", 7, [_file("pyproject.toml", patch)])

    assert _triples(claims[1:]) == [
        ("widgets", Relation.DEPENDS_ON, "sqlalchemy"),
        ("widgets", Relation.INSTALLS, "alembic@1.13"),
        ("widgets", Relation.DEPENDS_ON, "requests"),
    ]


def test_claim_id_is_stable_and_depends_only_on_the_triple():
    a = ProposedClaim("x", Relation.DEPENDS_ON, "y", "a.txt:1")
    b = ProposedClaim("x", Relation.DEPENDS_ON, "y", "b.txt:9")

    assert a.id == b.id
    assert a.id != ProposedClaim("x", Relation.INSTALLS, "y").id


def test_drop_commands_are_parsed_and_the_proposal_itself_is_ignored():
    comments = [
        {"user": {"login": "alice"}, "body": "/marginal drop abc123, def456"},
        {"user": {"login": "bob"}, "body": "looks fine\n/marginal drop 0a0a0a"},
        {"user": {"login": "carol"}, "body": "please /marginal drop abc123"},
        {"user": {"login": "bot"}, "body": f"{PROPOSAL_MARKER}\n/marginal drop abc123"},
    ]

    assert requested_drops(comments) == [
        ("alice", {"abc123", "def456"}),
        ("bob", {"0a0a0a"}),
    ]


def test_render_shows_dropped_claims_and_the_state():
    keep = ProposedClaim("widgets", Relation.DEPENDS_ON, "requests", "pyproject.toml:4")
    drop = ProposedClaim("/billing/", Relation.OWNED_BY, "@acme/payments")

    opened = render_proposal([keep, drop], {drop.id: "alice"}, "open")
    merged = render_proposal([keep, drop], {drop.id: "alice"}, "merged")
    closed = render_proposal([keep], {}, "closed")

    assert opened.startswith(PROPOSAL_MARKER)
    assert "This PR would record" in opened and "/marginal drop <id>" in opened
    assert f"~~`{drop.id}`" in opened and "dropped by `alice`" in opened
    assert "@alice" not in opened
    assert "accepted" in merged and "/marginal drop" not in merged
    assert "not recorded" in closed
    assert "No relations found" in render_proposal([], {}, "open")


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

    without = extract_claims("widgets", 7, [_file("pyproject.toml", patch)])
    with_text = extract_claims(
        "widgets", 7, [_file("pyproject.toml", patch)], {"pyproject.toml": text}
    )

    assert _triples(without[1:]) == []
    assert _triples(with_text[1:]) == [("widgets", Relation.DEPENDS_ON, "sqlalchemy")]
