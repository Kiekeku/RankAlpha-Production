export type Role = 'viewer' | 'analyst' | 'operator' | 'admin'

export function hasRole(roles: string[] | undefined | null, required: Role | Role[]): boolean {
  if (!roles || roles.length === 0) return false
  const normalized = new Set(roles.map(r => r.toLowerCase()))
  const targets = Array.isArray(required) ? required : [required]
  return targets.some(role => normalized.has(role))
}
