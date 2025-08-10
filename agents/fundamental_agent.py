import os
import requests
import time
from textwrap import dedent
from datetime import datetime
import json
import yfinance as yf

from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from langchain.agents import create_tool_calling_agent, AgentExecutor
from dotenv import load_dotenv

load_dotenv()

groq_api_key = os.getenv("GROQ_API_KEY")
fmp_api_key = os.getenv("FMP_API_KEY")

llm = ChatGroq(temperature=0, groq_api_key=groq_api_key, model_name="llama3-70b-8192")

def fmp_request(endpoint, symbol, params=None):
    """Make request to FMP API"""
    if not fmp_api_key:
        return None
    
    base_url = "https://financialmodelingprep.com/api/v3"
    url = f"{base_url}/{endpoint}/{symbol}"
    
    default_params = {"apikey": fmp_api_key}
    if params:
        default_params.update(params)
    
    try:
        response = requests.get(url, params=default_params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            return data if data else None
        else:
            print(f"FMP API error: {response.status_code}")
    except Exception as e:
        print(f"FMP request failed: {e}")
    
    return None

@tool
def get_stock_quote(ticker: str) -> str:
    """Get real-time stock quote from Financial Modeling Prep"""
    print(f"📊 Getting quote for {ticker}...")
    
    data = fmp_request("quote", ticker)
    if not data or len(data) == 0:
        return f"Unable to fetch quote for {ticker}"
    
    quote = data[0]
    
    price = quote.get('price', 0)
    change = quote.get('change', 0)
    change_pct = quote.get('changesPercentage', 0)
    open_price = quote.get('open', 0)
    high = quote.get('dayHigh', 0)
    low = quote.get('dayLow', 0)
    volume = quote.get('volume', 0)
    market_cap = quote.get('marketCap', 0)
    
    if market_cap >= 1e12:
        market_cap_str = f"${market_cap/1e12:.2f}T"
    elif market_cap >= 1e9:
        market_cap_str = f"${market_cap/1e9:.2f}B"
    elif market_cap >= 1e6:
        market_cap_str = f"${market_cap/1e6:.2f}M"
    else:
        market_cap_str = f"${market_cap:,.0f}"
    
    return dedent(f"""
        Stock Quote for {ticker}:
        - Current Price: ${price:.2f}
        - Daily Change: ${change:.2f} ({change_pct:+.2f}%)
        - Day's Range: ${low:.2f} - ${high:.2f}
        - Opening Price: ${open_price:.2f}
        - Volume: {volume:,}
        - Market Cap: {market_cap_str}
    """).strip()

@tool
def get_key_metrics(ticker: str) -> str:
    """Get key financial metrics from Financial Modeling Prep"""
    print(f"Getting key metrics for {ticker}...")
    
    data = fmp_request("key-metrics-ttm", ticker)
    if not data or len(data) == 0:
        return f"Unable to fetch key metrics for {ticker}"
    
    metrics = data[0]
    
    pe_ratio = metrics.get('peRatioTTM', 'N/A')
    pb_ratio = metrics.get('pbRatioTTM', 'N/A')
    ps_ratio = metrics.get('psRatioTTM', 'N/A')
    roe = metrics.get('roeTTM', 'N/A')
    roa = metrics.get('roaTTM', 'N/A')
    debt_to_equity = metrics.get('debtToEquityTTM', 'N/A')
    current_ratio = metrics.get('currentRatioTTM', 'N/A')
    
    def format_metric(value):
        if value == 'N/A' or value is None:
            return 'N/A'
        try:
            if isinstance(value, (int, float)):
                return f"{value:.2f}"
            return str(value)
        except:
            return 'N/A'
    
    return dedent(f"""
        Key Financial Metrics for {ticker} (TTM):
        - P/E Ratio: {format_metric(pe_ratio)}
        - Price-to-Book: {format_metric(pb_ratio)}
        - Price-to-Sales: {format_metric(ps_ratio)}
        - Return on Equity: {format_metric(roe)}%
        - Return on Assets: {format_metric(roa)}%
        - Debt-to-Equity: {format_metric(debt_to_equity)}
        - Current Ratio: {format_metric(current_ratio)}
    """).strip()

@tool
def get_company_profile(ticker: str) -> str:
    """Get company profile from Financial Modeling Prep"""
    print(f"🏢 Getting company profile for {ticker}...")
    
    data = fmp_request("profile", ticker)
    if not data or len(data) == 0:
        return f"Unable to fetch company profile for {ticker}"
    
    profile = data[0]
    
    name = profile.get('companyName', 'N/A')
    sector = profile.get('sector', 'N/A')
    industry = profile.get('industry', 'N/A')
    country = profile.get('country', 'N/A')
    website = profile.get('website', 'N/A')
    description = profile.get('description', 'N/A')
    
    if description != 'N/A' and len(description) > 400:
        description = description[:400] + "..."
        
    return dedent(f"""
        Company Profile for {ticker}:
        - Name: {name}
        - Sector: {sector}
        - Industry: {industry}
        - Country: {country}
        - Website: {website}
        - Description: {description}
    """).strip()

@tool
def get_analyst_estimates(ticker: str) -> str:
    """Get analyst estimates using yfinance"""
    print(f"Getting analyst estimates for {ticker}...")
    
    try:
        stock = yf.Ticker(ticker)
        
        recommendations = stock.recommendations
        info = stock.info
        
        result_lines = [f"Analyst Estimates for {ticker}:"]
        
        if recommendations is not None and not recommendations.empty:
            latest_rec = recommendations.iloc[-1]
            result_lines.append(f"- Latest Recommendation Period: {latest_rec.name}")
            result_lines.append(f"- Strong Buy: {latest_rec.get('strongBuy', 'N/A')}")
            result_lines.append(f"- Buy: {latest_rec.get('buy', 'N/A')}")
            result_lines.append(f"- Hold: {latest_rec.get('hold', 'N/A')}")
            result_lines.append(f"- Sell: {latest_rec.get('sell', 'N/A')}")
            result_lines.append(f"- Strong Sell: {latest_rec.get('strongSell', 'N/A')}")
        
        if info:
            target_high = info.get('targetHighPrice')
            target_low = info.get('targetLowPrice')
            target_mean = info.get('targetMeanPrice')
            recommendation = info.get('recommendationMean')
            recommendation_key = info.get('recommendationKey')
            
            if target_mean:
                result_lines.append(f"- Target Mean Price: ${target_mean:.2f}")
            if target_high:
                result_lines.append(f"- Target High Price: ${target_high:.2f}")
            if target_low:
                result_lines.append(f"- Target Low Price: ${target_low:.2f}")
            if recommendation_key:
                result_lines.append(f"- Overall Recommendation: {recommendation_key.title()}")
            elif recommendation:
                rec_map = {1: "Strong Buy", 2: "Buy", 3: "Hold", 4: "Sell", 5: "Strong Sell"}
                rec_text = rec_map.get(round(recommendation), "N/A")
                result_lines.append(f"- Overall Recommendation: {rec_text} ({recommendation:.1f})")
        
        if len(result_lines) == 1:  
            result_lines.append("- No analyst estimates available")
            
        return "\n".join(result_lines)
        
    except Exception as e:
        print(f"yfinance analyst estimates error: {e}")
        return f"Unable to fetch analyst estimates for {ticker}"

@tool
def get_stock_news(ticker: str) -> str:
    """Get latest stock news using yfinance"""
    print(f"Getting news for {ticker}...")
    
    try:
        stock = yf.Ticker(ticker)
        news = stock.news
        
        if not news or len(news) == 0:
            return f"No recent news available for {ticker}"
        
        news_items = []
        for i, article in enumerate(news[:5], 1):  
            title = article.get('title', '')
            publisher = article.get('publisher', '')
            
            publish_time = (article.get('providerPublishTime') or 
                          article.get('publishTime') or 
                          article.get('timestamp'))
            
            if title:  
                if publish_time:
                    try:
                        pub_date = datetime.fromtimestamp(publish_time).strftime('%Y-%m-%d')
                    except:
                        pub_date = 'Recent'
                else:
                    pub_date = 'Recent'
                
                news_item = f"{i}. {title}"
                if publisher:
                    news_item += f" ({publisher})"
                news_item += f" - {pub_date}"
                
                news_items.append(news_item)
        
        if not news_items:
            return f" No readable news articles available for {ticker}"
        
        return f"Latest News for {ticker}:\n" + "\n".join(news_items)
        
    except Exception as e:
        print(f"yfinance news error: {e}")
        return f"Unable to fetch news for {ticker}"

@tool
def get_financial_ratios(ticker: str) -> str:
    """Get financial ratios from Financial Modeling Prep"""
    print(f"📊 Getting financial ratios for {ticker}...")
    
    data = fmp_request("ratios-ttm", ticker)
    if not data or len(data) == 0:
        return f"Unable to fetch financial ratios for {ticker}"
    
    ratios = data[0]
    
    current_ratio = ratios.get('currentRatio', 'N/A')
    quick_ratio = ratios.get('quickRatio', 'N/A')
    gross_profit_margin = ratios.get('grossProfitMargin', 'N/A')
    operating_profit_margin = ratios.get('operatingProfitMargin', 'N/A')
    net_profit_margin = ratios.get('netProfitMargin', 'N/A')
    dividend_yield = ratios.get('dividendYield', 'N/A')
    
    def format_percentage(value):
        if value == 'N/A' or value is None:
            return 'N/A'
        try:
            return f"{float(value)*100:.2f}%"
        except:
            return 'N/A'
    
    def format_ratio(value):
        if value == 'N/A' or value is None:
            return 'N/A'
        try:
            return f"{float(value):.2f}"
        except:
            return 'N/A'
    
    return dedent(f"""
        Financial Ratios for {ticker} (TTM):
        - Current Ratio: {format_ratio(current_ratio)}
        - Quick Ratio: {format_ratio(quick_ratio)}
        - Gross Profit Margin: {format_percentage(gross_profit_margin)}
        - Operating Profit Margin: {format_percentage(operating_profit_margin)}
        - Net Profit Margin: {format_percentage(net_profit_margin)}
        - Dividend Yield: {format_percentage(dividend_yield)}
    """).strip()

@tool
def get_yfinance_info(ticker: str) -> str:
    """Get a variety of financial information for a stock ticker from Yahoo Finance."""
    print(f"Getting detailed info for {ticker} from yfinance...")
    
    try:
        stock = yf.Ticker(ticker)
        data = stock.info
        
        if not data:
            return f"Unable to fetch detailed info for {ticker} from yfinance"
            
        def format_large_number(num):
            if isinstance(num, (int, float)):
                if abs(num) >= 1e12:
                    return f"${num/1e12:.2f}T"
                elif abs(num) >= 1e9:
                    return f"${num/1e9:.2f}B"
                elif abs(num) >= 1e6:
                    return f"${num/1e6:.2f}M"
                else:
                    return f"{num:,.2f}"
            return "N/A"
            
        def format_ratio(ratio):
            return f"{ratio:.2f}" if isinstance(ratio, (int, float)) else "N/A"

        result_lines = [f"Detailed Financial Information for {ticker}:"]
        
        result_lines.append(f"- Market Cap: {format_large_number(data.get('marketCap'))}")
        result_lines.append(f"- P/E Ratio: {format_ratio(data.get('trailingPE'))}")
        result_lines.append(f"- PEG Ratio: {format_ratio(data.get('pegRatio'))}")
        result_lines.append(f"- Price/Book: {format_ratio(data.get('priceToBook'))}")
        result_lines.append(f"- Revenue: {format_large_number(data.get('totalRevenue'))}")
        result_lines.append(f"- Net Income: {format_large_number(data.get('netIncomeToCommon'))}")
        result_lines.append(f"- Free Cash Flow: {format_large_number(data.get('freeCashflow'))}")
        result_lines.append(f"- Debt/Equity: {format_ratio(data.get('debtToEquity'))}")
        
        return "\n".join(result_lines)
    
    except Exception as e:
        print(f"yfinance detailed info error: {e}")
        return f"An error occurred while fetching detailed info for {ticker}."
        
instructions = dedent("""\
    You are a senior financial analyst providing comprehensive stock analysis using reliable financial data! 📊

    ANALYSIS FRAMEWORK:
    1. **Executive Summary** - Key investment highlights and current status
    2. **Stock Performance** - Current price action, volume, and market cap
    3. **Financial Health** - Key metrics, ratios, and profitability analysis  
    4. **Company Overview** - Business profile, sector, and competitive position
    5. **Market Sentiment** - Analyst estimates and recent news
    6. **Investment Outlook** - Risk assessment and forward-looking perspective

    PROFESSIONAL STANDARDS:
    - Present only verified, real-time data from Financial Modeling Prep API and yfinance
    - Use clear section headers and organized formatting
    - Provide context and interpretation for key metrics
    - Compare metrics to industry standards when relevant
    - Include both opportunities and risk factors
    - End with balanced, actionable insights
    - Always disclose data limitations or unavailable information

    DATA QUALITY ASSURANCE:
    - If any tool returns "Unable to fetch" or errors, acknowledge the limitation
    - Focus analysis on successfully retrieved data
    - Never interpolate or estimate missing values
    - Clearly distinguish between confirmed data and general industry knowledge
""")

prompt = ChatPromptTemplate.from_messages([
    ("system", instructions),
    ("placeholder", "{chat_history}"),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}"),
])

