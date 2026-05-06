import { useState, useEffect, useRef } from 'react';

interface Option {
    value: string
    label: string
}

interface Limit {
    default?: number
}

interface SelectSpec {
    prefKey: string
    label: string
    kind: 'SelectSpec'

    options: Option[]
    allowMultiple: boolean
    allowOther?: boolean
}

interface RangeSpec {
    prefKey: string
    label: string
    kind: 'RangeSpec'

    upperLimit: Limit
    lowerLimit: Limit
    step: number
}

interface WithUpdater {
    update?: (key: string, value: any) => any
}

type PreferenceSpec = RangeSpec | SelectSpec;

const PLIST: PreferenceSpec[] = [
        {
            kind: 'SelectSpec',
            options: [
                { value: 'casual', label: 'Casual' },
                { value: 'fine-dining', label: 'Fine Dining' },
                { value: 'fast-casual', label: 'Fast Casual' },
                { value: 'street-food', label: 'Street Food' },
                { value: 'buffet', label: 'Buffet' },
                { value: 'cafe', label: 'Cafe' },
            ],
            label: "Restaurant Types",
            allowMultiple: true,
            prefKey: 'restaurant.type'
        },
        {
            kind: 'SelectSpec',
            options: [
                { value: 'spicy', label: 'Spicy' },
                { value: 'savory', label: 'Savory' },
                { value: 'sweet', label: 'Sweet' },
                { value: 'sour', label: 'Sour' },
                { value: 'umami', label: 'Umami' },
                { value: 'mild', label: 'Mild' },
            ],
            label: "Flavor Profiles",
            allowMultiple: true,
            prefKey: 'restaurant.flavor'
        },
        {
            kind: 'SelectSpec',
            options: [
                { value: 'other', label: 'Other' },
                { value: 'any', label: 'Any' },
                { value: 'date-night', label: 'Date Night' },
                { value: 'family', label: 'Family' },
                { value: 'business', label: 'Business' },
                { value: 'solo', label: 'Solo' },
                { value: 'friends', label: 'Friends' },
                { value: 'celebration', label: 'Celebration' },
            ],
            label: "Dining Purpose",
            allowMultiple: false,
            prefKey: 'restaurant.purpose'
        },
        {
            kind: 'SelectSpec',
            options: [
                { value: 'any', label: 'Any' },
                { value: 'Orchard', label: 'Orchard' },
                { value: 'Marina Bay', label: 'Marina Bay' },
                { value: 'Chinatown', label: 'Chinatown' },
                { value: 'Bugis', label: 'Bugis' },
                { value: 'Tanjong Pagar', label: 'Tanjong Pagar' },
                { value: 'Clarke Quay', label: 'Clarke Quay' },
                { value: 'Little India', label: 'Little India' },
                { value: 'Holland Village', label: 'Holland Village' },
                { value: 'Tiong Bahru', label: 'Tiong Bahru' },
                { value: 'Katong / Joo Chiat', label: 'Katong / Joo Chiat' },
            ],
            label: "Location",
            allowMultiple: false,
            allowOther: true,
            prefKey: 'restaurant.location'
        },
        {
            kind: 'RangeSpec',
            lowerLimit: { default: 0},
            upperLimit: { },
            label: 'Budget Range (SGD) Per Person',
            prefKey: 'restaurant.budget',
            step: 1,
        },
]

