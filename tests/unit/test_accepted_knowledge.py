from marginal.context.knowledge import (
    MAX_ACCEPTED_PER_REVIEW,
    AcceptedClaim,
    matching,
    parse_accepted,
)
from marginal.review.prompt import build_finding_prompt


def _claim(about, repo="widgets", applies_to=(), id="a3f91c", **extra):
    return AcceptedClaim(
        id=id,
        repo=repo,
        applies_to=list(applies_to),
        kind="rule",
        statement="agg levels stay ordered",
        about=about,
        **extra,
    )


def test_parse_reads_every_field():
    text = """
- id: a3f91c
  repo: rocks-noob
  applies_to: [rocks-noob, customer-pipeline-*]
  kind: decision
  statement: noob runs on the ML runtime
  about: rocks/noob/cluster.py
  pr: 516
  author: some-login
"""
    [claim] = parse_accepted(text)

    assert claim.applies_to == ["rocks-noob", "customer-pipeline-*"]
    assert (claim.kind, claim.pr, claim.author) == ("decision", 516, "some-login")


def test_parse_skips_a_bad_entry_and_keeps_the_rest(capsys):
    text = """
- {id: a1, repo: w, kind: rule, statement: s, about: a.py}
- {id: a2, repo: w, kind: opinion, statement: s, about: a.py}
- {id: a3, repo: w, kind: decision, about: a.py}
- {id: 123456, repo: w, kind: rule, statement: s, about: a.py, supersedes: a1}
"""
    claims = parse_accepted(text)

    # A digits-only id still loads as text, and an unknown key is ignored.
    assert [c.id for c in claims] == ["a1", "123456"]
    err = capsys.readouterr().err
    assert "skipping entry 2" in err and "kind" in err
    assert "skipping entry 3" in err and "statement" in err


def test_parse_warns_and_loads_nothing_from_a_broken_file(capsys):
    assert parse_accepted("- [unclosed") == []
    assert parse_accepted("id: a1") == []
    assert parse_accepted("") == []

    err = capsys.readouterr().err
    assert "isn't valid YAML" in err
    assert "must be a list" in err


def test_matching_picks_the_file_its_folder_and_its_siblings():
    claims = [
        _claim("rocks/noob/helpers.py", id="same-file"),
        _claim("rocks/noob/agg.py", id="sibling"),
        _claim("rocks/", id="folder"),
        _claim("rocks/opal/", id="other-folder"),
        _claim("rocks/other.py", id="parent-folder-file"),
    ]

    picked = matching(claims, "acme/widgets", ["rocks/noob/helpers.py"])

    # A rule on helpers.py also reaches selection.py next to it: that's how a
    # rule broken in a sibling file was caught.
    assert [c.id for c in picked] == ["folder", "sibling", "same-file"]


def test_matching_keeps_only_claims_for_this_repo():
    claims = [
        _claim("a.py", repo="widgets", id="own"),
        _claim("a.py", repo="gadgets", id="other"),
        _claim("a.py", repo="core", applies_to=["wid*"], id="glob"),
        _claim("a.py", repo="widgets", applies_to=["gadgets"], id="moved-away"),
    ]

    picked = matching(claims, "acme/widgets", ["a.py"])

    assert [c.id for c in picked] == ["glob", "own"]


def test_matching_keeps_the_newest_up_to_the_cap():
    claims = [_claim("a.py", id=f"c{n}") for n in range(MAX_ACCEPTED_PER_REVIEW + 5)]

    picked = matching(claims, "widgets", ["a.py"])

    assert len(picked) == MAX_ACCEPTED_PER_REVIEW
    assert picked[0].id == f"c{MAX_ACCEPTED_PER_REVIEW + 4}"


def test_prompt_lists_accepted_claims_before_the_diff():
    files = [{"filename": "a.py", "patch": "+x = 1"}]

    prompt = build_finding_prompt(files, [], [], ".", accepted=[_claim("a.py", pr=462)])

    assert "- rule (PR #462, a.py): agg levels stay ordered" in prompt
    assert prompt.index("agg levels stay ordered") < prompt.index("+x = 1")


def test_prompt_without_accepted_claims_is_unchanged():
    files = [{"filename": "a.py", "patch": "+x = 1"}]

    assert build_finding_prompt(files, [], [], ".", accepted=[]) == build_finding_prompt(
        files, [], [], "."
    )
