# Google Forms & Sheets Setup Guide

This guide details configuring Google Forms and Google Sheets to feed applications into the AWS Student Builder Group recruitment platform.

---

## 1. Create the Google Form

Create a new Google Form titled **"AWS Student Builder Group — SJBIT Recruitment 2026-27"** with the following recommended questions:

| # | Question Title | Field Type | Required | Notes |
|---|---|---|---|---|
| 1 | Full Name | Short answer | Yes | Student's legal full name |
| 2 | College Email Address | Short answer | Yes | e.g., name@sjbit.edu.in |
| 3 | University Seat Number (USN) | Short answer | Yes | e.g., 1JB22CS001 |
| 4 | Phone / WhatsApp Number | Short answer | Yes | e.g., +91 98765 43210 |
| 5 | Department / Branch | Multiple choice | Yes | CSE, ISE, ECE, AI&DS, Mech, Civil, etc. |
| 6 | Year of Study | Multiple choice | Yes | 1st Year, 2nd Year, 3rd Year, 4th Year |
| 7 | Which team(s) are you applying for? | Checkboxes / Multiple choice | Yes | Technical Team, Creative & Design, Marketing & Outreach, Social Media, Operations & Logistics |
| 8 | Technical Skills & Technologies | Paragraph | Yes | Programming languages, cloud tools, frameworks |
| 9 | Projects & Technical Experience | Paragraph | Yes | Links to GitHub, deployed apps, hackathons |
| 10 | Non-Technical Experience & Leadership | Paragraph | No | Student clubs, volunteering, team events |
| 11 | Why do you want to join AWS Student Builder Group? | Paragraph | Yes | Motivation & personal statement |
| 12 | Hours per week available | Short answer | Yes | e.g., 10 hours/week |
| 13 | Upload your Resume / CV | File upload | Yes | Supported: PDF, DOCX, DOC, JPG, PNG |

---

## 2. Link Form to Google Sheets

1. In the Google Form, click the **Responses** tab.
2. Click **Link to Sheets** → Create a new spreadsheet named **"SBG Recruitment 2026-27 Responses"**.
3. Google Sheets will automatically create a tab named **"Form Responses 1"**.

---

## 3. Install the Google Apps Script Bridge

1. In the linked Google Sheet, click **Extensions** → **Apps Script**.
2. Replace the contents of `Code.gs` with the code in `integrations/google-apps-script/Code.gs`.
3. In Apps Script settings, enable manifest view and replace `appsscript.json` with `integrations/google-apps-script/appsscript.json`.
4. Click **Project Settings** (gear icon) → **Script Properties** → **Add script property**:
   - `API_URL`: Your FastAPI endpoint (e.g., `https://your-service.onrender.com/api/intake`)
   - `INTAKE_KEY`: Your secure shared intake secret (e.g., `sbg-intake-secret-2026`)
   - `SHEET_NAME`: `Form Responses 1`
5. In the function dropdown, select `setup` and click **Run**.
6. Review and grant Google permissions.

`setup()` automatically configures:
- An **onFormSubmit** installable trigger.
- A **15-minute time-driven trigger** to retry any submissions queued during network interruptions.
- A **6-hour reconciliation trigger** to cross-verify the spreadsheet rows against sent submissions.
- A Google Drive folder **"SBG Recruitment Pending Submissions"** for offline resilience.

---

## 4. Test the Integration

1. Submit a test response through the Google Form with a sample PDF resume.
2. Check your FastAPI backend logs in Render: you should see `Intake submission received: ACCEPTED`.
3. Open your React Admin Dashboard at `/applicants`: the candidate will appear immediately with processing status transitioning from `QUEUED` to `EXTRACTED` → `EVALUATED` → `COMPLETED`.

