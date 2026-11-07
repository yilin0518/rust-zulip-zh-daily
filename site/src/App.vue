<script setup lang="ts">
import {
  computed,
  defineAsyncComponent,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
} from 'vue'
import {
  ArrowDownWideNarrow,
  ArrowRight,
  Bookmark,
  CheckCheck,
  ChevronRight,
  CircleHelp,
  CodeXml,
  Hash,
  Inbox,
  Menu,
  Moon,
  Radio,
  Search,
  Sun,
  X,
} from '@lucide/vue'
import type { Language, Meta, ReadPosition, Topic } from './types'
import { loadCatalog, loadTopic } from './lib/data'
import { formatTime, hasUnread, parseRoute, readStored, store, topicKey } from './lib/reader'
import TopicCard from './components/TopicCard.vue'
const TopicReader = defineAsyncComponent(() => import('./components/TopicReader.vue'))

const meta = ref<Meta>()
const topics = ref<Topic[]>([])
const loading = ref(true)
const error = ref('')
const detailError = ref('')
const detailLoading = ref(false)
const activeTopic = ref<Topic>()
const hash = ref(location.hash)
const route = computed(() => parseRoute(hash.value))
const selectedChannel = ref('all')
const selectedView = ref<'all' | 'unread' | 'saved'>('all')
const query = ref('')
const sort = ref('recent')
const sidebarOpen = ref(false)
const preferences = readStored<Record<string, unknown>>('rust-reader:preferences', {})
const language = ref<Language>(
  ['zh', 'both', 'en'].includes(String(preferences?.language))
    ? (preferences.language as Language)
    : 'zh',
)
const fontSize = ref(
  [15, 17, 19].includes(Number(preferences?.fontSize)) ? Number(preferences.fontSize) : 17,
)
const theme = ref(preferences?.theme === 'dark' ? 'dark' : 'light')
const storedSaved = readStored<unknown>('rust-reader:saved', [])
const saved = ref<string[]>(
  Array.isArray(storedSaved) ? storedSaved.filter((x) => typeof x === 'string') : [],
)
const storedPositions = readStored<unknown>('rust-reader:positions', {})
const positions = ref<Record<string, ReadPosition>>(
  Object.fromEntries(
    Object.entries(
      storedPositions && typeof storedPositions === 'object' ? storedPositions : {},
    ).filter(([, p]) => p && Number.isSafeInteger(p.message) && typeof p.updated === 'number'),
  ),
)
const reader = ref<InstanceType<typeof TopicReader>>()
const content = ref<HTMLElement>()
const search = ref<HTMLInputElement>()
let requestId = 0
let persistTimer: ReturnType<typeof setTimeout> | undefined

const keyFor = (topic: Topic) => topicKey(topic.stream, topic.name)
const isSaved = (topic: Topic) => saved.value.includes(keyFor(topic))
const isUnread = (topic: Topic) => hasUnread(topic, positions.value[keyFor(topic)])
const unreadCount = computed(() => topics.value.filter(isUnread).length)
const savedCount = computed(() => topics.value.filter(isSaved).length)
const filtered = computed(() => {
  const q = query.value.trim().toLowerCase()
  return topics.value
    .filter(
      (topic) =>
        (selectedChannel.value === 'all' || topic.stream === selectedChannel.value) &&
        (selectedView.value !== 'saved' || isSaved(topic)) &&
        (selectedView.value !== 'unread' || isUnread(topic)) &&
        (!q ||
          [topic.name, topic.name_zh, topic.summary].some((text) =>
            text?.toLowerCase().includes(q),
          )),
    )
    .sort((a, b) =>
      sort.value === 'active' ? b.count - a.count || b.last - a.last : b.last - a.last,
    )
})
const featured = computed(() =>
  selectedView.value === 'all' && selectedChannel.value === 'all' && !query.value
    ? filtered.value[0]
    : undefined,
)
const listTopics = computed(() => (featured.value ? filtered.value.slice(1) : filtered.value))
const pageTitle = computed(() =>
  selectedView.value === 'saved'
    ? '我的收藏'
    : selectedView.value === 'unread'
      ? '未读话题'
      : selectedChannel.value !== 'all'
        ? `# ${selectedChannel.value}`
        : '社区动态',
)
const messageCount = computed(() => topics.value.reduce((count, topic) => count + topic.count, 0))

