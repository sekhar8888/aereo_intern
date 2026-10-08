from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import pyogrio
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pyproj import CRS
from shapely.geometry import mapping


APP_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("GEOSPATIAL_DATA_DIR", APP_DIR / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "measurements.sqlite3"
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", 50 * 1024 * 1024))
CHUNK_SIZE = 1024 * 1024

app = FastAPI(
    title="Geospatial File Measurement API",
    description="Upload Shapefile ZIPs or KML files and inspect feature measurements.",
    version="1.0.0",
)


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def initialize_database() -> None:
    with closing(connect()) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS files (
                id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                feature_count INTEGER NOT NULL,
                crs TEXT NOT NULL,
                measurement_crs TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                features_json TEXT NOT NULL
            )"""
        )
        conn.commit()


@app.on_event("startup")
def startup() -> None:
    initialize_database()


def public_file(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "filename": row["filename"],
        "feature_count": row["feature_count"],
        "crs": row["crs"],
        "measurement_crs": row["measurement_crs"],
        "status": row["status"],
        "created_at": row["created_at"],
    }


def read_geospatial_file(path: Path, suffix: str) -> gpd.GeoDataFrame:
    if suffix == ".zip":
        try:
            layers = pyogrio.list_layers(path)
        except Exception as exc:
            raise ValueError("The ZIP could not be read as a Shapefile archive.") from exc
        if len(layers) == 0:
            raise ValueError("The ZIP archive does not contain a readable vector layer.")
        return gpd.read_file(path, engine="pyogrio")

    drivers = pyogrio.list_drivers(read=True)
    if "KML" not in drivers and "LIBKML" not in drivers:
        raise ValueError("This installation of GDAL does not include a KML reader.")
    driver = "LIBKML" if "LIBKML" in drivers else "KML"
    return gpd.read_file(path, driver=driver, engine="pyogrio")


def normalize_crs(frame: gpd.GeoDataFrame, suffix: str) -> gpd.GeoDataFrame:
    # KML coordinates are WGS84 longitude/latitude by specification. Some GDAL builds
    # do not attach that CRS when opening a KML, so supply it only when absent.
    if frame.crs is None and suffix == ".kml":
        frame = frame.set_crs("EPSG:4326")
    if frame.crs is None:
        raise ValueError("The file has no CRS. Add a CRS to the source data and upload again.")
    return frame


def choose_measurement_frame(frame: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, CRS]:
    source_crs = CRS.from_user_input(frame.crs)
    if source_crs.is_geographic:
        try:
            target = frame.estimate_utm_crs()
        except Exception:
            target = None
        # UTM is suitable for local datasets. Equal-area projection is a safe fallback
        # when an appropriate UTM zone cannot be estimated (for example, polar data).
        target_crs = CRS.from_user_input(target or "EPSG:6933")
        return frame.to_crs(target_crs), target_crs
    if not source_crs.is_projected:
        raise ValueError("Only geographic or projected coordinate reference systems are supported.")
    return frame, source_crs


def axis_to_meters(crs: CRS) -> float:
    if not crs.axis_info:
        return 1.0
    factor = crs.axis_info[0].unit_conversion_factor
    return float(factor or 1.0)


def serializable(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def process_file(path: Path, suffix: str) -> tuple[list[dict[str, Any]], str, str]:
    try:
        frame = read_geospatial_file(path, suffix)
        frame = normalize_crs(frame, suffix)
        source_crs = CRS.from_user_input(frame.crs)
        measured, measurement_crs = choose_measurement_frame(frame)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Could not process the geospatial file: {exc}") from exc

    factor = axis_to_meters(measurement_crs)
    features: list[dict[str, Any]] = []
    for index, source_row in enumerate(frame.iterfeatures()):
        geometry = source_row.get("geometry")
        shapely_geometry = measured.geometry.iloc[index]
        geom_type = shapely_geometry.geom_type if shapely_geometry is not None else "GeometryCollection"
        feature: dict[str, Any] = {
            "feature_index": index,
            "geometry_type": geom_type,
            "geometry": geometry,
            "crs": source_crs.to_string(),
            "properties": {key: serializable(value) for key, value in source_row.get("properties", {}).items()},
            "measurement": None,
        }
        if shapely_geometry is not None and not shapely_geometry.is_empty:
            if geom_type in {"Polygon", "MultiPolygon"}:
                feature["measurement"] = {"area_m2": float(shapely_geometry.area * factor**2)}
            elif geom_type in {"LineString", "MultiLineString", "LinearRing"}:
                feature["measurement"] = {"length_m": float(shapely_geometry.length * factor)}
            elif geom_type in {"Point", "MultiPoint"}:
                feature["measurement"] = None
            else:
                feature["measurement_note"] = "Measurement is not supported for this geometry type."
        else:
            feature["measurement_note"] = "Geometry is empty or missing; no measurement was calculated."
        features.append(feature)

    return features, source_crs.to_string(), measurement_crs.to_string()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/files/", status_code=201)
async def upload_file(file: UploadFile = File(...)) -> JSONResponse:
    filename = Path(file.filename or "upload").name
    suffix = Path(filename).suffix.lower()
    if suffix not in {".zip", ".kml"}:
        raise HTTPException(status_code=415, detail="Supported uploads are .zip Shapefile archives and .kml files.")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    file_id = str(uuid.uuid4())
    stored_path = UPLOAD_DIR / f"{file_id}{suffix}"
    size = 0
    try:
        with stored_path.open("wb") as destination:
            while chunk := await file.read(CHUNK_SIZE):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail=f"Upload exceeds the {MAX_UPLOAD_BYTES}-byte limit.")
                destination.write(chunk)
        if size == 0:
            raise HTTPException(status_code=400, detail="The uploaded file is empty.")

        features, crs, measurement_crs = process_file(stored_path, suffix)
        created_at = datetime.now(timezone.utc).isoformat()
        with closing(connect()) as conn:
            conn.execute(
                "INSERT INTO files VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (file_id, filename, str(stored_path), len(features), crs, measurement_crs, "COMPLETED", created_at, json.dumps(features, allow_nan=False)),
            )
            conn.commit()
        return JSONResponse(status_code=201, content={
            "id": file_id,
            "filename": filename,
            "feature_count": len(features),
            "crs": crs,
            "measurement_crs": measurement_crs,
            "status": "COMPLETED",
            "created_at": created_at,
        })
    except HTTPException:
        stored_path.unlink(missing_ok=True)
        raise
    except ValueError as exc:
        stored_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        stored_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="File processing failed.") from exc
    finally:
        await file.close()


@app.get("/api/files/{file_id}/")
def get_file(file_id: str) -> dict[str, Any]:
    with closing(connect()) as conn:
        row = conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="File not found.")
    return public_file(row)


@app.get("/api/files/{file_id}/measurements/")
def get_measurements(file_id: str) -> dict[str, Any]:
    with closing(connect()) as conn:
        row = conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="File not found.")
    return {
        "file_id": row["id"],
        "filename": row["filename"],
        "crs": row["crs"],
        "measurement_crs": row["measurement_crs"],
        "feature_count": row["feature_count"],
        "features": json.loads(row["features_json"]),
    }
