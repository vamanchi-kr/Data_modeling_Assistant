"""
Kimball Dimensional Modeling Assistant
Streamlit UI — Unity Catalog browser + Claude AI + Mermaid star-schema diagrams
"""

from __future__ import annotations

import os
from typing import Any

import streamlit as st
from dotenv import load_dotenv

from src.databricks_client import DatabricksClient
from src.kimball_assistant import (
    INITIAL_GREETING,
    KimballAssistant,
    build_table_context_message,
)
from src.visualizer import (
    build_export_prompt,
    extract_last_mermaid,
    generate_powerbi_model_skeleton,
    mermaid_to_html,
)

load_dotenv()

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Kimball Modeling Assistant",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

st.markdown("""
<style>
/* ── Sidebar width ─────────────────────────────────────────────────── */
[data-testid="stSidebar"] { min-width: 340px; max-width: 380px; }

/* ── Sidebar header ────────────────────────────────────────────────── */
.sidebar-brand {
  background: linear-gradient(135deg, #0f2942 0%, #1a1a2e 100%);
  border: 1px solid #3b82f6;
  border-radius: 10px;
  padding: 0.9rem 1.1rem;
  margin-bottom: 0.8rem;
}
.sidebar-brand h2 { color: #60a5fa; margin: 0; font-size: 1.05rem; }
.sidebar-brand p  { color: #94a3b8; margin: 0.2rem 0 0 0; font-size: 0.75rem; }

/* ── Section dividers ──────────────────────────────────────────────── */
.sec-label {
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: #64748b;
  padding: 0.6rem 0 0.25rem 0;
  border-bottom: 1px solid #1e3a5f;
  margin-bottom: 0.5rem;
}

/* ── Connection status badge ───────────────────────────────────────── */
.badge-live { background:#052e16; border:1px solid #16a34a; color:#4ade80;
  padding:0.15rem 0.6rem; border-radius:20px; font-size:0.75rem; font-weight:600; }
.badge-off  { background:#1a0000; border:1px solid #dc2626; color:#f87171;
  padding:0.15rem 0.6rem; border-radius:20px; font-size:0.75rem; font-weight:600; }

/* ── Table type chips in multiselect area ──────────────────────────── */
.tbl-fact { color:#fbbf24; }
.tbl-dim  { color:#34d399; }

/* ── Context table chips ───────────────────────────────────────────── */
.ctx-chip {
  display:inline-flex; align-items:center; gap:0.4rem;
  background:#0f2942; border:1px solid #3b82f6; border-radius:20px;
  padding:0.2rem 0.75rem; font-size:0.8rem; color:#93c5fd;
  margin:0.2rem 0.2rem 0.2rem 0;
}

/* ── Main header ───────────────────────────────────────────────────── */
.app-header {
  background: linear-gradient(135deg, #0a0e1a 0%, #0f2942 60%, #1a1a2e 100%);
  border: 1px solid #3b82f6;
  border-radius: 12px;
  padding: 1.2rem 1.8rem;
  margin-bottom: 1rem;
}
.app-header h1 {
  margin: 0; font-size: 1.6rem;
  background: linear-gradient(90deg,#3b82f6,#8b5cf6,#06b6d4);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
}
.app-header p { color:#94a3b8; margin:0.25rem 0 0 0; font-size:0.85rem; }

/* ── Context bar ───────────────────────────────────────────────────── */
.context-bar {
  background:#0f2942; border:1px solid #1e3a5f; border-radius:8px;
  padding:0.5rem 0.9rem; margin-bottom:0.8rem;
  font-size:0.82rem; color:#94a3b8;
}
.context-bar strong { color:#60a5fa; }

/* ── Quick prompt buttons ──────────────────────────────────────────── */
div[data-testid="stHorizontalBlock"] button[kind="secondary"] {
  font-size: 0.8rem !important;
  padding: 0.3rem 0.6rem !important;
}

/* ── Chat messages ─────────────────────────────────────────────────── */
[data-testid="stChatMessage"] { border-radius: 10px; }

/* ── Mermaid iframe ────────────────────────────────────────────────── */
iframe { border-radius: 10px; }

/* ── Remove default top padding on sidebar ─────────────────────────── */
[data-testid="stSidebarContent"] { padding-top: 1rem; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

_DEFAULTS: dict[str, Any] = {
    "messages": [{"role": "assistant", "content": INITIAL_GREETING}],
    "selected_tables": {},       # full_name → detail dict
    "db_client": None,
    "connected": False,
    "current_user": "",
    "catalogs": [],
    "catalog_tree": {},          # catalog → {schema → [table_dicts]}
    "table_detail_cache": {},    # full_name → detail dict
    "last_diagram": None,
    "generated_doc": None,
    "anthropic_key": os.getenv("ANTHROPIC_API_KEY", ""),
    "db_host": os.getenv("DATABRICKS_HOST", ""),
    "db_token": os.getenv("DATABRICKS_TOKEN", ""),
    "assistant": None,
    # cascade selector state
    "sel_catalog": None,
    "sel_schema": None,
}

for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_assistant() -> KimballAssistant | None:
    if not st.session_state.anthropic_key:
        return None
    if st.session_state.assistant is None:
        st.session_state.assistant = KimballAssistant(api_key=st.session_state.anthropic_key)
    return st.session_state.assistant


def connect_databricks(host: str, token: str) -> None:
    try:
        client = DatabricksClient(host=host, token=token)
        user = client.test_connection()
        st.session_state.db_client = client
        st.session_state.connected = True
        st.session_state.current_user = user
        st.session_state.catalogs = client.list_catalogs()
        st.session_state.catalog_tree = {}
        st.session_state.table_detail_cache = {}
        st.session_state.sel_catalog = None
        st.session_state.sel_schema = None
        st.toast(f"Connected as {user}", icon="✅")
    except Exception as exc:
        st.session_state.connected = False
        st.error(f"Connection failed: {exc}")


def get_schema_tree(catalog: str) -> dict[str, list[dict]]:
    """Return {schema: [tables]} — prefetch if not cached."""
    if catalog not in st.session_state.catalog_tree:
        client: DatabricksClient = st.session_state.db_client
        with st.spinner(f"Loading {catalog}…"):
            st.session_state.catalog_tree[catalog] = client.prefetch_catalog(catalog)
    return st.session_state.catalog_tree[catalog]


def add_tables_to_context(full_names: list[str]) -> int:
    """Add a list of tables to context; returns count actually added."""
    client: DatabricksClient = st.session_state.db_client
    missing = [n for n in full_names if n not in st.session_state.table_detail_cache]
    if missing:
        n = len(missing)
        label = f"Fetching {n} table schema{'s' if n > 1 else ''}…"
        with st.spinner(label):
            fetched = client.get_multiple_table_details(missing)
        st.session_state.table_detail_cache.update(fetched)
    added = 0
    for fn in full_names:
        if fn in st.session_state.table_detail_cache and fn not in st.session_state.selected_tables:
            st.session_state.selected_tables[fn] = st.session_state.table_detail_cache[fn]
            added += 1
    return added


def remove_table(full_name: str) -> None:
    st.session_state.selected_tables.pop(full_name, None)


# ---------------------------------------------------------------------------
# ── SIDEBAR ─────────────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

with st.sidebar:

    # Brand
    st.markdown("""
    <div class="sidebar-brand">
      <h2>🎯 Kimball Assistant</h2>
      <p>Unity Catalog → Star Schema → Power BI</p>
    </div>
    """, unsafe_allow_html=True)

    # ── Credentials ───────────────────────────────────────────────────────
    with st.expander("🔑 API Keys", expanded=not st.session_state.anthropic_key):
        new_key = st.text_input(
            "Anthropic API Key",
            value=st.session_state.anthropic_key,
            type="password",
            placeholder="sk-ant-...",
        )
        if new_key != st.session_state.anthropic_key:
            st.session_state.anthropic_key = new_key
            st.session_state.assistant = None

    # ── Databricks connection ─────────────────────────────────────────────
    with st.expander("☁️ Databricks Connection", expanded=not st.session_state.connected):
        db_host = st.text_input(
            "Workspace URL",
            value=st.session_state.db_host,
            placeholder="https://adb-xxx.azuredatabricks.net",
        )
        db_token = st.text_input(
            "Personal Access Token",
            value=st.session_state.db_token,
            type="password",
            placeholder="dapi...",
        )
        col_btn, col_status = st.columns([3, 2])
        with col_btn:
            if st.button("Connect", use_container_width=True, type="primary"):
                if db_host and db_token:
                    st.session_state.db_host = db_host
                    st.session_state.db_token = db_token
                    connect_databricks(db_host, db_token)
                else:
                    st.warning("Enter workspace URL and token.")
        with col_status:
            if st.session_state.connected:
                st.markdown('<span class="badge-live">● Live</span>', unsafe_allow_html=True)
                if st.session_state.current_user:
                    st.caption(st.session_state.current_user)
            else:
                st.markdown('<span class="badge-off">● Off</span>', unsafe_allow_html=True)

    st.divider()

    # ── Catalog Browser — cascade selector ───────────────────────────────
    if st.session_state.connected and st.session_state.catalogs:
        st.markdown('<div class="sec-label">🗂 Unity Catalog</div>', unsafe_allow_html=True)

        # ① Catalog picker
        catalog_options = st.session_state.catalogs
        sel_catalog = st.selectbox(
            "Catalog",
            options=["— select —"] + catalog_options,
            index=0 if st.session_state.sel_catalog is None
                  else (catalog_options.index(st.session_state.sel_catalog) + 1
                        if st.session_state.sel_catalog in catalog_options else 0),
            label_visibility="collapsed",
        )
        if sel_catalog == "— select —":
            sel_catalog = None
        if sel_catalog != st.session_state.sel_catalog:
            st.session_state.sel_catalog = sel_catalog
            st.session_state.sel_schema = None
            st.rerun()

        if sel_catalog:
            tree = get_schema_tree(sel_catalog)
            schema_options = sorted(tree.keys())

            if not schema_options:
                st.caption("No schemas found in this catalog.")
            else:
                # ② Schema picker
                sel_schema = st.selectbox(
                    "Schema",
                    options=["— select —"] + schema_options,
                    index=0 if st.session_state.sel_schema is None
                          else (schema_options.index(st.session_state.sel_schema) + 1
                                if st.session_state.sel_schema in schema_options else 0),
                    label_visibility="collapsed",
                )
                if sel_schema == "— select —":
                    sel_schema = None
                if sel_schema != st.session_state.sel_schema:
                    st.session_state.sel_schema = sel_schema
                    st.rerun()

                if sel_schema:
                    raw_tables = tree.get(sel_schema, [])

                    # ③ Table multiselect (has built-in search/filter)
                    def _label(t: dict) -> str:
                        icon = "📊" if "fact" in t["name"].lower() else (
                               "🔖" if any(x in t["name"].lower()
                                           for x in ("dim","dimension","lookup","ref"))
                               else "📋")
                        return f"{icon} {t['name']}"

                    table_labels = [_label(t) for t in raw_tables]
                    label_to_full = {_label(t): t["full_name"] for t in raw_tables}

                    already_in_ctx = {label_to_full[lbl]
                                      for lbl in table_labels
                                      if label_to_full[lbl] in st.session_state.selected_tables}
                    default_labels = [lbl for lbl in table_labels
                                      if label_to_full[lbl] in already_in_ctx]

                    chosen_labels = st.multiselect(
                        f"Tables in {sel_schema}",
                        options=table_labels,
                        default=default_labels,
                        placeholder="Search and select tables…",
                        label_visibility="collapsed",
                    )

                    chosen_full_names = [label_to_full[lbl] for lbl in chosen_labels]

                    col_add, col_info = st.columns([2, 1])
                    with col_add:
                        if st.button(
                            f"＋ Add {len(chosen_full_names)} table(s)",
                            use_container_width=True,
                            type="primary",
                            disabled=not chosen_full_names,
                        ):
                            n = add_tables_to_context(chosen_full_names)
                            st.toast(f"Added {n} table(s) to context", icon="✅")
                            st.rerun()
                    with col_info:
                        st.caption(f"{len(raw_tables)} total")

                    # Refresh cache button
                    if st.button("↺ Refresh schema", use_container_width=True):
                        client: DatabricksClient = st.session_state.db_client
                        with st.spinner("Refreshing…"):
                            st.session_state.catalog_tree[sel_catalog] = (
                                client.prefetch_catalog(sel_catalog)
                            )
                        st.rerun()

    elif st.session_state.connected and not st.session_state.catalogs:
        st.info("No catalogs visible with this token.")

    st.divider()

    # ── Modeling Context ───────────────────────────────────────────────────
    st.markdown('<div class="sec-label">🎯 Modeling Context</div>', unsafe_allow_html=True)

    sel = st.session_state.selected_tables
    if not sel:
        st.caption("No tables added yet. Select tables above and click **＋ Add**.")
    else:
        # Render chips
        chips_html = "".join(
            f'<span class="ctx-chip">📋 {fn.split(".")[-1]}</span>'
            for fn in sel
        )
        st.markdown(chips_html, unsafe_allow_html=True)
        st.caption(f"{len(sel)} table(s) · click × to remove")

        # Remove individual tables
        for full_name in list(sel.keys()):
            short = full_name.split(".")[-1]
            col_name, col_x = st.columns([5, 1])
            with col_name:
                st.caption(f"`{short}`")
            with col_x:
                if st.button("×", key=f"rm_{full_name}"):
                    remove_table(full_name)
                    st.rerun()

        st.divider()

        if st.button(
            "🔍 Analyze Selected Tables",
            use_container_width=True,
            type="primary",
            disabled=not st.session_state.anthropic_key,
        ):
            schema_block = DatabricksClient.format_multiple_schemas(sel)
            user_msg = build_table_context_message(schema_block)
            st.session_state.messages.append({"role": "user", "content": user_msg})
            st.rerun()

        if st.button("Clear All", use_container_width=True):
            st.session_state.selected_tables = {}
            st.rerun()

    # ── Model stats (when diagram exists) ─────────────────────────────────
    if st.session_state.last_diagram:
        st.divider()
        diag = st.session_state.last_diagram
        n_tables = diag.count("{")
        n_rels = diag.count("||") // 2
        c1, c2 = st.columns(2)
        with c1:
            st.metric("Tables", n_tables)
        with c2:
            st.metric("Relations", n_rels)

# ---------------------------------------------------------------------------
# ── MAIN ─────────────────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

st.markdown("""
<div class="app-header">
  <h1>🎯 Kimball Dimensional Modeling Assistant</h1>
  <p>Unity Catalog → Star Schema Design → Power BI Semantic Model &nbsp;·&nbsp; Powered by Claude</p>
</div>
""", unsafe_allow_html=True)

tab_chat, tab_diagram, tab_doc, tab_export = st.tabs([
    "💬 Assistant", "📐 Star Schema", "📄 Documentation", "📦 Export"
])

# ============================================================
# TAB 1 — CHAT
# ============================================================

with tab_chat:
    # Context bar
    if st.session_state.selected_tables:
        names_str = "  ·  ".join(
            f"`{fn.split('.')[-1]}`" for fn in st.session_state.selected_tables
        )
        st.markdown(
            f'<div class="context-bar">📋 Context: <strong>{names_str}</strong></div>',
            unsafe_allow_html=True,
        )

    # Render conversation
    for msg in st.session_state.messages:
        avatar = "🎯" if msg["role"] == "assistant" else "👤"
        with st.chat_message(msg["role"], avatar=avatar):
            st.markdown(msg["content"])

    # Chat input
    if not st.session_state.anthropic_key:
        st.warning("⚠️ Add your Anthropic API key in the sidebar **API Keys** section.")

    user_input = st.chat_input(
        "Ask about your data model, Kimball patterns, SCD types, DAX measures…",
        disabled=not st.session_state.anthropic_key,
    )

    if user_input:
        st.session_state.messages.append({"role": "user", "content": user_input})
        with st.chat_message("user", avatar="👤"):
            st.markdown(user_input)

        assistant = get_assistant()
        if assistant:
            with st.chat_message("assistant", avatar="🎯"):
                placeholder = st.empty()
                full_response = ""
                try:
                    for chunk in assistant.stream_response(st.session_state.messages):
                        full_response += chunk
                        placeholder.markdown(full_response + "▌")
                    placeholder.markdown(full_response)
                except Exception as exc:
                    full_response = f"❌ {exc}"
                    placeholder.error(full_response)

            st.session_state.messages.append(
                {"role": "assistant", "content": full_response}
            )
            diagram = extract_last_mermaid(full_response)
            if diagram:
                st.session_state.last_diagram = diagram
                st.session_state.generated_doc = None
            st.rerun()

    # Quick prompts
    st.divider()
    st.caption("Quick prompts")
    QUICK: list[tuple[str, str]] = [
        ("🏗️ Star Schema",
         "Design a complete Kimball star schema for the selected tables. Include all facts, dimensions, grain, and SCD types."),
        ("📅 Date Dimension",
         "Design a best-practice date dimension — calendar, fiscal, holiday, relative date flags. Show full column list."),
        ("📊 DAX Measures",
         "Generate a DAX starter kit — totals, ratios, YTD, MTD, prior period, YoY growth, and safe division pattern."),
        ("🔗 PBI Relationships",
         "Describe every Power BI relationship — table, column, cardinality, and filter direction for each."),
        ("🔄 SCD Analysis",
         "For each dimension, recommend SCD type (1/2/3/6) with business justification and the columns needed."),
        ("⚠️ Data Quality",
         "List data quality risks: nullable FKs, missing unknown members, partition strategy, skew risks."),
    ]
    cols = st.columns(3)
    for i, (label, prompt) in enumerate(QUICK):
        with cols[i % 3]:
            if st.button(label, use_container_width=True, key=f"q{i}"):
                st.session_state.messages.append({"role": "user", "content": prompt})
                st.rerun()

# ============================================================
# TAB 2 — STAR SCHEMA DIAGRAM
# ============================================================

with tab_diagram:
    if not st.session_state.last_diagram:
        st.info("💡 No diagram yet. Use the Assistant to design a star schema — the Mermaid ER diagram renders here automatically.")

        st.markdown("### Example — Retail Star Schema")
        example = """erDiagram
    FACT_SALES {
        int sale_key PK
        int date_key FK
        int customer_key FK
        int product_key FK
        int store_key FK
        decimal extended_price
        decimal discount_amount
        decimal net_sales_amount
        int quantity_sold
    }
    DIM_DATE {
        int date_key PK
        date full_date
        int year
        int quarter
        int month
        string month_name
        string day_of_week
        boolean is_weekend
        boolean is_holiday
        int fiscal_year
        int fiscal_period
    }
    DIM_CUSTOMER {
        int customer_key PK
        string customer_id NK
        string first_name
        string last_name
        string city
        string state
        date effective_date
        date expiry_date
        boolean is_current
    }
    DIM_PRODUCT {
        int product_key PK
        string product_id NK
        string product_name
        string brand
        string category
        decimal unit_price
        date effective_date
        boolean is_current
    }
    DIM_STORE {
        int store_key PK
        string store_id NK
        string store_name
        string city
        string state
    }
    FACT_SALES }o--|| DIM_DATE : "sold on"
    FACT_SALES }o--|| DIM_CUSTOMER : "sold to"
    FACT_SALES }o--|| DIM_PRODUCT : "product"
    FACT_SALES }o--|| DIM_STORE : "at store"
