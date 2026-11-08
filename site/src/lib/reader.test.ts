import { describe, expect, it, vi } from 'vitest'
import { hasUnread, parseRoute, readStored, routeHash, topicKey } from './reader'
import { renderMarkdown } from './markdown'
import type { Topic } from '../types'

describe('reader navigation and state', () => {
  it('round-trips topic names with Chinese, slashes, hash and emoji on GitHub Pages', () => {
    const topic = 'optimize_for_size / 中文 # & 🦀'
    const hash = routeHash('t-libs', topic, 637982590)
    expect(parseRoute(hash)).toEqual({ stream: 't-libs', topic, message: 637982590 })
    expect(new URL(hash, 'https://example.github.io/repo/').pathname).toBe('/repo/')
    expect(parseRoute('#message=-4').message).toBeUndefined()
  })
  it('keeps independent progress for same-named topics in different channels', () => {
    expect(topicKey('t-libs', 'one')).not.toBe(topicKey('general', 'one'))
    const topic = { last_id: 30, last: 100 } as Topic
    expect(hasUnread(topic)).toBe(true)
    expect(hasUnread(topic, { message: 20, updated: 200 })).toBe(true)
    expect(hasUnread(topic, { message: 30, updated: 200 })).toBe(false)
  })
  it('survives corrupted or unavailable local storage', () => {
    vi.stubGlobal('localStorage', { getItem: () => '{bad json' })
    expect(readStored('saved', [])).toEqual([])
    vi.stubGlobal('localStorage', {
      getItem: () => {
        throw new Error('blocked')
      },
    })
    expect(readStored('saved', [])).toEqual([])
    vi.unstubAllGlobals()
  })
})

describe('technical conversation rendering', () => {
  it('preserves Rust code and folds quoted text', () => {
    const html = renderMarkdown('> a quoted message\n\n```rust\nlet x = "<tag>";\n```')
    expect(html).toContain('<details')
    expect(html).toContain('&lt;tag&gt;')
    expect(html).toContain('code-copy')
  })
  it('escapes raw HTML and blocks executable Markdown URLs', () => {
    const html = renderMarkdown(
      '<script>alert(1)</script>\n\n[x](javascript:alert(1))\n\n[issue](https://github.com/rust-lang/rust/issues/1)',
    )
    expect(html).not.toContain('<script>')
    expect(html).not.toContain('href="javascript:')
    expect(html).toContain('rel="noopener noreferrer"')
  })
})
