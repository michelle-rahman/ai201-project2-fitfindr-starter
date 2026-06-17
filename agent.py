"""
agent.py

The FitFindr planning loop. Orchestrates the three tools in response to a
natural language user query, passing state between them via a session dict.

Complete tools.py and test each tool in isolation before implementing this file.

Usage (once implemented):
    from agent import run_agent
    from utils.data_loader import get_example_wardrobe

    result = run_agent(
        query="vintage graphic tee under $30, size M",
        wardrobe=get_example_wardrobe(),
    )
    print(result["fit_card"])
    print(result["error"])   # None on success
"""

import re

from tools import search_listings, suggest_outfit, create_fit_card


# ── session state ─────────────────────────────────────────────────────────────

def _new_session(query: str, wardrobe: dict) -> dict:
    """
    Initialize and return a fresh session dict for one user interaction.

    The session dict is the single source of truth for everything that happens
    during a run — it stores the original query, parsed parameters, tool results,
    and any error that caused early termination.

    You may add fields to this dict as needed for your implementation.
    """
    return {
        "query": query,              # original user query
        "parsed": {},                # extracted description / size / max_price
        "search_results": [],        # list of matching listing dicts
        "selected_item": None,       # top result, passed into suggest_outfit
        "wardrobe": wardrobe,        # user's wardrobe dict
        "outfit_suggestion": None,   # string returned by suggest_outfit
        "fit_card": None,            # string returned by create_fit_card
        "error": None,               # set if the interaction ended early
    }


# ── planning loop ─────────────────────────────────────────────────────────────

def run_agent(query: str, wardrobe: dict) -> dict:
    """
    Main agent entry point. Runs the FitFindr planning loop for a single
    user interaction and returns the completed session dict.

    Args:
        query:    Natural language user request
                  (e.g., "vintage graphic tee under $30, size M")
        wardrobe: User's wardrobe dict — use get_example_wardrobe() or
                  get_empty_wardrobe() from utils/data_loader.py

    Returns:
        The session dict after the interaction completes. Check session["error"]
        first — if it is not None, the interaction ended early and the other
        output fields (outfit_suggestion, fit_card) will be None.

    TODO — implement this function using the planning loop you designed in planning.md:

        Step 1: Initialize the session with _new_session().

        Step 2: Parse the user's query to extract a description, size, and
                max_price. You can use regex, string splitting, or ask the LLM
                to parse it — document your choice in planning.md.
                Store the result in session["parsed"].

        Step 3: Call search_listings() with the parsed parameters.
                Store results in session["search_results"].
                If no results: set session["error"] to a helpful message and
                return the session early. Do NOT proceed to suggest_outfit
                with empty input.

        Step 4: Select the item to use (e.g., the top result).
                Store it in session["selected_item"].

        Step 5: Call suggest_outfit() with the selected item and wardrobe.
                Store the result in session["outfit_suggestion"].

        Step 6: Call create_fit_card() with the outfit suggestion and selected item.
                Store the result in session["fit_card"].

        Step 7: Return the session.

    Before writing code, complete the Planning Loop and State Management sections
    of planning.md — your implementation should match what you described there.
    """
    session = _new_session(query, wardrobe)

    # Step 1–2: parse the query into search parameters.
    session["parsed"] = _parse_query(query)
    parsed = session["parsed"]

    # Guard: an empty wardrobe can't be styled — exit before searching.
    if not wardrobe or not wardrobe.get("items"):
        session["error"] = (
            "Your wardrobe is empty. Add a few pieces you own so FitFindr can "
            "style the find with them."
        )
        return session

    # Step 3: search for listings, loosening the filters if nothing matches.
    results = _search_with_loosening(parsed, session)
    session["search_results"] = results
    if not results:
        session["error"] = (
            f"No second-hand listings matched '{parsed['description']}'. "
            "Try a different item or loosen your size/price."
        )
        return session

    # Step 4: select the top (most relevant) result.
    session["selected_item"] = results[0]

    # Step 5: suggest an outfit pairing the find with the user's wardrobe.
    outfit = suggest_outfit(session["selected_item"], wardrobe)
    if not outfit or not outfit.strip():
        session["error"] = "Could not generate an outfit suggestion for this item."
        return session
    session["outfit_suggestion"] = outfit

    # Step 6: build the shareable fit card.
    session["fit_card"] = create_fit_card(outfit, session["selected_item"])

    # Step 7: return the completed session.
    return session


