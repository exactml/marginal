import pytest

from marginal.review import Evidence, Finding, Severity
from marginal.review.evidence import CodeView, check, decide

# The diff shows lines 10-12 of the new pk.py.
PATCH = (
    "@@ -10,2 +10,3 @@\n"
    " def _is_pk_set(self, meta=None):\n"
    "-    return pk is not None\n"
    "+    value = self._get_pk_val(meta)\n"
    "+    return not (value is None or isinstance(value, DatabaseDefault))\n"
)
FILES = [{"filename": "pk.py", "patch": PATCH}]


def _view(tmp_path, files=FILES, context=""):
    return CodeView(str(tmp_path), files, context)


def _finding(evidence, trigger="saving through `_is_pk_set`", severity=Severity.HIGH):
    return Finding(
        file="pk.py",
        line=12,
        severity=severity,
        message="A DatabaseDefault pk now reads as unset.",
        trigger=trigger,
        evidence=[Evidence(file=f, line=n, quote=q) for f, n, q in evidence],
    )


QUOTE = "return not (value is None or isinstance(value, DatabaseDefault))"


def test_a_quote_is_found_at_its_line_in_the_diff(tmp_path):
    assert _view(tmp_path).has_quote("pk.py", 12, QUOTE)


@pytest.mark.parametrize("line", [10, 14])
def test_a_quote_two_lines_off_is_still_found(tmp_path, line):
    assert _view(tmp_path).has_quote("pk.py", line, QUOTE)


def test_a_quote_three_lines_off_is_not_found(tmp_path):
    assert not _view(tmp_path).has_quote("pk.py", 15, QUOTE)


def test_a_quote_ignores_surrounding_whitespace_and_may_be_part_of_the_line(tmp_path):
    view = _view(tmp_path)

    assert view.has_quote(
        "pk.py", 12, "   return not (value is None  or isinstance(value, DatabaseDefault))"
    )
    assert view.has_quote("pk.py", 12, "isinstance(value, DatabaseDefault)")
    # Too short to prove anything on its own.
    assert not view.has_quote("pk.py", 12, "value")


def test_invented_code_is_not_found(tmp_path):
    assert not _view(tmp_path).has_quote("pk.py", 12, "return self.pk_is_set_cache[meta]")


def test_a_line_the_diff_doesnt_show_is_read_from_the_checkout(tmp_path):
    (tmp_path / "base.py").write_text("\n" * 96 + "        if not self._is_pk_set(meta):\n")

    assert _view(tmp_path).has_quote("base.py", 97, "if not self._is_pk_set(meta):")


def test_a_quote_never_reads_outside_the_checkout(tmp_path):
    outside = tmp_path.parent / "secret.py"
    outside.write_text("token = 'x'\n")
    repo = tmp_path / "repo"
    repo.mkdir()

    assert not CodeView(str(repo), []).has_quote("../secret.py", 1, "token = 'x'")


def test_a_trigger_is_concrete_when_it_names_code_the_model_was_shown(tmp_path):
    view = _view(tmp_path, context="`Model._save_table` is called from: base.py:1097")

    assert view.names_code("`Model.save()` reaches `_save_table()`", [])
    assert view.names_code("calling _get_pk_val with a db default", [])
    assert not view.names_code("whenever someone saves something", [])
    assert not view.names_code("calling `frobnicate_widget()`", [])


def test_a_trigger_may_name_code_from_a_verified_quote(tmp_path):
    assert _view(tmp_path, files=[]).names_code(
        "via `get_pk_value_on_save`", ["pk_val = meta.pk.get_pk_value_on_save(self)"]
    )


def test_check_counts_verified_quotes_and_whether_a_caller_was_shown(tmp_path):
    (tmp_path / "base.py").write_text("\n" * 96 + "        if not self._is_pk_set(meta):\n")
    finding = _finding(
        [
            ("pk.py", 12, QUOTE),
            ("base.py", 97, "if not self._is_pk_set(meta):"),
            ("pk.py", 12, "nope()"),
        ]
    )

    checks = check(finding, _view(tmp_path))

    assert checks.quotes == (True, True, False)
    assert (checks.quotes_verified, checks.quotes_not_found) == (2, 1)
    assert checks.trigger_concrete
    # base.py:97 is outside the diff: the model quoted a caller.
    assert checks.caller_shown


def test_only_the_first_three_quotes_count(tmp_path):
    finding = _finding([("pk.py", 12, "nope()")] * 3 + [("pk.py", 12, QUOTE)])

    assert check(finding, _view(tmp_path)).quotes == (False, False, False)


@pytest.mark.parametrize(
    ("evidence", "trigger", "reason"),
    [
        ([], "saving through `_is_pk_set`", "no quoted evidence"),
        (
            [("pk.py", 12, "return self.cache[meta]")],
            "saving through `_is_pk_set`",
            "quoted line not found",
        ),
        ([("pk.py", 12, QUOTE)], "whenever someone saves", "no concrete trigger"),
    ],
)
def test_decide_drops_a_finding_and_says_why(tmp_path, evidence, trigger, reason):
    [decision] = decide([_finding(evidence, trigger)], _view(tmp_path), max_comments=8)

    assert not decision.posted
    assert decision.reason == reason


def test_decide_posts_a_finding_with_a_verified_quote_and_a_concrete_trigger(tmp_path):
    finding = _finding([("pk.py", 12, QUOTE)])

    [decision] = decide([finding], _view(tmp_path), max_comments=8)

    assert decision.posted
    assert decision.reason == "1 verified quote, concrete trigger"
    assert finding.checks.quotes == (True,)


def test_decide_ranks_by_severity_then_verified_quotes_and_caps(tmp_path):
    low = _finding([("pk.py", 12, QUOTE)], severity=Severity.LOW)
    high_one = _finding([("pk.py", 12, QUOTE)], severity=Severity.HIGH)
    high_two = _finding([("pk.py", 12, QUOTE), ("pk.py", 11, "value = self._get_pk_val(meta)")])
    dropped = _finding([], severity=Severity.CRITICAL)

    decisions = decide([low, high_one, dropped, high_two], _view(tmp_path), max_comments=2)

    assert [(d.finding, d.posted) for d in decisions] == [
        (high_two, True),
        (high_one, True),
        (dropped, False),
        (low, False),
    ]
    assert decisions[-1].reason == "over review.max_comments"
