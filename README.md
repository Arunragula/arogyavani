# CuraVault AI

CuraVault AI is a health-literacy web application for reviewing medical reports
and prescriptions. It extracts text from uploaded PDFs and images, removes
selected personal details locally, and asks a Gemini model to explain the
medical content in the selected language. It also provides family profiles,
saved report history, health questions, and speech playback.

> **Medical notice:** This project provides informational explanations, not
> diagnoses or treatment recommendations. AI output and OCR may be inaccurate
> or incomplete. Always confirm medical decisions with a qualified healthcare
> professional. For urgent symptoms, seek appropriate medical care.

## Features

- Upload up to 10 medical files at a time: PDF, JPG, JPEG, PNG, or WEBP.
- Extract selectable PDF text and use OCR for scanned PDFs and images.
- Analyze laboratory/medical reports and prescriptions using Gemini.
- Request explanations in a selected language and translate saved reports.
- Create family member profiles and browse their report timelines.
- Ask health questions with optional context from the selected member's saved
  reports.
- Generate spoken summaries using Edge TTS.
- Store report metadata in SQLite by default, with PostgreSQL support in the
  SQLAlchemy models.
- Avoid repeat analysis for the same member, document category, and file
  contents by caching a document hash.

## Technology

- Python 3.13 or newer
- FastAPI and Uvicorn
- SQLAlchemy and Alembic
- SQLite by default; PostgreSQL and `pgvector` are supported by the model setup
- PyMuPDF, PyMuPDF4LLM, Pillow, and RapidOCR for PDF/text/image extraction
- Google Gemini API for report explanations, translation, Q&A, and embeddings
- Edge TTS for speech generation
- Static HTML, CSS, and JavaScript frontend served by FastAPI

## Project layout

```text
.
├── app/
│   ├── main.py                 # FastAPI pages and API routes
│   ├── db/
│   │   ├── database.py         # Database URL, engine, and SQLAlchemy base
│   │   └── models.py          # Family, report, and Q&A database models
│   ├── schemas/models.py       # Pydantic request/response data models
│   └── services/
│       ├── analyzer.py         # Gemini report analysis, translation, and Q&A
│       ├── db_vector.py        # Persistence, vault files, cache, history
│       ├── embeddings.py       # Report-history embeddings
│       ├── extractor.py        # PDF/image extraction and OCR
│       ├── guardrails.py       # Local document and question checks
│       ├── llm_router.py       # Gemini model fallback chain
│       ├── prescription.py     # Prescription explanation prompt
│       ├── scrubber.py         # Local PII scrubbing and demographics
│       └── voice_tts.py        # Speech generation and language voices
├── alembic/                    # Alembic environment and revision template
├── frontend/
│   ├── assets/                 # CSS, JavaScript, and logo
│   ├── index.html              # Landing page
│   ├── login.html              # Local profile/guest selection
│   └── dashboard.html          # Scanner, vault, and Q&A UI
├── vault_uploads/              # Original uploaded report files
├── generated_audio/            # Generated MP3 files
├── alembic.ini
├── main.py                     # Minimal placeholder module
├── pyproject.toml
└── uv.lock
```

The application entry point is `app.main:app`. The root `main.py` is a small
placeholder and is not the FastAPI server entry point.

## Requirements and local setup

