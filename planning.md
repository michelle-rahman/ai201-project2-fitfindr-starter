# FitFindr — planning.md

> Complete this document before writing any implementation code.
> Your spec and agent diagram are what you'll use to direct AI tools (Claude, Copilot, etc.) to generate your implementation — the more specific they are, the more useful the generated code will be.
> Your planning.md will be reviewed as part of your submission.
> Update it before starting any stretch features.

---

## Tools

List every tool your agent will use. For each tool, fill in all four fields.
You must have at least 3 tools. The three required tools are listed — add any additional tools below them.

### Tool 1: search_listings

**What it does:**
This tool takes the user's query, identifies a clothing item that they are searching for, their clothing size (optional), and their maximum price and/or price range (optional), and then searches the listings.json list for a match or a list of matches. 

**Input parameters:**
- `description` (str): A required parameter. A description of the details of the clothing item that the user is searching for. 
- `size` (str): An optional parameter. If the item is a top, it includes a size such as "S", "M", "L", "XL" (representing small, medium, large, and extra large respectively). If the item is a bottom, it includes the waist size (such as W28) and/or the length (such as W)
- `max_price` (float): An optional parameter. The maximum price ($) that the user is willing to pay for the item. 

**What it returns:**
This tool receives a list of matching second-hand listings sorted by relevance, and returns the first value from this list (the most relevant listing). Example: "Faded Band Tee — $22, Depop, Good condition".

**What happens if it fails or returns nothing:**
If this tool fails and/or returns nothing, set an error message in the session and return early. The user is informed that no relevant listings were found and are prompted to ask for another item. 

---

### Tool 2: suggest_outfit

**What it does:**
Takes the output of the search_listings tool as input (new_item) as well as the items in the user's current wardrobe and suggests an outfit that would pair well with the new item + any items in the user's wardrobe. Must create a complete outfit with a top + bottom (optional, if the top is a dress) + shoes + accessories. 

**Input parameters:**
- `new_item` (dict): The output from the search_listings tool. The second-hand item that was retrieved as the most relevant search from the listings. It is a dictionary type and includes id, title, description, category, style tags, size, condition, price, colors, brand and platform. 
- `wardrobe` (dict): A dictionary of items that are present in a user's wardrobe. Includes information including id, name, category, colors, style tags and notes describing the fit. 

**What it returns:**
Returns a description of the complete outfit combination that was created, in the form of instructions on what the user should do in order to pair the new item with items that are currently in their wardrobe. Example: "Pair this with your wide-leg jeans and platform Docs for a classic 90s grunge look. Roll the sleeves once and tuck the front corner slightly for shape". 

**What happens if it fails or returns nothing:**
If the wardrobe is empty, exit the agent loop and inform the user that their wardrobe is empty and prompt them to add items to their wardrobe. If the tool returns nothing, then attempt to work with the minimal wardrobe to identify outfits that could work, even loosely. If absolutely no combinations work out, then exit the agent loop and return to the user that they do not have sufficient items in their wardrobe that would pair well with the new second-hand item. 
---

### Tool 3: create_fit_card

**What it does:**
Generates a short, shareable outfit caption (like an Instagram/TikTok outfit of the day post) for the thrifted find, given the styled outfit and the item's details.

**Input parameters:**
- `outfit` (str): The outfit suggestion text returned by suggest_outfit(). The recommended value is the exact string output of the prior tool, passed through unchanged. The function should guard against an empty/whitespace-only string here (return a descriptive error string, not raise).
- `new_item` (dict): the listing for the second hand item (the output search_listings() returns). 

**What it returns:**
A 2–4 sentence string usable as a social-media caption. It reads casually and
authentically (not like a product description), naturally mentions the item's
name, price, and platform once each, and captures the outfit's vibe in specific terms. Captions must vary across inputs .

**What happens if it fails or returns nothing:**
If `outfit` is empty or whitespace-only, the tool returns a descriptive error
string rather than raising an exception. The agent should treat this as a
failed step, leave session["fit_card"] as None, and surface the issue (e.g.,
prompt for a valid outfit suggestion) instead of presenting a broken caption.


---

## Planning Loop

**How does your agent decide which tool to call next?**
The loop runs the three tools in a fixed order — search_listings → suggest_outfit → create_fit_card — and uses the session dict as the single source of truth for deciding whether to advance.

