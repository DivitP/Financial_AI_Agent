from flask import Flask, request, render_template_string, jsonify
import os
import sys
import threading
import time
import uuid
from typing import List, Dict, Any
from dotenv import load_dotenv

# Ensure project root is on sys.path for `main` import
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from main import run_research_and_fundamental_agents, run_technical_analysis_only, get_vectorstore, answer_question_with_rag
import markdown as md

load_dotenv()

app = Flask(__name__)

# Global storage for background tasks
background_tasks = {}

INDEX_HTML = """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Financial AI Agent</title>
    <style>
      body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, 'Helvetica Neue', Arial, sans-serif; margin: 2rem; }
      .container { max-width: 900px; margin: 0 auto; }
      textarea { width: 100%; height: 120px; }
      input[type=text] { width: 200px; padding: 0.4rem; }
      .btn { padding: 0.6rem 1rem; background: #0b6cff; color: white; border: none; border-radius: 6px; cursor: pointer; }
      .btn:disabled { background: #aaa; }
      .card { border: 1px solid #e5e7eb; border-radius: 8px; padding: 1rem; margin-top: 1rem; }
      .muted { color: #6b7280; }
      pre { white-space: pre-wrap; word-wrap: break-word; }
      img { max-width: 100%; border: 1px solid #e5e7eb; border-radius: 6px; }
      a { color: #0b6cff; }
      .report { line-height: 1.6; }
      .report h2 { margin-top: 0; }
      .report h3 { margin-top: 1rem; }
      .report ul { padding-left: 1.25rem; }
      .loading { 
        display: inline-block; 
        width: 20px; 
        height: 20px; 
        border: 3px solid #f3f3f3; 
        border-top: 3px solid #0b6cff; 
        border-radius: 50%; 
        animation: spin 1s linear infinite; 
        margin-right: 10px;
      }
      @keyframes spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
      }
      .status-bar {
        background: #f8f9fa;
        border: 1px solid #e5e7eb;
        border-radius: 6px;
        padding: 0.75rem;
        margin: 1rem 0;
        display: flex;
        align-items: center;
        justify-content: space-between;
      }
      .charts-container {
        margin-top: 1rem;
        padding: 1rem;
        border: 1px solid #e5e7eb;
        border-radius: 8px;
        background: #fafafa;
      }
    </style>
    <script>
      let currentTaskId = null;
      let chartCheckInterval = null;

      document.addEventListener('DOMContentLoaded', function() {
        const form = document.getElementById('askForm');
        if (form) {
          form.addEventListener('submit', async function(e) {
            e.preventDefault();
            const ticker = document.getElementById('tickerHidden').value;
            const question = document.getElementById('questionInput').value;
            const btn = document.getElementById('askBtn');
            const out = document.getElementById('answerContainer');
            if (!question.trim()) return;
            btn.disabled = true; out.innerHTML = 'Loading...';
            try {
              const res = await fetch('/api/ask', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ticker, question })
              });
              const data = await res.json();
              let html = '';
              if (data.answer) {
                html += '<div class="answer">' + (data.answer || '') + '</div>';
              }
              if (data.sources && data.sources.length) {
                html += '<div class="muted"><strong>Cited Sources</strong><ul>';
                for (const s of data.sources) { html += '<li><a href="' + s + '" target="_blank">' + s + '</a></li>'; }
                html += '</ul></div>';
              }
              out.innerHTML = html || 'No answer.';
            } catch (err) {
              out.textContent = 'Error: ' + err;
            } finally {
              btn.disabled = false;
            }
          });
        }

        // Check for chart updates if we have a task ID
        if (currentTaskId) {
          startChartPolling();
        }
      });

      function startChartPolling() {
        if (chartCheckInterval) {
          clearInterval(chartCheckInterval);
        }
        
        chartCheckInterval = setInterval(async () => {
          if (!currentTaskId) return;
          
          try {
            const response = await fetch(`/api/chart-status/${currentTaskId}`);
            const data = await response.json();
            
            if (data.status === 'completed') {
              clearInterval(chartCheckInterval);
              chartCheckInterval = null;
              
              // Update the charts section
              const chartsContainer = document.getElementById('chartsContainer');
              if (chartsContainer) {
                let chartsHtml = '<h3>Technical Analysis</h3>';
                if (data.tech_image) {
                  chartsHtml += '<img src="data:image/png;base64,' + data.tech_image + '" />';
                }
                if (data.forecast_image) {
                  chartsHtml += '<h3>Forecast</h3><img src="data:image/png;base64,' + data.forecast_image + '" />';
                }
                chartsContainer.innerHTML = chartsHtml;
              }
              
              // Update status
              const statusBar = document.getElementById('statusBar');
              if (statusBar) {
                statusBar.innerHTML = '<span>✅ Charts loaded successfully!</span>';
              }
            } else if (data.status === 'failed') {
              clearInterval(chartCheckInterval);
              chartCheckInterval = null;
              
              const statusBar = document.getElementById('statusBar');
              if (statusBar) {
                statusBar.innerHTML = '<span>❌ Failed to load charts: ' + (data.error || 'Unknown error') + '</span>';
              }
            }
          } catch (err) {
            console.error('Error checking chart status:', err);
          }
        }, 2000); // Check every 2 seconds
      }

      function setCurrentTaskId(taskId) {
        currentTaskId = taskId;
        if (taskId) {
          startChartPolling();
        }
      }
    </script>
  </head>
  <body>
    <div class="container">
      <h1>Financial AI Agent</h1>
      <p class="muted">Enter a stock or ETF ticker to generate a report, then ask follow-up questions via RAG.</p>

      <form method="POST" action="/run">
        <label>Ticker</label>
        <input type="text" name="ticker" value="" />
        <button class="btn" type="submit">Generate Report</button>
      </form>

      {% if report %}
        <div class="card">
          <h2>Report</h2>
          <div class="report">{{ text_report_html | safe }}</div>

          {% if task_id %}
            <div id="statusBar" class="status-bar">
              <span><div class="loading"></div>Generating technical analysis charts...</span>
            </div>
            
            <div id="chartsContainer" class="charts-container">
              <p class="muted">Charts are being generated in the background. You can ask questions while waiting!</p>
            </div>
            
            <script>setCurrentTaskId('{{ task_id }}');</script>
          {% endif %}

          {% if tech_image %}
            <h3>Technical Analysis</h3>
            <img src="data:image/png;base64,{{ tech_image }}" />
          {% endif %}
          {% if forecast_image %}
            <h3>Forecast</h3>
            <img src="data:image/png;base64,{{ forecast_image }}" />
          {% endif %}
        </div>
      {% endif %}

      <div class="card">
        <h2>Ask follow-up</h2>
        <form id="askForm">
          <input id="tickerHidden" type="hidden" name="ticker" value="{{ ticker or '' }}" />
          <label>Your question</label>
          <textarea id="questionInput" name="question" placeholder="e.g., How are analyst estimates trending?"></textarea>
          <button id="askBtn" class="btn" type="submit">Search Knowledge Base</button>
        </form>
        <div id="answerContainer" class="card" style="margin-top: 1rem;"></div>
      </div>

      {% if answer %}
        <div class="card">
          <h2>Answer</h2>
          <pre>{{ answer }}</pre>
          {% if sources %}
            <div class="muted">
              <strong>Cited Sources</strong>
              <ul>
                {% for s in sources %}
                  <li><a href="{{ s }}" target="_blank">{{ s }}</a></li>
                {% endfor %}
              </ul>
            </div>
          {% endif %}
        </div>
      {% endif %}
    </div>
  </body>
  </html>
"""