export function BoundedRange({
    upperLimit,
    lowerLimit,
    label,
    step,
    update,
    prefKey,
}: RangeSpec & WithUpdater ) {
    const [maximum, setMaximum] = useState<string>(String(upperLimit.default))
    const [minimum, setMinimum] = useState<string>(String(lowerLimit.default))
    
    useEffect(() => {
        update?.(`${prefKey}.min`, minimum)
        update?.(`${prefKey}.max`, maximum)
    }, [minimum, maximum])

    return (
        <div>
          <label style={{ fontSize: '12px', fontWeight: 500, marginBottom: '6px', display: 'block', color: 'var(--fg-secondary)' }}>
            {label}
          </label>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <input 
              type="number" 
              min={lowerLimit.default} 
              max={maximum}
              step={step || 1} 
              placeholder="Min" 
              value={minimum}
              onChange={(e) => {
                setMinimum(e.target.value)
              }}
              style={{
                flex: 1,
                padding: '8px 12px',
                border: '1px solid var(--border)',
                borderRadius: '8px',
                background: 'var(--bg)',
                color: 'var(--fg)',
                fontSize: '13px'
              }}
            />
            <span style={{ color: 'var(--muted)', fontSize: '12px' }}>to</span>
            <input 
              type="number" 
              min={minimum}
              max={upperLimit.default}
              step={step || 1} 
              placeholder="Max" 
              value={maximum}
              onChange={(e) => {
                setMaximum(e.target.value)
              }}
              style={{
                flex: 1,
                padding: '8px 12px',
                border: '1px solid var(--border)',
                borderRadius: '8px',
                background: 'var(--bg)',
                color: 'var(--fg)',
                fontSize: '13px'
              }}
            />
          </div>
        </div>
    )
}

export function Dropdown({
    label,
    options,
    allowMultiple,
    allowOther,
    prefKey,
    update,
}: SelectSpec & WithUpdater) {
    const dropdownRef = useRef<HTMLDivElement | null>(null)
    const [selected, setSelected] = useState<Option[]>([]);
    const [isOpen, setOpen] = useState<boolean>(false);
    const [other, setOther] = useState<string>("");

    const toggleOption = (option: Option) => {
        setSelected((prev: Option[]) => {
            const isSelected = prev.map(x => x.value).includes(option.value);
            var selected;
            if (isSelected) {
                selected = prev.filter(x => x.value != option.value)
            } else {
                selected = allowMultiple ? [...prev, option] : [option]
            }
            update?.(prefKey, selected.map(x => x.value))
            return selected;
        })
    
        if (!allowMultiple) {
            setOpen(!isOpen);
        }
    }

    const showOther = allowOther && !allowMultiple && selected.length == 1 && selected[0].value == 'other';
    
    var triggerLabel;
    if (allowMultiple) {
        triggerLabel = `${selected.length} selected`
    } else if (selected.length > 0) {
        triggerLabel = selected[0].label;
    } else {
        triggerLabel = 'None selected';
    }
    
    var selectedSymbol = allowMultiple ? '✓': '';
    
    useEffect(() => {
        if (!isOpen) return;
        const handleClickOutside = (event: MouseEvent) => {
          if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
            setOpen(false)
          }
        }
        
        document.addEventListener('mousedown', handleClickOutside)
        return () => {
            document.removeEventListener('mousedown', handleClickOutside)
        }
    }, [isOpen])
    
    return (
        <div>
          <label style={{ fontSize: '12px', fontWeight: 500, marginBottom: '6px', display: 'block', color: 'var(--fg-secondary)' }}>{label}</label>

          <div className="compact-multi-select" style={{ position: 'relative' }} ref={dropdownRef}>

          {allowMultiple && <div className="selected-tags" style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '6px' }}>
              {selected.map(option => (
                <span key={option.value} className="tag" onClick={() => toggleOption(option)} style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  padding: '4px 8px',
                  background: 'var(--primary-light)',
                  color: 'var(--primary-dark)',
                  borderRadius: '6px',
                  fontSize: '11px',
                  cursor: 'pointer'
                }}>
                  {option.label}
                  <span className="tag-remove" style={{ marginLeft: '4px' }}>×</span>
                </span>
              ))}
            </div>}

            <div className="dropdown-trigger" onClick={() => setOpen(!isOpen)} style={{
              padding: '8px 12px',
              border: '1px solid var(--border)',
              borderRadius: '8px',
              cursor: 'pointer',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              background: 'var(--bg)'
            }}>
              <span className={`dropdown-text ${selected.length === 0 ? 'placeholder' : ''}`} style={{
                color: selected.length === 0 ? 'var(--muted)' : 'var(--fg)',
                fontSize: '13px'
              }}>
                {triggerLabel}
              </span>
              <span className="dropdown-arrow" style={{ fontSize: '10px' }}>▼</span>
            </div>

            {isOpen && (
              <div className="dropdown-menu" style={{
                position: 'absolute',
                top: '100%',
                left: 0,
                right: 0,
                marginTop: '4px',
                background: 'var(--bg)',
                border: '1px solid var(--border)',
                borderRadius: '8px',
                boxShadow: '0 4px 12px rgba(0,0,0,0.1)',
                zIndex: 1000,
                maxHeight: '200px',
                overflowY: 'auto'
              }}>
                {options.map(option => {
                    const isSelected = selected.map(x => x.value).includes(option.value);
                    return (
                    <div 
                        key={option.value} 
                        className={`dropdown-option ${isSelected ? 'selected' : ''}`}
                        onClick={() => toggleOption(option)}
                        style={{
                          padding: '8px 12px',
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '8px',
                          background: isSelected ? 'var(--primary-light)' : 'transparent'
                        }}
                    >
                        <span className="checkbox" style={{ 
                            width: '16px', 
                            height: '16px', 
                            display: 'flex', 
                            alignItems: 'center', 
                            justifyContent: 'center',
                            borderRadius: allowMultiple ? '3px' : '8px',
                        }}>
                          {isSelected ? selectedSymbol : ''}
                        </span>
                        <span>{option.label}</span>
                    </div>
                    )
                })}
              </div>
            )}

          { showOther && <input 
            placeholder={`Other ${label}`}
            value={other}
            onChange={(e) => {
                setOther(e.target.value);
              }
            }
            style={{
              width: '100%',
              padding: '8px 12px',
              border: '1px solid var(--border)',
              borderRadius: '8px',
              background: 'var(--bg)',
              color: 'var(--fg)',
              fontSize: '13px'
            }}
          />}
          </div>
        </div>
    )
}

