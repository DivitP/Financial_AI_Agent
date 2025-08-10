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

...

## Setup

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

## License
MIT License
---
