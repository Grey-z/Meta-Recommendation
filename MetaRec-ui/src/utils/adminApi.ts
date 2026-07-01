// Admin dashboard + user-management (CMS) API client. Mirrors debugApi.ts's
// lightweight fetch wrapper (cookie-based auth, no Zod). All endpoints are
// gated server-side on the ADMIN role.

export const ADMIN_BASE_URL = import.meta.env.VITE_API_BASE_URL ||
  (import.meta.env.PROD ? '' : 'http://localhost:8000')

async function adminFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${ADMIN_BASE_URL}${path}`, {
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers || {}),
    },
    ...init,
  })
  const text = await res.text().catch(() => '')
  const parse = () => {
    try { return text ? JSON.parse(text) : {} } catch { return text }
  }
  if (!res.ok) {
    const parsed = parse() as any
    const detail = typeof parsed === 'string' ? parsed : parsed?.detail || text
    // Keep the status code in the message so callers can detect 409 (stale edit).
    throw new Error(`HTTP ${res.status} ${res.statusText}${detail ? `: ${detail}` : ''}`)
  }
  return parse() as T
}

export type AdminUser = {
  id: string
  kind: string
  role: string
  email: string | null
  display_name: string | null
  status: string
  created_at: string | null
  updated_at: string | null
  last_seen_at: string | null
}

export type AdminUserList = {
  items: AdminUser[]
  total: number
  limit: number
  offset: number
}

export type AdminStats = {
  tasks: { total: number; completed: number; errored: number; success_rate: number }
  tokens: {
    total_tokens: number
    prompt_tokens: number
    completion_tokens: number
    cost_usd: number
    last_7d_total_tokens: number
  }
  users: { total: number; registered: number; guests: number; new_registered_last_7d: number }
  conversations: { total_created: number; active_sessions: number }
  feedback: FeedbackStatsSummary & {
    // Per-domain slices (restaurant / movie / music / book / product / unknown),
    // most feedback first. The top-level fields above are the all-domains rollup.
    domains: Array<FeedbackStatsSummary & { domain: string }>
  }
  generated_at: string
}

export type FeedbackStatsSummary = {
  total: number
  satisfied: number
  unsatisfied: number
  satisfaction_ratio: number | null
  // `reason` is the stable code; `label` is the human-readable text for display.
  reasons: Array<{ reason: string; label: string; count: number }>
}

export type AdminSessionInfo = {
  ok: boolean
  user: { id: string; email: string | null; display_name: string | null; role: string }
}

export type ListUsersParams = {
  limit?: number
  offset?: number
  search?: string
  role?: string
  status?: string
  kind?: string
}

export type CreateUserPayload = {
  email: string
  password: string
  display_name?: string | null
  role?: string
  status?: string
}

export type UpdateUserPayload = {
  expected_updated_at?: string | null
  role?: string
  status?: string
  display_name?: string | null
}

export function getAdminSession(): Promise<AdminSessionInfo> {
  return adminFetch<AdminSessionInfo>('/api/admin/session', { method: 'GET' })
}

export function getAdminStats(): Promise<AdminStats> {
  return adminFetch<AdminStats>('/api/admin/stats', { method: 'GET' })
}

export function listUsers(params: ListUsersParams = {}): Promise<AdminUserList> {
  const q = new URLSearchParams()
  if (params.limit != null) q.set('limit', String(params.limit))
  if (params.offset != null) q.set('offset', String(params.offset))
  if (params.search) q.set('search', params.search)
  if (params.role) q.set('role', params.role)
  if (params.status) q.set('status', params.status)
  if (params.kind) q.set('kind', params.kind)
  const qs = q.toString()
  return adminFetch<AdminUserList>(`/api/admin/users${qs ? `?${qs}` : ''}`, { method: 'GET' })
}

export function createUser(payload: CreateUserPayload): Promise<AdminUser> {
  return adminFetch<AdminUser>('/api/admin/users', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function updateUser(userId: string, payload: UpdateUserPayload): Promise<AdminUser> {
  return adminFetch<AdminUser>(`/api/admin/users/${encodeURIComponent(userId)}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export function deleteUser(userId: string): Promise<AdminUser> {
  return adminFetch<AdminUser>(`/api/admin/users/${encodeURIComponent(userId)}`, {
    method: 'DELETE',
  })
}
