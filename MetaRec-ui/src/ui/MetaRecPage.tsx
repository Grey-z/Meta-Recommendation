import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { Rnd } from 'react-rnd'
import { Chat, type BackgroundConversationRequest, type BackgroundRecommendationTask } from './Chat'
import {
  updateConversationPreferences,
  getConversations,
  getConversation,
  createConversation,
  deleteConversation as deleteConversationAPI,
  updateConversation,
  addMessage,
  watchTaskStatus,
  ensureAuthSession,
  login,
  register,
  logout,
  getUserPreferences,
  updatePreferences,
  type AuthResponse,
} from '../utils/api'
import { getDeviceId } from '../utils/deviceId'
import type { ConversationSummary, Conversation, RecommendationResponse, TaskStatus } from '../utils/types'

// 动态背景组件
function AnimatedBackground() {
  const [mousePosition, setMousePosition] = useState({ x: 0, y: 0 })

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      setMousePosition({ x: e.clientX, y: e.clientY })
    }
    window.addEventListener('mousemove', handleMouseMove)
    return () => window.removeEventListener('mousemove', handleMouseMove)
  }, [])

  return (
    <div className="chat-background">
      <div 
        className="chat-gradient-orb" 
        style={{
          left: `${mousePosition.x / window.innerWidth * 100}%`,
          top: `${mousePosition.y / window.innerHeight * 100}%`,
        }}
      />
      <div className="chat-gradient-overlay" />
      <div className="chat-floating-elements">
        <div className="chat-floating-circle chat-circle-1" />
        <div className="chat-floating-circle chat-circle-2" />
        <div className="chat-floating-circle chat-circle-3" />
      </div>
    </div>
  )
}

// Available AI models

// Available service types
const SERVICE_TYPES = [
  {
    value: 'auto',
    label: 'Auto',
    description: 'Automatically detect the recommendation domain from the conversation',
    status: 'active'
  },
  { 
    value: 'restaurant', 
    label: 'RestRec', 
    description: 'Lock to restaurant recommendations and restaurant/place tools',
    status: 'active'
  },
  { 
    value: 'product', 
    label: 'ProductRec', 
    description: 'Lock to product recommendation routing and product/shopping tags',
    status: 'active'
  },
  { 
    value: 'movie', 
    label: 'MovieRec', 
    description: 'Lock to movie recommendation routing and movie tags',
    status: 'active'
  },
  { 
    value: 'music', 
    label: 'MusicRec', 
    description: 'Lock to music recommendation routing and music tags',
    status: 'active'
  },
  { 
    value: 'book', 
    label: 'BookRec', 
    description: 'Lock to book recommendation routing and book tags',
    status: 'active'
  }
]

function serviceValueFromModel(model: string | null | undefined): string {
  const normalized = String(model || '').trim().toLowerCase()
  const match = SERVICE_TYPES.find(service => service.label.toLowerCase() === normalized || service.value === normalized)
  return match?.value || 'auto'
}

function serviceLabelFromValue(value: string): string {
  return SERVICE_TYPES.find(service => service.value === value)?.label || 'Auto'
}

// Chat history interface (兼容旧接口)
interface ChatHistory {
  id: string
  title: string
  model: string
  lastMessage: string
  timestamp: Date
  messages: Array<{ role: 'user' | 'assistant'; content: string }>
}

type TaskNotification = {
  id: string
  taskId?: string
  requestId?: string
  conversationId: string
  kind: 'success' | 'error'
  title: string
  message: string
}

const BACKGROUND_TASK_STORAGE_PREFIX = 'metarec.backgroundTasks'

function backgroundTaskStorageKey(userId: string): string {
  return `${BACKGROUND_TASK_STORAGE_PREFIX}.${userId}`
}

function isTerminalTaskStatus(status?: TaskStatus | null): boolean {
  return status?.status === 'completed' || status?.status === 'error'
}

function shouldPersistBackgroundTask(task: BackgroundRecommendationTask): boolean {
  if (!isTerminalTaskStatus(task.status)) return true
  return !task.resultSaved || !task.notified
}

function recommendationSummaryText(result: RecommendationResponse): string {
  const restaurants = result.restaurants || []
  return restaurants.length > 0
    ? `Found ${restaurants.length} restaurant recommendations: ${restaurants.map(restaurant => restaurant.name).join(', ')}`
    : 'No recommendations found'
}

function extractTaskId(result?: RecommendationResponse | null): string | null {
  const details = result?.thinking_steps?.[0]?.details
  const match = typeof details === 'string' ? details.match(/Task ID: (.+)/) : null
  return match?.[1] || null
}

function backgroundResponseSummaryText(result: RecommendationResponse): string {
  if (result.llm_reply) return result.llm_reply
  if (result.confirmation_request?.message) return result.confirmation_request.message
  return recommendationSummaryText(result)
}

// 通知自动消失时间，以及退出动画时长（需与 CSS .task-notification.is-leaving 动画一致）
const NOTIFICATION_TIMEOUT_MS = 5000
const NOTIFICATION_EXIT_MS = 260

function TaskNotificationCard({
  notification,
  onOpen,
  onDismiss,
}: {
  notification: TaskNotification
  onOpen: (conversationId: string, notificationId: string) => void
  onDismiss: (notificationId: string) => void
}) {
  const [leaving, setLeaving] = useState(false)
  const autoTimerRef = useRef<number | undefined>(undefined)
  const exitTimerRef = useRef<number | undefined>(undefined)

  // 播放退出动画后再真正移除，保证多个通知各自独立淡出
  const requestClose = useCallback(() => {
    if (exitTimerRef.current) return
    window.clearTimeout(autoTimerRef.current)
    setLeaving(true)
    exitTimerRef.current = window.setTimeout(() => onDismiss(notification.id), NOTIFICATION_EXIT_MS)
  }, [notification.id, onDismiss])

  const startAutoTimer = useCallback(() => {
    window.clearTimeout(autoTimerRef.current)
    autoTimerRef.current = window.setTimeout(requestClose, NOTIFICATION_TIMEOUT_MS)
  }, [requestClose])

  useEffect(() => {
    startAutoTimer()
    return () => {
      window.clearTimeout(autoTimerRef.current)
      window.clearTimeout(exitTimerRef.current)
    }
  }, [startAutoTimer])

  return (
    <div
      className={`task-notification ${notification.kind}${leaving ? ' is-leaving' : ''}`}
      role="status"
      // 悬停时暂停自动消失，避免用户正要点击时卡片消失
      onMouseEnter={() => window.clearTimeout(autoTimerRef.current)}
      onMouseLeave={() => { if (!leaving) startAutoTimer() }}
    >
      <div className="task-notification-content">
        <strong>{notification.title}</strong>
        <span>{notification.message}</span>
        {(notification.taskId || notification.requestId) && (
          <code>{notification.taskId || notification.requestId}</code>
        )}
      </div>
      <div className="task-notification-actions">
        <button type="button" onClick={() => onOpen(notification.conversationId, notification.id)}>
          Open
        </button>
        <button type="button" aria-label="Dismiss notification" onClick={requestClose}>
          ×
        </button>
      </div>
    </div>
  )
}

function TaskNotificationTray({
  notifications,
  onOpen,
  onDismiss,
}: {
  notifications: TaskNotification[]
  onOpen: (conversationId: string, notificationId: string) => void
  onDismiss: (notificationId: string) => void
}) {
  if (notifications.length === 0) return null

  return (
    <div className="task-notification-tray" aria-live="polite" aria-label="Recommendation task notifications">
      {notifications.map(notification => (
        <TaskNotificationCard
          key={notification.id}
          notification={notification}
          onOpen={onOpen}
          onDismiss={onDismiss}
        />
      ))}
    </div>
  )
}

// 美式风格的图标列表
const AMERICAN_ICONS = [
  '🍔', '🍕', '🌭', '🍟', '🍗', '🍟', '🍖', '🌮', '🌯', '🥓',
  '🍳', '🥞', '🧇', '🥐', '🥨', '🍩', '🍪', '🧁', '🍰', '🎂',
  '☕', '🥤', '🍺', '🍻', '🥃', '🍷', '🍸', '🍹', '🥂', '🍾',
  '🍎', '🍊', '🍋', '🍌', '🍉', '🍇', '🍓', '🍈', '🍒', '🍑',
  '🥭', '🍍', '🥥', '🥝', '🍅', '🥑', '🥦', '🥬', '🥒', '🌶️',
  '🌽', '🥕', '🥔', '🍠', '🥜', '🌰', '🥜', '🍞', '🥖', '🥯',
  '🧀', '🥚', '🍳', '🥓', '🥞', '🧇', '🥨', '🥯', '🥐', '🍞',
]

