# F.R.I.D.A.Y. — Tool Catalogue

> *Complete reference for every MCP tool registered on the F.R.I.D.A.Y. server.*

All tools are automatically discovered from `friday/tools/`. To add a new tool, create a `.py` file there with a `register(mcp)` function — no manual registration needed.

---

## 🌐 Web (`web.py`)

| Tool | Description |
|------|-------------|
| `get_world_news` | Fetch live global headlines from BBC, CNBC, NYT, Al Jazeera |
| `search_web(query)` | Search the web via Brave API or DuckDuckGo fallback. Results are **cached for 30 min** |
| `search_code(query)` | Targeted search across Stack Overflow, GitHub, and official docs |
| `fetch_url(url)` | Fetch and strip HTML from any URL (first 5,000 chars). **Cached for 30 min** |
| `open_world_monitor` | Open worldmonitor.app in the default browser |
| `open_url(url)` | Open any URL in the host machine's default browser |

---

## 🖥️ System (`system.py`)

| Tool | Description |
|------|-------------|
| `get_current_time` | Returns the current date/time in human-readable + ISO 8601 format |
| `get_system_telemetry` | CPU cores, load, OS version, Python version, machine architecture |
| `get_environment_info` | Workspace path, user, hostname, shell, Python details |
| `get_host_control_status` | JSON snapshot of OS, hostname, user, workspace, shell, privileges |
| `scan_system_inventory(section, limit)` | Structured system overview: processes, storage, network interfaces |

---

## 📂 File Utils (`utils.py`)

| Tool | Description |
|------|-------------|
| `create_document(filename, content)` | Create a new file in the workspace |
| `append_to_file(file_path, content)` | Append text to an existing file |
| `get_file_contents(file_path)` | Read the full contents of a file |
| `read_file_snippet(file_path, start_line, end_line)` | Read a specific line range from a file |
| `write_file(file_path, content)` | Overwrite a file with new content |
| `list_directory_tree(path)` | Display a recursive file/folder tree |
| `search_in_files(directory, keyword)` | Grep for a keyword across all files in a directory |
| `copy_path(source_path, destination_path)` | Copy a file or directory |
| `move_path(source_path, destination_path)` | Move or rename a file or directory |
| `delete_path(path)` | Delete a file or directory |
| `format_json(data)` | Pretty-print a JSON string |
| `word_count(text)` | Count words, lines, and characters in text |
| `profile_dataset(file_path)` | Profile a CSV/JSON file — row counts, column types, samples |

---

## 📱 Apps & System Control (`apps.py`)

| Tool | Description |
|------|-------------|
| `open_application(app_name)` | Launch any application by name (macOS/Windows/Linux) |
| `list_chrome_profiles` | List Chrome profiles (Windows only) |
| `open_chrome_profile(profile_name, url, guest)` | Open Chrome directly into a specific profile (Windows) |
| `open_terminal(shell_name, wait_ms)` | Open and focus a terminal window |
| `get_running_apps` | List all foreground applications currently open |
| `list_open_windows(query, limit)` | List open window titles; permission-aware on macOS |
| `list_installed_apps(query, limit)` | Search installed applications |
| `search_local_apps(query)` | Locate app executables (Start Menu, /Applications, etc.) |
| `get_volume` | Get current system volume level |
| `set_volume(level)` | Set system volume (0–100) |
| `send_hotkey(keys)` | Send a keyboard shortcut (e.g. `cmd+c`, `ctrl+shift+t`) |
| `type_text(text, press_enter)` | Type text into the focused window |
| `set_timer(seconds, label)` | Set a countdown timer with a desktop notification |
| `send_notification(title, message)` | Send a desktop notification |

---

## 🖱️ Operator / Desktop Vision (`operator.py`)

