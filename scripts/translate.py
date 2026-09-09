#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""翻译模块：支持多后端（Google / MyMemory / DeepL / 火山方舟 ARK），带翻译缓存。

翻译策略：先把文本按「纯文本 / 代码块 / 行内代码 / URL / 邮箱」拆成段，
只翻译纯文本段（必要时按句子边界分块），代码与链接原样保留——避免翻译引擎破坏代码。

健壮性设计（2026-09 修订，修复云端挂起问题）：
- 启动时对每个后端做健康探测（probe），探测失败的后端本次运行直接跳过；
- 所有后端探测均失败时立即报错退出（保留上一次已部署的数据，避免静默产出英文站）；
- 单请求超时从 30s 降到 12s（ARK 30s），重试次数从 3 降到 2，并设置全局 socket 超时；
- 运行中某后端连续失败会被标记为失效，不再反复慢速重试。

环境变量：
  TRANSLATE_BACKEND : google | mymemory | deepl | ark | auto（默认 auto：优先 google，失败自动降级 mymemory）
  DEEPL_API_KEY     : DeepL API Key（免费 key 形如 xxxx:fx，使用 api-free.deepl.com）
  ARK_API_KEY       : 火山方舟 API Key（OpenAI 兼容接口，质量最佳）
  ARK_MODEL         : 火山方舟模型名或推理接入点 ID（如 doubao-seed-1-6-250615 或 ep-xxxxx）
  MYMEMORY_EMAIL    : MyMemory 邮箱参数（匿名每天 5000 字符；带邮箱每天 5 万字符）
