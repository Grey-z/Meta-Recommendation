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
  useOnlineAgent?: boolean
}

export function Chat({ selectedTypes, selectedFlavors, currentModel, chatHistory, conversationId, userId, onMessageAdded, useOnlineAgent: useOnlineAgentProp }: ChatProps): JSX.Element {
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
  const useOnlineAgent = useOnlineAgentProp ?? false // 从 props 获取，默认 false
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const recognitionRef = useRef<any>(null)
  // 悬浮确认按钮状态
  const [floatingConfirmation, setFloatingConfirmation] = useState<{
    onConfirm: () => void
    onNotSatisfied: () => void
  } | null>(null)
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

    const pollTaskStatus = async () => {
      try {
        const status = await getTaskStatus(currentTaskId, userId || undefined, conversationId || undefined)
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
                  userId={userId || undefined}
                  conversationId={conversationId || undefined}
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

        if (status.status === 'completed' || status.status === 'error') {
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

    const interval = setInterval(pollTaskStatus, 1000) // Poll every second
    return () => clearInterval(interval)
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

  // 处理preference确认的回调函数
  const handlePreferenceConfirm = async (summary: string) => {
    // 添加用户消息
    const userMessage: Message = { role: 'user', content: summary }
    appendMessage(userMessage)
    
    // 保存用户消息到后端
    if (conversationId && userId && onMessageAdded) {
      try {
        await addMessage(userId, conversationId, 'user', summary)
        onMessageAdded('user', summary)
      } catch (error) {
        console.error('Error saving user message:', error)
      }
    }
    
    // 发送请求
    setLoading(true)
    try {
      const conversationHistory = messages
        .filter(m => typeof m.content === 'string')
        .slice(-10)
        .map(m => ({
          role: m.role,
          content: typeof m.content === 'string' ? m.content : ''
        }))
      
      const res: RecommendationResponse = await recommend(
        summary, 
        userId || "default", 
        conversationHistory, 
        conversationId || undefined, 
        useOnlineAgent
      )
      
      // 处理响应
      if (res.llm_reply) {
        appendMessage({ role: 'assistant', content: res.llm_reply })
        saveAssistantMessage(res.llm_reply, res.llm_reply)
      } else if (res.confirmation_request) {
        const isGuidanceCase = res.intent === 'confirmation_no'
        const confirmationContent = <ConfirmationMessageView
          confirmationRequest={res.confirmation_request}
          showPreferences={isGuidanceCase}
        />
        appendMessage({ role: 'assistant', content: confirmationContent })
        saveAssistantMessage(confirmationContent, res.confirmation_request.message)
        // 只有需要确认用户需求时才设置悬浮确认按钮
        if (!isGuidanceCase) {
          const handlers = createConfirmationHandlers()
          setFloatingConfirmation(handlers)
        }
      } else if (res.thinking_steps) {
        const taskIdMatch = res.thinking_steps[0]?.details?.match(/Task ID: (.+)/)
        if (taskIdMatch) {
          setCurrentTaskId(taskIdMatch[1])
          appendMessage({ role: 'assistant', content: <ProcessingView taskId={taskIdMatch[1]} userId={userId || undefined} conversationId={conversationId || undefined} onAddressClick={handleAddressClick} onComplete={saveRecommendationResult} /> })
        }
      } else if (res.restaurants && res.restaurants.length > 0) {
        const resultsContent = <ResultsView data={res} onAddressClick={handleAddressClick} />
        appendMessage({ role: 'assistant', content: resultsContent })
        saveRecommendationResult(res)
      }
    } catch (error: any) {
      appendMessage({
        role: 'assistant',
        content: (
          <div className="content" style={{ borderColor: 'var(--error)' }}>
            Failed to process preferences. {error?.message || 'Unknown error'}
          </div>
        ),
      })
    } finally {
      setLoading(false)
    }
  }

  // 创建通用的确认处理函数，可以递归调用自己处理后续的confirm
  const createConfirmationHandlers = useCallback(() => {
    const handleConfirm = async () => {
      setFloatingConfirmation(null) // 隐藏悬浮按钮
      const confirmMessage = "Yes, that's correct"
      const userMessage: Message = { role: 'user', content: confirmMessage }
      appendMessage(userMessage)
      
      // 保存用户消息到后端
      if (conversationId && userId && onMessageAdded) {
        try {
          await addMessage(userId, conversationId, 'user', confirmMessage)
          onMessageAdded('user', confirmMessage)
        } catch (error) {
          console.error('Error saving user message:', error)
        }
      }
      
      setLoading(true)
      try {
        const conversationHistory = messages
          .filter(m => typeof m.content === 'string')
          .slice(-10)
          .map(m => ({
            role: m.role,
            content: typeof m.content === 'string' ? m.content : ''
          }))
        
        const response: RecommendationResponse = await recommend(
          confirmMessage, userId || "default", conversationHistory, conversationId || undefined, useOnlineAgent
        )
        
        if (response.confirmation_request) {
          const isGuidanceCase = response.intent === 'confirmation_no'
          const newContent = <ConfirmationMessageView
            confirmationRequest={response.confirmation_request}
            showPreferences={isGuidanceCase}
            onPreferenceConfirm={isGuidanceCase ? handlePreferenceConfirm : undefined}
          />
          appendMessage({ role: 'assistant', content: newContent })
          saveAssistantMessage(newContent, response.confirmation_request.message)
          // 只有需要确认用户需求时才设置悬浮确认按钮（递归调用自己）
          if (!isGuidanceCase) {
            const handlers = createConfirmationHandlers()
            setFloatingConfirmation(handlers)
          }
        } else if (response.thinking_steps) {
          const taskIdMatch = response.thinking_steps[0]?.details?.match(/Task ID: (.+)/)
          if (taskIdMatch) {
            setCurrentTaskId(taskIdMatch[1])
            appendMessage({ role: 'assistant', content: <ProcessingView taskId={taskIdMatch[1]} userId={userId || undefined} conversationId={conversationId || undefined} onAddressClick={handleAddressClick} onComplete={saveRecommendationResult} /> })
          }
        } else if (response.restaurants && response.restaurants.length > 0) {
          const resultsContent = <ResultsView data={response} onAddressClick={handleAddressClick} />
          appendMessage({ role: 'assistant', content: resultsContent })
          saveRecommendationResult(response)
        } else if (response.llm_reply) {
          appendMessage({ role: 'assistant', content: response.llm_reply })
          saveAssistantMessage(response.llm_reply, response.llm_reply)
        }
      } catch (err: any) {
        appendMessage({ role: 'assistant', content: <div className="content" style={{ borderColor: 'var(--error)' }}>Error: {err?.message}</div> })
      } finally {
        setLoading(false)
      }
    }

    const handleNotSatisfied = async () => {
      setFloatingConfirmation(null) // 隐藏悬浮按钮
      const notSatisfiedMessage = "No, that's not quite right"
      const userMessage: Message = { role: 'user', content: notSatisfiedMessage }
      appendMessage(userMessage)
      
      // 保存用户消息到后端
      if (conversationId && userId && onMessageAdded) {
        try {
          await addMessage(userId, conversationId, 'user', notSatisfiedMessage)
          onMessageAdded('user', notSatisfiedMessage)
        } catch (error) {
          console.error('Error saving user message:', error)
        }
      }
      
      setLoading(true)
      try {
        const conversationHistory = messages
          .filter(m => typeof m.content === 'string')
          .slice(-10)
          .map(m => ({
            role: m.role,
            content: typeof m.content === 'string' ? m.content : ''
          }))
        
        const response: RecommendationResponse = await recommend(
          notSatisfiedMessage, userId || "default", conversationHistory, conversationId || undefined, useOnlineAgent
        )
        
        // 检查是否是confirm no的情况
        const isConfirmNoCase = (response.intent === 'confirmation_no' || 
          (response.intent === 'chat' && response.llm_reply && response.preferences))
        
        if (isConfirmNoCase && response.llm_reply && response.preferences) {
          // 这是confirm no的情况，显示引导消息+preferences（不显示确认按钮）
          const guidanceContent = (
            <div>
              <div style={{ marginBottom: '16px' }}>{response.llm_reply}</div>
              <PreferenceDisplay preferences={response.preferences} onConfirm={handlePreferenceConfirm} />
            </div>
          )
          appendMessage({ role: 'assistant', content: guidanceContent })
          saveAssistantMessage(guidanceContent, response.llm_reply)
        } else if (response.llm_reply) {
          // 普通的llm回复
          appendMessage({ role: 'assistant', content: response.llm_reply })
          saveAssistantMessage(response.llm_reply, response.llm_reply)
        } else if (response.confirmation_request) {
          // 用户更新了偏好，需要重新确认
          const isGuidanceCase = response.intent === 'confirmation_no'
          const newContent = <ConfirmationMessageView
            confirmationRequest={response.confirmation_request}
            showPreferences={isGuidanceCase}
            onPreferenceConfirm={isGuidanceCase ? handlePreferenceConfirm : undefined}
          />
          appendMessage({ role: 'assistant', content: newContent })
          saveAssistantMessage(newContent, response.confirmation_request.message)
          // 只有需要确认用户需求时才设置悬浮确认按钮（递归调用自己）
          if (!isGuidanceCase) {
            const handlers = createConfirmationHandlers()
            setFloatingConfirmation(handlers)
          }
        } else if (response.thinking_steps) {
          const taskIdMatch = response.thinking_steps[0]?.details?.match(/Task ID: (.+)/)
          if (taskIdMatch) {
            setCurrentTaskId(taskIdMatch[1])
            appendMessage({ role: 'assistant', content: <ProcessingView taskId={taskIdMatch[1]} userId={userId || undefined} conversationId={conversationId || undefined} onAddressClick={handleAddressClick} onComplete={saveRecommendationResult} /> })
          }
        } else if (response.restaurants && response.restaurants.length > 0) {
          const resultsContent = <ResultsView data={response} onAddressClick={handleAddressClick} />
          appendMessage({ role: 'assistant', content: resultsContent })
          saveRecommendationResult(response)
        }
      } catch (err: any) {
        appendMessage({ role: 'assistant', content: <div className="content" style={{ borderColor: 'var(--error)' }}>Error: {err?.message}</div> })
      } finally {
        setLoading(false)
      }
    }

    return {
      onConfirm: handleConfirm,
      onNotSatisfied: handleNotSatisfied
    }
  }, [messages, conversationId, userId, onMessageAdded, useOnlineAgent, handlePreferenceConfirm, handleAddressClick, saveRecommendationResult, saveAssistantMessage, appendMessage, setLoading, setCurrentTaskId, setFloatingConfirmation])

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
      console.log('[Chat] Sending request:', {
        query: trimmed,
        userId: userId || "default",
        conversationId: conversationId || undefined,
        useOnlineAgent,
        conversationHistoryLength: conversationHistory?.length || 0
      })
      
      const res: RecommendationResponse = await recommend(trimmed, userId || "default", conversationHistory, conversationId || undefined, useOnlineAgent)
      
      console.log('[Chat] Received response:', {
        type: res.llm_reply ? 'llm_reply' : res.confirmation_request ? 'confirmation' : res.thinking_steps ? 'task_created' : 'unknown',
        hasLlmReply: !!res.llm_reply,
        hasConfirmationRequest: !!res.confirmation_request,
        hasThinkingSteps: !!res.thinking_steps,
        hasRestaurants: !!res.restaurants,
        restaurantsCount: res.restaurants?.length || 0,
        intent: res.intent,
        fullResponse: res
      })
      
      if (res.llm_reply) {
        // GPT-4 的普通对话回复，使用流式显示
        const streamingMessage: Message = { 
          role: 'assistant', 
          content: '' 
        }
        appendMessage(streamingMessage)
        
        // 使用流式显示
        let fullText = ''
        await recommendStream(
          trimmed,
          userId || "default",
          conversationHistory,
          (chunk) => {
            // 逐字更新消息
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
          },
          (completeText) => {
            // 流式完成，保存消息
            if (conversationId && userId && onMessageAdded) {
              saveAssistantMessage(completeText, completeText)
            }
          },
          useOnlineAgent
        )
      } else if (res.confirmation_request) {
        // Show confirmation message with buttons
        // 检测是否是引导用户填写缺失需求的情况（intent为confirmation_no）
        const isGuidanceCase = res.intent === 'confirmation_no'
        
        // 只有需要确认用户需求时才显示确认按钮，引导填写缺失需求时不显示
        if (!isGuidanceCase) {
          // 设置悬浮确认按钮
          setFloatingConfirmation({
          onConfirm: async () => {
            setFloatingConfirmation(null) // 隐藏悬浮按钮
            // 自动发送确认消息
            const confirmMessage = "Yes, that's correct" // 或者使用中文 "是的，正确"
            const userMessage: Message = { role: 'user', content: confirmMessage }
            appendMessage(userMessage)
            
            // 保存用户消息到后端
            if (conversationId && userId && onMessageAdded) {
              try {
                await addMessage(userId, conversationId, 'user', confirmMessage)
                onMessageAdded('user', confirmMessage)
              } catch (error) {
                console.error('Error saving user message:', error)
              }
            }
            
            // 发送确认请求
            setInput(confirmMessage)
            setLoading(true)
            try {
              const conversationHistory = messages
                .filter(m => typeof m.content === 'string')
                .slice(-10)
                .map(m => ({
                  role: m.role,
                  content: typeof m.content === 'string' ? m.content : ''
                }))
              
              const confirmRes: RecommendationResponse = await recommend(
                confirmMessage, 
                userId || "default", 
                conversationHistory, 
                conversationId || undefined, 
                useOnlineAgent
              )
              
              // 处理响应
              if (confirmRes.llm_reply) {
                appendMessage({ role: 'assistant', content: confirmRes.llm_reply })
                saveAssistantMessage(confirmRes.llm_reply, confirmRes.llm_reply)
              } else if (confirmRes.confirmation_request) {
                const handleConfirmClick = async () => {
                  const confirmMsg = "Yes, that's correct"
                  const userMsg: Message = { role: 'user', content: confirmMsg }
                  appendMessage(userMsg)
                  if (conversationId && userId && onMessageAdded) {
                    try {
                      await addMessage(userId, conversationId, 'user', confirmMsg)
                      onMessageAdded('user', confirmMsg)
                    } catch (error) {
                      console.error('Error saving user message:', error)
                    }
                  }
                  setLoading(true)
                  try {
                    const convHistory = messages
                      .filter(m => typeof m.content === 'string')
                      .slice(-10)
                      .map(m => ({
                        role: m.role,
                        content: typeof m.content === 'string' ? m.content : ''
                      }))
                    const response: RecommendationResponse = await recommend(
                      confirmMsg, userId || "default", convHistory, conversationId || undefined, useOnlineAgent
                    )
                    // 处理响应（简化处理）
                    if (response.confirmation_request) {
                      const isGuidanceCase5 = response.intent === 'confirmation_no'
                      const newContent = <ConfirmationMessageView
                        confirmationRequest={response.confirmation_request}
                        showPreferences={isGuidanceCase5}
                        onPreferenceConfirm={isGuidanceCase5 ? handlePreferenceConfirm : undefined}
                      />
                      appendMessage({ role: 'assistant', content: newContent })
                      // 只有需要确认用户需求时才设置悬浮确认按钮
                      if (!isGuidanceCase5) {
                        const handlers = createConfirmationHandlers()
                        setFloatingConfirmation(handlers)
                      }
                    } else if (response.thinking_steps) {
                      const taskIdMatch = response.thinking_steps[0]?.details?.match(/Task ID: (.+)/)
                      if (taskIdMatch) {
                        setCurrentTaskId(taskIdMatch[1])
                        appendMessage({ role: 'assistant', content: <ProcessingView taskId={taskIdMatch[1]} userId={userId || undefined} conversationId={conversationId || undefined} onAddressClick={handleAddressClick} onComplete={saveRecommendationResult} /> })
                      }
                    }
                  } catch (err: any) {
                    appendMessage({ role: 'assistant', content: <div className="content" style={{ borderColor: 'var(--error)' }}>Error: {err?.message}</div> })
                  } finally {
                    setLoading(false)
                  }
                }
                const handleNotSatisfiedClick = async () => {
                  const notSatisfiedMsg = "No, that's not quite right"
                  const userMsg: Message = { role: 'user', content: notSatisfiedMsg }
                  appendMessage(userMsg)
                  if (conversationId && userId && onMessageAdded) {
                    try {
                      await addMessage(userId, conversationId, 'user', notSatisfiedMsg)
                      onMessageAdded('user', notSatisfiedMsg)
                    } catch (error) {
                      console.error('Error saving user message:', error)
                    }
                  }
                  setLoading(true)
                  try {
                    const convHistory = messages
                      .filter(m => typeof m.content === 'string')
                      .slice(-10)
                      .map(m => ({
                        role: m.role,
                        content: typeof m.content === 'string' ? m.content : ''
                      }))
                    const response: RecommendationResponse = await recommend(
                      notSatisfiedMsg, userId || "default", convHistory, conversationId || undefined, useOnlineAgent
                    )
                    // 检查是否是confirm no的情况
                    const isConfirmNoCase = (response.intent === 'confirmation_no' || 
                      (response.intent === 'chat' && response.llm_reply && response.preferences))
                    
                    if (isConfirmNoCase && response.llm_reply && response.preferences) {
                      // 这是confirm no的情况，显示引导消息+preferences（不显示确认按钮）
                      const guidanceContent = (
                        <div>
                          <div style={{ marginBottom: '16px' }}>{response.llm_reply}</div>
                          <PreferenceDisplay preferences={response.preferences} onConfirm={handlePreferenceConfirm} />
                        </div>
                      )
                      appendMessage({ role: 'assistant', content: guidanceContent })
                      saveAssistantMessage(guidanceContent, response.llm_reply)
                    } else if (response.confirmation_request) {
                      // 用户更新了偏好，需要重新确认
                      const isGuidanceCase2 = response.intent === 'confirmation_no'
                      const newContent = <ConfirmationMessageView
                        confirmationRequest={response.confirmation_request}
                        showPreferences={isGuidanceCase2}
                        onPreferenceConfirm={isGuidanceCase2 ? handlePreferenceConfirm : undefined}
                      />
                      appendMessage({ role: 'assistant', content: newContent })
                      // 只有需要确认用户需求时才设置悬浮确认按钮
                      if (!isGuidanceCase2) {
                        const handlers = createConfirmationHandlers()
                        setFloatingConfirmation(handlers)
                      }
                    } else if (response.llm_reply) {
                      appendMessage({ role: 'assistant', content: response.llm_reply })
                    }
                  } catch (err: any) {
                    appendMessage({ role: 'assistant', content: <div className="content" style={{ borderColor: 'var(--error)' }}>Error: {err?.message}</div> })
                  } finally {
                    setLoading(false)
                  }
                }
                // 显示确认消息（按钮将在输入框上方悬浮显示）
                const isGuidanceCase7 = confirmRes.intent === 'confirmation_no'
                const newConfirmationContent = <ConfirmationMessageView
                  confirmationRequest={confirmRes.confirmation_request}
                  showPreferences={isGuidanceCase7}
                  onPreferenceConfirm={isGuidanceCase7 ? handlePreferenceConfirm : undefined}
                />
                appendMessage({ role: 'assistant', content: newConfirmationContent })
                saveAssistantMessage(newConfirmationContent, confirmRes.confirmation_request.message)
                // 只有需要确认用户需求时才设置悬浮确认按钮
                if (!isGuidanceCase7) {
                  const handlers = createConfirmationHandlers()
                  setFloatingConfirmation(handlers)
                }
              } else if (confirmRes.thinking_steps) {
                // 创建任务
                const taskIdMatch = confirmRes.thinking_steps[0]?.details?.match(/Task ID: (.+)/)
                if (taskIdMatch) {
                  const taskId = taskIdMatch[1]
                  setCurrentTaskId(taskId)
                  const processingContent = <ProcessingView 
                    taskId={taskId}
                    userId={userId || undefined}
                    conversationId={conversationId || undefined}
                    onAddressClick={handleAddressClick}
                    onComplete={(result) => {
                      saveRecommendationResult(result)
                    }}
                  />
                  appendMessage({ role: 'assistant', content: processingContent })
                }
              } else if (confirmRes.restaurants && confirmRes.restaurants.length > 0) {
                const resultsContent = <ResultsView 
                  data={confirmRes} 
                  onAddressClick={handleAddressClick}
                />
                appendMessage({ role: 'assistant', content: resultsContent })
                saveRecommendationResult(confirmRes)
              }
            } catch (error: any) {
              appendMessage({
                role: 'assistant',
                content: (
                  <div className="content" style={{ borderColor: 'var(--error)' }}>
                    Failed to process confirmation. {error?.message || 'Unknown error'}
                  </div>
                ),
              })
            } finally {
              setLoading(false)
            }
          },
          onNotSatisfied: async () => {
            setFloatingConfirmation(null) // 隐藏悬浮按钮
            // 自动发送不满意消息
            const notSatisfiedMessage = "No, that's not quite right" // 或者使用中文 "不，不太对"
            const userMessage: Message = { role: 'user', content: notSatisfiedMessage }
            appendMessage(userMessage)
            
            // 保存用户消息到后端
            if (conversationId && userId && onMessageAdded) {
              try {
                await addMessage(userId, conversationId, 'user', notSatisfiedMessage)
                onMessageAdded('user', notSatisfiedMessage)
              } catch (error) {
                console.error('Error saving user message:', error)
              }
            }
            
            // 发送不满意请求
            setLoading(true)
            try {
              const conversationHistory = messages
                .filter(m => typeof m.content === 'string')
                .slice(-10)
                .map(m => ({
                  role: m.role,
                  content: typeof m.content === 'string' ? m.content : ''
                }))
              
              const notSatisfiedRes: RecommendationResponse = await recommend(
                notSatisfiedMessage, 
                userId || "default", 
                conversationHistory, 
                conversationId || undefined, 
                useOnlineAgent
              )
              
              // 处理响应
              // 检查是否是confirm no的情况：intent为confirmation_no或chat，且有llm_reply和preferences
              const isConfirmNoCase = (notSatisfiedRes.intent === 'confirmation_no' || 
                (notSatisfiedRes.intent === 'chat' && notSatisfiedRes.llm_reply && notSatisfiedRes.preferences))
              
              if (isConfirmNoCase && notSatisfiedRes.llm_reply && notSatisfiedRes.preferences) {
                // 这是confirm no的情况，显示引导消息+preferences（不显示确认按钮）
                const guidanceContent = (
                  <div>
                    <div style={{ marginBottom: '16px' }}>{notSatisfiedRes.llm_reply}</div>
                    <PreferenceDisplay preferences={notSatisfiedRes.preferences} onConfirm={handlePreferenceConfirm} />
                  </div>
                )
                appendMessage({ role: 'assistant', content: guidanceContent })
                saveAssistantMessage(guidanceContent, notSatisfiedRes.llm_reply)
              } else if (notSatisfiedRes.llm_reply) {
                // 普通的llm回复
                appendMessage({ role: 'assistant', content: notSatisfiedRes.llm_reply })
                saveAssistantMessage(notSatisfiedRes.llm_reply, notSatisfiedRes.llm_reply)
              } else if (notSatisfiedRes.confirmation_request) {
                // 用户更新了偏好，需要重新确认
                const isGuidanceCase4 = notSatisfiedRes.intent === 'confirmation_no'
                
                // 显示确认消息（如果需要确认用户需求，按钮将在消息下方显示）
                const newConfirmationContent = <ConfirmationMessageView
                  confirmationRequest={notSatisfiedRes.confirmation_request}
                  showPreferences={isGuidanceCase4}
                  onPreferenceConfirm={isGuidanceCase4 ? handlePreferenceConfirm : undefined}
                />
                appendMessage({ role: 'assistant', content: newConfirmationContent })
                saveAssistantMessage(newConfirmationContent, notSatisfiedRes.confirmation_request.message)
                // 只有需要确认用户需求时才设置悬浮确认按钮
                if (!isGuidanceCase4) {
                  const handlers = createConfirmationHandlers()
                  setFloatingConfirmation(handlers)
                }
              } else if (notSatisfiedRes.thinking_steps) {
                const taskIdMatch = notSatisfiedRes.thinking_steps[0]?.details?.match(/Task ID: (.+)/)
                if (taskIdMatch) {
                  const taskId = taskIdMatch[1]
                  setCurrentTaskId(taskId)
                  const processingContent = <ProcessingView 
                    taskId={taskId}
                    userId={userId || undefined}
                    conversationId={conversationId || undefined}
                    onAddressClick={handleAddressClick}
                    onComplete={(result) => {
                      saveRecommendationResult(result)
                    }}
                  />
                  appendMessage({ role: 'assistant', content: processingContent })
                }
              } else if (notSatisfiedRes.restaurants && notSatisfiedRes.restaurants.length > 0) {
                const resultsContent = <ResultsView 
                  data={notSatisfiedRes} 
                  onAddressClick={handleAddressClick}
                />
                appendMessage({ role: 'assistant', content: resultsContent })
                saveRecommendationResult(notSatisfiedRes)
              }
            } catch (error: any) {
              appendMessage({
                role: 'assistant',
                content: (
                  <div className="content" style={{ borderColor: 'var(--error)' }}>
                    Failed to process request. {error?.message || 'Unknown error'}
                  </div>
                ),
              })
            } finally {
              setLoading(false)
            }
          }
        })
        }
        
        // 显示确认消息（如果需要确认用户需求，按钮将在消息下方显示）
        const confirmationContent = <ConfirmationMessageView
          confirmationRequest={res.confirmation_request}
          showPreferences={isGuidanceCase}
          onPreferenceConfirm={isGuidanceCase ? handlePreferenceConfirm : undefined}
        />
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
            const taskId = taskIdMatch[1]
            console.log('[Chat] Task created:', {
              taskId,
              thinkingSteps: res.thinking_steps
            })
            setCurrentTaskId(taskId)
            // Show ProcessingView, which will automatically poll and update
            const processingContent = <ProcessingView 
              taskId={taskId}
              userId={userId || undefined}
              conversationId={conversationId || undefined}
              onAddressClick={handleAddressClick}
              onComplete={(result) => {
                console.log('[Chat] Processing completed:', {
                  taskId,
                  restaurantsCount: result.restaurants?.length || 0,
                  hasThinkingSteps: !!result.thinking_steps,
                  hasConfirmationRequest: !!result.confirmation_request,
                  hasLlmReply: !!result.llm_reply,
                  intent: result.intent,
                  fullResult: result
                })
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
        {messages.map((m, i) => {
          // 检查是否是最后一个助手消息且需要显示悬浮按钮
          const isLastAssistantMessage = m.role === 'assistant' && 
            floatingConfirmation && 
            i === messages.length - 1
          
          return (
            <div key={i} className="bubble" data-role={m.role} style={{ position: 'relative' }}>
              <div className="who">{m.role === 'user' ? 'You' : 'MetaRec'}</div>
              <div className="content">{m.content}</div>
              {/* 悬浮确认按钮 - 显示在确认消息下方 */}
              {isLastAssistantMessage && (
                <div className="floating-confirmation-buttons" style={{
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
                  <button
                    onClick={() => {
                      floatingConfirmation.onConfirm()
                    }}
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
                    Confirm
                  </button>
                  <button
                    onClick={() => {
                      floatingConfirmation.onNotSatisfied()
                    }}
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
                    Not Satisfied
                  </button>
                  <button
                    onClick={() => setFloatingConfirmation(null)}
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
                  </button>
                </div>
              )}
            </div>
          )
        })}

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


// PreferenceDisplay组件：可编辑的偏好信息显示
function PreferenceDisplay({ 
  preferences, 
  onConfirm 
}: { 
  preferences: Record<string, any>
  onConfirm?: (summary: string) => void
}) {
  const RESTAURANT_TYPES = [
    { value: 'casual', label: 'Casual' },
    { value: 'fine-dining', label: 'Fine Dining' },
    { value: 'fast-casual', label: 'Fast Casual' },
    { value: 'street-food', label: 'Street Food' },
    { value: 'buffet', label: 'Buffet' },
    { value: 'cafe', label: 'Cafe' },
  ]

  const FLAVOR_PROFILES = [
    { value: 'spicy', label: 'Spicy' },
    { value: 'savory', label: 'Savory' },
    { value: 'sweet', label: 'Sweet' },
    { value: 'sour', label: 'Sour' },
    { value: 'umami', label: 'Umami' },
    { value: 'mild', label: 'Mild' },
  ]

  const DINING_PURPOSES = [
    { value: 'any', label: 'Any' },
    { value: 'date-night', label: 'Date Night' },
    { value: 'family', label: 'Family' },
    { value: 'business', label: 'Business' },
    { value: 'solo', label: 'Solo' },
    { value: 'friends', label: 'Friends' },
    { value: 'celebration', label: 'Celebration' },
  ]

  const LOCATIONS = [
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
  ]

  // 从preferences初始化状态
  const initialTypes = preferences?.restaurant_types || []
  const initialFlavors = preferences?.flavor_profiles || []
  const initialPurpose = preferences?.dining_purpose || 'any'
  const initialBudget = preferences?.budget_range || {}
  const initialLocation = preferences?.location || 'any'

  // 过滤掉空字符串和无效值
  const normalizeArray = (arr: any): string[] => {
    if (!Array.isArray(arr)) return []
    return arr.filter(item => item && typeof item === 'string' && item.trim() !== '' && item !== 'any')
  }

  const normalizeString = (value: any): string => {
    if (typeof value === 'string' && value.trim() !== '' && value !== 'any') {
      return value
    }
    return 'any'
  }

  const [selectedTypes, setSelectedTypes] = useState<string[]>(normalizeArray(initialTypes))
  const [selectedFlavors, setSelectedFlavors] = useState<string[]>(normalizeArray(initialFlavors))
  const [diningPurpose, setDiningPurpose] = useState<string>(normalizeString(initialPurpose))
  const [budgetMin, setBudgetMin] = useState<string>(initialBudget?.min ? String(initialBudget.min) : '')
  const [budgetMax, setBudgetMax] = useState<string>(initialBudget?.max ? String(initialBudget.max) : '')
  const [location, setLocation] = useState<string>(normalizeString(initialLocation))
  const [locationInput, setLocationInput] = useState<string>('')
  const [showTypeDropdown, setShowTypeDropdown] = useState(false)
  const [showFlavorDropdown, setShowFlavorDropdown] = useState(false)
  const typeDropdownRef = useRef<HTMLDivElement>(null)
  const flavorDropdownRef = useRef<HTMLDivElement>(null)

  // 点击外部关闭下拉菜单
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (typeDropdownRef.current && !typeDropdownRef.current.contains(event.target as Node)) {
        setShowTypeDropdown(false)
      }
      if (flavorDropdownRef.current && !flavorDropdownRef.current.contains(event.target as Node)) {
        setShowFlavorDropdown(false)
      }
    }

    if (showTypeDropdown || showFlavorDropdown) {
      document.addEventListener('mousedown', handleClickOutside)
      return () => {
        document.removeEventListener('mousedown', handleClickOutside)
      }
    }
  }, [showTypeDropdown, showFlavorDropdown])

  const toggleType = (type: string) => {
    setSelectedTypes(prev => 
      prev.includes(type) 
        ? prev.filter(t => t !== type)
        : [...prev, type]
    )
  }

  const toggleFlavor = (flavor: string) => {
    setSelectedFlavors(prev => 
      prev.includes(flavor) 
        ? prev.filter(f => f !== flavor)
        : [...prev, flavor]
    )
  }

  const generateSummary = (): string => {
    const parts: string[] = []
    
    if (selectedTypes.length > 0) {
      const typeLabels = selectedTypes.map(t => RESTAURANT_TYPES.find(rt => rt.value === t)?.label || t)
      parts.push(`restaurant type: ${typeLabels.join(', ')}`)
    }
    
    if (selectedFlavors.length > 0) {
      const flavorLabels = selectedFlavors.map(f => FLAVOR_PROFILES.find(fp => fp.value === f)?.label || f)
      parts.push(`flavor profile: ${flavorLabels.join(', ')}`)
    }
    
    if (diningPurpose !== 'any') {
      const purposeLabel = DINING_PURPOSES.find(p => p.value === diningPurpose)?.label || diningPurpose
      parts.push(`dining purpose: ${purposeLabel}`)
    }
    
    if (budgetMin || budgetMax) {
      if (budgetMin && budgetMax) {
        parts.push(`budget: ${budgetMin}-${budgetMax} SGD per person`)
      } else if (budgetMin) {
        parts.push(`budget: minimum ${budgetMin} SGD per person`)
      } else if (budgetMax) {
        parts.push(`budget: maximum ${budgetMax} SGD per person`)
      }
    }
    
    const finalLocation = locationInput || (location !== 'any' ? location : '')
    if (finalLocation) {
      parts.push(`location: ${finalLocation}`)
    }
    
    return parts.length > 0 
      ? `I want a restaurant with ${parts.join(', ')}.`
      : 'I want a restaurant.'
  }

  const handleConfirm = () => {
    if (onConfirm) {
      const summary = generateSummary()
      onConfirm(summary)
    }
  }

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
        {/* Restaurant Type */}
        <div>
          <label style={{ fontSize: '12px', fontWeight: 500, marginBottom: '6px', display: 'block', color: 'var(--fg-secondary)' }}>Restaurant Type</label>
          <div className="compact-multi-select" style={{ position: 'relative' }}>
            <div className="selected-tags" style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '6px' }}>
              {selectedTypes.map(type => (
                <span key={type} className="tag" onClick={() => toggleType(type)} style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  padding: '4px 8px',
                  background: 'var(--primary-light)',
                  color: 'var(--primary-dark)',
                  borderRadius: '6px',
                  fontSize: '11px',
                  cursor: 'pointer'
                }}>
                  {RESTAURANT_TYPES.find(t => t.value === type)?.label}
                  <span className="tag-remove" style={{ marginLeft: '4px' }}>×</span>
                </span>
              ))}
            </div>
            <div className="dropdown-trigger" onClick={() => setShowTypeDropdown(!showTypeDropdown)} style={{
              padding: '8px 12px',
              border: '1px solid var(--border)',
              borderRadius: '8px',
              cursor: 'pointer',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              background: 'var(--bg)'
            }}>
              <span className={`dropdown-text ${selectedTypes.length === 0 ? 'placeholder' : ''}`} style={{
                color: selectedTypes.length === 0 ? 'var(--muted)' : 'var(--fg)',
                fontSize: '13px'
              }}>
                {selectedTypes.length > 0 ? `${selectedTypes.length} selected` : 'Any'}
              </span>
              <span className="dropdown-arrow" style={{ fontSize: '10px' }}>▼</span>
            </div>
            {showTypeDropdown && (
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
                {RESTAURANT_TYPES.map(type => (
                  <div 
                    key={type.value} 
                    className={`dropdown-option ${selectedTypes.includes(type.value) ? 'selected' : ''}`}
                    onClick={() => toggleType(type.value)}
                    style={{
                      padding: '8px 12px',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '8px',
                      background: selectedTypes.includes(type.value) ? 'var(--primary-light)' : 'transparent'
                    }}
                  >
                    <span className="checkbox" style={{ width: '16px', height: '16px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                      {selectedTypes.includes(type.value) ? '✓' : ''}
                    </span>
                    <span>{type.label}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Flavor Profile */}
        <div>
          <label style={{ fontSize: '12px', fontWeight: 500, marginBottom: '6px', display: 'block', color: 'var(--fg-secondary)' }}>Flavor Profile</label>
          <div className="compact-multi-select" style={{ position: 'relative' }} ref={flavorDropdownRef}>
            <div className="selected-tags" style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '6px' }}>
              {selectedFlavors.map(flavor => (
                <span key={flavor} className="tag" onClick={() => toggleFlavor(flavor)} style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  padding: '4px 8px',
                  background: 'var(--primary-light)',
                  color: 'var(--primary-dark)',
                  borderRadius: '6px',
                  fontSize: '11px',
                  cursor: 'pointer'
                }}>
                  {FLAVOR_PROFILES.find(f => f.value === flavor)?.label}
                  <span className="tag-remove" style={{ marginLeft: '4px' }}>×</span>
                </span>
              ))}
            </div>
            <div className="dropdown-trigger" onClick={() => setShowFlavorDropdown(!showFlavorDropdown)} style={{
              padding: '8px 12px',
              border: '1px solid var(--border)',
              borderRadius: '8px',
              cursor: 'pointer',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              background: 'var(--bg)'
            }}>
              <span className={`dropdown-text ${selectedFlavors.length === 0 ? 'placeholder' : ''}`} style={{
                color: selectedFlavors.length === 0 ? 'var(--muted)' : 'var(--fg)',
                fontSize: '13px'
              }}>
                {selectedFlavors.length > 0 ? `${selectedFlavors.length} selected` : 'Any'}
              </span>
              <span className="dropdown-arrow" style={{ fontSize: '10px' }}>▼</span>
            </div>
            {showFlavorDropdown && (
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
                {FLAVOR_PROFILES.map(flavor => (
                  <div 
                    key={flavor.value} 
                    className={`dropdown-option ${selectedFlavors.includes(flavor.value) ? 'selected' : ''}`}
                    onClick={() => toggleFlavor(flavor.value)}
                    style={{
                      padding: '8px 12px',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '8px',
                      background: selectedFlavors.includes(flavor.value) ? 'var(--primary-light)' : 'transparent'
                    }}
                  >
                    <span className="checkbox" style={{ width: '16px', height: '16px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                      {selectedFlavors.includes(flavor.value) ? '✓' : ''}
                    </span>
                    <span>{flavor.label}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Dining Purpose */}
        <div>
          <label style={{ fontSize: '12px', fontWeight: 500, marginBottom: '6px', display: 'block', color: 'var(--fg-secondary)' }}>Dining Purpose</label>
          <select 
            value={diningPurpose}
            onChange={(e) => setDiningPurpose(e.target.value)}
            style={{
              width: '100%',
              padding: '8px 12px',
              border: '1px solid var(--border)',
              borderRadius: '8px',
              background: 'var(--bg)',
              color: 'var(--fg)',
              fontSize: '13px',
              cursor: 'pointer'
            }}
          >
            {DINING_PURPOSES.map(purpose => (
              <option key={purpose.value} value={purpose.value}>{purpose.label}</option>
            ))}
          </select>
        </div>

        {/* Budget Range */}
        <div>
          <label style={{ fontSize: '12px', fontWeight: 500, marginBottom: '6px', display: 'block', color: 'var(--fg-secondary)' }}>Budget Range (per person)</label>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <input 
              type="number" 
              min={0} 
              step={1} 
              placeholder="Min" 
              value={budgetMin}
              onChange={(e) => setBudgetMin(e.target.value)}
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
              min={0} 
              step={1} 
              placeholder="Max" 
              value={budgetMax}
              onChange={(e) => setBudgetMax(e.target.value)}
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
            <span style={{ color: 'var(--muted)', fontSize: '12px' }}>SGD</span>
          </div>
        </div>

        {/* Location */}
        <div>
          <label style={{ fontSize: '12px', fontWeight: 500, marginBottom: '6px', display: 'block', color: 'var(--fg-secondary)' }}>Location</label>
          <select 
            value={location}
            onChange={(e) => {
              setLocation(e.target.value)
              if (e.target.value !== 'any') {
                setLocationInput('')
              }
            }}
            style={{
              width: '100%',
              padding: '8px 12px',
              border: '1px solid var(--border)',
              borderRadius: '8px',
              background: 'var(--bg)',
              color: 'var(--fg)',
              fontSize: '13px',
              cursor: 'pointer',
              marginBottom: '6px'
            }}
          >
            {LOCATIONS.map(loc => (
              <option key={loc.value} value={loc.value}>{loc.label}</option>
            ))}
          </select>
          <input 
            placeholder="Type a specific address or area (optional)"
            value={locationInput}
            onChange={(e) => {
              setLocationInput(e.target.value)
              if (e.target.value) {
                setLocation('any')
              }
            }}
            style={{
              width: '100%',
              padding: '8px 12px',
              border: '1px solid var(--border)',
              borderRadius: '8px',
              background: 'var(--bg)',
              color: 'var(--fg)',
              fontSize: '13px'
            }}
          />
        </div>

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
            Confirm
          </button>
        )}
      </div>
    </div>
  )
}

// ConfirmationMessageView组件：只显示确认消息（不包含按钮）
function ConfirmationMessageView({ 
  confirmationRequest, 
  showPreferences = false,
  onPreferenceConfirm
}: { 
  confirmationRequest: ConfirmationRequest
  showPreferences?: boolean
  onPreferenceConfirm?: (summary: string) => void
}) {
  return (
    <div className="confirmation-message">
      <div className="confirmation-text">
        {confirmationRequest.message}
      </div>
      {showPreferences && confirmationRequest.preferences && (
        <PreferenceDisplay preferences={confirmationRequest.preferences} onConfirm={onPreferenceConfirm} />
      )}
    </div>
  )
}

function ProcessingView({ taskId, userId, conversationId, onAddressClick, onComplete }: { taskId: string; userId?: string; conversationId?: string; onAddressClick?: (restaurant: { name: string; address: string; coordinates?: { latitude: number; longitude: number } }) => void; onComplete?: (result: RecommendationResponse) => void }) {
  const [status, setStatus] = useState<TaskStatus | null>(null)
  const [currentStep, setCurrentStep] = useState(0)
  const [displayedSteps, setDisplayedSteps] = useState<ThinkingStep[]>([])
  
  useEffect(() => {
    const pollStatus = async () => {
      try {
        const taskStatus = await getTaskStatus(taskId, userId, conversationId)
        console.log('[ProcessingView] Status update:', {
          taskId,
          status: taskStatus.status,
          progress: taskStatus.progress,
          message: taskStatus.message,
          hasResult: !!taskStatus.result,
          resultRestaurantsCount: taskStatus.result?.restaurants?.length || 0,
          resultThinkingStepsCount: taskStatus.result?.thinking_steps?.length || 0,
          fullStatus: taskStatus
        })
        setStatus(taskStatus)
        
        // If there are thinking steps, update display
        if (taskStatus.result && taskStatus.result.thinking_steps) {
          setDisplayedSteps(taskStatus.result.thinking_steps)
        }
      } catch (error) {
        console.error('[ProcessingView] Error polling status:', {
          taskId,
          error
        })
      }
    }
    
    const interval = setInterval(pollStatus, 1000)
    return () => clearInterval(interval)
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
      console.log('[ProcessingView] Task completed, calling onComplete:', {
        taskId,
        restaurantsCount: status.result.restaurants?.length || 0,
        restaurants: status.result.restaurants,
        thinkingSteps: status.result.thinking_steps,
        hasConfirmationRequest: !!status.result.confirmation_request,
        hasLlmReply: !!status.result.llm_reply,
        intent: status.result.intent,
        fullResult: status.result
      })
      onComplete(status.result)
    }
  }, [status?.status, status?.result, onComplete, taskId])
  
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
    console.log('[ProcessingView] Rendering ResultsView:', {
      taskId,
      restaurantsCount: status.result.restaurants?.length || 0,
      restaurants: status.result.restaurants,
      thinkingSteps: status.result.thinking_steps,
      hasConfirmationRequest: !!status.result.confirmation_request,
      hasLlmReply: !!status.result.llm_reply,
      intent: status.result.intent,
      fullResult: status.result
    })
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
  console.log('[ResultsView] Rendering results:', {
    restaurantsCount: data.restaurants?.length || 0,
    restaurants: data.restaurants,
    thinkingSteps: data.thinking_steps,
    hasConfirmationRequest: !!data.confirmation_request,
    hasLlmReply: !!data.llm_reply,
    intent: data.intent,
    preferences: data.preferences,
    fullData: data
  })

  if (!data?.restaurants?.length) {
    console.warn('[ResultsView] No restaurants found:', {
      data,
      restaurantsLength: data?.restaurants?.length,
      restaurants: data?.restaurants
    })
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
            ): null}
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


