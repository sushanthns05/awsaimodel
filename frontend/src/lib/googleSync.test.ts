import { beforeEach, describe, expect, it } from 'vitest'

import {
  canonicalizeRole,
  clearStoredLiveApplicants,
  extractApplicantPriorities,
  getStoredLiveDetail,
  importGoogleFormResponses,
  roleMatchesFilter,
} from './googleSync'

beforeEach(() => {
  clearStoredLiveApplicants()
  localStorage.removeItem('sbg_eval_version')
})

describe('extractApplicantPriorities', () => {
  it('reads only the roles the candidate applied for, ignoring suggestive skill text', () => {
    const result = extractApplicantPriorities({
      'Priority 1': 'Operations & Logistics',
      'Priority 2': 'Social Media',
      'Which skills do you possess?': 'Event planning, public speaking, coordination',
      Department: 'Mechanical Engineering',
    })

    expect(result.priority1).toBe('Operations and Logistics')
    expect(result.priority2).toBe('Social Media, Marketing and Outreach')
    expect(result.roles).toEqual(['Operations and Logistics', 'Social Media, Marketing and Outreach'])
    expect(result.roles).not.toContain('Event and PR Management')
  })

  it('does not invent a second role when the candidate applied for one role only', () => {
    const result = extractApplicantPriorities({
      'Which team(s) are you applying for?': 'Operations & Logistics',
      'Which skills do you possess?': 'event coordination and public relations',
      Department: 'Event management club',
    })

    expect(result.roles).toEqual(['Operations and Logistics'])
    expect(result.priority1).toBe('Operations and Logistics')
    expect(result.priority2).toBe('')
  })

  it('reads both roles from a single multi-select form cell', () => {
    const result = extractApplicantPriorities({
      'Which team(s) are you applying for?': 'Operations & Logistics; Social Media',
    })

    expect(result.roles).toEqual(['Operations and Logistics', 'Social Media, Marketing and Outreach'])
  })
})

describe('role matching', () => {
  it('canonicalises both taxonomies to the same role name', () => {
    expect(canonicalizeRole('Operations & Logistics')).toBe('Operations and Logistics')
    expect(canonicalizeRole('social_media')).toBe('Social Media, Marketing and Outreach')
    expect(canonicalizeRole('event_management')).toBe('Event and PR Management')
    expect(canonicalizeRole('creative_design')).toBe('Creative and Decoration')
  })

  it('matches every community role against both frontend and backend role ids', () => {
    const equivalentPairs = [
      ['Technical Team', 'technical_team'],
      ['Event and PR Management', 'event_pr_management'],
      ['Event & pr management team', 'event_pr_management'],
      ['Event and PR Management', 'event_management'],
      ['Creative and Decoration', 'creative_decoration'],
      ['Creative & decoration team', 'creative_decoration'],
      ['Creative and Decoration', 'creative_design'],
      ['Social Media, Marketing and Outreach', 'social_media_marketing_outreach'],
      ['Social Media', 'social_media_marketing_outreach'],
      ['Social media team', 'social_media_marketing_outreach'],
      ['Social Media, Marketing and Outreach', 'social_media'],
      ['Social Media, Marketing and Outreach', 'marketing_outreach'],
      ['Operations and Logistics', 'operations_logistics'],
      ['Operations & logistics team', 'operations_logistics'],
      ['Operations & Logistics', 'operations_logistics'],
    ]

    equivalentPairs.forEach(([displayName, filterId]) => {
      expect(roleMatchesFilter(displayName, filterId)).toBe(true)
    })

    expect(roleMatchesFilter('Operations and Logistics', 'event_pr_management')).toBe(false)
  })
})

describe('importGoogleFormResponses', () => {
  it('stores evaluations only for the applied roles', () => {
    const result = importGoogleFormResponses(
      [
        {
          'Full Name': 'Test Candidate',
          'Email Address': 'test.candidate@sjbit.edu.in',
          USN: '1JS23CS001',
          'Priority 1': 'Operations & Logistics',
          'Priority 2': 'Social Media',
          'Which skills do you possess?': 'Event planning and coordination',
        },
      ],
      true
    )

    expect(result.errors).toEqual([])
    const applicant = result.applicants[0]
    expect(applicant.roles).toEqual(['Operations and Logistics', 'Social Media, Marketing and Outreach'])
    expect(applicant.priority1?.role).toBe('Operations and Logistics')
    expect(applicant.priority2?.role).toBe('Social Media, Marketing and Outreach')

    const detail = getStoredLiveDetail(applicant.applicantId)
    expect(detail?.evaluation?.role_evaluations?.map((evaluation) => evaluation.role_id)).toEqual([
      'Operations and Logistics',
      'Social Media, Marketing and Outreach',
    ])
  })
})
