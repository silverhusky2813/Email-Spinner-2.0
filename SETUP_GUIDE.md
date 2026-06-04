# Outreach Toolkit — Setup Guide

A two-tool system that supports **one personalized outreach email per publisher**, end to end:

1. **Research Brief** — pulls real, public facts about a publisher (monetization model, geo weighting, ad formats, candidate titles, contact emails) into a structured brief.
2. **Outreach Linter** — checks a draft email for fake urgency, unfilled placeholders / generic greetings, missing opt-out, and CPM figures that contradict the rate-card table.

The workflow is **Research → Write (you) → Lint**. Neither tool generates or sends email; the writing step stays human, by design. The brief tells you what's true about a target; the linter catches the mistakes that get honest outreach flagged as spam.

Both tools follow the same shape as the existing spintax codebase: a **pure logic engine** (no Streamlit, no network), a **thin Streamlit view**, and an **offline test suite**. The engines are independently testable so the part you rely on is the part that's proven.

---

## 1. File manifest

Drop these into the repo root (same directory as your stage modules), or into a `toolkit/` subfolder — see note in step 4 about imports.

| File | Role | Network? |
|------|------|----------|
| `brief_engine.py` | Brief extraction logic (pure) | No |
| `brief_fetch.py` | Fetches Wikipedia + public URLs | Yes (runtime) |
| `brief_ui.py` | Streamlit view: `render_brief()` | — |
| `test_brief.py` | 39 offline tests for the brief | No |
| `linter_rules.py` | Linter rule engine (pure) | No |
| `linter_ui.py` | Streamlit view: `render_linter()` | No |
| `test_linter.py` | 27 offline tests for the linter | No |

Import dependencies (keep these together in the same folder):

```
brief_ui.py   ->  brief_fetch.py  ->  (stdlib only)
brief_ui.py   ->  brief_engine.py ->  (stdlib only)
linter_ui.py  ->  linter_rules.py ->  (stdlib only)
test_brief.py ->  brief_engine.py, brief_fetch.py
test_linter.py -> linter_rules.py
```

No new third-party packages. Everything beyond Streamlit is Python stdlib.

---

## 2. Prerequisites

- Python 3.9+ (3.10+ recommended — the type hints use `X | None`)
- `streamlit` (already in your project)

Nothing else. The brief generator uses `urllib` from the standard library, so there is **no API key and no per-call cost**.

---

## 3. Run the tests first

Before wiring anything into the app, confirm the logic is sound. From the folder containing the files:

```bash
python3 test_linter.py
python3 test_brief.py
```

Each prints a per-check log and exits non-zero on failure. Expected:

```
==== 27 passed, 0 failed ====
==== 39 passed, 0 failed ====
```

Run these any time you edit a rule or an extractor. They are fast and offline, so they fit a pre-commit hook:

```bash
# .git/hooks/pre-commit  (chmod +x)
#!/bin/sh
python3 test_linter.py && python3 test_brief.py
```

---

## 4. Wire the two views into the sidebar

Both views expose a single render function: `render_brief()` and `render_linter()`. Mount them the same way your existing stage views are mounted.

**If the files are in the repo root**, import directly:

```python
from brief_ui import render_brief
from linter_ui import render_linter
```

**If you put them in `toolkit/`**, add an `__init__.py` to that folder and import as:

```python
from toolkit.brief_ui import render_brief
from toolkit.linter_ui import render_linter
```

> Important: `brief_ui` imports `brief_fetch` and `brief_engine` by bare module name, and `linter_ui` imports `linter_rules` by bare module name. Keep each UI file in the **same directory** as the modules it imports, or convert them to package-relative imports (`from .brief_engine import ...`) if you nest them in a package.

Then add the router entries. This mirrors how your `⚙️ Maintenance` view is registered under ADMIN — add a TOOLS section:

```python
# --- sidebar ---
st.sidebar.markdown("### 🧰 TOOLS")
if st.sidebar.button("🔎 Research Brief"):
    st.session_state["view"] = "brief"
if st.sidebar.button("✅ Outreach Linter"):
    st.session_state["view"] = "linter"

# --- router (wherever you dispatch on st.session_state["view"]) ---
view = st.session_state.get("view")
if view == "brief":
    render_brief()
elif view == "linter":
    render_linter()
# ... your existing stage/admin views ...
```

