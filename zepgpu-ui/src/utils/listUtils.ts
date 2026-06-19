/** Always return an array — handles bare arrays and `{ items: T[] }` API wrappers. */
export function ensureList<T>(
  value: T[] | Record<string, unknown> | null | undefined,
  nestedKey?: string,
): T[] {
  if (Array.isArray(value)) return value
  if (value && nestedKey && typeof value === 'object' && Array.isArray(value[nestedKey])) {
    return value[nestedKey] as T[]
  }
  return []
}