"""
        st.components.v1.html(mermaid_to_html(example), height=580, scrolling=True)
    else:
        col_hdr, col_regen = st.columns([4, 1])
        with col_hdr:
            st.markdown("### Generated Star Schema")
        with col_regen:
            if st.button("↺ Regenerate"):
                st.session_state.messages.append({
                    "role": "user",
                    "content": "Please regenerate the Mermaid erDiagram for the current model, ensuring all tables and relationships are included."
                })
                st.rerun()

        st.components.v1.html(
            mermaid_to_html(st.session_state.last_diagram),
            height=660, scrolling=True,
        )

        with st.expander("✏️ Edit Diagram Code"):
            edited = st.text_area(
                "Mermaid erDiagram",
                value=st.session_state.last_diagram,
                height=280,
                label_visibility="collapsed",
            )
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Apply", type="primary"):
                    st.session_state.last_diagram = edited
                    st.rerun()
            with c2:
                st.download_button(
                    "⬇️ .mmd",
                    data=st.session_state.last_diagram,
                    file_name="star_schema.mmd",
                    mime="text/plain",
                )

        st.divider()
        if st.button("📊 Generate Bus Matrix"):
            st.session_state.messages.append({
                "role": "user",
                "content": (
                    "Generate a Kimball Enterprise Data Warehouse Bus Matrix in markdown table format. "
                    "Rows = business processes (fact tables), Columns = conformed dimensions. "
                    "Mark shared dimensions ✓ and process-specific ones with a dot."
                )
            })
            st.rerun()

# ============================================================
# TAB 3 — DOCUMENTATION
# ============================================================

with tab_doc:
    st.markdown("### 📄 Model Design Document")

    if len(st.session_state.messages) <= 1:
        st.info("Start a conversation in the Assistant tab, then generate documentation here.")
    else:
        c1, c2 = st.columns([3, 1])
        with c1:
            if st.button(
                "📝 Generate Full Documentation",
                type="primary",
                disabled=not st.session_state.anthropic_key,
            ):
                assistant = get_assistant()
                if assistant:
                    with st.status("Generating comprehensive design document…", expanded=True) as status:
                        st.write("Analyzing conversation history…")
                        prompt = build_export_prompt(st.session_state.messages)
                        try:
                            doc = assistant.one_shot(prompt, max_tokens=8096)
                            st.session_state.generated_doc = doc
                            status.update(label="Done!", state="complete")
                        except Exception as exc:
                            status.update(label=f"Failed: {exc}", state="error")
        with c2:
            if st.session_state.generated_doc:
                st.download_button(
                    "⬇️ .md",
                    data=st.session_state.generated_doc,
                    file_name="kimball_model_design.md",
                    mime="text/markdown",
                    use_container_width=True,
                )

        if st.session_state.generated_doc:
            st.divider()
            st.markdown(st.session_state.generated_doc)

# ============================================================
# TAB 4 — EXPORT
# ============================================================

with tab_export:
    st.markdown("### 📦 Export Artifacts")

    has_diag = bool(st.session_state.last_diagram)
    has_doc  = bool(st.session_state.generated_doc)
    has_conv = len(st.session_state.messages) > 1

    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Star Schema Diagram", "✅ Ready" if has_diag else "⏳ Pending")
    with c2:
        st.metric("Design Document", "✅ Ready" if has_doc else "⏳ Pending")
    with c3:
        st.metric("Conversation turns", max(0, len(st.session_state.messages) - 1))

    st.divider()

    st.markdown("#### 📐 Mermaid ER Diagram")
    if has_diag:
        st.code(st.session_state.last_diagram, language="text")
        st.download_button("⬇️ star_schema.mmd", data=st.session_state.last_diagram,
                           file_name="star_schema.mmd", mime="text/plain")
    else:
        st.caption("Generate a star schema in the Assistant tab first.")

    st.divider()

    st.markdown("#### ⚡ Power BI Model Skeleton (JSON)")
    st.caption("Tabular Editor / ALM Toolkit starting point.")
    if has_diag:
        pbi = generate_powerbi_model_skeleton(st.session_state.last_diagram)
        st.code(pbi, language="json")
        st.download_button("⬇️ model_skeleton.json", data=pbi,
                           file_name="model_skeleton.json", mime="application/json")
    else:
        st.caption("Requires a diagram first.")

    st.divider()

    st.markdown("#### 📄 Design Document")
    if has_doc:
        st.download_button("⬇️ kimball_model_design.md",
                           data=st.session_state.generated_doc,
                           file_name="kimball_model_design.md", mime="text/markdown")
    else:
        st.caption("Generate it in the Documentation tab.")

    st.divider()

    st.markdown("#### 💬 Full Conversation")
    if has_conv:
        lines = ["# Kimball Modeling Assistant — Session\n"]
        for msg in st.session_state.messages:
            role = "### 🎯 Assistant" if msg["role"] == "assistant" else "### 👤 You"
            lines.append(f"{role}\n\n{msg['content']}\n\n---\n")
        st.download_button("⬇️ modeling_session.md", data="\n".join(lines),
                           file_name="modeling_session.md", mime="text/markdown")

    st.divider()
    st.markdown("#### 🔄 Reset")
    if st.button("Reset Session", type="secondary"):
        st.session_state.messages = [{"role": "assistant", "content": INITIAL_GREETING}]
        st.session_state.selected_tables = {}
        st.session_state.last_diagram = None
        st.session_state.generated_doc = None
        st.rerun()