# ── query parsing ──────────────────────────────────────────────────────────────

# "M", "S/M", "XL", waist/length sizes like "W30" or "W30 L30", and US shoe sizes.
_SIZE_RE = re.compile(
    r"\bsize\s+([a-z0-9/]+(?:\s+\d+(?:\.\d)?)?)\b"
    r"|\b(x{0,2}[sl]|m|l/xl|s/m|m/l)\b"
    r"|\b(w\d{2}(?:\s*l\d{2})?)\b"
    r"|\b(us\s*\d+(?:\.\d)?)\b",
    re.IGNORECASE,
)

def _parse_query(query: str) -> dict:
    """
    Extract a description, optional size, and optional max_price from the query.

    Uses regex (no LLM call) so parsing is deterministic and cheap. The size and
    price phrases are stripped from the text that becomes the search description.
    """
    size = None
    max_price = None
    description = query

    # Price: look for an explicit ceiling phrase ("under $30", "below 25").
    price_match = re.search(
        r"(?:under|below|less than|max|up to|<)\s*\$?\s*(\d+(?:\.\d{1,2})?)",
        query,
        re.IGNORECASE,
    )
    if price_match:
        max_price = float(price_match.group(1))
        description = description.replace(price_match.group(0), " ")

    # Size: prefer an explicit "size X" phrase, else a standalone size token.
    size_match = _SIZE_RE.search(query)
    if size_match:
        size = next(g for g in size_match.groups() if g).strip()
        description = description.replace(size_match.group(0), " ")

    # Clean leftover punctuation/whitespace from the description.
    description = re.sub(r"\s+", " ", description).strip(" ,.-")

    return {"description": description, "size": size, "max_price": max_price}


def _search_with_loosening(parsed: dict, session: dict) -> list:
    """
    Run search_listings, progressively loosening filters when nothing matches.

    Tries the full query first, then drops the size filter, then raises the
    price ceiling in $10 steps. Records any loosening in session["loosened"]
    so the agent can mention it to the user.
    """
    session["loosened"] = []

    results = search_listings(**parsed)
    if results:
        return results

    # Drop the size filter.
    if parsed.get("size") is not None:
        results = search_listings(parsed["description"], None, parsed.get("max_price"))
        if results:
            session["loosened"].append(f"ignored size {parsed['size']}")
            return results

    # Raise the price ceiling up to $30 over the original.
    if parsed.get("max_price") is not None:
        for bump in (10, 20, 30):
            raised = parsed["max_price"] + bump
            results = search_listings(parsed["description"], None, raised)
            if results:
                session["loosened"].append(f"raised max price to ${raised:.0f}")
                return results

    return []


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

    print("=== Happy path: graphic tee ===\n")
    session = run_agent(
        query="looking for a vintage graphic tee under $30",
        wardrobe=get_example_wardrobe(),
    )
    if session["error"]:
        print(f"Error: {session['error']}")
    else:
        print(f"Found: {session['selected_item']['title']}")
        print(f"\nOutfit: {session['outfit_suggestion']}")
        print(f"\nFit card: {session['fit_card']}")

    print("\n\n=== No-results path ===\n")
    session2 = run_agent(
        query="designer ballgown size XXS under $5",
        wardrobe=get_example_wardrobe(),
    )
    print(f"Error message: {session2['error']}")
