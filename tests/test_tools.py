"""
Tests for the three FitFindr tools, one per documented failure mode plus
happy-path coverage.

The LLM-backed tools (suggest_outfit, create_fit_card) are tested with the
`_chat` helper monkeypatched, so the suite runs fast and offline without
needing a GROQ_API_KEY or network access. search_listings runs against the
real mock dataset.

Run with:  pytest tests/
"""

import pytest

import tools
from tools import search_listings, suggest_outfit, create_fit_card
from utils.data_loader import get_example_wardrobe, get_empty_wardrobe


# ── search_listings ─────────────────────────────────────────────────────────

def test_search_returns_results():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    assert isinstance(results, list)
    assert len(results) > 0


def test_search_empty_results():
    # Failure mode: nothing matches — returns an empty list, not an exception.
    results = search_listings("designer ballgown", size="XXS", max_price=5)
    assert results == []


def test_search_price_filter():
    results = search_listings("jacket", size=None, max_price=10)
    assert all(item["price"] <= 10 for item in results)


def test_search_size_filter():
    # "M" should match listings like "S/M" / "M/L", never something sized "XL".
    results = search_listings("top", size="M", max_price=None)
    for item in results:
        assert tools._size_matches("M", item["size"])


def test_search_sorted_by_relevance():
    # Title/tag matches should outrank weaker description-only matches.
    results = search_listings("vintage denim jeans", size=None, max_price=None)
    assert len(results) > 1
    scores = [tools._relevance_score("vintage denim jeans", r) for r in results]
    assert scores == sorted(scores, reverse=True)


# ── suggest_outfit ──────────────────────────────────────────────────────────

@pytest.fixture
def stub_chat(monkeypatch):
    """Replace the LLM call with a deterministic stub and capture its prompt."""
    calls = {}

    def fake_chat(prompt, **kwargs):
        calls["prompt"] = prompt
        calls["kwargs"] = kwargs
        return "stubbed outfit suggestion"

    monkeypatch.setattr(tools, "_chat", fake_chat)
    return calls


@pytest.fixture
def sample_item():
    return search_listings("vintage graphic tee", size=None, max_price=50)[0]


def test_suggest_outfit_with_wardrobe(stub_chat, sample_item):
    result = suggest_outfit(sample_item, get_example_wardrobe())
    assert isinstance(result, str) and result.strip()
    # Wardrobe items should be named in the prompt sent to the LLM.
    assert "Baggy straight-leg jeans" in stub_chat["prompt"]


def test_suggest_outfit_empty_wardrobe(stub_chat, sample_item):
    # Failure mode: empty wardrobe must not crash and must return a string.
    result = suggest_outfit(sample_item, get_empty_wardrobe())
    assert isinstance(result, str) and result.strip()


def test_suggest_outfit_missing_items_key(stub_chat, sample_item):
    # Defensive: a wardrobe dict with no 'items' key is treated as empty.
    result = suggest_outfit(sample_item, {})
    assert isinstance(result, str) and result.strip()


# ── create_fit_card ─────────────────────────────────────────────────────────

def test_create_fit_card_happy_path(stub_chat, sample_item):
    result = create_fit_card("Pair it with baggy jeans and sneakers.", sample_item)
    assert result == "stubbed outfit suggestion"
    # Caption prompt must include name, price, and platform.
    assert sample_item["title"] in stub_chat["prompt"]
    assert str(sample_item["price"]) in stub_chat["prompt"]
    assert sample_item["platform"] in stub_chat["prompt"]


def test_create_fit_card_uses_high_temperature(stub_chat, sample_item):
    create_fit_card("Pair it with baggy jeans.", sample_item)
    # Higher temperature drives caption variety across runs.
    assert stub_chat["kwargs"].get("temperature", 0) >= 1.0


def test_create_fit_card_empty_outfit(sample_item):
    # Failure mode: empty/whitespace outfit returns an error string, no raise.
    # No _chat stub needed — the guard returns before any LLM call.
    result = create_fit_card("   ", sample_item)
    assert isinstance(result, str) and result.strip()
    assert "fit card" in result.lower()


def test_create_fit_card_empty_outfit_no_llm_call(monkeypatch, sample_item):
    # The empty-outfit guard must short-circuit before calling the LLM.
    def boom(*args, **kwargs):
        raise AssertionError("_chat should not be called for empty outfit")

    monkeypatch.setattr(tools, "_chat", boom)
    result = create_fit_card("", sample_item)
    assert isinstance(result, str) and result.strip()
