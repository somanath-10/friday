# F.R.I.D.A.Y. — Workflow Examples

> *Five complete end-to-end workflows demonstrating how to chain F.R.I.D.A.Y. tools together.*

---

## Workflow 1: Morning Briefing

Ask F.R.I.D.A.Y. to prepare your daily brief.

**Voice/Chat Prompt:**
> "Good morning F.R.I.D.A.Y., give me my morning briefing."

**Tools chained internally:**
1. `get_current_time` — establish today's date/time
2. `get_world_news` — fetch live global headlines
3. `get_weather(location="local")` — get today's weather
4. `get_context_stats` — check if there are notes from yesterday's session
5. `get_session_summary` — surface any saved session notes

**Output:** A structured markdown brief delivered in the chat or via TTS.

---

## Workflow 2: Deep Research + Report Generation

Ask F.R.I.D.A.Y. to research a topic and write a document.

**Voice/Chat Prompt:**
> "Research the latest trends in agentic AI and write a summary report."

**Tools chained internally:**
1. `search_web("agentic AI trends 2025")` — initial broad search (cached)
2. `search_code("LangGraph LlamaIndex multi-agent frameworks")` — technical angle
3. `fetch_url(top_3_urls)` — scrape the most relevant pages
4. `deep_scrape_url(url)` — for richer article extraction where needed
5. `create_document("agentic_ai_report.md", content)` — save the report to workspace

**Expected time:** ~30 seconds for a multi-source research report.

---

## Workflow 3: Desktop Automation — Open App and Type

Ask F.R.I.D.A.Y. to interact with an app.

**Voice/Chat Prompt:**
> "Open Notepad and type 'Meeting notes for April 24'"

**Tools chained internally:**
1. `run_permission_diagnostics` — verify Accessibility permission is granted
2. `open_application("Notepad")` — launch the app
3. `inspect_desktop_screen("Is Notepad open and focused?")` — visual verification
4. `type_text("Meeting notes for April 24", press_enter=False)` — type into the window
5. `inspect_desktop_screen("Confirm the text was typed correctly")` — self-verify

---

## Workflow 4: Git Workflow — Commit and Push

Ask F.R.I.D.A.Y. to commit your recent work.

**Voice/Chat Prompt:**
> "Commit all my changes with the message 'Add Phase 4 documentation' and push."

**Tools chained internally:**
1. `git_status(repo_path=".")` — show what's staged/unstaged
2. `git_diff(repo_path=".")` — review the changes
3. `git_commit(repo_path=".", message="Add Phase 4 documentation")` — commit
4. `git_push(repo_path=".")` — push to origin
5. `store_action_trace(goal="git push", outcome="success", status="completed")` — log to memory

---

## Workflow 5: Session Management — Start Fresh

Ask F.R.I.D.A.Y. to wrap up an old session and start clean.

**Voice/Chat Prompt:**
> "Save a note that we finished the best-in-class upgrade, then clear the session context."

**Tools chained internally:**
1. `get_context_stats` — check how large the current session is
2. `save_session_note("Completed Phases 1–4 of the Best-in-Class upgrade. 82 healthcheck tests passing.")` — bookmark the work
3. `clear_session_context` — wipe history for a clean slate on the next task

---

## Tips for Chaining Tools

- **Always verify permissions first** for desktop automation using `run_permission_diagnostics`.
- **Use caching** — `search_web` and `fetch_url` cache results for 30 minutes, so repeated lookups are instant.
- **Save important results** using `create_document` or `save_session_note` so nothing is lost between sessions.
- **Use `inspect_desktop_screen`** before and after GUI operations to self-verify the action succeeded.
- **Check context size** with `get_context_stats` if responses start feeling slow — trim with `trim_context`.
