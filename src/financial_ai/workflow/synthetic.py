"""Opt-in synthetic research through the real persistence/analysis/report pipeline."""

from financial_ai.providers.synthetic import SyntheticCollector
from financial_ai.workflow.pipeline import ResearchPipeline
from settings import get_settings


def handler(repository, run_id):
    settings = get_settings()
    runtime = (
        settings.persist_dir / "scaled"
        if repository.database.postgres
        else repository.database.path.parent
    )
    return ResearchPipeline(
        repository, run_id, SyntheticCollector(settings.synthetic_evidence_origin), runtime=runtime
    )
