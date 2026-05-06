from sqr.retrieval import retrieve

KB = [
    {
        "id": "KB-IAM-MFA",
        "topics": ["mfa", "authentication"],
        "statement": "All accounts use Microsoft Entra MFA.",
    },
    {
        "id": "KB-CRYPTO-AT-REST",
        "topics": ["encryption_at_rest", "encryption"],
        "statement": "Data at rest is encrypted with AES-256.",
    },
    {
        "id": "KB-IR-PROGRAM",
        "topics": ["incident_response", "breach"],
        "statement": "We have a documented incident response program.",
    },
]


def test_retrieve_finds_mfa_for_mfa_question():
    hits = retrieve("Do you require MFA for all employees?", KB, top_k=2)
    assert hits[0]["id"] == "KB-IAM-MFA"


def test_retrieve_topic_boost_beats_token_overlap():
    hits = retrieve("How is data encrypted at rest?", KB, top_k=1)
    assert hits[0]["id"] == "KB-CRYPTO-AT-REST"


def test_retrieve_returns_empty_for_irrelevant_question():
    hits = retrieve("What is your favorite color?", KB)
    assert hits == []


def test_retrieve_respects_top_k():
    # Question that mentions multiple categories
    hits = retrieve("authentication and encryption and incident response policies", KB, top_k=2)
    assert len(hits) == 2
