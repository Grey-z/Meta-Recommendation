import React, { useMemo, useRef, useState, useEffect, useCallback } from 'react'
import { recommend, recommendStream, getTaskStatus, getConversation, addMessage } from '../utils/api'
import type { RecommendationResponse, ThinkingStep, ConfirmationRequest, TaskStatus } from '../utils/types'
import { MapModal } from './MapModal'

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
  conversationId?: string | null
  userId?: string
  onMessageAdded?: (role: 'user' | 'assistant', content: string) => void
}

export function Chat({ selectedTypes, selectedFlavors, currentModel, chatHistory, conversationId, userId, onMessageAdded }: ChatProps): JSX.Element {
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
  const [isLoadingHistory, setIsLoadingHistory] = useState(false)
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [pendingConfirmation, setPendingConfirmation] = useState<ConfirmationRequest | null>(null)
  const [lastQuery, setLastQuery] = useState('')
  const [currentTaskId, setCurrentTaskId] = useState<string | null>(null)
  const [taskStatus, setTaskStatus] = useState<TaskStatus | null>(null)
  const [isListening, setIsListening] = useState(false)
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const recognitionRef = useRef<any>(null)
  // Map state - lifted to Chat component top level
  const [mapRestaurant, setMapRestaurant] = useState<{
    name: string
    address: string
    coordinates?: { latitude: number; longitude: number }
  } | null>(null)

  // Use useCallback to ensure callback function stability
  const handleAddressClick = useCallback((restaurant: {
    name: string
    address: string
    coordinates?: { latitude: number; longitude: number }
  }) => {
    console.log('Opening map for:', restaurant.name)
    setMapRestaurant(restaurant)
  }, [])

  // Add/remove class to body when map is open
  useEffect(() => {
    if (mapRestaurant) {
      document.body.classList.add('map-open')
    } else {
      document.body.classList.remove('map-open')
    }
    return () => {
      document.body.classList.remove('map-open')
    }
  }, [mapRestaurant])

  // 加载历史对话消息
  useEffect(() => {
    const loadHistory = async () => {
      if (!conversationId || !userId) return
      
      setIsLoadingHistory(true)
      try {
        const conversation = await getConversation(userId, conversationId)
        
        if (conversation && conversation.messages && conversation.messages.length > 0) {
          // 将历史消息转换为Message格式，并恢复推荐结果UI
          const historyMessages: Message[] = conversation.messages.map(msg => {
            // 检查是否有推荐结果数据
            if (msg.metadata?.type === 'recommendation' && msg.metadata?.recommendation_data) {
              const recommendationData = msg.metadata.recommendation_data as RecommendationResponse
              return {
                role: msg.role,
                content: <ResultsView 
                  data={recommendationData} 
                  onAddressClick={handleAddressClick}
                />
              }
            }
            // 普通文本消息
            return {
              role: msg.role,
              content: msg.content
            }
          })
          
          setMessages(historyMessages)
        } else {
          // 如果没有历史消息，显示欢迎消息
          setMessages([
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
        }
      } catch (error) {
        console.error('Error loading conversation history:', error)
        // 如果加载失败，显示欢迎消息
        setMessages([
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
      } finally {
        setIsLoadingHistory(false)
      }
    }
    
    loadHistory()
  }, [conversationId, userId, handleAddressClick])

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

  // Initialize speech recognition
  useEffect(() => {
    // Check if browser supports speech recognition
    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    
    if (SpeechRecognition) {
      const recognition = new SpeechRecognition()
      recognition.continuous = false
      recognition.interimResults = true
      recognition.lang = 'en-US' // Can be changed to 'zh-CN' for Chinese support
      
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

  // Poll task status - update the same dialog
  useEffect(() => {
    if (!currentTaskId) return

    let intervalId: ReturnType<typeof setInterval> | null = null

    const pollTaskStatus = async () => {
      try {
        const status = await getTaskStatus(currentTaskId)
        setTaskStatus(status)

        // Update the last message (processing message)
        setMessages(prev => {
          const newMessages = [...prev]
          const lastMessage = newMessages[newMessages.length - 1]
          
          if (lastMessage && lastMessage.role === 'assistant') {
            if (status.status === 'completed' && status.result) {
              // Task completed, update to ResultsView
              newMessages[newMessages.length - 1] = {
                ...lastMessage,
                content: <ResultsView 
                  data={status.result} 
                  onAddressClick={handleAddressClick}
                />
              }
            } else if (status.status === 'error') {
              // Task error, show error message
              newMessages[newMessages.length - 1] = {
                ...lastMessage,
                content: (
                  <div className="content" style={{ borderColor: 'var(--error)' }}>
                    Error: {status.error || 'Unknown error occurred'}
                  </div>
                )
              }
            } else {
              // Still processing, update to ProcessingView
              newMessages[newMessages.length - 1] = {
                ...lastMessage,
                content: <ProcessingView 
                  taskId={currentTaskId} 
                  onAddressClick={handleAddressClick}
                  onComplete={(result) => {
                    // Save complete recommendation data when ProcessingView completes
                    saveRecommendationResult(result).catch(err => {
                      console.error('Error saving recommendation result:', err)
                    })
                  }}
                />
              }
            }
          }
          
          return newMessages
        })

        // Stop polling when task is completed or error occurred
        if (status.status === 'completed' || status.status === 'error') {
          // Clear interval immediately to stop polling
          if (intervalId) {
            clearInterval(intervalId)
            intervalId = null
          }
          
          // Task completed or error occurred, stop polling
          if (status.status === 'completed' && status.result) {
            // Save complete recommendation data when task completes
            saveRecommendationResult(status.result).catch(err => {
              console.error('Error saving recommendation result:', err)
            })
          }
          setCurrentTaskId(null)
          setTaskStatus(null)
        }
      } catch (error) {
        console.error('Error polling task status:', error)
      }
    }

    intervalId = setInterval(pollTaskStatus, 1000) // Poll every second
    return () => {
      if (intervalId) {
        clearInterval(intervalId)
      }
    }
  }, [currentTaskId, handleAddressClick])

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

  // 从React节点提取文本内容的辅助函数
  const extractTextFromContent = (content: React.ReactNode): string => {
    if (typeof content === 'string') {
      return content
    }
    if (typeof content === 'number') {
      return String(content)
    }
    if (React.isValidElement(content)) {
      // 尝试从React元素中提取文本
      if (content.props && content.props.children) {
        return extractTextFromContent(content.props.children)
      }
    }
    if (Array.isArray(content)) {
      return content.map(item => extractTextFromContent(item)).join(' ')
    }
    return ''
  }

  function appendMessage(msg: Message) {
    setMessages(prev => [...prev, msg])
    queueMicrotask(() => {
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
    })
  }

  // 保存助手消息到后端
  const saveAssistantMessage = async (
    content: React.ReactNode, 
    fallbackText?: string,
    metadata?: Record<string, any>
  ) => {
    if (!conversationId || !userId || !onMessageAdded) return
    
    try {
      // 尝试提取文本内容
      let textContent = extractTextFromContent(content)
      if (!textContent && fallbackText) {
        textContent = fallbackText
      }
      if (!textContent) {
        textContent = 'Assistant response' // 默认文本
      }
      
      await addMessage(userId, conversationId, 'assistant', textContent, metadata)
      onMessageAdded('assistant', textContent)
    } catch (error) {
      console.error('Error saving assistant message:', error)
    }
  }

  // 保存推荐结果（包含完整数据）
  const saveRecommendationResult = async (result: RecommendationResponse) => {
    if (!conversationId || !userId || !onMessageAdded) return
    
    try {
      const textContent = result.restaurants.length > 0
        ? `Found ${result.restaurants.length} restaurant recommendations: ${result.restaurants.map(r => r.name).join(', ')}`
        : 'No recommendations found'
      
      // 在metadata中保存完整的推荐结果数据
      const metadata = {
        type: 'recommendation',
        recommendation_data: result
      }
      
      await addMessage(userId, conversationId, 'assistant', textContent, metadata)
      onMessageAdded('assistant', textContent)
    } catch (error) {
      console.error('Error saving recommendation result:', error)
    }
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

    const userMessage: Message = { role: 'user', content: trimmed }
    appendMessage(userMessage)
    
    // 保存用户消息到后端
    if (conversationId && userId && onMessageAdded) {
      try {
        await addMessage(userId, conversationId, 'user', trimmed)
        onMessageAdded('user', trimmed)
      } catch (error) {
        console.error('Error saving user message:', error)
      }
    }
    
    setInput('')
    setLoading(true)
    setPendingConfirmation(null)
    
    try {
      // 构建对话历史（用于 GPT-4 上下文）
      const conversationHistory = messages
        .filter(m => typeof m.content === 'string')
        .slice(-10)  // 只取最近10条消息
        .map(m => ({
          role: m.role,
          content: typeof m.content === 'string' ? m.content : ''
        }))
      
      // Send query and user_id, let backend intelligently determine intent
      const res: RecommendationResponse = await recommend(trimmed, userId || "default", conversationHistory, conversationId || undefined)
      
      if (res.llm_reply) {
        // GPT-4 的普通对话回复，使用流式显示
        // 立即设置 loading 为 false，隐藏加载占位符对话框
        setLoading(false)
        
        // 不在流式传输开始前创建空消息，而是在第一个chunk到达时创建
        let fullText = ''
        let messageCreated = false
        
        await recommendStream(
          trimmed,
          userId || "default",
          conversationHistory,
          (chunk) => {
            // 第一个chunk到达时创建消息
            if (!messageCreated) {
              messageCreated = true
              const streamingMessage: Message = { 
                role: 'assistant', 
                content: chunk
              }
              appendMessage(streamingMessage)
              fullText = chunk
            } else {
              // 后续chunk更新消息
              fullText += chunk
              setMessages(prev => {
                const newMessages = [...prev]
                const lastMessage = newMessages[newMessages.length - 1]
                if (lastMessage && lastMessage.role === 'assistant') {
                  newMessages[newMessages.length - 1] = {
                    ...lastMessage,
                    content: fullText
                  }
                }
                return newMessages
              })
            }
          },
          (completeText) => {
            // 流式完成，确保消息已创建并更新
            if (!messageCreated) {
              // 如果没有收到任何chunk，至少创建一个消息
              const streamingMessage: Message = { 
                role: 'assistant', 
                content: completeText || ''
              }
              appendMessage(streamingMessage)
            }
            // 保存消息
            if (conversationId && userId && onMessageAdded) {
              saveAssistantMessage(completeText, completeText)
            }
          }
        )
      } else if (res.confirmation_request) {
        // Show confirmation message, but don't show buttons
        const confirmationContent = <div className="confirmation-message">
          <div className="confirmation-text">
            {res.confirmation_request.message}
          </div>
        </div>
        appendMessage({ 
          role: 'assistant', 
          content: confirmationContent
        })
        // 保存确认消息
        saveAssistantMessage(confirmationContent, res.confirmation_request.message)
      } else if (res.thinking_steps) {
        // Start processing, show ProcessingView
        if (res.thinking_steps.length > 0) {
          const taskIdMatch = res.thinking_steps[0].details?.match(/Task ID: (.+)/)
          if (taskIdMatch) {
            setCurrentTaskId(taskIdMatch[1])
            // Show ProcessingView, which will automatically poll and update
            const processingContent = <ProcessingView 
              taskId={taskIdMatch[1]} 
              onAddressClick={handleAddressClick}
              onComplete={(result) => {
                // 当处理完成时，保存完整的推荐结果数据
                saveRecommendationResult(result)
              }}
            />
            appendMessage({ 
              role: 'assistant', 
              content: processingContent
            })
          }
        }
      } else {
        // Display results directly
        const resultsContent = <ResultsView 
          data={res} 
          onAddressClick={handleAddressClick}
        />
        appendMessage({ 
          role: 'assistant', 
          content: resultsContent
        })
        // 保存完整的推荐结果数据
        saveRecommendationResult(res)
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
      {/* Map Modal - Render at top level, ensure floating window displays above all content */}
      {mapRestaurant && (
        <MapModal
          isOpen={!!mapRestaurant}
          onClose={() => setMapRestaurant(null)}
          address={mapRestaurant.address}
          restaurantName={mapRestaurant.name}
          coordinates={mapRestaurant.coordinates}
        />
      )}

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


function ProcessingView({ taskId, onAddressClick, onComplete }: { taskId: string; onAddressClick?: (restaurant: { name: string; address: string; coordinates?: { latitude: number; longitude: number } }) => void; onComplete?: (result: RecommendationResponse) => void }) {
  const [status, setStatus] = useState<TaskStatus | null>(null)
  const [currentStep, setCurrentStep] = useState(0)
  const [displayedSteps, setDisplayedSteps] = useState<ThinkingStep[]>([])
  
  useEffect(() => {
    let intervalId: ReturnType<typeof setInterval> | null = null
    
    const pollStatus = async () => {
      try {
        const taskStatus = await getTaskStatus(taskId)
        setStatus(taskStatus)
        
        // If there are thinking steps, update display
        if (taskStatus.result && taskStatus.result.thinking_steps) {
          setDisplayedSteps(taskStatus.result.thinking_steps)
        }
        
        // Stop polling when task is completed or error occurred
        if (taskStatus.status === 'completed' || taskStatus.status === 'error') {
          if (intervalId) {
            clearInterval(intervalId)
            intervalId = null
          }
          return
        }
      } catch (error) {
        console.error('Error polling status:', error)
      }
    }
    
    intervalId = setInterval(pollStatus, 1000)
    return () => {
      if (intervalId) {
        clearInterval(intervalId)
      }
    }
  }, [taskId])
  
  // Simulate gradual display of thinking steps
  useEffect(() => {
    if (displayedSteps.length > 0 && currentStep < displayedSteps.length) {
      const timer = setTimeout(() => {
        setCurrentStep(prev => prev + 1)
      }, 800) // Display one step every 0.8 seconds for smoother experience
      return () => clearTimeout(timer)
    }
  }, [displayedSteps, currentStep])
  
  // When there are new thinking steps, reset current step
  useEffect(() => {
    if (displayedSteps.length > 0) {
      setCurrentStep(0)
    }
  }, [displayedSteps.length])
  
  // 通知父组件任务完成
  useEffect(() => {
    if (status?.status === 'completed' && status.result && onComplete) {
      onComplete(status.result)
    }
  }, [status?.status, status?.result, onComplete])
  
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
  
  // If task is completed, show results
  if (status.status === 'completed' && status.result) {
    return <ResultsView 
      data={status.result} 
      onAddressClick={onAddressClick || ((restaurant) => {
        console.warn('onAddressClick callback not provided')
      })}
    />
  }
  
  // If task has error, show error
  if (status.status === 'error') {
    return (
      <div className="content" style={{ borderColor: 'var(--error)' }}>
        Error: {status.error || 'Unknown error occurred'}
      </div>
    )
  }
  
  // Show processing progress
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
      
      {/* Display thinking steps */}
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

function ResultsView({ 
  data, 
  onAddressClick 
}: { 
  data: RecommendationResponse
  onAddressClick: (restaurant: { name: string; address: string; coordinates?: { latitude: number; longitude: number } }) => void
}) {

  if (!data?.restaurants?.length) {
    return <div style={{ padding: '20px', textAlign: 'center', color: 'var(--muted)' }}>No recommendations yet. Try adjusting filters or query.</div>
  }

  return (
      <div className="card-grid">
        {data.restaurants.map(r => (
        <div 
          key={r.id} 
          className="card" 
          style={{
            background: 'var(--card-bg)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius-lg)',
            padding: '20px',
            boxShadow: 'var(--shadow-sm)',
            transition: 'all 0.2s ease',
            cursor: 'default'
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.boxShadow = 'var(--shadow-md)'
            e.currentTarget.style.borderColor = 'var(--primary)'
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.boxShadow = 'var(--shadow-sm)'
            e.currentTarget.style.borderColor = 'var(--border)'
          }}
        >
          {/* Header: Name and Price */}
          <div style={{ 
            display: 'flex', 
            justifyContent: 'space-between', 
            alignItems: 'flex-start', 
            marginBottom: 16,
            gap: 12
          }}>
            <div style={{ 
              fontWeight: 600, 
              fontSize: '1.15em', 
              color: 'var(--fg)',
              lineHeight: '1.4',
              flex: 1
            }}>
              {r.name}
            </div>
            {/* Prioritize displaying amount, only show price level if amount is not available */}
            {r.price_per_person_sgd ? (
              <div style={{
                backgroundColor: 'var(--accent)',
                color: '#fff',
                padding: '6px 12px',
                borderRadius: 'var(--radius-sm)',
                fontSize: '0.875em',
                fontWeight: 500,
                whiteSpace: 'nowrap'
              }}>
                {r.price_per_person_sgd} SGD
              </div>
            ) : r.price ? (
              <div style={{
                backgroundColor: 'var(--primary)',
                color: '#fff',
                padding: '6px 12px',
                borderRadius: 'var(--radius-sm)',
                fontSize: '0.875em',
                fontWeight: 500,
                whiteSpace: 'nowrap'
              }}>
                {r.price}
              </div>
            ) : null}
          </div>

          {/* Rating and Reviews */}
          {(r.rating || r.reviews_count) && (
            <div style={{ 
              marginBottom: 12,
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              fontSize: '0.875em',
              color: 'var(--muted)'
            }}>
              {r.rating && (
                <span style={{ 
                  color: 'var(--secondary)', 
                  fontWeight: 600,
                  display: 'flex',
                  alignItems: 'center',
                  gap: 4
                }}>
                  ⭐ <span style={{ color: 'var(--fg)' }}>{r.rating}</span>
                </span>
              )}
              {r.rating && r.reviews_count && <span>·</span>}
              {r.reviews_count && (
                <span>{r.reviews_count.toLocaleString()} reviews</span>
              )}
            </div>
          )}

          {/* Cuisine, Location, Type - Use primary-light background uniformly */}
          <div style={{ 
            marginBottom: 12, 
            fontSize: '0.875em',
            display: 'flex',
            flexWrap: 'wrap',
            gap: 6
          }}>
            {r.cuisine && (
              <span style={{
                backgroundColor: 'var(--primary-light)',
                padding: '4px 10px',
                borderRadius: 'var(--radius-sm)',
                color: 'var(--primary)',
                fontWeight: 500,
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4
              }}>
                <span>🍽️</span>
                <span>{r.cuisine}</span>
              </span>
            )}
            {(r.area || r.location) && (
              <span style={{
                backgroundColor: 'var(--primary-light)',
                padding: '4px 10px',
                borderRadius: 'var(--radius-sm)',
                color: 'var(--primary)',
                fontWeight: 500,
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4
              }}>
                <span>📍</span>
                <span>{r.area || r.location}</span>
              </span>
            )}
            {r.type && (
              <span style={{
                backgroundColor: 'var(--primary-light)',
                padding: '4px 10px',
                borderRadius: 'var(--radius-sm)',
                color: 'var(--primary)',
                fontWeight: 500,
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4
              }}>
                <span>🏪</span>
                <span>{r.type}</span>
              </span>
            )}
          </div>

          {/* Address - Clickable to show map */}
          {r.address && (
            <div style={{ 
              marginBottom: 12, 
              fontSize: '0.875em', 
              color: 'var(--fg-secondary)',
              lineHeight: '1.5',
              display: 'flex',
              alignItems: 'flex-start',
              gap: 6
            }}>
              <span style={{ flexShrink: 0 }}>📍</span>
              <span
                onClick={(e) => {
                  e.preventDefault()
                  e.stopPropagation()
                  if (onAddressClick) {
                    onAddressClick({
                      name: r.name,
                      address: r.address || '',
                      coordinates: r.gps_coordinates
                    })
                  }
                }}
                style={{
                  cursor: 'pointer',
                  textDecoration: 'underline',
                  textDecorationColor: 'var(--primary)',
                  textUnderlineOffset: '2px',
                  transition: 'all 0.2s',
                  color: 'var(--primary)'
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.color = 'var(--primary-hover)'
                  e.currentTarget.style.textDecorationColor = 'var(--primary-hover)'
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.color = 'var(--primary)'
                  e.currentTarget.style.textDecorationColor = 'var(--primary)'
                }}
              >
                {r.address}
              </span>
            </div>
          )}

          {/* Distance and Hours */}
          {(r.distance_or_walk_time || r.open_hours_note) && (
            <div style={{ 
              marginBottom: 12, 
              fontSize: '0.875em', 
              color: 'var(--fg-secondary)',
              display: 'flex',
              flexDirection: 'column',
              gap: 6
            }}>
              {r.distance_or_walk_time && (
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6
                }}>
                  <span>🚶</span>
                  <span>{r.distance_or_walk_time}</span>
                </div>
              )}
              {r.open_hours_note && (
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6
                }}>
                  <span>🕐</span>
                  <span>{r.open_hours_note}</span>
                </div>
              )}
            </div>
          )}

          {/* Flavor Match - Use yellow tones to highlight flavor */}
          {r.flavor_match && r.flavor_match.length > 0 && (
            <div style={{ marginTop: 12, marginBottom: 12 }}>
              <div style={{ 
                fontSize: '0.875em', 
                color: 'var(--fg-secondary)', 
                marginBottom: 6,
                fontWeight: 500,
                display: 'flex',
                alignItems: 'center',
                gap: 6
              }}>
                <span>🌶️</span>
                <span>Flavor</span>
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {r.flavor_match.map((f, i) => (
                  <span key={i} style={{
                    backgroundColor: 'var(--secondary-light)',
                    color: 'var(--primary)',
                    padding: '4px 10px',
                    borderRadius: 'var(--radius-sm)',
                    fontSize: '0.875em',
                    fontWeight: 500
                  }}>
                    {f}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Purpose Match - Use green tones to indicate suitable scenarios */}
          {r.purpose_match && r.purpose_match.length > 0 && (
            <div style={{ marginTop: 12, marginBottom: 12 }}>
              <div style={{ 
                fontSize: '0.875em', 
                color: 'var(--fg-secondary)', 
                marginBottom: 6,
                fontWeight: 500,
                display: 'flex',
                alignItems: 'center',
                gap: 6
              }}>
                <span>👥</span>
                <span>Good for</span>
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {r.purpose_match.map((p, i) => (
                  <span key={i} style={{
                    backgroundColor: 'var(--accent-light)',
                    color: 'var(--accent)',
                    padding: '4px 10px',
                    borderRadius: 'var(--radius-sm)',
                    fontSize: '0.875em',
                    fontWeight: 500
                  }}>
                    {p}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Highlights (legacy support) */}
          {r.highlights && r.highlights.length > 0 && (
            <div style={{ marginTop: 12, marginBottom: 12 }}>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {r.highlights.map((h, i) => (
                  <span key={i} style={{
                    backgroundColor: 'var(--primary-light)',
                    color: 'var(--primary)',
                    padding: '4px 10px',
                    borderRadius: 'var(--radius-sm)',
                    fontSize: '0.875em',
                    fontWeight: 500
                  }}>
                    {h}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Why / Reason */}
          {(r.why || r.reason) && (
            <div style={{ 
              marginTop: 16, 
              paddingTop: 16,
              borderTop: '1px solid var(--border)',
              fontSize: '0.875em',
              lineHeight: '1.6',
              color: 'var(--fg-secondary)'
            }}>
              <div style={{ 
                fontWeight: 500, 
                marginBottom: 8,
                color: 'var(--fg)',
                fontSize: '0.9em',
                display: 'flex',
                alignItems: 'center',
                gap: 6
              }}>
                <span>💡</span>
                <span>Why we recommend</span>
              </div>
              <div>
                {r.why || r.reason}
              </div>
            </div>
          )}

          {/* Phone */}
          {r.phone && (
            <div style={{ 
              marginTop: 12, 
              fontSize: '0.875em', 
              color: 'var(--fg-secondary)',
              display: 'flex',
              alignItems: 'center',
              gap: 6
            }}>
              <span>📞</span>
              <span>{r.phone}</span>
            </div>
          )}

          {/* Sources */}
          {r.sources && Object.keys(r.sources).length > 0 && (
            <div style={{ 
              marginTop: 12, 
              fontSize: '0.8em', 
              color: 'var(--muted)',
              fontStyle: 'italic'
            }}>
              Sources: {Object.keys(r.sources).join(', ')}
            </div>
          )}

          {/* Reference (legacy support) */}
          {r.reference && (
            <div style={{ marginTop: 12 }}>
              <a 
                href={r.reference} 
                target="_blank" 
                rel="noreferrer" 
                style={{ 
                  fontSize: '0.875em',
                  color: 'var(--primary)',
                  textDecoration: 'none',
                  fontWeight: 500
                }}
                onMouseEnter={(e) => e.currentTarget.style.textDecoration = 'underline'}
                onMouseLeave={(e) => e.currentTarget.style.textDecoration = 'none'}
              >
                View Reference →
              </a>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}


