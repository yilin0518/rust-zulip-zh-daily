<script setup lang="ts">
import { ArrowUpRight, Bookmark, MessageSquare, Sparkles } from '@lucide/vue'
import type { Topic } from '../types'
import { excerpt, formatTime, routeHash } from '../lib/reader'
defineProps<{ topic: Topic; saved: boolean; unread: boolean; featured?: boolean }>()
defineEmits<{ save: [topic: Topic] }>()
</script>

<template>
  <article class="topic-card" :class="{ featured }">
    <div class="card-topline">
      <span class="channel-tag" :data-channel="topic.stream"># {{ topic.stream }}</span>
      <span v-if="unread" class="unread-label"><i></i> 未读</span>
      <button
        class="icon-button save-button"
        :class="{ saved }"
        :aria-label="saved ? '取消收藏' : '收藏话题'"
        :aria-pressed="saved"
        @click="$emit('save', topic)"
      >
        <Bookmark :size="17" />
      </button>
    </div>
    <a class="topic-card-link" :href="routeHash(topic.stream, topic.name)">
      <h3>{{ topic.name_zh || topic.name }} <ArrowUpRight :size="18" /></h3>
      <p v-if="topic.name_zh && topic.name_zh !== topic.name" class="english-title">
        {{ topic.name }}
      </p>
      <p class="topic-preview">
        {{ excerpt(topic.summary) || '暂无 AI 摘要，打开话题阅读讨论。' }}
      </p>
      <div class="card-bottomline">
        <span><MessageSquare :size="14" /> {{ topic.count }} 条讨论</span>
        <span>{{ formatTime(topic.last) }}</span>
        <span v-if="topic.summary" class="summary-label"><Sparkles :size="12" /> AI 摘要</span>
      </div>
    </a>
  </article>
</template>