@app.route("/", methods=["GET"]) 
def index():
    return render_template_string(INDEX_HTML)


def _extract_images(text: str):
    import re
    if not text:
        return text, None, None
    pattern = re.compile(r"<<IMAGE:(?P<tag>[A-Z_]+)>>(?P<b64>.*?)<<END_IMAGE>>", re.DOTALL)
    tech_image = None
    forecast_image = None
    def repl(m):
        nonlocal tech_image, forecast_image
        tag = m.group('tag')
        b64 = m.group('b64').strip()
        if tag == 'TECH_ANALYSIS':
            tech_image = b64
        elif tag == 'FORECAST':
            forecast_image = b64
        return ''
    cleaned = pattern.sub(repl, text)
    return cleaned.strip(), tech_image, forecast_image


def run_technical_analysis_background(task_id: str, ticker: str, persist_dir: str):
    """Run technical analysis in background thread"""
    try:
        # Run technical analysis
        tech_result = run_technical_analysis_only(ticker, persist_dir)
        
        # Extract images from the technical result
        tech_text, tech_image, forecast_image = _extract_images(tech_result["tech_result"].content)
        
        # Store results
        background_tasks[task_id] = {
            'status': 'completed',
            'tech_image': tech_image,
            'forecast_image': forecast_image,
            'tech_text': tech_text
        }
        
    except Exception as e:
        background_tasks[task_id] = {
            'status': 'failed',
            'error': str(e)
        }


