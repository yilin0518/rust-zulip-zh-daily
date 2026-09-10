/* Rust Zulip 中文日报 - 前端逻辑（原生 JS，无依赖） */
"use strict";

const $ = (s) => document.querySelector(s);

const state = {
  meta: null,
  data: {},          // streamKey -> {stream, display, topics:[...]}
  sel: null,         // {stream, topic}
  q: "",
  lang: "both",      // both | zh | en
  collapsed: {},
};

/* ---------- 工具 ---------- */
function esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

function parseTs(ts) {
  if (ts == null || ts === "") return null;
  if (typeof ts === "number") return new Date(ts * 1000); // Unix 秒
  const d = new Date(ts); // ISO 字符串
  return isNaN(d.getTime()) ? null : d;
}

function fmtTime(ts) {
  const d = parseTs(ts);
  if (!d) return "";
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  const opt = sameDay
    ? { hour: "2-digit", minute: "2-digit" }
    : { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" };
  return d.toLocaleString("zh-CN", opt);
}

function fmtFull(ts) {
  const d = parseTs(ts);
  if (!d) return "";
  return d.toLocaleString("zh-CN", {
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}

/* 极简 Markdown 渲染（先转义，再处理代码块/行内代码/链接/引用/加粗/列表/段落） */
function md(src) {
  if (!src) return "";
  let s = esc(src);
  // 围栏代码块
  s = s.replace(/```([\w+-]*)\n([\s\S]*?)```/g, (m, lang, code) =>
    `<pre><code>${code.trimEnd()}</code></pre>`);
  // 行内代码（含双反引号）
  s = s.replace(/`{2}([^`\n]+)`{2}|`([^`\n]+)`/g, (m, a, b) => `<code>${a || b}</code>`);
  // 链接 [text](url)
  s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  // 引用行
  s = s.split("\n").map((line) => {
    const q = line.match(/^(&gt;|&gt;)\s?(.*)$/);
    return q ? `<blockquote>${q[2]}</blockquote>` : line;
  }).join("\n");
  // 加粗 / 斜体
  s = s.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/__([^_\n]+)__/g, "<strong>$1</strong>");
  s = s.replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
  s = s.replace(/(^|[^_])_([^_\n]+)_/g, "$1<em>$2</em>");
  // 简单列表：行首 - / * / 数字. -> <li>
  const lines = s.split("\n");
  let html = "", inList = false;
  const closeList = () => { if (inList) { html += "</ul>"; inList = false; } };
  for (const line of lines) {
    const li = line.match(/^\s*[-*]\s+(.*)$/) || line.match(/^\s*\d+\.\s+(.*)$/);
    if (li) {
      if (!inList) { html += "<ul>"; inList = true; }
      html += `<li>${li[1]}</li>`;
    } else {
      closeList();
      html += line + "\n";
    }
  }
  closeList();
  // 段落：空行分隔
  return html.split(/\n{2,}/).map((p) => `<p>${p.replace(/\n/g, "<br>")}</p>`).join("");
}

/* ---------- 渲染 ---------- */
function isSel(s, t) {
  return state.sel && state.sel.stream === s && state.sel.topic === t;
}

function matchTopic(t) {
  const q = state.q.trim().toLowerCase();
  if (!q) return true;
  return (t.name || "").toLowerCase().includes(q) ||
         (t.name_zh || "").toLowerCase().includes(q);
}

function renderAll() {
  document.body.dataset.lang = state.lang;
  renderUpdated();
  renderNav();
  renderMessages();
  renderSeg();
}

function renderUpdated() {
  if (state.meta && state.meta.last_updated) {
    $("#updatedAt").textContent = "更新于 " + fmtFull(state.meta.last_updated);
  }
}

function renderSeg() {
  document.querySelectorAll(".seg button").forEach((b) => {
    b.classList.toggle("active", b.dataset.lang === state.lang);
  });
}

function renderNav() {
  const nav = $("#streamNav");
  nav.innerHTML = "";
  if (!state.meta) return;
  let any = false;
  for (const ms of state.meta.streams) {
    const d = state.data[ms.key];
    if (!d) continue;
    const topics = d.topics.filter(matchTopic);
    if (!state.q && topics.length === 0) continue;
    const open = state.collapsed[ms.key] !== true;
    const sec = document.createElement("section");
    sec.className = "stream" + (open ? " open" : "");

    const head = document.createElement("button");
    head.className = "stream-head";
    head.innerHTML =
      `<span class="dot"></span><span>${esc(d.display)}</span>` +
      `<span class="stream-count">${topics.length}${state.q ? "/" + d.topics.length : ""}</span>` +
      `<span class="chev">&#9656;</span>`;
    head.addEventListener("click", () => {
      state.collapsed[ms.key] = !open;
      renderNav();
    });
    sec.appendChild(head);

    if (open) {
      const ul = document.createElement("ul");
      ul.className = "topic-list";
      for (const t of topics) {
        const li = document.createElement("li");
        li.className = "topic" + (isSel(ms.key, t.name) ? " active" : "");
        li.innerHTML =
          `<div class="t-en">${esc(t.name)}</div>` +
          `<div class="t-zh">${esc(t.name_zh || "")}</div>` +
          `<div class="t-meta">${t.count} 条 · ${fmtTime(t.last)}</div>`;
        li.addEventListener("click", () => {
          state.sel = { stream: ms.key, topic: t.name };
          if (window.matchMedia("(max-width: 860px)").matches) closeSidebar();
          renderAll();
          $("#content").scrollTop = 0;
        });
        ul.appendChild(li);
      }
      if (topics.length === 0) {
        const p = document.createElement("div");
        p.className = "no-result";
        p.textContent = "无匹配话题";
        ul.appendChild(p);
      }
      sec.appendChild(ul);
    }
    nav.appendChild(sec);
    any = true;
  }
  if (!any) {
    const p = document.createElement("div");
    p.className = "no-result";
    p.textContent = "无匹配结果";
    nav.appendChild(p);
  }
}

function renderMessages() {
  if (!state.sel) {
    $("#empty").hidden = false;
    $("#topicView").hidden = true;
    return;
  }
  const d = state.data[state.sel.stream];
  const t = d && d.topics.find((x) => x.name === state.sel.topic);
  if (!t) {
    state.sel = null;
    renderMessages();
    return;
  }
  $("#empty").hidden = true;
  $("#topicView").hidden = false;
  $("#topicTitle").textContent = t.name;
  $("#topicTitleZh").textContent = t.name_zh || "";
  $("#topicMeta").textContent =
    `${t.count} 条消息 · 最后活跃 ${fmtFull(t.last)} · 最早 ${fmtFull(t.first)}`;

  const sourceLink = $("#topicSourceLink");
  if (t.zulip_url) {
    sourceLink.href = t.zulip_url;
    sourceLink.hidden = false;
  } else {
    sourceLink.removeAttribute("href");
    sourceLink.hidden = true;
  }

  const summaryBox = $("#topicSummary");
  if (t.summary) {
    $("#summaryContent").innerHTML = md(t.summary);
    summaryBox.hidden = false;
  } else {
    $("#summaryContent").textContent = "";
    summaryBox.hidden = true;
  }

  const box = $("#messages");
  box.innerHTML = "";
  for (const m of t.messages) {
    const el = document.createElement("div");
    el.className = "msg";
    el.innerHTML =
      `<div class="msg-head"><span class="sender">${esc(m.sender)}</span>` +
      `<span class="time">${fmtFull(m.time)}</span></div>` +
      `<div class="msg-zh">${md(m.zh)}</div>` +
      `<div class="msg-en">${md(m.en)}</div>`;
    box.appendChild(el);
  }
  document.title = t.name + " · Rust Zulip 中文日报";
}

/* ---------- 事件 ---------- */
function bindEvents() {
  $("#search").addEventListener("input", (e) => {
    state.q = e.target.value;
    renderNav();
  });
  document.querySelectorAll(".seg button").forEach((b) => {
    b.addEventListener("click", () => {
      state.lang = b.dataset.lang;
      renderAll();
    });
  });
  $("#menuBtn").addEventListener("click", () => {
    $("#sidebar").classList.toggle("open");
  });
  $("#backdrop").addEventListener("click", closeSidebar);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeSidebar();
  });
}

function closeSidebar() {
  $("#sidebar").classList.remove("open");
}

/* ---------- 初始化 ---------- */
async function init() {
  bindEvents();
  try {
    const meta = await (await fetch("data/meta.json")).json();
    state.meta = meta;
    await Promise.all(meta.streams.map(async (ms) => {
      const r = await fetch("data/" + ms.file);
      state.data[ms.key] = await r.json();
    }));
    renderAll();
  } catch (e) {
    $("#content").innerHTML =
      `<div class="empty"><div class="empty-mark">!</div>` +
      `<div>数据加载失败：${esc(e.message)}<br><span style="font-size:12px;color:var(--muted)">请确认站点数据已生成（运行 scripts/pipeline.py）</span></div></div>`;
  }
}

init();
