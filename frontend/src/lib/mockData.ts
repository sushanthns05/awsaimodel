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
        roleId: 'technical_team',
        name: 'Technical Team',
        applicants: 0,
        processed: 0,
        eligible: 0,
        shortlisted: 0,
        averageScore: 0,
        strongRecommendations: 0,
      },
      {
        roleId: 'event_pr_management',
        name: 'Event and PR Management',
        applicants: 0,
        processed: 0,
        eligible: 0,
        shortlisted: 0,
        averageScore: 0,
        strongRecommendations: 0,
      },
      {
        roleId: 'creative_decoration',
        name: 'Creative and Decoration',
        applicants: 0,
        processed: 0,
        eligible: 0,
        shortlisted: 0,
        averageScore: 0,
        strongRecommendations: 0,
      },
      {
        roleId: 'social_media_marketing_outreach',
        name: 'Social Media, Marketing and Outreach',
        applicants: 0,
        processed: 0,
        eligible: 0,
        shortlisted: 0,
        averageScore: 0,
        strongRecommendations: 0,
      },
      {
        roleId: 'operations_logistics',
        name: 'Operations and Logistics',
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
    version: '2026.2',
    default_role: 'technical_team',
    roles: [
      {
        id: 'technical_team',
        name: 'Technical Team',
        description: 'Cloud architecture, web development, software engineering and AI projects for SBG',
        evaluation_focus: ['AWS Services', 'Programming', 'Cloud Computing', 'AI/ML', 'Problem Solving'],
        interview_topics: ['AWS Architecture', 'Data structures', 'Project implementation'],
        weights: { tech_areas: 1.2, tech_proficiency: 1.1, projects_hackathons: 1.2 },
      },
      {
        id: 'event_pr_management',
        name: 'Event and PR Management',
        description: 'Planning, organizing and leading technical workshops, hackathons and public relations',
        evaluation_focus: ['Event Planning', 'Public Speaking', 'Communication', 'Leadership'],
        interview_topics: ['Event coordination', 'Conflict resolution', 'Campus outreach'],
        weights: { team_skills_leadership: 1.3, strongest_skill_contribution: 1.2 },
      },
      {
        id: 'creative_decoration',
        name: 'Creative and Decoration',
        description: 'UI/UX design, visual banners, aesthetic venue decoration and creative storytelling',
        evaluation_focus: ['Design', 'Creativity', 'Decoration', 'Visual Storytelling'],
        interview_topics: ['Design tools', 'Venue staging', 'Creative portfolio'],
        weights: { team_skills_leadership: 1.2, strongest_skill_contribution: 1.2 },
      },
      {
        id: 'social_media_marketing_outreach',
        name: 'Social Media, Marketing and Outreach',
        description: 'Managing Instagram, LinkedIn, campus marketing campaigns and builder community engagement',
        evaluation_focus: ['Social Media', 'Content Creation', 'Marketing', 'Communication', 'Outreach'],
        interview_topics: ['Campaign metrics', 'Community growth', 'Content creation'],
        weights: { team_skills_leadership: 1.2, strongest_skill_contribution: 1.2 },
      },
      {
        id: 'operations_logistics',
        name: 'Operations and Logistics',
        description: 'Resource management, schedule tracking, campus coordination and operational efficiency',
        evaluation_focus: ['Logistics', 'Operations', 'Resource Management', 'Organization'],
        interview_topics: ['Resource planning', 'Vendor coordination', 'Execution timelines'],
        weights: { team_skills_leadership: 1.3, projects_hackathons: 1.1 },
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