"""
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

socket.setdefaulttimeout(15)  # 全局兜底：任何 socket 操作不超过 15s

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_PATH = os.path.join(ROOT, "data", "translation_cache.json")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# Google 单请求可承载较长文本，用大块减少请求数；MyMemory 单次 500 字符上限
GOOGLE_CHUNK_LIMIT = 2000
ARK_CHUNK_LIMIT = 4000  # ARK 上下文窗口大，用更大块减少调用次数
DEFAULT_CHUNK_LIMIT = 450
TIMEOUT = 12
ATTEMPTS = 2

# 请求节流：成功调用后的等待秒数（实测 Google 在 GitHub 运行器上 0.5s/次 稳定 60/60）
PACING = {"google": 0.5, "mymemory": 0.25, "deepl": 0.15, "ark": 0.1}
# 后端连续失败次数达到该值后，本次运行禁用（防止持久性故障拖慢整体）
DEAD_AFTER_CONSEC = 5
# 连续失败后的冷却（秒）：15s, 30s, 45s … 指数增长
COOLDOWN_BASE = 15

# MyMemory 匿名配额仅 5000 字符/天，带 de 参数（任意标识邮箱）提升到 5 万字符/天
MYMEMORY_DEFAULT_EMAIL = "rust-zulip-daily@users.noreply.github.com"


class TranslationError(Exception):
    pass


# ---------------- 文本分段 ----------------
# 奇数索引为「保留原样」的段：围栏代码块、双反引号、行内代码、URL、邮箱
_SEG_RE = re.compile(
    r"(`{3,}[^\n]*\n.*?`{3,}"       # fenced code block
    r"|`{2}[^`\n]+`{2}"             # double-backtick inline code
    r"|`[^`\n]{1,200}`"             # single-backtick inline code
    r"|https?://[^\s<>\"'）】]+"     # URL
    r"|[\w.+-]+@[\w-]+\.[A-Za-z]{2,})",  # email
    re.DOTALL,
)


def split_segments(text):
    """把文本拆成 [(段文本, 是否原样保留)]。"""
    parts = _SEG_RE.split(text)
    return [(parts[i], i % 2 == 1) for i in range(len(parts))]


def _chunk(text, limit):
    """按句子边界把长文本切成 ≤limit 字符的片段。"""
    if len(text) <= limit:
        return [text]
    chunks, cur = [], ""
    for seg in re.split(r"(?<=[.!?。！？\n])", text):
        if cur and len(cur) + len(seg) > limit:
            chunks.append(cur)
            cur = seg
        else:
            cur += seg
    if cur:
        chunks.append(cur)
    out = []
    for c in chunks:
        while len(c) > limit:
            out.append(c[:limit])
            c = c[limit:]
        if c:
            out.append(c)
    return out or [""]


# 高频 Rust 术语错译修正（机器翻译常见错误）
GLOSSARY = [
    ("借款检查器", "借用检查器"),   # borrow checker 直译错误
    ("生存期", "生命周期"),          # lifetime 统一用 Rust 官方译法
]


def apply_glossary(zh):
    for a, b in GLOSSARY:
        if a in zh:
            zh = zh.replace(a, b)
    return zh


# 繁体 → 简体 高频字映射（MyMemory 偶尔输出繁体，做确定性归一化）
_TRAD_SIMP_PAIRS = [
    ("這", "这"), ("們", "们"), ("後", "后"), ("時", "时"), ("說", "说"), ("裡", "里"),
    ("與", "与"), ("個", "个"), ("來", "来"), ("會", "会"), ("沒", "没"), ("麼", "么"),
    ("應", "应"), ("據", "据"), ("讓", "让"), ("對", "对"), ("現", "现"), ("點", "点"),
    ("還", "还"), ("過", "过"), ("幾", "几"), ("開", "开"), ("關", "关"), ("號", "号"),
    ("樣", "样"), ("種", "种"), ("處", "处"), ("經", "经"), ("統", "统"), ("給", "给"),
    ("聯", "联"), ("網", "网"), ("總", "总"), ("譯", "译"), ("語", "语"), ("論", "论"),
    ("認", "认"), ("設", "设"), ("讀", "读"), ("變", "变"), ("資", "资"), ("質", "质"),
    ("轉", "转"), ("進", "进"), ("遠", "远"), ("選", "选"), ("長", "长"), ("響", "响"),
    ("驗", "验"), ("體", "体"), ("實", "实"), ("標", "标"), ("結", "结"), ("紙", "纸"),
    ("聞", "闻"), ("義", "义"), ("勝", "胜"), ("臺", "台"), ("規", "规"), ("記", "记"),
    ("試", "试"), ("詢", "询"), ("該", "该"), ("貨", "货"), ("賣", "卖"), ("購", "购"),
    ("費", "费"), ("責", "责"), ("賠", "赔"), ("贈", "赠"), ("輸", "输"), ("車", "车"),
    ("軍", "军"), ("農", "农"), ("邊", "边"), ("達", "达"), ("運", "运"), ("遊", "游"),
    ("陽", "阳"), ("隊", "队"), ("階", "阶"), ("隨", "随"), ("雙", "双"), ("難", "难"),
    ("雲", "云"), ("電", "电"), ("頁", "页"), ("項", "项"), ("須", "须"), ("領", "领"),
    ("顆", "颗"), ("題", "题"), ("館", "馆"), ("馬", "马"), ("鳥", "鸟"), ("黃", "黄"),
    ("黨", "党"), ("嗎", "吗"), ("請", "请"), ("講", "讲"), ("誰", "谁"), ("謝", "谢"),
    ("證", "证"), ("議", "议"), ("護", "护"), ("負", "负"), ("貴", "贵"), ("買", "买"),
    ("賤", "贱"), ("賜", "赐"), ("賞", "赏"), ("贏", "赢"),
    ("為", "为"), ("於", "于"), ("從", "从"), ("卻", "却"), ("問", "问"),
    ("間", "间"), ("門", "门"), ("見", "见"), ("產", "产"), ("業", "业"),
    ("員", "员"), ("滿", "满"), ("庫", "库"), ("參", "参"), ("區", "区"),
    ("錯", "错"), ("錢", "钱"), ("錄", "录"), ("鎖", "锁"), ("際", "际"),
    ("順", "顺"), ("預", "预"), ("飛", "飞"), ("東", "东"), ("樂", "乐"),
    ("樓", "楼"), ("機", "机"), ("權", "权"), ("歷", "历"), ("節", "节"),
    ("單", "单"), ("圖", "图"), ("場", "场"), ("聲", "声"), ("學", "学"),
    ("寫", "写"), ("層", "层"), ("幫", "帮"), ("幹", "干"), ("廠", "厂"),
    ("廣", "广"), ("彈", "弹"), ("復", "复"), ("態", "态"), ("懷", "怀"),
    ("書", "书"), ("術", "术"), ("氣", "气"), ("準", "准"), ("無", "无"),
    ("熱", "热"), ("狀", "状"), ("環", "环"), ("當", "当"), ("畫", "画"),
    ("發", "发"), ("確", "确"), ("碼", "码"), ("積", "积"), ("穩", "稳"),
    ("簡", "简"), ("類", "类"), ("紅", "红"), ("紀", "纪"), ("約", "约"),
    ("維", "维"), ("緊", "紧"), ("線", "线"), ("縣", "县"), ("繼", "继"),
    ("續", "续"), ("習", "习"), ("聖", "圣"), ("聽", "听"), ("職", "职"),
    ("藝", "艺"), ("蟲", "虫"), ("補", "补"), ("裝", "装"), ("複", "复"),
    ("觀", "观"), ("計", "计"), ("訓", "训"), ("註", "注"), ("詳", "详"),
    ("誤", "误"), ("貝", "贝"), ("貫", "贯"), ("貼", "贴"), ("賓", "宾"),
    ("賬", "账"), ("較", "较"), ("輕", "轻"), ("辦", "办"), ("連", "连"),
    ("鄉", "乡"), ("醫", "医"), ("鐘", "钟"), ("閉", "闭"), ("陸", "陆"),
    ("離", "离"), ("雜", "杂"), ("雞", "鸡"), ("霧", "雾"), ("願", "愿"),
    ("頂", "顶"), ("頻", "频"), ("額", "额"), ("顧", "顾"), ("顯", "显"),
    ("駕", "驾"), ("騙", "骗"), ("髮", "发"), ("鮮", "鲜"), ("齊", "齐"),
    ("齒", "齿"), ("龍", "龙"), ("龜", "龟"), ("歸", "归"), ("筆", "笔"),
    ("範", "范"), ("嚮", "向"), ("讚", "赞"), ("兩", "两"),
    ("別", "别"), ("動", "动"), ("務", "务"), ("勢", "势"), ("圓", "圆"),
    ("報", "报"), ("牆", "墙"), ("媽", "妈"), ("歲", "岁"), ("帥", "帅"),
    ("徑", "径"), ("戲", "戏"), ("戶", "户"), ("擔", "担"), ("擬", "拟"),
    ("擠", "挤"), ("斷", "断"), ("殼", "壳"), ("減", "减"), ("漢", "汉"),
    ("澤", "泽"), ("燒", "烧"), ("爭", "争"), ("異", "异"),
    ("築", "筑"), ("純", "纯"),
]
_TRAD2SIMP = str.maketrans(
    "".join(p[0] for p in _TRAD_SIMP_PAIRS),
    "".join(p[1] for p in _TRAD_SIMP_PAIRS),
)


def apply_simp(zh):
    return zh.translate(_TRAD2SIMP)


# ---------------- 翻译后端 ----------------
class GoogleTranslator:
    name = "google"
    URL = "https://translate.googleapis.com/translate_a/single"

    def translate_one(self, text):
        data = urllib.parse.urlencode([
            ("client", "gtx"), ("sl", "en"), ("tl", "zh-CN"), ("dt", "t"), ("q", text),
        ])
        for attempt in range(ATTEMPTS):
            try:
                req = urllib.request.Request(
                    self.URL, data=data.encode("utf-8"),
                    headers={"Content-Type": "application/x-www-form-urlencoded",
                             "User-Agent": UA})
                with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                    raw = r.read().decode("utf-8", "replace")
                if "Sorry" in raw or raw.lstrip().startswith("<html"):
                    raise TranslationError("google 返回拦截页（反爬）")
                parsed = json.loads(raw)
                sentences = parsed[0] if isinstance(parsed, list) and parsed else []
                out = "".join(s[0] for s in sentences
                              if isinstance(s, list) and s and isinstance(s[0], str))
                if not out:
                    raise TranslationError("google 返回空结果")
                return out
            except TranslationError:
                raise
            except urllib.error.HTTPError as e:
                if e.code in (429, 403, 503) and attempt < ATTEMPTS - 1:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise TranslationError("google http %s" % e.code)
            except (urllib.error.URLError, ValueError, OSError) as e:
                if attempt < ATTEMPTS - 1:
                    time.sleep(1)
                    continue
                raise TranslationError("google 网络错误: %s" % e)
        raise TranslationError("google 失败")


class MyMemoryTranslator:
    name = "mymemory"
    URL = "https://api.mymemory.translated.net/get"

    def translate_one(self, text):
        params = [("q", text), ("langpair", "en|zh-CN")]
        email = os.environ.get("MYMEMORY_EMAIL", "").strip() or MYMEMORY_DEFAULT_EMAIL
        params.append(("de", email))
        url = self.URL + "?" + urllib.parse.urlencode(params)
        for attempt in range(ATTEMPTS):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                    parsed = json.loads(r.read().decode("utf-8", "replace"))
                if parsed.get("responseStatus") != 200:
                    raise TranslationError("mymemory status=%s" % parsed.get("responseStatus"))
                out = parsed.get("responseData", {}).get("translatedText", "")
                if not out:
                    raise TranslationError("mymemory 返回空")
                out = re.sub(r"<ex[^>]*/>", "", out)  # 去掉记忆库示例标记
                return out
            except TranslationError:
                raise
            except urllib.error.HTTPError as e:
                if e.code in (429, 403, 503) and attempt < ATTEMPTS - 1:
                    time.sleep(3 * (attempt + 1))
                    continue
                raise TranslationError("mymemory http %s" % e.code)
            except (urllib.error.URLError, ValueError, OSError) as e:
                if attempt < ATTEMPTS - 1:
                    time.sleep(1)
                    continue
                raise TranslationError("mymemory 网络错误: %s" % e)
        raise TranslationError("mymemory 失败")


class DeepLTranslator:
    name = "deepl"

    def __init__(self):
        self.key = os.environ.get("DEEPL_API_KEY", "").strip()
        if not self.key:
            raise TranslationError("缺少 DEEPL_API_KEY")
        host = "api-free.deepl.com" if self.key.endswith(":fx") else "api.deepl.com"
        self.URL = "https://%s/v2/translate" % host

    def translate_one(self, text):
        body = json.dumps({"text": [text], "source_lang": "EN", "target_lang": "ZH"}).encode("utf-8")
        req = urllib.request.Request(
            self.URL, data=body, headers={
                "Authorization": "DeepL-Auth-Key " + self.key,
                "Content-Type": "application/json", "User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                parsed = json.loads(r.read().decode("utf-8", "replace"))
            return parsed["translations"][0]["text"]
        except urllib.error.HTTPError as e:
            raise TranslationError("deepl http %s: %s" % (e.code, e.read()[:200]))
        except (urllib.error.URLError, ValueError, KeyError, OSError) as e:
            raise TranslationError("deepl 错误: %s" % e)


class ARKTranslator:
    """火山方舟（豆包）OpenAI 兼容接口，翻译质量最好。"""
    name = "ark"
    URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"

    def __init__(self):
        self.key = os.environ.get("ARK_API_KEY", "").strip()
        self.model = os.environ.get("ARK_MODEL", "").strip()
        if not self.key or not self.model:
            raise TranslationError("缺少 ARK_API_KEY / ARK_MODEL")

    def translate_one(self, text):
        payload = json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system", "content": (
                    "你是专业翻译。把用户提供的英文（来自 Rust 编程语言社区聊天）翻译成自然、"
                    "地道的简体中文。代码、标识符、文件名、URL、邮箱保持原样。只输出译文，不要任何解释。")},
                {"role": "user", "content": text},
            ],
            "temperature": 0.2,
            "thinking": {"type": "disabled"},  # 关闭推理：翻译任务不需要思考链，显著降低时延
        }).encode("utf-8")
        for attempt in range(2):
            try:
                req = urllib.request.Request(
                    self.URL, data=payload, headers={
                        "Authorization": "Bearer " + self.key,
                        "Content-Type": "application/json", "User-Agent": UA})
                with urllib.request.urlopen(req, timeout=120) as r:
                    parsed = json.loads(r.read().decode("utf-8", "replace"))
                return parsed["choices"][0]["message"]["content"].strip()
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503) and attempt < 1:
                    time.sleep(2)
                    continue
                raise TranslationError("ark http %s: %s" % (e.code, e.read()[:200]))
            except (urllib.error.URLError, ValueError, KeyError, OSError) as e:
                if attempt < 1:
                    time.sleep(1)
                    continue
                raise TranslationError("ark 错误: %s" % e)
        raise TranslationError("ark 失败")


def build_backends():
    """按优先级返回后端列表。TRANSLATE_BACKEND 显式指定时只用该后端（无降级链）；
    auto（默认）时：配置了 ARK 则 [ARK, google, mymemory]，否则 [google, mymemory]。"""
    name = (os.environ.get("TRANSLATE_BACKEND") or "auto").strip().lower()
    if name == "deepl":
        return [DeepLTranslator()]
    if name == "ark":
        return [ARKTranslator()]
    if name == "mymemory":
        return [MyMemoryTranslator()]
    if name == "google":
        return [GoogleTranslator()]
    backends = [GoogleTranslator(), MyMemoryTranslator()]
    try:
        ark = ARKTranslator()
        backends = [ark] + backends
    except TranslationError:
        pass  # 未配置 ARK：走 google + mymemory
    return backends


# ---------------- 缓存 ----------------
class Cache:
    def __init__(self, path=CACHE_PATH):
        self.path = path
        self.data = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    self.data = loaded
            except Exception:
                self.data = {}

    def get(self, key, src=None):
        v = self.data.get(str(key))
        if not isinstance(v, dict):
            return None
        if src is not None and v.get("en") != src:
            return None
        return v.get("zh")

    def put(self, key, src, zh, backend):
        self.data[str(key)] = {"en": src, "zh": zh, "backend": backend}

    def save(self):
        d = os.path.dirname(self.path)
        os.makedirs(d, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False)
        os.replace(tmp, self.path)


# ---------------- 统一入口 ----------------
class Translator:
    def __init__(self, cache=None):
        self.cache = cache or Cache()
        self.backends = build_backends()
        self.stats = {"backend": {}, "chars": 0, "failed": 0}
        self._dead = {b.name: False for b in self.backends}
        self._consec = {b.name: 0 for b in self.backends}
        self._cooldown_until = {b.name: 0.0 for b in self.backends}
        self._chunk_limit = DEFAULT_CHUNK_LIMIT
        self._last_backend = ""
        self._probe()

    def _probe(self):
        """启动探测：用短文本实测每个后端，失败的后端本次运行直接禁用。"""
        probe_text = "Hello, Rust community!"
        for b in self.backends:
            ok = False
            try:
                out = b.translate_one(probe_text)
                ok = bool(out and out.strip())
            except TranslationError:
                ok = False
            except Exception:
                ok = False
            if ok:
                print("[backend] %s 可用 (探测: %s)" % (b.name, out.strip()[:40]), flush=True)
                if b.name == "google":
                    self._chunk_limit = GOOGLE_CHUNK_LIMIT
                elif b.name == "ark":
                    self._chunk_limit = ARK_CHUNK_LIMIT
            else:
                self._dead[b.name] = True
                print("[backend] %s 不可用，本次运行跳过" % b.name, flush=True)
        alive_names = [n for n, a in self._dead.items() if not a]
        if not alive_names:
            raise TranslationError(
                "所有翻译后端均不可用（%s）。请检查网络，或配置 DEEPL_API_KEY / ARK_API_KEY。"
                % ",".join(self._dead.keys()))
        print("[backend] 本次运行使用: %s（分块上限 %d 字符，节流 %ss）"
              % (",".join(alive_names), self._chunk_limit, PACING.get(alive_names[0], 0.2)),
              flush=True)

    def translate(self, text, cache_key=None):
        """翻译单条文本。cache_key 非空时按 key 缓存（key 通常为消息 id 或标题键）。"""
        text = (text or "").strip()
        if not text:
            return ""
        if cache_key is not None:
            hit = self.cache.get(cache_key, text)
            if hit is not None:
                return hit
        before = sum(self.stats["backend"].values())
        segments = split_segments(text)
        outs = []
        for seg, keep in segments:
            if keep or not seg.strip():
                outs.append(seg)  # 代码/URL/空段原样保留
            else:
                translated = [self._translate_seg(c) for c in _chunk(seg, self._chunk_limit)]
                outs.append("".join(translated))
        zh = apply_simp(apply_glossary("".join(outs))).strip()
        # 只有实际发生了翻译（至少一次后端成功）才写缓存；
        # 失败的翻译若写入缓存会把英文当译文缓存，导致下次运行跳过重译。
        translated_any = sum(self.stats["backend"].values()) > before
        if cache_key is not None and translated_any:
            self.cache.put(cache_key, text, zh, self._last_backend)
        return zh

    def _translate_seg(self, seg):
        if not seg.strip():
            return seg
        now = time.time()
        for b in self.backends:
            if self._dead.get(b.name) or now < self._cooldown_until[b.name]:
                continue
            try:
                out = b.translate_one(seg)
                self._consec[b.name] = 0
                self._cooldown_until[b.name] = 0.0
                self._last_backend = b.name
                self.stats["backend"][b.name] = self.stats["backend"].get(b.name, 0) + 1
                self.stats["chars"] += len(seg)
                pace = PACING.get(b.name, 0.2)
                if pace > 0:
                    time.sleep(pace)  # 节流：避免突发请求触发限流
                return out
            except TranslationError:
                self._consec[b.name] += 1
                if self._consec[b.name] >= DEAD_AFTER_CONSEC:
                    self._dead[b.name] = True
                    print("[warn] 后端 %s 连续 %d 次失败，本次运行禁用"
                          % (b.name, DEAD_AFTER_CONSEC), flush=True)
                else:
                    self._cooldown_until[b.name] = now + COOLDOWN_BASE * self._consec[b.name]
                time.sleep(0.2)
        self.stats["failed"] += 1
        return seg  # 全部失败：保留原文，下轮再试

    # ---------------- 批量翻译（ARK） ----------------
    _MARKER_RE = re.compile(r"【消息#(\d+)】\s*", re.MULTILINE)

    def translate_batch(self, items, max_msgs=20, max_chars=8000):
        """批量翻译多条文本，返回 {cache_key: zh}。

        items: [(cache_key, text), ...]
        命中缓存直接返回；未命中时若 ARK 可用则合并为一个请求翻译（标记模板 + 逐条解析），
        解析失败的消息回退到逐条翻译。逐条写缓存，保持增量更新能力。
        """
        result = {}
        todo = []
        for key, text in items:
            text = (text or "").strip()
            if not text:
                result[key] = ""
                continue
            hit = self.cache.get(key, text)
            if hit is not None:
                result[key] = hit
                continue
            todo.append((key, text))
        if not todo:
            return result
        ark = next((b for b in self.backends
                    if b.name == "ark" and not self._dead.get(b.name)), None)
        if ark is None:
            for key, text in todo:
                result[key] = self.translate(text, cache_key=key)
            return result
        batch, chars = [], 0
        for key, text in todo:
            if len(batch) >= max_msgs or (batch and chars + len(text) > max_chars):
                self._flush_batch(ark, batch, result)
                batch, chars = [], 0
            batch.append((key, text))
            chars += len(text)
        if batch:
            self._flush_batch(ark, batch, result)
        return result

    def _flush_batch(self, ark, batch, result):
        numbered = ["【消息#%d】\n%s" % (i, text) for i, (_, text) in enumerate(batch, 1)]
        prompt = ("以下是来自 Rust 编程语言社区的多条英文消息，请逐条翻译成自然、地道的简体中文。"
                  "代码、标识符、文件名、URL、邮箱保持原样。"
                  "输出格式：每条译文前必须保留输入中的标记（如【消息#1】），一行一个标记，"
                  "标记后接该条译文。不要输出任何其他内容。\n\n"
                  + "\n".join(numbered))
        try:
            out = ark.translate_one(prompt)
            parsed = self._parse_batch(out, len(batch))
        except TranslationError:
            parsed = {}
        self.stats["backend"]["ark"] = self.stats["backend"].get("ark", 0) + 1
        self.stats["chars"] += sum(len(text) for _, text in batch)
        for i, (key, text) in enumerate(batch, 1):
            zh = parsed.get(i)
            if zh:
                zh = apply_simp(apply_glossary(zh)).strip()
                result[key] = zh
                self.cache.put(key, text, zh, "ark")
            else:
                # 该条解析失败/缺失：回退逐条翻译
                result[key] = self.translate(text, cache_key=key)
        time.sleep(0.1)

    def _parse_batch(self, out, n):
        """解析 '【消息#N】译文' 输出，返回 {N: 译文}。损坏或缺失的项不返回。"""
        parts = self._MARKER_RE.split(out)
        res = {}
        for i in range(1, len(parts) - 1, 2):
            try:
                idx = int(parts[i])
            except ValueError:
                continue
            text = (parts[i + 1] or "").strip()
            if 1 <= idx <= n and text:
                res[idx] = text
        return res
