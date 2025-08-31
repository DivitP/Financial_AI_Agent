from flask import Flask, request, render_template_string, jsonify
import os
import sys
import threading
import time
import uuid
from typing import Dict, List, Tuple, Optional
from dotenv import load_dotenv
import base64
from datetime import datetime

# Ensure project root is on sys.path for `main` import
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from main import run_research_and_fundamental_agents, get_vectorstore, answer_question_with_rag, upsert_results_to_vectorstore
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
      img { max-width: 100%; border: 1px solid #e5e7eb; border-radius: 6px; margin-bottom: 1rem; }
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
      .chart-section {
        margin-bottom: 2rem;
        padding: 1rem;
        background: white;
        border-radius: 6px;
        border: 1px solid #ddd;
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
            
            console.log('Chart status update:', data); // Debug log
            
            // Update progress bar and status
            const statusBar = document.getElementById('statusBar');
            if (statusBar) {
              if (data.status === 'processing') {
                const progressPercent = data.progress || 0;
                const currentStep = data.current_step || 'Processing...';
                statusBar.innerHTML = `
                  <div style="width: 100%;">
                    <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
                      <span><div class="loading"></div>${currentStep}</span>
                      <span>${progressPercent}%</span>
                    </div>
                    <div style="width: 100%; background: #e5e7eb; border-radius: 4px; height: 8px;">
                      <div style="width: ${progressPercent}%; background: #0b6cff; height: 8px; border-radius: 4px; transition: width 0.3s;"></div>
                    </div>
                  </div>
                `;
              } else if (data.status === 'completed') {
                clearInterval(chartCheckInterval);
                chartCheckInterval = null;
                
                // Update the charts section with detailed content
                const chartsContainer = document.getElementById('chartsContainer');
                if (chartsContainer) {
                  let chartsHtml = '<h3>Technical Analysis Results</h3>';
                  
                  // Add text analysis
                  if (data.tech_text) {
                    chartsHtml += '<div class="chart-section"><h4>Analysis Summary</h4><pre style="white-space: pre-wrap; font-family: monospace;">' + data.tech_text + '</pre></div>';
                  }
                  
                  // Add technical chart
                  if (data.tech_image) {
                    chartsHtml += '<div class="chart-section"><h4>Technical Chart</h4>';
                    chartsHtml += '<img src="data:image/png;base64,' + data.tech_image + '" style="max-width: 100%;" /></div>';
                  }
                  
                  // Add forecast chart
                  if (data.forecast_image) {
                    chartsHtml += '<div class="chart-section"><h4>Price Forecast</h4>';
                    chartsHtml += '<img src="data:image/png;base64,' + data.forecast_image + '" style="max-width: 100%;" /></div>';
                  }
                  
                  if (!data.tech_text && !data.tech_image && !data.forecast_image) {
                    chartsHtml += '<p class="muted">Technical analysis completed but no results available.</p>';
                  }
                  
                  chartsContainer.innerHTML = chartsHtml;
                }
                
                // Update status
                statusBar.innerHTML = '<span>✅ Technical analysis complete!</span>';
              } else if (data.status === 'failed') {
                clearInterval(chartCheckInterval);
                chartCheckInterval = null;
                
                const chartsContainer = document.getElementById('chartsContainer');
                if (chartsContainer) {
                  chartsContainer.innerHTML = '<p style="color: red;">Technical analysis failed: ' + (data.error || 'Unknown error') + '</p>';
                }
                
                statusBar.innerHTML = '<span>❌ Failed: ' + (data.error || 'Unknown error') + '</span>';
              }
            }
          } catch (err) {
            console.error('Error checking chart status:', err);
          }
        }, 1000);
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
              <div style="width: 100%;">
                <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
                  <span><div class="loading"></div>Initializing technical analysis...</span>
                  <span>0%</span>
                </div>
                <div style="width: 100%; background: #e5e7eb; border-radius: 4px; height: 8px;">
                  <div style="width: 0%; background: #0b6cff; height: 8px; border-radius: 4px; transition: width 0.3s;"></div>
                </div>
              </div>
            </div>
            
            <div id="chartsContainer" class="charts-container">
              <p class="muted">Technical analysis is running in the background. Charts and forecasts will appear here when ready!</p>
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

