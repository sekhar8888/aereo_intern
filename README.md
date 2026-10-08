# Backend Assignment Projects

This repository contains two standalone Python API projects. Each folder has its own dependencies, setup instructions, API examples, and design notes.

## Projects

### Geospatial File Measurement API

[`/`](.) contains a FastAPI service for `.kml` uploads and zipped Shapefiles. It returns feature geometry and attributes, calculates polygon area and line length in metric units, handles unsupported geometry types, and stores results in SQLite.

- Setup and endpoint guide: [README](README.md)
- Tests: `tests/`
- Run locally: `python -m pip install -r requirements.txt` followed by `uvicorn main:app --reload`
- Run tests: install `requirements-dev.txt`, then run `python -m pytest -q`

### Bulk Certificate Generator API

[`bulk_certificate/`](bulk_certificate/) contains a separate FastAPI service that validates bulk recipient requests, tracks per-recipient outcomes in SQLite, generates PDF certificates, and serves each completed certificate for download.

- Setup, request examples, and design notes: [bulk_certificate/README.md](bulk_certificate/README.md)
- Run locally from that folder: `python -m pip install -r requirements.txt` followed by `uvicorn main:app --reload`
- Run its tests from that folder: `pytest`

## Geospatial API design notes

The geospatial service keeps returned geometry in the source CRS and transforms geographic inputs to a projected CRS for planar measurements. It estimates a local UTM CRS and reports the chosen CRS in each file response. Lengths and areas are converted to meters and square meters, including when projected source coordinates use feet.

The upload endpoint limits file size, ZIP member count, archive expansion size, and feature count. Shapefile archives must contain exactly one `.shp` plus matching `.shx` and `.dbf` sidecars; a `.prj` file should be included so the CRS can be identified. Archive paths are checked, uploads are assigned generated storage names, and non-finite attribute values are represented as JSON `null`.

Defaults can be adjusted with `MAX_UPLOAD_BYTES` (50 MiB), `MAX_FEATURES` (25,000), `MAX_ZIP_MEMBERS` (10,000), and `MAX_ZIP_UNCOMPRESSED_BYTES` (250 MiB). `GEOSPATIAL_DATA_DIR` changes where uploaded files and the SQLite database are stored.

UTM is suitable for local data and can be inaccurate for datasets spanning large regions or multiple zones. The service reports its measurement CRS so clients can assess the result. Processing is synchronous and uses SQLite/local disk, which keeps local setup simple; larger deployments would benefit from background workers, pagination, object storage, and a production database.

## Automated checks

Install the test dependencies with `python -m pip install -r requirements-dev.txt`, then run `python -m pytest -q`. The suite exercises KML and zipped Shapefile uploads, measurement and CRS behavior, point and unsupported geometry handling, error responses, archive/file limits, and JSON-safe attributes. The GitHub Actions workflow runs these checks on relevant pushes and pull requests.

## Local data

Uploaded geospatial files, generated certificate PDFs, SQLite databases, virtual environments, and sample input files are excluded through `.gitignore` rules and should not be committed.
