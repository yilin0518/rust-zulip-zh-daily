import { afterEach, describe, expect, it, vi } from 'vitest'
import { loadCatalog, loadTopic } from './data'
import type { Topic } from '../types'

afterEach(() => vi.unstubAllGlobals())

describe('lazy conversation loading', () => {
  it('loads only catalogs at startup and shares a single in-flight detail request', async () => {
    const topic = {
      id: 'lazy',
      name: 'topic',
      file: 'topics/lazy-test.json',
      count: 2,
      last: 100,
    } as Topic
    const fetcher = vi.fn(async (url: string) => ({
      ok: true,
      json: async () =>
        url.endsWith('meta.json')
          ? { streams: [{ key: 't-libs', file: 'stream.json' }] }
          : url.endsWith('stream.json')
            ? { topics: [topic] }
            : { ...topic, messages: [{ id: 4, en: 'body' }] },
    }))
    vi.stubGlobal('fetch', fetcher)
    const catalog = await loadCatalog()
    expect(fetcher).toHaveBeenCalledTimes(2)
    expect(catalog.topics[0].stream).toBe('t-libs')
    expect(catalog.topics[0].messages).toBeUndefined()
    const [a, b] = await Promise.all([loadTopic(catalog.topics[0]), loadTopic(catalog.topics[0])])
    expect(fetcher).toHaveBeenCalledTimes(3)
    expect(a.messages?.[0].id).toBe(4)
    expect(a).toEqual(b)
  })
  it('retries failed details and continues to support legacy inline message data', async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce({ ok: false, status: 503 })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ messages: [] }) })
    vi.stubGlobal('fetch', fetcher)
    const topic = { file: 'topics/retry-test.json' } as Topic
    await expect(loadTopic(topic)).rejects.toThrow('503')
    await expect(loadTopic(topic)).resolves.toHaveProperty('messages', [])
    await expect(loadTopic({ messages: [] } as unknown as Topic)).resolves.toHaveProperty(
      'messages',
      [],
    )
    expect(fetcher).toHaveBeenCalledTimes(2)
  })
})
