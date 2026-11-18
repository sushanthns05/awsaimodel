import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApplicantBrief } from '../types'
import { exportApplicantsToExcel } from './excelExport'
import { exportContactsPdf } from './contactsPdfGenerator'
import { clearStoredLiveApplicants } from './googleSync'

beforeEach(() => {
  clearStoredLiveApplicants()
  localStorage.clear()
})

const mockApplicants: ApplicantBrief[] = [
  {
    applicantId: 'AWS-2026-001',
    fullName: 'Yogesh R',
    email: 'yogesh@sjbit.edu.in',
    phone: '9876543210',
    usn: '1JB24CS228',
    department: 'Computer Science and Engineering',
    yearOfStudy: '3rd Year',
    roles: ['Operations and Logistics', 'Technical Team'],
    submittedAt: '2026-10-11T05:47:00.000Z',
    processingStatus: 'COMPLETED',
    totalScore: 93,
    recommendation: 'STRONG_INTERVIEW',
    eligibilityStatus: 'PASS',
    reviewStatus: 'PENDING',
    urgentReview: false,
    documents: 1,
    rubricVersion: '2026.2',
    priority1: {
      role: 'Operations and Logistics',
      priority: 'Priority 1',
      score: 93,
      rank: 1,
      totalInRole: 10,
      fit: 'high',
      recommendation: 'STRONG_INTERVIEW',
    },
    priority2: {
      role: 'Technical Team',
      priority: 'Priority 2',
      score: 89,
      rank: 9,
      totalInRole: 25,
      fit: 'high',
      recommendation: 'STRONG_INTERVIEW',
    },
    shortlistPriority: {
      role: 'Operations and Logistics',
      score: 93,
      rank: 1,
      sourcePriority: 'Priority 1',
      reason: 'Higher score achieved in Priority 1 (93.0 vs 89.0)',
    },
  },
  {
    applicantId: 'AWS-2026-002',
    fullName: 'Durga Shree D',
    email: 'durga@sjbit.edu.in',
    phone: '+91 9123456780',
    usn: '1JB24IS052',
    department: 'Information Science and Engineering',
    yearOfStudy: '3rd Year',
    roles: ['Event and PR Management', 'Creative and Decoration'],
    submittedAt: '2026-10-11T06:00:00.000Z',
    processingStatus: 'COMPLETED',
    totalScore: 92,
    recommendation: 'STRONG_INTERVIEW',
    eligibilityStatus: 'PASS',
    reviewStatus: 'PENDING',
    urgentReview: false,
    documents: 0,
    rubricVersion: '2026.2',
    priority1: {
      role: 'Event and PR Management',
      priority: 'Priority 1',
      score: 92,
      rank: 3,
      totalInRole: 15,
      fit: 'high',
      recommendation: 'STRONG_INTERVIEW',
    },
  },
]

describe('Excel Export', () => {
  it('exports applicants to an Excel workbook without errors', () => {
    // Mock URL and document.createElement
    const createObjectURLMock = vi.fn().mockReturnValue('blob:mock-url')
    const revokeObjectURLMock = vi.fn()
    vi.stubGlobal('URL', {
      createObjectURL: createObjectURLMock,
      revokeObjectURL: revokeObjectURLMock,
    })

    const appendChildSpy = vi.spyOn(document.body, 'appendChild')
    const removeChildSpy = vi.spyOn(document.body, 'removeChild')

    // Call export
    exportApplicantsToExcel(mockApplicants)

    expect(createObjectURLMock).toHaveBeenCalledTimes(1)
    expect(revokeObjectURLMock).toHaveBeenCalledWith('blob:mock-url')
    expect(appendChildSpy).toHaveBeenCalled()
    expect(removeChildSpy).toHaveBeenCalled()
  })

  it('throws an error if applicants array is empty', () => {
    expect(() => exportApplicantsToExcel([])).toThrow('No applicant records available to export.')
  })
})

describe('Contacts PDF Export', () => {
  it('generates a contacts PDF without errors', () => {
    expect(() => exportContactsPdf(mockApplicants)).not.toThrow()
  })

  it('throws an error if no applicants exist', () => {
    expect(() => exportContactsPdf([])).toThrow('No applicant contact data available to export.')
  })
})
