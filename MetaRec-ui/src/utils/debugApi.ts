import type { DebugConfig, DebugRunDetail, DebugRunSummary, DebugSession, DebugUnitSpec } from './types'

export const DEBUG_BASE_URL = import.meta.env.VITE_API_BASE_URL ||
  (import.meta.env.PROD ? '' : 'http://localhost:8000') // I guess I'd better follow what api.ts is doing

async function debugFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${DEBUG_BASE_URL}${path}`, {
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
    throw new Error(`HTTP ${res.status} ${res.statusText}${detail ? `: ${detail}` : ''}`)
  }
  return parse() as T
}

export async function fetchOpenApiSpec(): Promise<any> {
  return debugFetch('/openapi.json', { method: 'GET' })
}

export function getDebugConfig(): Promise<DebugConfig> {
  return debugFetch<DebugConfig>('/internal/debug/config', { method: 'GET' })
}

// Auth is delegated to the main app session (login/logout live in api.ts).
// This only verifies that the current app session is an ADMIN; the server is
// authoritative and returns 401/403 otherwise.
export async function getDebugSession(): Promise<{ ok: boolean; user: DebugSession }> {
  return debugFetch('/internal/debug/session', { method: 'GET' })
}

export async function listDebugRuns(): Promise<{ runs: DebugRunSummary[] }> {
  return debugFetch('/internal/debug/behavior-tests', { method: 'GET' })
}

export async function startBehaviorDebugRun(payload: {
  query: string
  conversation_id?: string
  use_online_agent?: boolean
  auto_confirm?: boolean
  confirm_message?: string
  max_wait_seconds?: number
  poll_interval_ms?: number
}): Promise<{ ok: boolean; run_id: string; status: string }> {
  return debugFetch('/internal/debug/behavior-tests', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function trackBehaviorDebugTask(payload: {
  task_id: string
  user_id?: string
  conversation_id?: string
  max_wait_seconds?: number
  poll_interval_ms?: number
}): Promise<{ ok: boolean; run_id: string; status: string }> {
  return debugFetch('/internal/debug/behavior-tests/track', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function getBehaviorDebugRun(runId: string): Promise<DebugRunDetail> {
  return debugFetch(`/internal/debug/behavior-tests/${runId}`, { method: 'GET' })
}

export async function explainBehaviorDebugRun(runId: string): Promise<{ ok: boolean; mode: string; explanation: any }> {
  return debugFetch(`/internal/debug/behavior-tests/${runId}/explain`, {
    method: 'POST',
    body: JSON.stringify({ mode: 'nl_explain' }),
  })
}

export async function listDebugUnits(): Promise<{ units: DebugUnitSpec[] }> {
  return debugFetch('/internal/debug/unit-tests/units', { method: 'GET' })
}

export async function generateDebugUnitInput(unitName: string, mode: 'schema' | 'sample' | 'llm'): Promise<any> {
  return debugFetch('/internal/debug/unit-tests/generate-input', {
    method: 'POST',
    body: JSON.stringify({ unit_name: unitName, mode }),
  })
}

export async function runDebugUnit(payload: {
  unit_name: string
  input_mode: 'manual' | 'sample' | 'schema' | 'llm'
  input_data?: Record<string, any>
  use_llm_generation?: boolean
}): Promise<any> {
  return debugFetch('/internal/debug/unit-tests/run', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function generateDebugApiPlaygroundInput(payload: {
  mode: 'schema' | 'llm'
  schema: Record<string, any>
  method?: string
  path?: string
  summary?: string
}): Promise<{ ok: boolean; mode: string; input_data: any; validation_errors: string[] }> {
  return debugFetch('/internal/debug/api-playground/generate-input', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}
