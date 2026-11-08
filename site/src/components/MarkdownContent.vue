<script setup lang="ts">
import { computed, ref } from 'vue'
import { renderMarkdown } from '../lib/markdown'
const props = defineProps<{ source: string }>()
const html = computed(() => renderMarkdown(props.source))
const root = ref<HTMLElement>()
const notice = ref('')
async function copyCode(event: MouseEvent) {
  const button = (event.target as HTMLElement).closest('.code-copy')
  const pre = button?.parentElement?.querySelector('pre code')
  if (!pre || !root.value?.contains(pre)) return
  try {
    await navigator.clipboard.writeText(pre.textContent || '')
    notice.value = '代码已复制'
  } catch {
    notice.value = '复制失败，请选择代码后复制'
  }
  setTimeout(() => {
    notice.value = ''
  }, 2000)
}
</script>

<template>
  <div ref="root" class="markdown" @click="copyCode" v-html="html"></div>
  <span v-if="notice" class="copy-notice" role="status">{{ notice }}</span>
</template>
