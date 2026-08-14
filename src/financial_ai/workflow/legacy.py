"""Temporary compatibility imports for the existing Flask application."""

from main import (  # noqa: F401
    answer_question_with_rag,
    get_vectorstore,
    run_research_and_fundamental_agents,
    run_technical_agent,
    upsert_results_to_vectorstore,
)
