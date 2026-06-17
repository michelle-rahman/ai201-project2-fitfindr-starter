# FitFindr 🛍️

FitFindr is an agent that finds secondhand clothing listings matching a natural-language
request, suggests a complete outfit pairing the find with the user's existing wardrobe, and
writes a short shareable "fit card" caption for it.

A single query flows through three tools connected by a planning loop:

```
User query + wardrobe → search_listings → suggest_outfit → create_fit_card → result
```

---

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Set your Groq API key in a `.env` file in the project root (get a free key at
   [console.groq.com](https://console.groq.com)):
   ```
   GROQ_API_KEY=your_key_here
   ```
   The two LLM-backed tools (`suggest_outfit`, `create_fit_card`) use Groq's
   `llama-3.3-70b-versatile` model.

## Running a complete interaction

**CLI** — runs the built-in happy-path and no-results test cases:
```bash
python agent.py
```

**Gradio UI** — type a query, choose a wardrobe, see the three result panels:
```bash
python app.py
```
Then open the localhost URL printed in the terminal (usually http://localhost:7860).

**Tests** — one test per failure mode plus happy paths (LLM calls are stubbed, runs offline):
```bash
pytest tests/
```

---

## Tool Inventory

### 1. `search_listings(description, size, max_price)`
- **Purpose:** Search the mock listings dataset for items matching the user's request.
- **Inputs:**
  - `description` (`str`, required) — keywords describing the item (e.g. `"vintage graphic tee"`).
  - `size` (`str | None`) — size to filter by; case-insensitive, token-based (`"M"` matches `"S/M"`). `None` skips the filter.
  - `max_price` (`float | None`) — inclusive price ceiling. `None` skips the filter.
- **Output:** `list[dict]` — matching listing dicts sorted by relevance, best match first. Empty list if nothing matches (never raises).
- **How it works:** Loads listings via `load_listings()`, filters by size/price, scores each remaining listing by keyword overlap with `description` (title/style-tag/category matches weighted ×2, description/color/brand ×1), drops zero-score items, and sorts by score.

### 2. `suggest_outfit(new_item, wardrobe)`
- **Purpose:** Suggest 1–2 complete outfits pairing the thrifted find with the user's wardrobe.
- **Inputs:**
  - `new_item` (`dict`) — the selected listing dict.
  - `wardrobe` (`dict`) — a dict with an `"items"` key listing wardrobe item dicts (`name`, `category`, `colors`, `style_tags`, `notes`).
- **Output:** `str` — outfit instructions referencing wardrobe pieces by name. If the wardrobe is empty, returns general styling advice instead (never empty, never raises).
- **How it works:** Formats the item and wardrobe into a prompt and calls the LLM via the shared `_chat` helper (temperature 0.7).

### 3. `create_fit_card(outfit, new_item)`
- **Purpose:** Write a short, shareable social-media caption for the styled find.
- **Inputs:**
  - `outfit` (`str`) — the outfit suggestion string from `suggest_outfit()`.
  - `new_item` (`dict`) — the selected listing dict (used for name, price, platform).
- **Output:** `str` — a 2–4 sentence casual caption mentioning the item name, price, and platform. If `outfit` is empty/whitespace, returns a descriptive error string instead.
- **How it works:** Guards the empty-outfit case first, then calls the LLM at a high temperature (1.0) so captions vary across runs.

---

## Planning Loop

`run_agent(query, wardrobe)` in `agent.py` runs the three tools in a fixed order, but
**branches on intermediate results** rather than calling every tool unconditionally:

1. **Parse** the query (`_parse_query`) into `description`, `size`, and `max_price` using
   regex — deterministic, no LLM call.
2. **Guard the wardrobe:** if `wardrobe["items"]` is empty, set `session["error"]` and return
   immediately — before any search.
3. **Search** with `_search_with_loosening`, which progressively drops the size filter and
   raises the price ceiling in $10 steps if the first search is empty.
4. If still no results, set `session["error"]` and return early — **`suggest_outfit` is never
   called on an empty result set.**
5. Otherwise select the top result, call `suggest_outfit`, then `create_fit_card`.
6. Return the completed `session`.

The loop's behavior differs by input: a matching query runs all three tools; an impossible
query stops after `search_listings` with an error and `fit_card` left as `None`.

---

## State Management

All state for one interaction lives in a single `session` dict created by `_new_session()`.
Tools never call each other directly — each step reads its inputs from the session and writes
its outputs back, so the next step picks them up:

| Field | Set by | Consumed by |
|-------|--------|-------------|
| `query` | entry point | parser |
| `parsed` | `_parse_query` | `search_listings` |
| `search_results` | `search_listings` | item selection |
| `selected_item` | top result | `suggest_outfit`, `create_fit_card` |
| `wardrobe` | caller | `suggest_outfit` |
| `outfit_suggestion` | `suggest_outfit` | `create_fit_card` |
| `fit_card` | `create_fit_card` | final output |
| `error` | any early-exit | caller / UI |
| `loosened` | `_search_with_loosening` | UI note (optional) |

State passing is by reference: the exact `selected_item` dict object is what reaches both
`suggest_outfit` and `create_fit_card`, and the exact `outfit_suggestion` string is what reaches
`create_fit_card` — verified by object identity during testing, confirming no re-prompting or
hardcoded values between steps. The caller checks `session["error"]` first to distinguish
success from early termination.

---

## Error Handling

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| `search_listings` | No results match | Returns `[]` (never raises). The loop loosens filters and retries; if still empty, sets `session["error"]` with an actionable message and returns early. |
| `suggest_outfit` | Empty wardrobe | Tool returns general styling advice (never empty/raises). The **agent loop** enforces the chosen UX policy by exiting earlier with a "your wardrobe is empty, add items" message. |
| `create_fit_card` | Empty/whitespace outfit | Returns a descriptive error string rather than raising; the loop leaves `session["fit_card"]` as `None`. |

**Concrete examples from testing:**

- **No results** — `search_listings('designer ballgown', size='XXS', max_price=5)` returned `[]`,
  and the full agent responded:
  > No second-hand listings matched 'designer ballgown'. Try a different item or loosen your size/price.

  with `fit_card` left as `None` and `suggest_outfit` confirmed called **0 times**.

- **Empty outfit** — `create_fit_card('', item)` returned, with no exception:
  > Could not create a fit card: no outfit suggestion was provided. Generate an outfit with suggest_outfit() first.

- **Empty wardrobe** — `suggest_outfit(item, get_empty_wardrobe())` returned useful general advice
  ("…pair it with high-waisted jeans or a flowy skirt…") instead of crashing or returning an empty
  string.

---

## Spec Reflection

The implementation follows the spec closely, with a few deliberate refinements discovered during
testing:

- **Where parameter-loosening lives:** the spec describes loosening size/price when a search comes
  up empty. I placed this in the *planning loop* (`_search_with_loosening`), not inside
  `search_listings`, so the tool stays a pure, predictable filter and the loop owns retry policy.
- **Empty-wardrobe behavior is split across two layers:** the tool's docstring asks for general
  advice, but the desired UX is to stop and prompt the user to add items. Rather than choose one, the
  tool gives advice (robust for direct use) while the agent loop enforces the early-exit policy. This
  keeps both the tool contract and the product behavior correct.
- **Size matching needed to be token-based:** a naive substring match made `"S"` match `"One Size"`.
  The final `_size_matches` tokenizes both sides and requires every requested token to be present,
  with a pass-through for "One Size" items.
- **Relevance scoring is keyword-based, not semantic.** For a deterministic, free, fast search filter
  this is the right tradeoff; a semantic/embedding approach would be the upgrade path if fuzzy intent
  matching becomes important.

---

## AI Usage

I used Claude (via Claude Code) to help implement the tools and planning loop. Two specific instances:

**1. Implementing `search_listings`.**
- *Input I gave it:* the Tool 1 spec block from `planning.md` (purpose, the three parameters with
  types, the sorted-list return value, and the empty-list failure mode), plus the `load_listings()`
  docstring showing the listing dict fields.
- *What it produced:* a keyword-overlap scoring implementation that filtered by size/price and sorted
  by score.
- *What I changed/overrode:* the first version did a plain case-insensitive substring size match, which
  let `"S"` match `"One Size"`. I replaced it with token-based matching (`_size_matches`) plus a
  "One Size" pass-through, and added a stopword list so filler words like "looking"/"under" didn't
  inflate scores. I also kept the retry/loosening logic *out* of the tool and moved it to the agent loop.

**2. Implementing the planning loop (`run_agent`) and query parser.**
- *Input I gave it:* the Planning Loop and State Management sections from `planning.md` and the agent
  architecture diagram, along with the numbered TODO steps already in `agent.py`.
- *What it produced:* a `run_agent` that branched on the search result and a regex-based `_parse_query`
  extracting `description`, `size`, and `max_price`.
- *What I changed/overrode:* the parser mis-handled multi-token shoe sizes — `"size US 8"` captured only
  `"US"` and left `"8"` in the description. I fixed the size regex to capture a trailing number and
  updated `_size_matches` to require all requested tokens, then verified by object identity that the
  same `selected_item` dict and `outfit_suggestion` string flowed between steps with no re-prompting.