| Tool | Description |
|------|-------------|
| `inspect_desktop_screen(question, include_windows)` | Capture desktop screenshot + optional vision analysis via OpenAI |
| `locate_screen_target(target, save_as)` | Find the (x, y) coordinates of a UI element using vision |
| `click_screen_target(x, y, button, clicks)` | Click at specific screen coordinates |
| `move_mouse(x, y)` | Move mouse to coordinates without clicking |
| `scroll_screen(x, y, amount, direction)` | Scroll at screen coordinates |

---

## 🧠 Memory (`memory.py`)

| Tool | Description |
|------|-------------|
| `store_core_fact(fact, category)` | Permanently store a fact about the user or FRIDAY |
| `synthesize_knowledge(task_description, outcome)` | LLM-powered synthesis of a task into a "Knowledge Nugget" |
| `query_agentic_memory(query)` | Semantic search across all memory tiers |
| `update_semantic_context(key, value)` | Update the current session's key-value semantic state |
| `get_recent_history(limit)` | Retrieve the last N conversation turns |
| `record_conversation_turn(user_message, assistant_reply, tool_events)` | Persist a conversation turn |
| `store_action_trace(goal, outcome, tool_events, status)` | Persist a task action trace |
| `get_recent_action_traces(limit)` | Retrieve recent action traces |

---

## 🗂️ Context Manager (`context_manager.py`) *(New in Phase 4)*

| Tool | Description |
|------|-------------|
| `get_context_stats` | Stats on current session: turn count, chars, trim needs |
| `trim_context(keep_last)` | Trim history to the N most recent turns |
| `get_session_summary` | Inline summary of recent conversation for context injection |
| `save_session_note(note)` | Bookmark what was accomplished in this session |
| `clear_session_context` | Wipe all history and saved notes (irreversible) |

---

## Workflow Orchestrator (`workflow_orchestrator.py`)

| Tool | Description |
|------|-------------|
| `analyze_workflow(goal)` | Detect likely capability needs and suggested tool families |
| `run_workflow_preflight(goal, live_checks)` | Check likely blockers before starting a workflow |
| `create_workflow_plan(goal, mode, live_checks)` | Persist a goal-level plan with preflight, verification, and recovery steps |
| `record_workflow_progress(workflow_id, step_id, status, result, next_action)` | Update a workflow step and append an event |
| `get_workflow_status(workflow_id)` | Show the latest or specified workflow state |
| `complete_workflow(workflow_id, outcome, verified)` | Mark a workflow complete with final outcome and verification status |

---

## Project Manifest (`project_manifest.py`)

| Tool | Description |
|------|-------------|
| `get_project_manifest` | Return the full `friday.project.json` metadata contract |
| `get_project_capabilities` | Return the declared capability table with roots and risk levels |
| `get_architecture_snapshot` | Return a compact runtime, security, extension, and validation snapshot |
| `get_tool_manifest` | Return loaded tool modules grouped by capability, risk, and approval posture |

---

## 🏥 Diagnostics (`diagnostics.py`) *(New in Phase 3)*

| Tool | Description |
|------|-------------|
| `run_permission_diagnostics` | Test macOS Screen Recording + Accessibility permissions and return fix instructions |

---

## 🔍 Planning & Research (`planning.py`, `research.py`, `subagent.py`)

| Tool | Description |
|------|-------------|
| `create_task_plan(goal)` | Generate a step-by-step plan for a complex task |
| `deep_research(query)` | Multi-source deep research with visual grid integration |
| `run_subagent(task, context)` | Spawn an autonomous sub-task agent |

---

## 🌍 Web Scraping (`firecrawl_tool.py`)

| Tool | Description |
|------|-------------|
| `deep_scrape_url(url)` | Full-page scrape via Firecrawl API or `trafilatura` fallback |

---

## 🌤️ Weather (`weather.py`)

| Tool | Description |
|------|-------------|
| `get_weather(location)` | Real-time weather via Open-Meteo (no API key required) |

---

## 🌐 Browser Automation (`browser.py`)

