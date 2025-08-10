import os
from textwrap import dedent
from datetime import datetime, timedelta
from dotenv import load_dotenv

from langchain_groq import ChatGroq
from langchain.agents import tool
from langchain.tools import Tool
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_community.tools import DuckDuckGoSearchRun
from newspaper import Article

load_dotenv()

llm = ChatGroq(temperature=0, model_name="llama3-70b-8192", api_key=os.getenv("GROQ_API_KEY"))

@tool
def search_web(query: str) -> str:
    """Search the web using DuckDuckGo for general queries and recent news."""
    try:
        search_tool = DuckDuckGoSearchRun()
        return search_tool.run(query)
    except Exception as e:
        return f"Error performing search: {e}"

@tool
def get_webpage_content(url: str) -> str:
    """A tool to get the full text content from a specific webpage URL."""
    try:
        article = Article(url)
        article.download()
        article.parse()
        return article.text
    except Exception as e:
        return f"Error fetching article from {url}: {e}"

tools = [search_web, get_webpage_content]

one_month_ago_str = (datetime.now().date() - timedelta(days=30)).isoformat()

system_message = dedent("""\
    You are an elite research analyst in the financial services domain, specializing in stock analysis.
    Your expertise encompasses:
    - Deep investigative financial research and analysis
    - Fact-checking and source verification
    - Data-driven reporting and visualization
    - Trend analysis and future predictions
    - Global context integration

    Follow these steps for a comprehensive financial report on a given stock:
    1. Research Phase
       - Search for recent news and articles about the company to gauge public sentiment. **All search queries must be restricted to the last month. Use a search syntax similar to this to filter your results: 'search term after:{}'**
       - Find and analyze recent analyst reports from reputable financial institutions, you may look at sources at most of 1 year old.
       - Research the company's official statements, press releases, and investor relations pages to determine short-term and long-term strategic goals. If you are unable to access a page to get its content, use the search_web tool to find the specific documents you need (e.g., search for 'Meta Q2 2025 earnings press release' instead of trying to scrape the investor relations page).
       - Look for updates on the company's progress towards those stated goals.
    2. Analysis Phase
       - Summarize the key findings and recommendations from articles and reports.
        - Current news headlines related to the company
       - Identify and articulate the company's short-term and long-term goals and evaluate their current progress.
       - Extract and verify critical information.
       - Cross-reference facts across multiple sources.
       - Identify emerging patterns and trends.
    3. Writing Phase
       - Structure your response as a clear, well-formatted report.
       - The report should be an extremely detailed analysis, not a brief summary. Each section should be comprehensive and well-supported by data.
        - The first section should be a summary of current events and news headlines related to the company from the past week.
       - Include relevant quotes and statistics.
       - **CRITICAL: Only include direct, verifiable sources found during the research. Do not invent or include hypothetical sources.** If you cannot find a source for a fact, do not include that fact.
       - Include direct links to all sources used to provide transparency and allow the user to verify the information at the bottom of the report.
    4. Quality Control
       - Verify all facts and attributions.
       - Ensure narrative flow and readability.
       - Add context where necessary.
       - Avoid making definitive predictions and instead, present potential implications and the reason you think they will occur.
""").format(one_month_ago_str)

prompt = ChatPromptTemplate.from_messages(
    [
        ("system", system_message),
        ("user", "{input}"),
        MessagesPlaceholder(variable_name="agent_scratchpad"),
    ]
)

agent = create_tool_calling_agent(llm, tools, prompt)
agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True, max_iterations=10)

def run_agent(user_prompt):
    print(f"Running agent for query: {user_prompt}\n")
    try:
        response = agent_executor.invoke({"input": user_prompt})
        report = response['output']
        
        print("\n" + "="*50)
        print("FINANCIAL REPORT")
        print("="*50 + "\n")
        print(report)
        print("\n" + "="*50 + "\n")
    except Exception as e:
        print(f"Error running agent: {e}")

if __name__ == "__main__":
    import sys
    ticker = (sys.argv[1] if len(sys.argv) > 1 else input("Enter ticker (e.g., AAPL): ").strip().upper() or "AAPL")
    run_agent(f"Provide an in-depth stock analysis of {ticker}")