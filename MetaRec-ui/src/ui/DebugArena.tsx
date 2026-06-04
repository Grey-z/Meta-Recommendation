import React, { useEffect, useMemo, useRef, useState } from 'react'
import type { DebugRunDetail, DebugRunSummary, DebugUnitSpec, OpenApiSpec } from '../utils/types'
import '../style/DebugPage.css'
import {
  DEBUG_BASE_URL,
  explainBehaviorDebugRun,
  fetchOpenApiSpec,
  generateDebugApiPlaygroundInput,
  generateDebugUnitInput,
  getBehaviorDebugRun,
  listDebugRuns,
  listDebugUnits,
  runDebugUnit,
  startBehaviorDebugRun,
  trackBehaviorDebugTask,
} from '../utils/debugApi'

function pretty(value: any): string {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function formatMs(ms?: number | null): string {
  if (typeof ms !== 'number') return '-'
  return `${ms} ms`
}

function describeValue(value: any): string {
  if (value === null) return 'null'
  if (value === undefined) return 'undefined'
  if (Array.isArray(value)) return `Array(${value.length})`
  if (typeof value === 'object') return `Object(${Object.keys(value).length} keys)`
  if (typeof value === 'string') return value.length > 120 ? `${value.slice(0, 117)}...` : value
  return String(value)
}

function renderStructuredValue(value: any, depth = 0): JSX.Element {
  if (value === null || value === undefined || typeof value !== 'object') {
    return <span className="debug-json-leaf">{describeValue(value)}</span>
  }

  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="debug-json-leaf">[]</span>
    return (
      <div className="debug-json-tree">
        {value.slice(0, 8).map((item, idx) => (
          <div key={idx} className="debug-json-row">
            <span className="debug-json-key">[{idx}]</span>
            <div className="debug-json-value">{renderStructuredValue(item, depth + 1)}</div>
          </div>
        ))}
        {value.length > 8 && (
          <div className="debug-json-row">
            <span className="debug-json-key">...</span>
            <span className="debug-json-leaf">{value.length - 8} more items</span>
          </div>
        )}
      </div>
    )
  }

  const entries = Object.entries(value)
  if (!entries.length) return <span className="debug-json-leaf">{'{}'}</span>

  return (
    <div className={`debug-json-tree ${depth > 0 ? 'nested' : ''}`}>
      {entries.map(([key, val]) => (
        <div key={key} className="debug-json-row">
          <span className="debug-json-key">{key}</span>
          <div className="debug-json-value">
            {depth >= 2 || val === null || typeof val !== 'object'
              ? <span className="debug-json-leaf">{describeValue(val)}</span>
              : renderStructuredValue(val, depth + 1)}
          </div>
        </div>
      ))}
    </div>
  )
}

type ApiOperationParam = {
  name: string
  in: 'path' | 'query' | string
  required?: boolean
  description?: string
  schema?: Record<string, any>
}

type ApiOperation = {
  id: string
  method: string
  path: string
  summary: string
  description?: string
  tags: string[]
  operationId?: string
  parameters: ApiOperationParam[]
  requestBodySchema?: Record<string, any> | null
  requestBodyRequired?: boolean
  requestContentType?: string | null
  responses?: Record<string, any>
}

function resolveRef(ref: string, spec: OpenApiSpec): any {
  if (!ref.startsWith('#/')) return null
  const parts = ref.slice(2).split('/')
  let current: any = spec
  for (const part of parts) {
    current = current?.[part]
    if (current === undefined) return null
  }
  return current
}

function resolveSchema(schema: any, spec: OpenApiSpec, seen = new Set<string>()): any {
  if (!schema || typeof schema !== 'object') return schema
  if (schema.$ref && typeof schema.$ref === 'string') {
    if (seen.has(schema.$ref)) return { type: 'object' }
    seen.add(schema.$ref)
    const target = resolveRef(schema.$ref, spec)
    const resolved = resolveSchema(target, spec, seen)
    const { $ref: _, ...rest } = schema
    return { ...(resolved || {}), ...rest }
  }
  if (Array.isArray(schema.allOf)) {
    return schema.allOf.reduce((acc: any, part: any) => {
      const resolved = resolveSchema(part, spec, seen)
      return { ...(acc || {}), ...(resolved || {}) }
    }, {})
  }
  const next: any = { ...schema }
  if (next.items) next.items = resolveSchema(next.items, spec, seen)
  if (next.properties && typeof next.properties === 'object') {
    const props: Record<string, any> = {}
    for (const [k, v] of Object.entries(next.properties)) {
      props[k] = resolveSchema(v, spec, new Set(seen))
    }
    next.properties = props
  }
  return next
}

function buildApiOperations(spec: OpenApiSpec | null): ApiOperation[] {
  if (!spec?.paths || typeof spec.paths !== 'object') return []
  const out: ApiOperation[] = []
  for (const [path, pathItem] of Object.entries(spec.paths as Record<string, any>)) {
    if (!pathItem || typeof pathItem !== 'object') continue
    const pathLevelParams = Array.isArray((pathItem as any).parameters) ? (pathItem as any).parameters : []
    for (const method of ['get', 'post', 'put', 'patch', 'delete', 'options', 'head']) {
      const op = (pathItem as any)[method]
      if (!op || typeof op !== 'object') continue
      const rawParams = [...pathLevelParams, ...(Array.isArray(op.parameters) ? op.parameters : [])]
      const resolvedParams: ApiOperationParam[] = rawParams.map((p: any) => {
        const resolvedParam = p?.$ref ? resolveRef(p.$ref, spec) || p : p
        return {
          name: String(resolvedParam?.name || ''),
          in: String(resolvedParam?.in || 'query'),
          required: Boolean(resolvedParam?.required),
          description: resolvedParam?.description,
          schema: resolveSchema(resolvedParam?.schema || {}, spec),
        }
      }).filter(p => p.name)

      const content = op.requestBody?.content || {}
      const requestContentType = content['application/json']
        ? 'application/json'
        : (Object.keys(content)[0] || null)
      const requestBodySchema = requestContentType ? resolveSchema(content[requestContentType]?.schema || null, spec) : null

      out.push({
        id: `${method.toUpperCase()} ${path}`,
        method: method.toUpperCase(),
        path,
        summary: op.summary || op.operationId || `${method.toUpperCase()} ${path}`,
        description: op.description,
        tags: Array.isArray(op.tags) ? op.tags : [],
        operationId: op.operationId,
        parameters: resolvedParams,
        requestBodySchema,
        requestBodyRequired: Boolean(op.requestBody?.required),
        requestContentType,
        responses: op.responses || {},
      })
    }
  }
  return out.sort((a, b) => a.path.localeCompare(b.path) || a.method.localeCompare(b.method))
}

