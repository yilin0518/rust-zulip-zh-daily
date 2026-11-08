export interface Message {
  id: number
  sender: string
  time: number
  en: string
  zh: string
}

export interface Topic {
  id: string
  stream: string
  name: string
  name_zh: string
  summary: string
  count: number
  first: number
  last: number
  last_id?: number
  file?: string
  zulip_url?: string
  messages?: Message[]
}

export interface Stream {
  key: string
  display: string
  topics: number
  messages: number
  file: string
}

export interface Meta {
  schema_version?: number
  sample?: boolean
  last_updated: string
  streams: Stream[]
}

export interface ReadPosition {
  message: number
  updated: number
}

export type Language = 'zh' | 'both' | 'en'