def run_optimized_technical_analysis(task_id: str, ticker: str, persist_dir: str):
    """Run optimized technical analysis with the UltraFastTechnicalAnalysisAgent"""
    try:
        background_tasks[task_id] = {
            'status': 'processing',
            'progress': 10,
            'current_step': 'Starting technical analysis...'
        }
        
        print(f"Starting technical analysis for {ticker}")
        
        # Import the ultra-fast analysis function directly
        try:
            background_tasks[task_id].update({
                'progress': 20,
                'current_step': 'Importing analysis module...'
            })
            
            # Import the run_ultra_fast_analysis function from the module
            from agents.ultra_fast_technical_agent import run_ultra_fast_analysis
            
            background_tasks[task_id].update({
                'progress': 40,
                'current_step': 'Running comprehensive analysis...'
            })
            
            # Run the full analysis which includes charts and forecasts
            result = run_ultra_fast_analysis(ticker)
            
            background_tasks[task_id].update({
                'progress': 80,
                'current_step': 'Processing results...'
            })
            
            # Extract results
            tech_text = result.get('text', '')
            tech_image = result.get('tech_image')
            forecast_image = result.get('forecast_image')
            
            print(f"Analysis completed - Text: {bool(tech_text)}, Tech Chart: {bool(tech_image)}, Forecast Chart: {bool(forecast_image)}")
            
            background_tasks[task_id].update({
                'progress': 90,
                'current_step': 'Updating knowledge base...'
            })
            
            # Update vectorstore with the analysis
            try:
                vs = get_vectorstore(persist_dir)
                from main import AgentResult
                result_obj = AgentResult(
                    name="technical", 
                    ticker=ticker, 
                    content=tech_text, 
                    sources=["https://finance.yahoo.com/"]
                )
                upsert_results_to_vectorstore(vs, [result_obj])
                print("Successfully updated vectorstore")
            except Exception as e:
                print(f"Vectorstore update failed: {e}")
            
            # Store final results
            background_tasks[task_id] = {
                'status': 'completed',
                'progress': 100,
                'current_step': 'Analysis complete!',
                'tech_image': tech_image,
                'forecast_image': forecast_image,
                'tech_text': tech_text
            }
            
            print(f"Technical analysis completed successfully for {ticker}")
            
        except ImportError as e:
            print(f"Import error for ultra_fast_technical_agent: {e}")
            # Fallback to simplified analysis
            background_tasks[task_id].update({
                'progress': 50,
                'current_step': 'Using simplified analysis (import failed)...'
            })
            
            fallback_result = ultra_simple_analysis(ticker)
            
            background_tasks[task_id] = {
                'status': 'completed',
                'progress': 100,
                'current_step': 'Simplified analysis complete!',
                'tech_image': None,
                'forecast_image': None,
                'tech_text': fallback_result['text']
            }
            
        except Exception as e:
            print(f"Analysis execution failed: {str(e)}")
            # Another fallback attempt
            background_tasks[task_id].update({
                'progress': 50,
                'current_step': 'Analysis failed, using fallback...'
            })
            
            fallback_result = ultra_simple_analysis(ticker)
            
            background_tasks[task_id] = {
                'status': 'completed',
                'progress': 100,
                'current_step': 'Fallback analysis complete!',
                'tech_image': None,
                'forecast_image': None,
                'tech_text': fallback_result['text']
            }
            
    except Exception as e:
        error_msg = str(e)
        print(f"Complete failure in technical analysis: {error_msg}")
        
        background_tasks[task_id] = {
            'status': 'failed',
            'progress': 0,
            'current_step': f'Analysis failed: {error_msg}',
            'tech_image': None,
            'forecast_image': None,
            'tech_text': f"Technical analysis unavailable: {error_msg}",
            'error': error_msg
        }

def ultra_simple_analysis(ticker: str) -> Dict:
    """Ultra-simple fallback analysis when everything else fails"""
    import yfinance as yf
    
    try:
        ticker_obj = yf.Ticker(ticker)
        data = ticker_obj.history(period="1mo", timeout=5)
        
        if data.empty:
            raise ValueError(f"No data for {ticker}")
        
        # Basic price info
        current_price = data['Close'].iloc[-1]
        price_change = data['Close'].iloc[-1] - data['Close'].iloc[-2] if len(data) > 1 else 0
        price_change_pct = (price_change / data['Close'].iloc[-2]) * 100 if len(data) > 1 and data['Close'].iloc[-2] != 0 else 0
        
        # Simple trend
        sma_5 = data['Close'].tail(5).mean()
        sma_20 = data['Close'].tail(20).mean() if len(data) >= 20 else data['Close'].mean()
        trend = "Bullish" if sma_5 > sma_20 else "Bearish"
        
        text = f"""ULTRA-SIMPLE TECHNICAL ANALYSIS - {ticker}
Current Price: ${current_price:.2f}
Daily Change: ${price_change:+.2f} ({price_change_pct:+.2f}%)
Short-term Trend: {trend}
Analysis Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Note: This is a minimal analysis due to system constraints."""
        
        return {
            'text': text.strip(),
            'tech_image': None,
            'forecast_image': None
        }
        
    except Exception as e:
        return {
            'text': f"Unable to perform technical analysis for {ticker}: {str(e)}",
            'tech_image': None,
            'forecast_image': None
        }

@app.route("/", methods=["GET"]) 
def index():
    return render_template_string(INDEX_HTML)

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
    
    # Start optimized technical analysis in background
    background_tasks[task_id] = {'status': 'processing'}
    thread = threading.Thread(
        target=run_optimized_technical_analysis,
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