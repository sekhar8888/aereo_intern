# Aereo Internship Backend Projects

This repository contains two independent backend assignments:

- **Geospatial File Measurement API** — uploads geospatial files, stores file metadata in SQLite, and returns feature measurements.
- **Bulk Certificate Generator API** — validates bulk recipient requests and generates downloadable PDF certificates.

Each project has its own setup guide and runtime dependencies.

## Repository layout

| Path | Purpose |
| --- | --- |
| \`main.py\`, root \`requirements.txt\` | Geospatial measurement API |
| \`examples/measurement_sample.kml\` | Sample input for the geospatial API |
| \`tests/\`, root \`requirements-dev.txt\` | Geospatial API test suite and development dependencies |
| \`bulk_certificate/\` | Certificate generator API and its own README, requirements, and tests |

## Geospatial Measurement API

The service accepts KML, GeoJSON, and zipped Shapefile uploads. It retains the source CRS in results and measures polygon area and line length in metric units. Uploads and metadata are stored locally under \`data/\`.

### Run on Windows

In PowerShell, change to the repository root—the folder containing \`main.py\`—then run:

\`\`\`powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload
\`\`\`

If PowerShell blocks activation, run \`Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass\` in that window and activate the environment again.

### Run on macOS or Linux

\`\`\`bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload
\`\`\`

The API is available at [http://127.0.0.1:8000](http://127.0.0.1:8000). Interactive endpoint documentation is at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs), and the health endpoint is [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health).

### Upload and measure the sample

With the server running, open a second terminal in the repository root and upload the included KML. It contains a polygon, a route, and a point near Bengaluru.

\`\`\`powershell
curl.exe -X POST http://127.0.0.1:8000/api/files/ -F "file=@examples/measurement_sample.kml"
\`\`\`

Copy the \`id\` from the upload response and substitute it for \`YOUR_FILE_ID\`:

\`\`\`powershell
curl.exe http://127.0.0.1:8000/api/files/YOUR_FILE_ID/measurements/
\`\`\`

Polygon results include \`area_m2\`; line results include \`length_m\`. Point features are returned without an area or length measurement. To process another file, replace the sample path in the upload command with the path to your file.

### Dependencies

The requirements files are separated by application and purpose:

- Root \`requirements.txt\` installs runtime dependencies for the geospatial API.
- \`bulk_certificate/requirements.txt\` installs runtime dependencies for the certificate generator. Run that app from the \`bulk_certificate/\` directory and follow its [README](bulk_certificate/README.md).
- Root \`requirements-dev.txt\` includes geospatial runtime dependencies and development/test tools, including pytest and httpx.

Use the requirements file for the application you are running. The two APIs can use separate virtual environments.

### Run geospatial tests

From the repository root:

\`\`\`powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q tests/
\`\`\`

### Measurement and input notes

For geographic data, the service selects a local UTM measurement CRS and reports it in the response. Measurements are planar and best suited to local or regional datasets. A Shapefile must be uploaded as a ZIP containing matching \`.shp\`, \`.shx\`, and \`.dbf\` files; including the \`.prj\` file is recommended.

## Bulk Certificate Generator API

The certificate generator is maintained as a separate project in [\`bulk_certificate/\`](bulk_certificate/). Its README documents its setup, endpoints, and examples. Install its dependencies from that directory with \`python -m pip install -r requirements.txt\`.
