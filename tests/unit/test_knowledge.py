from marginal.review import Evidence
from marginal.review.knowledge import knowledge_marker, posted_knowledge
from marginal.review.schema import MAX_KNOWLEDGE_PER_REVIEW, FindingsResponse, Knowledge

RULE = Knowledge(
    kind="rule",
    statement="Totals over 100 --> ship free.",
    about="shop/pricing.py",
    evidence=Evidence(file="shop/pricing.py", line=4, quote="if total >= 100:"),
)


def test_knowledge_survives_the_round_trip_through_a_review_body():
    body = f"### 👾 marginal review\n\n{knowledge_marker([RULE])}"

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


def test_more_knowledge_than_the_cap_is_cut_and_the_findings_survive():
    response = FindingsResponse.model_validate(
        {"findings": [], "knowledge": [RULE.model_dump()] * (MAX_KNOWLEDGE_PER_REVIEW + 3)}
    )

    assert len(response.knowledge) == MAX_KNOWLEDGE_PER_REVIEW


def test_a_malformed_knowledge_item_is_skipped_and_the_findings_survive():
    bad = {
        "kind": "opinion",
        "statement": "x",
        "about": "a.py",
        "evidence": RULE.evidence.model_dump(),
    }

    response = FindingsResponse.model_validate(
        {"findings": [], "knowledge": [bad, RULE.model_dump(), {"extra": 1}]}
    )

    assert response.knowledge == [RULE]
    assert FindingsResponse.model_json_schema()["properties"]["knowledge"]["maxItems"] == (
        MAX_KNOWLEDGE_PER_REVIEW
    )
