# -*- coding: utf-8 -*-
"""生成本地开发用的样例数据（无凭据时预览界面用）：python scripts/make_sample_data.py
会写入 site/data/*.json；运行真实管线（pipeline.py）后会覆盖。"""
import json, os, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "site", "data")
os.makedirs(OUT, exist_ok=True)

now = int(time.time())
base = now - 86400

def msg(mid, sender, zh, en, off=0):
    return {"id": mid, "sender": sender, "time": base + off,
            "zh": zh, "en": en}

streams = {
    "general": {
        "display": "general",
        "topics": [
            {"name": "Welcome to the Rust community",
             "name_zh": "欢迎来到 Rust 社区",
             "messages": [
                 msg(1001, "Alice", "欢迎来到 Rust Zulip！请阅读行为准则。",
                     "Welcome to the Rust Zulip! Please read the code of conduct."),
                 msg(1002, "Bob", "谢谢！我已经读过了。",
                     "Thanks! I already read it."),
             ]},
            {"name": "What are you working on?",
             "name_zh": "你最近在做什么？",
             "messages": [
                 msg(1003, "Carol", "我正在做一个用 Rust 写的文本编辑器。",
                     "I'm working on a text editor written in Rust."),
                 msg(1004, "Dave", "酷！是用 egui 还是 TUI？",
                     "Cool! Using egui or a TUI?"),
                 msg(1005, "Carol", "我倾向于 TUI，用 `ratatui` 构建。",
                     "I'm going with a TUI, built with `ratatui`."),
             ]},
        ],
    },
    "t-compiler": {
        "display": "T-compiler",
        "topics": [
            {"name": "Proposal: improve borrow checker diagnostics",
             "name_zh": "提案：改进借用检查器的诊断信息",
             "messages": [
                 msg(2001, "CompilerGuy", "我想改进借用检查器的错误信息，让新手更容易理解。",
                     "I'd like to improve the borrow checker error messages so beginners can understand them."),
                 msg(2002, "Niko", "这是个好方向。可以看看现有测试是怎么写快照的。",
                     "That's a good direction. Look at how existing snapshot tests are written."),
                 msg(2003, "CompilerGuy", "好的，我来看看。代码示例：\n```rust\nlet mut v = vec![1, 2, 3];\nlet r = &v[0];\nv.push(4);\nprintln!(\"{}\", r);\n```",
                     "Sure, I'll take a look. Code example:\n```rust\nlet mut v = vec![1, 2, 3];\nlet r = &v[0];\nv.push(4);\nprintln!(\"{}\", r);\n```"),
                 msg(2004, "Niko", "这个例子很典型——借用检查器应该提示不可变借用在这里还在使用。",
                     "That's a classic example — the borrow checker should point out the immutable borrow is still in use here."),
             ]},
            {"name": "RFC discussion: async fn in traits",
             "name_zh": "RFC 讨论：trait 中的 async fn",
             "messages": [
                 msg(2005, "AsyncFan", "我们终于要实现 trait 中的 async fn 了吗？参见 https://github.com/rust-lang/rfcs 。",
                     "Are we finally getting async fn in traits? See https://github.com/rust-lang/rfcs ."),
                 msg(2006, "Tyler", "已经合并了，相关实现正在推进中。",
                     "It's merged; the implementation is in progress."),
             ]},
        ],
    },
    "t-libs": {
        "display": "T-libs",
        "topics": [
            {"name": "Stabilization request: OnceLock",
             "name_zh": "稳定性申请：OnceLock",
             "messages": [
                 msg(3001, "LibDev", "我们想申请稳定 `std::sync::OnceLock`。",
                     "We'd like to stabilize `std::sync::OnceLock`."),
                 msg(3002, "Mara", "API 看起来没问题，合并到 FCP 吧。",
                     "API looks fine, let's move to FCP."),
             ]},
        ],
    },
    "t-opsem": {
        "display": "T-opsem",
        "topics": [
            {"name": "Modeling provenance in Stacked Borrows",
             "name_zh": "在 Stacked Borrows 中建模 provenance",
             "messages": [
                 msg(4001, "Ralf", "关于 Stacked Borrows 中的 provenance 建模，我有一个新想法。",
                     "I have a new idea about modeling provenance in Stacked Borrows."),
                 msg(4002, "Ralf", "核心问题是：引用被重新借用后，原始引用还能用来访问吗？",
                     "The core question: after a reference is reborrowed, can the original reference still be used to access?"),
                 msg(4003, "Someone", "我认为 `&mut` 重新借用后原引用就不该再有效，但 `&` 可以。",
                     "I think after a `&mut` reborrow the original shouldn't be valid anymore, but `&` can."),
             ]},
        ],
    },
}

meta = {
    "last_updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "streams": [],
}
for key, s in streams.items():
    for t in s["topics"]:
        t["count"] = len(t["messages"])
        t["first"] = t["messages"][0]["time"]
        t["last"] = t["messages"][-1]["time"]
    with open(os.path.join(OUT, key + ".json"), "w", encoding="utf-8") as f:
        json.dump({"stream": key, "display": s["display"], "topics": s["topics"]}, f, ensure_ascii=False)
    meta["streams"].append({"key": key, "display": s["display"], "file": key + ".json",
                            "topics": len(s["topics"]),
                            "messages": sum(t["count"] for t in s["topics"])})
with open(os.path.join(OUT, "meta.json"), "w", encoding="utf-8") as f:
    json.dump(meta, f, ensure_ascii=False)
print("样例数据已生成:", [x["file"] for x in meta["streams"]])
