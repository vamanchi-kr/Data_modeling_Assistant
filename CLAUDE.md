# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the App

`streamlit` is not on PATH — always invoke via:

```bash
python -m streamlit run app.py
```

The first run requires `~/.streamlit/credentials.toml` with `[general]\nemail = ""` to suppress the email prompt. A `.streamlit/config.toml` with `gatherUsageStats = false` is already committed.

## Architecture

This is a single-page Streamlit app with three backend modules. There is no build step, no test suite, and no server framework — `app.py` is the entrypoint and contains all UI logic.

### Data flow

1. **`app.py`** — Streamlit UI. Owns all session state (`st.session_state`). Calls the three `src/` modules and wires results together.
2. **`src/databricks_client.py`** — `DatabricksClient` wraps the Databricks SDK. Catalog/schema/table listing uses `ThreadPoolExecutor` (up to 12 workers) to parallelize Unity Catalog REST calls. `prefetch_catalog()` is the main entry point — returns `{schema: [table_dicts]}`. `get_multiple_table_details()` fetches column-level metadata in parallel. `format_multiple_schemas()` converts detail dicts into LLM-ready text.
3. **`src/kimball_assistant.py`** — `KimballAssistant` wraps `anthropic.Anthropic`. `stream_response()` yields tokens for chat; `one_shot()` is used for doc generation. The system prompt (`KIMBALL_SYSTEM_PROMPT`) encodes the full Kimball methodology and instructs the model to always produce a `mermaid` `erDiagram` block in its first modeling response.
4. **`src/visualizer.py`** — Stateless helpers: `extract_last_mermaid()` parses the last mermaid block from assistant text (used to auto-update the diagram tab after each reply), `mermaid_to_html()` wraps diagram code in a self-contained HTML page rendered via `st.components.v1.html`, `generate_powerbi_model_skeleton()` parses the mermaid source to emit a TMDL-compatible JSON skeleton, `build_export_prompt()` assembles the full conversation into a doc-generation prompt.

### Session state keys

Key state managed in `app.py`:

| Key | Purpose |
|---|---|
| `messages` | Full conversation history (Anthropic messages format) |
| `selected_tables` | `{full_name: detail_dict}` — tables in current modeling context |
| `catalog_tree` | `{catalog: {schema: [table_dicts]}}` — prefetch cache |
| `table_detail_cache` | `{full_name: detail_dict}` — column metadata cache |
| `last_diagram` | Raw mermaid source of the most recent ER diagram |
| `assistant` | `KimballAssistant` instance (recreated when API key changes) |

### Claude model

`KimballAssistant` defaults to `claude-sonnet-4-6`. To change the model, pass `model=` to the constructor in `get_assistant()` in `app.py`.

## Dependencies

```
streamlit>=1.35.0
anthropic>=0.30.0
databricks-sdk>=0.28.0
python-dotenv>=1.0.0
pandas>=2.0.0
```

`pandas` is listed as a dependency but not yet actively used — it was included for potential future schema diffing.

## Environment Variables

Loaded from `.env` via `python-dotenv` at startup. All three can also be entered in the sidebar at runtime:

- `ANTHROPIC_API_KEY`
- `DATABRICKS_HOST` — e.g. `https://adb-xxx.azuredatabricks.net`
- `DATABRICKS_TOKEN` — Databricks Personal Access Token