| Tool | Description |
|------|-------------|
| `browser_navigate(url)` | Navigate to a URL in a headless Chromium browser |
| `browser_get_state` | Get the current page title, URL, and interactive elements |
| `browser_read_page` | Read the page content as structured visual tags |
| `browser_click(element_index)` | Click an interactive element by its index |
| `browser_type(element_index, text)` | Type into a form field by element index |
| `browser_close` | Close the current browser session |

---

## 💰 Finance (`finance.py`)

| Tool | Description |
|------|-------------|
| `get_stock_price(ticker)` | Real-time stock price |
| `get_crypto_price(coin)` | Real-time crypto price |
| `convert_currency(amount, from_currency, to_currency)` | Currency conversion |

---

## 🗃️ Files (`files.py`)

| Tool | Description |
|------|-------------|
| `download_file(url, filename)` | Download a file to the workspace |
| `read_pdf(file_path)` | Extract text from a PDF |
| `get_special_paths` | List Desktop, Documents, Downloads, and Workspace paths |
| `create_folder(folder_path)` | Create a new folder |

---

## 🗜️ Compression (`compression.py`)

| Tool | Description |
|------|-------------|
| `zip_files(paths, output_name)` | Zip one or more files/folders |
| `unzip_file(archive_path, destination)` | Extract a zip archive |
| `list_zip_contents(archive_path)` | List contents of a zip without extracting |

---

## 🌐 Network (`network.py`)

| Tool | Description |
|------|-------------|
| `ping_host(host, count)` | Ping a host and return latency |
| `dns_lookup(hostname)` | DNS resolution |
| `get_local_network_info` | Local IP, hostname, interfaces |
| `check_port(host, port)` | Test if a port is open |
| `fetch_url(url)` | HTTP GET request (in web.py, cached) |

---

## 🔧 Shell (`shell.py`)

| Tool | Description |
|------|-------------|
| `run_shell_command(command)` | Execute a raw shell command and return stdout/stderr |
| `execute_python_code(code)` | Execute arbitrary Python code in an isolated subprocess |

---

## 🎵 Media (`media.py`)

| Tool | Description |
|------|-------------|
| `get_volume` | Get current volume (also in apps.py) |
| `play_audio(file_path)` | Play an audio file |

---

## 🖼️ Images (`image_tool.py`)

| Tool | Description |
|------|-------------|
| `generate_image(prompt, output_name)` | AI image generation via Pollinations.ai (free) |
| `get_image_info(file_path)` | Read image dimensions, format, size |
| `resize_image(file_path, width, height)` | Resize an image |
| `convert_image_format(file_path, target_format, output_name)` | Convert image format (PNG→JPEG, etc.) |

---

## 📅 Calendar & Reminders (`calendar_tool.py`)

| Tool | Description |
|------|-------------|
| `create_calendar_event(title, start_datetime, duration_hours)` | Create a `.ics` calendar file |
| `add_reminder(text, remind_at)` | Set a reminder with a due date |
| `list_reminders` | List all active reminders |
| `mark_reminder_done(reminder_id)` | Mark a reminder as completed |

---

## 🌿 Git (`git_tool.py`)

| Tool | Description |
|------|-------------|
| `git_status(repo_path)` | `git status` output |
| `git_branch(repo_path)` | List branches |
| `git_log(repo_path, limit)` | Recent commit log |
| `git_diff(repo_path)` | Unstaged changes diff |
| `git_commit(repo_path, message)` | Stage all and commit |
| `git_push(repo_path)` | Push current branch |
| `git_pull(repo_path)` | Pull latest changes |
| `git_clone(url, destination)` | Clone a repository |

---

## 🔗 Codex Relay (`codex_tool.py`)

| Tool | Description |
|------|-------------|
| `get_codex_relay_status` | Check VS Code and Codex extension availability |
| `build_codex_project_brief` | Snapshot the current project structure for Codex |
| `relay_to_codex(prompt)` | Open VS Code, start a Codex session, and inject a prompt |

---

## 🌍 Translation (`translate.py`)

| Tool | Description |
|------|-------------|
| `translate_text(text, target_language)` | Translate text via MyMemory (free, no API key) |
