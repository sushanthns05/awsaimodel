export type ProcessingStatus =
  | 'RECEIVED'
  | 'QUEUED'
  | 'EXTRACTING'
  | 'EXTRACTED'
  | 'EVALUATING'
  | 'SCORING'
  | 'COMPLETED'
  | 'NEEDS_REVIEW'
  | 'FAILED'
  | 'DELETED'

export type Recommendation =
  | 'STRONG_INTERVIEW'
  | 'INTERVIEW_CONSIDERATION'
  | 'MANUAL_REVIEW'
  | 'ELIGIBILITY_REVIEW'
  | 'NEEDS_REVIEW'

export type ReviewStatus = 'PENDING' | 'APPROVED' | 'REJECTED' | 'MANUAL_REVIEW'

export interface Principal {
  subject: string
  email: string
  username: string
  groups: string[]
  permissions: string[]
  isAdmin: boolean
}

export interface ApplicantBrief {
  applicantId: string
  fullName: string
  email: string
  usn: string
  department: string
  yearOfStudy: string
  roles: string[]
  submittedAt: string
  processingStatus: ProcessingStatus
  totalScore: number
  recommendation: Recommendation
  eligibilityStatus: 'PASS' | 'FAIL' | 'UNKNOWN'
  reviewStatus: ReviewStatus
  urgentReview: boolean
  documents: number
  rubricVersion: string
}

export interface ApplicantRecord {
  applicant_id: string
  source_response_id: string
  submitted_at: string
  full_name: string
  email: string
  usn: string
  phone: string
  department: string
  year_of_study: string
  roles: string[]
  responses: Record<string, unknown>
  processing_status: ProcessingStatus
  processing_error: string
  extracted_text_chars: number
  extraction_summary: Record<string, unknown>
  application_complete: boolean
  missing_required_fields: string[]
  urgent_review: boolean
  review_status: ReviewStatus
  review_decision: string
  review_notes: string
  reviewed_by: string
  reviewed_at?: string | null
  total_score: number
  recommendation: Recommendation
  eligibility_status: 'PASS' | 'FAIL' | 'UNKNOWN'
  eligibility_failures: string[]
  role_scores: Record<string, number>
  latest_evaluation_id: string
  rubric_version: string
  form_title: string
  created_at: string
  updated_at: string
}

export interface DocumentMeta {
  document_id: string
  filename: string
  content_type: string
  size_bytes: number
  sha256: string
  extraction_status: string
  extraction_error: string
  page_count: number
  text_chars: number
  textract_used: boolean
  scanned: boolean
  duplicate_of: string
  downloadUrl?: string
}

export interface CriterionScore {
  criterion_id: string
  name: string
  max_score: number
  suggested_score: number | null
  final_score: number
  evidence: string[]
  reasoning: string
  validated: boolean
  validation_error: string
}

export interface EligibilityResult {
  rule_id: string
  label: string
  status: 'PASS' | 'FAIL' | 'UNKNOWN'
  mandatory: boolean
  detail: string
  observed: string
}

export interface InterviewQuestion {
  role: string
  question: string
  why?: string
}

export interface Evaluation {
  applicant_id: string
  evaluation_id: string
  rubric_version: string
  created_at: string
  criteria: CriterionScore[]
  total_score: number
  max_score: number
  score_complete: boolean
  ai_suggested_total?: number | null
  recommendation: Recommendation
  eligibility: EligibilityResult[]
  eligibility_status: 'PASS' | 'FAIL' | 'UNKNOWN'
  eligibility_failures: string[]
  summary: string
  strengths: string[]
  weaknesses: string[]
  missing_information: string[]
  inconsistencies: string[]
  uncertain_findings: string[]
  technical_skills: string[]
  nontechnical_skills: string[]
  projects: Record<string, unknown>[]
  certifications: string[]
  experience: Record<string, unknown>[]
  leadership_evidence: string[]
  communication_evidence: string[]
  interview_questions: InterviewQuestion[]
  role_evaluations: { role_id: string; score: number; fit: string; rationale: string }[]
  confidence: string
  model_metadata: Record<string, unknown>
  validation_errors: string[]
  document_coverage: Record<string, unknown>
  review_status: ReviewStatus
  human_notes: string
  human_override: Record<string, unknown>
  version: number
}

