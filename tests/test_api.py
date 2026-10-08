from __future__ import annotations

import io
import math
import zipfile

import geopandas as gpd
from fastapi.testclient import TestClient
from shapely.geometry import GeometryCollection, LineString, Point, Polygon

import main


def test_kml_upload_reports_area_length_point_and_crs(client: TestClient, sample_kml: bytes):
    response = client.post("/api/files/", files={"file": ("survey.kml", sample_kml, "application/vnd.google-earth.kml+xml")})
    assert response.status_code == 201
    uploaded = response.json()
    assert uploaded["status"] == "COMPLETED"
    assert uploaded["feature_count"] == 3
    assert uploaded["crs"] == "EPSG:4326"
    assert uploaded["measurement_crs"] != uploaded["crs"]

    result = client.get(f"/api/files/{uploaded['id']}/measurements/")
    assert result.status_code == 200
    features = result.json()["features"]
    by_type = {feature["geometry_type"]: feature for feature in features}
    assert by_type["Polygon"]["measurement"]["area_m2"] > 10_000
    assert by_type["LineString"]["measurement"]["length_m"] > 100
    assert by_type["Point"]["measurement"] is None
    assert client.get(f"/api/files/{uploaded['id']}/").json()["feature_count"] == 3


def test_shapefile_zip_upload(client: TestClient, tmp_path):
    shape_path = tmp_path / "parcel.shp"
    frame = gpd.GeoDataFrame(
        {"label": ["parcel"]},
        geometry=[Polygon([(500000, 4400000), (500100, 4400000), (500100, 4400100), (500000, 4400100)])],
        crs="EPSG:32631",
    )
    frame.to_file(shape_path, engine="pyogrio")
    archive_path = tmp_path / "parcel.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for sidecar in tmp_path.glob("parcel.*"):
            if sidecar.suffix != ".zip":
                archive.write(sidecar, arcname=sidecar.name)

    response = client.post("/api/files/", files={"file": ("parcel.zip", archive_path.read_bytes(), "application/zip")})
    assert response.status_code == 201
    assert response.json()["feature_count"] == 1
    measurements = client.get(f"/api/files/{response.json()['id']}/measurements/").json()
    assert measurements["features"][0]["measurement"]["area_m2"] == 10_000


def test_rejects_unsupported_empty_and_invalid_zip_uploads(client: TestClient):
    unsupported = client.post("/api/files/", files={"file": ("data.geojson", b"{}", "application/json")})
    assert unsupported.status_code == 415
    empty = client.post("/api/files/", files={"file": ("empty.kml", b"", "application/xml")})
    assert empty.status_code == 400
    bad_zip = io.BytesIO()
    with zipfile.ZipFile(bad_zip, "w") as archive:
        archive.writestr("readme.txt", "not a Shapefile")
    rejected = client.post("/api/files/", files={"file": ("bad.zip", bad_zip.getvalue(), "application/zip")})
    assert rejected.status_code == 422
    assert "Shapefile" in rejected.json()["detail"]


def test_enforces_upload_and_feature_limits(client: TestClient, sample_kml: bytes, monkeypatch):
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 10)
    oversized = client.post("/api/files/", files={"file": ("survey.kml", sample_kml, "application/xml")})
    assert oversized.status_code == 413

    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 1024 * 1024)
    monkeypatch.setattr(main, "MAX_FEATURES", 2)
    too_many = client.post("/api/files/", files={"file": ("survey.kml", sample_kml, "application/xml")})
    assert too_many.status_code == 422
    assert "limit is 2" in too_many.json()["detail"]


def test_non_finite_properties_become_json_null():
    assert main.serializable(float("nan")) is None
    assert main.serializable(float("inf")) is None
    assert main.serializable({"nested": [1, float("nan")]}) == {"nested": [1, None]}


def test_unknown_file_id_returns_404(client: TestClient):
    assert client.get("/api/files/not-a-real-id/").status_code == 404
    assert client.get("/api/files/not-a-real-id/measurements/").status_code == 404


def test_crs_axis_units_are_converted_to_meters():
    feet_crs = main.CRS.from_epsg(2263)
    assert math.isclose(main.axis_to_meters(feet_crs), 0.3048006096012192, rel_tol=1e-12)


def test_unsupported_geometry_does_not_crash(monkeypatch, tmp_path):
    frame = gpd.GeoDataFrame(
        geometry=[GeometryCollection([Point(0, 0), LineString([(0, 0), (1, 1)])])],
        crs="EPSG:4326",
    )
    monkeypatch.setattr(main, "read_geospatial_file", lambda path, suffix: frame)
    features, _, _ = main.process_file(tmp_path / "unused.kml", ".kml")
    assert features[0]["measurement"] is None
    assert "not supported" in features[0]["measurement_note"]
