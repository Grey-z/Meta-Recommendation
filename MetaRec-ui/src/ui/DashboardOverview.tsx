import React, { useCallback, useEffect, useState } from 'react'
import { getAdminStats, type AdminStats } from '../utils/adminApi'
import { BarList, CHART_COLORS, Donut, StackedBar } from './DashboardCharts'

// "Real-time" = computed on request, auto-polled while the tab is open, plus a
// manual Refresh. 20s keeps load light while staying current enough for an
// admin overview.
const POLL_MS = 20000

// Chart mapping (one presentation per data shape):
//   Tasks         → donut/gauge (success rate as a part-to-whole ratio)
//   Tokens        → stacked bar (prompt vs completion split of the total)
//   Users         → donut (registered vs guests, total in the center)
//   Conversations → bar chart (created vs active sessions, two categories)
//   Feedback      → stacked bar (satisfaction) + histogram (reasons)

function fmtInt(n: number): string {
  return new Intl.NumberFormat().format(Math.round(n || 0))
}
function fmtPct(ratio: number | null | undefined): string {
  if (ratio == null) return '—'
  return `${(ratio * 100).toFixed(1)}%`
}
function fmtUsd(n: number): string {
  return `$${(n || 0).toFixed(2)}`
}

export function DashboardOverview(): JSX.Element {
  const [stats, setStats] = useState<AdminStats | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [lastUpdated, setLastUpdated] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const s = await getAdminStats()
      setStats(s)
      setError(null)
      setLastUpdated(new Date().toLocaleTimeString())
    } catch (e: any) {
      setError(e?.message || 'Failed to load statistics')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    const id = window.setInterval(load, POLL_MS)
    return () => window.clearInterval(id)
  }, [load])

  return (
    <section className="debug-panel dashboard-overview" aria-label="Dashboard statistics">
      <div className="dashboard-overview-head">
        <h2>Collective Statistics</h2>
        <div className="dashboard-overview-actions">
          {lastUpdated && <span className="dashboard-muted">Updated {lastUpdated}</span>}
          <button onClick={load} disabled={loading}>{loading ? 'Refreshing…' : 'Refresh'}</button>
        </div>
      </div>

      {error && <div className="debug-error">{error}</div>}
      {!stats && !error && <p className="dashboard-muted">Loading statistics…</p>}

      {stats && (
        <div className="dashboard-card-grid">
          <StatCard title="Tasks">
            <div className="dashboard-card-viz">
              <Donut
                segments={[
                  { value: stats.tasks.completed, color: CHART_COLORS.good, label: 'Completed' },
                  { value: stats.tasks.errored, color: CHART_COLORS.bad, label: 'Errored' },
                ]}
                centerValue={fmtPct(stats.tasks.success_rate)}
                centerLabel="success"
              />
              <div className="dashboard-card-body">
                <Stat label="Total done" value={fmtInt(stats.tasks.completed)} />
                <Stat label="Errored" value={fmtInt(stats.tasks.errored)} />
              </div>
            </div>
          </StatCard>

          <StatCard title="Token Consumption">
            <StackedBar
              segments={[
                { value: stats.tokens.prompt_tokens, color: CHART_COLORS.primary, label: 'Prompt' },
                { value: stats.tokens.completion_tokens, color: CHART_COLORS.accent, label: 'Completion' },
              ]}
            />
            <div className="dashboard-card-body">
              <Stat label="Total tokens" value={fmtInt(stats.tokens.total_tokens)} />
              <Stat label="Last 7 days" value={fmtInt(stats.tokens.last_7d_total_tokens)} />
              <Stat label="Est. cost" value={fmtUsd(stats.tokens.cost_usd)} />
            </div>
          </StatCard>

          <StatCard title="Users">
            <div className="dashboard-card-viz">
              <Donut
                segments={[
                  { value: stats.users.registered, color: CHART_COLORS.primary, label: 'Registered' },
                  { value: stats.users.guests, color: CHART_COLORS.secondary, label: 'Guests' },
                ]}
                centerValue={fmtInt(stats.users.total)}
                centerLabel="users"
              />
              <div className="dashboard-card-body">
                <Stat label="New (last week)" value={fmtInt(stats.users.new_registered_last_7d)} />
                <Stat label="Registered" value={fmtInt(stats.users.registered)} />
              </div>
            </div>
          </StatCard>

          <StatCard title="Conversations">
            <BarList
              items={[
                { label: 'Created', value: stats.conversations.total_created, color: CHART_COLORS.primary },
                { label: 'Active sessions', value: stats.conversations.active_sessions, color: CHART_COLORS.accent },
              ]}
            />
          </StatCard>

          <StatCard title="Feedback">
            {stats.feedback.total === 0 ? (
              <p className="dashboard-muted">No feedback collected yet.</p>
            ) : (
              <>
                <StackedBar
                  segments={[
                    { value: stats.feedback.satisfied, color: CHART_COLORS.good, label: 'Satisfied' },
                    { value: stats.feedback.unsatisfied, color: CHART_COLORS.bad, label: 'Unsatisfied' },
                  ]}
                />
                <div className="dashboard-card-body">
                  <Stat label="Satisfaction" value={fmtPct(stats.feedback.satisfaction_ratio)} />
                </div>
                {stats.feedback.reasons.length > 0 && (
                  <div className="dashboard-reasons">
                    <span className="dashboard-muted">Why unsatisfied</span>
                    <BarList
                      items={stats.feedback.reasons.map((r) => ({
                        label: r.reason,
                        value: r.count,
                        color: CHART_COLORS.bad,
                      }))}
                    />
                  </div>
                )}
              </>
            )}
          </StatCard>
        </div>
      )}
    </section>
  )
}

function StatCard({ title, children }: { title: string; children: React.ReactNode }): JSX.Element {
  return (
    <div className="dashboard-card">
      <h3>{title}</h3>
      <div className="dashboard-card-content">{children}</div>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }): JSX.Element {
  return (
    <div className="dashboard-stat">
      <span className="dashboard-stat-value">{value}</span>
      <span className="dashboard-stat-label">{label}</span>
    </div>
  )
}

export default DashboardOverview
