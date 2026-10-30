# ArogyaVani / CuraVault AI

ArogyaVani / CuraVault AI is a health-literacy web application for understanding
medical reports and prescriptions. It extracts document text, removes selected
personal identifiers locally, and uses Gemini to explain the remaining medical
content. Users can organize saved reports into family profiles, link
prescriptions to reports, ask health questions, and listen to text-to-speech
responses.

> **Educational use only:** This application does not diagnose conditions or
> prescribe treatment. OCR, AI explanations, and extracted values can be wrong
> or incomplete. Verify results with a qualified healthcare professional. Do
> not use the application for emergencies.

## What the app does

- Accepts up to 5 files per analysis request, each up to 10 MB. The total page
  count across the request is limited to 5 (each image counts as one page).
- Supports PDF, JPG/JPEG, PNG, and WEBP files. PDF text is extracted directly
  when available; scanned PDFs and images use OCR.
- Analyzes lab reports and prescriptions in a selected language.
- Lets users choose whether to save the analyzed result to the encrypted family
  vault. Unchecking the save option returns an analysis without adding a report
  to the vault.
- Supports household invite codes and owner/editor/viewer family access roles.
- Allows saved lab reports to have one or more prescriptions attached.
- Provides report timelines, translations, optional past-report context for
  health questions, and streamed speech playback.

## Technology

- Python 3.13 or newer (as specified by `pyproject.toml`)
- FastAPI and Uvicorn
- SQLAlchemy and Alembic
- SQLite or PostgreSQL; PostgreSQL uses `pgvector`
- PyMuPDF, PyMuPDF4LLM, Pillow, and RapidOCR for extraction
- Google Gemini API for analysis, translations, Q&A, and embeddings
- Edge TTS for streamed speech
- Static HTML, CSS, and JavaScript served by FastAPI

## Project layout

```text
.
├── app/
│   ├── main.py                    # Web pages and authenticated API routes
│   ├── db/
│   │   ├── database.py            # Database URL, engine, SQLAlchemy base
│   │   └── models.py              # Vault roles, family, reports, quota models
│   ├── schemas/models.py          # Validated API request models
│   └── services/
│       ├── analyzer.py            # Gemini analysis, translation, and Q&A
│       ├── auth_limiter.py        # Invite-code auth, roles, and quotas
│       ├── crypto_vault.py        # Vault key derivation and encryption helpers
│       ├── db_vector.py           # Encrypted report/file persistence and search
│       ├── embeddings.py          # Report-history embeddings
│       ├── extractor.py           # File validation, PDF extraction, and OCR
│       ├── guardrails.py          # Local document and question checks
│       ├── llm_router.py          # Gemini model fallback chain
│       ├── prescription.py        # Prescription analysis
│       ├── scrubber.py             # Personal-identifier scrubbing
│       └── voice_tts.py           # In-memory streamed speech and cache
├── alembic/
│   └── versions/                  # Database migration revisions
├── frontend/
│   ├── assets/                    # CSS, JavaScript, and logo
│   ├── index.html                 # Landing page
│   ├── login.html                 # Household invite-code login
│   └── dashboard.html             # Scanner, family vault, and Q&A
├── tests/                         # Unit and API integration tests
├── vault_uploads/                 # Encrypted saved document files
├── alembic.ini
├── pyproject.toml
└── uv.lock
```

Run the FastAPI application as `app.main:app`. The root `main.py` is not the
server entry point.

## Setup and run locally

### 1. Install prerequisites

