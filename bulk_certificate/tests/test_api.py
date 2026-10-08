from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    data_dir = tmp_path / "data"
    monkeypatch.setattr(main, "DATA_DIR", data_dir)
    monkeypatch.setattr(main, "DB_PATH", data_dir / "test.sqlite3")
    monkeypatch.setattr(main, "OUTPUT_DIR", data_dir / "generated")
    with TestClient(main.app) as test_client:
        yield test_client


def payload(recipients=None):
    return {
        "certificate_title": "Intro to GIS",
        "organization": "Example Learning",
        "issue_date": "2026-10-08",
        "recipients": recipients if recipients is not None else [
            {"name": "Alex Morgan", "email": "alex@example.com"},
            {"name": "Jordan Lee"},
        ],
    }


def get_one_result(client: TestClient, job_id: str, status: str = "COMPLETED") -> dict:
    results = client.get(f"/api/jobs/{job_id}/certificates/").json()
    assert results["status"] == status
    return results


def test_create_job_status_progress_and_retrieve_pdf(client: TestClient):
    response = client.post("/api/jobs/", json=payload())
    assert response.status_code == 202
    created = response.json()
    assert created["total"] == 2
    assert created["validated"] == 2

    status = client.get(created["status_url"]).json()
    assert status["status"] == "COMPLETED"
    assert status["processed"] == 2
    assert status["succeeded"] == 2
    assert status["failed"] == 0
    assert status["progress_percent"] == 100

    results = get_one_result(client, created["id"])
    completed = [item for item in results["certificates"] if item["status"] == "COMPLETED"]
    assert len(completed) == 2
    downloaded = client.get(completed[0]["download_url"])
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"] == "application/pdf"
    assert downloaded.content.startswith(b"%PDF-")


def test_invalid_shared_input_is_rejected(client: TestClient):
    bad = payload()
    bad["issue_date"] = "not-a-date"
    assert client.post("/api/jobs/", json=bad).status_code == 422
    assert client.post("/api/jobs/", json={**payload(), "recipients": []}).status_code == 422


def test_invalid_recipient_is_recorded_and_valid_ones_complete(client: TestClient):
    response = client.post("/api/jobs/", json=payload([
        {"name": "Valid Person", "email": "valid@example.com"},
        {"name": "", "email": "wrong"},
        None,
    ]))
    created = response.json()
    assert response.status_code == 202
    assert created["validated"] == 1
    assert created["failed_validation"] == 2

    status = client.get(created["status_url"]).json()
    assert status["status"] == "COMPLETED_WITH_ERRORS"
    assert status["succeeded"] == 1
    assert status["failed"] == 2
    results = client.get(f"/api/jobs/{created['id']}/certificates/").json()
    assert [item["status"] for item in results["certificates"]].count("FAILED") == 2
    assert all(item["error"] for item in results["certificates"] if item["status"] == "FAILED")


def test_one_render_failure_does_not_stop_other_recipients(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    original = main.generate_certificate_pdf

    def fail_first(path, recipient, job, certificate_id):
        if recipient["name"] == "Alex Morgan":
            raise RuntimeError("simulated renderer error")
        return original(path, recipient, job, certificate_id)

    monkeypatch.setattr(main, "generate_certificate_pdf", fail_first)
    response = client.post("/api/jobs/", json=payload())
    created = response.json()
    status = client.get(created["status_url"]).json()
    assert status["status"] == "COMPLETED_WITH_ERRORS"
    assert status["succeeded"] == 1
    assert status["failed"] == 1
    results = client.get(f"/api/jobs/{created['id']}/certificates/").json()
    assert [item["status"] for item in results["certificates"]].count("COMPLETED") == 1


def test_missing_job_and_unavailable_certificate_return_errors(client: TestClient):
    assert client.get("/api/jobs/no-such-job/").status_code == 404
    created = client.post("/api/jobs/", json=payload()).json()
    assert client.get(f"/api/jobs/{created['id']}/certificates/no-such-certificate/download/").status_code == 404