function toggleSaved(topic: Topic) {
  const key = keyFor(topic)
  saved.value = isSaved(topic) ? saved.value.filter((item) => item !== key) : [...saved.value, key]
  store('rust-reader:saved', saved.value)
}
function markRead(topic: Topic, message: number) {
  const key = keyFor(topic)
  const previous = positions.value[key]
  if (!previous || message > previous.message) {
    positions.value[key] = { message, updated: Date.now() / 1000 }
    clearTimeout(persistTimer)
    persistTimer = setTimeout(() => store('rust-reader:positions', positions.value), 300)
  }
}
function markAllRead() {
  for (const topic of filtered.value) {
    if (topic.last_id)
      positions.value[keyFor(topic)] = { message: topic.last_id, updated: Date.now() / 1000 }
  }
  store('rust-reader:positions', positions.value)
}
function browse(view: 'all' | 'unread' | 'saved', channel = 'all') {
  selectedView.value = view
  selectedChannel.value = channel
  sidebarOpen.value = false
  location.hash = ''
  content.value?.scrollTo({ top: 0 })
}
async function fetchCatalog() {
  loading.value = true
  error.value = ''
  try {
    const data = await loadCatalog()
    meta.value = data.meta
    topics.value = data.topics
  } catch (e) {
    error.value = e instanceof Error ? e.message : '无法加载讨论，请稍后重试。'
  } finally {
    loading.value = false
  }
}
async function openRoute() {
  const request = ++requestId
  detailError.value = ''
  sidebarOpen.value = false
  if (!route.value.topic || !route.value.stream) {
    activeTopic.value = undefined
    detailLoading.value = false
    document.title = 'Rust Zulip 中文日报'
    await nextTick()
    content.value?.scrollTo({ top: 0 })
    return
  }
  if (loading.value) return
  const topic = topics.value.find(
    (topic) => topic.stream === route.value.stream && topic.name === route.value.topic,
  )
  if (!topic) {
    activeTopic.value = undefined
    detailLoading.value = false
    detailError.value = '当前话题已不在最新列表中。你可以返回列表，或前往 Zulip 搜索原帖。'
    return
  }
  if (activeTopic.value?.id === topic.id) {
    detailLoading.value = false
    if (route.value.message) await reader.value?.jump(route.value.message)
    return
  }
  activeTopic.value = undefined
  detailLoading.value = true
  try {
    const detail = await loadTopic(topic)
    if (request !== requestId) return
    activeTopic.value = detail
    document.title = `${topic.name_zh || topic.name} · Rust Zulip 中文日报`
    content.value?.scrollTo({ top: 0 })
    await nextTick()
  } catch (e) {
    if (request === requestId) detailError.value = e instanceof Error ? e.message : '正文加载失败'
  } finally {
    if (request === requestId) detailLoading.value = false
  }
}
function syncHash() {
  hash.value = location.hash
}
function keyboard(event: KeyboardEvent) {
  if (event.key === 'Escape') sidebarOpen.value = false
  if (search.value && (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault()
    search.value?.focus()
  }
}
function persistPositions() {
  store('rust-reader:positions', positions.value)
}
watch([hash, loading], openRoute)
watch([language, fontSize, theme], () => {
  store('rust-reader:preferences', {
    language: language.value,
    fontSize: fontSize.value,
    theme: theme.value,
  })
  document.documentElement.dataset.theme = theme.value
})
onMounted(() => {
  document.documentElement.dataset.theme = theme.value
  window.addEventListener('hashchange', syncHash)
  window.addEventListener('keydown', keyboard)
  window.addEventListener('pagehide', persistPositions)
  fetchCatalog()
})
onBeforeUnmount(() => {
  window.removeEventListener('hashchange', syncHash)
  window.removeEventListener('keydown', keyboard)
  window.removeEventListener('pagehide', persistPositions)
  clearTimeout(persistTimer)
  store('rust-reader:positions', positions.value)
})
</script>

<template>
  <a class="skip-link" href="#main-content" @click.prevent="content?.focus()">跳到主要内容</a>
  <div class="app-shell">
    <button
      v-if="sidebarOpen"
      class="sidebar-backdrop"
      aria-label="关闭导航"
      @click="sidebarOpen = false"
    ></button>
    <aside class="sidebar" :class="{ open: sidebarOpen }" aria-label="频道导航">
      <a class="brand" href="#" @click="browse('all')"
        ><span class="brand-mark">R<span>›</span></span
        ><span>Rust Zulip<small>中文日报</small></span></a
      >
      <div class="sidebar-section-label">工作台 <span>WORKSPACE</span></div>
      <nav class="primary-nav">
        <button
          :class="{ active: selectedView === 'all' && selectedChannel === 'all' }"
          @click="browse('all')"
        >
          <Inbox :size="18" />社区动态<span>{{ topics.length }}</span>
        </button>
        <button :class="{ active: selectedView === 'unread' }" @click="browse('unread')">
          <Radio :size="18" />未读话题<span>{{ unreadCount }}</span>
        </button>
        <button :class="{ active: selectedView === 'saved' }" @click="browse('saved')">
          <Bookmark :size="18" />我的收藏<span>{{ savedCount }}</span>
        </button>
      </nav>
      <div class="sidebar-section-label channel-heading">
        关注的频道 <span>{{ meta?.streams.length || '—' }}</span>
      </div>
      <nav class="channel-nav">
        <button
          v-for="stream in meta?.streams"
          :key="stream.key"
          :class="{ active: selectedChannel === stream.key && selectedView === 'all' }"
          @click="browse('all', stream.key)"
        >
          <Hash :size="17" /><span>{{ stream.display }}</span
          ><small>{{ stream.topics }}</small>
        </button>
      </nav>
      <div class="sidebar-about">
        <span class="live-dot"></span> 按需更新 · 本机整理
        <p>跟进 Rust 的下一步，<br />从读懂每一次讨论开始。</p>
      </div>
      <div class="sidebar-bottom">
        <a
          href="https://github.com/yilin0518/rust-zulip-zh-daily"
          target="_blank"
          rel="noopener noreferrer"
          ><CodeXml :size="16" />项目源码<ArrowRight :size="14" /></a
        ><span>为 Rust 中文社区而构建</span>
      </div>
    </aside>

    <div class="main-shell">
      <header class="topbar">
        <button
          class="icon-button mobile-menu"
          aria-label="打开导航"
          :aria-expanded="sidebarOpen"
          @click="sidebarOpen = !sidebarOpen"
        >
          <Menu :size="21" />
        </button>
        <div class="breadcrumb">
          <span>Rust 社区</span><ChevronRight :size="14" /><strong>{{
            activeTopic ? '话题阅读' : pageTitle
          }}</strong>
        </div>
        <div class="topbar-actions">
          <span class="update-status" :title="meta ? formatTime(meta.last_updated, true) : ''"
            ><i></i>{{ meta ? `更新于 ${formatTime(meta.last_updated)}` : '正在同步目录' }}</span
          ><button
            class="icon-button theme-toggle"
            :aria-label="theme === 'light' ? '切换深色主题' : '切换浅色主题'"
            @click="theme = theme === 'light' ? 'dark' : 'light'"
          >
            <Moon v-if="theme === 'light'" :size="18" /><Sun v-else :size="18" /></button
          ><a
            class="icon-button"
            href="https://github.com/yilin0518/rust-zulip-zh-daily#readme"
            target="_blank"
            rel="noopener noreferrer"
            aria-label="项目说明"
            ><CircleHelp :size="18"
          /></a>
        </div>
      </header>
      <main id="main-content" ref="content" class="workspace" tabindex="-1">
        <div v-if="meta?.sample && (activeTopic || detailLoading)" class="reader-sample">
          示例预览 · 以下内容为界面测试数据，不是实际社区发言。
        </div>
        <div v-if="loading" class="loading-state" role="status">
          <span class="spinner"></span>
          <h2>正在整理社区动态</h2>
          <p>读取话题目录与摘要…</p>
        </div>
        <div v-else-if="error" class="empty-state" role="alert">
          <Inbox :size="32" />
          <h2>暂时无法加载内容</h2>
          <p>{{ error }}</p>
          <button class="primary-button" @click="fetchCatalog">重新加载</button>
        </div>
        <div v-else-if="detailLoading" class="loading-state" role="status">
          <span class="spinner"></span>
          <p>正在加载讨论正文…</p>
        </div>
        <div v-else-if="detailError" class="empty-state" role="alert">
          <h2>话题暂时无法打开</h2>
          <p>{{ detailError }}</p>
          <div class="empty-actions">
            <a href="#" class="primary-button">返回话题列表</a
            ><button class="text-button" @click="openRoute">重试</button>
          </div>
        </div>
        <TopicReader
          v-else-if="activeTopic"
          :key="activeTopic.id"
          ref="reader"
          :topic="activeTopic"
          :saved="isSaved(activeTopic)"
          :language="language"
          :font-size="fontSize"
          :position="positions[keyFor(activeTopic)]"
          :target="route.message"
          @save="toggleSaved(activeTopic)"
          @language="language = $event"
          @font="fontSize = $event"
          @read="markRead(activeTopic, $event)"
        />

        <div v-else class="dashboard">
          <div v-if="meta?.sample" class="sample-banner">
            当前为本地示例数据，用于预览界面；不是实际社区发言。
          </div>
          <section class="welcome">
            <div class="eyebrow"><span class="live-dot"></span> RUST COMMUNITY, IN CHINESE</div>
            <h1>
              {{
                selectedView === 'all' && selectedChannel === 'all'
                  ? '社区的讨论，中文的视角。'
                  : pageTitle
              }}
            </h1>
            <p>
              {{
                selectedView === 'saved'
                  ? '把值得反复阅读的讨论，留在这里。收藏保存在当前浏览器。'
                  : selectedView === 'unread'
                    ? '继续探索还没读完的观点与进展。阅读记录保存在当前浏览器。'
                    : '从编译器到标准库，读懂 Rust 正在发生的变化。'
              }}
            </p>
            <div class="overview-stats">
              <span
                ><b>{{ topics.length }}</b> 个活跃话题</span
              ><span
                ><b>{{ messageCount.toLocaleString() }}</b> 条讨论消息</span
              ><span
                ><b>{{ meta?.streams.length }}</b> 个关注频道</span
              >
            </div>
          </section>

          <div class="discovery-bar">
            <label class="search-field"
              ><Search :size="18" /><input
                ref="search"
                v-model="query"
                type="search"
                placeholder="搜索话题标题、摘要…"
                aria-label="搜索话题标题和摘要" /><kbd>Ctrl K</kbd
              ><button v-if="query" class="icon-button" aria-label="清除搜索" @click="query = ''">
                <X :size="15" /></button
            ></label>
            <label class="sort-control"
              ><ArrowDownWideNarrow :size="16" /><select v-model="sort" aria-label="话题排序">
                <option value="recent">最近更新</option>
                <option value="active">讨论最多</option>
              </select></label
            >
          </div>
          <div class="channel-filters" aria-label="筛选频道">
            <button
              :class="{ selected: selectedChannel === 'all' }"
              @click="selectedChannel = 'all'"
            >
              全部频道</button
            ><button
              v-for="stream in meta?.streams"
              :key="stream.key"
              :class="{ selected: selectedChannel === stream.key }"
              @click="selectedChannel = stream.key"
            >
              # {{ stream.key }}
            </button>
          </div>

          <section v-if="featured" class="featured-section">
            <div class="section-heading">
              <h2>
                <span class="accent-line"></span>{{ sort === 'active' ? '热议话题' : '最新动态' }}
              </h2>
              <span>{{ sort === 'active' ? '按讨论消息数排序' : '从最新活跃的讨论开始' }}</span>
            </div>
            <TopicCard
              :topic="featured"
              :saved="isSaved(featured)"
              :unread="isUnread(featured)"
              featured
              @save="toggleSaved"
            />
          </section>
          <section v-if="listTopics.length || !featured" class="topic-section">
            <div class="section-heading">
              <h2>
                {{ query ? '搜索结果' : featured ? '更多讨论' : pageTitle
                }}<span class="count-pill">{{ listTopics.length }}</span>
              </h2>
              <button
                v-if="filtered.some(isUnread)"
                class="text-button mark-all"
                @click="markAllRead"
              >
                <CheckCheck :size="15" />全部标为已读
              </button>
            </div>
            <div v-if="listTopics.length" class="topic-grid">
              <TopicCard
                v-for="topic in listTopics"
                :key="topic.id"
                :topic="topic"
                :saved="isSaved(topic)"
                :unread="isUnread(topic)"
                @save="toggleSaved"
              />
            </div>
            <div v-else-if="!featured" class="empty-state">
              <Search v-if="query" :size="30" /><Bookmark
                v-else-if="selectedView === 'saved'"
                :size="30"
              /><CheckCheck v-else :size="30" />
              <h2>
                {{
                  query
                    ? '没有找到相关话题'
                    : selectedView === 'saved'
                      ? '还没有收藏话题'
                      : selectedView === 'unread'
                        ? '已读完当前列表'
                        : '暂无话题'
                }}
              </h2>
              <p>
                {{
                  query
                    ? '试试英文术语，或换一个关键词。'
                    : selectedView === 'saved'
                      ? '点击话题右上角的书签，即可加入收藏。'
                      : '下次更新后，再来看看新的讨论。'
                }}
              </p>
            </div>
          </section>
          <footer class="page-footer">
            <span
              >来自
              <a href="https://rust-lang.zulipchat.com" target="_blank" rel="noopener noreferrer"
                >rust-lang Zulip ↗</a
              ></span
            ><span>机器翻译与 AI 摘要 · 重要信息请对照原文</span>
          </footer>
        </div>
      </main>
    </div>
  </div>
</template>
