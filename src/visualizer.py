"""
Visualizer — Mermaid diagram extraction/rendering and documentation utilities.
"""

from __future__ import annotations

import json
import re
from typing import Any


# ---------------------------------------------------------------------------
# Mermaid extraction
# ---------------------------------------------------------------------------

_MERMAID_RE = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
_CODE_RE = re.compile(r"```(?:\w+)?\s*\n(.*?)```", re.DOTALL)


def extract_mermaid_blocks(text: str) -> list[str]:
    """Return all mermaid code blocks found in *text* (without fences)."""
    return [m.group(1).strip() for m in _MERMAID_RE.finditer(text)]


def extract_last_mermaid(text: str) -> str | None:
    """Return the last mermaid block in *text*, or None."""
    blocks = extract_mermaid_blocks(text)
    return blocks[-1] if blocks else None


# ---------------------------------------------------------------------------
# Mermaid erDiagram sanitizer
# ---------------------------------------------------------------------------
# Mermaid v10 erDiagram grammar only accepts simple alphanumeric identifiers
# as attribute types (no parentheses, angle brackets, spaces, or colons).
# The NK keyword is also non-standard (only PK/FK/UK are valid).

_PARAM_TYPE_RE    = re.compile(r'\b([A-Za-z_]\w*)\s*\([^)]*\)')  # DECIMAL(18,2) → DECIMAL
_GENERIC_TYPE_RE  = re.compile(r'\b([A-Za-z_]\w*)\s*<[^>]+>')    # ARRAY<STRING> → ARRAY
_NOT_NULL_RE      = re.compile(r'\s+NOT\s+NULL', re.IGNORECASE)   # NOT NULL → (removed)
_COLON_IN_TYPE_RE = re.compile(r'(\s+\w+):(\w+)')                # field:TYPE → field TYPE
# Collapse accumulated over-quoting from previous buggy runs: ""NK"" / """NK""" → "NK"
_OVER_QUOTED_NK_RE = re.compile(r'"{2,}NK"{2,}')
# Attribute line: indent + type + name + optional key (PK/FK/UK/NK) + optional "comment"
_ATTR_LINE_RE = re.compile(
    r'^(\s+)(\S+)\s+(\S+)(?:\s+(PK|FK|UK|NK))?(?:\s+("[^"]*"))?(\s*)$'
)


def _fix_attr_line(line: str) -> str:
    """Normalise one erDiagram attribute line to be Mermaid v10–compatible.

    Rules derived from the v10 grammar (comment is only valid after a key):
    - NK key token  → replaced with UK (closest valid equivalent)
    - comment with no key → comment dropped (would cause parse error)
    - everything else → unchanged
    """
    m = _ATTR_LINE_RE.match(line)
    if not m:
        return line
    indent, typ, name, key, comment, trailing = m.groups()

    if key == 'NK':
        key = 'UK'  # NK is invalid; UK (Unique Key) is the nearest valid token

    if comment and not key:
        # A quoted comment with no preceding key is rejected by Mermaid v10.
        comment = None

    result = f"{indent}{typ} {name}"
    if key:
        result += f" {key}"
    if comment:
        result += f" {comment}"
    return result + trailing


def sanitize_erdiagram(diagram_code: str) -> str:
    """Strip constructs that Mermaid v10 erDiagram cannot parse."""
    lines = []
    for line in diagram_code.splitlines():
        line = _GENERIC_TYPE_RE.sub(r'\1', line)        # ARRAY<STRING>  → ARRAY
        line = _PARAM_TYPE_RE.sub(r'\1', line)          # DECIMAL(18,2)  → DECIMAL
        line = _NOT_NULL_RE.sub('', line)               # NOT NULL       → removed
        line = _COLON_IN_TYPE_RE.sub(r'\1 \2', line)    # field:TYPE    → field TYPE
        line = _OVER_QUOTED_NK_RE.sub('"NK"', line)     # ""NK"" → "NK" (prior-run fix)
        line = _fix_attr_line(line)                     # NK/comment     → valid form
        lines.append(line)
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Mermaid HTML renderer (embeds mermaid.js via CDN)
# ---------------------------------------------------------------------------

