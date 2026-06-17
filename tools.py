"""
tools.py

The three required FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Complete and test each tool before moving to agent.py.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str
"""

import os

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

load_dotenv()


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


# Groq-hosted model used for all LLM-backed tools.
_MODEL = "llama-3.3-70b-versatile"


def _chat(prompt: str, *, temperature: float = 0.7, max_tokens: int = 400) -> str:
    """
    Send a single-turn prompt to the LLM and return the response text.

    Args:
        prompt:      The full user prompt.
        temperature: Sampling temperature — higher means more varied output.
        max_tokens:  Maximum length of the response.

    Returns:
        The model's reply, stripped of surrounding whitespace.
    """
    client = _get_groq_client()
    response = client.chat.completions.create(
        model=_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content.strip()


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    Args:
        description: Keywords describing what the user is looking for
                     (e.g., "vintage graphic tee").
        size:        Size string to filter by, or None to skip size filtering.
                     Matching is case-insensitive (e.g., "M" matches "S/M").
        max_price:   Maximum price (inclusive), or None to skip price filtering.

    Returns:
        A list of matching listing dicts, sorted by relevance (best match first).
        Returns an empty list if nothing matches — does NOT raise an exception.

    Each listing dict has the following fields:
        id, title, description, category, style_tags (list), size,
        condition, price (float), colors (list), brand, platform

    TODO:
        1. Load all listings with load_listings().
        2. Filter by max_price and size (if provided).
        3. Score each remaining listing by keyword overlap with `description`.
        4. Drop any listings with a score of 0 (no relevant matches).
        5. Sort by score, highest first, and return the listing dicts.

    Before writing code, fill in the Tool 1 section of planning.md.
    """
    listings = load_listings()

    results = []
    for listing in listings:
        if max_price is not None and listing["price"] > max_price:
            continue
        if size is not None and not _size_matches(size, listing["size"]):
            continue

        score = _relevance_score(description, listing)
        if score > 0:
            results.append((score, listing))

    results.sort(key=lambda pair: pair[0], reverse=True)
    return [listing for _, listing in results]


# ── search helpers ─────────────────────────────────────────────────────────────

# Common words that carry no matching signal for clothing searches.
_STOPWORDS = {
    "a", "an", "the", "and", "or", "for", "with", "of", "to", "in", "on",
    "i", "im", "looking", "want", "need", "some", "any", "my", "me", "that",
    "this", "under", "over", "size", "sized", "please", "find", "show",
}


def _tokenize(text: str) -> list[str]:
    """Lowercase a string and split it into alphanumeric word tokens."""
    token, tokens = "", []
    for ch in text.lower():
        if ch.isalnum():
            token += ch
        elif token:
            tokens.append(token)
            token = ""
    if token:
        tokens.append(token)
    return tokens


def _size_matches(requested: str, listing_size: str) -> bool:
    """
    Case-insensitive size match.

    "One Size" listings fit any request. Otherwise every token in the requested
    size must appear in the listing size — so "M" matches "S/M" and "M/L",
    "W30" matches "W30 L30", and "US 8" matches "US 8", without "S" matching
    "One Size".
    """
    if "one size" in listing_size.lower():
        return True
    requested_tokens = _tokenize(requested)
    if not requested_tokens:
        return False
    listing_tokens = set(_tokenize(listing_size))
    return all(tok in listing_tokens for tok in requested_tokens)


def _relevance_score(description: str, listing: dict) -> int:
    """
    Score a listing by keyword overlap with the search description.

    Matches in the title and style tags are weighted more heavily than
    matches in the free-text description or other fields, since they're
    stronger relevance signals.
    """
    keywords = [t for t in _tokenize(description) if t not in _STOPWORDS]
    if not keywords:
        return 0

    strong = set(_tokenize(listing["title"]))
    for tag in listing.get("style_tags", []):
        strong.update(_tokenize(tag))
    strong.add(listing["category"].lower())

    weak = set(_tokenize(listing["description"]))
    for color in listing.get("colors", []):
        weak.update(_tokenize(color))
    if listing.get("brand"):
        weak.update(_tokenize(listing["brand"]))

    score = 0
    for kw in keywords:
        if kw in strong:
            score += 2
        elif kw in weak:
            score += 1
    return score


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(new_item: dict, wardrobe: dict) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty — handle this gracefully.

    Returns:
        A non-empty string with outfit suggestions.
        If the wardrobe is empty, offer general styling advice for the item
        rather than raising an exception or returning an empty string.

    TODO:
        1. Check whether wardrobe['items'] is empty.
        2. If empty: call the LLM with a prompt for general styling ideas
           (what kinds of items pair well, what vibe it suits, etc.).
        3. If not empty: format the wardrobe items into a prompt and ask
           the LLM to suggest specific outfit combinations using the new item
           and named pieces from the wardrobe.
        4. Return the LLM's response as a string.

    Before writing code, fill in the Tool 2 section of planning.md.
    """
    item_desc = _format_item(new_item)
    items = wardrobe.get("items", []) if wardrobe else []

    if not items:
        prompt = (
            "You are a personal stylist. A shopper is considering this "
            f"second-hand item:\n{item_desc}\n\n"
            "They haven't entered any wardrobe pieces yet. Give general styling "
            "advice for this item: what kinds of tops/bottoms/shoes/accessories "
            "pair well with it, and the overall vibe it suits. Describe one "
            "complete outfit (top + bottom or dress + shoes + accessories) in "
            "2-4 sentences of warm, specific advice. Do not invent specific "
            "items the shopper owns."
        )
        return _chat(prompt, temperature=0.7)

    wardrobe_desc = "\n".join(f"- {_format_wardrobe_item(it)}" for it in items)
    prompt = (
        "You are a personal stylist. A shopper is considering this second-hand "
        f"item:\n{item_desc}\n\n"
        f"Here is what they already own:\n{wardrobe_desc}\n\n"
        "Suggest 1-2 complete outfits that pair the second-hand item with "
        "specific pieces from their wardrobe (refer to those pieces by name). "
        "Each outfit must be complete: top + bottom (skip the bottom only if "
        "the item is a dress) + shoes + accessories. Write 2-4 sentences of "
        "warm, specific styling instructions, like a stylist texting a friend. "
        "Always include the second-hand item in every outfit."
    )
    return _chat(prompt, temperature=0.7)


def _format_item(item: dict) -> str:
    """Render a listing dict as a compact description for an LLM prompt."""
    tags = ", ".join(item.get("style_tags", []))
    colors = ", ".join(item.get("colors", []))
    brand = item.get("brand") or "unbranded"
    return (
        f"{item['title']} ({item['category']}) — {brand}, "
        f"colors: {colors}; style: {tags}; size {item['size']}; "
        f"${item['price']}. {item['description']}"
    )


def _format_wardrobe_item(item: dict) -> str:
    """Render a wardrobe item dict as a compact line for an LLM prompt."""
    colors = ", ".join(item.get("colors", []))
    tags = ", ".join(item.get("style_tags", []))
    notes = item.get("notes", "")
    line = f"{item['name']} ({item['category']}) — colors: {colors}; style: {tags}"
    return f"{line}; {notes}" if notes else line


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.

    Returns:
        A 2–4 sentence string usable as an Instagram/TikTok caption.
        If outfit is empty or missing, return a descriptive error message
        string — do NOT raise an exception.

    The caption should:
    - Feel casual and authentic (like a real OOTD post, not a product description)
    - Mention the item name, price, and platform naturally (once each)
    - Capture the outfit vibe in specific terms
    - Sound different each time for different inputs (use higher LLM temperature)

    TODO:
        1. Guard against an empty or whitespace-only outfit string.
        2. Build a prompt that gives the LLM the item details and the outfit,
           and asks for a caption matching the style guidelines above.
        3. Call the LLM and return the response.

    Before writing code, fill in the Tool 3 section of planning.md.
    """
    if not outfit or not outfit.strip():
        return (
            "Could not create a fit card: no outfit suggestion was provided. "
            "Generate an outfit with suggest_outfit() first."
        )

    prompt = (
        "Write a short, shareable social-media caption (like an Instagram or "
        "TikTok OOTD post) for a thrifted find.\n\n"
        f"Item: {new_item['title']}\n"
        f"Price: ${new_item['price']}\n"
        f"Platform: {new_item['platform']}\n"
        f"Styled outfit: {outfit}\n\n"
        "Guidelines:\n"
        "- 2-4 sentences, casual and authentic — sound like a real person "
        "posting their outfit, NOT a product description.\n"
        "- Naturally mention the item name, its price, and the platform once "
        "each.\n"
        "- Capture the outfit's vibe in specific terms.\n"
        "- A couple of tasteful emojis are fine. Return only the caption."
    )
    # Higher temperature so captions vary across runs and inputs.
    return _chat(prompt, temperature=1.0, max_tokens=200)
