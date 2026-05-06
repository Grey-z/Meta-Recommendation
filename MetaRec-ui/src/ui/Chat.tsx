import React, { useMemo, useRef, useState, useEffect, useCallback } from 'react'
import { recommend, recommendStream, getTaskStatus, getConversation, addMessage } from '../utils/api'
import type { Message, Restaurant, ConversationMessage, InteractionData, RecommendationResponse, ThinkingStep, ConfirmationRequest, TaskStatus } from '../utils/types'
import { MapModal } from './MapModal'
import { FloatingPrompt } from './FloatingPrompt'
import { ChatBubble } from './ChatBubble'
import { PreferenceDisplay as PD2 } from './PreferenceDisplay'

// 欢迎消息常量
const WELCOME_MESSAGE: Message = {
  role: 'assistant',
  content: (
    <div>
      <div className="muted">Welcome to MetaRec.</div>
      <div>I'm your personal <strong>Restaurant Recommender</strong>. How can I help you today?</div>
    </div>
  ),
}

interface HasRestaurants {
    restaurants: Restaurant[]
}
interface HasMessages {
    messages?: ConversationMessage[]
}

interface HasInteractionData {
    interactions?: Record<string, InteractionData>
}


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
  const [messages, setMessages] = useState<Message[]>([WELCOME_MESSAGE])
  const [interactions, setInteractions] = useState<Record<string, InteractionData>>({})

  const [isLoadingHistory, setIsLoadingHistory] = useState(false)
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [currentTaskId, setCurrentTaskId] = useState<string | null>(null)
  const [taskStatus, setTaskStatus] = useState<TaskStatus | null>(null)
  const [isListening, setIsListening] = useState(false)
  const useOnlineAgent = useOnlineAgentProp ?? false // 从 props 获取，默认 false
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const recognitionRef = useRef<any>(null)
  // 跟踪已保存的推荐结果ID，防止重复保存
  const savedRecommendationIds = useRef<Set<string>>(new Set())
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

  // 构建对话历史的辅助函数
  const buildConversationHistory = useCallback(() => {
    return messages
      .filter(m => typeof m.content === 'string')
      .slice(-10)
      .map(m => ({
        role: m.role,
        content: typeof m.content === 'string' ? m.content : ''
      }))
  }, [messages])
  
  const mapConversationMessages = (conversation: HasMessages) => {
    if (conversation.messages && conversation.messages.length > 0) {
        const msg_history = conversation.messages.map(msg => {
            return {
                id: msg.id,
                role: msg.role,
                content: msg.content,
            }
        })
        return msg_history;
    } else {
        return [];
    }
  }

  // 创建ProcessingView的辅助函数
  const createProcessingView = useCallback((taskId: string) => {
    return <ProcessingView 
      taskId={taskId}
      userId={userId || undefined}
      conversationId={conversationId || undefined}
      onAddressClick={handleAddressClick}
      onComplete={() => {}}
    />
  }, [userId, conversationId, handleAddressClick])

  // 处理任务创建的回调函数 (把重复的处理过程模块化)
  const handleTaskCreated = useCallback((taskId: string, thinkingSteps?: ThinkingStep[], source: string = 'unknown') => {
    console.log('[Chat] Task created:', {
      source,
      taskId,
      thinkingSteps
    })
    setCurrentTaskId(taskId)
    appendMessage({ role: 'assistant', content: createProcessingView(taskId) })
  }, [appendMessage, createProcessingView, setCurrentTaskId])

  // 加载历史对话消息
  useEffect(() => {
    const loadHistory = async () => {
      if (!conversationId || !userId) return
      
      setIsLoadingHistory(true)
      try {
        const conversation = await getConversation(userId, conversationId)
        
        if (conversation && conversation.messages && conversation.messages.length > 0) {
          // 初始化已保存的推荐结果ID集合
          const savedIds = new Set<string>()
          
          // 将历史消息转换为Message格式，并恢复推荐结果UI
          
          const historyMessages: Message[] = mapConversationMessages(conversation);
          
          // 更新已保存的推荐结果ID集合
          savedRecommendationIds.current = savedIds
          
          setInteractions(conversation.interactions || {});
          setMessages(historyMessages)
        } else {
          // 如果没有历史消息，显示欢迎消息
          setMessages([WELCOME_MESSAGE])
        }
      } catch (error) {
        console.error('Error loading conversation history:', error)
        // 如果加载失败，显示欢迎消息
        setMessages([WELCOME_MESSAGE])
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
                  onComplete={(result) => {}}
                />
              }
            }
          }
          
          return newMessages
        })

        if (status.status === 'completed' || status.status === 'error') {
          // Task completed or error occurred, stop polling
          // 注意：推荐结果的保存由 ProcessingView 的 onComplete 回调处理，这里不再重复保存
          // 如果 ProcessingView 没有触发 onComplete（比如页面刷新后），则在这里保存
          if (status.status === 'completed' && status.result) {
            // 检查是否已经通过 ProcessingView 保存过（通过防重复机制）
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
  }, [currentTaskId, handleAddressClick, userId, conversationId])

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

  // 处理preference确认的回调函数
  const handlePreferenceConfirm = async (summary: string) => {
    // 添加用户消息
    const userMessage: Message = { role: 'user', content: summary }
    appendMessage(userMessage)
    
    // 保存用户消息到后端
    //await saveUserMessage(summary)
    
    // 发送请求
    setLoading(true)
    const res: Promise<RecommendationResponse> = recommend(
    summary, 
    userId || "default", 
    [], 
    conversationId || undefined, 
    useOnlineAgent
    )
    await handleResponse(res, 'preference_confirm')
    setLoading(false)
  }

  // 创建通用的确认处理函数，可以递归调用自己处理后续的confirm
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
  
