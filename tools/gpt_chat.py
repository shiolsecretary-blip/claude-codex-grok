#!/usr/bin/env python3
"""Claude 跟 GPT（Codex 桌面版）直接对话，每个项目一个聊天。

走本机 Codex 后台服务（gbot codex send / wait），每个项目一个专用聊天，等 GPT 这一轮答完，把回复打印出来。
  python3 gpt_chat.py --project 项目名 --ticket 单号 "话"            发一句，等回复（默认最多 15 分钟）
  python3 gpt_chat.py --project 项目名 --ticket 单号 "话" --wait 30  最多等 30 分钟
  python3 gpt_chat.py --project 项目名 --ticket 单号 --new "话"      这个项目另开一个新聊天
  python3 gpt_chat.py --status                                        看 Codex 后台通不通、各项目用哪个聊天
项目只认 ~/.grok-dispatch/projects.json 里的名字；没有单号写「无单号」。每条话第一行自动带信头【项目｜单号】。
项目第一次用时自动开新聊天。旧版只记了一个聊天（gpt-link.json 的 threadId），升级后它归 LEGACY_PROJECT（环境变量，默认「AI for AI」）。
GPT 要反过来找 Claude，用 ask_claude.py（也要带 --project --ticket）。
"""
import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project_route as pr  # noqa: E402

HOME = os.path.expanduser("~")
GBOT = os.path.join(HOME, ".codex/tools/grok-clean-bridge/0.12.4-shared/bin/gbot.mjs")
STATE = os.path.join(HOME, ".grok-dispatch", "gpt-link.json")
CWD = os.path.join(HOME, "Documents", "Codex", "claude-link")
PREFIX = "[Claude Code 直接对话] "
LEGACY_PROJECT = os.environ.get("GPT_LEGACY_PROJECT", "AI for AI")


def gbot(*args, timeout=120):
    try:
        r = subprocess.run(["node", GBOT, "codex", *args, "--json"], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        sys.exit("Codex 后台没在规定时间内回应")
    try:
        return json.loads(r.stdout)
    except ValueError:
        sys.exit("gbot 出错：" + (r.stderr or r.stdout).strip()[:400])


def load():
    try:
        s = json.load(open(STATE, encoding="utf-8"))
    except (OSError, ValueError):
        s = {}
    s.setdefault("threads", {})
    if s.get("threadId") and LEGACY_PROJECT not in s["threads"]:
        s["threads"][LEGACY_PROJECT] = s["threadId"]  # 旧的共用聊天归 LEGACY_PROJECT
    return s


def save(s):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump(s, open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def wait(thread, turn, minutes):
    d = gbot("wait", thread, turn, "--timeout-ms", str(int(minutes * 60000)), timeout=minutes * 60 + 60)
    state = (d.get("execution") or {}).get("state")
    text = ((d.get("reply") or {}).get("text") or "").strip()
    if state != "completed":
        print(f"（GPT 还没答完：{state}。过会儿用 --status 看，或再发一句问进度）")
    print(text or "（没有文字回复）")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("message", nargs="?")
    ap.add_argument("--project", default="", help="项目名（见 ~/.grok-dispatch/projects.json）")
    ap.add_argument("--ticket", default="", help="单号；没有写「无单号」")
    ap.add_argument("--wait", type=float, default=15, help="最多等几分钟（默认 15）")
    ap.add_argument("--new", action="store_true", help="这个项目另开一个新聊天")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()
    s = load()
    if a.status:
        d = gbot("status")
        print("Codex 后台：" + ("通" if d.get("reachable") else "不通"))
        for p, t in s["threads"].items():
            print(f"  {p}：{t}")
        if not s["threads"]:
            print("  还没开过聊天")
        return
    if not a.message:
        ap.error("要写要说的话")
    project, ticket = pr.require(a.project, a.ticket)
    msg = PREFIX + pr.header(project, ticket) + "\n" + a.message
    thread = s["threads"].get(project)
    if a.new or not thread:
        cwd = os.path.join(CWD, project.replace("/", "_"))
        os.makedirs(cwd, exist_ok=True)
        d = gbot("new", "--cwd", cwd, msg)
        if d.get("exitCode") != 0 or not d.get("threadId"):
            sys.exit("开新聊天失败：" + json.dumps(d, ensure_ascii=False)[:400])
        thread = s["threads"][project] = d["threadId"]
        save(s)
        print(f"（{project} 开了新聊天 {thread}）")
    else:
        d = gbot("send", thread, msg)
        if d.get("exitCode") != 0:
            if "busy" in json.dumps(d):
                sys.exit("GPT 这个项目的聊天正在忙上一件事，过几分钟再发。")
            sys.exit("发送失败：" + json.dumps(d, ensure_ascii=False)[:400])
    if not d.get("turnId"):
        print("已送达，GPT 排着队，没拿到这一轮的编号；过会儿再问。")
        return
    wait(thread, d["turnId"], a.wait)


if __name__ == "__main__":
    main()
