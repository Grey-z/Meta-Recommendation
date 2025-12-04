import React, { useState, useEffect, useRef } from 'react'
import { Chat } from './Chat'
import { updateConversationPreferences, getConversationPreferences, getConversations, getConversation, createConversation, deleteConversation as deleteConversationAPI, updateConversation } from '../utils/api'
import { getDeviceId } from '../utils/deviceId'
import type { ConversationSummary, Conversation } from '../utils/types'

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
    value: 'restaurant', 
    label: 'RestRec', 
    description: 'AI-powered restaurant recommendations tailored to your taste and occasion',
    status: 'active'
  },
  { 
    value: 'product', 
    label: 'ProductRec', 
    description: 'Coming Soon...',
    status: 'development'
  },
  { 
    value: 'movie', 
    label: 'MovieRec', 
    description: 'Coming Soon...',
    status: 'development'
  },
  { 
    value: 'music', 
    label: 'MusicRec', 
    description: 'Coming Soon...',
    status: 'development'
  },
  { 
    value: 'book', 
    label: 'BookRec', 
    description: 'Coming Soon...',
    status: 'development'
  }
]

// Chat history interface (兼容旧接口)
interface ChatHistory {
  id: string
  title: string
  model: string
  lastMessage: string
  timestamp: Date
  messages: Array<{ role: 'user' | 'assistant'; content: string }>
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
  const [userId] = useState<string>(() => getDeviceId())
  const [chatHistories, setChatHistories] = useState<ChatHistory[]>([])
  const [currentChatId, setCurrentChatId] = useState<string | null>(null)
  const [selectedModel, setSelectedModel] = useState<string>('RestRec')
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
  const [selectedServiceType, setSelectedServiceType] = useState<string>('restaurant')
  const [showServiceDropdown, setShowServiceDropdown] = useState(false)
  const [isSubmittingPreferences, setIsSubmittingPreferences] = useState(false)
  const [isLoadingPreferences, setIsLoadingPreferences] = useState(false)
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
    updateFavicon('/assets/MR_coffee_reverse.png')
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
    // 如果已经初始化过，跳过（防止 StrictMode 重复执行）
    if (hasInitializedRef.current) {
      return
    }
    
    hasInitializedRef.current = true
    loadConversations()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId]) // userId在初始化时设置，不需要在依赖中

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
    } catch (error) {
      console.error('Error creating new chat:', error)
      alert('Failed to create new chat. Please try again.')
    }
  }

  // 从当前 conversation 加载偏好设置
  const loadConversationPreferences = async () => {
    if (!currentChatId) {
      // 如果没有当前对话，重置为默认值
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
      const result = await getConversationPreferences(userId, currentChatId)
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
      
      console.log('Conversation preferences loaded:', prefs)
      
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
    if (!currentChatId) {
      alert('No active conversation. Please select or create a conversation first.')
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
      
      // 更新 conversation 的 preferences
      const result = await updateConversationPreferences(userId, currentChatId, preferences)
      console.log('Conversation preferences updated:', result)
      
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
    }
  }

  const updateChatModel = (chatId: string, model: string) => {
    setChatHistories(prev => 
      prev.map(chat => 
        chat.id === chatId ? { ...chat, model } : chat
      )
    )
    if (chatId === currentChatId) {
      setSelectedModel(model)
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

  return (
    <div className="app">
      <AnimatedBackground />
      <aside className={`sidebar ${sidebarCollapsed ? 'collapsed' : ''}`}>
        <div className="sidebar-header">
          <div className="brand">
            <img src="/assets/MR_coffee.png" alt="MetaRec Logo" className="brand-logo" />
            <span>MetaRec</span>
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
                {chatHistories.map(chat => (
                  <div 
                    key={chat.id} 
                    className={`history-item ${currentChatId === chat.id ? 'active' : ''}`}
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
                  </div>
                ))}
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
              <div className="compact-multi-select">
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
        </div>

        {showPreferences && (
          <div className="preferences-overlay" onClick={() => setShowPreferences(false)}>
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
                  <div className="compact-multi-select">
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
                  <div className="compact-multi-select">
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
          </div>
        )}

        <Chat 
          selectedTypes={selectedTypes} 
          selectedFlavors={selectedFlavors} 
          currentModel={selectedModel}
          chatHistory={currentChat}
          conversationId={currentChatId}
          userId={userId}
          onMessageAdded={handleMessageAdded}
        />
      </main>
    </div>
  )
}