async function handleResponse(
    resPromise:  Promise<RecommendationResponse>,
    source: string = 'unknown',
) {

    try {
        const res = await resPromise;

        console.log('[Chat] Recv Response', res)
        
        if (res.messages && res.messages.length > 0) {
            const msg_history = mapConversationMessages(res);
            setMessages(msg_history)
            setInteractions(res.interactions || {});
        } else if (res.llm_reply) {
            appendMessage({ role: 'assistant', content: res.llm_reply })
        } else if (res.confirmation_request) {
            const isGuidanceCase = res.intent === 'confirmation_no';
            // 显示确认消息（如果需要确认用户需求，按钮将在消息下方显示）
            const confirmationContent = <ConfirmationMessageView
              confirmationRequest={res.confirmation_request} // confirmation_request: { message, preferences }
              showPreferences={isGuidanceCase}
              onPreferenceConfirm={isGuidanceCase ? handlePreferenceConfirm : undefined}
            />
            appendMessage({ 
              role: 'assistant', 
              content: confirmationContent
            })

        } else if (res.thinking_steps) {
            if (res.thinking_steps.length > 0) {
              const taskIdMatch = res.thinking_steps[0].details?.match(/Task ID: (.+)/)
              if (taskIdMatch) {
                const taskId = taskIdMatch[1];
                appendMessage({ role: 'assistant', content: createProcessingView(taskId) })
              }
            }
        } else if (res.restaurants && res.restaurants.length > 0) {
            const resultsContent = <ResultsView data={res} onAddressClick={handleAddressClick} />
            appendMessage({ role: 'assistant', content: resultsContent })
        }
    } catch (err: any) {
        appendMessage({ role: 'assistant', content: <div className="content" style={{ borderColor: 'var(--error)' }}>Error: {err?.message}</div> })
    }
}
  
  async function onSend() {
    const trimmed = input.trim()
    if (!trimmed) return

    const userMessage: Message = { role: 'user', content: trimmed }
    appendMessage(userMessage)

    // 保存用户消息到后端

    setInput('')
    setLoading(true)
    const res: Promise<RecommendationResponse> = recommend(trimmed, userId || "default", [], conversationId || undefined, useOnlineAgent)
    await handleResponse(res, 'on_send')
    setLoading(false);
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
           const interaction: InteractionData | undefined = m.id ? interactions[m.id] : undefined;
           if (interaction) {
                var footer: React.ReactNode | null = null;
                const onInteraction = (data: Record<string, any>, source: string) => {
                    const msg = data.message;
                    appendMessage({ role: 'user', content: msg });
                    const query: Record<string, InteractionData> = {}
                    query[m.id as string] = {
                        status: 'fulfilled',
                        data,
                        type: interaction.type,
                    }
                    const res = recommend(query, userId, [], conversationId || undefined, useOnlineAgent)
                    handleResponse(res, source);
                }

                if (interaction.type =='task') {
                    footer = <FloatingPrompt
                        status={<ProcessingView
                                taskId={interaction.data.taskId}
                                conversationId={conversationId || undefined}
                                userId={userId || 'default'}
                            />}
                    />
                } else if (interaction.type =='restaurants') {
                    const r_data: HasRestaurants = {
                        restaurants: (interaction.data?.restaurants || [])
                    }
                    footer = <FloatingPrompt
                        status={
                            <ResultsView 
                                data={r_data}
                                onAddressClick={handleAddressClick}
                            />
                        }
                    />
                } else if (interaction.status == 'fulfilled') {
                    footer = <FloatingPrompt
                        status={interaction.data.message}
                    />
                } else if (interaction.status == 'pending' && interaction.type =='yes_no') {
                    footer = <FloatingPrompt 
                        onConfirm={() => onInteraction({message: interaction.data.yes_message}, 'confirmation_yes')}
                        onConfirmText={interaction.data.yes_label}
                        onNotSatisfied={() => onInteraction({message: interaction.data.no_message}, 'confirmation_no')}
                        onNotSatisfiedText={interaction.data.no_label}
                        onDismiss={() => onInteraction({message: interaction.data.dismiss_message}, 'confirmation_no')}
                    />
                } else if (interaction.status == 'pending' && interaction.type =='preferences') {
                    footer = <PD2
                        preferences={interaction.data.preferences || []}
                        onConfirmText={interaction.data.confirm_label}
                        onConfirm={(data: Record<string, any>) => {
                            const summary = JSON.stringify(data, null, 2);
                            onInteraction({message: '[Preferences Confirmed]', preferences: data}, 'preference_confirm')
                        }}
                    />
                }

                return <ChatBubble key={i} message={m} footer={footer}/>
           } else {
                return <ChatBubble key={i} message={m}/>
           }
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
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'error'>('idle')

  useEffect(() => {
    if (copyState !== 'copied') return
    const timer = window.setTimeout(() => setCopyState('idle'), 1500)
    return () => window.clearTimeout(timer)
  }, [copyState])

  const copyTaskId = async () => {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(taskId)
      } else {
        throw new Error('Clipboard API unavailable')
      }
      setCopyState('copied')
    } catch (error) {
      console.warn('[ProcessingView] Failed to copy task ID:', { taskId, error })
      setCopyState('error')
      window.setTimeout(() => setCopyState('idle'), 2000)
    }
  }

  const taskIdInfo = (
    <div
      style={{
        marginTop: '10px',
        padding: '8px 10px',
        borderRadius: '10px',
        border: '1px solid rgba(194, 122, 54, 0.18)',
        background: 'rgba(255, 250, 244, 0.9)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: '8px',
        flexWrap: 'wrap',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', minWidth: 0 }}>
        <span style={{ color: 'var(--muted)', fontSize: '0.82rem' }}>Task ID</span>
        <code style={{ fontSize: '0.8rem', wordBreak: 'break-all' }}>{taskId}</code>
      </div>
      <button
        type="button"
        onClick={copyTaskId}
        style={{
          border: '1px solid var(--line)',
          background: '#fff',
          color: 'var(--fg)',
          borderRadius: '8px',
          padding: '4px 8px',
          cursor: 'pointer',
          fontSize: '0.8rem',
          whiteSpace: 'nowrap',
        }}
        title="Copy task ID"
      >
        {copyState === 'copied' ? 'Copied' : copyState === 'error' ? 'Copy failed' : 'Copy Task ID'}
      </button>
    </div>
  )
  
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
        {taskIdInfo}
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
      <div>
        <div className="content" style={{ borderColor: 'var(--error)' }}>
          Error: {status.error || 'Unknown error occurred'}
        </div>
        {taskIdInfo}
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
      {taskIdInfo}
      
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
  data: HasRestaurants,
  onAddressClick: (restaurant: { name: string; address: string; coordinates?: { latitude: number; longitude: number } }) => void
}) {

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
