<script setup lang="ts">
import { computed, ref } from 'vue'
import { Check, Copy, ExternalLink } from '@lucide/vue'
import type { Language, Message } from '../types'
import MarkdownContent from './MarkdownContent.vue'
import { formatTime, routeHash } from '../lib/reader'

const props = defineProps<{
  message: Message
  stream: string
  topic: string
  language: Language
  fontSize: number
}>()
const originalOpen = ref(false)
const copied = ref(false)
const copyError = ref(false)
const translated = computed(
  () => !!props.message.zh && props.message.zh.trim() !== props.message.en.trim(),
)
const initials = computed(() => props.message.sender.slice(0, 1).toUpperCase())
const color = computed(
  () =>
    ['#e6ede8', '#efe5df', '#e8e7f3', '#e4edf4'][
      [...props.message.sender].reduce((sum, char) => sum + char.charCodeAt(0), 0) % 4
    ],
)
async function copyLink() {
  const url = new URL(location.href)
  url.hash = routeHash(props.stream, props.topic, props.message.id)
  try {
    await navigator.clipboard.writeText(url.href)
    copied.value = true
    setTimeout(() => {
      copied.value = false
    }, 1800)
  } catch {
    copyError.value = true
  }
}
</script>

<template>
  <article
    :id="`message-${message.id}`"
    class="message-card"
    :data-message="message.id"
    :style="{ '--reading-size': `${fontSize}px` }"
  >
    <div class="message-header">
      <span class="avatar" :style="{ background: color }">{{ initials }}</span>
      <strong>{{ message.sender }}</strong>
      <time :datetime="new Date(message.time * 1000).toISOString()">{{
        formatTime(message.time, true)
      }}</time>
      <div class="message-actions">
        <button
          class="icon-button"
          :aria-label="copied ? '链接已复制' : '复制消息链接'"
          @click="copyLink"
        >
          <Check v-if="copied" :size="15" /><Copy v-else :size="15" />
        </button>
        <a
          class="icon-button"
          :href="`https://rust-lang.zulipchat.com/#narrow/with/${message.id}`"
          target="_blank"
          rel="noopener noreferrer"
          aria-label="在 Zulip 查看这条消息"
          ><ExternalLink :size="15"
        /></a>
      </div>
    </div>
    <p v-if="copyError" class="muted" role="status">无法自动复制，请使用浏览器地址栏或原帖链接。</p>
    <div class="message-body" :class="{ parallel: language === 'both' && translated }">
      <div v-if="language !== 'en'" class="translation">
        <span v-if="language === 'both' && translated" class="language-label">中文翻译</span>
        <span v-if="!translated" class="translation-fallback">原文 · 暂无独立译文</span>
        <MarkdownContent :source="message.zh || message.en" />
      </div>
      <div v-if="language === 'en' || (language === 'both' && translated)" class="original">
        <span v-if="language === 'both'" class="language-label">ENGLISH</span>
        <MarkdownContent :source="message.en" />
      </div>
    </div>
    <template v-if="language === 'zh' && translated">
      <button
        class="original-toggle"
        :aria-expanded="originalOpen"
        @click="originalOpen = !originalOpen"
      >
        {{ originalOpen ? '收起英文原文' : '查看英文原文' }}
        <span>{{ originalOpen ? '−' : '+' }}</span>
      </button>
      <div v-if="originalOpen" class="original-expanded">
        <MarkdownContent :source="message.en" />
      </div>
    </template>
  </article>
</template>
