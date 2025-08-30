import os
import re
import json
import math
import sqlite3
from collections import Counter, defaultdict
from typing import List, Dict, Any, Iterable, Tuple, Set
from dataclasses import dataclass

from dotenv import load_dotenv

from agents.search_agent import agent_executor as search_agent_executor
from agents.fundamental_agent import agent_executor as fundamental_agent_executor
from agents.technical_analysis_agent import TechnicalAnalysisAgent
import base64

from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.documents import Document

load_dotenv()


@dataclass
class AgentResult:
    name: str
    ticker: str
    content: str
    sources: List[str]


def run_search_agent(ticker: str) -> AgentResult:
    prompt = f"Provide an in-depth stock analysis of {ticker}. Include only verifiable sources and list them explicitly at the end."
    response = search_agent_executor.invoke({"input": prompt})
    text: str = response.get("output", "")

    # Extract sources from the bottom if present as links
    sources: List[str] = []
    if text:
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        for line in lines[-20:]:
            if line.lower().startswith("http") or line.lower().startswith("- http"):
                url = line.split()[-1]
                sources.append(url)

    return AgentResult(name="research", ticker=ticker, content=text, sources=sources)


def run_fundamental_agent(ticker: str) -> AgentResult:
    # fundamental agent is a tool-calling agent; prompt it for a comprehensive analysis
    response = fundamental_agent_executor.invoke({
        "input": f"Provide a comprehensive financial analysis of {ticker}. Include quotes, key metrics, profile, analyst estimates, news, ratios, and yfinance info."
    })
    text: str = response.get("output", "")
    # Fundamental tools' sources are FMP and yfinance
    sources = [
        "https://financialmodelingprep.com/",
        "https://finance.yahoo.com/",
    ]
    return AgentResult(name="fundamental", ticker=ticker, content=text, sources=sources)


def run_technical_agent(ticker: str) -> AgentResult:
    agent = TechnicalAnalysisAgent(ticker, period="1y")
    agent.calculate_all_indicators()
    summary = agent.get_analysis_summary()

    # Render a concise textual report from summary
    lines = [
        f"TECHNICAL ANALYSIS REPORT - {summary['symbol']}",
        f"Current Price: ${summary['current_price']:.2f}",
        f"Daily Change: ${summary['daily_change']:+.2f} ({summary['daily_change_pct']:+.2f}%)",
        f"Volatility (ATR): {summary['volatility_atr']:.2f}",
        f"Volume Ratio: {summary['volume_ratio']:.2f}x avg",
        f"RSI: {summary['rsi']:.1f}",
        "",
        "Signals:",
    ]
    for k, v in summary["signals"].items():
        lines.append(f"- {k}: {v}")
    lines.extend([
        "",
        "Forecast:",
        f"- Trend: {summary['forecast_trend']}",
        f"- Confidence: {summary['forecast_confidence']:.1%}",
        f"Analysis Date: {summary['analysis_date']}",
    ])
    # Generate charts as base64 PNGs
    try:
        tech_png = agent.generate_technical_analysis_png()
        tech_png_b64 = base64.b64encode(tech_png).decode("utf-8")
    except Exception:
        tech_png_b64 = ""

    try:
        forecast = agent.simple_forecast(days=30)
        forecast_png = agent.generate_forecast_png(forecast)
        forecast_png_b64 = base64.b64encode(forecast_png).decode("utf-8")
    except Exception:
        forecast_png_b64 = ""

    text = "\n".join(lines)
    # Append markers for frontend to parse images
    if tech_png_b64:
        text += f"\n\n<<IMAGE:TECH_ANALYSIS>>{tech_png_b64}<<END_IMAGE>>"
    if forecast_png_b64:
        text += f"\n\n<<IMAGE:FORECAST>>{forecast_png_b64}<<END_IMAGE>>"

    sources = ["https://finance.yahoo.com/"]
    return AgentResult(name="technical", ticker=ticker, content=text, sources=sources)


def get_embeddings():
    # Use fastembed (no torch/scipy) for easy install
    model_name = os.getenv("EMBEDDINGS_MODEL", "BAAI/bge-small-en-v1.5")
    return FastEmbedEmbeddings(model_name=model_name, cache_dir=os.path.join(os.getcwd(), ".embeddings_cache"))