@app.route("/run", methods=["POST"]) 
def run_agents():
    ticker = (request.form.get("ticker") or "").strip().upper()
    if not ticker:
        return render_template_string(INDEX_HTML, report="Please provide a ticker.")
    
    # Run research and fundamental agents first (fast)
    out = run_research_and_fundamental_agents(ticker, os.getenv("PERSIST_DIR", "./chroma_db"))
    
    # Convert markdown to HTML for immediate display
    text_report_html = md.markdown(out["report_md"] or "")
    
    # Generate task ID for background processing
    task_id = str(uuid.uuid4())
    
    # Start technical analysis in background
    background_tasks[task_id] = {'status': 'processing'}
    thread = threading.Thread(
        target=run_technical_analysis_background,
        args=(task_id, ticker, os.getenv("PERSIST_DIR", "./chroma_db"))
    )
    thread.daemon = True
    thread.start()
    
    return render_template_string(
        INDEX_HTML,
        report=True,
        text_report_html=text_report_html,
        ticker=ticker,
        task_id=task_id
    )


@app.route("/ask", methods=["POST"]) 
def ask():
    ticker = (request.form.get("ticker") or "").strip().upper()
    question = (request.form.get("question") or "").strip()
    if not question:
        return render_template_string(INDEX_HTML, report=None, ticker=ticker, answer="Please enter a question.")

    vs = get_vectorstore(os.getenv("PERSIST_DIR", "./chroma_db"))
    rag = answer_question_with_rag(vs, ticker, question, k=6)
    return render_template_string(INDEX_HTML, report=None, ticker=ticker, answer=rag["answer"], sources=rag.get("sources", []))


@app.route('/api/ask', methods=['POST'])
def api_ask():
    data = request.get_json(force=True) or {}
    ticker = (data.get('ticker') or '').strip().upper()
    question = (data.get('question') or '').strip()
    if not question:
        return jsonify({"error": "Missing question"}), 400
    vs = get_vectorstore(os.getenv("PERSIST_DIR", "./chroma_db"))
    rag = answer_question_with_rag(vs, ticker, question, k=6)
    return jsonify({
        "answer": rag.get("answer", ""),
        "sources": rag.get("sources", [])
    })


@app.route('/api/chart-status/<task_id>', methods=['GET'])
def chart_status(task_id):
    if task_id not in background_tasks:
        return jsonify({"error": "Task not found"}), 404
    
    return jsonify(background_tasks[task_id])


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8501)), debug=True)

