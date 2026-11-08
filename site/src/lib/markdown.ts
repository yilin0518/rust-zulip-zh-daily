import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js/lib/core'
import rust from 'highlight.js/lib/languages/rust'
import javascript from 'highlight.js/lib/languages/javascript'
import json from 'highlight.js/lib/languages/json'
import bash from 'highlight.js/lib/languages/bash'
import cpp from 'highlight.js/lib/languages/cpp'

hljs.registerLanguage('rust', rust)
hljs.registerLanguage('javascript', javascript)
hljs.registerLanguage('json', json)
hljs.registerLanguage('bash', bash)
hljs.registerLanguage('cpp', cpp)

const parser = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
  highlight(code, language) {
    return language && hljs.getLanguage(language)
      ? hljs.highlight(code, { language, ignoreIllegals: true }).value
      : ''
  },
})
const linkOpen = parser.renderer.rules.link_open
parser.renderer.rules.link_open = (tokens, index, options, env, self) => {
  tokens[index].attrSet('target', '_blank')
  tokens[index].attrSet('rel', 'noopener noreferrer')
  return linkOpen
    ? linkOpen(tokens, index, options, env, self)
    : self.renderToken(tokens, index, options)
}

const fence = parser.renderer.rules.fence!
parser.renderer.rules.fence = (tokens, index, options, env, self) => {
  if (tokens[index].info.trim() === 'quote') {
    return `<details class="quote-fold"><summary>引用的发言 · 展开查看</summary><blockquote>${parser.render(tokens[index].content)}</blockquote></details>`
  }
  return `<div class="code-block"><button type="button" class="code-copy" aria-label="复制代码">复制</button>${fence(tokens, index, options, env, self)}</div>`
}
parser.renderer.rules.blockquote_open = () =>
  '<details class="quote-fold"><summary>引用的发言 · 展开查看</summary><blockquote>'
parser.renderer.rules.blockquote_close = () => '</blockquote></details>'

export const renderMarkdown = (source: string) => parser.render(source || '')
