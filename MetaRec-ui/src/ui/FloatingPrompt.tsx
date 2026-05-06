import React from 'react'

export interface FloatingPromptProps {
    status?: React.ReactNode
    onConfirm?: () => void
    onConfirmText?: string
    onNotSatisfied?: () => void
    onNotSatisfiedText?: string
    onDismiss?: () => void
}

export const FloatingPrompt = ({
    status,
    onConfirm,
    onConfirmText,
    onNotSatisfied,
    onNotSatisfiedText,
    onDismiss,
}: FloatingPromptProps) => {
    return <div className="floating-confirmation-buttons" style={{
                  position: 'relative',
                  marginTop: '4px',
                  maxWidth: '80%',
                  width: '100%',
                  display: 'flex',
                  gap: '8px',
                  alignItems: 'center',
                  justifyContent: 'flex-start',
                  background: 'rgba(var(--bg-rgb), 0.95)',
                  backdropFilter: 'blur(10px)',
                  padding: '8px 16px',
                  borderRadius: 'var(--radius-lg)',
                  boxShadow: '0 1px 3px rgba(0, 0, 0, 0.08)',
                  border: '1px solid var(--border-light)',
                  animation: 'slideUp 0.3s ease-out'
                }}>
                  {status}
                  { onConfirm && <button
                    onClick={() => onConfirm?.()}
                    style={{
                      padding: '6px 14px',
                      background: 'var(--primary)',
                      color: 'white',
                      border: 'none',
                      borderRadius: '6px',
                      fontSize: '12px',
                      fontWeight: 500,
                      cursor: 'pointer',
                      transition: 'all 0.2s ease',
                      whiteSpace: 'nowrap'
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.background = 'var(--primary-hover)'
                      e.currentTarget.style.transform = 'translateY(-1px)'
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.background = 'var(--primary)'
                      e.currentTarget.style.transform = 'translateY(0)'
                    }}
                  >
                    {onConfirmText || 'Confirm'} 
                  </button>}
                  {onNotSatisfied && <button
                    onClick={() => onNotSatisfied?.()}
                    style={{
                      padding: '6px 14px',
                      background: 'transparent',
                      color: 'var(--fg-secondary)',
                      border: '1px solid var(--border)',
                      borderRadius: '6px',
                      fontSize: '12px',
                      fontWeight: 500,
                      cursor: 'pointer',
                      transition: 'all 0.2s ease',
                      whiteSpace: 'nowrap'
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.background = 'var(--bg-secondary)'
                      e.currentTarget.style.borderColor = 'var(--primary)'
                      e.currentTarget.style.color = 'var(--fg)'
                      e.currentTarget.style.transform = 'translateY(-1px)'
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.background = 'transparent'
                      e.currentTarget.style.borderColor = 'var(--border)'
                      e.currentTarget.style.color = 'var(--fg-secondary)'
                      e.currentTarget.style.transform = 'translateY(0)'
                    }}
                  >
                    {onNotSatisfiedText || 'Not Satisfied'}
                  </button>}
                  {onDismiss && <button
                    onClick={() => onDismiss?.()}
                    style={{
                      padding: '4px',
                      background: 'transparent',
                      color: 'var(--muted)',
                      border: 'none',
                      borderRadius: '4px',
                      fontSize: '16px',
                      lineHeight: '1',
                      cursor: 'pointer',
                      transition: 'all 0.2s ease',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      width: '24px',
                      height: '24px',
                      marginLeft: 'auto'
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.background = 'var(--bg-secondary)'
                      e.currentTarget.style.color = 'var(--fg)'
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.background = 'transparent'
                      e.currentTarget.style.color = 'var(--muted)'
                    }}
                    title="关闭"
                  >
                    ×
                  </button>}
                </div>
}
