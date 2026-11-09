# Production Deployment Guide: AWS AI Recruitment Platform

This guide outlines deployment to **Render** (FastAPI backend & Background Worker), **Firebase Hosting** (React Dashboard), and **AWS** (S3, DynamoDB, SQS, Textract, Cognito).

---

## 1. Prerequisites
- Python 3.12+
- Node.js 18+ and npm
- AWS Account with Administrator access
- Render Account (https://render.com)
- Firebase Account (https://firebase.google.com)
- DeepSeek API Key (https://platform.deepseek.com)

---

## 2. AWS Infrastructure Setup

### Option A: AWS SAM (Automated Provisioning)
The repository includes a complete `template.yaml` that provisions all AWS resources (DynamoDB tables, S3 buckets, SQS queues, Cognito User Pool, IAM roles):

```bash
sam build
sam deploy --guided \
  --stack-name sbg-recruitment-prod \
  --region ap-south-1 \
  --parameter-overrides Stage=prod AiApiKey=YOUR_DEEPSEEK_KEY IntakeKey=YOUR_SHARED_SECRET
```

### Option B: Manual AWS Resource Creation
If provisioning manually:
1. **DynamoDB Tables (Pay-per-request billing):**
   - `sbg-applicants-prod` (Partition Key: `applicant_id` [String])
   - `sbg-evaluations-prod` (Partition Key: `applicant_id` [String], Sort Key: `evaluation_id` [String])
   - `sbg-audit-prod` (Partition Key: `applicant_id` [String], Sort Key: `audit_id` [String])
   - `sbg-config-prod` (Partition Key: `key` [String])
   - `sbg-reports-prod` (Partition Key: `report_id` [String])
2. **S3 Buckets (Block all public access):**
   - `sbg-resumes-prod-sjbit`
   - `sbg-reports-prod-sjbit`
3. **SQS Queue:**
   - Name: `sbg-recruitment-queue`
   - Dead-Letter Queue: `sbg-recruitment-dlq` (Max receives: 5)
4. **Cognito User Pool:**
   - Create User Pool `sbg-recruitment-users`.
   - Create Groups: `sbg-admins`, `sbg-reviewers`, `sbg-viewers`.
   - Create App Client (Enable `ALLOW_USER_PASSWORD_AUTH` and `ALLOW_REFRESH_TOKEN_AUTH`).

---

## 3. Backend Deployment on Render

Render manages both the **FastAPI Web Service** and the **Background Worker** via `render.yaml`.

1. Push this repository to GitHub/GitLab.
2. In the Render Dashboard, click **New +** → **Blueprint**.
3. Select your repository. Render will automatically parse `render.yaml` and configure:
   - **Service 1:** `sbg-recruitment-api` (FastAPI Web Service)
     - Build Command: `pip install -r requirements.txt`
     - Start Command: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
     - Health Check Path: `/health`
   - **Service 2:** `sbg-recruitment-worker` (Background Worker)
     - Start Command: `python backend/run_worker.py`
4. In Render Dashboard, set the secret environment variables under Environment:
   - `AWS_ACCESS_KEY_ID`: Your IAM user access key
   - `AWS_SECRET_ACCESS_KEY`: Your IAM user secret key
   - `AWS_REGION`: `ap-south-1`
   - `AI_API_KEY`: Your DeepSeek API key
   - `INTAKE_KEY`: A strong random string for Google Apps Script signing
   - `PROCESSING_QUEUE_URL`: Your SQS Queue URL
   - `CORS_ORIGIN`: Your Firebase Hosting URL (e.g., `https://sbg-recruitment-sjbit.web.app`)
5. Click **Apply Blueprint**.

---

## 4. Frontend Deployment on Firebase Hosting

1. Install Firebase CLI:
   ```bash
   npm install -g firebase-tools
   ```
2. Authenticate:
   ```bash
   firebase login
   ```
3. Configure `frontend/.env.production`:
   ```bash
   VITE_API_BASE_URL=https://sbg-recruitment-api.onrender.com
   VITE_COGNITO_REGION=ap-south-1
   VITE_COGNITO_CLIENT_ID=your_cognito_app_client_id
   VITE_DEV_AUTH=false
   ```
4. Build the production React application:
   ```bash
   cd frontend
   npm run build
   cd ..
   ```
5. Deploy:
   ```bash
   firebase deploy --only hosting
   ```

---

## 5. Google Forms / Apps Script Integration

1. Open your recruitment Google Form and open **Script editor** from the form menu.
2. Paste `integrations/google-apps-script/Code.gs` and `appsscript.json`.
3. Set Script Properties:
   - `API_URL`: `https://sbg-recruitment-api.onrender.com/api/intake`
   - `INTAKE_KEY`: The matching secret set in your Render environment.
4. Run `setup()` once.
5. Submit a test form response to verify end-to-end receipt.

