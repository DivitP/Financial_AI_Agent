# Research Q&A

POST `/api/v1/research-runs/{run_id}/qa` with `{"question":"Revenue risks?"}`.
GET the same URL for the last 100 persisted turns for that run. Migration 7 adds
history. The UI displays history and suggested questions, validated streamed
excerpts, citation previews, and exact document URLs (including original fragments).

The default index is `<application database stem>.index.db` next to the source
database. Populate it using the source indexing API documented in retrieval.md.
The API uses lexical retrieval by default; an injected ResearchIndex may additionally
use Chroma. Collection is not automatically indexed by this change. Empty indexes
return insufficient evidence. Enable Groq or local Ollama using existing settings
for generation; disabled models are explicitly reported.

Decomposition is bounded to three subqueries and eight context chunks. Each answer
is a selection of exact excerpts, not unrestricted synthesis. Citation IDs and
quotes must match retrieved context; URLs are supplied by the server and rechecked
against relational evidence. Malformed answers return safe JSON 422 before any SSE
content or history write. Provider errors return 503. Validated claims are streamed
as `claim` events followed by `complete`. This intentionally buffers model generation
before streaming. A disconnected client can reload persisted history.

History is displayed but never treated as factual context for later questions.
Follow-ups should name their subject. Exact-quote checks establish provenance, not
semantic relevance or truth of a source. Retrieved documents remain untrusted.
No new keys or dependencies are required. Offline tests inject a fixture model.
