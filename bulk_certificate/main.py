from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph


APP_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("CERTIFICATE_DATA_DIR", APP_DIR / "data"))
DB_PATH = DATA_DIR / "certificates.sqlite3"
OUTPUT_DIR = DATA_DIR / "generated"
MAX_RECIPIENTS = int(os.environ.get("MAX_RECIPIENTS", "500"))

app = FastAPI(
    title="Bulk Certificate Generator API",
    description="Create a batch job, track individual certificate results, and download generated PDFs.",
    version="1.0.0",
)


class CertificateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    certificate_title: str = Field(min_length=1, max_length=160)
    organization: str = Field(min_length=1, max_length=160)
    issue_date: date
    recipients: list[Any] = Field(min_length=1, max_length=MAX_RECIPIENTS)


class RecipientInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    name: str = Field(min_length=1, max_length=120)
    email: str | None = Field(default=None, max_length=254)

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("email must be a valid email address")
        return value


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def initialize_database() -> None:
    with closing(connect()) as conn:
        conn.executescript(
            """CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                certificate_title TEXT NOT NULL,
                organization TEXT NOT NULL,
                issue_date TEXT NOT NULL,
                status TEXT NOT NULL,
                total INTEGER NOT NULL,
                processed INTEGER NOT NULL DEFAULT 0,
                succeeded INTEGER NOT NULL DEFAULT 0,
                failed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS certificates (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                ordinal INTEGER NOT NULL,
                recipient_json TEXT NOT NULL,
                status TEXT NOT NULL,
                error TEXT,
                output_path TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_certificates_job ON certificates(job_id, ordinal);"""
        )
        conn.commit()


@app.on_event("startup")
def startup() -> None:
    initialize_database()


def error_text(exc: ValidationError) -> str:
    pieces = []
    for item in exc.errors(include_url=False):
        field = ".".join(str(part) for part in item["loc"])
        pieces.append(f"{field}: {item['msg']}")
    return "; ".join(pieces)


def validate_recipient(raw: Any) -> tuple[dict[str, Any], str | None]:
    try:
        recipient = RecipientInput.model_validate(raw)
        return recipient.model_dump(), None
    except ValidationError as exc:
        name = raw.get("name") if isinstance(raw, dict) else None
        email = raw.get("email") if isinstance(raw, dict) else None
        return {"name": name if isinstance(name, str) else None,
                "email": email if isinstance(email, str) else None}, error_text(exc)


def draw_centered_paragraph(pdf: canvas.Canvas, text: str, x: float, y: float, width: float,
                            font_name: str, font_size: int, color: colors.Color) -> None:
    style = ParagraphStyle("certificate", fontName=font_name, fontSize=font_size,
                           leading=font_size * 1.35, alignment=TA_CENTER, textColor=color)
    paragraph = Paragraph(text, style)
    _, height = paragraph.wrap(width, 120)
    paragraph.drawOn(pdf, x - width / 2, y - height)


