import type { ReadPosition, Topic } from '../types'

export function topicKey(stream: string, name: string) {
  return JSON.stringify([stream, name])
}

export function routeHash(stream: string, topic: string, message?: number) {
  const params = new URLSearchParams({ stream, topic })
  if (message) params.set('message', String(message))
  return `#${params}`
}

export function parseRoute(hash: string) {
  const params = new URLSearchParams(hash.replace(/^#/, ''))
  const message = Number(params.get('message'))
  return {
    stream: params.get('stream') || '',
    topic: params.get('topic') || '',
    message: Number.isSafeInteger(message) && message > 0 ? message : undefined,
  }
}

export function readStored<T>(key: string, fallback: T): T {
  try {
    const value = localStorage.getItem(key)
    return value === null ? fallback : JSON.parse(value)
  } catch {
    return fallback
  }
}

export function store(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    /* Private mode / quota. */
  }
}

export function hasUnread(topic: Topic, position?: ReadPosition) {
  return (
    !position || (topic.last_id ? topic.last_id > position.message : topic.last > position.updated)
  )
}

export function excerpt(text: string, limit = 150) {
  return text
    .replace(/```[\s\S]*?```/g, '')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/(^|\n)\s*[-*#]+\s*/g, ' ')
    .replace(/[*_`]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, limit)
}

export function formatTime(value: number | string, full = false) {
  const date = new Date(typeof value === 'number' ? value * 1000 : value)
  if (Number.isNaN(date.getTime())) return '时间未知'
  return date.toLocaleString('zh-CN', {
    ...(full ? { year: 'numeric' as const } : {}),
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}
