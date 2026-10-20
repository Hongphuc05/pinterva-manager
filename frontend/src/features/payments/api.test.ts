import { describe, expect, it } from 'vitest'
import { recentWeeks } from './api'

describe('recentWeeks', () => {
  it('starts on Monday, runs to Sunday, newest first', () => {
    const weeks = recentWeeks(3, new Date(2026, 9, 21)) // Wednesday 21/10/2026
    expect(weeks.map((w) => w.value)).toEqual(['2026-10-19', '2026-10-12', '2026-10-05'])
    expect(weeks[0].label).toBe('Tuần này (19/10 – 25/10)')
    expect(weeks[1].label).toBe('Tuần trước (12/10 – 18/10)')
  })

  it('a Sunday still belongs to the week that began the Monday before', () => {
    expect(recentWeeks(1, new Date(2026, 9, 25))[0].value).toBe('2026-10-19')
  })
})
