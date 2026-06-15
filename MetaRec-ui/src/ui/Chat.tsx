import React, { useMemo, useRef, useState, useEffect, useCallback } from 'react'
import { recommend, getConversation, addMessage, setActiveConversationBranch } from '../utils/api'
import type { RecommendationResponse, ThinkingStep, ConfirmationRequest, TaskStatus, Conversation, ConversationBranch, FeedbackState } from '../utils/types'
import { MapModal } from './MapModal'
import { FeedbackControls } from './FeedbackControls'
import {
  extractResultId,
  extractTaskId,
  resolveRecommendationIdentity,
  withRecommendationIdentity,
} from '../utils/recommendationIdentity'
import { makeClientMessageId, makeClientRequestId } from '../utils/ids'

type Message = {
  id?: string
  role: 'user' | 'assistant'
  content: React.ReactNode
  branch_id?: string | null
  parent_message_id?: string | null
  fork_from_message_id?: string | null
  revision_of_message_id?: string | null
  metadata?: Record<string, any> | null
}

const MAIN_BRANCH_ID = 'branch-main'

function normalizeMessageRole(role: string): 'user' | 'assistant' {
  return role === 'user' ? 'user' : 'assistant'
}

// 把推荐结果动态转换为「类 Markdown」纯文本，便于复制到笔记 / IM 等
function recommendationResultToMarkdown(data: RecommendationResponse): string {
  const restaurants = data?.restaurants || []
  if (restaurants.length === 0) {
    return data?.llm_reply?.trim() || 'No recommendations found.'
  }
  const lines: string[] = [
    `Found ${restaurants.length} restaurant recommendation${restaurants.length > 1 ? 's' : ''}:`,
    '',
  ]
  restaurants.forEach((r, index) => {
    lines.push(`${index + 1}. **${r.name || 'Unnamed'}**`)
    const facts: string[] = []
    if (r.cuisine) facts.push(`Cuisine: ${r.cuisine}`)
    const area = r.area || r.location
    if (area) facts.push(`Area: ${area}`)
    if (r.price_per_person_sgd) facts.push(`Price: ${r.price_per_person_sgd} SGD/person`)
    else if (r.price) facts.push(`Price: ${r.price}`)
    if (typeof r.rating === 'number') {
      facts.push(`Rating: ${r.rating}${r.reviews_count ? ` (${r.reviews_count} reviews)` : ''}`)
    }
    if (r.address) facts.push(`Address: ${r.address}`)
    facts.forEach(fact => lines.push(`   - ${fact}`))
    const why = r.why || r.reason
    if (why) lines.push(`   - Why: ${why}`)
    lines.push('')
  })
  return lines.join('\n').trim()
}

// 返回某条消息可复制的纯文本；表单（确认/偏好编辑）与处理中占位不可复制，返回 null
function getMessageCopyText(message: Message): string | null {
  const type = message.metadata?.type
  if (type === 'confirmation' || type === 'processing') return null
  if (type === 'recommendation') {
    const data = message.metadata?.recommendation_data as RecommendationResponse | undefined
    return data ? recommendationResultToMarkdown(data) : null
  }
  if (typeof message.content === 'string') {
    const trimmed = message.content.trim()
    return trimmed ? trimmed : null
  }
  return null
}

function toLatLngCoordinates(value: Record<string, number> | null | undefined):
  | { latitude: number; longitude: number }
  | undefined {
  if (!value) {
    return undefined
  }
  const latitude = value.latitude
  const longitude = value.longitude
  if (typeof latitude === 'number' && typeof longitude === 'number') {
    return { latitude, longitude }
  }
  return undefined
}

function getMessageId(message?: Message | null): string | undefined {
  if (!message) return undefined
  return message.id || (message.metadata?.message_id as string | undefined)
}

function getMessageBranchId(message: Message): string {
  const timeTravel = message.metadata?.time_travel
  return (
    message.branch_id
    || (message.metadata?.branch_id as string | undefined)
    || (timeTravel?.branch_id as string | undefined)
    || MAIN_BRANCH_ID
  )
}

function getMessageRevisionSourceId(message: Message): string | undefined {
  const timeTravel = message.metadata?.time_travel
  return (
    message.revision_of_message_id
    || message.fork_from_message_id
    || (message.metadata?.revision_of_message_id as string | undefined)
    || (message.metadata?.fork_from_message_id as string | undefined)
    || (timeTravel?.replay_from_message_id as string | undefined)
  )
}

function buildMessageLookup(messages: Message[]): Map<string, Message> {
  const byId = new Map<string, Message>()
  messages.forEach(message => {
    const id = getMessageId(message)
    if (id) {
      byId.set(id, message)
    }
  })
  return byId
}

function getCanonicalRevisionRootId(
  message: Message,
  byId: Map<string, Message>
): string | undefined {
  let currentId = getMessageId(message)
  let sourceId = getMessageRevisionSourceId(message)
  const seen = new Set<string>()

  while (sourceId && !seen.has(sourceId)) {
    seen.add(sourceId)
    currentId = sourceId
    const sourceMessage = byId.get(sourceId)
    if (!sourceMessage) {
      return sourceId
    }

    const nextSourceId = getMessageRevisionSourceId(sourceMessage)
    if (!nextSourceId) {
      return getMessageId(sourceMessage) || sourceId
    }
    sourceId = nextSourceId
  }

  return currentId
}

function getCanonicalRevisionRootIdFromMessageId(
  messageId: string | null | undefined,
  byId: Map<string, Message>
): string | undefined {
  if (!messageId) {
    return undefined
  }
  const message = byId.get(messageId)
  if (!message) {
    return messageId
  }
  return getCanonicalRevisionRootId(message, byId)
}

function getBranchRevisionRootId(
  branchId: string,
  branches: Record<string, ConversationBranch>,
  byId: Map<string, Message>
): string | undefined {
  const branch = branches[branchId]
  if (!branch) {
    return undefined
  }
  return getCanonicalRevisionRootIdFromMessageId(
    branch.fork_from_message_id || branch.root_message_id,
    byId
  )
}

function deriveBranchesFromMessages(
  allMessages: Message[],
  knownBranches: Record<string, ConversationBranch>
): Record<string, ConversationBranch> {
  const now = new Date().toISOString()
  const byId = buildMessageLookup(allMessages)
  let changed = false
  const branches: Record<string, ConversationBranch> = { ...knownBranches }

  allMessages.forEach(message => {
    const messageId = getMessageId(message)
    if (!messageId) return
    const branchId = getMessageBranchId(message)
    const sourceId = getMessageRevisionSourceId(message)
    const sourceMessage = sourceId ? byId.get(sourceId) : undefined
    const parentBranchId = branchId === MAIN_BRANCH_ID
      ? null
      : (sourceMessage ? getMessageBranchId(sourceMessage) : MAIN_BRANCH_ID)
    const timestamp = (message.metadata?.timestamp as string | undefined) || now

    if (!branches[branchId]) {
      branches[branchId] = {
        id: branchId,
        parent_branch_id: parentBranchId,
        fork_from_message_id: sourceId || null,
        root_message_id: messageId,
        head_message_id: messageId,
        title: branchId === MAIN_BRANCH_ID ? 'Main' : 'Branch',
        created_at: timestamp,
        updated_at: timestamp,
      }
      changed = true
      return
    }

    const branch = branches[branchId]
    const nextBranch = { ...branch }
    if (!nextBranch.root_message_id) {
      nextBranch.root_message_id = messageId
      changed = true
    }
    if (!nextBranch.head_message_id || !message.metadata?.superseded) {
      nextBranch.head_message_id = messageId
      nextBranch.updated_at = timestamp
      changed = true
    }
    if (!nextBranch.fork_from_message_id && sourceId) {
      nextBranch.fork_from_message_id = sourceId
      changed = true
    }
    if (!nextBranch.parent_branch_id && parentBranchId) {
      nextBranch.parent_branch_id = parentBranchId
      changed = true
    }
    if (changed) {
      branches[branchId] = nextBranch
    }
  })

  return changed ? branches : knownBranches
}

function resolveSelectedBranchId(
  activeBranchId: string,
  allMessages: Message[],
  branches: Record<string, ConversationBranch>,
  branchSelectionState: Record<string, string>
): string {
  const byId = buildMessageLookup(allMessages)
  let resolvedBranchId = branches[activeBranchId] ? activeBranchId : MAIN_BRANCH_ID
  const seen = new Set<string>()

  while (!seen.has(resolvedBranchId)) {
    seen.add(resolvedBranchId)
    const currentRootMessageId = getBranchRevisionRootId(resolvedBranchId, branches, byId)
    const selectedBranchId = currentRootMessageId ? branchSelectionState[currentRootMessageId] : undefined
    if (
      !selectedBranchId
      || !branches[selectedBranchId]
      || selectedBranchId === resolvedBranchId
      || getBranchRevisionRootId(selectedBranchId, branches, byId) === currentRootMessageId
    ) {
      const visiblePath = buildVisibleBranchPath(allMessages, branches, resolvedBranchId)
      const pathRootIds = visiblePath.map(message => getCanonicalRevisionRootId(message, byId))
      // Only descend to fork points that lie *downstream* of the current branch's
      // own fork root. Editing a mid-conversation message forks a branch whose
      // root is that message, while its sibling (e.g. branch-main) forks at the
      // very first message — an *ancestor*. Without this guard, a selection that
      // points up to the ancestor branch and one that points down to the freshly
      // forked child both qualify, so resolve() is no longer idempotent:
      // resolve(child) walks up to the ancestor and resolve(ancestor) walks back
      // down to the child. Re-renders (e.g. from an in-flight task poll) feed the
      // result back in and the chat ping-pongs between the two branches while the
      // branch switcher stays stuck. Restricting to downstream forks keeps the
      // walk monotonic toward the leaf and convergent.
      const currentRootIndex = currentRootMessageId ? pathRootIds.indexOf(currentRootMessageId) : -1
      let nestedSelectedBranchId: string | undefined
      for (let index = 0; index < visiblePath.length; index += 1) {
        if (index <= currentRootIndex) continue
        const rootMessageId = pathRootIds[index]
        if (!rootMessageId || rootMessageId === currentRootMessageId) continue
        const selectedNested = branchSelectionState[rootMessageId]
        if (!selectedNested || !branches[selectedNested] || selectedNested === resolvedBranchId) continue
        if (getBranchRevisionRootId(selectedNested, branches, byId) === rootMessageId) {
          nestedSelectedBranchId = selectedNested
        }
      }
      if (!nestedSelectedBranchId || seen.has(nestedSelectedBranchId)) {
        break
      }
      resolvedBranchId = nestedSelectedBranchId
      continue
    }
    resolvedBranchId = selectedBranchId
  }

  return resolvedBranchId
}

function hydrateSelectionStateFromActiveBranch(
  activeBranchId: string,
  allMessages: Message[],
  branches: Record<string, ConversationBranch>,
  branchSelectionState: Record<string, string>
): Record<string, string> {
  const byId = buildMessageLookup(allMessages)
  let nextSelectionState = branchSelectionState
  let cursor: string | null | undefined = branches[activeBranchId] ? activeBranchId : MAIN_BRANCH_ID
  const seen = new Set<string>()
  const hydratedRoots = new Set<string>()

  while (cursor && branches[cursor] && !seen.has(cursor)) {
    seen.add(cursor)
    const rootMessageId = getBranchRevisionRootId(cursor, branches, byId)
    if (rootMessageId && !hydratedRoots.has(rootMessageId)) {
      nextSelectionState = { ...nextSelectionState, [rootMessageId]: cursor }
    }
    if (rootMessageId) {
      hydratedRoots.add(rootMessageId)
    }
    cursor = branches[cursor].parent_branch_id
  }

  return nextSelectionState
}

