import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'

import {
  EligibilityBadge,
  RecommendationBadge,
  ReviewBadge,
  ScoreBadge,
  StatusBadge,
} from './StatusBadges'

describe('ScoreBadge', () => {
  it('formats the score to one decimal place', () => {
    render(<ScoreBadge score={78.46} />)
    expect(screen.getByText('78.5')).toBeInTheDocument()
  })

  it('uses the tone palette that matches the score band', () => {
    const { container, rerender } = render(<ScoreBadge score={91} />)
    expect(container.firstElementChild?.className).toContain('emerald')

    rerender(<ScoreBadge score={70} />)
    expect(container.firstElementChild?.className).toContain('sky')

    rerender(<ScoreBadge score={55} />)
    expect(container.firstElementChild?.className).toContain('amber')

    rerender(<ScoreBadge score={20} />)
    expect(container.firstElementChild?.className).toContain('red')
  })
})

describe('RecommendationBadge', () => {
  it.each([
    ['STRONG_INTERVIEW', 'Strong interview'],
    ['INTERVIEW_CONSIDERATION', 'Interview consideration'],
    ['MANUAL_REVIEW', 'Manual review'],
    ['ELIGIBILITY_REVIEW', 'Eligibility review'],
    ['NEEDS_REVIEW', 'Needs review'],
  ])('renders %s as %s', (value, label) => {
    render(<RecommendationBadge value={value} />)
    expect(screen.getByText(label)).toBeInTheDocument()
  })

  it('humanises an unknown value instead of crashing', () => {
    render(<RecommendationBadge value="SOME_NEW_STATE" />)
    expect(screen.getByText('Some New State')).toBeInTheDocument()
  })
})

describe('StatusBadge', () => {
  it('humanises processing states', () => {
    render(<StatusBadge value="NEEDS_REVIEW" />)
    expect(screen.getByText('Needs Review')).toBeInTheDocument()
  })
})

describe('ReviewBadge', () => {
  it('renders review decisions', () => {
    render(<ReviewBadge value="APPROVED" />)
    expect(screen.getByText('Approved')).toBeInTheDocument()
  })
})

describe('EligibilityBadge', () => {
  it('maps eligibility states to explicit labels', () => {
    const { rerender } = render(<EligibilityBadge value="PASS" />)
    expect(screen.getByText('Eligible')).toBeInTheDocument()

    rerender(<EligibilityBadge value="FAIL" />)
    expect(screen.getByText('Ineligible')).toBeInTheDocument()

    rerender(<EligibilityBadge value="UNKNOWN" />)
    expect(screen.getByText('Unverified')).toBeInTheDocument()
  })
})