class SimpleSQLiteVectorStore:
    """
    Lightweight TF-IDF vector store implemented on SQLite with on-the-fly TF-IDF.
    No external heavy deps; suitable for small corpora like agent outputs.
    """

    TOKEN_RE = re.compile(r"[a-z0-9]+")

    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    metadata TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS term_doc (
                    term TEXT NOT NULL,
                    doc_id TEXT NOT NULL,
                    count INTEGER NOT NULL,
                    PRIMARY KEY (term, doc_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS terms (
                    term TEXT PRIMARY KEY,
                    df INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS stats (
                    key TEXT PRIMARY KEY,
                    value INTEGER NOT NULL
                )
                """
            )
            # Initialize doc_count if missing
            cur = conn.execute("SELECT value FROM stats WHERE key='doc_count'")
            row = cur.fetchone()
            if row is None:
                conn.execute("INSERT INTO stats(key, value) VALUES ('doc_count', 0)")
            conn.commit()

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        return SimpleSQLiteVectorStore.TOKEN_RE.findall(text.lower())

    def _get_doc_count(self, conn: sqlite3.Connection) -> int:
        cur = conn.execute("SELECT value FROM stats WHERE key='doc_count'")
        value = cur.fetchone()[0]
        return int(value)

    def add_texts(self, texts: List[str], metadatas: List[Dict[str, Any]], ids: List[str]) -> None:
        with sqlite3.connect(self.db_path) as conn:
            doc_count = self._get_doc_count(conn)
            for text, meta, doc_id in zip(texts, metadatas, ids):
                # Upsert document
                conn.execute(
                    "INSERT OR REPLACE INTO documents(id, content, metadata) VALUES (?, ?, ?)",
                    (doc_id, text, json.dumps(meta)),
                )

                # Remove existing term rows for this doc
                conn.execute("DELETE FROM term_doc WHERE doc_id = ?", (doc_id,))

                tokens = self._tokenize(text)
                counts = Counter(tokens)

                # Insert term counts
                rows = [(term, doc_id, int(cnt)) for term, cnt in counts.items()]
                if rows:
                    conn.executemany(
                        "INSERT OR REPLACE INTO term_doc(term, doc_id, count) VALUES (?, ?, ?)", rows
                    )

                # Update document frequency for unique terms
                unique_terms: Set[str] = set(counts.keys())
                for term in unique_terms:
                    cur = conn.execute("SELECT df FROM terms WHERE term = ?", (term,))
                    trow = cur.fetchone()
                    if trow is None:
                        conn.execute("INSERT INTO terms(term, df) VALUES (?, ?)", (term, 1))
                    else:
                        conn.execute("UPDATE terms SET df = df + 1 WHERE term = ?", (term,))

                # Increment doc_count when adding new IDs; best-effort detect new vs replace
                # Here we assume all provided ids are new for simplicity
                doc_count += 1
                conn.execute("UPDATE stats SET value = ? WHERE key='doc_count'", (doc_count,))

            conn.commit()

    def similarity_search_with_relevance_scores(self, query: str, k: int = 6) -> List[Tuple[Document, float]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            doc_count = self._get_doc_count(conn)
            if doc_count == 0:
                return []

            q_tokens = self._tokenize(query)
            if not q_tokens:
                return []
            q_counts = Counter(q_tokens)

            # Fetch df for query terms
            placeholders = ",".join(["?"] * len(q_counts))
            cur = conn.execute(f"SELECT term, df FROM terms WHERE term IN ({placeholders})", tuple(q_counts.keys()))
            term_to_df = {row["term"]: int(row["df"]) for row in cur.fetchall()}

            # Compute query tf-idf and its norm
            q_weights: Dict[str, float] = {}
            for term, tf in q_counts.items():
                df = term_to_df.get(term, 0)
                idf = math.log((1 + doc_count) / (1 + df)) + 1.0
                q_weights[term] = float(tf) * idf
            q_norm = math.sqrt(sum(w * w for w in q_weights.values())) or 1.0

            # Candidate docs: those containing at least one query term
            cur = conn.execute(
                f"SELECT DISTINCT doc_id FROM term_doc WHERE term IN ({placeholders})",
                tuple(q_counts.keys()),
            )
            candidate_ids = [row["doc_id"] for row in cur.fetchall()]
            if not candidate_ids:
                return []

            # For each candidate, get counts for the query terms and compute cosine
            results: List[Tuple[Document, float]] = []
            for doc_id in candidate_ids:
                cur = conn.execute("SELECT content, metadata FROM documents WHERE id = ?", (doc_id,))
                drow = cur.fetchone()
                if drow is None:
                    continue
                content = drow["content"]
                metadata = json.loads(drow["metadata"])

                cur = conn.execute(
                    f"SELECT term, count FROM term_doc WHERE doc_id = ? AND term IN ({placeholders})",
                    (doc_id, *tuple(q_counts.keys())),
                )
                doc_term_counts = {row["term"]: int(row["count"]) for row in cur.fetchall()}

                # Compute doc tf-idf on query term subset
                dot = 0.0
                d_norm_sq = 0.0
                for term, q_w in q_weights.items():
                    tf_d = float(doc_term_counts.get(term, 0))
                    if tf_d == 0:
                        continue
                    df = term_to_df.get(term, 0)
                    idf = math.log((1 + doc_count) / (1 + df)) + 1.0
                    d_w = tf_d * idf
                    dot += q_w * d_w
                    d_norm_sq += d_w * d_w

                d_norm = math.sqrt(d_norm_sq) or 1.0
                score = dot / (q_norm * d_norm)
                results.append((Document(page_content=content, metadata=metadata), float(score)))

            results.sort(key=lambda x: x[1], reverse=True)
            return results[:k]


def get_vectorstore(persist_dir: str) -> SimpleSQLiteVectorStore:
    os.makedirs(persist_dir, exist_ok=True)
    db_path = os.path.join(persist_dir, "vectorstore.db")
    return SimpleSQLiteVectorStore(db_path=db_path)


def upsert_results_to_vectorstore(vs: SimpleSQLiteVectorStore, results: List[AgentResult]):
    documents: List[str] = []
    metadatas: List[Dict[str, Any]] = []
    ids: List[str] = []

    for r in results:
        doc_id = f"{r.ticker}:{r.name}:{abs(hash(r.content))}"
        documents.append(r.content)
        metadatas.append({
            "ticker": r.ticker,
            "agent": r.name,
            "sources": r.sources,
        })
        ids.append(doc_id)

    if documents:
        vs.add_texts(texts=documents, metadatas=metadatas, ids=ids)


def retrieve_context(vs: SimpleSQLiteVectorStore, ticker: str, question: str, k: int = 6) -> List[Dict[str, Any]]:
    query = f"{ticker} - {question}" if ticker else question
    docs = vs.similarity_search_with_relevance_scores(query, k=k)
    results = []
    for doc, score in docs:
        meta = doc.metadata or {}
        results.append({
            "content": doc.page_content,
            "metadata": meta,
            "score": float(score),
        })
    return results


def build_report(results: List[AgentResult]) -> str:
    parts = []
    for r in results:
        parts.append(f"## {r.name.title()} Analysis\n")
        parts.append(r.content)
        if r.sources:
            parts.append("\nSources:\n" + "\n".join(r.sources))
        parts.append("\n\n")
    return "\n".join(parts).strip()


def run_research_and_fundamental_agents(ticker: str, persist_dir: str = "./chroma_db") -> Dict[str, Any]:
    """Run only research and fundamental agents for immediate display"""
    results = [
        run_search_agent(ticker),
        run_fundamental_agent(ticker),
    ]
    vs = get_vectorstore(persist_dir)
    upsert_results_to_vectorstore(vs, results)
    return {
        "report_md": build_report(results),
        "vectorstore": vs,
    }


def run_technical_analysis_only(ticker: str, persist_dir: str = "./chroma_db") -> Dict[str, Any]:
    """Run only technical analysis agent"""
    result = run_technical_agent(ticker)
    vs = get_vectorstore(persist_dir)
    upsert_results_to_vectorstore(vs, [result])
    return {
        "tech_result": result,
        "vectorstore": vs,
    }


def run_all_agents_and_store(ticker: str, persist_dir: str = "./chroma_db") -> Dict[str, Any]:
    results = [
        run_search_agent(ticker),
        run_fundamental_agent(ticker),
        run_technical_agent(ticker),
    ]
    vs = get_vectorstore(persist_dir)
    upsert_results_to_vectorstore(vs, results)
    return {
        "report_md": build_report(results),
        "vectorstore": vs,
    }


def answer_question_with_rag(vs: SimpleSQLiteVectorStore, ticker: str, question: str, k: int = 6) -> Dict[str, Any]:
    contexts = retrieve_context(vs, ticker, question, k=k)
    context_blocks = []
    aggregated_sources: List[str] = []
    for c in contexts:
        meta = c.get("metadata", {})
        srcs = meta.get("sources", []) or []
        aggregated_sources.extend(srcs)
        snippet = c.get("content", "")
        agent = meta.get("agent", "unknown")
        context_blocks.append(f"[Agent={agent}]\n{snippet}")

    system = (
        "You are a financial analysis assistant. Answer the user's question strictly using the provided context excerpts. "
        "Cite evidence inline by noting the agent name in parentheses, e.g., (fundamental) or (research). If the answer is not supported by the context, say you don't have enough information."
    )
    prompt = ChatPromptTemplate.from_messages([
        ("system", system),
        ("human", "Ticker: {ticker}\nQuestion: {question}\n\nContext:\n{context}\n\nAnswer concisely and include citations."),
    ])

    llm = ChatGroq(temperature=0, groq_api_key=os.getenv("GROQ_API_KEY"), model_name="llama3-70b-8192")
    messages = prompt.format_messages(ticker=ticker, question=question, context="\n\n".join(context_blocks))
    ai_msg = llm.invoke(messages)
    answer_text = getattr(ai_msg, "content", str(ai_msg))

    # Unique sources preserving order
    seen = set()
    dedup_sources = []
    for s in aggregated_sources:
        if s not in seen:
            dedup_sources.append(s)
            seen.add(s)

    return {"answer": answer_text, "sources": dedup_sources, "contexts": contexts}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("ticker", help="Stock/ETF ticker symbol")
    parser.add_argument("--db", dest="db", default="./chroma_db")
    args = parser.parse_args()

    out = run_all_agents_and_store(args.ticker, args.db)
    print(out["report_md"])  # Basic CLI usage
