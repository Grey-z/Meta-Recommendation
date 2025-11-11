import React, { useState, useEffect } from 'react'
import { Chat } from './Chat'
import { updatePreferences, getUserPreferences } from '../utils/api'

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

// Chat history interface
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
  const [chatHistories, setChatHistories] = useState<ChatHistory[]>([
    {
      id: '1',
      title: 'Restaurant Recommendations',
      model: 'RestRec',
      lastMessage: 'Tell me what you crave, when, where, and your budget.',
      timestamp: new Date(),
      messages: []
    }
  ])
  const [currentChatId, setCurrentChatId] = useState<string>('1')
  const [selectedModel, setSelectedModel] = useState<string>('RestRec')
  const [showModelDropdown, setShowModelDropdown] = useState(false)
  const [showPreferences, setShowPreferences] = useState(false)
  const [selectedTypes, setSelectedTypes] = useState<string[]>([])
  const [selectedFlavors, setSelectedFlavors] = useState<string[]>([])
  const [showTypeDropdown, setShowTypeDropdown] = useState(false)
  const [showFlavorDropdown, setShowFlavorDropdown] = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [selectedServiceType, setSelectedServiceType] = useState<string>('restaurant')
  const [showServiceDropdown, setShowServiceDropdown] = useState(false)
  const [isSubmittingPreferences, setIsSubmittingPreferences] = useState(false)
  const [isLoadingPreferences, setIsLoadingPreferences] = useState(false)

  const createNewChat = () => {
    const newChat: ChatHistory = {
      id: Date.now().toString(),
      title: 'New Chat',
      model: selectedModel,
      lastMessage: 'Start a new conversation...',
      timestamp: new Date(),
      messages: []
    }
    setChatHistories(prev => [newChat, ...prev])
    setCurrentChatId(newChat.id)
  }

  const loadUserPreferences = async () => {
    setIsLoadingPreferences(true)
    try {
      const result = await getUserPreferences('default')
      const prefs = result.preferences
      
      // 设置餐厅类型
      if (prefs.restaurant_types && prefs.restaurant_types[0] !== 'any') {
        setSelectedTypes(prefs.restaurant_types)
      }
      
      // 设置口味偏好
      if (prefs.flavor_profiles && prefs.flavor_profiles[0] !== 'any') {
        setSelectedFlavors(prefs.flavor_profiles)
      }
      
      // 设置用餐目的
      if (prefs.dining_purpose && prefs.dining_purpose !== 'any') {
        const purposeSelect = document.getElementById('purpose-select') as HTMLSelectElement
        if (purposeSelect) {
          purposeSelect.value = prefs.dining_purpose
        }
      }
      
      // 设置预算范围
      if (prefs.budget_range) {
        const budgetMin = document.getElementById('budget-min') as HTMLInputElement
        const budgetMax = document.getElementById('budget-max') as HTMLInputElement
        if (budgetMin) budgetMin.value = prefs.budget_range.min?.toString() || '20'
        if (budgetMax) budgetMax.value = prefs.budget_range.max?.toString() || '60'
      }
      
      // 设置位置
      if (prefs.location && prefs.location !== 'any') {
        const locationInput = document.getElementById('location-input') as HTMLInputElement
        if (locationInput) {
          locationInput.value = prefs.location
        }
      }
      
      console.log('Preferences loaded:', prefs)
      
    } catch (error) {
      console.error('Error loading preferences:', error)
    } finally {
      setIsLoadingPreferences(false)
    }
  }

  const handleSubmitPreferences = async () => {
    setIsSubmittingPreferences(true)
    try {
      const purpose = (document.getElementById('purpose-select') as HTMLSelectElement)?.value || 'any'
      const budgetMin = parseInt((document.getElementById('budget-min') as HTMLInputElement)?.value || '0') || 0
      const budgetMax = parseInt((document.getElementById('budget-max') as HTMLInputElement)?.value || '0') || 0
      const location = (document.getElementById('location-input') as HTMLInputElement)?.value || 'any'
      
      const preferences = {
        user_id: 'default',
        restaurantTypes: selectedTypes.length > 0 ? selectedTypes : ['any'],
        flavorProfiles: selectedFlavors.length > 0 ? selectedFlavors : ['any'],
        diningPurpose: purpose,
        budgetRange: {
          min: budgetMin || 20,
          max: budgetMax || 60,
          currency: 'SGD',
          per: 'person'
        },
        location: location
      }
      
      const result = await updatePreferences(preferences)
      console.log('Preferences updated:', result)
      
      // 可以在这里添加成功提示
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

  const deleteChat = (chatId: string, e: React.MouseEvent) => {
    e.stopPropagation() // 阻止触发选择聊天事件
    if (chatHistories.length <= 1) {
      // 如果只有一个聊天，不允许删除
      return
    }
    
    setChatHistories(prev => prev.filter(chat => chat.id !== chatId))
    
    // 如果删除的是当前聊天，切换到第一个聊天
    if (currentChatId === chatId) {
      const remainingChats = chatHistories.filter(chat => chat.id !== chatId)
      if (remainingChats.length > 0) {
        setCurrentChatId(remainingChats[0].id)
        setSelectedModel(remainingChats[0].model)
      }
    }
  }

  const currentChat = chatHistories.find(c => c.id === currentChatId)

  return (
    <div className="app">
      <aside className={`sidebar ${sidebarCollapsed ? 'collapsed' : ''}`}>
        <div className="sidebar-header">
          <div className="brand">
            <img src="/assets/MR_coffee.png" alt="MetaRec Logo" className="brand-logo" />
            <span>MetaRec</span>
          </div>
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
                    onClick={() => selectChat(chat.id)}
                  >
                    <div className="history-content">
                      <div className="history-title">{chat.title}</div>
                      <div className="history-preview">{chat.lastMessage}</div>
                      <div className="history-meta">
                        <span className="history-model">{chat.model}</span>
                        <span className="history-time">
                          {chat.timestamp.toLocaleDateString()}
                        </span>
                      </div>
                    </div>
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
                ))}
              </div>
            </div>
          </>
        )}
      </aside>
      {/* 浮动恢复按钮 - 只在侧边栏完全隐藏时显示 */}
      {sidebarCollapsed && (
        <button 
          className="sidebar-restore-btn"
          onClick={() => setSidebarCollapsed(false)}
          title="展开侧边栏"
        >
          <span className="restore-arrow">{'>'}</span>
        </button>
      )}
      {/* 侧边栏切换按钮 */}
      {!sidebarCollapsed && (
      <button 
          className="sidebar-toggle" 
          onClick={() => setSidebarCollapsed(true)}
          title={'收起侧边栏'}
        >
          <span className="toggle-arrow">
            {'<'}
          </span>
        </button>
      )}
      <main className="main">
        <div className="main-header">
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
                loadUserPreferences()
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
                  <select id="purpose-select" defaultValue="any">
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
                    <input id="budget-min" type="number" min={0} step={1} placeholder="Min" defaultValue={20} />
                    <span className="muted">to</span>
                    <input id="budget-max" type="number" min={0} step={1} placeholder="Max" defaultValue={60} />
                    <span className="muted">(SGD)</span>
                  </div>
                </div>
                <div>
                  <label>Location (Singapore)</label>
                  <select id="location-select" defaultValue="any">
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
                  <input id="location-input" placeholder="Type a specific address or area (optional)"/>
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
        />
      </main>
    </div>
  )
}