Install Python 3.13+ and [uv](https://docs.astral.sh/uv/). In PowerShell, from
the project directory:

```powershell
uv sync
```

Create a `.env` file in the project directory (or configure these variables in
your process environment):

```dotenv
# Optional. Defaults to SQLite in the project directory.
DATABASE_URL=sqlite:///./health_vault.db

# Required for Gemini report analysis, translations, and health Q&A.
GEMINI_API_KEY=replace-with-your-key

# Optional. Comma-separated Gemini model names tried in order on errors.
# If omitted, the application uses its built-in model chain.
GEMINI_MODEL_CHAIN=gemini-2.5-flash,gemini-2.5-flash-lite
```

Do not commit `.env`, API keys, real patient data, database files, uploaded
reports, or generated audio. `.gitignore` excludes these local files.

Start the development server from the project directory:

```powershell
uv run uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>. Interactive API documentation is available at
<http://127.0.0.1:8000/docs>; the OpenAPI schema is at
<http://127.0.0.1:8000/openapi.json>.

The app uses relative paths for the frontend and local output directories, so
run Uvicorn with the project directory as the working directory.

### Database configuration

The default database is `sqlite:///./health_vault.db`. For PostgreSQL, set
`DATABASE_URL` to a SQLAlchemy-compatible PostgreSQL URL, for example:

```dotenv
DATABASE_URL=postgresql://user:password@localhost:5432/curavault
```

PostgreSQL mode enables the `vector` extension and stores report embeddings as
768-dimensional `pgvector` values. SQLite stores embeddings as JSON. The current
history search calculates a dot-product score over the saved report embeddings
and returns the top three reports for the selected member.

### Alembic migrations

Alembic is configured in `alembic.ini` and `alembic/env.py`. The environment
loads SQLAlchemy metadata from `app.db.models`. At the time this documentation
was written, the `alembic/` directory had no revision files. The application
also calls `Base.metadata.create_all()` and runs a SQLite-specific schema
adjustment when its database service is imported; this is not a replacement for
a reviewed migration history.

After establishing a correct baseline revision for your database, create and
apply future migrations from the project directory:

```powershell
New-Item -ItemType Directory -Force .\alembic\versions
uv run alembic revision --autogenerate -m "describe the schema change"
# Review the generated file under alembic/versions before applying it.
uv run alembic upgrade head
uv run alembic current
```

Autogeneration cannot reliably infer every intent (for example, whether a
column was renamed or dropped). Back up the database and review each revision's
`upgrade()` and `downgrade()` functions. For a database that already contains
tables but has no Alembic history, define and validate a baseline strategy
before applying later migrations; do not blindly stamp or apply a generated
revision to a database with valuable data.

## Application workflow

1. The browser sends the selected files to the report or prescription endpoint.
2. The server enforces the 10-file limit and checks for a cached matching
   document hash.
3. PDF text is extracted directly when available; scanned PDFs and images are
   processed with OCR.
4. Local checks reject documents with insufficient or obviously non-medical
   text. The scrubber removes selected personal details and preserves
   demographics for analysis.
5. The cleaned text is sent to Gemini. A configured model chain is tried in
   order if a model call fails.
6. The result is checked, then report data and original uploaded files are
   saved in the database and `vault_uploads/`.
7. Q&A may retrieve up to three saved reports for the selected family member.
   The answer is stored in the Q&A log.
8. Speech requests generate MP3 files under `generated_audio/`.

The language selection applies to supported analysis/translation and speech
flows. Speech voices are mapped for English, Hindi/Hinglish, Telugu, Tamil,
Kannada, Malayalam, Bengali, Marathi, Gujarati, Urdu, Arabic, Spanish, French,
and German; unrecognized languages use the English voice.

## API reference

All API routes use the `/api/v1` prefix. Detailed schemas are available through
FastAPI's `/docs` page.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/analyze-report` | Analyze one or more reports. Multipart form fields: `files` (repeatable), `member_id` (default `self`), and `language` (default `English`). |
| `POST` | `/api/v1/analyze-prescription` | Analyze prescription/medicine files; same multipart fields as report analysis. |
| `POST` | `/api/v1/vault/members` | Create or update a family member profile. JSON body follows `FamilyMemberCreate`. |
| `GET` | `/api/v1/vault/members` | List family members. |
| `GET` | `/api/v1/vault/members/{member_id}/timeline` | Get a member's saved reports/timeline. |
| `GET` | `/api/v1/vault/records/{report_id}` | Retrieve a saved report; optional `language` query parameter. |
| `POST` | `/api/v1/vault/records/{report_id}/translate` | Translate a saved report; optional `language` query parameter (default `English`). |
| `DELETE` | `/api/v1/vault/records/{report_id}` | Delete a saved report. |
| `POST` | `/api/v1/ask-question` | Ask a health question. JSON body follows `DirectQuestionRequest`. |
| `POST` | `/api/v1/speak` | Generate speech. JSON body follows `SpeakRequest`; returns an audio filename and playback URL. |
| `GET` | `/api/v1/audio/{filename}` | Play/download a generated MP3. |
| `GET` | `/api/v1/training-dataset/export` | Export saved report text and analysis as a training dataset. |

The frontend pages are served at `/`, `/login`, `/dashboard`, `/about`, and
`/contact`. Static frontend files are available under `/assets` and `/static`;
original uploaded files are served under `/vault-files`.

### Request model notes

- `SpeakRequest`: `text` is required; `language` defaults to `English`.
- `DirectQuestionRequest`: `question` is required; `member_id` defaults to
  `self`, `language` defaults to `English`, and `use_past_history` defaults to
  `true`.
- `FamilyMemberCreate`: `member_id` and `display_name` are required.
  Relationship defaults to `Self`; age, gender, blood group, and known
  conditions are optional.

Invalid uploads/questions and missing report records return HTTP errors with a
detail message. Uploads are limited to 10 files per request; accepted file
extensions are PDF, JPG, JPEG, PNG, and WEBP.

## Data model

The SQLAlchemy models in `app/db/models.py` define:

- **`family_members`**: member ID, display name, relationship, optional profile
  details, and creation timestamp.
- **`medical_reports`**: report/member IDs, upload date, document hash,
  original-file metadata, language, demographics, scrubbed extracted text,
  AI analysis, translations, and embedding.
- **`qa_training_logs`**: member ID, timestamp, language, question, and AI
  response.

Database rows do not contain the original file bytes; those are written to the
`vault_uploads/` directory and referenced by file URLs in the report metadata.

## Privacy and deployment considerations

- The application performs its configured PII scrubbing before sending cleaned
  document text to Gemini. This should not be treated as a guarantee of
  anonymization; inspect the scrubber and your privacy obligations before use.
- Uploaded originals and report/Q&A data are persisted locally or in the
  configured database. Deleting a report through the API deletes the database
  record; verify separately how files and backups are handled in your
  deployment.
- Gemini requests send text to Google's API. Speech generation uses Edge TTS.
  Review each provider's terms and privacy requirements before processing
  sensitive health information.
- The current sign-in page stores a display profile in browser `localStorage`;
  it does not authenticate users with the backend or enforce per-user access
  control. The API currently has permissive CORS configuration. Do not expose
  this development application publicly or use it for real patient data without
  implementing and reviewing authentication, authorization, transport
  security, data retention, and deployment controls.
- The training dataset export includes stored report text and AI output. Protect
  that endpoint and any exported data appropriately.
- This project has no configured test command or test suite in the current
  repository.

## Troubleshooting

- **Gemini calls fail:** check that `GEMINI_API_KEY` is configured, reachable,
  and permitted to use the selected models. An optional
  `GEMINI_MODEL_CHAIN` can configure model fallback order.
- **Database connection fails:** verify `DATABASE_URL`, the database server,
  and the installed DB driver. SQLite is the default and does not require a
  separate database server.
- **A PDF/image is rejected or has poor results:** check that the file is a
  supported type and that text is legible. Scanned documents depend on OCR
  quality; try a clearer image or PDF.
- **Frontend pages or local files are missing:** start the server from the
  project directory so relative paths resolve correctly.
- **Schema changes are not reflected:** `create_all()` only creates missing
  tables; it does not update existing tables in general. Use reviewed Alembic
  migrations and back up the database first.