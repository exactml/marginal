from marginal.context.knowledge import (
    MAX_ACCEPTED_PER_REVIEW,
    MAX_REPO_WIDE_PER_REVIEW,
    AcceptedClaim,
    load_accepted,
    parse_accepted,
)
from marginal.review.prompt import build_finding_prompt

REPO = ".marginal/knowledge/repo"
PATHS = ".marginal/knowledge/paths"


class _Commit:
    """A client stand-in serving `files` (path -> text) at one commit, and
    recording which it was asked to read."""

    def __init__(self, files):
        self.files = files
        self.read = []

    def list_files(self, path, ref):
        return [f for f in self.files if f.startswith(path + "/")]

    def get_files(self, paths, ref):
        self.read += paths
        return {path: self.files[path] for path in paths if path in self.files}


def _yaml(about="", repo="widgets", pr=None, applies_to=None, kind="rule"):
    lines = [f"repo: {repo}", f"kind: {kind}", f"statement: claim {pr}"]
    lines += [f"about: {about}"] if about else []
    lines += [f"pr: {pr}"] if pr else []
    lines += [f"applies_to: {applies_to}"] if applies_to else []
    return "\n".join(lines) + "\n"


def _ids(claims):
    return [c.id for c in claims]


def test_parse_reads_every_field_and_takes_the_id_from_the_file_name():
    text = """
repo: widgets
applies_to: [widgets, widgets-*]
kind: decision
statement: checkout runs on the payments service
about: shop/cart/payments.py
pr: 516
author: some-login
supersedes: 7be210
"""
    claim = parse_accepted(f"{PATHS}/shop/cart/a3f91c.yaml", text)

    assert claim.id == "a3f91c"
    assert claim.applies_to == ["widgets", "widgets-*"]
    assert (claim.kind, claim.pr, claim.author) == ("decision", 516, "some-login")


def test_parse_skips_a_bad_file_with_a_warning(capsys):
    assert parse_accepted(f"{REPO}/a.yaml", "kind: [unclosed") is None
    assert parse_accepted(f"{REPO}/b.yaml", "- a list") is None
    assert parse_accepted(f"{REPO}/c.yaml", "repo: w\nkind: opinion\nstatement: s\n") is None
    assert parse_accepted(f"{PATHS}/d.yaml", "repo: w\nkind: rule\nstatement: s\n") is None
    # A repo-wide claim needs no `about`.
    assert parse_accepted(f"{REPO}/e.yaml", "repo: w\nkind: rule\nstatement: s\n")

    err = capsys.readouterr().err
    assert f"skipping {REPO}/a.yaml: not valid YAML" in err
    assert f"skipping {REPO}/b.yaml: it must hold one claim's fields" in err
    assert f"skipping {REPO}/c.yaml: bad or missing kind" in err
    assert f"skipping {PATHS}/d.yaml: a claim under" in err


def test_load_matches_the_file_its_folder_and_its_siblings_and_reads_no_other_area():
    commit = _Commit(
        {
            f"{PATHS}/shop/cart/same.yaml": _yaml("shop/cart/helpers.py", pr=1),
            f"{PATHS}/shop/cart/sibling.yaml": _yaml("shop/cart/agg.py", pr=2),
            f"{PATHS}/shop/folder.yaml": _yaml("shop/", pr=3),
            f"{PATHS}/shop/parent-file.yaml": _yaml("shop/other.py", pr=4),
            f"{PATHS}/billing/elsewhere.yaml": _yaml("billing/invoice.py", pr=5),
            f"{PATHS}/shop/cart/notes.md": "not a claim",
        }
    )

    claims = load_accepted(commit, "abc", "acme/widgets", ["shop/cart/helpers.py"])

    # A rule on helpers.py also reaches a change next to it: that's how a rule
    # broken in a sibling file was caught.
    assert _ids(claims) == ["folder", "sibling", "same"]
    assert f"{PATHS}/billing/elsewhere.yaml" not in commit.read
    assert f"{PATHS}/shop/cart/notes.md" not in commit.read


def test_load_reads_about_as_written_by_hand():
    commit = _Commit(
        {
            f"{PATHS}/shop/dotted.yaml": _yaml("./shop/pricing.py", pr=4),
            f"{PATHS}/shop/rooted.yaml": _yaml("/shop/pricing.py", pr=3),
            # Its own folder, without the trailing `/`: still a folder claim.
            f"{PATHS}/shop/folder.yaml": _yaml("shop", pr=2),
            f"{PATHS}/setup.yaml": _yaml("setup.py", pr=1),
        }
    )

    assert _ids(load_accepted(commit, "abc", "widgets", ["shop/deep/cart.py"])) == ["folder"]
    assert _ids(load_accepted(commit, "abc", "widgets", ["shop/tax.py"])) == [
        "dotted",
        "rooted",
        "folder",
    ]
    # At the root a file has no siblings: every top-level file would be one.
    assert _ids(load_accepted(commit, "abc", "widgets", ["README.md"])) == []
    assert _ids(load_accepted(commit, "abc", "widgets", ["setup.py"])) == ["setup"]