// 根据对话ID生成稳定的随机图标
const getChatIcon = (chatId: string): string => {
  // 使用chatId的hash值来选择图标，确保同一个对话总是显示相同的图标
  let hash = 0
  for (let i = 0; i < chatId.length; i++) {
    hash = ((hash << 5) - hash) + chatId.charCodeAt(i)
    hash = hash & hash // Convert to 32bit integer
  }
  const index = Math.abs(hash) % AMERICAN_ICONS.length
  return AMERICAN_ICONS[index]
}

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

export function MetaRecPage(): JSX.Element {
  // 获取设备ID作为用户ID
  const [userId, setUserId] = useState<string>(() => getDeviceId())
  const [authReady, setAuthReady] = useState(false)
  const [authUser, setAuthUser] = useState<AuthResponse['user'] | null>(null)
  const [showAuthPanel, setShowAuthPanel] = useState(false)
  const [authMode, setAuthMode] = useState<'login' | 'register'>('login')
  const [authEmail, setAuthEmail] = useState('')
  const [authPassword, setAuthPassword] = useState('')
  const [authDisplayName, setAuthDisplayName] = useState('')
  const [authError, setAuthError] = useState<string | null>(null)
  const [chatHistories, setChatHistories] = useState<ChatHistory[]>([])
  const [currentChatId, setCurrentChatId] = useState<string | null>(null)
  const currentChatIdRef = useRef<string | null>(null)
  const [backgroundTasks, setBackgroundTasks] = useState<Record<string, BackgroundRecommendationTask>>({})
  const backgroundTasksRef = useRef<Record<string, BackgroundRecommendationTask>>({})
  const [backgroundRequests, setBackgroundRequests] = useState<Record<string, BackgroundConversationRequest>>({})
  const [backgroundTasksReady, setBackgroundTasksReady] = useState(false)
  const [taskNotifications, setTaskNotifications] = useState<TaskNotification[]>([])
  const savingTaskIdsRef = useRef<Set<string>>(new Set())
  const savingRequestIdsRef = useRef<Set<string>>(new Set())
  const [selectedModel, setSelectedModel] = useState<string>('Auto')
  const [showModelDropdown, setShowModelDropdown] = useState(false)
  const [showPreferences, setShowPreferences] = useState(false)
  const [selectedTypes, setSelectedTypes] = useState<string[]>([])
  const [selectedFlavors, setSelectedFlavors] = useState<string[]>([])
  const [showTypeDropdown, setShowTypeDropdown] = useState(false)
  const [showFlavorDropdown, setShowFlavorDropdown] = useState(false)
  const [isLoadingConversations, setIsLoadingConversations] = useState(true)
  const isCreatingDefaultChatRef = useRef(false) // 使用 ref 来跟踪是否正在创建默认对话
  const hasInitializedRef = useRef(false) // 跟踪是否已经初始化过
  
  // 检测是否是移动设备（屏幕宽度小于768px）
  const isMobileDevice = () => {
    if (typeof window === 'undefined') return false
    return window.innerWidth < 768
  }

  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => isMobileDevice())
  const [sidebarWidth, setSidebarWidth] = useState<number>(() => {
    const saved = localStorage.getItem('sidebarWidth')
    return saved ? parseInt(saved, 10) : 280
  }) // 侧边栏宽度状态
  const [isResizingSidebar, setIsResizingSidebar] = useState(false) // 是否正在调整侧边栏大小
  // 跟踪移动端视口（随窗口尺寸变化更新），用于让浮层/面板自适应而不溢出
  const [isMobileViewport, setIsMobileViewport] = useState(() => isMobileDevice())

  useEffect(() => {
    const handleResize = () => setIsMobileViewport(window.innerWidth < 768)
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [])

  // 保存侧边栏宽度到localStorage
  useEffect(() => {
    localStorage.setItem('sidebarWidth', sidebarWidth.toString())
  }, [sidebarWidth])
  const [selectedServiceType, setSelectedServiceType] = useState<string>('auto')
  const [showServiceDropdown, setShowServiceDropdown] = useState(false)
  // 各自定义下拉菜单的容器引用，用于点击/触摸外部时关闭
  const serviceDropdownRef = useRef<HTMLDivElement>(null)
  const typeDropdownRef = useRef<HTMLDivElement>(null)
  const flavorDropdownRef = useRef<HTMLDivElement>(null)
  const [isSubmittingPreferences, setIsSubmittingPreferences] = useState(false)

  // 点击/触摸下拉菜单以外的区域时关闭对应下拉（偏好编辑等自定义下拉）
  useEffect(() => {
    if (!showServiceDropdown && !showTypeDropdown && !showFlavorDropdown) return
    const handlePointerOutside = (event: Event) => {
      const target = event.target as Node
      if (serviceDropdownRef.current && !serviceDropdownRef.current.contains(target)) {
        setShowServiceDropdown(false)
      }
      if (typeDropdownRef.current && !typeDropdownRef.current.contains(target)) {
        setShowTypeDropdown(false)
      }
      if (flavorDropdownRef.current && !flavorDropdownRef.current.contains(target)) {
        setShowFlavorDropdown(false)
      }
    }
    document.addEventListener('mousedown', handlePointerOutside)
    document.addEventListener('touchstart', handlePointerOutside)
    return () => {
      document.removeEventListener('mousedown', handlePointerOutside)
      document.removeEventListener('touchstart', handlePointerOutside)
    }
  }, [showServiceDropdown, showTypeDropdown, showFlavorDropdown])
  const [isLoadingPreferences, setIsLoadingPreferences] = useState(false)
  const [useOnlineAgent, setUseOnlineAgent] = useState(true) // Agent 模式开关，默认 online
  // show preference面板的位置和大小状态
  const [preferencePanelSize, setPreferencePanelSize] = useState(() => {
    const saved = localStorage.getItem('preferencePanelSize')
    if (saved) {
      try {
        return JSON.parse(saved)
      } catch {
        return { width: 600, height: 600 }
      }
    }
    return { width: 600, height: 600 }
  })
  const [preferencePanelPosition, setPreferencePanelPosition] = useState(() => {
    const saved = localStorage.getItem('preferencePanelPosition')
    if (saved) {
      try {
        return JSON.parse(saved)
      } catch {
        return { x: 0, y: 0 }
      }
    }
    return { x: 0, y: 0 }
  })
  
  // 保存preference面板位置和大小到localStorage
  useEffect(() => {
    localStorage.setItem('preferencePanelSize', JSON.stringify(preferencePanelSize))
  }, [preferencePanelSize])
  
  useEffect(() => {
    localStorage.setItem('preferencePanelPosition', JSON.stringify(preferencePanelPosition))
  }, [preferencePanelPosition])
  
  // 当showPreferences打开时，如果没有保存的位置，则计算居中位置
  useEffect(() => {
    if (showPreferences) {
      const saved = localStorage.getItem('preferencePanelPosition')
      if (!saved || (preferencePanelPosition.x === 0 && preferencePanelPosition.y === 0)) {
        const centerX = (window.innerWidth - preferencePanelSize.width) / 2
        const centerY = (window.innerHeight - preferencePanelSize.height) / 2
        setPreferencePanelPosition({ x: centerX, y: centerY })
      }
    }
  }, [showPreferences])
  // 偏好设置相关状态
  const [diningPurpose, setDiningPurpose] = useState<string>('any')
  const [budgetMin, setBudgetMin] = useState<string>('')
  const [budgetMax, setBudgetMax] = useState<string>('')
  const [locationSelect, setLocationSelect] = useState<string>('any')
  const [locationInput, setLocationInput] = useState<string>('')
  // 编辑标题相关状态
  const [editingChatId, setEditingChatId] = useState<string | null>(null)
  const [editingTitle, setEditingTitle] = useState<string>('')
  const editInputRef = useRef<HTMLInputElement>(null)

  // 设置页面标题和favicon
  useEffect(() => {
    document.title = 'MetaRec — Restaurant Recommender'
    
    // Update favicon for chat page
    const updateFavicon = (href: string) => {
      let link = document.querySelector("link[rel~='icon']") as HTMLLinkElement
      if (!link) {
        link = document.createElement('link')
        link.rel = 'icon'
        document.getElementsByTagName('head')[0].appendChild(link)
      }
      link.href = href
    }
    updateFavicon('/assets/MR_orange_round.png')
  }, [])

  useEffect(() => {
    currentChatIdRef.current = currentChatId
  }, [currentChatId])

  useEffect(() => {
    backgroundTasksRef.current = backgroundTasks
  }, [backgroundTasks])

  useEffect(() => {
    if (!authReady || !userId) return
    setBackgroundTasksReady(false)
    try {
      const raw = window.localStorage.getItem(backgroundTaskStorageKey(userId))
      const parsed = raw ? JSON.parse(raw) : []
      const tasks = Array.isArray(parsed) ? parsed : Object.values(parsed || {})
      const scopedTasks = (tasks as BackgroundRecommendationTask[])
        .filter(task => task && task.userId === userId && task.taskId && task.conversationId)
        .filter(shouldPersistBackgroundTask)
      const next = Object.fromEntries(scopedTasks.map(task => [task.taskId, task]))
      setBackgroundTasks(next)
    } catch (error) {
      console.warn('[MetaRecPage] Failed to restore background tasks:', error)
      setBackgroundTasks({})
    } finally {
      setBackgroundTasksReady(true)
    }
  }, [authReady, userId])

  useEffect(() => {
    if (!backgroundTasksReady || !userId) return
    const tasksToPersist = Object.values(backgroundTasks).filter(shouldPersistBackgroundTask)
    try {
      window.localStorage.setItem(backgroundTaskStorageKey(userId), JSON.stringify(tasksToPersist))
    } catch (error) {
      console.warn('[MetaRecPage] Failed to persist background tasks:', error)
    }
  }, [backgroundTasks, backgroundTasksReady, userId])

  useEffect(() => {
    let cancelled = false

    const bootstrapAuth = async () => {
      try {
        const auth = await ensureAuthSession(getDeviceId())
        if (cancelled) return
        applyAuth(auth)
        setAuthReady(true)
      } catch (error: any) {
        if (cancelled) return
        setAuthError(error?.message || 'Authentication failed')
        setAuthReady(true)
      }
    }

    bootstrapAuth()
    return () => {
      cancelled = true
    }
  }, [])

  // 监听窗口大小变化，自动调整侧边栏状态（仅在初始加载后）
  useEffect(() => {
    const handleResize = () => {
      // 只在窗口大小跨越移动/桌面边界时自动调整
      const isMobile = window.innerWidth < 768
      // 如果从桌面切换到移动，自动收起；从移动切换到桌面，自动展开
      if (isMobile && !sidebarCollapsed) {
        setSidebarCollapsed(true)
      } else if (!isMobile && sidebarCollapsed) {
        // 可选：从移动切换到桌面时自动展开（如果用户没有手动操作过）
        // 这里我们保持用户的选择，不自动展开
      }
    }

    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [sidebarCollapsed])

  // 从后端加载对话历史列表
  const loadConversations = async () => {
    setIsLoadingConversations(true)
    try {
      const summaries = await getConversations(userId)
      
      // 转换为ChatHistory格式
      const histories: ChatHistory[] = summaries.map(summary => ({
        id: summary.id,
        title: summary.title,
        model: summary.model,
        lastMessage: summary.last_message,
        timestamp: new Date(summary.timestamp),
        messages: [] // 摘要不包含完整消息
      }))
      
      setChatHistories(histories)
      
      // 如果没有对话记录，创建一个起始对话（防止重复创建）
      if (histories.length === 0 && !isCreatingDefaultChatRef.current) {
        isCreatingDefaultChatRef.current = true // 设置标志，防止重复创建
        
        try {
          // 创建对话前再次检查，防止并发请求
          const doubleCheckSummaries = await getConversations(userId)
          if (doubleCheckSummaries.length > 0) {
            // 如果再次检查时发现有对话了，说明已经有其他请求创建了
            const doubleCheckHistories: ChatHistory[] = doubleCheckSummaries.map(summary => ({
              id: summary.id,
              title: summary.title,
              model: summary.model,
              lastMessage: summary.last_message,
              timestamp: new Date(summary.timestamp),
              messages: []
            }))
            setChatHistories(doubleCheckHistories)
            setCurrentChatId(doubleCheckHistories[0].id)
            setSelectedModel(doubleCheckHistories[0].model)
            setSelectedServiceType(serviceValueFromModel(doubleCheckHistories[0].model))
            isCreatingDefaultChatRef.current = false
            return
          }
          
          const newConversation = await createConversation(userId, {
            title: 'Welcome to MetaRec',
            model: selectedModel
          })
          
          const newChat: ChatHistory = {
            id: newConversation.id,
            title: newConversation.title,
            model: newConversation.model,
            lastMessage: newConversation.last_message,
            timestamp: new Date(newConversation.timestamp),
            messages: []
          }
          
          setChatHistories([newChat])
          setCurrentChatId(newChat.id)
          setSelectedModel(newChat.model)
          setSelectedServiceType(serviceValueFromModel(newChat.model))
        } catch (createError) {
          console.error('Error creating default conversation:', createError)
          // 如果创建失败，至少设置一个空数组，避免无限循环
          setChatHistories([])
        } finally {
          isCreatingDefaultChatRef.current = false // 重置标志
        }
      } else if (histories.length > 0 && !currentChatId) {
        // 如果有对话，默认选择第一个
        setCurrentChatId(histories[0].id)
        setSelectedModel(histories[0].model)
        setSelectedServiceType(serviceValueFromModel(histories[0].model))
      }
    } catch (error) {
      console.error('Error loading conversations:', error)
      // 如果加载失败，创建一个默认对话
      createNewChat()
    } finally {
      setIsLoadingConversations(false)
    }
  }

  // 初始加载对话历史（只执行一次）
  useEffect(() => {
    if (!authReady) {
      return
    }
    // 如果已经初始化过，跳过（防止 StrictMode 重复执行）
    if (hasInitializedRef.current) {
      return
    }
    
    hasInitializedRef.current = true
    loadConversations()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authReady, userId]) // userId comes from auth bootstrap

  const createNewChat = async () => {
    try {
      const newConversation = await createConversation(userId, {
        title: 'New Chat',
        model: selectedModel
      })
      
      const newChat: ChatHistory = {
        id: newConversation.id,
        title: newConversation.title,
        model: newConversation.model,
        lastMessage: newConversation.last_message,
        timestamp: new Date(newConversation.timestamp),
        messages: []
      }
      
      setChatHistories(prev => [newChat, ...prev])
      setCurrentChatId(newChat.id)
      setSelectedModel(newChat.model)
      setSelectedServiceType(serviceValueFromModel(newChat.model))
    } catch (error) {
      console.error('Error creating new chat:', error)
      alert('Failed to create new chat. Please try again.')
    }
  }

  const updateChatSummary = useCallback((chatId: string, lastMessage: string) => {
    setChatHistories(prev => prev.map(chat => (
      chat.id === chatId
        ? { ...chat, lastMessage, timestamp: new Date() }
        : chat
    )))
  }, [])

  const registerBackgroundTask = useCallback((task: BackgroundRecommendationTask) => {
    setBackgroundTasks(prev => {
      const existing = prev[task.taskId]
      const nextTask: BackgroundRecommendationTask = {
        ...existing,
        ...task,
        status: existing?.status || task.status || null,
        resultSaved: existing?.resultSaved || task.resultSaved || false,
        notified: existing?.notified || task.notified || false,
        updatedAt: new Date().toISOString(),
      }
      return { ...prev, [task.taskId]: nextTask }
    })
  }, [])

  const markBackgroundTask = useCallback((taskId: string, updates: Partial<BackgroundRecommendationTask>) => {
    setBackgroundTasks(prev => {
      const existing = prev[taskId]
      if (!existing) return prev
      return {
        ...prev,
        [taskId]: {
          ...existing,
          ...updates,
          updatedAt: new Date().toISOString(),
        },
      }
    })
  }, [])

  const registerBackgroundRequest = useCallback((request: BackgroundConversationRequest) => {
    setBackgroundRequests(prev => {
      const existing = prev[request.requestId]
      const nextRequest: BackgroundConversationRequest = {
        ...existing,
        ...request,
        status: request.status || existing?.status || 'pending',
        resultSaved: request.resultSaved ?? existing?.resultSaved ?? false,
        notified: request.notified ?? existing?.notified ?? false,
        updatedAt: new Date().toISOString(),
      }
      return { ...prev, [request.requestId]: nextRequest }
    })
  }, [])

  const markBackgroundRequest = useCallback((requestId: string, updates: Partial<BackgroundConversationRequest>) => {
    setBackgroundRequests(prev => {
      const existing = prev[requestId]
      if (!existing) return prev
      return {
        ...prev,
        [requestId]: {
          ...existing,
          ...updates,
          updatedAt: new Date().toISOString(),
        },
      }
    })
  }, [])

  const dismissTaskNotification = useCallback((notificationId: string) => {
    setTaskNotifications(prev => prev.filter(notification => notification.id !== notificationId))
  }, [])

  const addTaskNotification = useCallback((notification: TaskNotification) => {
    setTaskNotifications(prev => {
      if (prev.some(existing => existing.id === notification.id)) return prev
      return [notification, ...prev].slice(0, 4)
    })
  }, [])

  const saveCompletedBackgroundTask = useCallback(async (
    task: BackgroundRecommendationTask,
    status: TaskStatus,
  ) => {
    if (!status.result || savingTaskIdsRef.current.has(task.taskId)) return
    savingTaskIdsRef.current.add(task.taskId)
    const resultMessageId = task.resultMessageId || `task-result-${task.taskId}`
    try {
      const conversation = await getConversation(task.userId, task.conversationId)
      const alreadySaved = conversation.messages?.some(message => (
        message.id === resultMessageId
        || message.metadata?.message_id === resultMessageId
        || message.metadata?.task_id === task.taskId
      ))
      if (!alreadySaved) {
        const result = status.result
        const textContent = recommendationSummaryText(result)
        const metadata = {
          type: 'recommendation',
          recommendation_data: result,
          message_id: resultMessageId,
          branch_id: task.branchId,
          task_id: task.taskId,
          source: 'background_task',
          ...(task.parentMessageId ? { parent_message_id: task.parentMessageId } : {}),
        }
        await addMessage(task.userId, task.conversationId, 'assistant', textContent, metadata)
        updateChatSummary(task.conversationId, textContent)
      }
      const shouldNotify = currentChatIdRef.current !== task.conversationId
      markBackgroundTask(task.taskId, {
        status,
        resultSaved: true,
        notified: shouldNotify ? task.notified : true,
        resultMessageId,
      })
      if (shouldNotify && !task.notified) {
        addTaskNotification({
          id: `complete-${task.taskId}`,
          taskId: task.taskId,
          conversationId: task.conversationId,
          kind: 'success',
          title: 'Recommendation ready',
          message: 'A previous recommendation task has finished.',
        })
        markBackgroundTask(task.taskId, { notified: true })
      }
    } catch (error) {
      console.error('[MetaRecPage] Failed to save completed background task:', { taskId: task.taskId, error })
      markBackgroundTask(task.taskId, {
        status,
        error: error instanceof Error ? error.message : String(error),
      })
    } finally {
      savingTaskIdsRef.current.delete(task.taskId)
    }
  }, [addTaskNotification, markBackgroundTask, updateChatSummary])

  const saveCompletedBackgroundRequest = useCallback(async (request: BackgroundConversationRequest) => {
    const result = request.result
    if (!result || request.resultSaved || savingRequestIdsRef.current.has(request.requestId)) return
    savingRequestIdsRef.current.add(request.requestId)
    const resultMessageId = request.resultMessageId || `request-result-${request.requestId}`

    try {
      const taskId = extractTaskId(result)
      if (taskId) {
        registerBackgroundTask({
          taskId,
          userId: request.userId,
          conversationId: request.conversationId,
          branchId: request.branchId,
          parentMessageId: request.userMessageId || request.parentMessageId || null,
          processingMessageId: `processing-${taskId}`,
          source: request.source ? `${request.source}_request_result` : 'request_result',
          createdAt: new Date().toISOString(),
          status: {
            task_id: taskId,
            status: 'pending',
            progress: 0,
            message: 'Task created',
            result: null,
            error: null,
            metadata: { branch_id: request.branchId },
          },
          resultSaved: false,
          notified: false,
        })
        markBackgroundRequest(request.requestId, {
          status: 'completed',
          resultSaved: true,
          notified: true,
          resultMessageId,
        })
        return
      }

      const conversation = await getConversation(request.userId, request.conversationId)
      const alreadySaved = conversation.messages?.some(message => (
        message.id === resultMessageId
        || message.metadata?.message_id === resultMessageId
        || message.metadata?.request_id === request.requestId
      ))
      if (!alreadySaved) {
        const textContent = backgroundResponseSummaryText(result)
        const parentMessageId = request.userMessageId || request.parentMessageId || null
        const metadata: Record<string, any> = {
          message_id: resultMessageId,
          branch_id: request.branchId,
          request_id: request.requestId,
          source: 'background_request',
          ...(parentMessageId ? { parent_message_id: parentMessageId } : {}),
          ...(result.hitl_state ? { hitl_state: result.hitl_state } : {}),
          ...(result.domain ? { domain: result.domain } : {}),
        }

        if (result.confirmation_request) {
          const hitlState = result.hitl_state || {
            node: 'collect_confirm_preferences',
            status: 'awaiting_confirmation',
            intent: result.intent || 'query',
            preferences: result.confirmation_request.preferences || result.preferences || {},
            needs_confirmation: result.confirmation_request.needs_confirmation ?? true,
            confirmation_request: result.confirmation_request,
          }
          metadata.type = 'confirmation'
          metadata.confirmation_request = result.confirmation_request
          metadata.hitl_state = hitlState
          metadata.show_preferences = result.intent === 'confirmation_no'
        } else if (!result.llm_reply && Array.isArray(result.restaurants)) {
          metadata.type = 'recommendation'
          metadata.recommendation_data = result
        }

        await addMessage(request.userId, request.conversationId, 'assistant', textContent, metadata)
        updateChatSummary(request.conversationId, textContent)
      }

      const shouldNotify = currentChatIdRef.current !== request.conversationId
      markBackgroundRequest(request.requestId, {
        status: 'completed',
        resultSaved: true,
        notified: shouldNotify ? request.notified : true,
        resultMessageId,
      })
      if (shouldNotify && !request.notified) {
        addTaskNotification({
          id: `request-complete-${request.requestId}`,
          requestId: request.requestId,
          conversationId: request.conversationId,
          kind: 'success',
          title: 'Conversation reply ready',
          message: 'A previous conversation reply has finished.',
        })
        markBackgroundRequest(request.requestId, { notified: true })
      }
    } catch (error) {
      console.error('[MetaRecPage] Failed to save completed background request:', { requestId: request.requestId, error })
      markBackgroundRequest(request.requestId, {
        status: 'error',
        error: error instanceof Error ? error.message : String(error),
      })
    } finally {
      savingRequestIdsRef.current.delete(request.requestId)
    }
  }, [addTaskNotification, markBackgroundRequest, registerBackgroundTask, updateChatSummary])

  const completeBackgroundRequest = useCallback((request: BackgroundConversationRequest) => {
    registerBackgroundRequest(request)
    if (!request.resultSaved) {
      void saveCompletedBackgroundRequest(request)
    }
  }, [registerBackgroundRequest, saveCompletedBackgroundRequest])

  const failBackgroundRequest = useCallback((request: BackgroundConversationRequest) => {
    registerBackgroundRequest(request)
    if (request.notified) return
    addTaskNotification({
      id: `request-error-${request.requestId}`,
      requestId: request.requestId,
      conversationId: request.conversationId,
      kind: 'error',
      title: 'Conversation request failed',
      message: request.error || 'A previous conversation request failed.',
    })
    markBackgroundRequest(request.requestId, { notified: true })
  }, [addTaskNotification, markBackgroundRequest, registerBackgroundRequest])

  const handleErroredBackgroundTask = useCallback((task: BackgroundRecommendationTask, status: TaskStatus) => {
    markBackgroundTask(task.taskId, {
      status,
      notified: true,
      error: status.error || status.message || 'Task failed',
    })
    if (!task.notified) {
      addTaskNotification({
        id: `error-${task.taskId}`,
        taskId: task.taskId,
        conversationId: task.conversationId,
        kind: 'error',
        title: 'Recommendation failed',
        message: status.error || status.message || 'A previous recommendation task failed.',
      })
    }
  }, [addTaskNotification, markBackgroundTask])

  // Watch in-flight background tasks via a live SSE stream (watchTaskStatus),
  // which falls back to polling when streaming is unavailable. Each task gets one
  // watcher; a lightweight reconcile tick discovers newly-created tasks and tears
  // down watchers once a task has fully settled (result saved / error notified).
  useEffect(() => {
    if (!authReady || !backgroundTasksReady || !userId) return
    let cancelled = false
    const watchers = new Map<string, () => void>()

    const applyStatus = (task: BackgroundRecommendationTask, status: TaskStatus) => {
      if (cancelled) return
      markBackgroundTask(task.taskId, { status })
      if (status.status === 'completed' && status.result) {
        void saveCompletedBackgroundTask({ ...task, status }, status)
      } else if (status.status === 'error') {
        handleErroredBackgroundTask({ ...task, status }, status)
      }
    }

    const stopWatcher = (taskId: string) => {
      const close = watchers.get(taskId)
      if (close) { close(); watchers.delete(taskId) }
    }

    const reconcile = () => {
      if (cancelled) return
      const tasks = Object.values(backgroundTasksRef.current).filter(task => (
        task.userId === userId
        && task.conversationId
        && !(
          task.status?.status === 'completed'
          && task.resultSaved
          && task.notified
        )
        && !(task.status?.status === 'error' && task.notified)
      ))
      const liveIds = new Set(tasks.map(task => task.taskId))
      for (const taskId of [...watchers.keys()]) {
        if (!liveIds.has(taskId)) stopWatcher(taskId)
      }
      for (const task of tasks) {
        const conversationId = task.conversationId
        if (!conversationId) continue
        const settledStatus = task.status?.status
        if (settledStatus === 'completed' || settledStatus === 'error') {
          // Terminal but not fully persisted/notified yet — retry the side effect
          // directly (idempotent) instead of reopening a stream for it.
          stopWatcher(task.taskId)
          applyStatus(task, task.status as TaskStatus)
          continue
        }
        if (watchers.has(task.taskId)) continue
        const close = watchTaskStatus(task.taskId, task.userId, conversationId, {
          onStatus: (status) => applyStatus(task, status),
          onSettled: () => stopWatcher(task.taskId),
        })
        watchers.set(task.taskId, close)
      }
    }

    reconcile()
    const interval = window.setInterval(reconcile, 1000)
    return () => {
      cancelled = true
      window.clearInterval(interval)
      for (const taskId of [...watchers.keys()]) stopWatcher(taskId)
    }
  }, [
    authReady,
    backgroundTasksReady,
    handleErroredBackgroundTask,
    markBackgroundTask,
    saveCompletedBackgroundTask,
    userId,
  ])

  // 从当前用户 Profile 加载偏好设置；conversation 只保留当前运行上下文快照
  const loadConversationPreferences = async () => {
    if (!userId) {
      setSelectedTypes([])
      setSelectedFlavors([])
      setDiningPurpose('any')
      setBudgetMin('20')
      setBudgetMax('60')
      setLocationSelect('any')
      setLocationInput('')
      return
    }
    
    setIsLoadingPreferences(true)
    try {
      const result = await getUserPreferences(userId)
      const prefs = result.preferences || {}
      
      // 设置餐厅类型
      if (prefs.restaurant_types && Array.isArray(prefs.restaurant_types) && prefs.restaurant_types.length > 0 && prefs.restaurant_types[0] !== 'any') {
        setSelectedTypes(prefs.restaurant_types)
      } else {
        setSelectedTypes([])
      }
      
      // 设置口味偏好
      if (prefs.flavor_profiles && Array.isArray(prefs.flavor_profiles) && prefs.flavor_profiles.length > 0 && prefs.flavor_profiles[0] !== 'any') {
        setSelectedFlavors(prefs.flavor_profiles)
      } else {
        setSelectedFlavors([])
      }
      
      // 设置用餐目的
      if (prefs.dining_purpose) {
        setDiningPurpose(prefs.dining_purpose)
      } else {
        setDiningPurpose('any')
      }
      
      // 设置预算范围
      if (prefs.budget_range) {
        setBudgetMin(prefs.budget_range.min?.toString() || '20')
        setBudgetMax(prefs.budget_range.max?.toString() || '60')
      } else {
        setBudgetMin('20')
        setBudgetMax('60')
      }
      
      // 设置位置
      if (prefs.location && prefs.location !== 'any') {
        const presetLocations = ['Orchard', 'Marina Bay', 'Chinatown', 'Bugis', 'Tanjong Pagar', 'Clarke Quay', 'Little India', 'Holland Village', 'Tiong Bahru', 'Katong / Joo Chiat']
        const isPreset = presetLocations.includes(prefs.location)
        if (isPreset) {
          setLocationSelect(prefs.location)
          setLocationInput('')
        } else {
          setLocationSelect('any')
          setLocationInput(prefs.location)
        }
      } else {
        setLocationSelect('any')
        setLocationInput('')
      }
      
      console.log('User preferences loaded:', prefs)
      
    } catch (error) {
      console.error('Error loading conversation preferences:', error)
      // 如果加载失败，使用默认值
      setSelectedTypes([])
      setSelectedFlavors([])
      setDiningPurpose('any')
      setBudgetMin('20')
      setBudgetMax('60')
      setLocationSelect('any')
      setLocationInput('')
    } finally {
      setIsLoadingPreferences(false)
    }
  }

  const handleSubmitPreferences = async () => {
    if (!userId) {
      alert('No active user session. Please sign in again.')
      return
    }
    
    setIsSubmittingPreferences(true)
    try {
      // 确定位置值：如果 locationSelect 不是 'any'，使用它；否则使用 locationInput
      const location = locationSelect !== 'any' ? locationSelect : (locationInput || 'any')
      
      const preferences = {
        restaurant_types: selectedTypes.length > 0 ? selectedTypes : ['any'],
        flavor_profiles: selectedFlavors.length > 0 ? selectedFlavors : ['any'],
        dining_purpose: diningPurpose,
        budget_range: {
          min: parseInt(budgetMin) || 20,
          max: parseInt(budgetMax) || 60,
          currency: 'SGD',
          per: 'person'
        },
        location: location
      }
      
      const result = await updatePreferences(preferences, userId)
      if (currentChatId) {
        await updateConversationPreferences(userId, currentChatId, result.preferences)
      }
      console.log('User preferences updated:', result)
      
      alert('Preferences updated successfully!')
      
    } catch (error) {
      console.error('Error updating preferences:', error)
      alert('Failed to update preferences. Please try again.')
    } finally {
      setIsSubmittingPreferences(false)
    }
  }

  const selectChat = (chatId: string) => {
    setCurrentChatId(chatId)
    const chat = chatHistories.find(c => c.id === chatId)
    if (chat) {
      setSelectedModel(chat.model)
      setSelectedServiceType(serviceValueFromModel(chat.model))
    }
  }

  const openTaskNotification = (conversationId: string, notificationId: string) => {
    selectChat(conversationId)
    dismissTaskNotification(notificationId)
  }

  const updateChatModel = (chatId: string, model: string) => {
    setChatHistories(prev => 
      prev.map(chat => 
        chat.id === chatId ? { ...chat, model } : chat
      )
    )
    if (chatId === currentChatId) {
      setSelectedModel(model)
      setSelectedServiceType(serviceValueFromModel(model))
    }
  }

  const toggleType = (value: string) => {
    setSelectedTypes(prev => 
      prev.includes(value) 
        ? prev.filter(t => t !== value)
        : [...prev, value]
    )
  }

  const toggleFlavor = (value: string) => {
    setSelectedFlavors(prev => 
      prev.includes(value) 
        ? prev.filter(f => f !== value)
        : [...prev, value]
    )
  }

  const deleteChat = async (chatId: string, e: React.MouseEvent) => {
    e.stopPropagation() // 阻止触发选择聊天事件
    if (chatHistories.length <= 1) {
      // 如果只有一个聊天，不允许删除
      return
    }
    
    try {
      await deleteConversationAPI(userId, chatId)
      
      setChatHistories(prev => prev.filter(chat => chat.id !== chatId))
      
      // 如果删除的是当前聊天，切换到第一个聊天
      if (currentChatId === chatId) {
        const remainingChats = chatHistories.filter(chat => chat.id !== chatId)
        if (remainingChats.length > 0) {
          setCurrentChatId(remainingChats[0].id)
          setSelectedModel(remainingChats[0].model)
          setSelectedServiceType(serviceValueFromModel(remainingChats[0].model))
        } else {
          // 如果没有剩余对话，创建新对话
          createNewChat()
        }
      }
    } catch (error) {
      console.error('Error deleting chat:', error)
      alert('Failed to delete chat. Please try again.')
    }
  }
  
  // 编辑对话标题
  const startEditingTitle = (chatId: string, currentTitle: string, e: React.MouseEvent) => {
    e.stopPropagation() // 阻止触发选择聊天事件
    setEditingChatId(chatId)
    setEditingTitle(currentTitle)
  }

  const cancelEditingTitle = () => {
    setEditingChatId(null)
    setEditingTitle('')
  }

  const saveEditingTitle = async (chatId: string) => {
    if (!editingTitle.trim()) {
      alert('标题不能为空')
      return
    }

    try {
      await updateConversation(userId, chatId, { title: editingTitle.trim() })
      
      // 更新本地状态
      setChatHistories(prev => prev.map(chat => 
        chat.id === chatId 
          ? { ...chat, title: editingTitle.trim() }
          : chat
      ))
      
      setEditingChatId(null)
      setEditingTitle('')
    } catch (error) {
      console.error('Error updating conversation title:', error)
      alert('更新标题失败，请重试')
    }
  }

  // 监听编辑输入框的键盘事件
  const handleEditKeyDown = (e: React.KeyboardEvent<HTMLInputElement>, chatId: string) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      saveEditingTitle(chatId)
    } else if (e.key === 'Escape') {
      e.preventDefault()
      cancelEditingTitle()
    }
  }

  const resetConversationBootstrap = () => {
    setChatHistories([])
    setCurrentChatId(null)
    setSelectedModel('Auto')
    setSelectedServiceType('auto')
    setSelectedTypes([])
    setSelectedFlavors([])
    setDiningPurpose('any')
    setBudgetMin('')
    setBudgetMax('')
    setLocationSelect('any')
    setLocationInput('')
    setBackgroundTasks({})
    setTaskNotifications([])
    setBackgroundRequests({})
    setBackgroundTasksReady(false)
    hasInitializedRef.current = false
    isCreatingDefaultChatRef.current = false
  }

  const applyAuth = (auth: AuthResponse) => {
    setUserId(auth.user.id)
    setAuthUser(auth.user)
    setAuthError(null)
    resetConversationBootstrap()
  }

  const handleAuthSubmit = async () => {
    setAuthError(null)
    try {
      const auth = authMode === 'login'
        ? await login(authEmail.trim(), authPassword)
        : await register(authEmail.trim(), authPassword, authDisplayName.trim() || undefined)
      applyAuth(auth)
      setShowAuthPanel(false)
      setAuthPassword('')
    } catch (error: any) {
      setAuthError(error?.message || 'Authentication failed')
    }
  }

  const handleLogout = async () => {
    setAuthError(null)
    try {
      await logout()
      const auth = await ensureAuthSession(getDeviceId())
      applyAuth(auth)
      setShowAuthPanel(false)
    } catch (error: any) {
      setAuthError(error?.message || 'Logout failed')
    }
  }

  // 当开始编辑时，聚焦输入框
  useEffect(() => {
    if (editingChatId && editInputRef.current) {
      editInputRef.current.focus()
      editInputRef.current.select()
    }
  }, [editingChatId])

  // Add/remove class to body when preferences panel is open
  useEffect(() => {
    if (showPreferences) {
      document.body.classList.add('preferences-open')
    } else {
      document.body.classList.remove('preferences-open')
    }
    return () => {
      document.body.classList.remove('preferences-open')
    }
  }, [showPreferences])

  // 添加回调函数供Chat组件使用，用于保存消息
  const handleMessageAdded = async (role: 'user' | 'assistant', content: string) => {
    if (!currentChatId) return
    
    try {
      // 更新本地状态中的lastMessage（消息已经在Chat组件中保存到后端了）
      setChatHistories(prev => prev.map(chat => {
        if (chat.id === currentChatId) {
          return {
            ...chat,
            lastMessage: content.substring(0, 100),
            timestamp: new Date()
          }
        }
        return chat
      }))
      
      // 定期重新加载对话列表以获取最新的更新时间（不立即加载，避免频繁请求）
      setTimeout(() => {
        loadConversations()
      }, 1000)
    } catch (error) {
      console.error('Error updating message:', error)
    }
  }

  const currentChat = chatHistories.find(c => c.id === currentChatId)
  const conversationActivity = useMemo(() => {
    const activity: Record<string, { hasRequest: boolean; taskProgress: number | null }> = {}
    const ensure = (conversationId: string) => {
      if (!activity[conversationId]) {
        activity[conversationId] = { hasRequest: false, taskProgress: null }
      }
      return activity[conversationId]
    }

    Object.values(backgroundRequests).forEach(request => {
      if (request.userId !== userId || request.status !== 'pending') return
      ensure(request.conversationId).hasRequest = true
    })

    Object.values(backgroundTasks).forEach(task => {
      if (task.userId !== userId || isTerminalTaskStatus(task.status)) return
      const item = ensure(task.conversationId)
      const progress = typeof task.status?.progress === 'number' ? task.status.progress : 0
      item.taskProgress = Math.max(item.taskProgress ?? 0, progress)
    })

    return activity
  }, [backgroundRequests, backgroundTasks, userId])

  return (
    <div className="app">
      <AnimatedBackground />
      <aside 
        className={`sidebar ${sidebarCollapsed ? 'collapsed' : ''} ${isResizingSidebar ? 'resizing' : ''}`}
        style={{ width: sidebarCollapsed ? 0 : `${sidebarWidth}px` }}
      >
        {!sidebarCollapsed && (
          <div 
            className="sidebar-resize-handle"
            onMouseDown={(e) => {
              e.preventDefault()
              setIsResizingSidebar(true)
              const startX = e.clientX
              const startWidth = sidebarWidth
              
              const handleMouseMove = (e: MouseEvent) => {
                const diff = e.clientX - startX
                const newWidth = Math.max(240, Math.min(600, startWidth + diff)) // 最小240px（确保不遮挡组件），最大600px
                setSidebarWidth(newWidth)
              }
              
              const handleMouseUp = () => {
                setIsResizingSidebar(false)
                document.removeEventListener('mousemove', handleMouseMove)
                document.removeEventListener('mouseup', handleMouseUp)
              }
              
              document.addEventListener('mousemove', handleMouseMove)
              document.addEventListener('mouseup', handleMouseUp)
            }}
          />
        )}
        <div className="sidebar-header">
          <div className="brand">
            <img src="/assets/MR_orange.png" alt="MetaRec Logo" className="brand-logo" />
            <img src="/assets/MR_name.png" alt="MetaRec Logo" className="brand-name" />
          </div>
          {/* 收起按钮 - 只在侧边栏展开时显示 */}
          {!sidebarCollapsed && (
            <button 
              className="sidebar-close-btn" 
              onClick={() => setSidebarCollapsed(true)}
              title="收起侧边栏"
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
                <line x1="9" y1="3" x2="9" y2="21"></line>
              </svg>
            </button>
          )}
        </div>
        
        {!sidebarCollapsed && (
          <>
            <div className="service-description">
              Providing an AI-powered cross-platform real-time recommendation system.
            </div>
            <div className="sidebar-divider"></div>
            
            <div className="chat-history">
              <div className="history-header">
                <label>Chat History</label>
                <button className="new-chat-btn" onClick={createNewChat}>
                  + New Chat
                </button>
              </div>
              <div className="history-list">
                {chatHistories.map(chat => {
                  const activity = conversationActivity[chat.id]
                  const taskProgress = activity?.taskProgress
                  return (
                  <div 
                    key={chat.id} 
                    className={`history-item ${currentChatId === chat.id ? 'active' : ''} ${activity?.hasRequest ? 'has-running-request' : ''} ${taskProgress !== null && taskProgress !== undefined ? 'has-running-task' : ''}`}
                    onClick={() => {
                      // 如果正在编辑，不触发选择
                      if (editingChatId !== chat.id) {
                        selectChat(chat.id)
                      }
                    }}
                  >
                    <div className="history-content">
                      {editingChatId === chat.id ? (
                        // 编辑模式：显示输入框
                        <div 
                          className="history-title-edit"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <input
                            ref={editingChatId === chat.id ? editInputRef : null}
                            type="text"
                            value={editingTitle}
                            onChange={(e) => setEditingTitle(e.target.value)}
                            onKeyDown={(e) => handleEditKeyDown(e, chat.id)}
                            onBlur={() => saveEditingTitle(chat.id)}
                            onClick={(e) => e.stopPropagation()}
                            className="history-title-input"
                            maxLength={50}
                          />
                        </div>
                      ) : (
                        // 普通模式：显示标题，支持双击编辑
                        <div 
                          className="history-title"
                          onDoubleClick={(e) => startEditingTitle(chat.id, chat.title, e)}
                          title="双击编辑标题"
                        >
                          <span className="chat-icon" style={{ marginRight: '8px', fontSize: '16px' }}>
                            {getChatIcon(chat.id)}
                          </span>
                          {chat.title}
                        </div>
                      )}
                      <div className="history-preview">{chat.lastMessage}</div>
                      <div className="history-meta">
                        <span className="history-model">{chat.model}</span>
                        <span className="history-time">
                          {chat.timestamp.toLocaleDateString()}
                        </span>
                      </div>
                    </div>
                    <div className="history-actions">
                      {editingChatId !== chat.id && (
                        <button
                          className="edit-chat-btn"
                          onClick={(e) => startEditingTitle(chat.id, chat.title, e)}
                          title="编辑标题"
                        >
                          ✏️
                        </button>
                      )}
                      {chatHistories.length > 1 && (
                        <button 
                          className="delete-chat-btn"
                          onClick={(e) => deleteChat(chat.id, e)}
                          title="删除聊天"
                        >
                          ×
                        </button>
                      )}
                    </div>
                    {activity?.hasRequest && (
                      <span className="history-running-spinner" aria-label="Conversation request running" />
                    )}
                    {taskProgress !== null && taskProgress !== undefined && (
                      <div className="history-task-progress" aria-label="Recommendation task progress">
                        <span style={{ width: `${Math.max(4, Math.min(100, taskProgress))}%` }} />
                      </div>
                    )}
                  </div>
                )})}
              </div>
            </div>
          </>
        )}
      </aside>
      <main className="main">
        <div className="main-header">
          {/* 展开按钮 - 只在侧边栏收起时显示 */}
          {sidebarCollapsed && (
            <button 
              className="sidebar-toggle-header" 
              onClick={() => setSidebarCollapsed(false)}
              title="展开侧边栏"
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="3" y1="6" x2="21" y2="6"></line>
                <line x1="3" y1="12" x2="21" y2="12"></line>
                <line x1="3" y1="18" x2="21" y2="18"></line>
              </svg>
            </button>
          )}
          <div className="service-selector-section">
            <div className="service-selector-inline">
              <label>Service Type:</label>
              <div className="compact-multi-select" ref={serviceDropdownRef}>
                <div className="dropdown-trigger" onClick={() => setShowServiceDropdown(!showServiceDropdown)}>
                  <span className="dropdown-text">
                    {SERVICE_TYPES.find(s => s.value === selectedServiceType)?.label || 'Select Service'}
                  </span>
                  <span className="dropdown-arrow">▼</span>
                </div>
                {showServiceDropdown && (
                  <div className="dropdown-menu">
                    {SERVICE_TYPES.map(service => (
                      <div 
                        key={service.value} 
                        className={`dropdown-option ${selectedServiceType === service.value ? 'selected' : ''} ${service.status === 'development' ? 'disabled' : ''}`}
                        onClick={() => {
                          if (service.status === 'active') {
                            setSelectedServiceType(service.value)
                            setSelectedModel(service.label)
                            if (currentChatId) {
                              updateChatModel(currentChatId, service.label)
                              updateConversation(userId, currentChatId, { model: service.label }).catch(error => {
                                console.error('Error updating conversation service type:', error)
                              })
                            }
                            setShowServiceDropdown(false)
                          }
                        }}
                      >
                        <div>
                          <div style={{ fontWeight: 500, display: 'flex', alignItems: 'center', gap: '8px' }}>
                            {service.label}
                            {service.status === 'development' && (
                              <span className="status-badge">Coming Soon</span>
                            )}
                          </div>
                          <div style={{ fontSize: '12px', color: 'var(--muted)' }}>
                            {service.description}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
            <div className="service-description-inline">
              {SERVICE_TYPES.find(s => s.value === selectedServiceType)?.description}
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            {/* Agent Mode Toggle */}
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                cursor: 'pointer',
                padding: '6px 8px',
                borderRadius: '8px',
                transition: 'background-color 0.2s',
                position: 'relative'
              }}
              onClick={() => setUseOnlineAgent(!useOnlineAgent)}
              onMouseEnter={(e) => {
                e.currentTarget.style.backgroundColor = 'var(--bg-secondary)'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.backgroundColor = 'transparent'
              }}
              title={useOnlineAgent ? 'Using online agent (real-time search)' : 'Using offline agent (cached results)'}
            >
              🤖
              {/* Toggle Switch */}
              <div style={{
                width: '40px',
                height: '22px',
                borderRadius: '11px',
                backgroundColor: useOnlineAgent ? 'var(--primary)' : 'var(--border)',
                position: 'relative',
                transition: 'background-color 0.2s',
                cursor: 'pointer'
              }}>
                <div style={{
                  width: '18px',
                  height: '18px',
                  borderRadius: '50%',
                  backgroundColor: 'white',
                  position: 'absolute',
                  top: '2px',
                  left: useOnlineAgent ? '20px' : '2px',
                  transition: 'left 0.2s',
                  boxShadow: '0 2px 4px rgba(0,0,0,0.2)'
                }} />
              </div>
            </div>
            
            <button 
              className="preferences-toggle" 
              onClick={() => {
                if (!showPreferences) {
                  loadConversationPreferences()
                }
                setShowPreferences(!showPreferences)
              }}
            >
              {showPreferences ? 'Hide' : 'Show'} Preferences
            </button>
            <div style={{ position: 'relative' }}>
              <button
                className="preferences-toggle"
                onClick={() => setShowAuthPanel(!showAuthPanel)}
                disabled={!authReady}
                title={authUser?.kind === 'guest' ? 'Guest session' : authUser?.email || 'Account'}
              >
                {authUser?.kind === 'guest' ? 'Guest' : (authUser?.display_name || authUser?.email || 'Account')}
              </button>
              {showAuthPanel && (
                <div className="auth-panel">
                  <div className="auth-panel-title">
                    {authUser?.kind === 'guest' ? 'Guest account' : 'Signed in'}
                  </div>
                  {authUser?.kind !== 'guest' ? (
                    <>
                      <div className="auth-panel-subtitle">
                        {authUser?.email}
                      </div>
                      <button className="submit-preferences-btn" onClick={handleLogout}>
                        Sign out
                      </button>
                    </>
                  ) : (
                    <>
                      <div className="auth-mode-tabs">
                        <button
                          className={`auth-mode-tab ${authMode === 'login' ? 'active' : ''}`}
                          onClick={() => setAuthMode('login')}
                        >
                          Login
                        </button>
                        <button
                          className={`auth-mode-tab ${authMode === 'register' ? 'active' : ''}`}
                          onClick={() => setAuthMode('register')}
                        >
                          Register
                        </button>
                      </div>
                      <input
                        type="email"
                        placeholder="Email"
                        value={authEmail}
                        onChange={(event) => setAuthEmail(event.target.value)}
                        className="auth-input"
                      />
                      <input
                        type="password"
                        placeholder="Password"
                        value={authPassword}
                        onChange={(event) => setAuthPassword(event.target.value)}
                        onKeyDown={(event) => {
                          if (event.key === 'Enter') handleAuthSubmit()
                        }}
                        className="auth-input"
                      />
                      {authMode === 'register' && (
                        <input
                          type="text"
                          placeholder="Display name"
                          value={authDisplayName}
                          onChange={(event) => setAuthDisplayName(event.target.value)}
                          className="auth-input"
                        />
                      )}
                      {authError && (
                        <div className="auth-error">
                          {authError}
                        </div>
                      )}
                      <button className="submit-preferences-btn" onClick={handleAuthSubmit}>
                        {authMode === 'login' ? 'Login' : 'Create account'}
                      </button>
                    </>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>

        {showPreferences && (
          <div className="preferences-overlay" onClick={() => setShowPreferences(false)}>
            <Rnd
              // 移动端：固定为贴合视口的居中弹窗（不可拖拽/缩放），避免 600px 默认尺寸
              // 与 400px 最小宽度在窄屏上溢出；桌面端保留可拖拽/缩放行为。
              size={isMobileViewport
                ? { width: Math.min(preferencePanelSize.width, window.innerWidth - 24), height: Math.min(preferencePanelSize.height, window.innerHeight - 24) }
                : { width: preferencePanelSize.width, height: preferencePanelSize.height }}
              position={isMobileViewport
                ? { x: Math.max(12, (window.innerWidth - Math.min(preferencePanelSize.width, window.innerWidth - 24)) / 2), y: 12 }
                : { x: preferencePanelPosition.x, y: preferencePanelPosition.y }}
              onDragStop={(e, d) => {
                if (isMobileViewport) return
                setPreferencePanelPosition({ x: d.x, y: d.y })
              }}
              onResizeStop={(e, direction, ref, delta, position) => {
                if (isMobileViewport) return
                setPreferencePanelSize({
                  width: parseInt(ref.style.width),
                  height: parseInt(ref.style.height)
                })
                setPreferencePanelPosition({ x: position.x, y: position.y })
              }}
              minWidth={isMobileViewport ? Math.min(300, window.innerWidth - 24) : 400}
              minHeight={300}
              maxWidth={window.innerWidth - (isMobileViewport ? 24 : window.innerWidth * 0.1)}
              maxHeight={window.innerHeight * (isMobileViewport ? 1 : 0.9)}
              bounds="window"
              disableDragging={isMobileViewport}
              enableResizing={!isMobileViewport}
              dragHandleClassName="preferences-header"
              style={{
                position: 'absolute'
              }}
            >
              <div className="preferences-panel" onClick={(e) => e.stopPropagation()}>
                <div className="preferences-header">
                  <h3>Restaurant Preferences</h3>
                  <button 
                    className="close-btn" 
                    onClick={() => setShowPreferences(false)}
                    title="Close"
                  >
                    ×
                  </button>
                </div>
              {isLoadingPreferences ? (
                <div className="preferences-loading">
                  <div className="loading-spinner"></div>
                  <p>Loading your preferences...</p>
                </div>
              ) : (
              <>
              <div className="filters">
                <div>
                  <label>Restaurant Type</label>
                  <div className="compact-multi-select" ref={typeDropdownRef}>
                    <div className="selected-tags">
                      {selectedTypes.map(type => (
                        <span key={type} className="tag" onClick={() => toggleType(type)}>
                          {RESTAURANT_TYPES.find(t => t.value === type)?.label}
                          <span className="tag-remove">×</span>
                        </span>
                      ))}
                    </div>
                    <div className="dropdown-trigger" onClick={() => setShowTypeDropdown(!showTypeDropdown)}>
                      <span className={`dropdown-text ${selectedTypes.length === 0 ? 'placeholder' : ''}`}>
                        {selectedTypes.length > 0 
                          ? `${selectedTypes.length} selected` 
                          : 'Any'
                        }
                      </span>
                      <span className="dropdown-arrow">▼</span>
                    </div>
                    {showTypeDropdown && (
                      <div className="dropdown-menu">
                        {RESTAURANT_TYPES.map(type => (
                          <div 
                            key={type.value} 
                            className={`dropdown-option ${selectedTypes.includes(type.value) ? 'selected' : ''}`}
                            onClick={() => toggleType(type.value)}
                          >
                            <span className="checkbox">{selectedTypes.includes(type.value) ? '✓' : ''}</span>
                            <span>{type.label}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
                <div>
                  <label>Flavor Profile</label>
                  <div className="compact-multi-select" ref={flavorDropdownRef}>
                    <div className="selected-tags">
                      {selectedFlavors.map(flavor => (
                        <span key={flavor} className="tag" onClick={() => toggleFlavor(flavor)}>
                          {FLAVOR_PROFILES.find(f => f.value === flavor)?.label}
                          <span className="tag-remove">×</span>
                        </span>
                      ))}
                    </div>
                    <div className="dropdown-trigger" onClick={() => setShowFlavorDropdown(!showFlavorDropdown)}>
                      <span className={`dropdown-text ${selectedFlavors.length === 0 ? 'placeholder' : ''}`}>
                        {selectedFlavors.length > 0 
                          ? `${selectedFlavors.length} selected` 
                          : 'Any'
                        }
                      </span>
                      <span className="dropdown-arrow">▼</span>
                    </div>
                    {showFlavorDropdown && (
                      <div className="dropdown-menu">
                        {FLAVOR_PROFILES.map(flavor => (
                          <div 
                            key={flavor.value} 
                            className={`dropdown-option ${selectedFlavors.includes(flavor.value) ? 'selected' : ''}`}
                            onClick={() => toggleFlavor(flavor.value)}
                          >
                            <span className="checkbox">{selectedFlavors.includes(flavor.value) ? '✓' : ''}</span>
                            <span>{flavor.label}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
                <div>
                  <label>Dining Purpose</label>
                  <select 
                    id="purpose-select" 
                    value={diningPurpose}
                    onChange={(e) => setDiningPurpose(e.target.value)}
                  >
                    <option value="any">Any</option>
                    <option value="date-night">Date Night</option>
                    <option value="family">Family</option>
                    <option value="business">Business</option>
                    <option value="solo">Solo</option>
                    <option value="friends">Friends</option>
                    <option value="celebration">Celebration</option>
                  </select>
                </div>
                <div>
                  <label>Budget Range (per person)</label>
                  <div className="row">
                    <input 
                      id="budget-min" 
                      type="number" 
                      min={0} 
                      step={1} 
                      placeholder="Min" 
                      value={budgetMin}
                      onChange={(e) => setBudgetMin(e.target.value)}
                    />
                    <span className="muted">to</span>
                    <input 
                      id="budget-max" 
                      type="number" 
                      min={0} 
                      step={1} 
                      placeholder="Max" 
                      value={budgetMax}
                      onChange={(e) => setBudgetMax(e.target.value)}
                    />
                    <span className="muted">(SGD)</span>
                  </div>
                </div>
                <div>
                  <label>Location (Singapore)</label>
                  <select 
                    id="location-select" 
                    value={locationSelect}
                    onChange={(e) => {
                      setLocationSelect(e.target.value)
                      // 如果选择了预设选项，清空输入框
                      if (e.target.value !== 'any') {
                        setLocationInput('')
                      }
                    }}
                  >
                    <option value="any">Any</option>
                    <option value="Orchard">Orchard</option>
                    <option value="Marina Bay">Marina Bay</option>
                    <option value="Chinatown">Chinatown</option>
                    <option value="Bugis">Bugis</option>
                    <option value="Tanjong Pagar">Tanjong Pagar</option>
                    <option value="Clarke Quay">Clarke Quay</option>
                    <option value="Little India">Little India</option>
                    <option value="Holland Village">Holland Village</option>
                    <option value="Tiong Bahru">Tiong Bahru</option>
                    <option value="Katong / Joo Chiat">Katong / Joo Chiat</option>
                  </select>
                  <div className="space" />
                  <input 
                    id="location-input" 
                    placeholder="Type a specific address or area (optional)"
                    value={locationInput}
                    onChange={(e) => {
                      setLocationInput(e.target.value)
                      // 如果输入了自定义位置，将 select 设置为 'any'
                      if (e.target.value) {
                        setLocationSelect('any')
                      }
                    }}
                  />
                </div>
              </div>
              <div className="preferences-actions">
                <button 
                  className="submit-preferences-btn"
                  onClick={handleSubmitPreferences}
                  disabled={isSubmittingPreferences}
                >
                  {isSubmittingPreferences ? 'Updating...' : 'Update Preferences'}
                </button>
              </div>
              </>
              )}
              </div>
            </Rnd>
          </div>
        )}

        <Chat 
          selectedTypes={selectedTypes} 
          selectedFlavors={selectedFlavors} 
          currentModel={selectedModel}
          chatHistory={currentChat}
          conversationId={currentChatId}
          userId={userId}
          isRegistered={authUser?.kind === 'registered'}
          onMessageAdded={handleMessageAdded}
          useOnlineAgent={useOnlineAgent}
          serviceDomainLock={selectedServiceType === 'auto' ? undefined : selectedServiceType}
          backgroundTasks={Object.values(backgroundTasks)}
          backgroundRequests={Object.values(backgroundRequests)}
          onTaskCreated={registerBackgroundTask}
          onRequestStarted={registerBackgroundRequest}
          onRequestCompleted={completeBackgroundRequest}
          onRequestFailed={failBackgroundRequest}
        />
      </main>
      <TaskNotificationTray
        notifications={taskNotifications}
        onOpen={openTaskNotification}
        onDismiss={dismissTaskNotification}
      />
    </div>
  )
}
