# Voltscope

Structured extraction and deterministic validation for UK commercial energy
bills. The bill-intelligence module of VoltEdge. MIT licensed.

Point it at a folder of supplier bills (PDFs or images). For each one it:

1. sends the file to Claude for structured field extraction,
2. parses the reply into a fixed JSON schema (never guessing missing fields),
3. runs a set of deterministic validation / anomaly checks,
4. writes one JSON file per bill to the output directory and prints a summary.

The question this answers is a single one: **can AI reliably extract the
critical fields from real, messy commercial energy bills?** Read the
`low_confidence_fields` and the FLAGS in the output, and spot-check the JSON
against the real bill. Extraction accuracy on the money fields is the product.

A one-page overview is in [docs/Voltscope_Executive_Summary.pdf](docs/Voltscope_Executive_Summary.pdf).

## Quick start

```bash
git clone https://github.com/ShazMoghaddam/voltscope.git
cd voltscope
./run.sh                 # creates the venv, installs deps, starts the app
```

Open http://127.0.0.1:8000. To explore the review, dashboard, and insights on
sample data without an API key:

```bash
source .venv/bin/activate
python seed_demo.py      # loads the bundled example bills
```

For live extraction of your own bills, copy `.env.example` to `.env` and add your
Anthropic API key. Run the tests with `python -m pytest`.

## Layout

```
voltscope/
  voltscope/
    config.py            # Settings loaded from env / .env
    models.py            # Pydantic schema for extracted bills
    prompts/
      extraction_system.txt   # the extraction system prompt (edit this)
    extractor.py         # Anthropic call, file encoding, JSON parsing
    validator.py         # deterministic checks (behaviour frozen in seg 1)
    logging_config.py    # structured logging
    cli.py               # the ./bills -> ./out batch loop + report
  tests/
    fixtures/            # golden input bills + expected flag lists
    test_validator.py
  extract.py             # compatibility shim: `python extract.py` still works
  requirements.txt
  requirements-dev.txt
  .env.example
```

## Usage

```bash
pip install -r requirements.txt
cp .env.example .env      # then edit ANTHROPIC_API_KEY
# drop bills into ./bills/
python extract.py         # or: python -m voltscope
```

## Configuration

| Variable              | Default            | Purpose                        |
|-----------------------|--------------------|--------------------------------|
| `ANTHROPIC_API_KEY`   | (required)         | Anthropic API key              |
| `VOLTSCOPE_MODEL`     | `claude-opus-4-8`  | Extraction model               |
| `VOLTSCOPE_BILLS_DIR` | `bills`            | Input folder                   |
| `VOLTSCOPE_OUT_DIR`   | `out`              | Output folder                  |
| `VOLTSCOPE_LOG_LEVEL` | `INFO`             | Log verbosity                  |

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

The tests are golden-file tests over the validator: each fixture bill is paired
with the exact list of flag strings it must produce. They freeze current
behaviour so later refactors (segment 2 onward) can prove they changed nothing.
Extraction output is model-driven and is checked by hand against real bills, not
asserted here.

## Validation engine (segment 2)

Validation is now a registry of independent, single-rule check modules under
`voltscope/checks/`. Each check is a function `(bill) -> list[Finding]`
decorated with `@register`; the engine runs every registered check and
concatenates the results. Adding a rule is a one-file change with no edit to the
engine.

Each `Finding` (see `models.py`) carries:

| field            | meaning                                             |
|------------------|-----------------------------------------------------|
| `severity`       | `INFO`, `WARNING`, or `ERROR`                        |
| `category`       | completeness / contract / meter / reads / charges / totals / extraction_quality |
| `code`           | stable machine identifier (e.g. `mpan_digit_count`) |
| `message`        | human-readable line                                 |
| `affected_field` | JSON path into the bill, where applicable           |
| `recommendation` | what to do about it                                 |

Current checks: missing required fields, missing supply points, contract
renewal window, MPAN digit count, estimated reads, duplicate charges, subtotal
reconciliation, VAT (new), and extractor low-confidence fields.

Two deliberate changes from segment 1, both covered by tests:

* **VAT check (additive).** Flags `subtotal + VAT != total` (WARNING) and an
  implied VAT rate that is not a standard 0/5/20% (INFO). It stays silent on a
  well-formed bill, so it does not disturb the frozen fixtures.
* **ISO date fix.** `parse_date` now tries a strict `YYYY-MM-DD` parse before the
  day-first heuristic, fixing a latent bug where ISO contract dates with a day
  of 12 or less were mis-parsed and the renewal window silently missed.

### Adding a check

Create `voltscope/checks/my_rule.py`:

```python
from ..models import Category, Finding, Severity
from .base import register

@register
def check_my_rule(bill):
    findings = []
    # ... inspect bill, append Finding(...) as needed ...
    return findings
```

