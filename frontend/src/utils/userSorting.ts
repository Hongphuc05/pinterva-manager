export type SortableUser = {
  id: string
  username: string
  full_name?: string | null
  role: string
}

/**
 * Sorts users first by role precedence (admin -> support -> designer -> designer_trello),
 * then alphabetically (A-Z) by full_name or username using Vietnamese locale rules.
 */
export function sortUsersByRoleAndName<T extends SortableUser>(usersList: T[]): T[] {
  const roleOrder: Record<string, number> = {
    admin: 1,
    support: 2,
    designer: 3,
    'designer-trello': 4,
    designer_trello: 4,
  }

  return [...usersList].sort((a, b) => {
    const roleA = roleOrder[a.role] ?? 99
    const roleB = roleOrder[b.role] ?? 99
    if (roleA !== roleB) return roleA - roleB

    const nameA = (a.full_name || a.username || '').trim()
    const nameB = (b.full_name || b.username || '').trim()
    return nameA.localeCompare(nameB, 'vi', { sensitivity: 'base' })
  })
}
