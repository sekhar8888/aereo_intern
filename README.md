# Geospatial File Measurement API

A FastAPI service that accepts zipped Shapefiles and KML, stores uploaded files and processed feature data in a local SQLite database, and reports polygon area and line length in metric units.

## Requirements

- Python 3.10 or newer
- GDAL support for the KML driver (`KML` or `LIBKML`). The `pyogrio` wheels usually bundle GDAL, but available drivers vary by platform.

## Run locally

```bash
python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
uvicorn main:app --reload
```

The service listens at `http://127.0.0.1:8000`. Interactive API documentation is available at `/docs`; a health check is available at `/health`.

Configuration:

- `GEOSPATIAL_DATA_DIR`: directory for the SQLite database and uploaded files (defaults to `./data`).
- `MAX_UPLOAD_BYTES`: maximum upload size in bytes (defaults to 52,428,800 bytes / 50 MiB).

## API

### Upload and process a file

`POST /api/files/` accepts a multipart form field named `file`. Supported inputs are `.kml` files and `.zip` archives containing a readable vector layer, typically a Shapefile. A Shapefile archive should include its `.shp`, `.shx`, `.dbf`, and `.prj` files.

```bash
curl -X POST http://127.0.0.1:8000/api/files/ \
  -F "file=@survey.kml"
```

Example response (`201 Created`):

```json
{
  "id": "a5e8c8e8-d780-4aa1-8bbc-35bb0a541d30",
  "filename": "survey.kml",
  "feature_count": 2,
  "crs": "EPSG:4326",
  "measurement_crs": "EPSG:32643",
  "status": "COMPLETED",
  "created_at": "2026-10-08T12:00:00+00:00"
}
```

The processing is synchronous: a successful upload response means processing has completed. Invalid or unprocessable files return `422`; unsupported file extensions return `415`; oversized uploads return `413`.

### Get file information

`GET /api/files/{id}/` returns the file metadata, feature count, source CRS, and measurement CRS.

### Get feature measurements

`GET /api/files/{id}/measurements/` returns each feature's zero-based index, geometry type, original geometry, CRS, properties, and applicable measurement. Polygon and MultiPolygon features include `area_m2`; LineString and MultiLineString features include `length_m`. Point features have a `null` measurement. Other geometry types are returned without a measurement and include a note.

```bash
curl http://127.0.0.1:8000/api/files/a5e8c8e8-d780-4aa1-8bbc-35bb0a541d30/measurements/
```

Example feature:

```json
{
  "feature_index": 0,
  "geometry_type": "Polygon",
  "geometry": {"type": "Polygon", "coordinates": []},
  "crs": "EPSG:4326",
  "properties": {"name": "field A"},
  "measurement": {"area_m2": 2459.23}
}
```

Unknown file IDs return `404`.

## Architecture

- `main.py` defines the FastAPI routes, upload handling, geospatial processing, and SQLite persistence.
- `data/uploads/` stores uploads under generated UUID names; the original filename is retained as metadata only.
- `data/measurements.sqlite3` stores file metadata and the processed feature response. SQLite and the data directory are created automatically.

Upload flow: validate extension and size, save the input under a generated name, read its vector layer through GeoPandas and Pyogrio, normalize CRS metadata, calculate feature measurements, and save the completed result. ZIP contents are read by GDAL without manually extracting archive paths. Failed inputs are removed and are not recorded as completed files.

## Measurement and CRS decisions

Geometries and properties in responses remain in their source coordinate system. Measurements use a projected CRS: geographic data is reprojected to the UTM zone estimated from its extent, with EPSG:6933 as a fallback when UTM cannot be estimated. Projected data is measured in its existing CRS. The CRS axis unit conversion factor is applied so lengths are returned in meters and areas in square meters, including for projected CRSs whose units are feet.

UTM is suitable for local data, not for large regions spanning multiple zones or the world. For those datasets, select a projection appropriate to the application's region and whether area or distance accuracy matters most. The service calculates planar geometry measurements; it does not repair invalid geometries or compute geodesic measurements.

## Learning and future scope

This project demonstrates multipart uploads, geospatial vector reading, CRS-aware measurements, API design, and lightweight persistence. Future work could add background processing for large files, configurable projection policies, streaming/pagination for large feature sets, authentication, retention controls, support for additional formats, and deployment guidance for managed storage and a production database.

## Design decisions

- **FastAPI:** provides a small typed API and generated OpenAPI documentation with little framework overhead.
- **GeoPandas, Pyogrio, Shapely, and PyProj:** provide vector file access, geometry operations, CRS transformation, and area/length calculations.
- **SQLite:** keeps the example self-contained and persistent across restarts without a separate database service. The database stores processed features, so response reads do not need to reprocess source files.
- **Synchronous processing:** keeps status handling straightforward for an assignment-sized service. Very large files should move to a background job queue.
- **Local UTM for geographic inputs:** provides reasonable metric measurements for typical local survey data. A single automatically chosen UTM zone is not appropriate for global or very large extents.

