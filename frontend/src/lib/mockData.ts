import type {
  ApplicantBrief,
  ApplicantDetail,
  Overview,
  ReportRecord,
  SettingsPayload,
  ShortlistResponse,
} from '../types'
import {
  computeLiveOverview,
  getStoredLiveApplicants,
  getStoredLiveDetail,
} from './googleSync'

export function getMockOverview(): Overview {
  const stored = getStoredLiveApplicants()
  if (stored.length > 0) {
    return computeLiveOverview(stored)
  }
  return {
    stats: {
      totalApplications: 0,
      processed: 0,
      pending: 0,
      failed: 0,
      eligible: 0,
      ineligible: 0,
      needsReview: 0,
      approvedShortlist: 0,
      strongRecommendations: 0,
      interviewConsideration: 0,
      averageScore: 0,
      highestScore: 0,
    },
    roleStats: [
      {
        roleId: 'cloud_architecture',
        name: 'Cloud Architecture & AWS Services',
        applicants: 0,
        processed: 0,
        eligible: 0,
        shortlisted: 0,
        averageScore: 0,
        strongRecommendations: 0,
      },
      {
        roleId: 'full_stack',
        name: 'Full-Stack Development (React & Node)',
        applicants: 0,
        processed: 0,
        eligible: 0,
        shortlisted: 0,
        averageScore: 0,
        strongRecommendations: 0,
      },
      {
        roleId: 'ai_ml',
        name: 'AI / Machine Learning & Generative AI',
        applicants: 0,
        processed: 0,
        eligible: 0,
        shortlisted: 0,
        averageScore: 0,
        strongRecommendations: 0,
      },
    ],
    scoreDistribution: [
      { label: '80–100 (Strong Interview)', min: 80, max: 100, count: 0 },
      { label: '65–79 (Consideration)', min: 65, max: 79, count: 0 },
      { label: '50–64 (Manual Review)', min: 50, max: 64, count: 0 },
      { label: 'Below 50 (Ineligible)', min: 0, max: 49, count: 0 },
    ],
    processingStatus: [],
    recentApplicants: [],
    topApplicants: [],
    organization: {
      name: 'AWS Student Builder Group',
      institution: 'SJB Institute of Technology',
      cycle: '2026–27',
    },
    truncated: false,
    generatedAt: new Date().toISOString(),
  }
}

export function getMockApplicantsList(): ApplicantBrief[] {
  return getStoredLiveApplicants()
}

export function getMockApplicantDetail(id: string): ApplicantDetail | null {
  const detail = getStoredLiveDetail(id)
  if (detail) return detail
  const brief = getStoredLiveApplicants().find((a) => a.applicantId === id)
  if (!brief) return null
  return {
    applicantId: brief.applicantId,
    brief,
    applicant: {
      applicant_id: brief.applicantId,
      source_response_id: 'GF-RESP',
      submitted_at: brief.submittedAt,
      full_name: brief.fullName,
      email: brief.email,
      usn: brief.usn,
      phone: '',
      department: brief.department,
      year_of_study: brief.yearOfStudy,
      roles: brief.roles,
      responses: {
        'Full Name': brief.fullName,
        'Email Address': brief.email,
        'USN': brief.usn,
        'Department': brief.department,
        'Year of Study': brief.yearOfStudy,
        'Applied Roles': brief.roles.join(', '),
      },
      processing_status: brief.processingStatus,
      processing_error: '',
      extracted_text_chars: 2500,
      extraction_summary: { source: 'Google Form' },
      application_complete: true,
      missing_required_fields: [],
      urgent_review: false,
      review_status: brief.reviewStatus,
      review_decision: '',
      review_notes: '',
      reviewed_by: '',
      total_score: brief.totalScore,
      recommendation: brief.recommendation,
      eligibility_status: brief.eligibilityStatus,
      eligibility_failures: [],
      role_scores: { [brief.roles[0]]: brief.totalScore },
      latest_evaluation_id: `eval-${brief.applicantId}`,
      rubric_version: '2026.1',
      form_title: 'AWS Student Builder Group SJBIT Recruitment 2026-27',
      created_at: brief.submittedAt,
      updated_at: new Date().toISOString(),
    },
    documents: [],
    evaluation: null,
    evaluationHistory: [],
    audit: [],
  }
}

export function getMockShortlist(): ShortlistResponse {
  const list = getStoredLiveApplicants()
  return {
    items: list.map((app, index) => ({
      applicantId: app.applicantId,
      fullName: app.fullName,
      email: app.email,
      usn: app.usn,
      department: app.department,
      yearOfStudy: app.yearOfStudy,
      roles: app.roles,
      roleScore: app.totalScore,
      totalScore: app.totalScore,
      recommendation: app.recommendation,
      eligibilityStatus: app.eligibilityStatus,
      eligibilityFailures: [],
      reviewStatus: app.reviewStatus,
      reviewDecision: app.reviewStatus === 'APPROVED' ? 'SHORTLISTED' : 'PENDING',
      reviewedBy: '',
      strongestEvidence: ['Responses verified against rubric requirements.'],
      concerns: [],
      urgentReview: app.urgentReview,
      documents: app.documents,
      rank: index + 1,
    })),
    total: list.length,
    role: 'all',
  }
}

