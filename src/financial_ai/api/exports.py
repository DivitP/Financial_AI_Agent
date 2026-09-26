import json
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query
from fastapi.responses import Response

from financial_ai.api.errors import ApiError
from financial_ai.exports import export_bundle, markdown_export, pdf_export


def export_router(database, artifact_root: Path):
    router = APIRouter(tags=["exports"])

    @router.get("/api/v1/research-runs/{run_id}/export")
    def download(
        run_id: UUID, version: int = Query(ge=1), format: Literal["json", "md", "pdf"] = "json"
    ):
        try:
            bundle = export_bundle(database, run_id, version, artifact_root)
            if format == "json":
                content, media = (
                    json.dumps(bundle, ensure_ascii=False, indent=2).encode(),
                    "application/json",
                )
            elif format == "md":
                content, media = markdown_export(bundle), "text/markdown"
            else:
                content, media = pdf_export(bundle), "application/pdf"
        except KeyError:
            raise ApiError("report_not_found", "Saved report version not found.", 404) from None
        except ValueError as exc:
            raise ApiError("export_unavailable", str(exc), 422) from None
        return Response(
            content,
            media_type=media,
            headers={
                "Content-Disposition": f'attachment; filename="research-{run_id}-v{version}.{format}"',
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    return router