function buildParameterSchema(params: ApiOperationParam[]): Record<string, any> {
  const properties: Record<string, any> = {}
  const required: string[] = []
  for (const p of params) {
    properties[p.name] = p.schema || { type: 'string' }
    if (p.required) required.push(p.name)
  }
  return { type: 'object', properties, required }
}

function buildApiInputCompositeSchema(op: ApiOperation | null): Record<string, any> | null {
  if (!op) return null
  const pathParams = op.parameters.filter(p => p.in === 'path')
  const queryParams = op.parameters.filter(p => p.in === 'query')
  const properties: Record<string, any> = {}
  const required: string[] = []

  if (pathParams.length) {
    properties.path_params = buildParameterSchema(pathParams)
    required.push('path_params')
  }
  if (queryParams.length) {
    properties.query_params = buildParameterSchema(queryParams)
  }
  if (op.requestBodySchema && op.requestContentType === 'application/json') {
    properties.body = op.requestBodySchema
    if (op.requestBodyRequired) required.push('body')
  }

  return { type: 'object', properties, required }
}

function extractResponseContentType(result: any): string | null {
  const headers = result?.headers
  if (!headers || typeof headers !== 'object') return null
  for (const [k, v] of Object.entries(headers)) {
    if (String(k).toLowerCase() === 'content-type') return String(v)
  }
  return null
}

