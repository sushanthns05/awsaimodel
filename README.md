# AWS Student Builder Group — AI Recruitment & Candidate Shortlisting Platform

**Institution:** SJB Institute of Technology (SJBIT), Bengaluru, India  
**Organization:** AWS Student Builder Group (SBG)  
**Recruitment Cycle:** 2026–27  
**Build Status:** ✅ Production Ready & Fully Tested (155 backend pytest tests + 31 frontend vitest tests passing)

---

## Overview

The **AWS AI Recruitment Platform** is a full-stack, enterprise-grade recruitment and candidate evaluation SaaS designed for the AWS Student Builder Group at SJBIT. The system automates application intake from Google Forms, extracts text from uploaded digital and scanned resumes, performs evidence-backed candidate evaluations using **DeepSeek V4.1 Flash**, calculates transparent scores through a deterministic Python 100-point rubric, and provides an administrative dashboard for committee review, shortlisting, and multi-format report exports.

---

## Architecture

```
Google Forms (Student Submissions)
       ↓
Google Sheets (Response Storage)
       ↓
Google Apps Script (HMAC-SHA256 Signed Webhook)
       ↓
Render FastAPI Backend (/api/intake)
       ↓
AWS S3 (Encrypted Document Storage) & Amazon DynamoDB (Database)
       ↓
Amazon SQS (Background Processing Queue)
       ↓
Render Background Worker
       ↓
Document Extraction (PyMuPDF / python-docx / Amazon Textract)
       ↓
DeepSeek AI Evaluation (Evidence Citations & Structured JSON)
       ↓
Deterministic Python Scoring Engine (100-Point Rubric)
       ↓
Report Generation (12-Sheet Excel Workbook & ReportLab PDF)
       ↓
React Admin Dashboard (Firebase Hosting)
```

---

## Technology Stack

- **Frontend:** React 18, TypeScript, Vite, Tailwind CSS, shadcn/ui, Lucide React icons, Recharts, React Router 6, TanStack Query 5
- **Frontend Hosting:** Firebase Hosting
- **Backend:** Python 3.12+, FastAPI, Pydantic v2, Uvicorn, REST APIs
- **Backend Hosting:** Render Web Service & Render Background Worker
- **AWS Cloud Services:**
  - **Amazon S3:** Private buckets for resume files and generated reports
  - **Amazon DynamoDB:** Pay-per-request storage for applicants, evaluations, audit, and configuration
  - **Amazon SQS:** Asynchronous job processing queue with Dead-Letter Queue (DLQ)
  - **Amazon Textract:** OCR extraction for scanned resumes and images
  - **AWS Secrets Manager:** Secure storage for DeepSeek API keys and intake credentials
  - **Amazon Cognito:** User Pool authentication and role-based groups
- **AI / LLM:** DeepSeek V4.1 Flash via OpenAI-compatible API with structured JSON output and anti-prompt-injection defenses
- **Document Processing:** PyMuPDF, python-docx, Pillow, Amazon Textract
- **Reporting:** openpyxl (12-sheet formatted Excel workbook), ReportLab (executive summary & candidate PDFs)

---

## Project Structure

