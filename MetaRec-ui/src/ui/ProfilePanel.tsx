import { useEffect, useState } from 'react'
import { getUserProfile, updateUserProfile, type UserProfile } from '../utils/api'

type Props = {
  userId: string
  onClose: () => void
}

const DEMOGRAPHIC_FIELDS: Array<{ key: string; label: string }> = [
  { key: 'age_range', label: 'Age range' },
  { key: 'gender', label: 'Gender' },
  { key: 'occupation', label: 'Occupation' },
  { key: 'location', label: 'Location' },
  { key: 'nationality', label: 'Nationality' },
]

const RESTAURANT_FIELDS: Array<{ key: string; label: string }> = [
  { key: 'typical_budget', label: 'Typical budget' },
  { key: 'dietary_restrictions', label: 'Dietary restrictions' },
  { key: 'spice_tolerance', label: 'Spice tolerance' },
]

const EMPTY: Omit<UserProfile, 'user_id'> = {
  demographics: {},
  constraints: {},
  taste_persona: '',
  domains: {},
}

function str(value: unknown): string {
  if (value == null) return ''
  if (Array.isArray(value)) return value.join(', ')
  return String(value)
}

function csv(value: string): string[] {
  return value.split(',').map(part => part.trim()).filter(Boolean)
}

/**
 * Editor for the three-layer profile: generic core (demographics + cross-domain
 * constraints), the natural-language taste persona, and per-domain slices.
 */
