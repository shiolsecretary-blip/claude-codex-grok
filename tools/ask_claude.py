#!/usr/bin/env python3
"""给 Claude 投一封信（Codex 用；每封信带信头【项目｜单号】，按项目分开）。

  python3 ~/.claude/tools/ask_claude.py --project 项目名 --ticket 单号 "要跟 Claude 说的话"

- 项目只认 ~/.grok-dispatch/projects.json 里的名字或别名（见 projects.example.json）。没有单号写「无单号」。
- 信头【项目｜单号】自动加在第一行；不带项目或单号不让投。
- 信进 Claude 的收件箱 ~/.grok-dispatch/grok-inbox.jsonl，收信脚本按信头放进那个项目的来信文件；
  接点名的 Claude（终端方案或桌面定时任务）用 gpt_chat.py 在这个项目的聊天里回你。
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project_route as pr  # noqa: E402

INBOX = os.path.expanduser("~/.grok-dispatch/grok-inbox.jsonl")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", default="", help="项目名（见 ~/.grok-dispatch/projects.json）")
    ap.add_argument("--ticket", default="", help="单号；没有写「无单号」")
    ap.add_argument("message", nargs="*")
    a = ap.parse_args()
    body = " ".join(a.message).strip()
    if not body:
        sys.exit("用法：python3 ask_claude.py --project 项目名 --ticket 单号 \"要跟 Claude 说的话\"")
    project, ticket = pr.require(a.project, a.ticket)
    os.makedirs(os.path.dirname(INBOX), exist_ok=True)
    now = datetime.now(timezone.utc)
    rec = {"at": now.isoformat(), "targetId": "gpt", "sourceId": "gpt-" + now.strftime("%Y%m%d%H%M%S%f"),
           "requestId": None, "from": "gpt", "to": "claude", "project": project, "ticket": ticket,
           "body": pr.header(project, ticket) + "\n" + body}
    with open(INBOX, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"已投进 Claude 收件箱（{rec['sourceId']}，{pr.header(project, ticket)}）。白天最多半小时内，Claude 会在这个项目的聊天里回你。")


if __name__ == "__main__":
    main()