// The debug arena (Task Process Tracker / Unit Test Bench / API Playground).
// Auth, config gating, and the tab bar live in the parent DashboardPage; this
// component is only mounted for an authenticated admin and is told which debug
// sub-tab to show via the `tab` prop.
export function DebugArena({
  tab,
  llmExplainEnabled = false,
}: {
  tab: 'task' | 'unit' | 'api'
  llmExplainEnabled?: boolean
}): JSX.Element {
  const activeTab = tab
  const [toast, setToast] = useState<{ message: string; kind: 'info' | 'success' | 'warning' | 'error' } | null>(null)

  const [runs, setRuns] = useState<DebugRunSummary[]>([])
  const [selectedRunId, setSelectedRunId] = useState<string>('')
  const [selectedRun, setSelectedRun] = useState<DebugRunDetail | null>(null)
  const [runLoading, setRunLoading] = useState(false)
  const [runError, setRunError] = useState<string | null>(null)
  const [behaviorActionLoading, setBehaviorActionLoading] = useState<'create' | 'track' | null>(null)
  const [behaviorQuery, setBehaviorQuery] = useState('Find spicy Sichuan food for friends in Chinatown, budget 20 to 60 SGD')
  const [behaviorUseOnline, setBehaviorUseOnline] = useState(false)
  const [behaviorAutoConfirm, setBehaviorAutoConfirm] = useState(true)
  const [trackTaskId, setTrackTaskId] = useState('')
  const [explainLoading, setExplainLoading] = useState(false)

  const [units, setUnits] = useState<DebugUnitSpec[]>([])
  const [selectedUnitName, setSelectedUnitName] = useState('')
  const selectedUnit = useMemo(
    () => units.find(u => u.name === selectedUnitName) || null,
    [units, selectedUnitName]
  )
  const [unitInputMode, setUnitInputMode] = useState<'manual' | 'sample' | 'schema' | 'llm'>('manual')
  const [unitInputText, setUnitInputText] = useState('{}')
  const [unitRunResult, setUnitRunResult] = useState<any>(null)
  const [unitError, setUnitError] = useState<string | null>(null)
  const [unitRunning, setUnitRunning] = useState(false)
  const unitInputTouchedRef = useRef(false)

  const [openApiSpec, setOpenApiSpec] = useState<OpenApiSpec | null>(null)
  const [openApiLoading, setOpenApiLoading] = useState(false)
  const [openApiError, setOpenApiError] = useState<string | null>(null)
  const apiOperations = useMemo(() => buildApiOperations(openApiSpec), [openApiSpec])
  const [selectedApiOpId, setSelectedApiOpId] = useState('')
  const selectedApiOp = useMemo(
    () => apiOperations.find(op => op.id === selectedApiOpId) || apiOperations[0] || null,
    [apiOperations, selectedApiOpId]
  )
  const [apiInputMode, setApiInputMode] = useState<'manual' | 'schema' | 'llm'>('manual')
  const [apiPathParamsText, setApiPathParamsText] = useState('{}')
  const [apiQueryParamsText, setApiQueryParamsText] = useState('{}')
  const [apiBodyText, setApiBodyText] = useState('{}')
  const [apiPlaygroundError, setApiPlaygroundError] = useState<string | null>(null)
  const [apiRunning, setApiRunning] = useState(false)
  const [apiGenerateLoading, setApiGenerateLoading] = useState(false)
  const [apiResult, setApiResult] = useState<any>(null)
  const [apiInputWarnings, setApiInputWarnings] = useState<string[]>([])

  const unitHarness = unitRunResult && typeof unitRunResult === 'object' ? unitRunResult : null
  const unitExecution = unitHarness?.result && typeof unitHarness.result === 'object' ? unitHarness.result : null
  const unitFunctionOutput = unitExecution?.ok ? unitExecution.output : null
  const unitFunctionError = unitExecution?.ok ? null : unitExecution?.error
  const unitValidationWarnings = Array.isArray(unitHarness?.validation_errors) ? unitHarness.validation_errors : []
  const apiCompositeSchema = useMemo(() => buildApiInputCompositeSchema(selectedApiOp), [selectedApiOp])

  useEffect(() => {
    if (!toast) return
    const timer = window.setTimeout(() => setToast(null), 4000)
    return () => window.clearTimeout(timer)
  }, [toast])

  const refreshRuns = async (keepSelected = true) => {
    const data = await listDebugRuns()
    setRuns(data.runs || [])
    if (!keepSelected && data.runs?.length) {
      setSelectedRunId(data.runs[0].id)
    }
  }

  const refreshUnits = async () => {
    const data = await listDebugUnits()
    setUnits(data.units || [])
    if (!selectedUnitName && data.units?.length) {
      setSelectedUnitName(data.units[0].name)
    }
  }

  useEffect(() => {
    refreshRuns(false).catch((e: any) => setRunError(e?.message || 'Failed to load runs'))
    refreshUnits().catch((e: any) => setUnitError(e?.message || 'Failed to load units'))
  }, [])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setOpenApiLoading(true)
      setOpenApiError(null)
      try {
        const spec = await fetchOpenApiSpec()
        if (cancelled) return
        setOpenApiSpec(spec)
      } catch (e: any) {
        if (cancelled) return
        setOpenApiError(e?.message || 'Failed to load OpenAPI spec')
      } finally {
        if (!cancelled) setOpenApiLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    if (!selectedRunId) return
    let stop = false
    const load = async () => {
      setRunLoading(true)
      try {
        const run = await getBehaviorDebugRun(selectedRunId)
        if (stop) return
        setSelectedRun(run)
        setRunError(null)
      } catch (e: any) {
        if (stop) return
        setRunError(e?.message || 'Failed to load run')
      } finally {
        if (!stop) setRunLoading(false)
      }
    }
    load()
    const interval = setInterval(() => {
      if (selectedRun?.job_running || ['queued', 'running'].includes(selectedRun?.status || '')) {
        load().catch(() => {})
      }
    }, 1500)
    return () => {
      stop = true
      clearInterval(interval)
    }
  }, [selectedRunId, selectedRun?.job_running, selectedRun?.status])

  useEffect(() => {
    if (!selectedUnit) return
    if (unitInputTouchedRef.current) return
    setUnitInputText(pretty(selectedUnit.sample_input || {}))
  }, [selectedUnit])

  useEffect(() => {
    if (!apiOperations.length) return
    if (!selectedApiOpId || !apiOperations.some(op => op.id === selectedApiOpId)) {
      setSelectedApiOpId(apiOperations[0].id)
    }
  }, [apiOperations, selectedApiOpId])

  useEffect(() => {
    if (!selectedApiOp) return
    const pathDefaults: Record<string, any> = {}
    for (const p of selectedApiOp.parameters.filter(p => p.in === 'path')) {
      pathDefaults[p.name] = p.schema?.example ?? (p.schema?.type === 'integer' ? 1 : 'test')
    }
    const queryDefaults: Record<string, any> = {}
    for (const p of selectedApiOp.parameters.filter(p => p.in === 'query')) {
      if (p.required) {
        queryDefaults[p.name] = p.schema?.example ?? (p.schema?.type === 'integer' ? 1 : 'test')
      }
    }
    setApiPathParamsText(pretty(pathDefaults))
    setApiQueryParamsText(pretty(queryDefaults))
    if (selectedApiOp.requestContentType === 'application/json' && selectedApiOp.requestBodySchema) {
      setApiBodyText(pretty({}))
    } else {
      setApiBodyText('')
    }
    setApiResult(null)
    setApiInputWarnings([])
    setApiPlaygroundError(null)
  }, [selectedApiOp?.id])

  const startBehavior = async () => {
    setRunError(null)
    setBehaviorActionLoading('create')
    try {
      const result = await startBehaviorDebugRun({
        query: behaviorQuery,
        use_online_agent: behaviorUseOnline,
        auto_confirm: behaviorAutoConfirm,
      })
      await refreshRuns()
      setSelectedRunId(result.run_id)
    } catch (e: any) {
      setRunError(e?.message || 'Failed to start behavior run')
    } finally {
      setBehaviorActionLoading(null)
    }
  }

  const startTrack = async () => {
    if (!trackTaskId.trim()) return
    setRunError(null)
    setBehaviorActionLoading('track')
    try {
      const result = await trackBehaviorDebugTask({ task_id: trackTaskId.trim() })
      await refreshRuns()
      setSelectedRunId(result.run_id)
    } catch (e: any) {
      const message = e?.message || 'Failed to track task'
      setRunError(message)
      if (message.toLowerCase().includes('task id not found') || message.toLowerCase().includes('task not found')) {
        setToast({
          kind: 'warning',
          message: `Task not found: "${trackTaskId.trim()}". No tracking run was created.`,
        })
      }
    } finally {
      setBehaviorActionLoading(null)
    }
  }

  const runExplain = async () => {
    if (!selectedRunId) return
    setExplainLoading(true)
    try {
      await explainBehaviorDebugRun(selectedRunId)
      const refreshed = await getBehaviorDebugRun(selectedRunId)
      setSelectedRun(refreshed)
    } catch (e: any) {
      setRunError(e?.message || 'LLM explanation failed')
    } finally {
      setExplainLoading(false)
    }
  }

  const onGenerateUnitInput = async (mode: 'sample' | 'schema' | 'llm') => {
    // refers to backend DebugRoute's private function _generate_unit_input()
    if (!selectedUnit) return
    setUnitError(null)
    try {
      const result = await generateDebugUnitInput(selectedUnit.name, mode)
      unitInputTouchedRef.current = true
      setUnitInputText(pretty(result.input_data || {}))
      if (result.validation_errors?.length) {
        setUnitError(`Validation warnings: ${result.validation_errors.join('; ')}`)
      }
    } catch (e: any) {
      setUnitError(e?.message || 'Failed to generate input')
    }
  }

  const onRunUnit = async () => {
    if (!selectedUnit) return
    setUnitError(null)
    setUnitRunResult(null)
    setUnitRunning(true)
    try {
      const inputData = unitInputMode === 'manual'
        ? JSON.parse(unitInputText || '{}')
        : undefined
      const result = await runDebugUnit({
        unit_name: selectedUnit.name,
        input_mode: unitInputMode,
        input_data: inputData,
        use_llm_generation: unitInputMode === 'llm',
      })
      setUnitRunResult(result)
      if (result?.input_data) {
        unitInputTouchedRef.current = true
        setUnitInputText(pretty(result.input_data))
      }
    } catch (e: any) {
      setUnitError(e?.message || 'Failed to run unit')
    } finally {
      setUnitRunning(false)
    }
  }

  const onGenerateApiInput = async (mode: 'schema' | 'llm') => {
    if (!selectedApiOp || !apiCompositeSchema) return
    setApiPlaygroundError(null)
    setApiGenerateLoading(true)
    setApiInputMode(mode)
    try {
      const generated = await generateDebugApiPlaygroundInput({
        mode,
        schema: apiCompositeSchema,
        method: selectedApiOp.method,
        path: selectedApiOp.path,
        summary: selectedApiOp.summary,
      })
      const inputData = generated.input_data || {}
      setApiPathParamsText(pretty(inputData.path_params || {}))
      setApiQueryParamsText(pretty(inputData.query_params || {}))
      if (selectedApiOp.requestContentType === 'application/json' && selectedApiOp.requestBodySchema) {
        setApiBodyText(pretty(inputData.body ?? {}))
      }
      setApiInputWarnings(Array.isArray(generated.validation_errors) ? generated.validation_errors : [])
      setApiInputMode(mode)
    } catch (e: any) {
      setApiPlaygroundError(e?.message || 'Failed to generate API input')
    } finally {
      setApiGenerateLoading(false)
    }
  }

  const onRunApi = async () => {
    if (!selectedApiOp) return
    setApiPlaygroundError(null)
    setApiResult(null)
    setApiRunning(true)
    try {
      const pathParams = apiPathParamsText.trim() ? JSON.parse(apiPathParamsText) : {}
      const queryParams = apiQueryParamsText.trim() ? JSON.parse(apiQueryParamsText) : {}
      const hasJsonBody = selectedApiOp.requestContentType === 'application/json' && selectedApiOp.requestBodySchema
      const bodyObj = hasJsonBody && apiBodyText.trim() ? JSON.parse(apiBodyText) : undefined

      if (pathParams && typeof pathParams !== 'object') throw new Error('Path Params must be a JSON object')
      if (queryParams && typeof queryParams !== 'object') throw new Error('Query Params must be a JSON object')
      let resolvedPath = selectedApiOp.path
      for (const p of selectedApiOp.parameters.filter(p => p.in === 'path')) {
        if (!(p.name in pathParams)) {
          throw new Error(`Missing required path param: ${p.name}`)
        }
        resolvedPath = resolvedPath.replace(new RegExp(`\\{${p.name}\\}`, 'g'), encodeURIComponent(String((pathParams as any)[p.name])))
      }

      const query = new URLSearchParams()
      for (const [k, v] of Object.entries(queryParams || {})) {
        if (v === undefined || v === null || v === '') continue
        if (Array.isArray(v)) {
          v.forEach(item => query.append(k, String(item)))
        } else {
          query.set(k, String(v))
        }
      }

      const url = `${DEBUG_BASE_URL}${resolvedPath}${query.toString() ? `?${query.toString()}` : ''}`
      const headers: Record<string, string> = {}
      let body: string | undefined
      if (hasJsonBody) {
        headers['Content-Type'] = 'application/json'
        body = JSON.stringify(bodyObj ?? {})
      }

      const controller = new AbortController()
      const timeoutId = window.setTimeout(() => controller.abort(), 120_000)
      const started = performance.now()
      const res = await fetch(url, {
        method: selectedApiOp.method,
        credentials: 'include',
        headers,
        body,
        signal: controller.signal,
      }).finally(() => window.clearTimeout(timeoutId))
      const durationMs = Math.round(performance.now() - started)
      const text = await res.text().catch(() => '')
      let parsed: any = null
      let isJson = false
      try {
        parsed = text ? JSON.parse(text) : null
        isJson = true
      } catch {
        parsed = text
      }

      const headerObj: Record<string, string> = {}
      res.headers.forEach((value, key) => { headerObj[key] = value })

      setApiResult({
        ok: res.ok,
        request: {
          method: selectedApiOp.method,
          path_template: selectedApiOp.path,
          resolved_path: resolvedPath,
          query_params: queryParams,
          path_params: pathParams,
          body: hasJsonBody ? (bodyObj ?? {}) : undefined,
          input_mode: apiInputMode,
        },
        response: {
          status: res.status,
          status_text: res.statusText,
          headers: headerObj,
          content_type: res.headers.get('content-type'),
          is_json: isJson,
          body: parsed,
          raw_text: text,
        },
        duration_ms: durationMs,
      })
    } catch (e: any) {
      if (e?.name === 'AbortError') {
        setApiPlaygroundError('API request timed out after 120s')
      } else {
        setApiPlaygroundError(e?.message || 'Failed to run API request')
      }
    } finally {
      setApiRunning(false)
    }
  }

  const isBehaviorRunning = behaviorActionLoading !== null || Boolean(selectedRun?.job_running)

  return (
    <div className="debug-arena">
      {toast && (
        <div className={`debug-toast ${toast.kind}`} role="status" aria-live="polite">
          <div className="debug-toast-content">
            <strong>{toast.kind === 'warning' ? 'Notice' : 'Debug'}</strong>
            <span>{toast.message}</span>
          </div>
          <button className="debug-toast-close" onClick={() => setToast(null)} aria-label="Dismiss notification">
            ×
          </button>
        </div>
      )}

      {activeTab === 'task' ? (
            <div className="debug-grid debug-tab-panel" role="tabpanel" aria-label="Task Process Tracker">
              <section className="debug-panel">
                <h2>System Behaviour Test</h2>
                <label>Query</label>
                <textarea
                  rows={4}
                  value={behaviorQuery}
                  onChange={(e) => setBehaviorQuery(e.target.value)}
                />
                <div className="debug-inline-options">
                  <label><input type="checkbox" checked={behaviorUseOnline} onChange={(e) => setBehaviorUseOnline(e.target.checked)} /> Use online agent</label>
                  <label><input type="checkbox" checked={behaviorAutoConfirm} onChange={(e) => setBehaviorAutoConfirm(e.target.checked)} /> Auto-confirm if needed</label>
                </div>
                <div className="debug-row">
                  <button onClick={startBehavior} disabled={behaviorActionLoading !== null}>
                    {behaviorActionLoading === 'create' ? (
                      <span className="debug-btn-content"><span className="debug-spinner" /> Creating Run...</span>
                    ) : (
                      'Create Trace Run'
                    )}
                  </button>
                  <button onClick={() => refreshRuns()} className="debug-secondary">Refresh Runs</button>
                </div>
                <hr />
                <label>Track Existing Task ID</label>
                <div className="debug-row">
                  <input value={trackTaskId} onChange={(e) => setTrackTaskId(e.target.value)} placeholder="task_id" />
                  <button onClick={startTrack} disabled={behaviorActionLoading !== null}>
                    {behaviorActionLoading === 'track' ? (
                      <span className="debug-btn-content"><span className="debug-spinner" /> Tracking...</span>
                    ) : (
                      'Track Task'
                    )}
                  </button>
                </div>
                {isBehaviorRunning && (
                  <div className="debug-loading-banner">
                    <span className="debug-spinner" />
                    <span>Test run is in progress. Trace updates will stream into the viewer.</span>
                    <span className="debug-loading-dots"><i></i><i></i><i></i></span>
                  </div>
                )}
                {runError && <div className="debug-error">{runError}</div>}

                <div className="debug-runs-list">
                  {(runs || []).map(run => (
                    <button
                      key={run.id}
                      className={`debug-run-item ${selectedRunId === run.id ? 'active' : ''}`}
                      onClick={() => setSelectedRunId(run.id)}
                    >
                      <div className="debug-run-main">
                        <strong>{run.kind}</strong>
                        <span className={`debug-status ${run.status}`}>{run.status}</span>
                      </div>
                      <div className="debug-run-meta">{run.id.slice(0, 8)} • {run.event_count} events</div>
                    </button>
                  ))}
                  {!runs.length && <div className="debug-muted">No debug runs yet.</div>}
                </div>
              </section>

              <section className={`debug-panel debug-panel-wide ${selectedRun?.job_running ? 'debug-panel-live' : ''}`}>
                <div className="debug-panel-title-row">
                  <h2>Trace Viewer</h2>
                  <div className="debug-row">
                    {llmExplainEnabled && selectedRunId && (
                      <button onClick={runExplain} disabled={explainLoading}>
                        {explainLoading ? (
                          <span className="debug-btn-content"><span className="debug-spinner" /> Explaining...</span>
                        ) : (
                          'NL Explain + Suggestions'
                        )}
                      </button>
                    )}
                  </div>
                </div>
                {runLoading && (
                  <div className="debug-loading-inline">
                    <span className="debug-spinner" />
                    <span className="debug-muted">Loading trace...</span>
                  </div>
                )}
                {selectedRun ? (
                  <>
                    <div className="debug-trace-summary">
                      <span><strong>Run:</strong> {selectedRun.id}</span>
                      <span><strong>Status:</strong> <span className={`debug-status ${selectedRun.status}`}>{selectedRun.status}</span></span>
                      <span><strong>Kind:</strong> {selectedRun.kind}</span>
                      <span><strong>Events:</strong> {selectedRun.events?.length || 0}</span>
                    </div>
                    {selectedRun.explanation?.content && (
                      <div className="debug-explanation">
                        <h3>NL Explanation</h3>
                        <pre>{selectedRun.explanation.content}</pre>
                      </div>
                    )}
                    <div className="debug-events">
                      {(selectedRun.events || []).map((ev, idx) => (
                        <details key={`${ev.timestamp}-${idx}`} open={idx >= (selectedRun.events.length - 4)}>
                          <summary>
                            <span className={`debug-status ${ev.status}`}>{ev.status}</span>
                            <strong>{ev.label}</strong>
                            <span className="debug-muted">[{ev.type}] {new Date(ev.timestamp).toLocaleTimeString()}</span>
                          </summary>
                          <pre>{pretty(ev.data)}</pre>
                        </details>
                      ))}
                      {!selectedRun.events?.length && <div className="debug-muted">No events yet.</div>}
                    </div>
                    <details>
                      <summary>Artifacts</summary>
                      <pre>{pretty(selectedRun.artifacts || {})}</pre>
                    </details>
                    <details>
                      <summary>Raw Trace JSON</summary>
                      <pre>{pretty(selectedRun)}</pre>
                    </details>
                  </>
                ) : (
                  <div className="debug-muted">Select a run to inspect details.</div>
                )}
              </section>
            </div>
          ) : activeTab === 'unit' ? (
            <section className="debug-panel debug-panel-wide debug-panel-full-span debug-tab-panel" role="tabpanel" aria-label="Unit Test Bench">
              <div className="debug-panel-title-row">
                <h2>Unit Test Bench</h2>
                <div className="debug-row">
                  <button className="debug-secondary" onClick={() => refreshUnits()}>Refresh Units</button>
                </div>
              </div>
              <div className="debug-unit-layout">
                  <div className="debug-unit-left">
                    <label>Registered Units</label>
                    <select
                      value={selectedUnitName}
                      onChange={(e) => {
                        unitInputTouchedRef.current = false
                        setSelectedUnitName(e.target.value)
                        setUnitRunResult(null)
                      }}
                    >
                      {units.map(u => (
                        <option key={u.name} value={u.name}>{u.name}</option>
                      ))}
                    </select>
                    {selectedUnit && (
                      <div className="debug-unit-meta">
                        <div><strong>Function:</strong> {selectedUnit.function_name}</div>
                        <div>{selectedUnit.description}</div>
                      </div>
                    )}
                    {selectedUnit && (
                      <>
                        <details open>
                          <summary>Input Schema</summary>
                          <pre>{pretty(selectedUnit.input_schema)}</pre>
                        </details>
                        <details>
                          <summary>Expected I/O</summary>
                          <pre>{pretty(selectedUnit.expected_io)}</pre>
                        </details>
                      </>
                    )}
                    <label>Input Mode</label>
                    <select value={unitInputMode} onChange={(e) => setUnitInputMode(e.target.value as any)}>
                      <option value="manual">Manual JSON</option>
                      <option value="sample">Use Sample Input</option>
                      <option value="schema">Generate From Schema</option>
                      <option value="llm">LLM-Generated Input</option>
                    </select>
                    <div className="debug-row">
                      <button className="debug-secondary" onClick={() => onGenerateUnitInput('sample')} disabled={!selectedUnit}>Load Sample</button>
                      <button className="debug-secondary" onClick={() => onGenerateUnitInput('schema')} disabled={!selectedUnit}>Schema Generate</button>
                      <button className="debug-secondary" onClick={() => onGenerateUnitInput('llm')} disabled={!selectedUnit}>LLM Generate</button>
                    </div>
                    <label>Input JSON</label>
                    <textarea
                      rows={14}
                      value={unitInputText}
                      onChange={(e) => {
                        unitInputTouchedRef.current = true
                        setUnitInputText(e.target.value)
                      }}
                    />
                    <div className="debug-row">
                      <button onClick={onRunUnit} disabled={!selectedUnit || unitRunning}>
                        {unitRunning ? (
                          <span className="debug-btn-content"><span className="debug-spinner" /> Running...</span>
                        ) : (
                          'Run Unit'
                        )}
                      </button>
                    </div>
                    {unitError && <div className="debug-error">{unitError}</div>}
                  </div>

                  <div className="debug-unit-right">
                    <div className={`debug-unit-result ${unitRunning ? 'is-running' : ''}`}>
                      <h3>Output</h3>
                      <div className="debug-output-shell">
                        {unitRunning && (
                          <div className="debug-output-overlay" aria-live="polite">
                            <span className="debug-spinner" />
                            <span>Executing function harness...</span>
                          </div>
                        )}
                        {!unitHarness ? (
                          <pre>{'No unit run yet.'}</pre>
                        ) : (
                          <div className="debug-rendered-output">
                            <div className="debug-result-grid">
                              <div className="debug-result-card">
                                <div className="debug-result-card-title">Harness Status</div>
                                <div className="debug-result-card-value">
                                  <span className={`debug-status ${unitHarness.ok ? 'completed' : 'error'}`}>
                                    {unitHarness.ok ? 'ok' : 'error'}
                                  </span>
                                </div>
                                <div className="debug-result-card-meta">
                                  Wrapper route response from `/internal/debug/unit-tests/run`
                                </div>
                              </div>

                              <div className="debug-result-card">
                                <div className="debug-result-card-title">Execution Time</div>
                                <div className="debug-result-card-value">{formatMs(unitExecution?.duration_ms)}</div>
                                <div className="debug-result-card-meta">Actual unit execution duration</div>
                              </div>

                              <div className="debug-result-card">
                                <div className="debug-result-card-title">Input Source</div>
                                <div className="debug-result-card-value">{unitHarness.input_source || '-'}</div>
                                <div className="debug-result-card-meta">manual / sample / schema / llm</div>
                              </div>

                              <div className="debug-result-card">
                                <div className="debug-result-card-title">Validation Warnings</div>
                                <div className="debug-result-card-value">{unitValidationWarnings.length}</div>
                                <div className="debug-result-card-meta">
                                  {unitValidationWarnings.length ? 'Input schema warnings found' : 'Input matches schema checks'}
                                </div>
                              </div>
                            </div>

                            {unitHarness.unit && (
                              <div className="debug-result-section">
                                <div className="debug-result-section-title">Tested Unit</div>
                                <div className="debug-result-keyvals">
                                  <div><span>Name</span><strong>{unitHarness.unit.name || '-'}</strong></div>
                                  <div><span>Function</span><strong>{unitHarness.unit.function_name || '-'}</strong></div>
                                </div>
                              </div>
                            )}

                            {unitHarness.input_data !== undefined && (
                              <div className="debug-result-section">
                                <div className="debug-result-section-title">Resolved Input (structured)</div>
                                <div className="debug-result-structured">
                                  {renderStructuredValue(unitHarness.input_data)}
                                </div>
                              </div>
                            )}

                            {unitValidationWarnings.length > 0 && (
                              <div className="debug-result-section warning">
                                <div className="debug-result-section-title">Validation Warnings</div>
                                <ul className="debug-result-list">
                                  {unitValidationWarnings.map((w: string, i: number) => (
                                    <li key={`${w}-${i}`}>{w}</li>
                                  ))}
                                </ul>
                              </div>
                            )}

                            {unitFunctionError && (
                              <div className="debug-result-section error">
                                <div className="debug-result-section-title">Function Error</div>
                                <div className="debug-result-error-text">{String(unitFunctionError)}</div>
                                {unitExecution?.traceback && (
                                  <details>
                                    <summary>Traceback</summary>
                                    <pre>{String(unitExecution.traceback)}</pre>
                                  </details>
                                )}
                              </div>
                            )}

                            <div className="debug-result-section">
                              <div className="debug-result-section-title">Function Output (raw JSON)</div>
                              <pre>{pretty(unitFunctionOutput ?? null)}</pre>
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
            </section>
          ) : (
            <section className="debug-panel debug-panel-wide debug-panel-full-span debug-tab-panel" role="tabpanel" aria-label="API Playground">
              <div className="debug-panel-title-row">
                <h2>API Playground</h2>
                <div className="debug-row">
                  <button className="debug-secondary" onClick={() => {
                    setOpenApiLoading(true)
                    setOpenApiError(null)
                    fetchOpenApiSpec()
                      .then(spec => setOpenApiSpec(spec))
                      .catch((e: any) => setOpenApiError(e?.message || 'Failed to load OpenAPI spec'))
                      .finally(() => setOpenApiLoading(false))
                  }}>
                    Refresh OpenAPI
                  </button>
                </div>
              </div>

              <div className="debug-api-layout">
                <div className="debug-api-left">
                  <div className="debug-api-catalog-header">
                    <div>
                      <label>Registered APIs (from `/openapi.json`)</label>
                      <div className="debug-muted">
                        {openApiLoading ? 'Loading OpenAPI spec...' : `${apiOperations.length} endpoints`}
                      </div>
                    </div>
                  </div>
                  {openApiError && <div className="debug-error">{openApiError}</div>}
                  <div className="debug-api-list">
                    {apiOperations.map(op => (
                      <button
                        key={op.id}
                        className={`debug-api-item ${selectedApiOp?.id === op.id ? 'active' : ''}`}
                        onClick={() => setSelectedApiOpId(op.id)}
                      >
                        <div className="debug-api-item-top">
                          <span className={`debug-method-badge ${op.method.toLowerCase()}`}>{op.method}</span>
                          <span className="debug-api-path">{op.path}</span>
                        </div>
                        <div className="debug-api-summary">{op.summary}</div>
                        <div className="debug-api-item-meta">
                          <span>{op.parameters.length} params</span>
                          <span>{op.requestBodySchema ? (op.requestContentType || 'body') : 'no body'}</span>
                        </div>
                      </button>
                    ))}
                    {!openApiLoading && !apiOperations.length && !openApiError && (
                      <div className="debug-muted">No endpoints found in OpenAPI spec.</div>
                    )}
                  </div>
                </div>

                <div className="debug-api-right">
                  {!selectedApiOp ? (
                    <div className="debug-muted">Select an API endpoint to inspect and test.</div>
                  ) : (
                    <div className="debug-rendered-output">
                      <div className="debug-result-grid">
                        <div className="debug-result-card">
                          <div className="debug-result-card-title">Method</div>
                          <div className="debug-result-card-value">
                            <span className={`debug-method-badge ${selectedApiOp.method.toLowerCase()}`}>{selectedApiOp.method}</span>
                          </div>
                          <div className="debug-result-card-meta">{selectedApiOp.path}</div>
                        </div>
                        <div className="debug-result-card">
                          <div className="debug-result-card-title">Operation</div>
                          <div className="debug-result-card-value">{selectedApiOp.operationId || '-'}</div>
                          <div className="debug-result-card-meta">{selectedApiOp.tags.join(', ') || 'No tags'}</div>
                        </div>
                        <div className="debug-result-card">
                          <div className="debug-result-card-title">Path Params</div>
                          <div className="debug-result-card-value">{selectedApiOp.parameters.filter(p => p.in === 'path').length}</div>
                          <div className="debug-result-card-meta">Required URL placeholders</div>
                        </div>
                        <div className="debug-result-card">
                          <div className="debug-result-card-title">Body Schema</div>
                          <div className="debug-result-card-value">{selectedApiOp.requestBodySchema ? 'Yes' : 'No'}</div>
                          <div className="debug-result-card-meta">{selectedApiOp.requestContentType || 'No request body'}</div>
                        </div>
                      </div>

                      <div className="debug-result-section">
                        <div className="debug-result-section-title">Endpoint Info</div>
                        <div className="debug-result-keyvals">
                          <div><span>Summary</span><strong>{selectedApiOp.summary}</strong></div>
                          <div><span>Description</span><strong>{selectedApiOp.description || '-'}</strong></div>
                          <div><span>Tags</span><strong>{selectedApiOp.tags.join(', ') || '-'}</strong></div>
                          <div><span>Responses</span><strong>{Object.keys(selectedApiOp.responses || {}).join(', ') || '-'}</strong></div>
                        </div>
                      </div>

                      {selectedApiOp.parameters.length > 0 && (
                        <div className="debug-result-section">
                          <div className="debug-result-section-title">Parameters (structured)</div>
                          <div className="debug-result-structured">
                            {renderStructuredValue(
                              selectedApiOp.parameters.map(p => ({
                                name: p.name,
                                in: p.in,
                                required: p.required,
                                description: p.description,
                                schema: p.schema,
                              }))
                            )}
                          </div>
                        </div>
                      )}

                      {selectedApiOp.requestBodySchema && (
                        <details className="debug-result-section" open>
                          <summary>Request Body Schema (`{selectedApiOp.requestContentType || 'unknown'}`)</summary>
                          <div className="debug-result-structured">
                            {renderStructuredValue(selectedApiOp.requestBodySchema)}
                          </div>
                        </details>
                      )}

                      <div className="debug-result-section">
                        <div className="debug-result-section-title">Test Input</div>
                        <div className="debug-api-actions">
                          <button className="debug-secondary" onClick={() => onGenerateApiInput('schema')} disabled={!apiCompositeSchema || apiGenerateLoading}>
                            {apiGenerateLoading && apiInputMode === 'schema'
                              ? <span className="debug-btn-content"><span className="debug-spinner" /> Generating...</span>
                              : 'Schema Generate'}
                          </button>
                          <button className="debug-secondary" onClick={() => onGenerateApiInput('llm')} disabled={!apiCompositeSchema || apiGenerateLoading}>
                            {apiGenerateLoading && apiInputMode === 'llm'
                              ? <span className="debug-btn-content"><span className="debug-spinner" /> LLM Generating...</span>
                              : 'LLM Generate'}
                          </button>
                          <button onClick={onRunApi} disabled={apiRunning}>
                            {apiRunning
                              ? <span className="debug-btn-content"><span className="debug-spinner" /> Running API...</span>
                              : 'Run API'}
                          </button>
                        </div>

                        {apiInputWarnings.length > 0 && (
                          <div className="debug-result-section warning">
                            <div className="debug-result-section-title">Generated Input Warnings</div>
                            <ul className="debug-result-list">
                              {apiInputWarnings.map((w, i) => <li key={`${w}-${i}`}>{w}</li>)}
                            </ul>
                          </div>
                        )}
                        {apiPlaygroundError && <div className="debug-error">{apiPlaygroundError}</div>}

                        <div className="debug-api-editor-grid">
                          <div>
                            <label>Path Params JSON</label>
                            <textarea rows={6} value={apiPathParamsText} onChange={(e) => { setApiInputMode('manual'); setApiPathParamsText(e.target.value) }} />
                          </div>
                          <div>
                            <label>Query Params JSON</label>
                            <textarea rows={6} value={apiQueryParamsText} onChange={(e) => { setApiInputMode('manual'); setApiQueryParamsText(e.target.value) }} />
                          </div>
                        </div>
                        {selectedApiOp.requestContentType === 'application/json' && selectedApiOp.requestBodySchema ? (
                          <>
                            <label>Request Body JSON</label>
                            <textarea rows={12} value={apiBodyText} onChange={(e) => { setApiInputMode('manual'); setApiBodyText(e.target.value) }} />
                          </>
                        ) : selectedApiOp.requestBodySchema ? (
                          <div className="debug-error">
                            Request body content type `{selectedApiOp.requestContentType}` is not yet supported by the API Playground runner (JSON only).
                          </div>
                        ) : null}
                      </div>

                      <div className={`debug-unit-result ${apiRunning ? 'is-running' : ''}`}>
                        <h3>API Output</h3>
                        <div className="debug-output-shell">
                          {apiRunning && (
                            <div className="debug-output-overlay" aria-live="polite">
                              <span className="debug-spinner" />
                              <span>Executing API request...</span>
                            </div>
                          )}
                          {!apiResult ? (
                            <pre>{'No API run yet.'}</pre>
                          ) : (
                            <div className="debug-rendered-output">
                              <div className="debug-result-grid">
                                <div className="debug-result-card">
                                  <div className="debug-result-card-title">HTTP Status</div>
                                  <div className="debug-result-card-value">
                                    <span className={`debug-status ${apiResult.ok ? 'completed' : 'error'}`}>
                                      {apiResult.response?.status} {apiResult.response?.status_text}
                                    </span>
                                  </div>
                                  <div className="debug-result-card-meta">{apiResult.ok ? 'Request succeeded' : 'Request failed'}</div>
                                </div>
                                <div className="debug-result-card">
                                  <div className="debug-result-card-title">Latency</div>
                                  <div className="debug-result-card-value">{formatMs(apiResult.duration_ms)}</div>
                                  <div className="debug-result-card-meta">Measured in browser</div>
                                </div>
                                <div className="debug-result-card">
                                  <div className="debug-result-card-title">Content Type</div>
                                  <div className="debug-result-card-value">{extractResponseContentType(apiResult.response) || '-'}</div>
                                  <div className="debug-result-card-meta">Response header</div>
                                </div>
                                <div className="debug-result-card">
                                  <div className="debug-result-card-title">Resolved Path</div>
                                  <div className="debug-result-card-value">{apiResult.request?.resolved_path || selectedApiOp.path}</div>
                                  <div className="debug-result-card-meta">{apiResult.request?.method}</div>
                                </div>
                              </div>

                              <div className="debug-result-section">
                                <div className="debug-result-section-title">Request Summary (structured)</div>
                                <div className="debug-result-structured">
                                  {renderStructuredValue(apiResult.request || {})}
                                </div>
                              </div>

                              <div className="debug-result-section">
                                <div className="debug-result-section-title">Response Summary (structured)</div>
                                <div className="debug-result-structured">
                                  {renderStructuredValue({
                                    status: apiResult.response?.status,
                                    status_text: apiResult.response?.status_text,
                                    content_type: apiResult.response?.content_type,
                                    is_json: apiResult.response?.is_json,
                                    body: apiResult.response?.body,
                                  })}
                                </div>
                              </div>

                              <details className="debug-result-section">
                                <summary>Response Headers</summary>
                                <pre>{pretty(apiResult.response?.headers || {})}</pre>
                              </details>

                              <div className="debug-result-section">
                                <div className="debug-result-section-title">Raw API Response (pretty JSON/text)</div>
                                <pre>{apiResult.response?.is_json ? pretty(apiResult.response?.body) : String(apiResult.response?.raw_text || '')}</pre>
                              </div>
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </section>
          )}
    </div>
  )
}

export default DebugArena
