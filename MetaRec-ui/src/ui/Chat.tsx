import React, { useMemo, useRef, useState, useEffect } from 'react'
import { recommend, confirmAndStartTask, getTaskStatus, recommendWithConstraints } from '../utils/api'
import type { RecommendationResponse, ThinkingStep, ConfirmationRequest, TaskStatus } from '../utils/types'

type Message = { role: 'user' | 'assistant'; content: React.ReactNode }

interface ChatProps {
  selectedTypes: string[]
  selectedFlavors: string[]
  currentModel?: string
  chatHistory?: {
    id: string
    title: string
    model: string
    lastMessage: string
    timestamp: Date
    messages: Array<{ role: 'user' | 'assistant'; content: string }>
  }
}

export function Chat({ selectedTypes, selectedFlavors, currentModel, chatHistory }: ChatProps): JSX.Element {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: 'assistant',
      content: (
        <div>
          <div className="muted">Welcome to MetaRec.</div>
          <div>I'm your personal <strong>Restaurant Recommender</strong>. How can I help you today?</div>
        </div>
      ),
    },
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [pendingConfirmation, setPendingConfirmation] = useState<ConfirmationRequest | null>(null)
  const [lastQuery, setLastQuery] = useState('')
  const [currentTaskId, setCurrentTaskId] = useState<string | null>(null)
  const [taskStatus, setTaskStatus] = useState<TaskStatus | null>(null)
  const [isListening, setIsListening] = useState(false)
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const recognitionRef = useRef<any>(null)

  const currentFilters = useMemo(() => {
    const purpose = (document.getElementById('purpose-select') as HTMLSelectElement | null)?.value || 'any'
    const budgetMinRaw = (document.getElementById('budget-min') as HTMLInputElement | null)?.value
    const budgetMaxRaw = (document.getElementById('budget-max') as HTMLInputElement | null)?.value
    const budgetMin = budgetMinRaw ? Number(budgetMinRaw) : undefined
    const budgetMax = budgetMaxRaw ? Number(budgetMaxRaw) : undefined
    const locationSelect = (document.getElementById('location-select') as HTMLSelectElement | null)?.value || 'any'
    const locationInput = (document.getElementById('location-input') as HTMLInputElement | null)?.value || ''
    const location = locationInput || locationSelect
    return { types: selectedTypes, flavors: selectedFlavors, purpose, budgetMin, budgetMax, location }
  }, [messages, input, selectedTypes, selectedFlavors])

  // 初始化语音识别
  useEffect(() => {
    // 检查浏览器是否支持语音识别
    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    
    if (SpeechRecognition) {
      const recognition = new SpeechRecognition()
      recognition.continuous = false
      recognition.interimResults = true
      recognition.lang = 'en-US' // 可以改为 'zh-CN' 支持中文
      
      recognition.onstart = () => {
        setIsListening(true)
      }
      
      recognition.onresult = (event: any) => {
        const transcript = Array.from(event.results)
          .map((result: any) => result[0])
          .map((result: any) => result.transcript)
          .join('')
        
        setInput(transcript)
      }
      
      recognition.onerror = (event: any) => {
        console.error('Speech recognition error:', event.error)
        setIsListening(false)
      }
      
      recognition.onend = () => {
        setIsListening(false)
      }
      
      recognitionRef.current = recognition
    }
    
    return () => {
      if (recognitionRef.current) {
        recognitionRef.current.stop()
      }
    }
  }, [])

  // 轮询任务状态 - 更新同一个对话框
  useEffect(() => {
    if (!currentTaskId) return

    const pollTaskStatus = async () => {
      try {
        const status = await getTaskStatus(currentTaskId)
        setTaskStatus(status)

        // 更新最后一个消息（处理中的消息）
        setMessages(prev => {
          const newMessages = [...prev]
          const lastMessage = newMessages[newMessages.length - 1]
          
          if (lastMessage && lastMessage.role === 'assistant') {
            // 更新为ProcessingView，它会自动处理显示逻辑
            newMessages[newMessages.length - 1] = {
              ...lastMessage,
              content: <ProcessingView taskId={currentTaskId} />
            }
          }
          
          return newMessages
        })

        if (status.status === 'completed' || status.status === 'error') {
          // 任务完成或出错，停止轮询
          setCurrentTaskId(null)
          setTaskStatus(null)
        }
      } catch (error) {
        console.error('Error polling task status:', error)
      }
    }

    const interval = setInterval(pollTaskStatus, 1000) // 每秒轮询一次
    return () => clearInterval(interval)
  }, [currentTaskId])

  function synthesizePayload(query: string) {
    // Contract for backend
    return {
      query,
      constraints: {
        restaurantTypes: currentFilters.types.length > 0 ? currentFilters.types : ['any'],
        flavorProfiles: currentFilters.flavors.length > 0 ? currentFilters.flavors : ['any'],
        diningPurpose: currentFilters.purpose,
        budgetRange: {
          min: typeof currentFilters.budgetMin === 'number' ? currentFilters.budgetMin : undefined,
          max: typeof currentFilters.budgetMax === 'number' ? currentFilters.budgetMax : undefined,
          currency: 'SGD' as const,
          per: 'person' as const,
        },
        location: currentFilters.location,
      },
      // Room for future extensions: dietaryNeeds, distanceLimitKm, openNow, etc.
      meta: {
        source: 'MetaRec-UI',
        sentAt: new Date().toISOString(),
        uiVersion: '0.0.1',
      },
    }
  }

  function appendMessage(msg: Message) {
    setMessages(prev => [...prev, msg])
    queueMicrotask(() => {
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
    })
  }

  function toggleVoiceInput() {
    if (!recognitionRef.current) {
      alert('Your browser does not support speech recognition. Please use Chrome, Edge, or Safari.')
      return
    }
    
    if (isListening) {
      recognitionRef.current.stop()
    } else {
      try {
        recognitionRef.current.start()
      } catch (error) {
        console.error('Error starting speech recognition:', error)
      }
    }
  }

  async function onSend() {
    const trimmed = input.trim()
    if (!trimmed) return

    appendMessage({ role: 'user', content: trimmed })
    setInput('')
    setLoading(true)
    setPendingConfirmation(null)
    
    try {
      // 发送query和user_id，让后端智能判断意图
      const res: RecommendationResponse = await recommend(trimmed, "default")
      
      if (res.confirmation_request) {
        // 显示确认消息，但不显示按钮
        appendMessage({ 
          role: 'assistant', 
          content: <div className="confirmation-message">
            <div className="confirmation-text">
              {res.confirmation_request.message}
            </div>
          </div>
        })
      } else if (res.thinking_steps) {
        // 开始处理，显示ProcessingView
        if (res.thinking_steps.length > 0) {
          const taskIdMatch = res.thinking_steps[0].details?.match(/Task ID: (.+)/)
          if (taskIdMatch) {
            setCurrentTaskId(taskIdMatch[1])
            // 显示ProcessingView，它会自动轮询和更新
            appendMessage({ 
              role: 'assistant', 
              content: <ProcessingView taskId={taskIdMatch[1]} />
            })
          }
        }
      } else {
        // 直接显示结果
        appendMessage({ role: 'assistant', content: <ResultsView data={res} /> })
      }
    } catch (err: any) {
      appendMessage({
        role: 'assistant',
        content: (
          <div className="content" style={{ borderColor: 'var(--error)' }}>
            Failed to fetch recommendations. {err?.message || 'Unknown error'}
          </div>
        ),
      })
    } finally {
      setLoading(false)
    }
  }


  return (
    <>
      <div className="messages" ref={scrollRef}>
        {messages.map((m, i) => (
          <div key={i} className="bubble" data-role={m.role}>
            <div className="who">{m.role === 'user' ? 'You' : 'MetaRec'}</div>
            <div className="content">{m.content}</div>
          </div>
        ))}

        {loading && (
          <div className="bubble" data-role="assistant">
            <div className="who">MetaRec</div>
            <div className="content">
              <div className="skeleton" style={{ width: 220 }} />
              <div className="space" />
              <div className="skeleton" />
              <div className="space" />
              <div className="skeleton" style={{ width: '70%' }} />
            </div>
          </div>
        )}
      </div>
      <div className="composer">
        <div className="composer-inner">
          <input
            placeholder="Ask for recommendations... e.g. spicy Sichuan for date night near downtown"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                onSend()
              }
            }}
          />
          <button 
            className={`voice-btn ${isListening ? 'listening' : ''}`}
            onClick={toggleVoiceInput}
            disabled={loading}
            title={isListening ? 'Stop recording' : 'Start voice input'}
          >
            {isListening ? (
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/>
                <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
                <line x1="12" y1="19" x2="12" y2="22"/>
                <line x1="8" y1="22" x2="16" y2="22"/>
              </svg>
            ) : (
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/>
                <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
                <line x1="12" y1="19" x2="12" y2="22"/>
                <line x1="8" y1="22" x2="16" y2="22"/>
              </svg>
            )}
          </button>
          <button className="send" onClick={onSend} disabled={loading}>
            {loading ? 'Thinking…' : 'Send'}
          </button>
        </div>
      </div>
    </>
  )
}


