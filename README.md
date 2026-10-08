# Geospatial File Measurement API

A FastAPI service that accepts KML, GeoJSON, and Shapefile uploads, stores file metadata in SQLite, and returns geometry measurements in meters. This repository also contains the separate `bulk_certificate` assignment; each API has its own dependencies.

## Geospatial API: run on Windows

Open PowerShell in the repository root (the folder containing `main.py`) and run:

```powershell
py -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload
```

If PowerShell blocks virtual environment activation, run this once in that PowerShell window, then activate again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

The service runs at `http://127.0.0.1:8000`. Open `http://127.0.0.1:8000/docs` for interactive API documentation, or `http://127.0.0.1:8000/health` for the health check. The SQLite database and uploaded-file storage are created under `data/` when the app runs.

### Run on macOS or Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload
```

## Try the included sample KML

With the server running, open a second terminal in the repository root and upload the included file. It contains a polygon, a route, and a point around Bengaluru:

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/files/ -F "file=@examples/measurement_sample.kml"
```

The response includes an `id`. Use that value to retrieve the parsed features and measurements (replace `<FILE_ID>` with the returned id):

```powershell
curl.exe http://127.0.0.1:8000/api/files/<FILE_ID>/measurements/
```

The API reports polygon area as `area_m2` and line length as `length_m`. Point features are returned without an area or length measurement. You can also upload your own supported file by replacing the sample path, for example `-F "file=@C:\\path\\to\\your-file.kml"`.

## Dependencies: why there are two requirements files

There are two independent applications in this repository, so each has its own runtime dependency list:

- Root [`requirements.txt`](requirements.txt): runtime packages for the geospatial measurement API in `main.py`.
- [`bulk_certificate/requirements.txt`](bulk_certificate/requirements.txt): runtime packages for the certificate generator in the `bulk_certificate/` folder. Install this file when running that app from its folder.
- Root [`requirements-dev.txt`](requirements-dev.txt): includes the geospatial runtime dependencies plus development/test tools such as pytest and httpx. Use it when you want to run the geospatial project's tests.

Do not install both app requirement files into one environment unless you specifically need both applications in that environment. For the certificate API's own setup instructions, see [`bulk_certificate/README.md`](bulk_certificate/README.md).

## Geospatial tests

From the repository root, install development dependencies and run:

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q tests/
```

## Measurement and format notes

The source CRS is retained in API results. Measurements use a projected CRS in meters; for geographic source data, the service selects a UTM zone based on the input geometry. Measurements are planar, and the selected UTM CRS is most appropriate for local/regional datasets. Shapefiles should be uploaded as a ZIP containing the required companion files (`.shp`, `.shx`, and `.dbf`, with `.prj` recommended).
