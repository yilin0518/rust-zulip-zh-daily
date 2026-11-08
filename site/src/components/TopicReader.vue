<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { ArrowDown, ArrowLeft, ArrowUp, Bookmark, ExternalLink, Sparkles } from '@lucide/vue'
import type { Language, ReadPosition, Topic } from '../types'
import { formatTime } from '../lib/reader'
import MarkdownContent from './MarkdownContent.vue'
import MessageCard from './MessageCard.vue'

const props = defineProps<{
  topic: Topic
  saved: boolean
  language: Language
  fontSize: number
  position?: ReadPosition
  target?: number
}>()
const emit = defineEmits<{
  save: []
  read: [message: number]
  language: [value: Language]
  font: [size: number]
}>()
const messages = computed(() => props.topic.messages || [])
const visibleCount = ref(60)
const root = ref<HTMLElement>()
const summary = ref<HTMLElement>()
// Freeze the previous visit's position while this visit updates storage.
const previousMessage = props.position?.message
const newCount = computed(() =>
  previousMessage ? messages.value.filter((m) => m.id > previousMessage).length : 0,
)
const readIndex = ref(
  previousMessage ? Math.max(0, messages.value.findIndex((m) => m.id === previousMessage) + 1) : 0,
)
const percent = computed(() =>
  messages.value.length ? Math.round((readIndex.value / messages.value.length) * 100) : 0,
)
let observer: IntersectionObserver | undefined
function observe() {
  observer?.disconnect()
  root.value
    ?.querySelectorAll<HTMLElement>('[data-message]')
    .forEach((element) => observer?.observe(element))
}
async function showMore() {
  visibleCount.value += 60
  await nextTick()
  observe()
}
async function jump(id?: number) {
  if (!id) return
  const index = messages.value.findIndex((message) => message.id === id)
  if (index < 0) return
  visibleCount.value = Math.max(visibleCount.value, index + 20)
  await nextTick()
  observe()
  document.getElementById(`message-${id}`)?.scrollIntoView({ block: 'start' })
}
defineExpose({ jump })
onMounted(async () => {
  observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue
        const id = Number((entry.target as HTMLElement).dataset.message)
        const index = messages.value.findIndex((message) => message.id === id)
        readIndex.value = Math.max(readIndex.value, index + 1)
        emit('read', id)
      }
    },
    { threshold: 0.15 },
  )
  observe()
  if (props.target) await jump(props.target)
})
onBeforeUnmount(() => observer?.disconnect())
</script>

<template>
  <div ref="root" class="reader-layout">
    <div class="reader-main">
      <a href="#" class="back-link"><ArrowLeft :size="16" /> 返回话题列表</a>
      <header class="reader-heading">
        <span class="channel-tag" :data-channel="topic.stream"># {{ topic.stream }}</span>
        <h1>{{ language === 'en' ? topic.name : topic.name_zh || topic.name }}</h1>
        <p v-if="topic.name_zh && language !== 'en'" class="reader-english">{{ topic.name }}</p>
        <div class="reader-meta">
          <span>{{ topic.count }} 条消息</span
          ><span>更新于 {{ formatTime(topic.last, true) }}</span>
        </div>
        <div class="reader-heading-actions">
          <button
            class="text-button"
            :class="{ saved }"
            :aria-pressed="saved"
            @click="emit('save')"
          >
            <Bookmark :size="15" />{{ saved ? '已收藏' : '收藏话题' }}
          </button>
          <a
            v-if="topic.zulip_url"
            class="text-button"
            :href="topic.zulip_url"
            target="_blank"
            rel="noopener noreferrer"
            >Zulip 原帖 <ExternalLink :size="14"
          /></a>
        </div>
      </header>

      <section v-if="topic.summary" ref="summary" class="summary-panel" aria-label="AI 讨论摘要">
        <div class="summary-title">
          <Sparkles :size="17" />
          <h2>先读摘要</h2>
          <span>AI 整理 · 请结合原文理解</span>
        </div>
        <MarkdownContent :source="topic.summary" />
      </section>

      <div v-if="previousMessage" class="resume-banner">
        <span>{{
          newCount ? `上次读到的位置之后，还有 ${newCount} 条消息` : '已保存你上次的阅读位置'
        }}</span>
        <button @click="jump(previousMessage)">继续阅读 →</button>
      </div>

      <div class="reader-toolbar">
        <h2>
          讨论正文 <span>{{ messages.length }}</span>
        </h2>
        <div class="language-switch" aria-label="阅读语言">
          <button
            v-for="item in [
              ['zh', '中文'],
              ['both', '双语'],
              ['en', 'EN'],
            ] as const"
            :key="item[0]"
            :class="{ active: language === item[0] }"
            :aria-pressed="language === item[0]"
            @click="emit('language', item[0])"
          >
            {{ item[1] }}
          </button>
        </div>
        <label class="font-control"
          >字号<select
            :value="fontSize"
            @change="emit('font', Number(($event.target as HTMLSelectElement).value))"
          >
            <option :value="15">小</option>
            <option :value="17">中</option>
            <option :value="19">大</option>
          </select></label
        >
      </div>
      <div class="mobile-reader-nav">
        <button @click="jump(messages[0]?.id)">从头阅读</button
        ><button @click="jump(messages.at(-1)?.id)">跳到最新 ↓</button>
      </div>

      <MessageCard
        v-for="message in messages.slice(0, visibleCount)"
        :key="message.id"
        :message="message"
        :stream="topic.stream"
        :topic="topic.name"
        :language="language"
        :font-size="fontSize"
      />
      <button v-if="visibleCount < messages.length" class="load-more" @click="showMore">
        加载后续讨论（还有 {{ messages.length - visibleCount }} 条）<ArrowDown :size="15" />
      </button>
      <div v-else class="discussion-end"><span></span> 已到达当前讨论末尾 <span></span></div>
    </div>
    <aside class="reading-rail" aria-label="阅读导航">
      <div class="reading-rail-inner">
        <span class="eyebrow">阅读导航</span>
        <button v-if="topic.summary" @click="summary?.scrollIntoView({ block: 'start' })">
          <Sparkles :size="15" />讨论摘要
        </button>
        <button @click="jump(messages[0]?.id)"><ArrowUp :size="15" />从头阅读</button>
        <button @click="jump(messages.at(-1)?.id)"><ArrowDown :size="15" />跳到最新</button>
        <div class="reading-progress">
          <span
            >阅读进度 <b>{{ percent }}%</b></span
          >
          <div><i :style="{ width: `${percent}%` }"></i></div>
        </div>
        <p>译文由机器生成。遇到疑问时，可以展开英文原文对照阅读。</p>
      </div>
    </aside>
  </div>
</template>
