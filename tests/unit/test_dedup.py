from marginal.review.dedup import (
    current_fingerprints,
    finding_fingerprint,
    fingerprint_marker,
    nearby_fingerprints,
    posted_fingerprints,
)

PATCH = (
    "@@ -10,3 +10,4 @@ def retry():\n"
    "     attempts = 0\n"
    "-    time.sleep(0)\n"
    "+    time.sleep(1)\n"
    "     return attempts\n"
)


def fp(line, patch=PATCH, severity="high", message="x", file="retry.py"):
    return finding_fingerprint(file, line, severity, message, patch)


def nearby(line, patch=PATCH, severity="high", message="x", file="retry.py"):
    return nearby_fingerprints(file, line, severity, message, patch)


def test_same_line_text_matches_despite_reworded_message():
    assert fp(11, message="Blocking sleep in async loop.") == fp(
        11, message="time.sleep blocks the event loop here"
    )


def test_same_line_text_matches_after_the_line_shifts():
    assert fp(11) == fp(15, patch=PATCH.replace("+10,4", "+14,4"))


def test_same_line_text_matches_when_the_hunk_around_it_changes():
    # A later push widens the hunk: new lines above and below, a different
    # header -- the flagged line itself is untouched.
    wider = (
        "@@ -6,6 +6,9 @@ def retry():\n"
        "+    log = logger()\n"
        "+    log.info('start')\n"
        "     attempts = 0\n"
        "-    time.sleep(0)\n"
        "+    time.sleep(1)\n"
        "+    log.info('slept')\n"
        "     return attempts\n"
    )

    assert fp(11) == fp(9, patch=wider)


def test_different_line_text_differs():
    changed = PATCH.replace("+    time.sleep(1)", "+    await asyncio.sleep(1)")

    assert fp(11) != fp(11, patch=changed)


def test_line_text_ignores_whitespace_changes():
    assert fp(11) == fp(11, patch=PATCH.replace("+    time.sleep(1)", "+\t\ttime.sleep(1)  "))


def test_different_file_or_severity_differs():
    assert fp(11) != fp(11, file="other.py")
    assert fp(11) != fp(11, severity="medium")


def test_line_outside_the_patch_falls_back_to_its_number():
    assert fp(99) == fp(99, patch=None, message="something else")
    assert fp(99) != fp(98)


def test_unanchored_finding_uses_normalized_message():
    assert fp(None, message="Add  a Backoff cap.") == fp(None, message="add a backoff\ncap.")
    assert fp(None, message="Add a backoff cap.") != fp(None, message="Add a retry limit.")


def test_secret_on_the_line_does_not_leak_into_the_hash():
    def with_key(key):
        return f"@@ -1 +1 @@\n+api_key = '{key}'\n"

    # Both lines redact to the same text, so the hash can't depend on the secret.
    assert fp(1, patch=with_key("AKIAIOSFODNN7EXAMPLE")) == fp(
        1, patch=with_key("AKIAZZZZZZZZZZZZZZZZ")
    )


def test_nearby_matches_an_anchor_that_drifted_by_one_line():
    # Run 1 pinned the issue to line 10 ("attempts = 0"); run 2 to its own line, 11.
    assert fp(10) in nearby(11)


def test_nearby_ignores_a_same_severity_finding_two_lines_away():
    assert fp(10) not in nearby(12)


def test_nearby_ignores_a_different_severity_on_the_next_line():
    assert fp(10) not in nearby(11, severity="medium")


def test_nearby_treats_a_same_severity_neighbour_as_a_repeat():
    # The accepted trade-off of tolerating anchor drift.
    assert fp(11, message="one issue") in nearby(12, message="a different issue")


def test_nearby_for_an_unanchored_finding_is_just_its_own_fingerprint():
    assert nearby(None, message="Add a cap.") == {fp(None, message="Add a cap.")}


