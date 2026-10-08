from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture
def client(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setattr(main, "DATA_DIR", data_dir)
    monkeypatch.setattr(main, "UPLOAD_DIR", data_dir / "uploads")
    monkeypatch.setattr(main, "DB_PATH", data_dir / "measurements.sqlite3")
    with TestClient(main.app) as test_client:
        yield test_client


@pytest.fixture
def sample_kml() -> bytes:
    return b'''<?xml version="1.0" encoding="UTF-8"?>
    <kml xmlns="http://www.opengis.net/kml/2.2"><Document>
      <Placemark><name>Field</name><Polygon><outerBoundaryIs><LinearRing><coordinates>
        77.5946,12.9716,0 77.5956,12.9716,0 77.5956,12.9726,0
        77.5946,12.9726,0 77.5946,12.9716,0
      </coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
      <Placemark><name>Route</name><LineString><coordinates>
        77.5946,12.9716,0 77.5960,12.9730,0
      </coordinates></LineString></Placemark>
      <Placemark><name>Marker</name><Point><coordinates>77.5946,12.9716,0</coordinates></Point></Placemark>
    </Document></kml>'''
