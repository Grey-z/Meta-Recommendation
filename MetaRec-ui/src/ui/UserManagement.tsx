import React, { useCallback, useEffect, useState } from 'react'
import {
  createUser,
  deleteUser,
  listUsers,
  updateUser,
  type AdminUser,
} from '../utils/adminApi'

const PAGE_SIZE = 20
const ROLES = ['user', 'admin']
const STATUSES = ['active', 'suspended', 'deleted']

type Notice = { kind: 'success' | 'error' | 'warning'; message: string } | null

// User-table CMS. Reads are strictly paginated (backend + frontend); edits send
// the row's updated_at as an optimistic-concurrency token (409 → reload); the
// acting admin cannot downgrade or deactivate/delete itself (mirrored here for
// UX, enforced authoritatively on the server).
export function UserManagement({ currentUserId }: { currentUserId: string | null }): JSX.Element {
  const [users, setUsers] = useState<AdminUser[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [search, setSearch] = useState('')
  const [roleFilter, setRoleFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<Notice>(null)

  const [editing, setEditing] = useState<AdminUser | null>(null)
  const [creating, setCreating] = useState(false)

  const load = useCallback(
    async (nextOffset: number) => {
      setLoading(true)
      try {
        const res = await listUsers({
          limit: PAGE_SIZE,
          offset: nextOffset,
          search: search.trim() || undefined,
          role: roleFilter || undefined,
          status: statusFilter || undefined,
        })
        setUsers(res.items)
        setTotal(res.total)
        setOffset(res.offset)
        setError(null)
      } catch (e: any) {
        setError(e?.message || 'Failed to load users')
      } finally {
        setLoading(false)
      }
    },
    [search, roleFilter, statusFilter],
  )

  // Filters/search reset to the first page; search is debounced.
  useEffect(() => {
    const t = window.setTimeout(() => { load(0) }, 250)
    return () => window.clearTimeout(t)
  }, [load])

  const page = Math.floor(offset / PAGE_SIZE) + 1
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const canPrev = offset > 0
  const canNext = offset + PAGE_SIZE < total

  const onSaveEdit = async (form: { role: string; status: string; display_name: string }) => {
    if (!editing) return
    try {
      await updateUser(editing.id, {
        expected_updated_at: editing.updated_at,
        role: form.role,
        status: form.status,
        display_name: form.display_name,
      })
      setNotice({ kind: 'success', message: 'User updated.' })
      setEditing(null)
      await load(offset)
    } catch (e: any) {
      const msg = String(e?.message || '')
      if (msg.includes('409')) {
        setNotice({ kind: 'warning', message: 'This user was modified elsewhere — reloaded the latest.' })
        setEditing(null)
        await load(offset)
      } else {
        setNotice({ kind: 'error', message: msg || 'Update failed' })
      }
    }
  }

  const onCreate = async (form: {
    email: string
    password: string
    display_name: string
    role: string
    status: string
  }) => {
    try {
      await createUser({
        email: form.email,
        password: form.password,
        display_name: form.display_name || null,
        role: form.role,
        status: form.status,
      })
      setNotice({ kind: 'success', message: 'User created.' })
      setCreating(false)
      await load(0)
    } catch (e: any) {
      setNotice({ kind: 'error', message: e?.message || 'Create failed' })
    }
  }

  const onDelete = async (u: AdminUser) => {
    if (u.id === currentUserId) return
    if (!window.confirm(`Deactivate ${u.email || u.id}? Their data is retained and this can be reversed.`)) return
    try {
      await deleteUser(u.id)
      setNotice({ kind: 'success', message: 'User deactivated.' })
      await load(offset)
    } catch (e: any) {
      setNotice({ kind: 'error', message: e?.message || 'Delete failed' })
    }
  }

  return (
    <section className="debug-panel user-management" aria-label="User management">
      <div className="dashboard-overview-head">
        <h2>User Management</h2>
        <div className="dashboard-overview-actions">
          <button onClick={() => { setNotice(null); setCreating(true) }}>+ Create user</button>
        </div>
      </div>

      <div className="cms-filters">
        <input
          type="search"
          placeholder="Search email or name"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          aria-label="Search users"
        />
        <select value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)} aria-label="Filter by role">
          <option value="">All roles</option>
          {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} aria-label="Filter by status">
          <option value="">All statuses</option>
          {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>

      {notice && <div className={notice.kind === 'error' ? 'debug-error' : `cms-notice ${notice.kind}`}>{notice.message}</div>}
      {error && <div className="debug-error">{error}</div>}

      <table className="dashboard-table">
        <thead>
          <tr>
            <th>Email</th>
            <th>Name</th>
            <th>Role</th>
            <th>Status</th>
            <th>Kind</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {users.length === 0 && !loading && (
            <tr><td colSpan={6} className="dashboard-muted">No users found.</td></tr>
          )}
          {users.map((u) => {
            const isSelf = u.id === currentUserId
            return (
              <tr key={u.id} className={isSelf ? 'cms-self-row' : ''}>
                <td>{u.email || <span className="dashboard-muted">(guest)</span>}{isSelf && <span className="cms-you-badge"> you</span>}</td>
                <td>{u.display_name || <span className="dashboard-muted">—</span>}</td>
                <td><span className={`cms-pill role-${u.role}`}>{u.role}</span></td>
                <td><span className={`cms-pill status-${u.status}`}>{u.status}</span></td>
                <td>{u.kind}</td>
                <td className="cms-actions">
                  <button onClick={() => { setNotice(null); setEditing(u) }}>Edit</button>
                  <button
                    className="cms-danger"
                    disabled={isSelf}
                    title={isSelf ? 'You cannot deactivate your own account' : 'Deactivate user'}
                    onClick={() => onDelete(u)}
                  >
                    Deactivate
                  </button>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>

      <div className="cms-pagination">
        <button onClick={() => load(Math.max(0, offset - PAGE_SIZE))} disabled={!canPrev || loading}>Prev</button>
        <span className="dashboard-muted">
          Page {page} of {pageCount} · {total} user{total === 1 ? '' : 's'}
        </span>
        <button onClick={() => load(offset + PAGE_SIZE)} disabled={!canNext || loading}>Next</button>
      </div>

      {editing && (
        <EditUserModal
          user={editing}
          isSelf={editing.id === currentUserId}
          onCancel={() => setEditing(null)}
          onSave={onSaveEdit}
        />
      )}
      {creating && <CreateUserModal onCancel={() => setCreating(false)} onCreate={onCreate} />}
    </section>
  )
}

function EditUserModal({
  user,
  isSelf,
  onCancel,
  onSave,
}: {
  user: AdminUser
  isSelf: boolean
  onCancel: () => void
  onSave: (form: { role: string; status: string; display_name: string }) => void
}): JSX.Element {
  const [role, setRole] = useState(user.role)
  const [status, setStatus] = useState(user.status)
  const [displayName, setDisplayName] = useState(user.display_name || '')

  return (
    <div className="cms-modal-backdrop" role="dialog" aria-modal="true" aria-label="Edit user">
      <div className="cms-modal">
        <h3>Edit user</h3>
        <p className="dashboard-muted">{user.email || user.id}</p>
        {isSelf && (
          <p className="cms-notice warning">You cannot change your own role or status.</p>
        )}
        <label>Display name</label>
        <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} aria-label="Display name" />
        <label>Role</label>
        <select value={role} onChange={(e) => setRole(e.target.value)} disabled={isSelf} aria-label="Role">
          {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
        <label>Status</label>
        <select value={status} onChange={(e) => setStatus(e.target.value)} disabled={isSelf} aria-label="Status">
          {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <div className="debug-row cms-modal-actions">
          <button onClick={onCancel}>Cancel</button>
          <button onClick={() => onSave({ role, status, display_name: displayName })}>Save</button>
        </div>
      </div>
    </div>
  )
}

function CreateUserModal({
  onCancel,
  onCreate,
}: {
  onCancel: () => void
  onCreate: (form: { email: string; password: string; display_name: string; role: string; status: string }) => void
}): JSX.Element {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [role, setRole] = useState('user')
  const [status, setStatus] = useState('active')

  const canSubmit = email.includes('@') && password.length >= 8

  return (
    <div className="cms-modal-backdrop" role="dialog" aria-modal="true" aria-label="Create user">
      <div className="cms-modal">
        <h3>Create user</h3>
        <label>Email</label>
        <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} aria-label="Email" />
        <label>Temporary password</label>
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} aria-label="Temporary password" />
        <p className="dashboard-muted">At least 8 characters. Share securely; the user can change it later.</p>
        <label>Display name</label>
        <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} aria-label="Display name" />
        <label>Role</label>
        <select value={role} onChange={(e) => setRole(e.target.value)} aria-label="New user role">
          {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
        <label>Status</label>
        <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="New user status">
          {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <div className="debug-row cms-modal-actions">
          <button onClick={onCancel}>Cancel</button>
          <button
            disabled={!canSubmit}
            title={canSubmit ? 'Create user' : 'Enter a valid email and an 8+ character password'}
            onClick={() => onCreate({ email, password, display_name: displayName, role, status })}
          >
            Create
          </button>
        </div>
      </div>
    </div>
  )
}

export default UserManagement
