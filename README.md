# Kimball Dimensional Modeling Assistant

A Streamlit app that connects to a Databricks Unity Catalog workspace, lets you browse and select tables, and uses Claude AI to design Kimball-style star schemas — complete with Mermaid ER diagrams, SCD recommendations, Power BI relationship definitions, and DAX measure templates.

## Features

- **Unity Catalog browser** — cascade selector (catalog → schema → table) with parallel metadata fetching
- **AI modeling assistant** — Claude-powered chat with a Kimball expert system prompt
- **Star schema diagrams** — auto-rendered Mermaid `erDiagram` output, editable in-app
- **Power BI export** — Tabular Editor–compatible JSON model skeleton
- **Design documentation** — generated markdown design doc, downloadable
- **Session export** — full conversation history as markdown

## Prerequisites

- Python 3.9+
- An [Anthropic API key](https://console.anthropic.com/)
- A Databricks workspace with Unity Catalog enabled and a Personal Access Token

## Setup

```bash
git clone https://github.com/vamanchi-kr/Data_modeling_Assistant.git
cd Data_modeling_Assistant
pip install -r requirements.txt
```

Create a `.env` file in the project root (never commit this):

```env
ANTHROPIC_API_KEY=sk-ant-...
DATABRICKS_HOST=https://adb-xxx.azuredatabricks.net
DATABRICKS_TOKEN=dapi...
```

## Running

```bash
python -m streamlit run app.py
```

Open [http://localhost:8501](http://localhost:8501) in your browser.

## Usage

1. **API Keys** — enter your Anthropic API key in the sidebar (pre-filled from `.env`)
2. **Databricks Connection** — enter your workspace URL and PAT, click **Connect**
3. **Browse tables** — select a catalog → schema → tables, click **＋ Add**
4. **Analyze** — click **Analyze Selected Tables** or type a question in the chat
5. **View diagram** — the **Star Schema** tab renders the Mermaid ER diagram automatically
6. **Export** — download the diagram (`.mmd`), Power BI skeleton (`.json`), or design doc (`.md`)

## Project Structure

```
app.py                        # Streamlit UI
src/
  kimball_assistant.py        # Claude API wrapper + Kimball system prompt
  databricks_client.py        # Unity Catalog browser (parallel fetching)
  visualizer.py               # Mermaid rendering + Power BI export helpers
requirements.txt
.streamlit/
  config.toml                 # Disables usage stats prompt
```

## Environment Variables

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic API key for Claude |
| `DATABRICKS_HOST` | Databricks workspace URL |
| `DATABRICKS_TOKEN` | Databricks Personal Access Token |

All three can also be entered directly in the sidebar at runtime.