What it looks at: Before each step it checks the relevant session field populated by the previous step:

After parsing, it has session["parsed"] (description, size, max_price) to feed search_listings.

After search, it checks session["search_results"]. If the list is empty, it sets session["error"] and returns early — it does not call suggest_outfit with empty input.
With results, it selects the top match into session["selected_item"], which becomes the input to suggest_outfit and later create_fit_card.

What changes its behavior: The main branch is the empty-results condition (and similarly, an empty/error outfit string), which short-circuits the pipeline. On any early exit, session["error"] is set and the downstream output fields (outfit_suggestion, fit_card) stay None.

How it knows it's done: The loop is finished when create_fit_card has populated session["fit_card"] (success), or as soon as session["error"] is set (early termination). Either way it returns the session dict; the caller checks session["error"] first to tell the two apart.

---

## State Management

**How does information from one tool get passed to the next?**
All state lives in a single `session` dict created by `_new_session(query, wardrobe)` at the start of each interaction. This dict is the single source of truth — tools don't call each other directly; instead each step reads its inputs from the session and writes its outputs back into it, so the next step can pick them up.

**What is tracked:**
- `query` — the original user query.
- `parsed` — the extracted `description`, `size`, and `max_price` (input to `search_listings`).
- `search_results` — the list of matching listing dicts returned by `search_listings`.
- `selected_item` — the top result chosen from `search_results` (input to both `suggest_outfit` and `create_fit_card`).
- `wardrobe` — the user's wardrobe dict (input to `suggest_outfit`).
- `outfit_suggestion` — the string returned by `suggest_outfit` (input to `create_fit_card`).
- `fit_card` — the final caption string returned by `create_fit_card`.
- `error` — `None` on success, or a message string if the loop ended early.

**How it's passed between tool calls:** The planning loop threads outputs forward through the session — `parsed` feeds `search_listings`; its results are stored, then the top one becomes `selected_item`; `selected_item` + `wardrobe` feed `suggest_outfit`, whose result is stored as `outfit_suggestion`; finally `outfit_suggestion` + `selected_item` feed `create_fit_card`, stored as `fit_card`. The completed session dict is returned to the caller, who checks `session["error"]` first to distinguish success from early termination.

---

## Error Handling

For each tool, describe the specific failure mode you're handling and what the agent does in response.

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| search_listings | No results match the query | Returns an empty list (never raises). The planning loop first loosens the parameters and retries — e.g. raise `max_price` by $10 and broaden keywords — noting any loosened values to surface to the user. If still empty, set `session["error"]`, return the session early, and tell the user no relevant listings were found and to try a different item. Does NOT proceed to `suggest_outfit` with empty input. |
| suggest_outfit | Wardrobe is empty | Set `session["error"]`, return the session early, and inform the user their wardrobe is empty, prompting them to add items before FitFindr can style an outfit. Does NOT fabricate an outfit from no wardrobe data. |
| create_fit_card | Outfit input is missing or incomplete | Guards against an empty/whitespace-only `outfit` and returns a descriptive error string rather than raising. The loop treats this as a failed step: leave `session["fit_card"]` as `None`, set `session["error"]`, and surface the issue rather than presenting a broken caption. |

---

## Architecture

User query + wardrobe
        │
        ▼
┌───────────────────────────────────────────────────────────┐
│  Planning loop                                            │
│                                                           │
│  Parse query → extracted description/size/max_price       │
│        │                        ↕ read/write              │
│        ▼                  ┌─────────────┐                 │
│  search_listings ─────────┤             │                 │
│        │  empty? → error  │   session   │                 │
│        ▼                  │   ─────────  │                 │
│  suggest_outfit ──────────┤  query      │                 │
│        │  empty? → error  │  parsed     │                 │
│        ▼                  │  selected_  │                 │
│  create_fit_card ─────────┤    item     │                 │
│        │  empty? → error  │  outfit_    │                 │
│        ▼                  │    sugg.    │                 │
│   session returned        │  fit_card   │                 │
│                           │  error      │                 │
└───────────────────────────┴─────────────┘                │
        │
        ▼
  Caller checks session["error"]
  ├── None → present fit_card to user
  └── set  → surface error message, prompt retry