Adapt the exact session-state key and button pattern to match whatever your current router uses; the only requirement is that each view's render function gets called when its entry is selected.

---

## 5. Run locally

```bash
streamlit run app.py
```

You can also smoke-test either view standalone, since each UI file has a `__main__` guard:

```bash
streamlit run linter_ui.py     # linter only — fully offline
streamlit run brief_ui.py      # brief only — needs network for live fetch
```

---

## 6. Deploy to Streamlit Cloud

1. Commit the seven files to the repo (`github.com/silverhusky2813/spintax-direct`).
2. No `requirements.txt` change is needed unless Streamlit itself isn't pinned there already.
3. Push. Streamlit Cloud redeploys automatically.

**One environment caveat:** the brief generator makes outbound HTTP calls at runtime (Wikipedia + any URLs you paste). Streamlit Cloud allows outbound network, so this works in production. It will **not** work inside a locked-down sandbox with egress restrictions — that's expected; the engine's logic is still fully testable offline via `test_brief.py`, which is why the fetch layer is kept separate.

---

## 7. End-to-end use (worked example: Mytona)

1. **Research Brief**
   - Publisher: `Mytona`
   - Optional URLs: the company site, a monetization case-study page, an app-store listing.
   - Generate. You get: monetization = **Hybrid (IAP + ads)**, geo weighting led by the **United States**, formats including **rewarded / intrinsic / in-game**, candidate titles, and any public emails (usually generic).
   - Read the **Verify before acting** notes. The most important one: the scraped email is a starting point, not a target — find the actual ad-monetization / platform-partnerships owner. Don't pitch the CEO or `info@`.

2. **Write the email yourself**
   - Anchor it on what the brief surfaced: US weighting, UX-respecting formats, a specific title. One real, checkable claim beats ten spun variants.
   - Make the offer true. If your rate card lists a $6 rewarded floor, the email says $6.

3. **Outreach Linter**
   - Paste the draft (include the rate-card table — the CPM check only runs when a table is present).
   - Fix every 🔴 error before sending. A red on `cpm_consistency` means a number in your prose contradicts the table (this is the exact $5-vs-$6 bug the linter was built to catch). A red on `greeting` means an unfilled `[Name]` placeholder.
   - Treat 🟡 warnings (fake urgency, missing opt-out) as send-blockers in practice — they're the difference between outreach and spam.

---

## 8. Known limits (read these)

**Brief generator**
- Free sources mean rate limits and some sites blocking scrapers. A partial brief is normal and still useful; the engine reports what it couldn't find rather than inventing it.
- Candidate titles are extracted heuristically from trigger phrases ("known for", "such as", …). Verify them — treat as leads, not facts.
- The CPM/ad-fit signal is only as good as the pages you feed it. If a publisher is IAP-only with no ad formats found, the brief flags that an ad-buy pitch may not fit — confirm before reaching out.

**Linter**
- The CPM consistency check fires only when a markdown rate-card table is present. No table, nothing to validate against — it stays silent rather than guess.
- Fake-urgency detection matches a fixed phrase list (`_URGENCY_PATTERNS` in `linter_rules.py`). A genuinely novel pressure phrasing can slip through; adding it is a one-line edit.
- It's a linter, not a guarantee. It catches known failure modes fast; a human read is still the last check before send.

---

## 9. Maintenance

- **Add an urgency phrase:** append a `(regex, label)` tuple to `_URGENCY_PATTERNS` in `linter_rules.py`, add a test in `test_linter.py`, run the suite.
- **Add a geo or format:** extend `_GEO_PATTERNS` / `_FORMAT_PATTERNS` in `brief_engine.py`, add a test, run the suite.
- **Add a title trigger phrase:** append to `_TITLE_TRIGGERS` in `brief_engine.py`, add a test, run the suite.
- Golden rule: **a rule change without a matching test doesn't ship.** The suites are the contract that keeps both tools honest as they grow.

---

## What this system deliberately does not do

It does not generate outreach copy from a publisher name, spin variants, rotate senders, or send anything. Those steps are intentionally left to you. The toolkit makes the *honest* half of outreach faster — knowing your target and not making careless mistakes — which is the half that earns repeat business from sophisticated publishers.
