"""Version-pinned exports; persisted report content is never rewritten by a model."""

import base64
import hashlib
import io
import json
import re
from pathlib import Path
from xml.sax.saxutils import escape
from PIL import Image as PillowImage

from financial_ai.storage.artifacts import FileSystemArtifactStore
from financial_ai.storage.history import ResearchHistory


def export_bundle(database, run_id, version, artifact_root):
    saved = ResearchHistory(database).reopen(run_id, version)
    report = saved["report"]
    if report is None:
        raise KeyError("report")
    charts = []
    warnings = [saved["notice"]]
    for snapshot in saved["snapshots"]:
        if snapshot["lane"] != "charts" or snapshot["status"] != "completed":
            continue
        payload = snapshot["payload"] or {}
        refs = payload.get("charts", []) if isinstance(payload, dict) else []
        if not isinstance(refs, list) or len(refs) > 20:
            warnings.append("Chart manifest invalid or exceeds 20 charts.")
            continue
        for ref in refs:
            try:
                if not isinstance(ref, dict):
                    raise ValueError("Invalid chart reference")
                artifact_id = ref.get("artifact_id", "")
                if not isinstance(artifact_id, str) or not re.fullmatch(
                    r"charts_[0-9a-f]{64}", artifact_id
                ):
                    raise ValueError("Invalid chart ID")
                store = FileSystemArtifactStore(artifact_root)
                path = store._path_for(artifact_id, ".png")
                if (
                    not path.resolve().is_relative_to(Path(artifact_root).resolve())
                    or path.is_symlink()
                ):
                    raise ValueError("Unsafe chart path")
                if path.stat().st_size > 10_000_000:
                    raise ValueError("Chart exceeds 10 MB")
                data = path.read_bytes()
                if hashlib.sha256(data).hexdigest() != artifact_id.removeprefix("charts_"):
                    raise ValueError("Chart hash mismatch")
                with PillowImage.open(io.BytesIO(data)) as image:
                    if image.format != "PNG" or image.width * image.height > 20_000_000:
                        raise ValueError("Unsupported chart image")
                    image.verify()
                charts.append(
                    {
                        "reference": ref,
                        "mime_type": "image/png",
                        "base64": base64.b64encode(data).decode("ascii"),
                    }
                )
            except (OSError, ValueError, PillowImage.DecompressionBombError):
                warnings.append(
                    "Saved chart unavailable: missing, invalid, unsafe, oversized, or hash mismatch."
                )
    if not charts:
        warnings.append(
            "No usable charts captured with this report version. No charts were regenerated."
        )
    encoded = json.dumps(report, ensure_ascii=False, sort_keys=True).encode()
    return {
        "report": report,
        "report_sha256": hashlib.sha256(encoded).hexdigest(),
        "charts": charts,
        "warnings": warnings,
    }


def blocks(bundle):
    report = bundle["report"]
    yield "title", "Research report"
    yield "text", f"Report {report['id']} | Run {report['run_id']} | Version {report['version']}"
    yield "text", "As of: " + report["as_of"]
    yield "heading", "Decision brief"
    for text in report["decision_brief"]:
        yield "text", text
    for section in report["sections"]:
        yield "heading", section["title"]
        for finding in section["findings"]:
            yield "text", finding["summary"]
            for limitation in finding.get("limitations", []):
                yield "text", limitation
            yield "text", "Evidence IDs: " + ", ".join(finding["evidence_ids"])
            if finding.get("numeric_claims"):
                yield "text", json.dumps(finding["numeric_claims"], ensure_ascii=False)
    yield "heading", "Evidence appendix"
    for eid, url in sorted(report["evidence_links"].items()):
        yield "text", eid
        yield "text", url
    yield "heading", "Model metadata"
    yield "text", json.dumps(report["model_configuration"], ensure_ascii=False, sort_keys=True)
    if bundle["charts"]:
        yield "heading", "Saved chart metadata"
        for chart in bundle["charts"]:
            yield "text", json.dumps(chart["reference"], ensure_ascii=False, sort_keys=True)
    yield "heading", "Export limitations"
    for warning in bundle["warnings"]:
        yield "text", warning
    yield "text", "Persisted report SHA-256: " + bundle["report_sha256"]


def markdown_export(bundle):
    # Escape HTML and Markdown syntax so source text cannot become executable markup.
    def literal(text):
        return re.sub(r"([\\`*_{}\[\]()#+.!|>~-])", r"\\\1", escape(text))

    parts = []
    for kind, text in blocks(bundle):
        parts.append(
            ("# " if kind == "title" else "## " if kind == "heading" else "") + literal(text)
        )
    for chart in bundle["charts"]:
        parts.append("![Saved chart](data:image/png;base64," + chart["base64"] + ")")
        parts.append(literal(json.dumps(chart["reference"], ensure_ascii=False)))
    # Preserve every field, including future structured fields, without losing precision.
    raw = json.dumps(bundle["report"], ensure_ascii=False, indent=2)
    fence = "`" * max(3, max((len(m[0]) + 1 for m in re.finditer(r"`+", raw)), default=3))
    parts.append("## Exact persisted report JSON\n\n" + fence + "json\n" + raw + "\n" + fence)
    return ("\n\n".join(parts) + "\n").encode()


def pdf_export(bundle):
    import matplotlib
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, PageBreak

    font_path = Path(matplotlib.get_data_path()) / "fonts/ttf/DejaVuSans.ttf"
    if "ResearchSans" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("ResearchSans", str(font_path)))
    font = pdfmetrics.getFont("ResearchSans")
    all_blocks = list(blocks(bundle))
    all_blocks += [
        ("heading", "Exact persisted report JSON"),
        ("text", json.dumps(bundle["report"], ensure_ascii=False, indent=2)),
    ]
    for _, text in all_blocks:
        if any(ord(c) not in font.face.charToGlyph for c in text if not c.isspace()):
            raise ValueError("PDF font cannot represent saved text exactly; use JSON or Markdown.")
    styles = {
        kind: ParagraphStyle(
            kind,
            fontName="ResearchSans",
            fontSize=size,
            leading=size * 1.5,
            spaceAfter=10,
            splitLongWords=True,
            keepWithNext=kind != "text",
        )
        for kind, size in (("title", 20), ("heading", 13), ("text", 9))
    }
    story = []
    for kind, text in all_blocks:
        story.append(Paragraph(escape(text).replace("\n", "<br/>"), styles[kind]))
    for chart in bundle["charts"]:
        story.extend([PageBreak(), Paragraph("Saved chart", styles["heading"])])
        image = Image(io.BytesIO(base64.b64decode(chart["base64"])))
        scale = min(480 / image.imageWidth, 550 / image.imageHeight, 1)
        image.drawWidth, image.drawHeight = image.imageWidth * scale, image.imageHeight * scale
        story.extend(
            [
                image,
                Spacer(1, 12),
                Paragraph(escape(chart["reference"]["artifact_id"]), styles["text"]),
            ]
        )
    output = io.BytesIO()

    def footer(canvas, doc):
        canvas.setFont("ResearchSans", 8)
        canvas.drawString(48, 25, f"Saved research - page {doc.page}")

    SimpleDocTemplate(
        output, pagesize=(612, 792), leftMargin=48, rightMargin=48, topMargin=48, bottomMargin=48
    ).build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