export default function ProfilePanel({ userId, onClose }: Props) {
  const [form, setForm] = useState<Omit<UserProfile, 'user_id'>>(EMPTY)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    getUserProfile(userId)
      .then(profile => {
        if (!active) return
        setForm({
          demographics: profile.demographics || {},
          constraints: profile.constraints || {},
          taste_persona: profile.taste_persona || '',
          domains: profile.domains || {},
        })
      })
      .catch(e => active && setError(String(e?.message || e)))
      .finally(() => active && setLoading(false))
    return () => {
      active = false
    }
  }, [userId])

  const setDemographic = (key: string, value: string) =>
    setForm(prev => ({ ...prev, demographics: { ...prev.demographics, [key]: value } }))

  const setConstraint = (key: string, value: string) =>
    setForm(prev => ({ ...prev, constraints: { ...prev.constraints, [key]: value } }))

  const setDomainField = (domain: string, key: string, value: unknown) =>
    setForm(prev => ({
      ...prev,
      domains: { ...prev.domains, [domain]: { ...(prev.domains[domain] || {}), [key]: value } },
    }))

  const handleSave = async () => {
    setSaving(true)
    setError(null)
    try {
      const updated = await updateUserProfile(userId, form)
      setForm({
        demographics: updated.demographics || {},
        constraints: updated.constraints || {},
        taste_persona: updated.taste_persona || '',
        domains: updated.domains || {},
      })
      onClose()
    } catch (e: any) {
      setError(String(e?.message || e))
    } finally {
      setSaving(false)
    }
  }

  const restaurant = form.domains.restaurant || {}
  const movie = form.domains.movie || {}

  return (
    <div className="profile-overlay" role="dialog" aria-label="Edit profile" style={overlayStyle}>
      <div className="profile-card" style={cardStyle}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <h2 style={{ margin: 0, fontSize: '1.2rem' }}>Your profile</h2>
          <button onClick={onClose} aria-label="Close" style={closeBtnStyle}>×</button>
        </div>

        {loading ? (
          <p>Loading…</p>
        ) : (
          <div style={{ display: 'grid', gap: 18 }}>
            <Section title="About you">
              {DEMOGRAPHIC_FIELDS.map(field => (
                <Field key={field.key} label={field.label}>
                  <input
                    value={str(form.demographics[field.key])}
                    onChange={e => setDemographic(field.key, e.target.value)}
                    style={inputStyle}
                  />
                </Field>
              ))}
            </Section>

            <Section title="Your taste (free text, used across all recommendations)">
              <textarea
                aria-label="Taste persona"
                value={form.taste_persona}
                onChange={e => setForm(prev => ({ ...prev, taste_persona: e.target.value }))}
                rows={3}
                placeholder="e.g. enjoys spicy Sichuan food and quiet cafes; into hard sci-fi films and literary fiction"
                style={{ ...inputStyle, resize: 'vertical' }}
              />
            </Section>

            <Section title="Constraints (apply to every domain)">
              <Field label="Language">
                <input
                  value={str(form.constraints.language)}
                  onChange={e => setConstraint('language', e.target.value)}
                  style={inputStyle}
                />
              </Field>
              <Field label="Max content rating">
                <input
                  value={str(form.constraints.content_rating_max)}
                  onChange={e => setConstraint('content_rating_max', e.target.value)}
                  style={inputStyle}
                />
              </Field>
            </Section>

            <Section title="Restaurant preferences">
              {RESTAURANT_FIELDS.map(field => (
                <Field key={field.key} label={field.label}>
                  <input
                    value={str(restaurant[field.key])}
                    onChange={e => setDomainField('restaurant', field.key, e.target.value)}
                    style={inputStyle}
                  />
                </Field>
              ))}
            </Section>

            <Section title="Movie preferences">
              <Field label="Genres (comma separated)">
                <input
                  value={str(movie.genres)}
                  onChange={e => setDomainField('movie', 'genres', csv(e.target.value))}
                  placeholder="e.g. science fiction, drama"
                  style={inputStyle}
                />
              </Field>
            </Section>

            {error && <p style={{ color: 'var(--danger, #c0392b)' }}>{error}</p>}

            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button onClick={onClose} style={secondaryBtnStyle}>Cancel</button>
              <button onClick={handleSave} disabled={saving} style={primaryBtnStyle}>
                {saving ? 'Saving…' : 'Save'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section style={{ display: 'grid', gap: 8 }}>
      <h3 style={{ margin: 0, fontSize: '0.95rem', color: 'var(--muted, #666)' }}>{title}</h3>
      {children}
    </section>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label style={{ display: 'grid', gap: 4, fontSize: 13 }}>
      <span style={{ color: 'var(--muted, #666)' }}>{label}</span>
      {children}
    </label>
  )
}

const overlayStyle: React.CSSProperties = {
  position: 'fixed',
  inset: 0,
  background: 'rgba(0,0,0,0.45)',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  zIndex: 1000,
  padding: 16,
}

const cardStyle: React.CSSProperties = {
  background: 'var(--card-bg, #fff)',
  color: 'var(--fg, #111)',
  border: '1px solid var(--border, #ddd)',
  borderRadius: 12,
  padding: 24,
  width: 'min(560px, 100%)',
  maxHeight: '90vh',
  overflowY: 'auto',
  boxShadow: '0 10px 40px rgba(0,0,0,0.2)',
}

const inputStyle: React.CSSProperties = {
  width: '100%',
  padding: '8px 10px',
  borderRadius: 8,
  border: '1px solid var(--border, #ddd)',
  background: 'var(--bg, #fff)',
  color: 'inherit',
  fontSize: 14,
}

const primaryBtnStyle: React.CSSProperties = {
  padding: '8px 16px',
  borderRadius: 8,
  border: 'none',
  background: 'var(--primary, #e8742c)',
  color: '#fff',
  fontWeight: 600,
  cursor: 'pointer',
}

const secondaryBtnStyle: React.CSSProperties = {
  padding: '8px 16px',
  borderRadius: 8,
  border: '1px solid var(--border, #ddd)',
  background: 'transparent',
  color: 'inherit',
  cursor: 'pointer',
}

const closeBtnStyle: React.CSSProperties = {
  background: 'transparent',
  border: 'none',
  fontSize: 24,
  lineHeight: 1,
  cursor: 'pointer',
  color: 'inherit',
}