def generate_certificate_pdf(path: Path, recipient: dict[str, Any], job: dict[str, str], certificate_id: str) -> None:
    """Render one certificate with the built-in, single-page PDF template."""
    path.parent.mkdir(parents=True, exist_ok=True)
    page_width, page_height = landscape(letter)
    pdf = canvas.Canvas(str(path), pagesize=(page_width, page_height), pageCompression=1)
    pdf.setTitle(f"Certificate for {recipient['name']}")

    pdf.setFillColor(colors.HexColor("#f7f5ef"))
    pdf.rect(0, 0, page_width, page_height, fill=1, stroke=0)
    pdf.setStrokeColor(colors.HexColor("#163b52"))
    pdf.setLineWidth(2)
    pdf.rect(28, 28, page_width - 56, page_height - 56, fill=0, stroke=1)
    pdf.setStrokeColor(colors.HexColor("#c89b4b"))
    pdf.setLineWidth(0.8)
    pdf.rect(38, 38, page_width - 76, page_height - 76, fill=0, stroke=1)

    draw_centered_paragraph(pdf, "CERTIFICATE OF COMPLETION", page_width / 2, page_height - 100,
                            page_width - 140, "Helvetica-Bold", 15, colors.HexColor("#9b7130"))
    draw_centered_paragraph(pdf, f"Presented to {escape(recipient['name'])}", page_width / 2, page_height - 178,
                            page_width - 120, "Helvetica-Bold", 30, colors.HexColor("#163b52"))
    draw_centered_paragraph(pdf, f"for completing <b>{escape(job['certificate_title'])}</b>", page_width / 2,
                            page_height - 245, page_width - 160, "Helvetica", 17,
                            colors.HexColor("#28353b"))
    draw_centered_paragraph(pdf, f"Issued by {escape(job['organization'])} on {job['issue_date']}",
                            page_width / 2, page_height - 295, page_width - 160,
                            "Helvetica", 12, colors.HexColor("#555555"))
    pdf.setStrokeColor(colors.HexColor("#777777"))
    pdf.line(page_width / 2 - 110, 93, page_width / 2 + 110, 93)
    draw_centered_paragraph(pdf, "Authorized signature", page_width / 2, 80, 240,
                            "Helvetica", 10, colors.HexColor("#555555"))
    pdf.setFont("Helvetica", 8)
    pdf.setFillColor(colors.HexColor("#777777"))
    pdf.drawCentredString(page_width / 2, 51, f"Certificate ID: {certificate_id}")
    pdf.showPage()
    pdf.save()


def set_certificate_result(certificate_id: str, status: str, error: str | None = None,
                           output_path: Path | None = None) -> None:
    with closing(connect()) as conn:
        conn.execute(
            "UPDATE certificates SET status = ?, error = ?, output_path = ? WHERE id = ?",
            (status, error, str(output_path) if output_path else None, certificate_id),
        )
        conn.execute(
            """UPDATE jobs SET processed = processed + 1,
               succeeded = succeeded + ?, failed = failed + ?, updated_at = ? WHERE id = ?""",
            (1 if status == "COMPLETED" else 0, 1 if status == "FAILED" else 0,
             utc_now(), _job_id_for_certificate(conn, certificate_id)),
        )
        conn.commit()


def _job_id_for_certificate(conn: sqlite3.Connection, certificate_id: str) -> str:
    row = conn.execute("SELECT job_id FROM certificates WHERE id = ?", (certificate_id,)).fetchone()
    if row is None:
        raise RuntimeError("Certificate record disappeared while processing.")
    return str(row["job_id"])


