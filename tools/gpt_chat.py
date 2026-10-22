#!/usr/bin/env python3
"""Claude 跟 GPT（Codex 桌面版）直接对话。

走本机 Codex 后台服务（gbot codex send / wait），发进一个专用聊天「Claude 对接」，等 GPT 这一轮答完，把回复打印出来。
  python3 gpt_chat.py "话"            发一句，等回复（默认最多 15 分钟）
  python3 gpt_chat.py "话" --wait 30  最多等 30 分钟
  python3 gpt_chat.py --new "话"      另开一个新聊天（以后都发到新的）
  python3 gpt_chat.py --status        只看 Codex 后台通不通、现在用哪个聊天
GPT 要反过来找 Claude，用 ask_claude.py。
"""
import argparse
import json
import os
import subprocess
import sys

HOME = os.path.expanduser("~")
GBOT = os.path.join(HOME, ".codex/tools/grok-clean-bridge/0.12.4-shared/bin/gbot.mjs")
STATE = os.path.join(HOME, ".grok-dispatch", "gpt-link.json")
CWD = os.path.join(HOME, "Documents", "Codex", "claude-link")
PREFIX = "[Claude Code 直接对话] "


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
        return json.load(open(STATE, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


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
    ap.add_argument("--wait", type=float, default=15, help="最多等几分钟（默认 15）")
    ap.add_argument("--new", action="store_true", help="另开一个新聊天")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()
    s = load()
    if a.status:
        d = gbot("status")
        print("Codex 后台：" + ("通" if d.get("reachable") else "不通"))
        print("当前聊天：" + (s.get("threadId") or "还没开"))
        return
    if not a.message:
        ap.error("要写要说的话")
    msg = PREFIX + a.message
    if a.new or not s.get("threadId"):
        os.makedirs(CWD, exist_ok=True)
        d = gbot("new", "--cwd", CWD, msg)
        if d.get("exitCode") != 0 or not d.get("threadId"):
            sys.exit("开新聊天失败：" + json.dumps(d, ensure_ascii=False)[:400])
        s["threadId"] = d["threadId"]
        save(s)
    else:
        d = gbot("send", s["threadId"], msg)
        if d.get("exitCode") != 0:
            if "busy" in json.dumps(d):
                sys.exit("GPT 这个聊天正在忙上一件事，过几分钟再发。")
            sys.exit("发送失败：" + json.dumps(d, ensure_ascii=False)[:400])
    if not d.get("turnId"):
        print("已送达，GPT 排着队，没拿到这一轮的编号；过会儿再问。")
        return
    wait(s["threadId"], d["turnId"], a.wait)


if __name__ == "__main__":
    main()