function ProcessingView({ taskId }: { taskId: string }) {
  const [status, setStatus] = useState<TaskStatus | null>(null)
  const [currentStep, setCurrentStep] = useState(0)
  const [displayedSteps, setDisplayedSteps] = useState<ThinkingStep[]>([])
  
  useEffect(() => {
    const pollStatus = async () => {
      try {
        const taskStatus = await getTaskStatus(taskId)
        setStatus(taskStatus)
        
        // 如果有思考步骤，更新显示
        if (taskStatus.result && taskStatus.result.thinking_steps) {
          setDisplayedSteps(taskStatus.result.thinking_steps)
        }
      } catch (error) {
        console.error('Error polling status:', error)
      }
    }
    
    const interval = setInterval(pollStatus, 1000)
    return () => clearInterval(interval)
  }, [taskId])
  
  // 模拟思考步骤的逐步显示
  useEffect(() => {
    if (displayedSteps.length > 0 && currentStep < displayedSteps.length) {
      const timer = setTimeout(() => {
        setCurrentStep(prev => prev + 1)
      }, 800) // 每0.8秒显示一个步骤，更流畅
      return () => clearTimeout(timer)
    }
  }, [displayedSteps, currentStep])
  
  // 当有新的思考步骤时，重置当前步骤
  useEffect(() => {
    if (displayedSteps.length > 0) {
      setCurrentStep(0)
    }
  }, [displayedSteps.length])
  
  if (!status) {
    return (
      <div className="processing-container">
        <div className="processing-header">
          <div className="processing-icon">⚙️</div>
          <span>Starting processing...</span>
        </div>
        <div className="progress-bar">
          <div className="progress-fill" style={{ width: '0%' }} />
        </div>
        <div className="processing-message">
          Initializing...
        </div>
      </div>
    )
  }
  
  // 如果任务完成，显示结果
  if (status.status === 'completed' && status.result) {
    return <ResultsView data={status.result} />
  }
  
  // 如果任务出错，显示错误
  if (status.status === 'error') {
    return (
      <div className="content" style={{ borderColor: 'var(--error)' }}>
        Error: {status.error || 'Unknown error occurred'}
      </div>
    )
  }
  
  // 显示处理进度
  return (
    <div className="processing-container">
      <div className="processing-header">
        <div className="processing-icon">⚙️</div>
        <span>Processing your request...</span>
      </div>
      <div className="progress-bar">
        <div 
          className="progress-fill" 
          style={{ width: `${status.progress}%` }}
        />
      </div>
      <div className="processing-message">
        {status.message}
      </div>
      
      {/* 显示思考步骤 */}
      {displayedSteps.length > 0 && (
        <div className="thinking-steps">
          {displayedSteps.slice(0, currentStep + 1).map((step, index) => (
            <div key={index} className={`thinking-step ${step.status}`}>
              <div className="step-indicator">
                {step.status === 'completed' ? '✓' : step.status === 'thinking' ? '⏳' : '❌'}
              </div>
              <div className="step-content">
                <div className="step-description">{step.description}</div>
                {step.details && (
                  <div className="step-details">{step.details}</div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function ThinkingView({ 
  steps, 
  currentStep, 
  onComplete 
}: { 
  steps: ThinkingStep[]
  currentStep: number
  onComplete: () => void
}) {
  const [displayedSteps, setDisplayedSteps] = useState<ThinkingStep[]>([])
  const [isComplete, setIsComplete] = useState(false)
  
  useEffect(() => {
    if (currentStep >= 0 && currentStep < steps.length) {
      const timer = setTimeout(() => {
        setDisplayedSteps(prev => [...prev, steps[currentStep]])
        if (currentStep === steps.length - 1) {
          setIsComplete(true)
          setTimeout(() => {
            onComplete()
          }, 1500)
        }
      }, 800)
      return () => clearTimeout(timer)
    }
  }, [currentStep, steps, onComplete])

  return (
    <div className="thinking-container">
      <div className="thinking-header">
        <div className="thinking-icon">🤔</div>
        <span>AI is thinking...</span>
      </div>
      <div className="thinking-steps">
        {displayedSteps.map((step, index) => (
          <div key={index} className={`thinking-step ${step.status}`}>
            <div className="step-indicator">
              {step.status === 'completed' ? '✓' : step.status === 'thinking' ? '⏳' : '❌'}
            </div>
            <div className="step-content">
              <div className="step-description">{step.description}</div>
              {step.details && (
                <div className="step-details">{step.details}</div>
              )}
            </div>
          </div>
        ))}
        {isComplete && (
          <div className="thinking-complete">
            <div className="step-indicator">🎉</div>
            <div className="step-content">
              <div className="step-description">Recommendations ready!</div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function ResultsView({ data }: { data: RecommendationResponse }) {
  if (!data?.restaurants?.length) {
    return <div>No recommendations yet. Try adjusting filters or query.</div>
  }

  return (
    <div className="card-grid">
      {data.restaurants.map(r => (
        <div key={r.id} className="card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div style={{ fontWeight: 700 }}>{r.name}</div>
            {r.price && <span className="badge">{r.price}</span>}
          </div>
          <div className="muted" style={{ marginTop: 4 }}>
            {r.cuisine || 'Cuisine'} {r.location ? `· ${r.location}` : ''} {r.rating ? `· ⭐ ${r.rating}` : ''}
          </div>
          {r.highlights?.length ? (
            <div style={{ marginTop: 8 }}>
              {r.highlights.map((h, i) => (
                <span key={i} className="badge" style={{ marginRight: 6, marginBottom: 6 }}>
                  {h}
                </span>
              ))}
            </div>
          ) : null}
          {r.reason && <div style={{ marginTop: 10 }}>{r.reason}</div>}
          {r.reference && (
            <div style={{ marginTop: 8 }}>
              <a href={r.reference} target="_blank" rel="noreferrer" className="muted">
                Reference
              </a>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}