export const mockReportsList: { items: ReportRecord[]; count: number } = {
  items: [],
  count: 0,
}

export const mockSettings: SettingsPayload = {
  rubric: {
    version: '2026.1',
    max_total_score: 100,
    criteria: [
      { id: 'relevant_skills', name: 'Relevant technical skills', max_score: 20 },
      { id: 'projects_experience', name: 'Projects & practical experience', max_score: 20 },
      { id: 'role_knowledge', name: 'Role-specific domain knowledge', max_score: 15 },
      { id: 'problem_solving', name: 'Problem-solving and technical agility', max_score: 15 },
      { id: 'communication', name: 'Communication & presentation', max_score: 10 },
      { id: 'commitment', name: 'Commitment & availability', max_score: 10 },
      { id: 'leadership', name: 'Leadership & collaboration', max_score: 10 },
    ],
  },
  eligibility: {
    version: '2026.1',
    rules: [
      { id: 'enrolled_student', label: 'SJBIT Enrolled Student', type: 'required', mandatory: true },
      { id: 'minimum_year', label: '2nd, 3rd or 4th Year', type: 'one_of', mandatory: true },
    ],
  },
  roles: {
    version: '2026.1',
    default_role: 'cloud_architecture',
    roles: [
      {
        id: 'cloud_architecture',
        name: 'Cloud Architecture & AWS Services',
        description: 'Design and deploy resilient AWS solutions',
        evaluation_focus: ['AWS Services', 'Cloud Architecture'],
        interview_topics: ['AWS Well-Architected Framework'],
        weights: { relevant_skills: 1.2, role_knowledge: 1.2 },
      },
      {
        id: 'full_stack',
        name: 'Full-Stack Development (React & Node)',
        description: 'Build web applications for SBG initiatives',
        evaluation_focus: ['React', 'TypeScript', 'Node.js', 'FastAPI'],
        interview_topics: ['State management', 'REST APIs'],
        weights: { relevant_skills: 1.1, projects_experience: 1.2 },
      },
      {
        id: 'ai_ml',
        name: 'AI / Machine Learning & Generative AI',
        description: 'Integrate LLMs and build intelligent systems',
        evaluation_focus: ['LLMs', 'Prompt Engineering', 'Python'],
        interview_topics: ['Model evaluation', 'Structured output'],
        weights: { relevant_skills: 1.2, problem_solving: 1.2 },
      },
      {
        id: 'devops',
        name: 'DevOps & Site Reliability',
        description: 'CI/CD pipelines, containerization and automation',
        evaluation_focus: ['Docker', 'GitHub Actions', 'Terraform'],
        interview_topics: ['Pipeline security', 'Monitoring'],
        weights: { relevant_skills: 1.1, problem_solving: 1.2 },
      },
      {
        id: 'community',
        name: 'Community, Media & Event Management',
        description: 'Coordinate AWS events and builder workshops',
        evaluation_focus: ['Communication', 'Event Logistics'],
        interview_topics: ['Community building', 'Leadership'],
        weights: { communication: 1.3, leadership: 1.3 },
      },
    ],
  },
  field_mapping: {
    version: '2026.1',
    fields: [
      { canonical: 'full_name', aliases: ['Full Name', 'Name', 'Student Name'] },
      { canonical: 'email', aliases: ['Email Address', 'Email', 'College Email'] },
      { canonical: 'usn', aliases: ['University Seat Number (USN)', 'USN'] },
      { canonical: 'department', aliases: ['Department', 'Branch'] },
      { canonical: 'year_of_study', aliases: ['Year of Study', 'Year'] },
      { canonical: 'roles', aliases: ['Which team(s) are you applying for?', 'Preferred Team', 'Roles'] },
    ],
  },
  processing: {
    textract_enabled: true,
    max_submission_bytes: 8388608,
    max_document_bytes: 6291456,
  },
  organization: {
    name: 'AWS Student Builder Group',
    institution: 'SJB Institute of Technology',
    cycle: '2026–27',
  },
  aiPublic: {
    provider: 'gemini',
    model: 'gemini-1.5-flash',
    baseUrl: 'https://generativelanguage.googleapis.com/v1beta/openai',
    enabled: true,
    timeoutSeconds: 90,
    maxRetries: 4,
    temperature: 0.1,
    apiKeyConfigured: true,
  },
  environment: {
    localMode: false,
    environment: 'production',
    region: 'ap-south-1',
  },
  meta: {
    rubric: { key: 'rubric', version: 1, updated_at: null, updated_by: 'system', source: 'default' },
    eligibility: { key: 'eligibility', version: 1, updated_at: null, updated_by: 'system', source: 'default' },
    roles: { key: 'roles', version: 1, updated_at: null, updated_by: 'system', source: 'default' },
    field_mapping: { key: 'field_mapping', version: 1, updated_at: null, updated_by: 'system', source: 'default' },
  },
  serverTime: new Date().toISOString(),
}