function getSelectedBranchIdForMessage(
  message: Message,
  allMessages: Message[],
  branches: Record<string, ConversationBranch>,
  branchSelectionState: Record<string, string>,
  messageLookup?: Map<string, Message>
): string {
  const messageBranchId = getMessageBranchId(message)
  const byId = messageLookup || buildMessageLookup(allMessages)
  const rootMessageId = getCanonicalRevisionRootId(message, byId)
  const selectedBranchId = rootMessageId ? branchSelectionState[rootMessageId] : undefined

  if (!selectedBranchId || !branches[selectedBranchId]) {
    return messageBranchId
  }

  return getBranchRevisionRootId(selectedBranchId, branches, byId) === rootMessageId
    ? selectedBranchId
    : messageBranchId
}

function buildSiblingBranchIdsByRoot(
  allMessages: Message[],
  branches: Record<string, ConversationBranch>,
  byId: Map<string, Message>
): Map<string, string[]> {
  const siblingsByRoot = new Map<string, string[]>()
  const addBranchId = (rootMessageId: string | undefined, branchId: string | null | undefined) => {
    if (!rootMessageId || !branchId) return
    const existing = siblingsByRoot.get(rootMessageId) || []
    if (!existing.includes(branchId)) {
      siblingsByRoot.set(rootMessageId, [...existing, branchId])
    }
  }

  allMessages.forEach(item => {
    if (item.role !== 'user') return
    addBranchId(getCanonicalRevisionRootId(item, byId), getMessageBranchId(item))
  })

  Object.values(branches)
    .sort((left, right) => (
      new Date(left.created_at || left.updated_at).getTime()
      - new Date(right.created_at || right.updated_at).getTime()
    ))
    .forEach(branch => {
      const branchRootMessageId = getCanonicalRevisionRootIdFromMessageId(
        branch.fork_from_message_id || branch.root_message_id,
        byId
      )
      addBranchId(branchRootMessageId, branch.id)
    })

  return siblingsByRoot
}

function buildVisibleBranchPath(
  allMessages: Message[],
  branches: Record<string, ConversationBranch>,
  activeBranchId: string
): Message[] {
  if (allMessages.length === 0) {
    return []
  }

  const branch = branches[activeBranchId]
  const byId = buildMessageLookup(allMessages)
  const branchMessages = allMessages.filter(message => (
    getMessageBranchId(message) === activeBranchId && !message.metadata?.superseded
  ))

  const headId = branch?.head_message_id || getMessageId([...allMessages].reverse().find(
    message => getMessageBranchId(message) === activeBranchId && !message.metadata?.superseded
  ) || allMessages[allMessages.length - 1])

  if (!headId || !byId.has(headId)) {
    return branchMessages
  }

  const path: Message[] = []
  const seen = new Set<string>()
  let cursor: string | undefined = headId
  while (cursor && byId.has(cursor) && !seen.has(cursor)) {
    seen.add(cursor)
    const currentMessage: Message = byId.get(cursor)!
    path.push(currentMessage)
    cursor = currentMessage.parent_message_id || (currentMessage.metadata?.parent_message_id as string | undefined)
  }
  const visiblePath = path.reverse()

  if (activeBranchId === MAIN_BRANCH_ID && branchMessages.length > visiblePath.length) {
    const visibleIds = new Set(visiblePath.map(message => getMessageId(message)).filter(Boolean))
    const missingBranchMessages = branchMessages.some(message => {
      const messageId = getMessageId(message)
      return messageId ? !visibleIds.has(messageId) : true
    })
    if (missingBranchMessages) {
      return branchMessages
    }
  }

  return visiblePath
}

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

function withWelcomeMessage(items: Message[]): Message[] {
  return items.length > 0 ? items : [WELCOME_MESSAGE]
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
  // Only registered users may leave feedback; guests never see the controls.
  isRegistered?: boolean
  onMessageAdded?: (role: 'user' | 'assistant', content: string) => void
  useOnlineAgent?: boolean
  serviceDomainLock?: string
  backgroundTasks?: BackgroundRecommendationTask[]
  backgroundRequests?: BackgroundConversationRequest[]
  onTaskCreated?: (task: BackgroundRecommendationTask) => void
  onRequestStarted?: (request: BackgroundConversationRequest) => void
  onRequestCompleted?: (request: BackgroundConversationRequest) => void
  onRequestFailed?: (request: BackgroundConversationRequest) => void
}

export interface BackgroundRecommendationTask {
  taskId: string
  userId: string
  conversationId: string
  branchId: string
  parentMessageId?: string | null
  processingMessageId?: string | null
  source?: string
  createdAt: string
  updatedAt?: string
  status?: TaskStatus | null
  resultSaved?: boolean
  notified?: boolean
  resultMessageId?: string | null
  error?: string | null
}

export interface BackgroundConversationRequest {
  requestId: string
  userId: string
  conversationId: string
  branchId: string
  parentMessageId?: string | null
  userMessageId?: string | null
  query: string
  source?: string
  createdAt: string
  updatedAt?: string
  status: 'pending' | 'completed' | 'error'
  result?: RecommendationResponse | null
  resultSaved?: boolean
  notified?: boolean
  resultMessageId?: string | null
  error?: string | null
}

const EMPTY_BACKGROUND_TASKS: BackgroundRecommendationTask[] = []
const EMPTY_BACKGROUND_REQUESTS: BackgroundConversationRequest[] = []

