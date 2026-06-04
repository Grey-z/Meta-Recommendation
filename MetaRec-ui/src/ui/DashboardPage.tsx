import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import '../style/DebugPage.css'
import '../style/Dashboard.css'
import { getDebugConfig } from '../utils/debugApi'
import { getAdminSession, type AdminSessionInfo } from '../utils/adminApi'
import { login, logout } from '../utils/api'
import { DebugArena } from './DebugArena'
import { DashboardOverview } from './DashboardOverview'
import { UserManagement } from './UserManagement'

type TabKey = 'dashboard' | 'cms' | 'task' | 'unit' | 'api'
const DEBUG_TABS: TabKey[] = ['task', 'unit', 'api']

// Admin dashboard shell. Owns config + admin auth + the tab bar, and routes the
// active tab to the relevant feature component. The DEBUG_UI_ENABLED flag (read
// via getDebugConfig().enabled) now only controls whether the debug-arena tabs
// are shown — the Dashboard and User Management tabs are always available to an
// admin. Admin identity is verified via the debug-independent /api/admin/session.
export function DashboardPage(): JSX.Element {
  const [sessionReady, setSessionReady] = useState(false)
  const [authed, setAuthed] = useState(false)
  const [accessDenied, setAccessDenied] = useState(false)
  const [currentUser, setCurrentUser] = useState<AdminSessionInfo['user'] | null>(null)
  const [debugEnabled, setDebugEnabled] = useState(false)
  const [llmExplainEnabled, setLlmExplainEnabled] = useState(false)
  const [activeTab, setActiveTab] = useState<TabKey>('dashboard')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [authError, setAuthError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      // Debug-tab visibility is best-effort; failure just hides the debug tabs.
      const c = await getDebugConfig().catch(() => null)
      if (!cancelled && c) {
        setDebugEnabled(Boolean(c.enabled))
        setLlmExplainEnabled(Boolean(c.llm_explain_enabled))
      }
      try {
        const s = await getAdminSession()
        if (cancelled) return
        setCurrentUser(s.user)
        setAuthed(true)
        setAccessDenied(false)
      } catch (e: any) {
        if (cancelled) return
        setAuthed(false)
        // 403 = signed in but not an admin; otherwise (401) just needs login.
        setAccessDenied(String(e?.message || '').includes('403'))
      } finally {
        if (!cancelled) setSessionReady(true)
      }
    })()
    return () => { cancelled = true }
  }, [])

  // If debug becomes disabled while a debug tab is active, fall back to Dashboard.
  useEffect(() => {
    if (!debugEnabled && DEBUG_TABS.includes(activeTab)) {
      setActiveTab('dashboard')
    }
  }, [debugEnabled, activeTab])

  const onLogin = async () => {
    setAuthError(null)
    try {
      const auth = await login(email.trim(), password)
      if (auth.user.role !== 'admin') {
        setAuthed(false)
        setAccessDenied(true)
        setPassword('')
        return
      }
      const s = await getAdminSession()
      setCurrentUser(s.user)
      setAuthed(true)
      setAccessDenied(false)
      setPassword('')
    } catch (e: any) {
      if (String(e?.message || '').includes('403')) {
        setAccessDenied(true)
        setAuthed(false)
      } else {
        setAuthError(e?.message || 'Login failed')
      }
    }
  }

  const onLogout = async () => {
    try {
      await logout()
    } finally {
      setAuthed(false)
      setAccessDenied(false)
      setCurrentUser(null)
      setActiveTab('dashboard')
    }
  }

  const tabs: Array<{ key: TabKey; label: string }> = [
    { key: 'dashboard', label: 'Dashboard' },
    { key: 'cms', label: 'User Management' },
    ...(debugEnabled
      ? [
          { key: 'task' as TabKey, label: 'Task Process Tracker' },
          { key: 'unit' as TabKey, label: 'Unit Test Bench' },
          { key: 'api' as TabKey, label: 'API Playground' },
        ]
      : []),
  ]

  if (!sessionReady) {
    return <div className="debug-page"><div className="debug-panel">Loading dashboard...</div></div>
  }

  return (
    <div className="debug-page">
      <header className="debug-header">
        <div>
          <h1>MetaRec Admin Dashboard</h1>
          <p>Collective analytics, user management, and internal diagnostics.</p>
        </div>
        <div className="debug-header-actions">
          <Link to="/MetaRec" className="debug-link-btn">Back to MetaRec</Link>
          {authed && <button className="debug-link-btn" onClick={onLogout}>Logout</button>}
        </div>
      </header>

      {accessDenied ? (
        <section className="debug-panel">
          <h2>Access denied</h2>
          <p>You are signed in, but the admin dashboard requires an <strong>admin</strong> role.</p>
          <p>Ask an existing admin to elevate your account, then sign in again.</p>
          <div className="debug-row">
            <button onClick={onLogout}>Sign out</button>
            <Link to="/MetaRec" className="debug-link-btn">Back to MetaRec</Link>
          </div>
        </section>
      ) : !authed ? (
        <section className="debug-panel">
          <h2>Admin sign in</h2>
          <p>Sign in with your MetaRec account. Access requires the <strong>admin</strong> role.</p>
          <div className="debug-row">
            <input
              type="email"
              placeholder="Email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') onLogin() }}
            />
            <input
              type="password"
              placeholder="Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') onLogin() }}
            />
            <button onClick={onLogin}>Login</button>
          </div>
          {authError && <div className="debug-error">{authError}</div>}
        </section>
      ) : (
        <>
          <div className="debug-tabs" role="tablist" aria-label="Admin dashboard tabs">
            {tabs.map((t) => (
              <button
                key={t.key}
                role="tab"
                aria-selected={activeTab === t.key}
                className={`debug-tab ${activeTab === t.key ? 'active' : ''}`}
                onClick={() => setActiveTab(t.key)}
              >
                {t.label}
              </button>
            ))}
          </div>

          {activeTab === 'dashboard' && <DashboardOverview />}
          {activeTab === 'cms' && <UserManagement currentUserId={currentUser?.id || null} />}
          {(activeTab === 'task' || activeTab === 'unit' || activeTab === 'api') && (
            <DebugArena tab={activeTab} llmExplainEnabled={llmExplainEnabled} />
          )}
        </>
      )}
    </div>
  )
}

export default DashboardPage