def test_load_puts_repo_wide_claims_first_on_every_review():
    commit = _Commit(
        {
            f"{REPO}/everywhere.yaml": _yaml(pr=1),
            f"{PATHS}/a.yaml": _yaml("a.py", pr=9),
        }
    )

    assert _ids(load_accepted(commit, "abc", "widgets", ["a.py"])) == ["everywhere", "a"]
    assert _ids(load_accepted(commit, "abc", "widgets", ["deep/b.py"])) == ["everywhere"]


def test_load_keeps_only_claims_for_this_repo():
    commit = _Commit(
        {
            f"{REPO}/own.yaml": _yaml(repo="widgets", pr=4),
            # Decided elsewhere, but its file is here and it names no repos.
            f"{REPO}/copied.yaml": _yaml(repo="gadgets", pr=3),
            f"{REPO}/glob.yaml": _yaml(repo="core", applies_to='["widg?ts"]', pr=2),
            f"{REPO}/moved.yaml": _yaml(repo="widgets", applies_to="[gadgets]", pr=1),
        }
    )

    assert _ids(load_accepted(commit, "abc", "acme/widgets", ["a.py"])) == [
        "own",
        "copied",
        "glob",
    ]
    # A local review names the repo after its folder, which may differ.
    assert _ids(load_accepted(commit, "abc", "widgets-clone", ["a.py"])) == ["own", "copied"]


def test_load_caps_repo_wide_claims_and_warns(capsys):
    commit = _Commit({f"{REPO}/c{n}.yaml": _yaml(pr=n) for n in range(1, 9)})

    claims = load_accepted(commit, "abc", "widgets", ["a.py"])

    assert _ids(claims) == ["c8", "c7", "c6", "c5", "c4"][:MAX_REPO_WIDE_PER_REVIEW]
    assert "8 repo-wide claims" in capsys.readouterr().err


def test_load_fills_the_rest_of_the_cap_with_the_newest_area_claims():
    files = {f"{REPO}/r{n}.yaml": _yaml(pr=n) for n in range(1, 3)}
    files |= {f"{PATHS}/p{n}.yaml": _yaml("a.py", pr=100 + n) for n in range(1, 21)}

    claims = load_accepted(_Commit(files), "abc", "widgets", ["a.py"])

    assert len(claims) == MAX_ACCEPTED_PER_REVIEW
    assert _ids(claims)[:3] == ["r2", "r1", "p20"]


def test_load_without_the_folder_reads_nothing():
    commit = _Commit({})

    assert load_accepted(commit, "abc", "widgets", ["a.py"]) == []
    assert commit.read == []


def _claim(about, pr=None):
    return AcceptedClaim(
        id="a3f91c", repo="w", kind="rule", statement="levels stay ordered", about=about, pr=pr
    )


def test_prompt_lists_accepted_claims_before_the_diff():
    files = [{"filename": "a.py", "patch": "+x = 1"}]

    prompt = build_finding_prompt(files, [], [], ".", accepted=[_claim("a.py", pr=462)])

    assert "- rule (PR #462, a.py): levels stay ordered" in prompt
    assert prompt.index("levels stay ordered") < prompt.index("+x = 1")


def test_prompt_names_a_repo_wide_claim_as_such():
    files = [{"filename": "a.py", "patch": "+x = 1"}]

    prompt = build_finding_prompt(files, [], [], ".", accepted=[_claim("")])

    assert "- rule (repo-wide): levels stay ordered" in prompt


def test_prompt_redacts_a_secret_in_a_statement():
    files = [{"filename": "a.py", "patch": "+x = 1"}]
    claim = _claim("a.py").model_copy(update={"statement": "use key AKIAIOSFODNN7EXAMPLE"})

    prompt = build_finding_prompt(files, [], [], ".", accepted=[claim])

    assert "AKIAIOSFODNN7EXAMPLE" not in prompt
    assert "use key [REDACTED" in prompt


def test_prompt_cuts_a_long_statement():
    files = [{"filename": "a.py", "patch": "+x = 1"}]
    claim = _claim("a.py").model_copy(update={"statement": "word " * 200})

    prompt = build_finding_prompt(files, [], [], ".", accepted=[claim])

    assert "word " * 60 in prompt
    assert "word " * 61 not in prompt


def test_prompt_without_accepted_claims_is_unchanged():
    files = [{"filename": "a.py", "patch": "+x = 1"}]

    assert build_finding_prompt(files, [], [], ".", accepted=[]) == build_finding_prompt(
        files, [], [], "."
    )