def test_posted_fingerprints_reads_markers_from_bodies():
    bodies = [
        f"🟠 **High**\n\nissue\n\n{fingerprint_marker('0123456789abcdef')}",
        None,
        "a human reply with no marker",
        f"summary\n{fingerprint_marker('fedcba9876543210')}",
    ]

    assert posted_fingerprints(bodies) == {"0123456789abcdef", "fedcba9876543210"}


BADGE_EMOJI = {"Critical": "🔴", "High": "🟠", "Medium": "🟡", "Low": "⚪"}


def comment(path, line, severity="High", fingerprint=None, marker=True):
    body = f"{BADGE_EMOJI[severity]} **{severity}** · 90% confidence\n\nissue"
    if marker:
        body += f"\n\n{fingerprint_marker(fingerprint or fp(11))}"
    return {
        "body": body,
        "path": path,
        "line": line,
    }


def test_current_fingerprints_follow_a_file_renamed_since_posting():
    # Posted on retry.py; GitHub now shows the comment on the renamed file.
    patches = {"backoff.py": PATCH}

    posted = current_fingerprints([comment("backoff.py", 11)], patches)

    assert nearby(11, file="backoff.py") & posted


def test_current_fingerprints_match_the_stored_hash_when_nothing_moved():
    patches = {"retry.py": PATCH}

    posted = current_fingerprints([comment("retry.py", 11)], patches)

    assert posted == {fp(11)}
    assert not nearby(13, severity="medium") & posted


def test_current_fingerprints_skip_outdated_unlisted_and_foreign_comments():
    patches = {"retry.py": PATCH}
    comments = [
        comment("retry.py", None),
        comment("gone.py", 11),
        {"body": "a human reply", "path": "retry.py", "line": 11},
        {"body": None, "path": "retry.py", "line": 11},
        {"path": "retry.py"},
    ]

    assert current_fingerprints(comments, patches) == set()


def test_current_fingerprints_cover_every_line_of_a_multi_line_comment():
    # GitHub reports a multi-line comment's last line; the finding was on 11.
    patches = {"backoff.py": PATCH}

    posted = current_fingerprints([comment("backoff.py", 13) | {"start_line": 11}], patches)

    assert nearby(11, file="backoff.py") & posted


def test_current_fingerprints_keep_a_different_finding_on_the_renamed_file_new():
    patches = {"backoff.py": PATCH}

    posted = current_fingerprints([comment("backoff.py", 11)], patches)

    assert not nearby(11, file="backoff.py", severity="low") & posted
    assert not nearby(11, file="backoff.py", patch=PATCH.replace("sleep(1)", "sleep(5)")) & posted


def test_current_fingerprints_take_the_severity_from_a_low_badge():
    patches = {"backoff.py": PATCH}

    posted = current_fingerprints([comment("backoff.py", 11, severity="Low")], patches)

    assert nearby(11, file="backoff.py", severity="low") & posted
    assert not nearby(11, file="backoff.py", severity="high") & posted


def test_current_fingerprints_take_the_severity_from_a_medium_badge():
    patches = {"backoff.py": PATCH}

    posted = current_fingerprints([comment("backoff.py", 11, severity="Medium")], patches)

    assert nearby(11, file="backoff.py", severity="medium") & posted
    assert not nearby(11, file="backoff.py", severity="high") & posted


def test_current_fingerprints_ignore_a_badge_without_a_marginal_marker():
    # Another bot, or a person quoting marginal's badge format.
    patches = {"backoff.py": PATCH}

    posted = current_fingerprints([comment("backoff.py", 11, marker=False)], patches)

    assert posted == set()


def test_current_fingerprints_read_the_badge_without_a_confidence():
    # Findings no longer carry a confidence, so the badge is severity only.
    patches = {"backoff.py": PATCH}
    body = f"🟠 **High**\n\nissue\n\n{fingerprint_marker(fp(11))}"

    posted = current_fingerprints([{"body": body, "path": "backoff.py", "line": 11}], patches)

    assert nearby(11, file="backoff.py") & posted