export interface AuditEntry {
  audit_id: string
  applicant_id: string
  reviewer: string
  action: string
  timestamp: string
  previous_value: unknown
  updated_value: unknown
  reason: string
  metadata: Record<string, unknown>
}

export interface EvaluationHistoryItem {
  evaluationId: string
  createdAt: string
  totalScore: number
  recommendation: Recommendation
  rubricVersion: string
  reviewStatus: ReviewStatus
  scoreComplete: boolean
  model: string
  validationErrors: string[]
  humanOverride: Record<string, unknown>
}

export interface ApplicantDetail {
  applicant: ApplicantRecord
  applicantId: string
  brief: ApplicantBrief
  documents: DocumentMeta[]
  evaluation: Evaluation | null
  evaluationHistory: EvaluationHistoryItem[]
  audit: AuditEntry[]
}

export interface PagedApplicants {
  items: ApplicantBrief[]
  nextCursor: string | null
  pageSize: number
  count: number
}

export interface RoleStat {
  roleId: string
  name: string
  applicants: number
  processed: number
  eligible: number
  shortlisted: number
  averageScore: number
  strongRecommendations: number
}

export interface Overview {
  stats: {
    totalApplications: number
    processed: number
    pending: number
    failed: number
    eligible: number
    ineligible: number
    needsReview: number
    approvedShortlist: number
    strongRecommendations: number
    interviewConsideration: number
    averageScore: number
    highestScore: number
  }
  roleStats: RoleStat[]
  scoreDistribution: { label: string; min: number; max: number; count: number }[]
  processingStatus: { status: string; count: number }[]
  recentApplicants: ApplicantBrief[]
  topApplicants: ApplicantBrief[]
  organization: Record<string, string>
  truncated: boolean
  generatedAt: string
}

export interface ShortlistItem {
  applicantId: string
  fullName: string
  email: string
  usn: string
  department: string
  yearOfStudy: string
  roles: string[]
  roleScore: number
  totalScore: number
  recommendation: Recommendation
  eligibilityStatus: string
  eligibilityFailures: string[]
  reviewStatus: ReviewStatus
  reviewDecision: string
  reviewedBy: string
  strongestEvidence: string[]
  concerns: string[]
  urgentReview: boolean
  documents: number
  rank: number
}

export interface ShortlistResponse {
  items: ShortlistItem[]
  total: number
  role: string
  minScore?: number | null
  maxScore?: number | null
}

export interface ReportRecord {
  report_id: string
  kind: string
  status: string
  created_at: string
  created_by: string
  s3_key: string
  filename: string
  size_bytes: number
  scope: Record<string, string>
  error: string
  downloadUrl?: string
}

export interface RoleConfig {
  id: string
  name: string
  description: string
  evaluation_focus: string[]
  interview_topics: string[]
  weights: Record<string, number>
}

export interface SettingsPayload {
  rubric: Record<string, unknown>
  eligibility: Record<string, unknown>
  roles: { version: string; default_role: string; roles: RoleConfig[] }
  field_mapping: { version: string; fields: Record<string, unknown>[] }
  processing: Record<string, unknown>
  organization: Record<string, string>
  aiPublic: {
    provider: string
    model: string
    baseUrl: string
    enabled: boolean
    timeoutSeconds: number
    maxRetries: number
    temperature: number
    apiKeyConfigured: boolean
  }
  environment: Record<string, unknown>
  meta: Record<string, { key: string; version: number; updated_at: string | null; updated_by: string; source: string }>
  serverTime: string
}

export interface AdminUser {
  username: string
  email: string
  status: string
  groups: string[]
}

export interface AdminList {
  items: AdminUser[]
  groups: string[]
  note?: string
}
