# Google Forms to FastAPI Recruitment Intake Bridge

**Organization:** AWS Student Builder Group  
**Institution:** SJB Institute of Technology (SJBIT), Bengaluru  
**Recruitment Cycle:** 2026–27  

---

## Overview

The Google Apps Script bridge connects Google Forms and Google Sheets directly to the Render FastAPI backend. Whenever an applicant submits the Google Form, this script:

1. Captures all submitted form responses (student name, email, USN, department, year, applied role, etc.).
2. Retrieves uploaded resume documents from Google Drive.
3. Encodes attachments as base64 with MIME type detection.
4. Generates an HMAC-SHA256 signature using a shared secret (`INTAKE_KEY`).
5. Transmits the payload to the FastAPI `/api/intake` endpoint.
6. Handles transient network errors with an automatic Google Drive offline queue and 15-minute retry triggers.
7. Performs reconciliation every 6 hours to prevent lost submissions.

---

## Setup Instructions

### 1. Open Google Forms / Sheets Script Editor
1. Open the Google Form or the linked Google Sheet for SBG Recruitment.
2. In Google Sheets: Click **Extensions** → **Apps Script**.
3. In Google Forms: Click the three dots (⋮) → **Script editor**.

### 2. Add Project Files
1. Copy the contents of `Code.gs` into the editor's `Code.gs`.
2. Click **Project Settings** (gear icon) → Check **"Show 'appsscript.json' manifest file in editor"**.
3. Replace `appsscript.json` with the repository's `appsscript.json`.

### 3. Configure Credentials (Script Properties)
Click **Project Settings** → **Script Properties** → **Add script property**:

| Property | Value | Description |
|---|---|---|
| `API_URL` | `https://your-service.onrender.com/api/intake` | FastAPI intake endpoint |
| `INTAKE_KEY` | `your-secure-shared-secret-here` | Shared secret key for HMAC signing |
| `SHEET_NAME` | `Form Responses 1` | Google Sheet responses tab name |

Alternatively, update the `CONFIG` object at the top of `Code.gs`.

### 4. Run Setup
1. In the Apps Script toolbar, select the function `setup` from the dropdown.
2. Click **Run**.
3. Grant the required Google OAuth permissions (Forms, Sheets, Drive, UrlFetch).
4. `setup()` will:
   - Verify connection settings.
   - Create an installable form submit trigger (`onFormSubmit`).
   - Create a 15-minute retry trigger (`processPendingQueue`).
   - Create a 6-hour reconciliation trigger (`reconcileWithSheet`).
   - Create a Google Drive folder named `SBG Recruitment Pending Submissions` for offline retry queues.

---

## Security Architecture

- **HMAC-SHA256 Authentication:** Every request header includes `X-Signature` computed over `timestamp + '.' + body` using `INTAKE_KEY`.
- **Replay Protection:** Header `X-Timestamp` is validated within a configurable tolerance window (default: 15 minutes).
- **Zero Exposure of AWS Keys:** The Google Apps Script never holds AWS credentials or AI keys. It only communicates with the authenticated FastAPI intake service.
- **Fail-Safe Operation:** Google Form submissions are never blocked or delayed if the API is experiencing high load. Unsent submissions are securely queued in Google Drive and retried automatically.