def process_job(job_id: str) -> None:
    with closing(connect()) as conn:
        job_row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if job_row is None:
            return
        job = {"certificate_title": job_row["certificate_title"],
               "organization": job_row["organization"], "issue_date": job_row["issue_date"]}
        rows = conn.execute(
            "SELECT * FROM certificates WHERE job_id = ? AND status = 'PENDING' ORDER BY ordinal",
            (job_id,),
        ).fetchall()
        conn.execute("UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?",
                     ("PROCESSING", utc_now(), job_id))
        conn.commit()

    for row in rows:
        certificate_id = str(row["id"])
        recipient = json.loads(row["recipient_json"])
        try:
            output_path = OUTPUT_DIR / job_id / f"{certificate_id}.pdf"
            generate_certificate_pdf(output_path, recipient, job, certificate_id)
            set_certificate_result(certificate_id, "COMPLETED", output_path=output_path)
        except Exception as exc:  # A single rendering failure must not stop the rest of the batch.
            set_certificate_result(certificate_id, "FAILED", error=f"Certificate generation failed: {exc}")

    with closing(connect()) as conn:
        counts = conn.execute("SELECT succeeded, failed, total FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if counts is None:
            return
        if counts["failed"] == 0:
            final_status = "COMPLETED"
        elif counts["succeeded"] == 0:
            final_status = "FAILED"
        else:
            final_status = "COMPLETED_WITH_ERRORS"
        conn.execute("UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?",
                     (final_status, utc_now(), job_id))
        conn.commit()


def get_job(job_id: str) -> sqlite3.Row:
    with closing(connect()) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Generation job not found.")
    return row


def job_response(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "status": row["status"],
        "total": row["total"],
        "processed": row["processed"],
        "succeeded": row["succeeded"],
        "failed": row["failed"],
        "progress_percent": round(row["processed"] * 100 / row["total"]) if row["total"] else 100,
        "certificate_title": row["certificate_title"],
        "organization": row["organization"],
        "issue_date": row["issue_date"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/jobs/", status_code=202)
def create_job(payload: CertificateRequest, background_tasks: BackgroundTasks) -> dict[str, Any]:
    job_id = str(uuid.uuid4())
    now = utc_now()
    prepared: list[tuple[str, int, str, str, str | None]] = []
    failed_at_validation = 0
    for ordinal, raw in enumerate(payload.recipients):
        recipient, error = validate_recipient(raw)
        status = "FAILED" if error else "PENDING"
        failed_at_validation += int(error is not None)
        prepared.append((str(uuid.uuid4()), ordinal, json.dumps(recipient, ensure_ascii=False), status, error))

    with closing(connect()) as conn:
        conn.execute(
            """INSERT INTO jobs (id, certificate_title, organization, issue_date, status, total,
               processed, succeeded, failed, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (job_id, payload.certificate_title, payload.organization, payload.issue_date.isoformat(),
             "QUEUED", len(prepared), failed_at_validation, 0, failed_at_validation, now, now),
        )
        conn.executemany(
            """INSERT INTO certificates (id, job_id, ordinal, recipient_json, status, error, output_path, created_at)
               VALUES (?, ?, ?, ?, ?, ?, NULL, ?)""",
            [(certificate_id, job_id, ordinal, recipient_json, status, error, now)
             for certificate_id, ordinal, recipient_json, status, error in prepared],
        )
        conn.commit()

    background_tasks.add_task(process_job, job_id)
    return {"id": job_id, "status": "QUEUED", "total": len(prepared),
            "validated": len(prepared) - failed_at_validation, "failed_validation": failed_at_validation,
            "status_url": f"/api/jobs/{job_id}/"}


@app.get("/api/jobs/{job_id}/")
def get_job_status(job_id: str) -> dict[str, Any]:
    return job_response(get_job(job_id))


@app.get("/api/jobs/{job_id}/certificates/")
def get_job_certificates(job_id: str) -> dict[str, Any]:
    row = get_job(job_id)
    with closing(connect()) as conn:
        items = conn.execute(
            "SELECT * FROM certificates WHERE job_id = ? ORDER BY ordinal", (job_id,)
        ).fetchall()
    certificates = []
    for item in items:
        recipient = json.loads(item["recipient_json"])
        result: dict[str, Any] = {
            "id": item["id"],
            "name": recipient.get("name"),
            "email": recipient.get("email"),
            "status": item["status"],
            "error": item["error"],
        }
        if item["status"] == "COMPLETED":
            result["download_url"] = f"/api/jobs/{job_id}/certificates/{item['id']}/download/"
        certificates.append(result)
    return {"job_id": job_id, "status": row["status"], "certificates": certificates}


@app.get("/api/jobs/{job_id}/certificates/{certificate_id}/download/")
def download_certificate(job_id: str, certificate_id: str) -> FileResponse:
    get_job(job_id)
    with closing(connect()) as conn:
        row = conn.execute(
            "SELECT * FROM certificates WHERE id = ? AND job_id = ?",
            (certificate_id, job_id),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Certificate not found for this job.")
    if row["status"] != "COMPLETED" or not row["output_path"]:
        raise HTTPException(status_code=409, detail="This certificate is not available for download.")
    path = Path(row["output_path"]).resolve()
    if not path.is_relative_to(OUTPUT_DIR.resolve()) or not path.is_file():
        raise HTTPException(status_code=404, detail="Generated certificate file is missing.")
    return FileResponse(path, media_type="application/pdf", filename=f"certificate-{certificate_id}.pdf")