Install Python 3.13+ and [uv](https://docs.astral.sh/uv/). Open PowerShell in
the project directory and install the locked dependencies:

```powershell
uv sync
```

### 2. Configure environment variables

Create a `.env` file in the project directory. Do not copy real credentials
into source control or share them in issues, logs, or screenshots.

```dotenv
# Required. For local development, this creates/uses a SQLite database file.
DATABASE_URL=sqlite:///./health_vault.db

# Required for Gemini analysis, translation, Q&A, and API-based embeddings.
GEMINI_API_KEY=replace-with-your-Gemini-key

# Required for household access. Each comma-separated owner code initializes
# an independent household vault the first time it is used.
INVITE_CODES=replace-with-a-long-random-owner-code

# Required for production. Generate a long random value and keep it stable.
SECRET_SALT=replace-with-a-long-random-secret-salt

# Optional. Comma-separated Gemini model names tried in order.
GEMINI_MODEL_CHAIN=gemini-2.5-flash,gemini-2.5-flash-lite

# Optional. Comma-separated browser origins permitted to call the API.
ALLOWED_ORIGINS=http://127.0.0.1:8000,http://localhost:8000
```

Generate random values locally if needed:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Run that command separately for each secret; copy its output into your private
environment configuration. Use strong, unique invite codes. Do not use
development/default values in a deployment.

**Keep `SECRET_SALT` unchanged after creating vaults.** It is used in invite
code hashing and key derivation. Changing it can prevent users from unlocking
existing vaults. Keep invite codes available to their owners; the server does
not store the raw code. Back up `SECRET_SALT`, database data, and encrypted
files securely and together.

The `.env`, databases, and `vault_uploads/` are excluded from Git. Do not commit
medical information, keys, or backups.

### 3. Create or update the database

For a fresh database, run the Alembic migration before starting the server:

```powershell
uv run alembic upgrade head
uv run alembic current
```

The current revision creates the production tables for household roles,
members, reports, and quota tracking. The application also calls
`Base.metadata.create_all()` at startup; that creates missing tables, but it
does not replace migrations for changing existing tables.

If upgrading a database created by an older version of the app, make a verified
backup first. Its schema and stored data may not match the current encrypted
schema. Do not blindly apply the new initial migration to a non-empty legacy
database: compare the live schema with the revision and plan a data-preserving
migration or baseline before upgrading.

For later model changes, create a revision, inspect it, and then apply it:

```powershell
uv run alembic revision --autogenerate -m "describe the schema change"
# Review upgrade() and downgrade() in alembic/versions before continuing.
uv run alembic upgrade head
uv run alembic current
```

Autogeneration cannot determine intent for operations such as column renames.
Edit and test generated revisions rather than treating them as automatically
correct.

### 4. Start and open the application

Run from the project directory because the app uses relative paths:

```powershell
uv run uvicorn app.main:app --reload
```

- Web app: <http://127.0.0.1:8000>
- API reference: <http://127.0.0.1:8000/docs>
- OpenAPI JSON: <http://127.0.0.1:8000/openapi.json>
- Health check: <http://127.0.0.1:8000/healthz>

### 5. Run tests

```powershell
uv run pytest -v
```

## Configuration and database notes

`DATABASE_URL` is required; the application does not choose a default if it is
missing. SQLite is suitable for local development:

```dotenv
DATABASE_URL=sqlite:///./health_vault.db
```

For PostgreSQL, use a SQLAlchemy-compatible URL and make sure the server has
the PostgreSQL driver and the `vector` extension available:

```dotenv
DATABASE_URL=postgresql+psycopg2://user:password@localhost:5432/curavault
```

PostgreSQL stores embeddings as 768-dimensional vectors; SQLite stores them as
JSON. Set `ALLOWED_ORIGINS` to the exact trusted origins for the deployment.
The defaults are intended for local development.

## User workflow

### A. Unlock a household vault

1. Open `/login`.
2. Enter a household owner invite code or a family role code.
3. Accept the beta/educational-use notice and choose **Unlock Family Vault**.
4. The browser sends the code to `/api/v1/auth/me`. On success, the browser
   keeps the code in `localStorage` and includes it as the `X-Invite-Code`
   header on API calls.
5. Select **Lock Vault** to clear the browser's saved code and return to login.

The first use of an owner code initializes that household's owner record.
Owners can create editor or viewer codes from the dashboard's role-management
control, optionally restricting a code to one family profile. Share role codes
only with their intended users.

### B. Analyze a report or prescription

1. In the dashboard, choose a family profile. Add a profile if needed.
2. Select **Lab Report** or **Prescription**.
3. Select up to 5 supported files (10 MB each; no more than 5 PDF pages total).
4. Accept **Privacy & Educational Consent**. This consent is required to submit
   the analysis.
5. Choose whether **Zero-Knowledge Vault Storage** is checked:
   - Checked: after analysis, save encrypted report data and original files in
     the Family Vault.
   - Unchecked: return the result for this request without saving it to the
     vault. It will not have a saved report ID or appear in the timeline.
6. Select a language and choose **Decode Document**.
7. Review the result. Check all values and recommendations with a healthcare
   professional.

Behind the scenes, the server validates file size/type, extracts PDF text or
uses OCR, runs local medical-document checks, and scrubs selected identifiers.
The cleaned text is sent to Gemini for analysis. When vault saving is enabled,
the app encrypts report JSON and uploaded file bytes before persistent storage.
Images are resized/compressed before being encrypted; PDFs remain PDFs.

The app checks for an existing report with the same household, profile,
document category, and file contents to avoid repeating analysis. Analysis
requests are limited to 20 per IP per minute and 10 report/prescription
operations per household in a rolling 24-hour period.

### C. Attach a prescription to a saved report

1. Save a lab report to the vault first.
2. Open that saved report from its family member's timeline.
3. Choose **Attach Prescription / Medicine Strip**.
4. Upload the prescription files. The app extracts and analyzes them with
   context from the parent lab report, then adds the encrypted prescription
   files and decoded medicine guide under that report.

This feature requires a saved parent report and a role that can write to that
profile. A viewer cannot attach prescriptions.

### D. Use the Family Vault

- Family profiles group reports inside a household.
- Open a profile to view its timeline, open a report, translate it, or inspect
  its saved original files.
- Original files are decrypted only for an authenticated request and streamed
  to the browser. They are not served from a public static-file route.
- Only the owner can delete reports or manage/revoke family role codes.
- Editors can add/update profiles and analyze or attach documents. Profile
  restrictions apply to some operations; see the security note below before
  relying on them for profile-level isolation.
- Viewers can view and listen but cannot upload or modify records.

### E. Ask a question or listen

1. Select the family member whose report history should be used.
2. Open **Ask Health AI**, enter a health question, and choose whether to use
   past report context.
3. The app may retrieve up to three reports for that member, sends the question
   and selected context to Gemini, and returns an educational answer.
4. Use the speech controls to request streamed MP3 audio. Audio is held in a
   small in-memory cache; the app does not write speech files to disk.

Questions and speech requests require a valid invite code. Per-household
rolling 24-hour limits are 30 questions and 30 speech requests; relevant API
routes also have a 20-per-IP-per-minute rate limit. Q&A text is not stored as a
chat transcript; the database records action counts for quota enforcement.

## API reference

All API routes use `/api/v1`. Except `/healthz` and the page/static routes,
protected API calls require the `X-Invite-Code` header. Open `/docs` for full
request and response schemas.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/auth/me` | Validate an invite/role code and return its role and profile scope. |
| `GET` | `/api/v1/vault/roles` | List household roles; owner only. |
| `POST` | `/api/v1/vault/roles` | Create an editor/viewer share code; owner only. |
| `DELETE` | `/api/v1/vault/roles/{role_id}` | Revoke a non-owner role code; owner only. |
| `POST` | `/api/v1/analyze-report` | Analyze multipart `files`, `member_id`, `language`, `privacy_consent`, and `save_to_vault`. |
| `POST` | `/api/v1/analyze-prescription` | Analyze prescription files; same form fields as report analysis. |
| `POST` | `/api/v1/vault/records/{report_id}/attach-prescription` | Analyze and attach prescription files to a saved report. |
| `POST` | `/api/v1/vault/members` | Create/update a family profile; JSON body follows `FamilyMemberCreate`. |
| `GET` | `/api/v1/vault/members` | List profiles accessible to the current role. |
| `GET` | `/api/v1/vault/members/{member_id}/timeline` | Get a profile's report timeline. |
| `GET` | `/api/v1/vault/records/{report_id}` | Get a saved report; optional `language` query parameter. |
| `POST` | `/api/v1/vault/records/{report_id}/translate` | Translate a saved report; `language` query parameter defaults to English. |
| `GET` | `/api/v1/vault/records/{report_id}/files/{file_id}` | Decrypt and return an authorized saved file. |
| `DELETE` | `/api/v1/vault/records/{report_id}` | Delete a report and its encrypted files; owner only. |
| `POST` | `/api/v1/ask-question` | Ask a health question; JSON body follows `DirectQuestionRequest`. |
| `POST` | `/api/v1/speak` | Return streamed `audio/mpeg`; JSON body follows `SpeakRequest`. |

The website pages are `/`, `/login`, `/dashboard`, `/about`, and `/contact`.
Static frontend assets are served under `/assets` and `/static`.

### Request fields

- **Report and prescription analysis**: multipart `files` (repeatable),
  `member_id` (default `self`), `language` (default `English`),
  `privacy_consent` (must be true), and `save_to_vault` (default true).
- **Attach prescription**: multipart `files` and `language`; the parent
  `report_id` is in the URL.
- **FamilyMemberCreate**: required `member_id` and `display_name`; optional
  `relationship`, `age`, `gender`, `blood_group`, and `known_conditions`.
- **RoleCodeCreate**: required `share_code` and `label`; `role` must be
  `editor` or `viewer`; `allowed_member_id` can be `*` or a profile ID.
- **DirectQuestionRequest**: required `question`; `member_id` defaults to
  `self`, `language` to `English`, and `use_past_history` to true.
- **SpeakRequest**: required `text`; `language` defaults to `English`.

## Data and privacy

The database contains:

- **`vault_access_roles`**: a hash of each role code, household and access
  scope, plus the wrapped vault key. The raw invite/share code is not stored in
  this table.
- **`family_members`**: household/profile IDs, display name, relationship,
  age, gender, blood group, and known conditions.
- **`medical_reports`**: household/profile IDs, report ID, dates, document hash,
  file metadata, language, encrypted report content/translations/attached
  prescriptions, and an embedding.
- **`qa_training_logs`**: household, action type, and timestamp used for
  question/speech quotas; this is not a stored conversation transcript.

Report content and saved original files are encrypted with Fernet using a
household vault key derived/unwrapped using the invite code. This should not be
interpreted as end-to-end security for the entire system: some database
metadata (including profile details, filenames/file metadata, timestamps,
document hashes, and embeddings) is not encrypted by this application. The
embedding is derived from report content and should also be treated as
sensitive.

Selected identifiers are scrubbed locally before document text is sent to
Gemini, but regular-expression scrubbing is not guaranteed anonymization.
Gemini receives cleaned document text for analysis and may receive text to
create embeddings; Q&A sends the question and any selected report context.
Speech requests send the requested text to Edge TTS. Review provider terms,
privacy rules, and data-processing requirements before using real health data.

The browser stores the invite code in `localStorage` to authenticate API
requests. Protect access to the browser and device; logging out clears the
stored code. The app uses shared role codes rather than a full user account,
password reset, or identity-verification system. Treat role codes as
credentials. Member-specific role restrictions are not enforced consistently
across every report endpoint, so do not treat them as a security boundary
between family profiles without reviewing and testing those access paths.

Deletion is owner-only and removes a report database row plus the encrypted
files referenced by that row. It does not erase backups, logs, database
snapshots, or other copies. Define retention and backup policies for your
deployment.

## Troubleshooting

- **Server reports missing `DATABASE_URL`:** add it to `.env` or the process
  environment, then restart from the project directory.
- **Invite code is rejected:** check the configured owner code or ask the
  household owner for a current role code. Confirm the same database and
  `SECRET_SALT` are being used.
- **A user cannot upload or modify a profile:** check whether the code is
  viewer-only or restricted to a different profile.
- **Daily limit or rate limit is reached:** wait for the applicable rolling
  limit to expire.
- **Gemini analysis fails:** confirm `GEMINI_API_KEY`, network access, and
  model availability. `GEMINI_MODEL_CHAIN` can configure model fallback order.
- **File upload is rejected:** verify it is a genuine PDF/JPG/JPEG/PNG/WEBP
  file, is no larger than 10 MB, and that no more than 5 files or 5 total pages
  across the request are being submitted.
- **A saved original will not open:** make sure the encrypted file directory
  and database are from the same backup and the same invite code and
  `SECRET_SALT` are in use.
- **A schema change is missing:** apply the reviewed Alembic revision with
  `uv run alembic upgrade head`; `create_all()` does not update existing
  columns in general.

## Deployment checklist

- Use strong, unique owner/share codes and a cryptographically random,
  persistent `SECRET_SALT`.
- Set production `DATABASE_URL`, `GEMINI_API_KEY`, and `ALLOWED_ORIGINS`.
- Run Alembic migrations during deployment before serving traffic.
- Use HTTPS and a supported PostgreSQL deployment with `pgvector` if using
  PostgreSQL.
- Persist and back up the database, `vault_uploads/`, and configuration needed
  to unlock the vault; restrict backup access.
- Do not deploy the example/default development credentials or expose a
  development server publicly.
- Review authentication, access controls, retention, privacy, and medical
  regulatory requirements before processing real patient data.
