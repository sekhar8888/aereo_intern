# Bulk Certificate Generator API

A FastAPI service that accepts one bulk request, validates each recipient independently, generates one PDF certificate per valid recipient, tracks batch progress and per-recipient failures in SQLite, and serves generated PDFs for download.

## Setup

Python 3.10 or newer is required.

```bash
cd bulk_certificate
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Run

```bash
uvicorn main:app --reload
```

The API is available at `http://127.0.0.1:8000`. Swagger UI is at `/docs`; `/health` is a simple health check.

Environment variables:

- `CERTIFICATE_DATA_DIR`: location for the SQLite database and generated PDFs (default `./data`).
- `MAX_RECIPIENTS`: maximum recipients in one request (default 500).

## Create a bulk job

`POST /api/jobs/` accepts JSON. A recipient needs a non-empty `name`; `email` is optional and, when provided, must look like a valid email address. Invalid recipient entries are reported as failed rows while valid entries in the same request continue.

```bash
curl -X POST http://127.0.0.1:8000/api/jobs/ \
  -H "Content-Type: application/json" \
  -d '{
    "certificate_title": "Introduction to GIS",
    "organization": "Example Learning",
    "issue_date": "2026-10-08",
    "recipients": [
      {"name": "Alex Morgan", "email": "alex@example.com"},
      {"name": "Jordan Lee"},
      {"name": "", "email": "not-an-email"}
    ]
  }'
```

The API returns `202 Accepted` with a job ID, initial status, counts, and a status URL. The job validates shared fields (`certificate_title`, `organization`, `issue_date`, recipient count) before queuing. A malformed shared field or invalid JSON returns `422` and does not create a job.

## Check progress and results

`GET /api/jobs/{job_id}/` returns the batch status (`QUEUED`, `PROCESSING`, `COMPLETED`, `COMPLETED_WITH_ERRORS`, or `FAILED`), total, processed, successful and failed counts, and a progress percentage.

`GET /api/jobs/{job_id}/certificates/` returns the per-recipient result list. Successful entries have a `download_url`; failed entries include an error explaining the validation or rendering failure.

Download one generated PDF with the returned URL:

```bash
curl -L "http://127.0.0.1:8000/api/jobs/JOB_ID/certificates/CERTIFICATE_ID/download/" \
  -o certificate.pdf
```

An unknown job or certificate returns `404`. Attempting to download a certificate that is still pending or failed returns `409`.

## Run the tests

From this folder:

```bash
pytest
```

The tests cover job creation, shared and per-recipient input validation, PDF generation and retrieval, status/progress, and continuation after an individual certificate rendering failure.

## Design decisions

- **FastAPI:** typed request validation, concise routing, and generated OpenAPI documentation.
- **SQLite:** a small relational store that persists job and per-recipient status between application restarts. Each recipient has an independent row and output path.
- **BackgroundTasks:** keeps the request from waiting for all PDFs. It is appropriate for this standalone assignment and modest batches, and avoids introducing a broker. For production workloads or multiple API replicas, move processing to a durable queue such as Celery/RQ with shared object storage.
- **Per-recipient validation and exception handling:** malformed recipient entries are recorded as failed certificates without rejecting valid entries; a PDF rendering exception affects only that recipient.
- **One built-in PDF template:** ReportLab draws a landscape certificate with the recipient, certificate title, organization, issue date, and unique certificate ID. The assignment does not require template editing.
- **Generated files stay under the configured data directory:** downloads resolve only successful certificate records, and the path is checked to remain inside generated storage.

## Learning and future scope

This project demonstrates bulk request handling, row-level validation, background job status, partial failure handling, PDF generation, relational persistence, and file retrieval. Future improvements could include authentication, job cancellation, expiration and cleanup, pagination for very large batches, a durable task queue, object storage, and configurable templates.
