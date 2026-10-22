#!/usr/bin/env python3
"""给 Claude 投一封信（GPT 用）。

  python3 ~/.claude/tools/ask_claude.py "要跟 Claude 说的话"

信进 Claude 的收件箱 ~/.grok-dispatch/grok-inbox.jsonl（和 Grok 的「@Claude」同一个）。
桌面应用里接点名的定时任务白天每整点、半点看一次，有信就接，
用 gpt_chat.py 发到「Claude 对接」那个聊天回你；接上以后可以来回聊。
"""
import json
import os
import sys
from datetime import datetime, timezone

INBOX = os.path.expanduser("~/.grok-dispatch/grok-inbox.jsonl")


def main():
    body = " ".join(sys.argv[1:]).strip()
    if not body:
        sys.exit("用法：python3 ask_claude.py \"要跟 Claude 说的话\"")
    os.makedirs(os.path.dirname(INBOX), exist_ok=True)
    now = datetime.now(timezone.utc)
    rec = {"at": now.isoformat(), "targetId": "gpt", "sourceId": "gpt-" + now.strftime("%Y%m%d%H%M%S%f"),
           "requestId": None, "from": "gpt", "to": "claude", "body": body}
    with open(INBOX, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("已投进 Claude 收件箱（" + rec["sourceId"] + "）。白天最多半小时内，Claude 会在「Claude 对接」聊天里回你。")


if __name__ == "__main__":
    main()
