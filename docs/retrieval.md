# Local hybrid retrieval

Install optional dependencies with `uv sync --locked --extra vector`. No API key
is needed. Supply a downloaded sentence-transformer directory (for example,
all-MiniLM-L6-v2) to `LocalEmbeddings`; loading uses `local_files_only=True` and
disables remote code. Models are never downloaded during tests or API startup.
Review the chosen model's license before redistribution.

`ChromaIndex(path, embeddings, model_version="pinned-model-revision")` persists
vectors in a collection isolated by model version. Pass it to
`ResearchIndex(source_database, index_path, vector)`. Keep both paths under
`data/runtime/`, separate from the source database. Dependencies are optional to
keep ordinary collection and CI independent of model weights.

Index `SourceText` records only after saving relational evidence. Headings (Markdown
and SEC Item headings) and paragraphs form sections, with bounded character splits
for long paragraphs. HTML must first be converted to plain text. Every chunk retains
source type, ticker, run, URL, period, publication/retrieval dates, evidence ID,
source/content hashes and section. Common secrets and chart/binary payloads are
rejected; this heuristic is not a general-purpose secret detector. Only approved
public source text should be supplied, never configuration or raw provider JSON.

SQLite FTS5 and Chroma are disposable derived indexes; neither writes source records.
Embedding failures return a warning and leave lexical search usable. Reindex the
same sources to repair Chroma; deterministic IDs make retries idempotent. Changed
source versions remain distinct. Callers must filter periods when comparing versions.

`search(query, ticker=..., run_id=..., as_of=..., kind=..., period=...)` performs
filtered lexical and semantic searches, reciprocal-rank fusion (k=60), and a bounded
publication-recency boost (default half-life 90 days). Both retrieval and publication
dates must precede as-of. Semantic IDs are rechecked against local metadata. Scores
are ranking signals, never financial confidence. This is a library boundary; existing
legacy Q&A and API endpoints are not automatically switched to it.

References: [Chroma query API](https://docs.trychroma.com/docs/querying-collections/query-and-get),
[local embedding API](https://www.sbert.net/docs/package_reference/sentence_transformer/model.html).