# Uses mermaid.render() API (not startOnLoad) so the diagram code is passed
# as a JSON-encoded JS string — immune to special characters — and errors are
# caught and shown as a readable message instead of the cryptic
# "Syntax error in text" that Mermaid surfaces through startOnLoad.
_MERMAID_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
  <style>
    body  { margin:0; padding:12px; background:#0e1117; display:flex; justify-content:center; }
    #erd  { max-width:100%; }
    .er.entityLabel { fill:#e2e8f0 !important; }
    .err  { color:#f87171; font-family:monospace; font-size:13px; white-space:pre-wrap; padding:8px; }
  </style>
</head>
<body>
  <div id="erd"></div>
  <script>
    mermaid.initialize({
      startOnLoad: false,
      theme: 'dark',
      themeVariables: {
        primaryColor: '#1e3a5f',
        primaryTextColor: '#e2e8f0',
        primaryBorderColor: '#3b82f6',
        lineColor: '#60a5fa',
        secondaryColor: '#0f2942',
        tertiaryColor: '#1a1a2e',
        background: '#0e1117',
        mainBkg: '#1e3a5f',
        nodeBorder: '#3b82f6',
        clusterBkg: '#0f2942',
        titleColor: '#e2e8f0',
        edgeLabelBackground: '#1a1a2e',
        attributeBackgroundColorEven: '#0f2942',
        attributeBackgroundColorOdd: '#1e3a5f',
      },
      er: {
        diagramPadding: 30,
        layoutDirection: 'LR',
        minEntityWidth: 100,
        minEntityHeight: 75,
        entityPadding: 15,
        useMaxWidth: true,
      },
      securityLevel: 'loose',
    });
    (async function () {
      const code = DIAGRAM_JSON;
      try {
        const { svg } = await mermaid.render('mermaid-erd', code);
        document.getElementById('erd').innerHTML = svg;
      } catch (err) {
        document.getElementById('erd').innerHTML =
          '<div class="err">⚠️ Could not render diagram:\\n\\n' +
          (err.message || String(err)) + '</div>';
      }
    })();
  </script>
</body>
</html>
"""


def mermaid_to_html(diagram_code: str) -> str:
    """Wrap Mermaid diagram code in a self-contained HTML page.

    The diagram is JSON-encoded so all special characters (angle brackets,
    backticks, curly braces, quotes) are safe inside the JS string literal.
    Rendering errors are caught and displayed rather than crashing silently.
    """
    clean = sanitize_erdiagram(diagram_code)
    # Final-pass nuclear strip: remove every variant of NK comment strings
    # (1–3 quotes on either side) that may have escaped per-line processing.
    # These are decorative-only; the UK key token already conveys uniqueness.
    clean = re.sub(r'"{1,3}NK"{1,3}', '', clean)
    diagram_json = json.dumps(clean)          # produces a valid JS string literal
    return _MERMAID_HTML_TEMPLATE.replace("DIAGRAM_JSON", diagram_json)


# ---------------------------------------------------------------------------
# Conversation → model document extraction
# ---------------------------------------------------------------------------

def extract_model_sections(conversation: list[dict]) -> dict[str, str]:
    """
    Scan assistant messages and extract key model design sections.

    Returns dict with optional keys:
      diagram, grain, relationships, measures, scd_types, powerbi_notes
    """
    full_text = "\n\n".join(
        m["content"] for m in conversation if m["role"] == "assistant"
    )

    result: dict[str, str] = {}

    # Last mermaid diagram
    diagram = extract_last_mermaid(full_text)
    if diagram:
        result["diagram"] = diagram

    return result


# ---------------------------------------------------------------------------
# Markdown documentation generator
# ---------------------------------------------------------------------------

_DOC_PROMPT_TEMPLATE = """Based on our conversation, generate a comprehensive Kimball Dimensional Model design document in Markdown.

Structure it as follows:

# Kimball Dimensional Model — [Business Process Name]

## Executive Summary
(2–3 sentences on what business questions this model answers)

## Business Process & Grain

### Fact Table(s)
For each fact table:
- **Table name**: `FACT_...`
- **Grain**: One row per ...
- **Type**: Transactional / Periodic Snapshot / Accumulating Snapshot
- **Measures**: list each metric with data type and aggregation behavior (additive/semi-additive/non-additive)

## Dimensions

For each dimension:
| Attribute | Type | SCD | Notes |
|-----------|------|-----|-------|

Include: SCD type with justification, natural key(s), surrogate key naming.

## Star Schema Relationships

| From | Cardinality | To | Join Key |
|------|-------------|-----|----------|

## Power BI Implementation Guide

### Model Settings
- Date table configuration
- Relationship directions (single vs bidirectional)
- Role-playing dimension setup

### DAX Measures (Starter Kit)
```dax
-- Paste ready-to-use DAX for each key metric
```

## Data Quality Checklist
- [ ] Surrogate keys on all dimensions
- [ ] Unknown members for nullable FKs
- [ ] Date dimension covers full date range
- [ ] Partition strategy for large fact tables

## Naming Conventions
Standard prefixes and conventions used in this model.
"""


def build_export_prompt(conversation: list[dict]) -> str:
    """Build the prompt to generate a full model document from conversation history."""
    history = "\n\n".join(
        f"{'USER' if m['role'] == 'user' else 'ASSISTANT'}: {m['content']}"
        for m in conversation
    )
    return f"Previous conversation:\n\n{history}\n\n---\n\n{_DOC_PROMPT_TEMPLATE}"


# ---------------------------------------------------------------------------
# Power BI model JSON skeleton
# ---------------------------------------------------------------------------

def generate_powerbi_model_skeleton(diagram_code: str) -> str:
    """
    Generate a minimal TMDL-style JSON skeleton from a mermaid erDiagram.
    This gives the Power BI developer a starting point.
    """
    tables: list[str] = []
    relationships: list[str] = []

    for line in diagram_code.splitlines():
        line = line.strip()
        # Table entity declarations
        if "{" in line and not line.startswith("erDiagram"):
            table_name = line.split("{")[0].strip()
            tables.append(table_name)
        # Relationships  e.g.  FACT }o--|| DIM : "label"
        if "}o--||" in line or "}|--||" in line or "}o--|{" in line:
            parts = re.split(r"\s+", line)
            if len(parts) >= 3:
                from_table = parts[0]
                to_table = parts[2]
                relationships.append(f'  // {from_table} → {to_table}')

    lines = [
        "{",
        '  "name": "SemanticModel",',
        '  "compatibilityLevel": 1605,',
        '  "model": {',
        '    "tables": [',
    ]
    for t in tables:
        lines.append(f'      {{ "name": "{t}", "columns": [] }},')
    lines.append("    ],")
    lines.append('    "relationships": [')
    for r in relationships:
        lines.append(r)
    lines.append("    ]")
    lines.append("  }")
    lines.append("}")

    return "\n".join(lines)
