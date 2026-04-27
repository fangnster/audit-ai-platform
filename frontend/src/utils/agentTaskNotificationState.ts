type AgentTaskNotificationScope = 'document_parse' | 'fact_reparse' | 'draft_work'

type StoredTaskState = {
  submitted: Record<string, number>
  notified: Record<string, number>
}

const STORAGE_KEY = 'agent-task-notification-state-v1'
const MAX_AGE_MS = 1000 * 60 * 60 * 24 * 7
const MAX_IDS_PER_BUCKET = 200

function storageAvailable() {
  return typeof window !== 'undefined' && typeof window.localStorage !== 'undefined'
}

function emptyState(): StoredTaskState {
  return { submitted: {}, notified: {} }
}

function scopeKey(scope: AgentTaskNotificationScope, taskId: string) {
  return `${scope}:${taskId}`
}

function pruneBucket(bucket: Record<string, number>, now: number) {
  const entries = Object.entries(bucket)
    .filter(([, timestamp]) => Number.isFinite(timestamp) && now - timestamp < MAX_AGE_MS)
    .sort((a, b) => b[1] - a[1])
    .slice(0, MAX_IDS_PER_BUCKET)
  return Object.fromEntries(entries)
}

function readState(): StoredTaskState {
  if (!storageAvailable()) return emptyState()
  try {
    const parsed = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || 'null')
    if (!parsed || typeof parsed !== 'object') return emptyState()
    const now = Date.now()
    return {
      submitted: pruneBucket(parsed.submitted || {}, now),
      notified: pruneBucket(parsed.notified || {}, now),
    }
  } catch {
    return emptyState()
  }
}

function writeState(state: StoredTaskState) {
  if (!storageAvailable()) return
  try {
    const now = Date.now()
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({
      submitted: pruneBucket(state.submitted, now),
      notified: pruneBucket(state.notified, now),
    }))
  } catch {
    // Best effort only. Missing localStorage should not break Agent polling.
  }
}

export function rememberSubmittedAgentTask(scope: AgentTaskNotificationScope, taskId: string) {
  const id = taskId.trim()
  if (!id) return
  const state = readState()
  state.submitted[scopeKey(scope, id)] = Date.now()
  writeState(state)
}

export function forgetSubmittedAgentTask(scope: AgentTaskNotificationScope, taskId: string) {
  const id = taskId.trim()
  if (!id) return
  const state = readState()
  delete state.submitted[scopeKey(scope, id)]
  writeState(state)
}

export function wasSubmittedAgentTask(scope: AgentTaskNotificationScope, taskId: string) {
  const id = taskId.trim()
  if (!id) return false
  const state = readState()
  return Boolean(state.submitted[scopeKey(scope, id)])
}

export function rememberNotifiedAgentTask(scope: AgentTaskNotificationScope, taskId: string) {
  const id = taskId.trim()
  if (!id) return
  const state = readState()
  const key = scopeKey(scope, id)
  state.notified[key] = Date.now()
  delete state.submitted[key]
  writeState(state)
}

export function wasNotifiedAgentTask(scope: AgentTaskNotificationScope, taskId: string) {
  const id = taskId.trim()
  if (!id) return false
  const state = readState()
  return Boolean(state.notified[scopeKey(scope, id)])
}
