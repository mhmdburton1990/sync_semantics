import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import { ValidationPanel } from './ValidationPanel'
import type { MeasureValidation, ValidationSummary } from '../types'

const results: MeasureValidation[] = [
  { name: 'rev', status: 'passed', dim_used: 'region', scalar_sql: 100, scalar_dax: 100, scalar_delta: 0, scalar_matched: true, by_dim: [], skip_reason: null },
  { name: 'margin', status: 'failed', dim_used: 'region', scalar_sql: 100, scalar_dax: 110, scalar_delta: 0.1, scalar_matched: false, by_dim: [], skip_reason: null },
  { name: 'fx', status: 'skipped', dim_used: null, scalar_sql: null, scalar_dax: null, scalar_delta: null, scalar_matched: null, by_dim: [], skip_reason: 'placeholder' },
]
const summary: ValidationSummary = { passed: 1, failed: 1, skipped: 1 }

describe('ValidationPanel', () => {
  it('renders summary counts and the skip reason', () => {
    render(<ValidationPanel results={results} summary={summary} />)
    expect(screen.getByText(/1 passed/)).toBeInTheDocument()
    expect(screen.getByText(/1 failed/)).toBeInTheDocument()
    expect(screen.getByText('placeholder')).toBeInTheDocument()
  })

  it('names the measure being validated when running', () => {
    render(<ValidationPanel results={results} summary={summary} running total={5} current="orders" />)
    expect(screen.getByText(/Validating orders \(4 of 5\)/i)).toBeInTheDocument()
  })

  it('shows a preparing message before the first measure starts', () => {
    render(<ValidationPanel results={[]} summary={{ passed: 0, failed: 0, skipped: 0 }} running total={5} current={null} />)
    expect(screen.getByText(/Preparing validation/i)).toBeInTheDocument()
  })
})

describe('ValidationPanel per-dimension breakdown', () => {
  it('renders by_dim sub-rows with their keys and values', () => {
    const withDims: MeasureValidation[] = [
      {
        name: 'total_quantity', status: 'passed', dim_used: 'c_mktsegment',
        scalar_sql: 100, scalar_dax: 100, scalar_delta: 0, scalar_matched: true,
        skip_reason: null,
        by_dim: [
          { key: 'BUILDING', sql: 60, dax: 60, delta: 0, matched: true },
          { key: 'AUTOMOBILE', sql: 40, dax: 41, delta: 0.025, matched: false },
        ],
      },
    ]
    const sum: ValidationSummary = { passed: 1, failed: 0, skipped: 0 }
    render(<ValidationPanel results={withDims} summary={sum} />)
    expect(screen.getByText('BUILDING')).toBeInTheDocument()
    expect(screen.getByText('AUTOMOBILE')).toBeInTheDocument()
  })
})