```
├── backend/
│   ├── api/                     # FastAPI route handlers & dependencies
│   │   ├── routers/             # intake, auth, dashboard, applicants, shortlist, reports, settings
│   │   ├── deps.py              # Dependency injection & RBAC checks
│   │   └── __init__.py
│   ├── schemas/                 # Pydantic v2 request/response validation models
│   ├── workers/                 # Render background worker (SQS consumer)
│   │   └── sqs_worker.py        # SQS polling, exponential backoff, DLQ, retries
│   ├── src/                     # Core business logic
│   │   ├── ai/                  # DeepSeek client, prompts, schema validation
│   │   ├── scoring/             # Deterministic 100-point rubric scoring engine
│   │   ├── documents/           # Document extraction (PDF, DOCX, Textract) & storage
│   │   ├── reports/             # Excel (openpyxl) and PDF (ReportLab) generators
│   │   ├── services/            # Applicants, dashboard, shortlist, reports services
│   │   ├── common/              # DynamoDB repository, models, auth, config
│   │   └── config/              # Active rubric, roles, eligibility, field mappings
│   ├── tests/                   # 138 core unit & integration tests
│   ├── main.py                  # FastAPI ASGI application entry point
│   ├── run_api.py               # Render Web Service start script
│   ├── run_worker.py            # Render Background Worker start script
│   ├── Procfile                 # Render process configuration
│   └── requirements.txt         # Backend Python dependencies
├── frontend/
│   ├── src/
│   │   ├── pages/               # Login, Overview, Applicants, Detail, Shortlist, Reports, Settings
│   │   ├── components/          # AppShell, StatCard, StatusBadges, Charts, UI primitives
│   │   ├── lib/                 # API client, Cognito auth helpers, utils
│   │   ├── hooks/               # useAuth, useDebouncedValue
│   │   └── types/               # TypeScript data models (33+ interfaces)
│   ├── dist/                    # Compiled production build
│   ├── package.json             # Frontend dependencies & scripts
│   └── vite.config.ts           # Vite configuration
├── integrations/
│   └── google-apps-script/
│       ├── Code.gs              # Google Forms submit trigger & HMAC bridge
│       ├── appsscript.json      # Google Apps Script manifest
│       └── README.md            # Setup instructions
├── config/                      # Packaged default configuration files
│   ├── rubric.json              # 100-point scoring rubric
│   ├── roles.json               # 9 recruitment team definitions
│   ├── eligibility.json         # Automated eligibility rules
│   └── field-mapping.json       # Google Form question bindings
├── tests/
│   └── test_fastapi_endpoints.py # 17 FastAPI integration tests
├── scripts/
│   ├── seed_demo_data.py        # Synthetic candidate data generator
│   ├── test_intake_submission.py# Intake webhook test utility
│   ├── deploy_render.bat / .sh  # Render deployment scripts
│   └── deploy_firebase.bat / .sh# Firebase Hosting deployment scripts
├── docs/                        # Complete technical documentation
│   ├── ARCHITECTURE.md          # Architecture diagrams & component breakdown
│   ├── DEPLOYMENT_GUIDE.md      # Step-by-step production deployment guide
│   ├── API_REFERENCE.md         # REST API endpoints & request/response specs
│   ├── GOOGLE_FORMS_SETUP.md    # Google Forms & Sheets integration guide
│   └── SECURITY_AND_RBAC.md     # Security, privacy, and DPDP compliance
├── render.yaml                  # Render Blueprint definition (API + Worker)
├── firebase.json                # Firebase Hosting configuration
├── .firebaserc                  # Firebase project binding
├── .env.example                 # Root environment variables template
├── BUILD_STATUS.md              # Detailed verification status & test results
└── pytest.ini                   # Pytest test discovery settings
```

---

## Quick Start (Local Development)

### 1. Prerequisites
- Python 3.12+
- Node.js 18+

### 2. Backend Setup
```bash
# Activate virtual environment
.\.venv\Scripts\activate   # Windows
# or: source .venv/bin/activate  # macOS/Linux

# Install dependencies
pip install -r backend/requirements.txt

# Run the FastAPI server in local development mode
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```
API Documentation will be available at: http://127.0.0.1:8000/docs

### 3. Seed Synthetic Candidate Data
In a separate terminal:
```bash
python scripts/seed_demo_data.py
```
This populates the local store with realistic applicants across SJBIT engineering departments (CSE, ISE, ECE, AI&DS, Mech) and runs them through AI evaluation and scoring.

### 4. Frontend Setup
```bash
cd frontend
npm install

# Start Vite dev server
npm run dev
```
The React dashboard will be live at: http://localhost:5173

---

## Running the Automated Test Suite

### Backend Pytest Suite (155 tests)
```bash
python -m pytest
```

### Frontend Vitest Suite (31 tests)
```bash
cd frontend
npm test
```

### Frontend Production Build
```bash
cd frontend
npm run build
```

---

## Production Deployment

### 1. Render Deployment (Backend Web Service & Background Worker)
1. Link your repository in [Render Dashboard](https://dashboard.render.com).
2. Create a new **Blueprint** from `render.yaml`.
3. Set secret environment variables (`AI_API_KEY`, `INTAKE_KEY`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`).
4. Render automatically deploys both `sbg-recruitment-api` and `sbg-recruitment-worker`.

### 2. Firebase Hosting Deployment (Frontend Dashboard)
```bash
cd frontend
npm run build
cd ..
firebase deploy --only hosting
```

For complete instructions, see [docs/DEPLOYMENT_GUIDE.md](docs/DEPLOYMENT_GUIDE.md).

---

## Evaluation Rubric (100 Points)

| Category | Max Marks | Description |
|---|---|---|
| Relevant Technical Skills | 20 | Verified programming, framework, and tooling capabilities |
| Projects & Practical Experience | 20 | Demonstrated GitHub repositories, live applications, and hackathons |
| Role-Specific Knowledge | 15 | Depth of understanding in applied recruitment role |
| Problem-Solving Ability | 15 | Algorithmic logic, debugging aptitude, and analytical thinking |
| Communication & Articulation | 10 | Clarity of written responses and structured explanations |
| Commitment & Availability | 10 | Weekly time allocation (minimum 8-10 hours/week) |
| Leadership & Collaboration | 10 | Teamwork evidence, student initiative, and community participation |

---

## License & Credits

Developed for the **AWS Student Builder Group**, **SJB Institute of Technology**, Bengaluru.  
Recruitment Cycle: 2026–27.  
AI-assisted evaluation, deterministic scoring, human-approved decisions.

