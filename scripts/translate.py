#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""翻译模块：支持多后端（Google / MyMemory / DeepL / 火山方舟 ARK），带翻译缓存。

翻译策略：先把文本按「纯文本 / 代码块 / 行内代码 / URL / 邮箱」拆成段，
只翻译纯文本段（必要时按句子边界分块），代码与链接原样保留——避免翻译引擎破坏代码。

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
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

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


def _chunk(text, limit=450):
    """按句子边界把长文本切成 ≤limit 字符的片段（MyMemory 单次上限 500 字符）。"""
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
    ("範", "范"), ("嚮", "向"), ("讚", "赞"), ("個", "个"), ("兩", "两"),
    ("別", "别"), ("動", "动"), ("務", "务"), ("勢", "势"), ("圓", "圆"),
    ("報", "报"), ("牆", "墙"), ("媽", "妈"), ("歲", "岁"), ("帥", "帅"),
    ("徑", "径"), ("戲", "戏"), ("戶", "户"), ("擔", "担"), ("擬", "拟"),
    ("擠", "挤"), ("斷", "断"), ("殼", "壳"), ("減", "减"), ("漢", "汉"),
    ("澤", "泽"), ("燒", "烧"), ("爭", "争"), ("確", "确"), ("異", "异"),
    ("築", "筑"), ("純", "纯"), ("習", "习"), ("術", "术"), ("複", "复"),
    ("計", "计"), ("訓", "训"), ("註", "注"), ("誤", "误"), ("貝", "贝"),
    ("負", "负"), ("貴", "贵"), ("買", "买"), ("賤", "贱"), ("賜", "赐"),
    ("賞", "赏"), ("贏", "赢"), ("與", "与"), ("個", "个"),
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
        for attempt in range(3):
            try:
                req = urllib.request.Request(
                    self.URL, data=data.encode("utf-8"),
                    headers={"Content-Type": "application/x-www-form-urlencoded",
                             "User-Agent": UA})
                with urllib.request.urlopen(req, timeout=30) as r:
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
                if e.code in (429, 403, 503) and attempt < 2:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise TranslationError("google http %s" % e.code)
            except (urllib.error.URLError, ValueError, OSError) as e:
                if attempt < 2:
                    time.sleep(1)
                    continue
                raise TranslationError("google 网络错误: %s" % e)
        raise TranslationError("google 失败")


class MyMemoryTranslator:
    name = "mymemory"
    URL = "https://api.mymemory.translated.net/get"

    def translate_one(self, text):
        params = [("q", text), ("langpair", "en|zh-CN")]
        email = os.environ.get("MYMEMORY_EMAIL", "").strip()
        if email:
            params.append(("de", email))
        url = self.URL + "?" + urllib.parse.urlencode(params)
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=30) as r:
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
                if e.code in (429, 403, 503) and attempt < 2:
                    time.sleep(3 * (attempt + 1))
                    continue
                raise TranslationError("mymemory http %s" % e.code)
            except (urllib.error.URLError, ValueError, OSError) as e:
                if attempt < 2:
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
            with urllib.request.urlopen(req, timeout=30) as r:
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
                    "地道的简体中文。代码、标识符、文件名、URL 保持原样。只输出译文，不要任何解释。")},
                {"role": "user", "content": text},
            ],
            "temperature": 0.2,
        }).encode("utf-8")
        req = urllib.request.Request(
            self.URL, data=payload, headers={
                "Authorization": "Bearer " + self.key,
                "Content-Type": "application/json", "User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                parsed = json.loads(r.read().decode("utf-8", "replace"))
            return parsed["choices"][0]["message"]["content"].strip()
        except urllib.error.HTTPError as e:
            raise TranslationError("ark http %s: %s" % (e.code, e.read()[:200]))
        except (urllib.error.URLError, ValueError, KeyError, OSError) as e:
            raise TranslationError("ark 错误: %s" % e)


def build_backends():
    name = (os.environ.get("TRANSLATE_BACKEND") or "auto").strip().lower()
    if name == "deepl":
        return [DeepLTranslator()]
    if name == "ark":
        return [ARKTranslator()]
    if name == "mymemory":
        return [MyMemoryTranslator()]
    return [GoogleTranslator(), MyMemoryTranslator()]  # google / auto


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
        self._preferred_dead = False
        self._last_backend = ""

    def translate(self, text, cache_key=None):
        """翻译单条文本。cache_key 非空时按 key 缓存（key 通常为消息 id 或标题键）。"""
        text = (text or "").strip()
        if not text:
            return ""
        if cache_key is not None:
            hit = self.cache.get(cache_key, text)
            if hit is not None:
                return hit
        segments = split_segments(text)
        outs = []
        for seg, keep in segments:
            if keep or not seg.strip():
                outs.append(seg)  # 代码/URL/空段原样保留
            else:
                translated = [self._translate_seg(c) for c in _chunk(seg)]
                outs.append("".join(translated))
        zh = apply_simp(apply_glossary("".join(outs))).strip()
        if cache_key is not None:
            self.cache.put(cache_key, text, zh, self._last_backend)
        return zh

    def _translate_seg(self, seg):
        if not seg.strip():
            return seg
        last_err = None
        for b in self.backends:
            if b.name == self.backends[0].name and self._preferred_dead:
                continue
            try:
                out = b.translate_one(seg)
                self._last_backend = b.name
                self.stats["backend"][b.name] = self.stats["backend"].get(b.name, 0) + 1
                self.stats["chars"] += len(seg)
                return out
            except TranslationError as e:
                last_err = e
                if b.name == self.backends[0].name:
                    self._preferred_dead = True  # 本会话内不再尝试首选后端
                time.sleep(0.4)
        self.stats["failed"] += 1
        return seg  # 全部失败：保留原文，下轮再试
