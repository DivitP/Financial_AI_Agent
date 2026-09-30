from flask import Flask, request, render_template, jsonify, session
from secrets import token_hex, compare_digest
from urllib.parse import urlsplit
from werkzeug.exceptions import HTTPException
from financial_ai.security import HEADERS, safe_link, sanitized_markdown, rejected_browser_request
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
from settings import get_settings

load_dotenv()

app = Flask(__name__)
settings = get_settings()
app.config.update(SECRET_KEY=token_hex(32), DEBUG=False, SESSION_COOKIE_HTTPONLY=True,
                  SESSION_COOKIE_SAMESITE="Strict", SESSION_COOKIE_SECURE=settings.app_environment == "production")
app.jinja_env.globals["safe_link"] = safe_link

@app.context_processor
def csrf_context():
    session.setdefault("csrf_token", token_hex(32))
    return {"csrf_token": session["csrf_token"]}

@app.before_request
def protect_requests():
    form = request.path in ("/run", "/ask") and request.method == "POST"
    method = "GET" if form else request.method
    if urlsplit(request.url).hostname not in settings.allowed_hosts or rejected_browser_request(method, request.headers, settings.allowed_browser_origins):
        return jsonify(error="Request forbidden"), 403
    if form and not compare_digest(session.get("csrf_token", "").encode(), request.form.get("csrf_token", "").encode()):
        return jsonify(error="Invalid form token"), 403
    if form and not session.get("csrf_token"):
        return jsonify(error="Missing form token"), 403

@app.after_request
def security_headers(response):
    response.headers.update(HEADERS)
    if request.is_secure:
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    return response

@app.errorhandler(HTTPException)
def safe_http_error(error):
    return jsonify(error=error.name), error.code

# Global storage for background tasks
background_tasks = {}

INDEX_HTML = 'index.html'

def run_optimized_technical_analysis(task_id: str, ticker: str, persist_dir: str):
    """Run comprehensive technical analysis with ARIMA, GARCH, and Bollinger Bands"""
    try:
        background_tasks[task_id] = {
            'status': 'processing',
            'progress': 5,
            'current_step': 'Starting advanced technical analysis...'
        }
        
        print(f"Starting comprehensive technical analysis for {ticker}")
        
        # Import the enhanced analysis function
        try:
            background_tasks[task_id].update({
                'progress': 15,
                'current_step': 'Importing enhanced analysis module...'
            })
            
            # Import the enhanced run_ultra_fast_analysis function
            from agents.ultra_fast_technical_agent import run_enhanced_analysis
            
            background_tasks[task_id].update({
                'progress': 30,
                'current_step': 'Running comprehensive analysis with ARIMA/GARCH...'
            })
            
            # Run the enhanced analysis which includes all charts
            result = run_enhanced_analysis(ticker)
            
            background_tasks[task_id].update({
                'progress': 70,
                'current_step': 'Processing all forecast models...'
            })
            
            # Extract all results
            tech_text = result.get('text', '')
            tech_image = result.get('tech_image')
            bollinger_image = result.get('bollinger_image')
            arima_image = result.get('arima_image')
            garch_image = result.get('garch_image')
            
            print(f"Enhanced analysis completed - Text: {bool(tech_text)}, Tech: {bool(tech_image)}, BB: {bool(bollinger_image)}, ARIMA: {bool(arima_image)}, GARCH: {bool(garch_image)}")
            
            background_tasks[task_id].update({
                'progress': 85,
                'current_step': 'Updating knowledge base...'
            })
            
            # Update vectorstore with the comprehensive analysis
            try:
                vs = get_vectorstore(persist_dir)
                from main import AgentResult
                result_obj = AgentResult(
                    name="advanced_technical", 
                    ticker=ticker, 
                    content=tech_text, 
                    sources=["https://finance.yahoo.com/", "ARIMA Model", "GARCH Model"]
                )
                upsert_results_to_vectorstore(vs, [result_obj])
                print("Successfully updated vectorstore with advanced analysis")
            except Exception as e:
                print(f"Vectorstore update failed: {e}")
            
            # Store final results with all charts
            background_tasks[task_id] = {
                'status': 'completed',
                'progress': 100,
                'current_step': 'Advanced analysis complete!',
                'tech_image': tech_image,
                'bollinger_image': bollinger_image,
                'arima_image': arima_image,
                'garch_image': garch_image,
                'tech_text': tech_text
            }
            
            print(f"Advanced technical analysis completed successfully for {ticker}")
            
        except ImportError as e:
            print(f"Import error for enhanced analysis: {e}")
            # Fallback to original analysis
            background_tasks[task_id].update({
                'progress': 50,
                'current_step': 'Using standard analysis (enhanced module not found)...'
            })
            
            fallback_result = ultra_simple_analysis(ticker)
            
            background_tasks[task_id] = {
                'status': 'completed',
                'progress': 100,
                'current_step': 'Standard analysis complete!',
                'tech_image': None,
                'bollinger_image': None,
                'arima_image': None,
                'garch_image': None,
                'tech_text': fallback_result['text']
            }
            
        except Exception as e:
            print(f"Enhanced analysis execution failed: {str(e)}")
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
                'bollinger_image': None,
                'arima_image': None,
                'garch_image': None,
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
            'bollinger_image': None,
            'arima_image': None,
            'garch_image': None,
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
        
        text = f"""SIMPLE TECHNICAL ANALYSIS - {ticker}
Current Price: ${current_price:.2f}
Daily Change: ${price_change:+.2f} ({price_change_pct:+.2f}%)
Short-term Trend: {trend}
Analysis Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Note: Enhanced analysis with ARIMA/GARCH models unavailable due to system constraints."""
        
        return {
            'text': text.strip(),
            'tech_image': None,
            'bollinger_image': None,
            'arima_image': None,
            'garch_image': None
        }
        
    except Exception as e:
        return {
            'text': f"Unable to perform technical analysis for {ticker}: {str(e)}",
            'tech_image': None,
            'bollinger_image': None,
            'arima_image': None,
            'garch_image': None
        }

