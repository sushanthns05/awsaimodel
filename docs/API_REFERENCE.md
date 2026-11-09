# FastAPI REST API Reference

The API documentation is interactively accessible via Swagger UI at `/docs` or ReDoc at `/redoc`.

Base URL: `https://your-render-url.onrender.com` or `http://localhost:8000`

---

## Authentication & Headers

- **Admin APIs:** Require header `Authorization: Bearer <ID_TOKEN>`.
- **Intake API:** Requires header `x-intake-key: <KEY>` and HMAC-SHA256 headers `x-signature: <SIG>`, `x-timestamp: <TS>`.

---

## Endpoint Summary

### 1. Intake
| Method | Path | Description |
|---|---|---|
| `POST` | `/api/intake` | Receive Google Form application and uploaded resumes |

### 2. Auth & Admin Identity
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/me` | Current administrator identity and RBAC permissions |
| `POST` | `/api/auth/login` | Login with email and password |
| `POST` | `/api/auth/logout` | End session |

### 3. Analytics & Overview
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/dashboard/overview` | Pipeline stats, role counts, score distribution |

### 4. Applicants Management
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/applicants` | List applicants with search, pagination, multi-filtering |
| `GET` | `/api/applicants/{id}` | Complete candidate profile, extracted text, AI evaluation |
| `GET` | `/api/applicants/{id}/documents/{doc_id}/url` | Pre-signed short-lived download URL for resume |
| `POST` | `/api/applicants/{id}/review` | Record human review decision (APPROVED, REJECTED, MANUAL_REVIEW) |
| `PATCH` | `/api/applicants/{id}/evaluation` | Override specific rubric criterion scores with reason |
| `POST` | `/api/applicants/{id}/reprocess` | Re-queue applicant through extraction and AI evaluation |
| `GET` | `/api/applicants/{id}/audit` | Immutable audit trail for candidate changes |
| `DELETE` | `/api/applicants/{id}` | Purge candidate personal data (DPDP / GDPR) |

### 5. Shortlisting
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/shortlist` | Role-wise rankings and eligibility filter |
| `POST` | `/api/shortlist/bulk` | Bulk approve or reject selected applicants for interview |

### 6. Reports Generation
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/reports` | List generated reports catalog |
| `POST` | `/api/reports/generate` | Generate Excel workbook or consolidated/candidate PDF |
| `GET` | `/api/reports/{id}` | Check report generation status |
| `GET` | `/api/reports/{id}/download` | Pre-signed download URL for generated report |

### 7. Configuration & System Settings
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/settings` | Read active rubric, eligibility rules, roles, field mappings |
| `PUT` | `/api/settings/{key}` | Update specific configuration section |
| `POST` | `/api/settings/ai/test` | Live probe test of DeepSeek AI provider |
| `GET` | `/api/settings/health` | S3, DynamoDB, and system health status |
| `GET` | `/api/form/mapping` | Preview Google Form question bindings |
| `GET` | `/api/admins` | List admin users and groups |
| `POST` | `/api/admins` | Grant administrator privileges |
| `DELETE` | `/api/admins` | Revoke administrator privileges |

### 8. System Probes
| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check for Render Web Service |
| `GET` | `/api/health` | Health check alias |
| `GET` | `/dev/files/{bucket}/{key}` | Local file server for resumes and reports |

