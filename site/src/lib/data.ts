import type { Meta, Topic } from '../types'
import { topicKey } from './reader'

const detailCache = new Map<string, Promise<Topic>>()

async function json<T>(file: string): Promise<T> {
  const response = await fetch(`${import.meta.env.BASE_URL}data/${file}`)
  if (!response.ok) throw new Error(`读取数据失败（${response.status}），请稍后重试。`)
  return response.json()
}

export async function loadCatalog() {
  const meta = await json<Meta>('meta.json')
  const groups = await Promise.all(
    meta.streams.map(async (stream) => {
      const data = await json<{ topics: Topic[] }>(stream.file)
      return data.topics.map((topic) => ({
        ...topic,
        stream: stream.key,
        id: topic.id || topicKey(stream.key, topic.name),
        last_id: topic.last_id || topic.messages?.at(-1)?.id,
      }))
    }),
  )
  return { meta, topics: groups.flat().sort((a, b) => b.last - a.last) }
}

export async function loadTopic(topic: Topic): Promise<Topic> {
  if (topic.messages) return topic
  if (!topic.file) throw new Error('该话题没有正文数据，请重新生成站点数据。')
  if (!detailCache.has(topic.file)) {
    const request = json<Topic>(topic.file).catch((error) => {
      detailCache.delete(topic.file!)
      throw error
    })
    detailCache.set(topic.file, request)
  }
  return { ...topic, ...(await detailCache.get(topic.file)!) }
}