Then add `from . import my_rule` to `voltscope/checks/__init__.py` at the
position you want it to run. The engine and CLI pick it up automatically.

### Compatibility

`voltscope/validator.py` keeps the segment 1 surface: `check_bill(bill)` still
returns a flat list of flag strings (now projected from the findings), and
`parse_date` is re-exported. The golden tests assert this projection reproduces
the original flags exactly.

## Review app (segment 3)

A lightweight FastAPI app for uploading bills, reviewing extracted fields beside
their validation findings, correcting fields, and exporting.

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...   # needed for uploads to extract
python -m voltscope.api               # serves http://127.0.0.1:8000
```

Open the URL, drag bills onto the drop zone (or click to choose), then select a
bill to see its fields and findings. Editing a field and pressing **Save
changes** re-runs validation, so findings update against the corrected data.
Export a single bill as JSON or Excel, or the whole batch as Excel.

The server still starts without an API key; it warns in the UI and uploads
return a clear error, but viewing, editing, and exporting existing records work.

### Shape of it

* `api/store.py` defines a `BillStore` interface with an in-memory implementation.
  The app depends only on the interface, so segment 4 swaps in a SQLite store
  without touching routes, service, or frontend.
* `api/service.py` holds the orchestration and takes an injected `extract_fn`,
  so the API is testable without a live Anthropic key (the tests pass a stub).
* `api/exporters.py` builds the JSON and Excel outputs (four sheets: Bills,
  Supply Points, Charges, Findings).
* `api/static/index.html` is the whole frontend: one file, vanilla JS, no build
  step, deliberately plain.

### Endpoints

| Method | Path                            | Purpose                     |
|--------|---------------------------------|-----------------------------|
| POST   | `/api/bills`                    | Upload one or more bills    |
| GET    | `/api/bills`                    | List records                |
| GET    | `/api/bills/{id}`               | One record                  |
| PUT    | `/api/bills/{id}`               | Save edits, re-validate     |
| DELETE | `/api/bills/{id}`               | Remove a record             |
| GET    | `/api/bills/{id}/export.json`   | Export one record as JSON   |
| GET    | `/api/bills/{id}/export.xlsx`   | Export one record as Excel  |
| GET    | `/api/export.xlsx`              | Export all records as Excel |

Records live in memory only until segment 4 adds persistence.

## Persistence & dashboard (segment 4)

Records now persist in SQLite. `api/sqlite_store.py` implements the same
`BillStore` interface the app already depended on, so segment 4 is a one-line
swap in `create_app` with no change to the routes, service, or frontend. The
default database is `./voltscope.db` (override with `VOLTSCOPE_DB`).

What is stored: each bill's scalar fields and full extracted JSON, its findings
(in a `findings` table), and a `history` table of processing events (processed,
edited, failed, deleted). Deleting a bill cascades its findings but leaves its
history as an audit trail.

The **Dashboard** tab in the UI (and `GET /api/dashboard`) shows status and
severity totals, total spend, a per-supplier breakdown, and contracts renewing
within the switching window. `GET /api/history` returns recent activity.

Run it exactly as before; the database is created on first run:

```bash
python -m voltscope.api        # uses ./voltscope.db, survives restarts
```

For a direct uvicorn invocation, use the factory form (keeps imports
side-effect free):

```bash
uvicorn --factory voltscope.api.app:get_app
```

### New endpoints

| Method | Path             | Purpose                          |
|--------|------------------|----------------------------------|
| GET    | `/api/dashboard` | Portfolio aggregates             |
| GET    | `/api/history`   | Recent processing events         |

## Commercialisation (segment 5)

### Export formats

Alongside JSON and Excel, records export as CSV:

| Path                              | Output                                        |
|-----------------------------------|-----------------------------------------------|
| `GET /api/export.csv?sheet=bills` | One row per bill (default sheet)               |
| `GET /api/export.csv?sheet=findings` | One row per finding                         |
| `GET /api/export.csv?sheet=supply_points` / `charges` | The other flattenings      |
| `GET /api/bills/{id}/export.csv`  | A single bill's row                            |

Excel (`.xlsx`) and CSV share the same flattening code, so the formats never
diverge.

### Authentication

Set `VOLTSCOPE_API_KEYS` to one or more comma-separated keys to require an
`X-API-Key` header on every `/api` route except `/api/health`. Left unset, the
API runs open (handy for local development) and logs a warning. The bundled UI
prompts for a key when the server reports that auth is required.

```bash
export VOLTSCOPE_API_KEYS="key-for-partner-a,key-for-partner-b"
curl -H "X-API-Key: key-for-partner-a" http://localhost:8000/api/bills
```

### API documentation

Interactive OpenAPI docs are served at `/docs` (Swagger UI) and `/redoc`, with
the raw spec at `/openapi.json`. Response models carry examples, and the
`X-API-Key` scheme is advertised so the docs get an Authorize button.

### Deploying to Render

`render.yaml` is a Blueprint: in the Render dashboard choose New -> Blueprint and
point it at the repo. It provisions a web service, a health check at
`/api/health`, and a 1 GB disk mounted at `/data` so the SQLite database
survives restarts and deploys. Set `ANTHROPIC_API_KEY` and `VOLTSCOPE_API_KEYS`
as secrets in the dashboard.

```
Build:  pip install -r requirements.txt
Start:  uvicorn --factory voltscope.api.app:get_app --host 0.0.0.0 --port $PORT
```

A `Dockerfile` is included for container-based deploys (it expands `$PORT` and
defaults the database to `/data/voltscope.db`).

Two honest limitations to plan around: the free Render plan has an ephemeral
filesystem, so without a paid instance and the disk the database resets on each
deploy; and SQLite is single-instance, so scaling past one web instance means
moving to a managed Postgres.

## Intelligence layer (segment 6)

Deterministic portfolio analytics over the stored records, no LLM calls. Served
at `GET /api/intelligence` and shown under the **Insights** tab. The report has
eight sections:

* **Alerts** — a severity-ordered "needs attention" summary synthesised from the
  sections below (error-level bills, renewals due, estimated reads, duplicate
  charges, high rates).
* **Renewals** — contracts inside the switching window, with an urgency of ERROR
  (≤30 days), WARNING (≤60), or INFO.
* **Estimated reads** — every site currently billed on an estimate.
* **Duplicate charges** — repeated charge lines within a bill, with the suspected
  overcharge (amount × extra copies) quantified.
* **High unit rates** — rate lines above `VOLTSCOPE_HIGH_RATE_MULTIPLIER` times the
  portfolio median for that fuel (default 1.3×). The baseline is portfolio-relative
  and needs at least three rates for a fuel before it flags anything.
* **Spend summary** — total and average spend, broken down by supplier and by
  invoice month.
* **Supplier comparison** — per supplier: bills, spend, average unit rate per fuel,
  average standing charge, estimated-read bills, and error-finding count.
* **Portfolio statistics** — bills, sites, suppliers, total spend, total
  consumption, average rates, status and severity breakdowns, invoice date range.

The boundary with validation (segment 2) is deliberate: validation answers "is
this one bill correct?"; intelligence answers "what does the whole portfolio, over
time, tell me?". Where the two overlap (renewals, estimated reads, duplicates), the
per-bill validation findings remain the source of truth, and this layer recomputes
from the same structured data to produce richer, quantified, cross-bill output.

"High unit rate" is defined against a portfolio-relative baseline rather than a
fixed number, so it adapts as the portfolio grows and does not need a hard-coded
price that would date quickly. Tune the sensitivity with
`VOLTSCOPE_HIGH_RATE_MULTIPLIER`.

## HEIC input and the real-bill anchor

The extractor now accepts iPhone **HEIC/HEIF** photos in addition to PDF, PNG,
JPG, WEBP and GIF. HEIC is converted to JPEG before extraction (the API does not
accept HEIC directly), needing `pillow` and `pillow-heif` from requirements.

`tests/fixtures/real_ovo_bill.json` is a genuine OVO domestic dual-fuel bill,
transcribed into the schema with all personal identifiers replaced by synthetic
stand-ins. It joins the golden validator suite and is the project's first
real-world anchor: on this clean bill the money fields reconcile, the MPAN is 13
digits, VAT checks out, and the only finding raised is the contract-renewal
alert (the fixed term ends inside the switching window).

## Non-energy bill detection

Voltscope is scoped to electricity and gas. A non-energy document (a water bill,
say) still runs through extraction, but the validator now flags it: when a bill
has supply points yet none carry an energy signal (no electricity/gas fuel type,
no MPAN/MPRN, no p/kWh unit rate, no kWh reading), the `not_energy_bill` finding
fires as a WARNING so the extracted fields are not trusted. This is deterministic
and needs no extra model call. `tests/fixtures/water_bill.json`, modelled on a
real Thames Water bill, anchors it.

## Multi-page bills

A single bill photographed across several images is extracted as one bill three ways:

* **Review app** — tick "Combine files into one bill" before dropping the pages.
* **API** — `POST /api/bills?merge=true` treats all files in the request as one bill.
* **CLI** — put the pages in a sub-folder of `bills/`; each sub-folder becomes one
  bill (pages ordered by filename), while loose files stay one bill each.

Under the hood the pages are sent to the model together in a single request, so
it reads the whole bill at once rather than extracting disconnected fragments.
