import { describe, it, expect } from 'vitest'
import { sortUsersByRoleAndName, type SortableUser } from './userSorting'

describe('sortUsersByRoleAndName', () => {
  it('sorts users by role order (admin -> support -> designer -> designer_trello) and alphabetically A-Z by name', () => {
    const input: SortableUser[] = [
      { id: '1', username: 'trong', full_name: 'Trọng', role: 'designer' },
      { id: '2', username: 'hieu', full_name: 'Hiếu', role: 'designer' },
      { id: '3', username: 'ngoc_anh', full_name: 'Ngọc Anh', role: 'designer_trello' },
      { id: '4', username: 'chien', full_name: 'Chiến', role: 'designer_trello' },
      { id: '5', username: 'dan', full_name: 'Dân', role: 'designer' },
      { id: '6', username: 'sup1', full_name: 'An Support', role: 'support' },
      { id: '7', username: 'adm1', full_name: 'Bình Admin', role: 'admin' },
    ]

    const result = sortUsersByRoleAndName(input)

    expect(result.map((u) => `${u.full_name} (${u.role})`)).toEqual([
      'Bình Admin (admin)',
      'An Support (support)',
      'Dân (designer)',
      'Hiếu (designer)',
      'Trọng (designer)',
      'Chiến (designer_trello)',
      'Ngọc Anh (designer_trello)',
    ])
  })
})
