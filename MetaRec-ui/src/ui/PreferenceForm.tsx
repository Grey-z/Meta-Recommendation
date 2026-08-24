import type { DomainPreferenceForm, PreferenceField } from '../utils/api'

type Props = {
  form: DomainPreferenceForm
  values: Record<string, any>
  onChange: (values: Record<string, any>) => void
}

function asArray(value: unknown): string[] {
  if (Array.isArray(value)) return value.map(String)
  if (typeof value === 'string' && value.trim()) {
    return value.split(',').map(part => part.trim()).filter(Boolean)
  }
  return []
}

/**
 * Generic renderer for a server-generated preference form. Adding a domain's
 * form is a backend data change; this component renders whatever fields arrive.
 */
export default function PreferenceForm({ form, values, onChange }: Props) {
  const setValue = (key: string, value: unknown) => onChange({ ...values, [key]: value })

  return (
    <div style={{ display: 'grid', gap: 10 }}>
      {form.fields.map(field => {
        const requiredWhen = field.required_when
        const expected = requiredWhen?.value ?? requiredWhen?.equals
        const conditionallyRequired = requiredWhen
          ? requiredWhen.operator === 'gt'
            ? Number(values[requiredWhen.key]) > Number(expected)
            : values[requiredWhen.key] === expected
          : false
        return (
        <div key={field.key} style={{ display: 'grid', gap: 4 }}>
          <label style={{ fontSize: 13, color: 'var(--muted, #666)' }}>
            {field.label}
            {(field.required || conditionallyRequired) && <span style={{ color: 'var(--danger, #c0392b)' }}> *</span>}
          </label>
          {renderField(field, values[field.key], setValue)}
        </div>
        )
      })}
    </div>
  )
}

function renderField(
  field: PreferenceField,
  value: unknown,
  setValue: (key: string, value: unknown) => void,
) {
  if (field.type === 'multiselect') {
    const selected = asArray(value)
    return (
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
        {field.options.map(option => {
          const active = selected.includes(option)
          return (
            <button
              type="button"
              key={option}
              aria-pressed={active}
              onClick={() =>
                setValue(
                  field.key,
                  active ? selected.filter(item => item !== option) : [...selected, option],
                )
              }
              style={chipStyle(active)}
            >
              {option}
            </button>
          )
        })}
      </div>
    )
  }

  if (field.type === 'select') {
    return (
      <select
        aria-label={field.label}
        value={typeof value === 'string' ? value : ''}
        onChange={e => setValue(field.key, e.target.value)}
        style={inputStyle}
      >
        <option value="">—</option>
        {field.options.map(option => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    )
  }

  if (field.type === 'date' || field.type === 'time' || field.type === 'number') {
    return (
      <input
        aria-label={field.label}
        type={field.type}
        value={typeof value === 'string' || typeof value === 'number' ? value : ''}
        placeholder={field.placeholder}
        min={field.type === 'number' ? (field.min ?? 0) : undefined}
        max={field.type === 'number' ? (field.max ?? undefined) : undefined}
        onChange={e => setValue(field.key, field.type === 'number' && e.target.value !== '' ? Number(e.target.value) : e.target.value)}
        style={inputStyle}
      />
    )
  }

  // text (default)
  return (
    <input
      aria-label={field.label}
      value={typeof value === 'string' ? value : Array.isArray(value) ? value.join(', ') : ''}
      placeholder={field.placeholder}
      onChange={e => setValue(field.key, e.target.value)}
      style={inputStyle}
    />
  )
}

function chipStyle(active: boolean): React.CSSProperties {
  return {
    padding: '4px 10px',
    borderRadius: 999,
    border: `1px solid ${active ? 'var(--primary, #e8742c)' : 'var(--border, #ddd)'}`,
    background: active ? 'var(--primary, #e8742c)' : 'transparent',
    color: active ? '#fff' : 'inherit',
    cursor: 'pointer',
    fontSize: 13,
  }
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
