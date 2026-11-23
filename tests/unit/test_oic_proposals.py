from marginal.oic.domain.schema import Relation
from marginal.oic.services.proposals import (
    PROPOSAL_MARKER,
    ProposedClaim,
    decisions_from_replies,
    extract_claims,
    knowledge_claims,
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
        ("widgets", Relation.DEPENDS_ON, "pandas>=2"),
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
        ("widgets", Relation.DEPENDS_ON, "sqlalchemy>=2"),
        ("widgets", Relation.INSTALLS, "alembic@1.13"),
        ("widgets", Relation.DEPENDS_ON, "requests>=2"),
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
    assert _triples(with_text) == [("widgets", Relation.DEPENDS_ON, "sqlalchemy>=2")]


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


def test_replies_that_explain_a_choice_become_decisions():
    replies = [
        ("shop/stock.py", 12, "Intentional: zero-stock items stay listed. They ship.", "ann"),
        ("shop/stock.py", 30, "Good catch, fixed in abc123.", "ann"),
        ("shop/stock.py", 40, "Fixed, because the old check was wrong. Not expected.", "ann"),
        ("shop/pricing.py", None, "We chose to round down: finance reconciles to the cent.", "bo"),
    ]

    claims = decisions_from_replies(replies)

    assert _triples(claims) == [
        (
            "decision: Intentional: zero-stock items stay listed.",
            Relation.DECISION_ABOUT,
            "shop/stock.py",
        ),
        (
            "decision: We chose to round down: finance reconciles to the cent.",
            Relation.DECISION_ABOUT,
            "shop/pricing.py",
        ),
    ]
    assert [c.source for c in claims] == ["shop/stock.py:12", "shop/pricing.py"]
    assert [c.author for c in claims] == ["ann", "bo"]


def test_review_knowledge_is_kept_only_while_its_quote_is_in_the_merged_diff():
    files = [_file("shop/pricing.py", "@@ -1,1 +1,2 @@\n x = 1\n+if total >= 100:\n")]
    pricing, refund = "shop/pricing.py", "shop/refund.py"
    knowledge = [
        ("rule", "Orders of 100 or more ship free.", pricing, pricing, 2, "if  total >= 100:"),
        ("decision", "Refunds take 3 days.", refund, refund, 9, "DAYS = 3"),
        ("opinion", "Looks fine.", pricing, pricing, 1, "x = 1"),
    ]

    claims = knowledge_claims(knowledge, files)

    assert _triples(claims) == [
        ("rule: Orders of 100 or more ship free.", Relation.CONSTRAINS, "shop/pricing.py")
    ]
    assert claims[0].source == "shop/pricing.py:2"


def test_review_knowledge_about_something_not_a_path_points_at_its_evidence_file():
    files = [_file("shop/pricing.py", "@@ -1,1 +1,2 @@\n x = 1\n+if total >= 100:\n")]
    knowledge = [("rule", "Free shipping.", "pricing logic", "shop/pricing.py", 2, "total >= 100")]

    assert _triples(knowledge_claims(knowledge, files)) == [
        ("rule: Free shipping.", Relation.CONSTRAINS, "shop/pricing.py")
    ]


def test_a_raised_floor_is_a_new_claim_with_its_comment_as_the_reason():
    # Found on a real PR: only the floor moved, and the comment says why.
    patch = (
        "@@ -1,5 +1,5 @@\n"
        " [project]\n"
        ' name = "lib"\n'
        " dependencies = [\n"
        '-    "core>=3.0.0,<4.0.0", # >=3.0.0: new runner\n'
        '+    "core>=3.0.4,<4.0.0", # >=3.0.4: io control works again\n'
        " ]\n"
    )

    claims = extract_claims("widgets", [_file("pyproject.toml", patch)])

    assert _triples(claims) == [("lib", Relation.DEPENDS_ON, "core>=3.0.4,<4.0.0")]
    assert claims[0].reason == ">=3.0.4: io control works again"


def test_url_and_vcs_dependencies_name_their_package_or_nothing():
    requirements = (
        "@@ -0,0 +1,4 @@\n"
        "+git+https://github.com/acme/lib.git#egg=lib\n"
        "+https://example.com/pkg-1.0.whl\n"
        "+git+ssh://git@github.com/acme/lib.git\n"
        "+tool @ https://example.com/tool-2.0.whl\n"
    )
    pyproject = (
        "@@ -1,3 +1,4 @@\n"
        " [project]\n"
        ' name = "lib"\n'
        " dependencies = [\n"
        '+    "pkg @ git+https://host/repo.git#subdirectory=pkg", # vendored fork\n'
    )

    claims = extract_claims(
        "widgets", [_file("requirements.txt", requirements), _file("pyproject.toml", pyproject)]
    )

    assert _triples(claims) == [
        ("widgets", Relation.DEPENDS_ON, "tool"),
        ("lib", Relation.DEPENDS_ON, "pkg"),
    ]
    assert claims[1].reason == "vendored fork"


def test_a_reason_cannot_ping_or_render_markdown():
    reason = "needed by @acme/payments <b> | `x`"
    claim = ProposedClaim("lib", Relation.DEPENDS_ON, "pkg>=1", "pyproject.toml:4", reason)

    assert "`needed by @acme/payments <b> \\| 'x'`" in render_proposal([claim], "merged")


def test_single_quoted_toml_dependencies_are_read_whole():
    patch = (
        "@@ -1,3 +1,5 @@\n"
        " [project]\n"
        ' name = "lib"\n'
        " dependencies = [\n"
        "+    'pkg @ git+https://host/repo.git#subdirectory=pkg', # vendored fork\n"
        "+    'core>=2', # it's pinned low on purpose\n"
    )

    claims = extract_claims("widgets", [_file("pyproject.toml", patch)])

    assert _triples(claims) == [
        ("lib", Relation.DEPENDS_ON, "pkg"),
        ("lib", Relation.DEPENDS_ON, "core>=2"),
    ]
    assert [c.reason for c in claims] == ["vendored fork", "it's pinned low on purpose"]


def test_url_dependency_with_extras_and_single_quoted_project_name():
    patch = (
        "@@ -1,3 +1,4 @@\n"
        " [project]\n"
        " name = 'lib'\n"
        " dependencies = [\n"
        '+    "pkg[socks] @ https://example.com/pkg-1.0.whl",\n'
    )

    claims = extract_claims("widgets", [_file("pyproject.toml", patch)])

    assert _triples(claims) == [("lib", Relation.DEPENDS_ON, "pkg")]


def test_empty_strings_in_a_dependency_array_do_not_pair_the_wrong_quotes():
    patch = (
        "@@ -1,2 +1,3 @@\n"
        " [project.optional-dependencies]\n"
        " x = []\n"
        "+dev = [\"\", \"ruff>=0.6\", '', 'pytest>=8']\n"
    )

    claims = extract_claims("widgets", [_file("pyproject.toml", patch)])

    assert _triples(claims) == [
        ("widgets", Relation.DEPENDS_ON, "ruff>=0.6"),
        ("widgets", Relation.DEPENDS_ON, "pytest>=8"),
    ]