@app.route("/", methods=["GET"]) 
def index():
    return render_template(INDEX_HTML)

@app.route("/run", methods=["POST"]) 
def run_agents():
    ticker = (request.form.get("ticker") or "").strip().upper()
    if not ticker:
        return render_template(INDEX_HTML, report="Please provide a ticker.")
    
    # Run research and fundamental agents first (fast)
    out = run_research_and_fundamental_agents(ticker, str(settings.persist_dir))
    
    # Convert markdown to HTML for immediate display
    text_report_html = sanitized_markdown(out["report_md"] or "")
    
    # Generate task ID for background processing
    task_id = str(uuid.uuid4())
    
    # Start enhanced technical analysis in background
    background_tasks[task_id] = {'status': 'processing'}
    thread = threading.Thread(
        target=run_optimized_technical_analysis,
        args=(task_id, ticker, str(settings.persist_dir))
    )
    thread.daemon = True
    thread.start()
    
    return render_template(
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
        return render_template(INDEX_HTML, report=None, ticker=ticker, answer="Please enter a question.")

    vs = get_vectorstore(str(settings.persist_dir))
    rag = answer_question_with_rag(vs, ticker, question, k=6)
    return render_template(INDEX_HTML, report=None, ticker=ticker, answer=rag["answer"], sources=rag.get("sources", []))

@app.route('/api/ask', methods=['POST'])
def api_ask():
    try:
        # Get JSON data with better error handling
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400
            
        ticker = (data.get('ticker') or '').strip().upper()
        question = (data.get('question') or '').strip()
        
        if not question:
            return jsonify({"error": "Missing question"}), 400
            
        if not ticker:
            return jsonify({"error": "Missing ticker"}), 400
        # Get vectorstore and perform RAG
        vs = get_vectorstore(str(settings.persist_dir))
        rag = answer_question_with_rag(vs, ticker, question, k=6)
        
        # Ensure we return valid JSON
        response_data = {
            "answer": rag.get("answer", "No answer available"),
            "sources": rag.get("sources", [])
        }
        
        print(f"API Ask Response: {len(response_data['answer'])} chars, {len(response_data['sources'])} sources")
        
        return jsonify(response_data)
        
    except Exception:
        return jsonify({"error": "Unable to answer the question."}), 500

@app.route('/api/chart-status/<task_id>', methods=['GET'])
def chart_status(task_id):
    if task_id not in background_tasks:
        return jsonify({"error": "Task not found"}), 404
    
    return jsonify(background_tasks[task_id])

if __name__ == "__main__":
    app.run(host=settings.host, port=settings.port, debug=False, use_reloader=False)
