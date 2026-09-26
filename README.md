# Multi-Agent Financial Analysis Platform

A Flask-based platform that uses multiple AI agents (fundamental, technical, research) to generate an investment report with technical charts, forecasts, and source-grounded Q\&A via a persistent vector knowledge base.

## Overview

The platform:

* Analyzes a user-provided stock/ETF ticker with three agents:

  * **Fundamental**: Financial metrics, ratios, and company data from FMP and yfinance.
  * **Technical**: Indicators, trading signals, forecasts, and PNG charts.
  * **Research**: Recent news, analyst reports, company goals, and sentiment.
* Stores all agent outputs and sources in a SQLite TF-IDF vector store.
* Supports follow-up Q\&A through a retrieval-augmented generation (RAG) pipeline.
* Serves results through a Flask frontend with AJAX-based Q\&A.


## Project Structure

```
Financial_AI_Agent/
├── agents/
│   ├── fundamental_agent.py
│   ├── search_agent.py
│   └── technical_analysis_agent.py (void - takes too long)
│   └── ultra_fast_technical_analysis_agent.py (currently using)
├── chroma_db/
│   └── vectorstore.db
├── frontend/
│   └── app.py
├── workflow/
│   └── agent_workflow.png
├── main.py
├── requirements.txt
├── README.md
└── .gitignore
```


## Setup

### Replacement API and React research workspace

The legacy Flask screen remains available while the replacement application is
being built. The new API runs without provider keys; data collection is added
only when a research workflow is executed.

```bash
uv run uvicorn financial_ai.api.app:create_app --factory --reload
cd frontend/web
npm install
npm run dev
```

Open the workspace at `http://localhost:5173`. It proxies `/api` requests to
the FastAPI server on port 8000. Run `npm run test`, `npm run lint`, and
`npm run build` from `frontend/web` to validate the client.

1. Clone the repository:

   ```
   git clone https://github.com/DivitP/Financial_AI_Agent.git
   cd Financial_AI_Agent
   ```

2. Create and activate a virtual environment:

   ```
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. Install dependencies:

   ```
   pip install -r requirements.txt
   pip install 'lxml[html_clean]'
   ```

4. Set environment variables:

   ```
   export GROQ_API_KEY=your_groq_api_key
   export FMP_API_KEY=your_fmp_api_key   # optional
   export PERSIST_DIR=./chroma_db        # optional
   ```

5. Run the application:

   ```
   python frontend/app.py
   ```

   Access via: [http://localhost:8501](http://localhost:8501)

## Usage

Saved report versions can be downloaded as **Markdown, JSON or PDF**, including
their evidence appendix, metadata and captured charts. See [exports](docs/exports.md).

**Calendar** aggregates cited events from saved watchlist research with source
dates, timezone offsets, and date-confidence labels. See [calendar](docs/calendar.md).

**Portfolio context** analyzes hypothetical weights and a candidate allocation
using saved data only. See [portfolio assumptions and limits](docs/portfolio-context.md).

Saved History includes **Changes since last run**, comparing eight research
areas with old/new evidence links and explicit coverage gaps.
See [saved-run comparisons](docs/delta.md).

The React **Watchlists** page saves multiple lists with ticker notes and tags.
Research status, retrieval ages, and upcoming earnings use saved data only;
opening a list never starts provider requests. See [watchlists](docs/watchlists.md).

For the React application, open **Saved research** to filter, name, archive, and
reopen stored report versions without refreshing their data. See
[saved research history](docs/history.md) for API details and legacy limitations.

1. Enter a ticker symbol in the form.
2. View the generated report with the following structure:
  * Executive Summary
  * Stock Performance
  * Financial Health
  * Company Overview
  * Market Sentiment
  * Investment Outlook
  * Technical Signals & Forecasts (with charts)
  * Sources (with links)
3. Ask follow-up questions via the Q\&A box for citation-backed answers.

## Error Handling

* API calls have timeouts and fallbacks.
* Missing keys degrade gracefully with notices.
* Charts render inline when available; text remains functional otherwise.
* Q\&A errors return user-readable messages.

## Future Plans

* Replace TF-IDF with ANN vector DB + embeddings.
* Cache agent outputs per ticker with TTL.
* Add more agents (e.g., earnings call summaries, competitor comparisons).
* Export to PDF with embedded charts.
* Add authentication and saved workspaces.
---