---

## AI Tool Plan

**Milestone 3 — Individual tool implementations:**

For each tool I'll give Claude only the spec for that one tool (inputs, return value, failure mode) plus a note about any helper functions available (e.g. load_listings() for search_listings). I won't paste the whole planning doc — a focused prompt produces cleaner, less bloated code.

search_listings — I'll give Claude the Tool 1 spec, tell it the listings are loaded from listings.json via load_listings(), and ask it to return the single best match (or an empty list on no results). I'll verify by running three queries: one with all three params, one with only description, and one designed to return no matches. The function must never raise — I'll check that the no-match case returns [] cleanly.

suggest_outfit — I'll give Claude the Tool 2 spec and a sample new_item dict and a sample wardrobe dict. I'll ask it to return a natural-language outfit string, fall back to general advice when the wardrobe is sparse, and return None (not raise) when no combination works. I'll verify with three wardrobes: a full one, a minimal one (one item), and an empty one — confirming the empty case returns None rather than throwing.

create_fit_card — I'll give Claude the Tool 3 spec and a sample outfit string and new_item dict, and ask it to produce a 2–4 sentence social caption that varies across inputs. I'll verify by running it three times with different items/outfit strings and confirming (a) captions don't repeat structure verbatim, (b) price and platform are each mentioned once, and (c) an empty outfit input returns an error string rather than raising.

**Milestone 4 — Planning loop and state management:**

I'll give Claude the entire State Management and Planning Loop sections of this doc, plus the completed tool function signatures from Milestone 3, and ask it to implement run_agent(query, wardrobe) — the function that initialises _new_session, calls the three tools in order, threads state forward through the session dict, and returns the session. I'll explicitly tell it not to add extra logic beyond what's in the spec.
I'll verify the loop with four end-to-end cases:

Happy path — query matches a listing, wardrobe has items → session["fit_card"] is a non-empty string, session["error"] is None.
No search results — crafted query that matches nothing → loop exits after search_listings, session["error"] is set, downstream fields are None.
Empty wardrobe — valid query, wardrobe {} → loop exits after suggest_outfit (or returns general advice per the spec), session["fit_card"] is None.
Bad outfit string — I'll monkey-patch suggest_outfit to return "" → create_fit_card returns its error string, session["fit_card"] stays None, session["error"] is set.


---

## A Complete Interaction (Step by Step)

Write out what a full user interaction looks like from start to finish — tool call by tool call. Use a specific example query.

**Example user query:** "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers. What's out there and how would I style it?"

**Step 1:**
A search is performed first using the search_listings tool. For example, search_listings("vintage graphic tee", size="M", max_price=30.0) returns 3 matching listings sorted by relevance. FitFindr picks the top result: "Faded Band Tee — $22, Depop, Good condition". If nothing is found, then loosen the parameters and take note of these loosened parameters to include in the final output for the user. For instance, if a max price 30 was mentioned and nothing was returned, then increase the max_price by an increment of 10.  Also search for items with similar keywords. Do not move forward with next step unless something is outputted. If there is no output, then leave the tool loop and report to the user that no match could be found and prompt them to ask for a different item. 

**Step 2:**
The item that was outputted by the tool in step one is used as input for the second tool to suggest an outfit. suggest_outfit(new_item=<band tee>, wardrobe=<user's wardrobe>) returns: "Pair this with your wide-leg jeans and platform Docs for a classic 90s grunge look. Roll the sleeves once and tuck the front corner slightly for shape." Ensure that the suggested outfit includes the second-hand item that was found from the search_listings call in step one. 

**Step 3:**
The suggestion that was created by the previous tool gets inputted into the third tool in order to create a fit card, which outputs a description of the complete outfit that was generated, formatted like an instagram caption. create_fit_card(outfit=<suggestion>, new_item=<band tee>) returns: "thrifted this faded band tee off depop for $22 and honestly it was made for my wide-legs 🖤 full look in my stories"

**Final output to user:**
At the end, the agent outputs a response in three tiers: a description of the secondhand piece that it found based on the user's query, a description of the outfit that can be generated with the secondhand piece + items that are already in the users closet, as well as a shareable outfit description formatted like an instagram caption of the outfit. 