export function PreferenceDisplay({ 
  preferences, 
  onConfirm,
  onConfirmText,
}: { 
  onConfirmText: string
  preferences: PreferenceSpec[]
  onConfirm?: (data: Record<string, any>) => void
}) {

    const formDataRef = useRef<Record<string, any>>({});
    const update = (key: string, value: any) => {
        const data = formDataRef.current;
        formDataRef.current = {...data, [key]: value};
        console.log(data)
    }
    const handleConfirm = () => onConfirm?.(formDataRef.current);


  return (
    <div className="preference-display" style={{
      marginTop: '16px',
      padding: '16px',
      background: 'rgba(var(--bg-secondary-rgb), 0.5)',
      borderRadius: '12px',
      border: '1px solid rgba(var(--primary-rgb), 0.1)'
    }}>
      <div style={{ fontSize: '12px', fontWeight: 600, marginBottom: '12px', color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
        Current Preferences
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
        {preferences.map((pinfo: PreferenceSpec) => {
            switch (pinfo.kind) {
                case 'RangeSpec': {
                    const { kind, ...data } = pinfo;
                    const spec = data as RangeSpec;
                    return <BoundedRange {...spec} update={update}/>
                }
                case 'SelectSpec': {
                    const { kind, ...data } = pinfo;
                    const spec = data as SelectSpec;
                    return <Dropdown {...spec} update={update}/>
                }
                default:
                    return null;
            }
        })}

        {/* Confirm Button */}
        {onConfirm && (
          <button
            onClick={handleConfirm}
            style={{
              marginTop: '8px',
              padding: '10px 20px',
              background: 'var(--primary)',
              color: 'white',
              border: 'none',
              borderRadius: '8px',
              fontSize: '13px',
              fontWeight: 500,
              cursor: 'pointer',
              transition: 'all 0.2s ease',
              width: '100%'
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = 'var(--primary-hover)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = 'var(--primary)'
            }}
          >
            {onConfirmText}
          </button>
        )}
      </div>
    </div>
  )
}