tools = [
    get_stock_quote,
    get_key_metrics,
    get_company_profile,
    get_analyst_estimates,
    get_stock_news,
    get_financial_ratios,
    get_yfinance_info
]

agent = create_tool_calling_agent(llm, tools, prompt)
agent_executor = AgentExecutor(
    agent=agent,
    tools=tools,
    verbose=True,
    max_iterations=10,
    early_stopping_method="generate"
)

if __name__ == "__main__":
    print("Financial Modeling Prep + yfinance Stock Analysis Agent")
    print("Professional-grade financial data")
    print("Real-time quotes, metrics, and analysis")
    print("-" * 60)

    try:
        ticker = input("Enter ticker (e.g., AAPL): ").strip().upper() or "AAPL"
        response = agent_executor.invoke({
            "input": f"Provide a comprehensive financial analysis of {ticker}. Include current stock performance, financial metrics, company profile, analyst estimates, recent news, and investment outlook."
        })

        print("\n" + "="*70)
        print(f"COMPREHENSIVE {ticker} FINANCIAL ANALYSIS")
        print("="*70)
        print(response["output"])
        print("="*70)

        print("\n" + "Data Sources: Financial Modeling Prep API + yfinance")
        print("Analysis generated:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    except Exception as e:
        print(f"Analysis failed: {str(e)}")