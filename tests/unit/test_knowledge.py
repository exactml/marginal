from marginal.review import Evidence
from marginal.review.knowledge import knowledge_marker, posted_knowledge
from marginal.review.schema import Knowledge

RULE = Knowledge(
    kind="rule",
    statement="Totals over 100 --> ship free.",
    about="shop/pricing.py",
    evidence=Evidence(file="shop/pricing.py", line=4, quote="if total >= 100:"),
)


def test_knowledge_survives_the_round_trip_through_a_review_body():
    body = f"### 🤖 marginal review\n\n{knowledge_marker([RULE])}"

    assert "-->" not in knowledge_marker([RULE])[:-3]
    assert posted_knowledge([None, body]) == [RULE]


def test_no_knowledge_writes_no_marker():
    assert knowledge_marker([]) == ""


def test_a_hand_edited_marker_that_does_not_parse_is_skipped():
    bodies = [
        '<!-- marginal:knowledge [{"kind": "opinion"}] -->',
        "<!-- marginal:knowledge [not json] -->",
        knowledge_marker([RULE]),
    ]

    assert posted_knowledge(bodies) == [RULE]
