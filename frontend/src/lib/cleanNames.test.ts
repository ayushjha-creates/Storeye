import { describe, it, expect } from 'vitest'
import { cleanName } from './cleanNames'

describe('cleanName', () => {
  it('strips the word demo (token) from display names', () => {
    expect(cleanName('Storeye Demo Mart')).toBe('Storeye Mart')
    expect(cleanName('Demo Shelf Camera')).toBe('Shelf Camera')
    expect(cleanName('DEMO-BILL-0001')).toBe('BILL-0001')
    expect(cleanName('Storeye Demo-Mart')).toBe('Storeye Mart')
  })

  it('leaves clean names untouched', () => {
    expect(cleanName('Kiran General Store')).toBe('Kiran General Store')
    expect(cleanName('Storeye Mart')).toBe('Storeye Mart')
    expect(cleanName('BILL-0001')).toBe('BILL-0001')
  })

  it('handles nullish and blank values', () => {
    expect(cleanName(null)).toBe('')
    expect(cleanName(undefined)).toBe('')
    expect(cleanName('')).toBe('')
  })
})