export function Chat({ selectedTypes, selectedFlavors, currentModel, chatHistory, conversationId, userId, isRegistered = false, onMessageAdded, useOnlineAgent: useOnlineAgentProp, serviceDomainLock, backgroundTasks = EMPTY_BACKGROUND_TASKS, backgroundRequests = EMPTY_BACKGROUND_REQUESTS, onTaskCreated, onRequestStarted, onRequestCompleted, onRequestFailed }: ChatProps): JSX.Element {
  const [messages, setMessages] = useState<Message[]>([WELCOME_MESSAGE])
  const [allConversationMessages, setAllConversationMessages] = useState<Message[]>([])
  const [conversationBranches, setConversationBranches] = useState<Record<string, ConversationBranch>>({})
  const [branchSelectionState, setBranchSelectionState] = useState<Record<string, string>>({})
  const [activeBranchId, setActiveBranchId] = useState(MAIN_BRANCH_ID)
  const [editingMessage, setEditingMessage] = useState<{
    index: number
    id?: string
    branchId: string
    parentMessageId?: string | null
    originalContent: string
  } | null>(null)
  const [editInput, setEditInput] = useState('')
  const [isLoadingHistory, setIsLoadingHistory] = useState(false)
  // Surfaces backend persistence failures so a dropped save is never silent
  // (an unsaved message would otherwise vanish on reload / conversation switch).
  const [saveError, setSaveError] = useState<string | null>(null)
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [confirmationActionInFlight, setConfirmationActionInFlight] = useState(false)
  const [isListening, setIsListening] = useState(false)
  const useOnlineAgent = useOnlineAgentProp ?? false // 从 props 获取，默认 false
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const recognitionRef = useRef<any>(null)
  const messagesRef = useRef<Message[]>([WELCOME_MESSAGE])
  const allConversationMessagesRef = useRef<Message[]>([])
  const conversationBranchesRef = useRef<Record<string, ConversationBranch>>({})
  const branchSelectionStateRef = useRef<Record<string, string>>({})
  const activeBranchIdRef = useRef(MAIN_BRANCH_ID)
  const conversationIdRef = useRef<string | null | undefined>(conversationId)
  const userIdRef = useRef<string | undefined>(userId)
  const loadedConversationIdRef = useRef<string | null>(null)
  const confirmationActionInFlightRef = useRef(false)
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
  const backgroundTaskById = useMemo(() => {
    return new Map(backgroundTasks.map(task => [task.taskId, task]))
  }, [backgroundTasks])
  const getBackgroundTaskStatus = useCallback((taskId: string): TaskStatus | null => {
    return backgroundTaskById.get(taskId)?.status || null
  }, [backgroundTaskById])
  const hasPendingBackgroundRequest = useMemo(() => {
    if (!conversationId || !userId) return false
    return backgroundRequests.some(request => (
      request.userId === userId
      && request.conversationId === conversationId
      && request.status === 'pending'
    ))
  }, [backgroundRequests, conversationId, userId])
  const isBusy = loading || hasPendingBackgroundRequest

  useEffect(() => {
    messagesRef.current = messages
  }, [messages])

  useEffect(() => {
    allConversationMessagesRef.current = allConversationMessages
  }, [allConversationMessages])

  useEffect(() => {
    conversationBranchesRef.current = conversationBranches
  }, [conversationBranches])

  useEffect(() => {
    branchSelectionStateRef.current = branchSelectionState
  }, [branchSelectionState])

  useEffect(() => {
    activeBranchIdRef.current = activeBranchId
  }, [activeBranchId])

  useEffect(() => {
    conversationIdRef.current = conversationId
    userIdRef.current = userId
  }, [conversationId, userId])

  const isCurrentConversationScope = useCallback((
    scopeConversationId: string | null | undefined,
    scopeUserId: string | undefined
  ) => {
    return (conversationIdRef.current || null) === (scopeConversationId || null)
      && (userIdRef.current || undefined) === (scopeUserId || undefined)
  }, [])

  const startBackgroundRequest = useCallback((
    query: string,
    source: string,
    branchId: string,
    parentMessageId?: string | null,
    userMessageId?: string | null
  ): BackgroundConversationRequest | null => {
    if (!userId || !conversationId) return null
    const now = new Date().toISOString()
    const request: BackgroundConversationRequest = {
      requestId: makeClientRequestId(),
      userId,
      conversationId,
      branchId,
      parentMessageId: parentMessageId || null,
      userMessageId: userMessageId || null,
      query,
      source,
      createdAt: now,
      updatedAt: now,
      status: 'pending',
      resultSaved: false,
      notified: false,
    }
    onRequestStarted?.(request)
    return request
  }, [conversationId, onRequestStarted, userId])

  const completeBackgroundRequest = useCallback((
    request: BackgroundConversationRequest | null,
    result: RecommendationResponse,
    handledInCurrentConversation: boolean
  ) => {
    if (!request) return
    onRequestCompleted?.({
      ...request,
      status: 'completed',
      result,
      resultSaved: handledInCurrentConversation,
      notified: handledInCurrentConversation,
      updatedAt: new Date().toISOString(),
    })
  }, [onRequestCompleted])

  const failBackgroundRequest = useCallback((
    request: BackgroundConversationRequest | null,
    error: unknown,
    handledInCurrentConversation: boolean
  ) => {
    if (!request) return
    onRequestFailed?.({
      ...request,
      status: 'error',
      error: error instanceof Error ? error.message : String(error),
      resultSaved: handledInCurrentConversation,
      notified: handledInCurrentConversation,
      updatedAt: new Date().toISOString(),
    })
  }, [onRequestFailed])

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
    return messagesRef.current
      .filter(m => typeof m.content === 'string' && !m.metadata?.superseded)
      .slice(-10)
      .map(m => ({
        role: m.role,
        content: typeof m.content === 'string' ? m.content : ''
      }))
  }, [])

  // 记录后端持久化失败，向用户给出简洁提示
  const reportSaveError = useCallback((label: string, error: unknown) => {
    console.error(`Error saving ${label}:`, error)
    setSaveError(`Couldn't save your ${label} to the server — it may disappear when you reload or switch chats.`)
  }, [])

  // 保存用户消息的辅助函数
  const saveUserMessage = useCallback(async (content: string, metadata?: Record<string, any>) => {
    if (!conversationId || !userId || !onMessageAdded) return

    try {
      await addMessage(userId, conversationId, 'user', content, metadata)
      onMessageAdded('user', content)
      setSaveError(null)
    } catch (error) {
      reportSaveError('message', error)
    }
  }, [conversationId, userId, onMessageAdded, reportSaveError])

  // 保存推荐结果（包含完整数据）- 需要在 createProcessingView 之前定义
  const makeRecommendationResultKey = useCallback((
    result: RecommendationResponse,
    branchId: string,
    fallbackOperationId?: string | null
  ): string | null => {
    const resultId = extractResultId(result)
    if (resultId) return `result:${resultId}`
    const taskId = extractTaskId(result)
    if (taskId) return `task:${branchId}:${taskId}`
    return fallbackOperationId ? `operation:${branchId}:${fallbackOperationId}` : null
  }, [])

  const saveRecommendationResult = useCallback(async (
    result: RecommendationResponse,
    branchId: string = activeBranchIdRef.current,
    parentMessageId?: string | null,
    replaceMessageId?: string | null
  ) => {
    const identity = resolveRecommendationIdentity(result, { generateResultId: true })
    const resultForMessage = withRecommendationIdentity(result, identity)
    const resultKey = makeRecommendationResultKey(resultForMessage, branchId, replaceMessageId || parentMessageId)
    
    // 检查是否已经保存过
    if (resultKey && savedRecommendationIds.current.has(resultKey)) {
      console.log('[Chat] Recommendation result already saved, skipping:', resultKey)
      return
    }
    if (resultKey) {
      savedRecommendationIds.current.add(resultKey)
    }
    
    try {
      const textContent = resultForMessage.restaurants.length > 0
        ? `Found ${resultForMessage.restaurants.length} restaurant recommendations: ${resultForMessage.restaurants.map(r => r.name).join(', ')}`
        : 'No recommendations found'
      const resultMessageId = makeClientMessageId()
      const effectiveParentMessageId = parentMessageId ?? getMessageId(messagesRef.current[messagesRef.current.length - 1]) ?? null
      
      // 在metadata中保存完整的推荐结果数据
      const metadata = {
        type: 'recommendation',
        recommendation_data: resultForMessage,
        message_id: resultMessageId,
        branch_id: branchId,
        ...(identity.resultId ? { result_id: identity.resultId } : {}),
        ...(identity.taskId ? { task_id: identity.taskId } : {}),
        ...(identity.clientGeneratedResultId ? { client_generated_result_id: true } : {}),
        ...(effectiveParentMessageId ? { parent_message_id: effectiveParentMessageId } : {})
      }
      const resultMessage: Message = {
        id: resultMessageId,
        role: 'assistant',
        branch_id: branchId,
        parent_message_id: effectiveParentMessageId,
        content: <ResultsView data={resultForMessage} onAddressClick={handleAddressClick} />,
        metadata,
      }
      
      if (conversationId && userId && onMessageAdded) {
        await addMessage(userId, conversationId, 'assistant', textContent, metadata)
        onMessageAdded('assistant', textContent)
        setSaveError(null)
      }

      const replaceOrAppend = (items: Message[]) => {
        const replacementIndex = replaceMessageId
          ? items.findIndex(item => getMessageId(item) === replaceMessageId)
          : -1
        if (replacementIndex >= 0) {
          const next = [...items]
          next[replacementIndex] = resultMessage
          return next
        }
        if (items.some(item => getMessageId(item) === resultMessageId)) {
          return items
        }
        return [...items, resultMessage]
      }

      const nextVisibleMessages = replaceOrAppend(messagesRef.current)
      messagesRef.current = nextVisibleMessages
      setMessages(nextVisibleMessages)
      setAllConversationMessages(prev => {
        const next = replaceOrAppend(prev)
        allConversationMessagesRef.current = next
        return next
      })
      setConversationBranches(prev => {
        const derived = deriveBranchesFromMessages(allConversationMessagesRef.current, prev)
        const existing = derived[branchId]
        if (!existing) return derived
        const next = {
          ...derived,
          [branchId]: {
            ...existing,
            head_message_id: resultMessageId,
            updated_at: new Date().toISOString(),
          }
        }
        conversationBranchesRef.current = next
        return next
      })
      
      console.log('[Chat] Recommendation result saved:', resultKey || resultMessageId)
    } catch (error) {
      if (resultKey) {
        savedRecommendationIds.current.delete(resultKey)
      }
      reportSaveError('recommendation', error)
    }
  }, [conversationId, handleAddressClick, makeRecommendationResultKey, userId, onMessageAdded, reportSaveError])

  // 把当前会话里已完成的后台任务结果固化为持久的推荐消息（替换处理中占位，没有则追加）。
  // MetaRecPage.saveCompletedBackgroundTask 只把结果写回后端，无法触达本组件的 state；
  // 缺了这一步，任务完成后处理中占位会在 resultSaved 时被清除，推荐结果要等到刷新页面/
  // 切回会话重新拉取后才显示。复用后端使用的 `task-result-<taskId>` 消息 ID，使刷新后
  // 加载到的同一条结果能够去重。仅更新前端，不重复写后端。
  const materializeCompletedResults = useCallback((items: Message[]): Message[] => {
    if (!conversationId || !userId) return items
    let next = items
    backgroundTasks.forEach(task => {
      if (task.userId !== userId || task.conversationId !== conversationId) return
      const result = task.status?.status === 'completed' ? task.status.result : null
      if (!result) return
      const resultMessageId = task.resultMessageId || `task-result-${task.taskId}`
      // Skip if this result is already on screen — either our materialized copy,
      // or the backend-persisted recommendation re-fetched on reload (same
      // task_id but a server-assigned message id).
      const alreadyShown = next.some(item => (
        getMessageId(item) === resultMessageId
        || (item.metadata?.task_id === task.taskId && item.metadata?.type === 'recommendation')
      ))
      if (alreadyShown) return
      const branchId = task.branchId || activeBranchIdRef.current
      const parentMessageId = task.parentMessageId || null
      const identity = resolveRecommendationIdentity(result, { fallbackTaskId: task.taskId })
      const resultForMessage = withRecommendationIdentity(result, identity)
      const resultMessage: Message = {
        id: resultMessageId,
        role: 'assistant',
        branch_id: branchId,
        parent_message_id: parentMessageId,
        content: <ResultsView data={resultForMessage} onAddressClick={handleAddressClick} />,
        metadata: {
          type: 'recommendation',
          recommendation_data: resultForMessage,
          message_id: resultMessageId,
          branch_id: branchId,
          task_id: identity.taskId || task.taskId,
          ...(identity.resultId ? { result_id: identity.resultId } : {}),
          ...(identity.clientGeneratedResultId ? { client_generated_result_id: true } : {}),
          ...(parentMessageId ? { parent_message_id: parentMessageId } : {}),
        },
      }
      const idx = next.findIndex(item => (
        item.metadata?.task_id === task.taskId && item.metadata?.type === 'processing'
      ))
      next = idx >= 0
        ? next.map((item, i) => (i === idx ? resultMessage : item))
        : [...next, resultMessage]
      const resultKey = makeRecommendationResultKey(resultForMessage, branchId, resultMessageId)
      if (resultKey) {
        savedRecommendationIds.current.add(resultKey)
      }
    })
    return next
  }, [backgroundTasks, conversationId, userId, handleAddressClick, makeRecommendationResultKey])

  // 创建ProcessingView的辅助函数
  const createProcessingView = useCallback((
    taskId: string,
    branchId: string = activeBranchIdRef.current,
    parentMessageId?: string | null,
    processingMessageId?: string | null,
    initialThinkingSteps?: ThinkingStep[] | null
  ) => {
    return <ProcessingView 
      taskId={taskId}
      status={getBackgroundTaskStatus(taskId)}
      initialSteps={initialThinkingSteps || undefined}
      userId={userId || undefined}
      conversationId={conversationId || undefined}
      onAddressClick={handleAddressClick}
    />
  }, [userId, conversationId, handleAddressClick, getBackgroundTaskStatus])

  // 处理任务创建的回调函数 (把重复的处理过程模块化)
  const handleTaskCreated = useCallback((taskId: string, thinkingSteps?: ThinkingStep[], source: string = 'unknown') => {
    console.log('[Chat] Task created:', {
      source,
      taskId,
      thinkingSteps
    })
    const branchId = activeBranchIdRef.current
    const visibleMessages = messagesRef.current
    const parentMessageId = getMessageId(visibleMessages[visibleMessages.length - 1]) || null
    const processingMessageId = makeClientMessageId()
    appendMessage({
      id: processingMessageId,
      role: 'assistant',
      branch_id: branchId,
      parent_message_id: parentMessageId,
      content: createProcessingView(taskId, branchId, parentMessageId, processingMessageId, thinkingSteps),
      metadata: {
        type: 'processing',
        task_id: taskId,
        thinking_steps: thinkingSteps || [],
      },
    })
    if (userId && conversationId) {
      onTaskCreated?.({
        taskId,
        userId,
        conversationId,
        branchId,
        parentMessageId,
        processingMessageId,
        source,
        createdAt: new Date().toISOString(),
        status: {
          task_id: taskId,
          status: 'pending',
          progress: 0,
          message: 'Task created',
          result: null,
          error: null,
          metadata: { branch_id: branchId },
        },
        resultSaved: false,
        notified: false,
      })
    }
  }, [appendMessage, createProcessingView, conversationId, onTaskCreated, userId])

  const mergeVirtualProcessingMessages = useCallback((items: Message[]): Message[] => {
    if (!conversationId || !userId) return items
    const existingTaskIds = new Set(
      items
        .map(item => item.metadata?.task_id)
        .filter((taskId): taskId is string => typeof taskId === 'string' && taskId.length > 0)
    )
    const pendingVirtualMessages = backgroundTasks
      .filter(task => (
        task.userId === userId
        && task.conversationId === conversationId
        && !existingTaskIds.has(task.taskId)
        && !(task.status?.status === 'completed' && task.resultSaved)
        && !(task.status?.status === 'error' && task.notified)
      ))
      .map((task): Message => {
        const branchId = task.branchId || MAIN_BRANCH_ID
        const processingMessageId = task.processingMessageId || `processing-${task.taskId}`
        return {
          id: processingMessageId,
          role: 'assistant',
          branch_id: branchId,
          parent_message_id: task.parentMessageId || null,
          content: createProcessingView(task.taskId, branchId, task.parentMessageId || null, processingMessageId),
          metadata: {
            type: 'processing',
            task_id: task.taskId,
            message_id: processingMessageId,
            branch_id: branchId,
            ...(task.parentMessageId ? { parent_message_id: task.parentMessageId } : {}),
            virtual_task: true,
          },
        }
      })
    return pendingVirtualMessages.length > 0 ? [...items, ...pendingVirtualMessages] : items
  }, [backgroundTasks, conversationId, createProcessingView, userId])

  // 加载历史对话消息
  useEffect(() => {
    let cancelled = false
    const requestedConversationId = conversationId || null

    const loadHistory = async () => {
      loadedConversationIdRef.current = null
      setLoading(false)
      setFloatingConfirmation(null)
      setEditingMessage(null)
      setEditInput('')
      setSaveError(null)
      messagesRef.current = [WELCOME_MESSAGE]
      allConversationMessagesRef.current = []
      conversationBranchesRef.current = {}
      branchSelectionStateRef.current = {}
      activeBranchIdRef.current = MAIN_BRANCH_ID
      setMessages([WELCOME_MESSAGE])
      setAllConversationMessages([])
      setConversationBranches({})
      setBranchSelectionState({})
      setActiveBranchId(MAIN_BRANCH_ID)

      if (!conversationId || !userId) {
        return
      }
      
      setIsLoadingHistory(true)
      try {
        const conversation = await getConversation(userId, conversationId)
        if (cancelled || conversationIdRef.current !== requestedConversationId) {
          return
        }
        
        if (conversation && conversation.messages && conversation.messages.length > 0) {
          // 初始化已保存的推荐结果ID集合
          const savedIds = new Set<string>()
          
          // 将历史消息转换为Message格式，并恢复推荐结果UI
          const historyMessages: Message[] = conversation.messages.map(msg => {
            const metadata = msg.metadata || null
            const messageId = msg.id || (metadata?.message_id as string | undefined)
            const branchId = msg.branch_id || (metadata?.branch_id as string | undefined) || MAIN_BRANCH_ID
            const parentMessageId = msg.parent_message_id || (metadata?.parent_message_id as string | undefined) || null
            const forkFromMessageId = msg.fork_from_message_id || (metadata?.fork_from_message_id as string | undefined) || null
            const revisionOfMessageId = msg.revision_of_message_id || (metadata?.revision_of_message_id as string | undefined) || null
            if (msg.metadata?.type === 'confirmation' && msg.metadata?.confirmation_request) {
              const confirmationRequest = msg.metadata.confirmation_request as ConfirmationRequest
              return {
                id: messageId,
                role: normalizeMessageRole(msg.role),
                branch_id: branchId,
                parent_message_id: parentMessageId,
                fork_from_message_id: forkFromMessageId,
                revision_of_message_id: revisionOfMessageId,
                content: <ConfirmationMessageView
                  confirmationRequest={confirmationRequest}
                  showPreferences={!!msg.metadata.show_preferences}
                  onPreferenceConfirm={msg.metadata.show_preferences ? handlePreferenceConfirm : undefined}
                />,
                metadata
              }
            }
            // 检查是否有推荐结果数据
            if (msg.metadata?.type === 'recommendation' && msg.metadata?.recommendation_data) {
              const recommendationData = msg.metadata.recommendation_data as RecommendationResponse
              const identity = resolveRecommendationIdentity(recommendationData, {
                fallbackResultId: typeof metadata?.result_id === 'string' ? metadata.result_id : null,
                fallbackTaskId: typeof metadata?.task_id === 'string' ? metadata.task_id : null,
              })
              const normalizedRecommendationData = withRecommendationIdentity(recommendationData, identity)
              const recommendationMetadata = {
                ...metadata,
                recommendation_data: normalizedRecommendationData,
                ...(identity.resultId ? { result_id: identity.resultId } : {}),
                ...(identity.taskId ? { task_id: identity.taskId } : {}),
                ...(identity.clientGeneratedResultId ? { client_generated_result_id: true } : {}),
              }
              // 只用稳定身份初始化去重集合；legacy 无 id 的消息不再用内容反推。
              const resultKey = makeRecommendationResultKey(normalizedRecommendationData, branchId, messageId)
              if (resultKey) {
                savedIds.add(resultKey)
              }
              
              return {
                id: messageId,
                role: normalizeMessageRole(msg.role),
                branch_id: branchId,
                parent_message_id: parentMessageId,
                fork_from_message_id: forkFromMessageId,
                revision_of_message_id: revisionOfMessageId,
                content: <ResultsView
                  data={normalizedRecommendationData}
                  onAddressClick={handleAddressClick}
                />,
                metadata: recommendationMetadata
              }
            }
            // 普通文本消息
            return {
              id: messageId,
              role: normalizeMessageRole(msg.role),
              branch_id: branchId,
              parent_message_id: parentMessageId,
              fork_from_message_id: forkFromMessageId,
              revision_of_message_id: revisionOfMessageId,
              content: msg.content,
              metadata
            }
          })
          
          // 更新已保存的推荐结果ID集合
          savedRecommendationIds.current = savedIds
          
          const historyWithVirtualTasks = mergeVirtualProcessingMessages(historyMessages)
          const branches = deriveBranchesFromMessages(historyWithVirtualTasks, conversation.branches || {})
          const selectionState = hydrateSelectionStateFromActiveBranch(
            conversation.active_branch_id || MAIN_BRANCH_ID,
            historyWithVirtualTasks,
            branches,
            conversation.branch_selection_state || {}
          )
          const active = resolveSelectedBranchId(
            conversation.active_branch_id || MAIN_BRANCH_ID,
            historyWithVirtualTasks,
            branches,
            selectionState
          )
          allConversationMessagesRef.current = historyWithVirtualTasks
          conversationBranchesRef.current = branches
          branchSelectionStateRef.current = selectionState
          activeBranchIdRef.current = active
          setAllConversationMessages(historyWithVirtualTasks)
          setConversationBranches(branches)
          setBranchSelectionState(selectionState)
          setActiveBranchId(active)
          const visibleMessages = withWelcomeMessage(buildVisibleBranchPath(historyWithVirtualTasks, branches, active))
          messagesRef.current = visibleMessages
          setMessages(visibleMessages)
          loadedConversationIdRef.current = requestedConversationId
        } else {
          // 如果没有历史消息，显示欢迎消息
          messagesRef.current = [WELCOME_MESSAGE]
          allConversationMessagesRef.current = []
          conversationBranchesRef.current = {}
          branchSelectionStateRef.current = {}
          activeBranchIdRef.current = MAIN_BRANCH_ID
          setMessages([WELCOME_MESSAGE])
          setAllConversationMessages([])
          setConversationBranches({})
          setBranchSelectionState({})
          setActiveBranchId(MAIN_BRANCH_ID)
          loadedConversationIdRef.current = requestedConversationId
        }
      } catch (error) {
        if (cancelled || conversationIdRef.current !== requestedConversationId) {
          return
        }
        console.error('Error loading conversation history:', error)
        // 如果加载失败，显示欢迎消息
        messagesRef.current = [WELCOME_MESSAGE]
        allConversationMessagesRef.current = []
        conversationBranchesRef.current = {}
        branchSelectionStateRef.current = {}
        activeBranchIdRef.current = MAIN_BRANCH_ID
        setMessages([WELCOME_MESSAGE])
        setAllConversationMessages([])
        setConversationBranches({})
        setBranchSelectionState({})
        setActiveBranchId(MAIN_BRANCH_ID)
        loadedConversationIdRef.current = requestedConversationId
      } finally {
        if (!cancelled && conversationIdRef.current === requestedConversationId) {
          setIsLoadingHistory(false)
        }
      }
    }
    
    loadHistory()
    return () => {
      cancelled = true
    }
  }, [conversationId, userId, handleAddressClick, makeRecommendationResultKey])

  // 进入会话（历史加载完成）后滚动到最新消息，而不是停在最顶部
  useEffect(() => {
    if (isLoadingHistory) return
    if (!conversationId || loadedConversationIdRef.current !== conversationId) return
    const el = scrollRef.current
    if (!el) return
    // 等消息（含推荐卡片）渲染提交后再滚动到底部
    const raf = requestAnimationFrame(() => {
      el.scrollTop = el.scrollHeight
    })
    return () => cancelAnimationFrame(raf)
  }, [isLoadingHistory, conversationId])

  useEffect(() => {
    if (!conversationId || !userId) return
    if (loadedConversationIdRef.current !== conversationId) return
    setAllConversationMessages(prev => {
      const withoutStaleVirtuals = prev.filter(message => {
        if (!(message.metadata?.virtual_task && message.metadata?.type === 'processing')) return true
        const taskId = message.metadata?.task_id
        if (typeof taskId !== 'string') return false
        const task = backgroundTaskById.get(taskId)
        if (!task || task.userId !== userId || task.conversationId !== conversationId) return false
        if (task.status?.status === 'completed' && task.resultSaved) return false
        if (task.status?.status === 'error' && task.notified) return false
        return true
      })
      const next = materializeCompletedResults(mergeVirtualProcessingMessages(withoutStaleVirtuals))
      allConversationMessagesRef.current = next
      const branches = deriveBranchesFromMessages(next, conversationBranchesRef.current)
      conversationBranchesRef.current = branches
      setConversationBranches(branches)
      const resolvedActiveBranchId = resolveSelectedBranchId(
        activeBranchIdRef.current,
        next,
        branches,
        branchSelectionStateRef.current
      )
      if (resolvedActiveBranchId !== activeBranchIdRef.current) {
        activeBranchIdRef.current = resolvedActiveBranchId
        setActiveBranchId(resolvedActiveBranchId)
      }
      const visibleMessages = withWelcomeMessage(buildVisibleBranchPath(next, branches, resolvedActiveBranchId))
      messagesRef.current = visibleMessages
      setMessages(visibleMessages)
      return next
    })
  }, [backgroundTaskById, backgroundTasks, conversationId, materializeCompletedResults, mergeVirtualProcessingMessages, userId])

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

  function buildConfirmationMetadata(
    response: RecommendationResponse,
    extraMetadata: Record<string, any> = {},
    showPreferences = response.intent === 'confirmation_no'
  ): Record<string, any> {
    const confirmationRequest = response.confirmation_request
    const hitlState = response.hitl_state || {
      node: 'collect_confirm_preferences',
      status: 'awaiting_confirmation',
      intent: response.intent || 'query',
      preferences: confirmationRequest?.preferences || response.preferences || {},
      needs_confirmation: confirmationRequest?.needs_confirmation ?? true,
      confirmation_request: confirmationRequest,
    }
    return {
      ...extraMetadata,
      type: 'confirmation',
      confirmation_request: confirmationRequest,
      hitl_state: hitlState,
      show_preferences: showPreferences,
    }
  }

  function getActiveHitlState(action: 'confirm' | 'reject'): Record<string, any> | undefined {
    const lastConfirmation = [...messagesRef.current].reverse().find(message => (
      message.role === 'assistant'
      && message.metadata?.type === 'confirmation'
      && message.metadata?.hitl_state?.node === 'collect_confirm_preferences'
      && message.metadata?.hitl_state?.status === 'awaiting_confirmation'
    ))
    if (!lastConfirmation?.metadata?.hitl_state) {
      return undefined
    }
    return {
      ...(lastConfirmation.metadata.hitl_state as Record<string, any>),
      action,
    }
  }

  function buildPreferenceRevisionConfirmation(hitlState?: Record<string, any>): {
    confirmationRequest: ConfirmationRequest
    hitlState: Record<string, any>
  } {
    const existingConfirmation = hitlState?.confirmation_request as ConfirmationRequest | undefined
    const preferences = (
      existingConfirmation?.preferences
      || hitlState?.preferences
      || {}
    ) as Record<string, any>
    const confirmationRequest: ConfirmationRequest = {
      message: 'No problem. Update the preferences below, then confirm to continue.',
      preferences,
      needs_confirmation: true,
    }
    return {
      confirmationRequest,
      hitlState: {
        ...(hitlState || {}),
        node: 'collect_confirm_preferences',
        status: 'awaiting_clarification',
        intent: 'confirmation_no',
        action: 'reject',
        preferences,
        pending_preferences: preferences,
        confirmation_request: confirmationRequest,
      },
    }
  }

  function getLatestHitlState(): Record<string, any> | undefined {
    const lastHitlMessage = [...messagesRef.current].reverse().find(message => (
      message.role === 'assistant'
      && message.metadata?.hitl_state?.node === 'collect_confirm_preferences'
      && ['awaiting_confirmation', 'awaiting_clarification'].includes(String(message.metadata?.hitl_state?.status || ''))
    ))
    return lastHitlMessage?.metadata?.hitl_state as Record<string, any> | undefined
  }

  function buildAssistantMetadataFromResponse(response: RecommendationResponse): Record<string, any> | undefined {
    if (!response.hitl_state) return undefined
    return {
      hitl_state: response.hitl_state,
      ...(response.domain ? { domain: response.domain } : {}),
    }
  }

  function appendMessage(msg: Message): Message {
    const id = msg.id || makeClientMessageId()
    const visibleMessages = messagesRef.current
    const branchId = msg.branch_id || (msg.metadata?.branch_id as string | undefined) || activeBranchIdRef.current
    const parentMessageId = msg.parent_message_id || (msg.metadata?.parent_message_id as string | undefined) || getMessageId(visibleMessages[visibleMessages.length - 1]) || null
    const nextMessage = {
      ...msg,
      id,
      branch_id: branchId,
      parent_message_id: parentMessageId,
      metadata: {
        ...(msg.metadata || {}),
        message_id: id,
        branch_id: branchId,
        ...(parentMessageId ? { parent_message_id: parentMessageId } : {})
      }
    }
    const nextVisibleMessages = [...visibleMessages, nextMessage]
    messagesRef.current = nextVisibleMessages
    setMessages(nextVisibleMessages)
    if (nextMessage.role === 'user' || nextMessage.role === 'assistant') {
      const nextAllMessages = [...allConversationMessagesRef.current, nextMessage]
      setAllConversationMessages(prev => {
        const next = [...prev, nextMessage]
        allConversationMessagesRef.current = next
        return next
      })
      setConversationBranches(prev => {
        const derived = deriveBranchesFromMessages(nextAllMessages, prev)
        const existing = derived[branchId]
        const next = existing
          ? {
              ...derived,
              [branchId]: {
                ...existing,
                head_message_id: id,
                updated_at: new Date().toISOString(),
              }
            }
          : derived
        conversationBranchesRef.current = next
        return next
      })
    }
    queueMicrotask(() => {
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
    })
    return nextMessage
  }

  function startEditingMessage(index: number, message: Message) {
    if (message.role !== 'user' || typeof message.content !== 'string') return
    const visibleMessages = messagesRef.current
    const parentMessageId = (
      message.parent_message_id
      || (message.metadata?.parent_message_id as string | undefined)
      || getMessageId(visibleMessages[index - 1])
      || null
    )
    setEditingMessage({
      index,
      id: getMessageId(message),
      branchId: getMessageBranchId(message),
      parentMessageId,
      originalContent: message.content,
    })
    setEditInput(message.content)
    setFloatingConfirmation(null)
  }

  function cancelEditingMessage() {
    setEditingMessage(null)
    setEditInput('')
  }

  async function switchBranch(branchId: string, sourceMessage?: Message) {
    const allMessages = allConversationMessagesRef.current.length > 0
      ? allConversationMessagesRef.current
      : allConversationMessages
    const branches = deriveBranchesFromMessages(allMessages, conversationBranchesRef.current)
    if (branches !== conversationBranchesRef.current) {
      conversationBranchesRef.current = branches
      setConversationBranches(branches)
    }
    if (!conversationId || !userId || branchId === activeBranchIdRef.current || !branches[branchId]) return
    const previousBranchId = activeBranchIdRef.current
    const previousMessages = messagesRef.current
    const previousBranchSelectionState = branchSelectionStateRef.current
    const byId = buildMessageLookup(allMessages)
    const sourceMessageId = sourceMessage
      ? getCanonicalRevisionRootId(sourceMessage, byId)
      : getBranchRevisionRootId(branchId, branches, byId)
    const nextBranchSelectionState = sourceMessageId
      ? { ...previousBranchSelectionState, [sourceMessageId]: branchId }
      : previousBranchSelectionState

    branchSelectionStateRef.current = nextBranchSelectionState
    setBranchSelectionState(nextBranchSelectionState)
    const effectiveBranchId = resolveSelectedBranchId(
      branchId,
      allMessages,
      branches,
      nextBranchSelectionState
    )
    activeBranchIdRef.current = effectiveBranchId
    setActiveBranchId(effectiveBranchId)
    const nextMessages = withWelcomeMessage(buildVisibleBranchPath(allMessages, branches, effectiveBranchId))
    messagesRef.current = nextMessages
    setMessages(nextMessages)
    setFloatingConfirmation(null)
    setEditingMessage(null)

    try {
      const updatedConversation = await setActiveConversationBranch(
        userId,
        conversationId,
        branchId,
        sourceMessageId
      )
      const persistedSelectionState = {
        ...nextBranchSelectionState,
        ...(updatedConversation.branch_selection_state || {}),
      }
      branchSelectionStateRef.current = persistedSelectionState
      setBranchSelectionState(persistedSelectionState)
      const persistedEffectiveBranchId = resolveSelectedBranchId(
        branchId,
        allMessages,
        branches,
        persistedSelectionState
      )
      if (persistedEffectiveBranchId !== activeBranchIdRef.current) {
        activeBranchIdRef.current = persistedEffectiveBranchId
        setActiveBranchId(persistedEffectiveBranchId)
        const persistedMessages = withWelcomeMessage(buildVisibleBranchPath(allMessages, branches, persistedEffectiveBranchId))
        messagesRef.current = persistedMessages
        setMessages(persistedMessages)
      }
    } catch (error) {
      console.error('Error switching branch:', error)
      activeBranchIdRef.current = previousBranchId
      messagesRef.current = previousMessages
      branchSelectionStateRef.current = previousBranchSelectionState
      setActiveBranchId(previousBranchId)
      setMessages(previousMessages)
      setBranchSelectionState(previousBranchSelectionState)
    }
  }

  async function submitEditedMessage() {
    if (!editingMessage) return
    await regenerateFromUserMessage(
      { id: editingMessage.id, index: editingMessage.index, parentMessageId: editingMessage.parentMessageId },
      editInput,
    )
  }

  // Regenerate an assistant answer by re-running the user turn that prompted it.
  // Lets a single "regenerate" click produce a fresh response without the user
  // manually editing/forking the question.
  async function regenerateAssistantMessage(assistantIndex: number) {
    if (isBusy) return
    let sourceIndex = -1
    for (let idx = assistantIndex - 1; idx >= 0; idx--) {
      const candidate = messages[idx]
      if (candidate?.role === 'user' && typeof candidate.content === 'string') {
        sourceIndex = idx
        break
      }
    }
    if (sourceIndex < 0) return
    const sourceMessage = messages[sourceIndex]
    const parentMessageId = (
      sourceMessage.parent_message_id
      || (sourceMessage.metadata?.parent_message_id as string | undefined)
      || getMessageId(messages[sourceIndex - 1])
      || null
    )
    setFloatingConfirmation(null)
    await regenerateFromUserMessage(
      { id: getMessageId(sourceMessage), index: sourceIndex, parentMessageId },
      sourceMessage.content as string,
    )
  }

  // Re-run a user turn's query as a branch fork, producing a fresh assistant
  // answer. Shared by the user-message edit flow and the regenerate button.
  async function regenerateFromUserMessage(
    source: { id?: string; index: number; parentMessageId?: string | null },
    rawText: string,
  ) {
    const trimmed = rawText.trim()
    if (!trimmed) return
    const requestConversationId = conversationId || null
    const requestUserId = userId

    const replayFromMessageId = source.id || makeClientMessageId()
    const newMessageId = makeClientMessageId()
    const branchId = `branch-${newMessageId}`
    const sourceIndex = source.id
      ? messages.findIndex(message => getMessageId(message) === source.id)
      : source.index
    const visibleSourceIndex = sourceIndex >= 0 ? sourceIndex : source.index
    const persistedSourceMessage = source.id
      ? allConversationMessagesRef.current.find(message => getMessageId(message) === source.id)
      : undefined
    const editedSourceMessage = persistedSourceMessage || messages[visibleSourceIndex]
    const parentMessageId = (
      editedSourceMessage?.parent_message_id
      || (editedSourceMessage?.metadata?.parent_message_id as string | undefined)
      || source.parentMessageId
      || getMessageId(messages[visibleSourceIndex - 1])
      || null
    )
    const previousMessages = messages.slice(0, visibleSourceIndex)
    const editedMessage: Message = {
      id: newMessageId,
      role: 'user',
      content: trimmed,
      branch_id: branchId,
      parent_message_id: parentMessageId,
      fork_from_message_id: replayFromMessageId,
      revision_of_message_id: replayFromMessageId,
      metadata: {
        message_id: newMessageId,
        branch_id: branchId,
        parent_message_id: parentMessageId,
        fork_from_message_id: replayFromMessageId,
        revision_of_message_id: replayFromMessageId,
        time_travel: {
          mode: 'branch_fork',
          replay_from_message_id: replayFromMessageId,
          branch_id: branchId
        }
      }
    }
    const nextMessages = [...previousMessages, editedMessage]
    const now = new Date().toISOString()
    const nextBranches = deriveBranchesFromMessages(
      [...allConversationMessagesRef.current, editedMessage],
      {
        ...conversationBranchesRef.current,
        [branchId]: {
          id: branchId,
          parent_branch_id: getMessageBranchId(editedSourceMessage || editedMessage),
          fork_from_message_id: replayFromMessageId,
          root_message_id: newMessageId,
          head_message_id: newMessageId,
          title: 'Branch',
          created_at: now,
          updated_at: now,
        },
      }
    )
    const sourceRootMessageId = editedSourceMessage
      ? getCanonicalRevisionRootId(editedSourceMessage, buildMessageLookup(allConversationMessagesRef.current))
      : replayFromMessageId
    const nextBranchSelectionState = sourceRootMessageId
      ? { ...branchSelectionStateRef.current, [sourceRootMessageId]: branchId }
      : branchSelectionStateRef.current
    setAllConversationMessages(prev => {
      const next = [...prev, editedMessage]
      allConversationMessagesRef.current = next
      return next
    })
    conversationBranchesRef.current = nextBranches
    branchSelectionStateRef.current = nextBranchSelectionState
    activeBranchIdRef.current = branchId
    messagesRef.current = nextMessages
    setConversationBranches(nextBranches)
    setBranchSelectionState(nextBranchSelectionState)
    setActiveBranchId(branchId)
    setMessages(nextMessages)
    setEditingMessage(null)
    setEditInput('')
    setLoading(true)

    await saveUserMessage(trimmed, editedMessage.metadata || undefined)

    const conversationHistory = nextMessages
      .filter(m => typeof m.content === 'string' && !m.metadata?.superseded)
      .slice(-10)
      .map(m => ({ role: m.role, content: String(m.content) }))
    const backgroundRequest = startBackgroundRequest(
      trimmed,
      'time_travel_edit',
      branchId,
      parentMessageId,
      newMessageId
    )

    try {
      const response = await recommend(
        trimmed,
        userId || "default",
        conversationHistory,
        conversationId || undefined,
        useOnlineAgent,
        {
          timeTravel: {
            sourceMessageId: newMessageId,
            replayFromMessageId,
            branchId,
            parentMessageId: parentMessageId || undefined,
            timeTravelMode: 'branch_fork'
          },
          domainLock: serviceDomainLock,
          ...(getLatestHitlState() ? { hitlState: getLatestHitlState() } : {}),
        }
      )

      if (!isCurrentConversationScope(requestConversationId, requestUserId)) {
        completeBackgroundRequest(backgroundRequest, response, false)
        return
      }

      if (response.llm_reply) {
        const llmMetadata = {
          ...(buildAssistantMetadataFromResponse(response) || {}),
          time_travel: { branch_id: branchId, replay_from_message_id: replayFromMessageId }
        }
        const appendedAssistant = appendMessage({ role: 'assistant', content: response.llm_reply, metadata: llmMetadata })
        saveAssistantMessage(appendedAssistant.content, response.llm_reply, appendedAssistant.metadata || undefined)
      } else if (response.confirmation_request) {
        const isGuidanceCase = response.intent === 'confirmation_no'
        if (!isGuidanceCase) {
          const handlers = createConfirmationHandlers()
          setFloatingConfirmation(handlers)
        }
        const confirmationContent = <ConfirmationMessageView
          confirmationRequest={response.confirmation_request}
          showPreferences={isGuidanceCase}
          onPreferenceConfirm={isGuidanceCase ? handlePreferenceConfirm : undefined}
        />
        const confirmationMetadata = buildConfirmationMetadata(response, {
          time_travel: { branch_id: branchId, replay_from_message_id: replayFromMessageId }
        }, isGuidanceCase)
        const appendedAssistant = appendMessage({ role: 'assistant', content: confirmationContent, metadata: confirmationMetadata })
        saveAssistantMessage(appendedAssistant.content, response.confirmation_request.message, appendedAssistant.metadata || undefined)
      } else if (response.thinking_steps) {
        const taskId = extractTaskId(response)
        if (taskId) {
          handleTaskCreated(taskId, response.thinking_steps, 'time_travel_edit')
        }
      } else if (response.restaurants) {
        saveRecommendationResult(response, branchId, getMessageId(editedMessage) || parentMessageId)
      }
      completeBackgroundRequest(backgroundRequest, response, true)
    } catch (err: any) {
      if (!isCurrentConversationScope(requestConversationId, requestUserId)) {
        failBackgroundRequest(backgroundRequest, err, false)
        return
      }
      appendMessage({
        role: 'assistant',
        content: (
          <div className="content" style={{ borderColor: 'var(--error)' }}>
            Failed to regenerate from edited message. {err?.message || 'Unknown error'}
          </div>
        ),
      })
      failBackgroundRequest(backgroundRequest, err, true)
    } finally {
      if (isCurrentConversationScope(requestConversationId, requestUserId)) {
        setLoading(false)
      }
    }
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
      setSaveError(null)
    } catch (error) {
      reportSaveError('reply', error)
    }
  }

  // 处理preference确认的回调函数
  const handlePreferenceConfirm = async (summary: string) => {
    const requestConversationId = conversationId || null
    const requestUserId = userId
    // 添加用户消息
    const userMessage: Message = { role: 'user', content: summary }
    const appendedUser = appendMessage(userMessage)
    
    // 保存用户消息到后端
    await saveUserMessage(summary, appendedUser.metadata || undefined)
    
    // 发送请求
    setLoading(true)
    let backgroundRequest: BackgroundConversationRequest | null = null
    try {
      const conversationHistory = buildConversationHistory()
      backgroundRequest = startBackgroundRequest(
        summary,
        'preference_confirm',
        getMessageBranchId(appendedUser),
        appendedUser.parent_message_id || null,
        getMessageId(appendedUser) || null
      )
      
      const res: RecommendationResponse = await recommend(
        summary, 
        userId || "default", 
        conversationHistory, 
        conversationId || undefined, 
        useOnlineAgent,
        {
          scopeBranchId: getMessageBranchId(appendedUser),
          ...(serviceDomainLock ? { domainLock: serviceDomainLock } : {}),
          ...(getLatestHitlState() ? { hitlState: getLatestHitlState() } : {}),
        }
      )

      if (!isCurrentConversationScope(requestConversationId, requestUserId)) {
        completeBackgroundRequest(backgroundRequest, res, false)
        return
      }
      
      // 处理响应
      if (res.llm_reply) {
        const llmMetadata = buildAssistantMetadataFromResponse(res)
        const appendedAssistant = appendMessage({ role: 'assistant', content: res.llm_reply, metadata: llmMetadata })
        saveAssistantMessage(appendedAssistant.content, res.llm_reply, appendedAssistant.metadata || undefined)
      } else if (res.confirmation_request) {
        const isGuidanceCase = res.intent === 'confirmation_no'
        const confirmationContent = <ConfirmationMessageView
          confirmationRequest={res.confirmation_request}
          showPreferences={isGuidanceCase}
        />
        const confirmationMetadata = buildConfirmationMetadata(res, {}, isGuidanceCase)
        const appendedAssistant = appendMessage({ role: 'assistant', content: confirmationContent, metadata: confirmationMetadata })
        saveAssistantMessage(appendedAssistant.content, res.confirmation_request.message, appendedAssistant.metadata || undefined)
        // 只有需要确认用户需求时才设置悬浮确认按钮
        if (!isGuidanceCase) {
          const handlers = createConfirmationHandlers()
          setFloatingConfirmation(handlers)
        }
      } else if (res.thinking_steps) {
        const taskId = extractTaskId(res)
        if (taskId) {
          handleTaskCreated(taskId, res.thinking_steps, 'preference_confirm')
        }
      } else if (res.restaurants && res.restaurants.length > 0) {
        saveRecommendationResult(res)
      }
      completeBackgroundRequest(backgroundRequest, res, true)
    } catch (error: any) {
      if (!isCurrentConversationScope(requestConversationId, requestUserId)) {
        failBackgroundRequest(backgroundRequest, error, false)
        return
      }
      appendMessage({
        role: 'assistant',
        content: (
          <div className="content" style={{ borderColor: 'var(--error)' }}>
            Failed to process preferences. {error?.message || 'Unknown error'}
          </div>
        ),
      })
      failBackgroundRequest(backgroundRequest, error, true)
    } finally {
      if (isCurrentConversationScope(requestConversationId, requestUserId)) {
        setLoading(false)
      }
    }
  }

  // 创建通用的确认处理函数，可以递归调用自己处理后续的confirm
  const createConfirmationHandlers = useCallback(() => {
    const handleConfirm = async () => {
      if (confirmationActionInFlightRef.current) return
      confirmationActionInFlightRef.current = true
      setConfirmationActionInFlight(true)
      const requestConversationId = conversationId || null
      const requestUserId = userId
      setFloatingConfirmation(null) // 隐藏悬浮按钮
      const confirmMessage = "Yes, that's correct"
      const userMessage: Message = { role: 'user', content: confirmMessage }
      const appendedUser = appendMessage(userMessage)
      
      // 保存用户消息到后端
      await saveUserMessage(confirmMessage, appendedUser.metadata || undefined)
      
      setLoading(true)
      let backgroundRequest: BackgroundConversationRequest | null = null
      try {
        const conversationHistory = buildConversationHistory()
        backgroundRequest = startBackgroundRequest(
          confirmMessage,
          'confirmation_yes',
          getMessageBranchId(appendedUser),
          appendedUser.parent_message_id || null,
          getMessageId(appendedUser) || null
        )
        
        const response: RecommendationResponse = await recommend(
          confirmMessage,
          userId || "default",
          conversationHistory,
          conversationId || undefined,
          useOnlineAgent,
          {
            scopeBranchId: getMessageBranchId(appendedUser),
            ...(serviceDomainLock ? { domainLock: serviceDomainLock } : {}),
            ...(getActiveHitlState('confirm') ? { hitlState: getActiveHitlState('confirm') } : {}),
          }
        )

        if (!isCurrentConversationScope(requestConversationId, requestUserId)) {
          completeBackgroundRequest(backgroundRequest, response, false)
          return
        }
        
        if (response.confirmation_request) {
          const isGuidanceCase = response.intent === 'confirmation_no'
          const newContent = <ConfirmationMessageView
            confirmationRequest={response.confirmation_request}
            showPreferences={isGuidanceCase}
            onPreferenceConfirm={isGuidanceCase ? handlePreferenceConfirm : undefined}
          />
          const confirmationMetadata = buildConfirmationMetadata(response, {}, isGuidanceCase)
          const appendedAssistant = appendMessage({ role: 'assistant', content: newContent, metadata: confirmationMetadata })
          saveAssistantMessage(appendedAssistant.content, response.confirmation_request.message, appendedAssistant.metadata || undefined)
          // 只有需要确认用户需求时才设置悬浮确认按钮（递归调用自己）
          if (!isGuidanceCase) {
            const handlers = createConfirmationHandlers()
            setFloatingConfirmation(handlers)
          }
        } else if (response.thinking_steps) {
          const taskId = extractTaskId(response)
          if (taskId) {
            handleTaskCreated(taskId, response.thinking_steps, 'confirmation_yes')
          }
        } else if (response.restaurants && response.restaurants.length > 0) {
          saveRecommendationResult(response)
        } else if (response.llm_reply) {
          const llmMetadata = buildAssistantMetadataFromResponse(response)
          const appendedAssistant = appendMessage({ role: 'assistant', content: response.llm_reply, metadata: llmMetadata })
          saveAssistantMessage(appendedAssistant.content, response.llm_reply, appendedAssistant.metadata || undefined)
        }
        completeBackgroundRequest(backgroundRequest, response, true)
      } catch (err: any) {
        if (!isCurrentConversationScope(requestConversationId, requestUserId)) {
          failBackgroundRequest(backgroundRequest, err, false)
          return
        }
        appendMessage({ role: 'assistant', content: <div className="content" style={{ borderColor: 'var(--error)' }}>Error: {err?.message}</div> })
        failBackgroundRequest(backgroundRequest, err, true)
      } finally {
        if (isCurrentConversationScope(requestConversationId, requestUserId)) {
          setLoading(false)
        }
        confirmationActionInFlightRef.current = false
        setConfirmationActionInFlight(false)
      }
    }

    const handleNotSatisfied = async () => {
      if (confirmationActionInFlightRef.current) return
      confirmationActionInFlightRef.current = true
      setConfirmationActionInFlight(true)
      const requestConversationId = conversationId || null
      const requestUserId = userId
      try {
        setFloatingConfirmation(null) // 隐藏悬浮按钮
        const notSatisfiedMessage = "No, that's not quite right"
        const activeHitlState = getActiveHitlState('reject')
        const userMessage: Message = { role: 'user', content: notSatisfiedMessage }
        const appendedUser = appendMessage(userMessage)
        
        // 保存用户消息到后端
        await saveUserMessage(notSatisfiedMessage, appendedUser.metadata || undefined)

        if (!isCurrentConversationScope(requestConversationId, requestUserId)) {
          return
        }

        const { confirmationRequest, hitlState } = buildPreferenceRevisionConfirmation(activeHitlState)
        const guidanceContent = (
          <ConfirmationMessageView
            confirmationRequest={confirmationRequest}
            showPreferences
            onPreferenceConfirm={handlePreferenceConfirm}
          />
        )
        const guidanceMetadata = {
          type: 'confirmation',
          confirmation_request: confirmationRequest,
          hitl_state: hitlState,
          show_preferences: true,
        }
        const appendedAssistant = appendMessage({
          role: 'assistant',
          content: guidanceContent,
          metadata: guidanceMetadata,
        })
        saveAssistantMessage(appendedAssistant.content, confirmationRequest.message, appendedAssistant.metadata || undefined)
      } finally {
        confirmationActionInFlightRef.current = false
        setConfirmationActionInFlight(false)
      }
    }

    return {
      onConfirm: handleConfirm,
      onNotSatisfied: handleNotSatisfied
    }
  }, [messages, conversationId, userId, onMessageAdded, useOnlineAgent, handlePreferenceConfirm, handleAddressClick, saveRecommendationResult, saveAssistantMessage, appendMessage, setLoading, setFloatingConfirmation, buildConversationHistory, saveUserMessage, createProcessingView, handleTaskCreated, isCurrentConversationScope, startBackgroundRequest, completeBackgroundRequest, failBackgroundRequest])

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
    const requestConversationId = conversationId || null
    const requestUserId = userId

    const messageId = makeClientMessageId()
    const userMessage: Message = {
      id: messageId,
      role: 'user',
      content: trimmed,
      branch_id: activeBranchId,
      parent_message_id: getMessageId(messages[messages.length - 1]) || null,
      metadata: {
        message_id: messageId,
        branch_id: activeBranchId,
        parent_message_id: getMessageId(messages[messages.length - 1]) || null
      }
    }
    const appendedUser = appendMessage(userMessage)
    
    // 保存用户消息到后端
    await saveUserMessage(trimmed, appendedUser.metadata || undefined)
    
    setInput('')
    setLoading(true)
    let backgroundRequest: BackgroundConversationRequest | null = null
    
    try {
      // 构建对话历史（用于 GPT-4 上下文）
      const conversationHistory = buildConversationHistory()
      backgroundRequest = startBackgroundRequest(
        trimmed,
        'on_send',
        getMessageBranchId(appendedUser),
        appendedUser.parent_message_id || null,
        getMessageId(appendedUser) || null
      )
      
      // Send query and user_id, let backend intelligently determine intent
      console.log('[Chat] Sending request:', {
        query: trimmed,
        userId: userId || "default",
        conversationId: conversationId || undefined,
        useOnlineAgent,
        conversationHistoryLength: conversationHistory?.length || 0
      })
      
      const res: RecommendationResponse = await recommend(
        trimmed,
        userId || "default",
        conversationHistory,
        conversationId || undefined,
        useOnlineAgent,
        {
          scopeBranchId: getMessageBranchId(appendedUser),
          ...(serviceDomainLock ? { domainLock: serviceDomainLock } : {}),
          ...(getLatestHitlState() ? { hitlState: getLatestHitlState() } : {}),
        }
      )

      if (!isCurrentConversationScope(requestConversationId, requestUserId)) {
        completeBackgroundRequest(backgroundRequest, res, false)
        return
      }
      
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
        const llmMetadata = buildAssistantMetadataFromResponse(res)
        const appendedAssistant = appendMessage({ role: 'assistant', content: res.llm_reply, metadata: llmMetadata })
        saveAssistantMessage(appendedAssistant.content, res.llm_reply, appendedAssistant.metadata || undefined)
      } else if (res.confirmation_request) {
        // Show confirmation message with buttons
        // 检测是否是引导用户填写缺失需求的情况（intent为confirmation_no）
        const isGuidanceCase = res.intent === 'confirmation_no'
        
        // 只有需要确认用户需求时才显示确认按钮，引导填写缺失需求时不显示
        if (!isGuidanceCase) {
          // 设置悬浮确认按钮，直接使用通用的确认处理函数
          const handlers = createConfirmationHandlers()
          setFloatingConfirmation(handlers)
        }
        
        // 显示确认消息（如果需要确认用户需求，按钮将在消息下方显示）
        const confirmationContent = <ConfirmationMessageView
          confirmationRequest={res.confirmation_request}
          showPreferences={isGuidanceCase}
          onPreferenceConfirm={isGuidanceCase ? handlePreferenceConfirm : undefined}
        />
        const confirmationMetadata = buildConfirmationMetadata(res, {}, isGuidanceCase)
        const appendedAssistant = appendMessage({ 
          role: 'assistant', 
          content: confirmationContent,
          metadata: confirmationMetadata
        })
        // 保存确认消息
        saveAssistantMessage(appendedAssistant.content, res.confirmation_request.message, appendedAssistant.metadata || undefined)
      } else if (res.thinking_steps) {
        // Start processing, show ProcessingView
        if (res.thinking_steps.length > 0) {
          const taskId = extractTaskId(res)
          if (taskId) {
            handleTaskCreated(taskId, res.thinking_steps, 'on_send')
          }
        }
      } else {
        // Display results directly
        // 保存完整的推荐结果数据
        saveRecommendationResult(res)
      }
      completeBackgroundRequest(backgroundRequest, res, true)
    } catch (err: any) {
      if (!isCurrentConversationScope(requestConversationId, requestUserId)) {
        failBackgroundRequest(backgroundRequest, err, false)
        return
      }
      appendMessage({
        role: 'assistant',
        content: (
          <div className="content" style={{ borderColor: 'var(--error)' }}>
            Failed to fetch recommendations. {err?.message || 'Unknown error'}
          </div>
        ),
      })
      failBackgroundRequest(backgroundRequest, err, true)
    } finally {
      if (isCurrentConversationScope(requestConversationId, requestUserId)) {
        setLoading(false)
      }
    }
  }

  const renderMessageContent = useCallback((message: Message): React.ReactNode => {
    if (message.metadata?.type === 'processing' && typeof message.metadata.task_id === 'string') {
      const taskId = message.metadata.task_id
      const branchId = message.branch_id || (message.metadata.branch_id as string | undefined) || activeBranchIdRef.current
      const parentMessageId = message.parent_message_id || (message.metadata.parent_message_id as string | undefined) || null
      const initialThinkingSteps = Array.isArray(message.metadata.thinking_steps)
        ? message.metadata.thinking_steps as ThinkingStep[]
        : undefined
      return createProcessingView(taskId, branchId, parentMessageId, getMessageId(message), initialThinkingSteps)
    }
    return message.content
  }, [createProcessingView])

  const branchRenderState = useMemo(() => {
    const allMessagesForBranchState = allConversationMessages.length > 0
      ? allConversationMessages
      : allConversationMessagesRef.current
    const knownBranches = Object.keys(conversationBranches).length > 0
      ? conversationBranches
      : conversationBranchesRef.current
    const branchesForBranchState = deriveBranchesFromMessages(
      allMessagesForBranchState,
      knownBranches
    )
    const messageLookup = buildMessageLookup(allMessagesForBranchState)
    return {
      allMessagesForBranchState,
      branchesForBranchState,
      messageLookup,
      siblingBranchIdsByRoot: buildSiblingBranchIdsByRoot(
        allMessagesForBranchState,
        branchesForBranchState,
        messageLookup
      ),
      branchSelectionState,
    }
  }, [allConversationMessages, branchSelectionState, conversationBranches])


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
          const persistedHitlState = m.metadata?.hitl_state
          const persistedConfirmationActive = (
            m.metadata?.type === 'confirmation'
            && persistedHitlState?.node === 'collect_confirm_preferences'
            && persistedHitlState?.status === 'awaiting_confirmation'
          )
          const confirmationControls = floatingConfirmation || (persistedConfirmationActive ? createConfirmationHandlers() : null)
          const isLastAssistantMessage = m.role === 'assistant' && 
            confirmationControls && 
            i === messages.length - 1
          const isSuperseded = !!m.metadata?.superseded
          const isEditingThis = editingMessage?.index === i
          // 可复制的纯文本；表单/处理中消息为 null（不显示复制按钮）
          const copyText = isEditingThis ? null : getMessageCopyText(m)
          // 反馈控件：仅注册用户、且为「非空推荐结果」的助手消息下方展示
          const feedbackRecommendation = m.metadata?.type === 'recommendation'
            ? (m.metadata?.recommendation_data as RecommendationResponse | undefined)
            : undefined
          const feedbackResultId = (m.metadata?.result_id as string | undefined) || extractResultId(feedbackRecommendation)
          const feedbackTaskId = (m.metadata?.task_id as string | undefined) || extractTaskId(feedbackRecommendation)
          const hasClientGeneratedResultId = (
            m.metadata?.client_generated_result_id === true
            || feedbackRecommendation?.metadata?.client_generated_result_id === true
          )
          const feedbackSubmitResultId = hasClientGeneratedResultId ? null : feedbackResultId
          const showFeedback = isRegistered
            && !!feedbackRecommendation
            && (feedbackRecommendation.restaurants?.length || 0) > 0
            && !!(feedbackSubmitResultId || feedbackTaskId)
          // 重生成按钮：仅 MetaRec（助手）的非占位/非确认回复，且其前面存在用户提问
          const messageType = m.metadata?.type
          const hasPriorUserMessage = messages
            .slice(0, i)
            .some(prev => prev.role === 'user' && typeof prev.content === 'string')
          const showRegenerate = m.role === 'assistant'
            && !isSuperseded
            && messageType !== 'processing'
            && messageType !== 'confirmation'
            && hasPriorUserMessage
          const messageRootId = m.role === 'user'
            ? getCanonicalRevisionRootId(m, branchRenderState.messageLookup)
            : undefined
          const siblingBranchIds = messageRootId
            ? branchRenderState.siblingBranchIdsByRoot.get(messageRootId) || []
            : []
          const messageBranchId = getMessageBranchId(m)
          const selectedBranchIdForMessage = m.role === 'user'
            ? getSelectedBranchIdForMessage(
                m,
                branchRenderState.allMessagesForBranchState,
                branchRenderState.branchesForBranchState,
                branchRenderState.branchSelectionState,
                branchRenderState.messageLookup
              )
            : messageBranchId
          const activeSiblingIndex = Math.max(0, siblingBranchIds.indexOf(selectedBranchIdForMessage))
          const showBranchSwitcher = siblingBranchIds.length > 1 && siblingBranchIds.includes(selectedBranchIdForMessage)
          const previousBranchId = showBranchSwitcher
            ? siblingBranchIds[activeSiblingIndex - 1] || null
            : null
          const nextBranchId = showBranchSwitcher
            ? siblingBranchIds[activeSiblingIndex + 1] || null
            : null
          
          return (
            <div
              key={m.id || i}
              className="bubble"
              data-role={m.role}
              style={{ position: 'relative', opacity: isSuperseded ? 0.52 : 1 }}
            >
              <div className="who">{m.role === 'user' ? 'You' : 'MetaRec'}</div>
              {isEditingThis ? (
                <div className="content">
                  <textarea
                    className="message-edit-textarea"
                    value={editInput}
                    onChange={(event) => setEditInput(event.target.value)}
                    rows={3}
                  />
                  <div className="message-edit-actions">
                    <button
                      type="button"
                      className="message-edit-button message-edit-button-secondary"
                      onClick={cancelEditingMessage}
                      disabled={isBusy}
                      aria-label="Cancel editing"
                      title="Cancel"
                    >
                      <i className="bi bi-x-lg" aria-hidden="true" />
                    </button>
                    <button
                      type="button"
                      className="message-edit-button message-edit-button-primary"
                      onClick={submitEditedMessage}
                      disabled={isBusy || !editInput.trim()}
                      aria-label="Regenerate from edited message"
                      title="Regenerate"
                    >
                      <i className="bi bi-arrow-clockwise" aria-hidden="true" />
                    </button>
                  </div>
                </div>
              ) : (
                <div className="message-content-row">
                  {m.role === 'user' && typeof m.content === 'string' && !isSuperseded && (
                    <div className="message-edit-entry">
                      <button
                        type="button"
                        className="message-edit-button message-edit-button-ghost"
                        onClick={() => startEditingMessage(i, m)}
                        disabled={isBusy}
                        aria-label="Edit message"
                        title="Edit"
                      >
                        <i className="bi bi-pencil-square" aria-hidden="true" />
                      </button>
                    </div>
                  )}
                  {showBranchSwitcher && (
                    <div className="message-branch-switcher" aria-label="Message branches">
                      <button
                        type="button"
                        className="message-edit-button message-branch-button"
                        onClick={() => previousBranchId && switchBranch(previousBranchId, m)}
                        disabled={isBusy || !previousBranchId}
                        aria-label="Previous branch"
                        title="Previous branch"
                      >
                        <i className="bi bi-chevron-left" aria-hidden="true" />
                      </button>
                      <span className="message-branch-count" title="Branch versions">
                        <i className="bi bi-diagram-3" aria-hidden="true" />
                        {activeSiblingIndex + 1}/{siblingBranchIds.length}
                      </span>
                      <button
                        type="button"
                        className="message-edit-button message-branch-button"
                        onClick={() => nextBranchId && switchBranch(nextBranchId, m)}
                        disabled={isBusy || !nextBranchId}
                        aria-label="Next branch"
                        title="Next branch"
                      >
                        <i className="bi bi-chevron-right" aria-hidden="true" />
                      </button>
                    </div>
                  )}
                  <div className="content">
                    {isSuperseded && (
                      <div className="muted" style={{ marginBottom: 6 }}>
                        Superseded by a regenerated message
                      </div>
                    )}
                    {renderMessageContent(m)}
                  </div>
                </div>
              )}
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
                    type="button"
                    onClick={() => {
                      confirmationControls?.onConfirm()
                    }}
                    disabled={isBusy || confirmationActionInFlight}
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
                    type="button"
                    onClick={() => {
                      confirmationControls?.onNotSatisfied()
                    }}
                    disabled={isBusy || confirmationActionInFlight}
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
              {/* 操作栏：重生成（仅 MetaRec 回复）/ 复制 / 反馈 同一行展示 */}
              {!isEditingThis && (showRegenerate || copyText || showFeedback) && (
                <div className="message-actions">
                  {showRegenerate && (
                    <button
                      type="button"
                      className="message-copy-button"
                      aria-label="Regenerate response"
                      title="Regenerate"
                      disabled={isBusy}
                      onClick={() => regenerateAssistantMessage(i)}
                    >
                      <i className="bi bi-arrow-clockwise" aria-hidden="true" />
                    </button>
                  )}
                  {copyText && <CopyMessageButton text={copyText} />}
                  {showFeedback && (
                    <FeedbackControls
                      resultId={feedbackSubmitResultId ?? null}
                      taskId={feedbackTaskId ?? null}
                      branchId={(m.metadata?.branch_id as string | undefined) ?? messageBranchId}
                      conversationId={conversationId ?? null}
                      messageId={getMessageId(m) ?? null}
                      existingFeedback={(m.metadata?.feedback as FeedbackState | undefined) ?? null}
                    />
                  )}
                </div>
              )}
            </div>
          )
        })}

        {isBusy && (
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
      {saveError && (
        <div
          role="alert"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            margin: '0 16px 8px',
            padding: '8px 12px',
            background: 'rgba(220, 38, 38, 0.08)',
            border: '1px solid var(--error)',
            borderRadius: '8px',
            color: 'var(--error)',
            fontSize: '13px',
          }}
        >
          <i className="bi bi-exclamation-triangle-fill" aria-hidden="true" />
          <span style={{ flex: 1 }}>{saveError}</span>
          <button
            type="button"
            onClick={() => setSaveError(null)}
            aria-label="Dismiss"
            title="Dismiss"
            style={{
              background: 'transparent',
              border: 'none',
              color: 'inherit',
              cursor: 'pointer',
              fontSize: '16px',
              lineHeight: 1,
              padding: 0,
            }}
          >
            ×
          </button>
        </div>
      )}
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
            disabled={isBusy}
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
          <button className="send" onClick={onSend} disabled={isBusy}>
            {isBusy ? 'Thinking…' : 'Send'}
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
  // 显式菜系/菜品意图（自由文本，逗号分隔）
  const initialFoodIntent = (preferences?.food_intent && typeof preferences.food_intent === 'object')
    ? preferences.food_intent as { cuisines?: string[]; dishes?: string[] }
    : {}
  const joinTerms = (arr: any): string => (Array.isArray(arr) ? arr.filter(Boolean).join(', ') : '')

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
  const [cuisineInput, setCuisineInput] = useState<string>(joinTerms(initialFoodIntent.cuisines))
  const [dishInput, setDishInput] = useState<string>(joinTerms(initialFoodIntent.dishes))
  const [showTypeDropdown, setShowTypeDropdown] = useState(false)
  const [showFlavorDropdown, setShowFlavorDropdown] = useState(false)
  // 提交后锁定，避免重复点击把同一条确认消息反复发出去。
  const [submitted, setSubmitted] = useState(false)
  const typeDropdownRef = useRef<HTMLDivElement>(null)
  const flavorDropdownRef = useRef<HTMLDivElement>(null)

  // 点击/触摸外部关闭下拉菜单
  useEffect(() => {
    const handleClickOutside = (event: Event) => {
      const target = event.target as Node
      if (typeDropdownRef.current && !typeDropdownRef.current.contains(target)) {
        setShowTypeDropdown(false)
      }
      if (flavorDropdownRef.current && !flavorDropdownRef.current.contains(target)) {
        setShowFlavorDropdown(false)
      }
    }

    if (showTypeDropdown || showFlavorDropdown) {
      document.addEventListener('mousedown', handleClickOutside)
      document.addEventListener('touchstart', handleClickOutside)
      return () => {
        document.removeEventListener('mousedown', handleClickOutside)
        document.removeEventListener('touchstart', handleClickOutside)
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

    // 显式菜系/菜品作为主收窄条件，放在最前面
    const cuisines = cuisineInput.split(',').map(s => s.trim()).filter(Boolean)
    const dishes = dishInput.split(',').map(s => s.trim()).filter(Boolean)
    if (cuisines.length > 0) {
      parts.push(`cuisine: ${cuisines.join(', ')}`)
    }
    if (dishes.length > 0) {
      parts.push(`dish: ${dishes.join(', ')}`)
    }

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
    if (submitted) return
    if (onConfirm) {
      const summary = generateSummary()
      setSubmitted(true)
      onConfirm(summary)
    }
  }

  // 提交后移除可编辑表单，只留一句状态提示，杜绝重复提交。
  if (onConfirm && submitted) {
    return (
      <div className="preference-display" style={{
        marginTop: '16px',
        padding: '16px',
        background: 'rgba(var(--bg-secondary-rgb), 0.5)',
        borderRadius: '12px',
        border: '1px solid rgba(var(--primary-rgb), 0.1)'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', color: 'var(--muted)' }}>
          <i className="bi bi-check-circle-fill" style={{ color: 'var(--primary)' }} />
          Preferences submitted — updating your recommendations…
        </div>
      </div>
    )
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
        {/* Cuisine / Dish — explicit food intent (primary narrowing) */}
        <div>
          <label style={{ fontSize: '12px', fontWeight: 500, marginBottom: '6px', display: 'block', color: 'var(--fg-secondary)' }}>Cuisine</label>
          <input
            placeholder="e.g. Vietnamese, Japanese (optional)"
            value={cuisineInput}
            onChange={(e) => setCuisineInput(e.target.value)}
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
        <div>
          <label style={{ fontSize: '12px', fontWeight: 500, marginBottom: '6px', display: 'block', color: 'var(--fg-secondary)' }}>Specific Dish</label>
          <input
            placeholder="e.g. Pho, Burger, Kopi-C (optional)"
            value={dishInput}
            onChange={(e) => setDishInput(e.target.value)}
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

// 复制消息按钮：复制后短暂显示对勾反馈
function CopyMessageButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  const timerRef = useRef<number | undefined>(undefined)

  useEffect(() => () => window.clearTimeout(timerRef.current), [])

  const handleCopy = async () => {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text)
      } else {
        // 旧浏览器 / 非安全上下文回退
        const textarea = document.createElement('textarea')
        textarea.value = text
        textarea.style.position = 'fixed'
        textarea.style.opacity = '0'
        document.body.appendChild(textarea)
        textarea.select()
        document.execCommand('copy')
        document.body.removeChild(textarea)
      }
      setCopied(true)
      window.clearTimeout(timerRef.current)
      timerRef.current = window.setTimeout(() => setCopied(false), 1500)
    } catch (error) {
      console.warn('[Chat] Failed to copy message:', error)
    }
  }

  return (
    <button
      type="button"
      className="message-copy-button"
      onClick={handleCopy}
      aria-label={copied ? 'Copied' : 'Copy message'}
      title={copied ? 'Copied' : 'Copy message'}
    >
      <i className={`bi ${copied ? 'bi-check-lg' : 'bi-clipboard'}`} aria-hidden="true" />
    </button>
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

function ProcessingView({ taskId, status, initialSteps, onAddressClick }: { taskId: string; status?: TaskStatus | null; initialSteps?: ThinkingStep[]; userId?: string; conversationId?: string; onAddressClick?: (restaurant: { name: string; address: string; coordinates?: { latitude: number; longitude: number } }) => void }) {
  const [displayedSteps, setDisplayedSteps] = useState<ThinkingStep[]>([])
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'error'>('idle')

  useEffect(() => {
    setDisplayedSteps(initialSteps || [])
  }, [initialSteps, taskId])

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
    if (status?.result?.thinking_steps) {
      setDisplayedSteps(status.result.thinking_steps)
    }
  }, [status?.result?.thinking_steps])

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
          Task queued. You can switch chats; MetaRec will keep watching it in the background.
        </div>
        {taskIdInfo}
        {displayedSteps.length > 0 && (
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
          </div>
        )}
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

  // metadata drives both the no-match explanation and the "widened to nearby" banner.
  const metadata = (data?.metadata || {}) as Record<string, any>
  const foodTerms = Array.isArray(metadata.food_intent_terms) ? metadata.food_intent_terms.filter(Boolean) : []
  const foodSubject = foodTerms.length > 0 ? foodTerms.join(' / ') : 'that cuisine/dish'
  const searchedLocation = (typeof metadata.searched_location === 'string'
    && metadata.searched_location
    && metadata.searched_location !== 'any')
    ? metadata.searched_location
    : null

  if (!data?.restaurants?.length) {
    console.warn('[ResultsView] No restaurants found:', {
      data,
      restaurantsLength: data?.restaurants?.length,
      restaurants: data?.restaurants
    })
    // Explicit cuisine/dish with no match: explain + offer to widen, never a bare empty state.
    if (metadata.food_intent_no_match) {
      return (
        <div style={{ padding: '20px', textAlign: 'center', color: 'var(--muted)' }}>
          No <strong>{foodSubject}</strong> found {searchedLocation ? <>near <strong>{searchedLocation}</strong></> : 'nearby'}.{' '}
          Want me to widen the area, or look at a related cuisine? Just ask.
        </div>
      )
    }
    return <div style={{ padding: '20px', textAlign: 'center', color: 'var(--muted)' }}>No recommendations yet. Try adjusting filters or query.</div>
  }

  return (
    <>
      {metadata.food_intent_widened && (
        <div className="widen-banner" style={{
          padding: '10px 14px',
          marginBottom: 12,
          borderRadius: 'var(--radius-md)',
          background: 'var(--accent-soft, rgba(99, 102, 241, 0.08))',
          border: '1px solid var(--border)',
          color: 'var(--muted)',
          fontSize: 13,
          lineHeight: 1.5,
        }}>
          No <strong>{foodSubject}</strong> right {searchedLocation ? <>at <strong>{searchedLocation}</strong></> : 'in that exact area'} — showing the closest <strong>{foodSubject}</strong> spots nearby.
        </div>
      )}
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
                      coordinates: toLatLngCoordinates(r.gps_coordinates)
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
    </>
  )
}
