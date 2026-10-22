#!/usr/bin/env python3
"""Collect "@Claude" mentions (from Grok Bot via the patched relay, or from Codex via ask_claude.py),
filed by project.

Run it first in a scheduled Claude task (e.g. every 30 minutes):
  1. restarts the relay worker if it is not running (from ~/.grok-dispatch/relay-env.json);
  2. reads new lines of ~/.grok-dispatch/grok-inbox.jsonl and keeps those with to == "claude";
  3. reads the header 【project｜ticket】 in the first lines and appends the letter to that project's letters file
     (projects.json, see project_route.py) marked 【待接】; letters without a header, or with an unknown project,
     go to the default letters file (CLAUDE_LETTERS, default ~/.grok-dispatch/letters.md) marked 【待接·待分流】;
  4. prints them with project, ticket, letters file and handoff file, or "没有新的点名" when there is nothing new.
  grok_inbox_watch.py --pending                               lists letters not yet handled, in every letters file.
  grok_inbox_watch.py --done <sourceId> "<what was done>"   marks a letter 【已接】 (searched in every letters file).
The first run reads the whole inbox; letters already in a letters file are skipped, so re-runs never duplicate.
The read position is saved only after the letters files are written, so a failed write is retried next time.
Every change to a letters file takes a short lock (letters.lock, separate from the long collector lock) and is
written to a temp file then swapped in, so concurrent claim / hand-back / --done never overwrite each other.
With --run-claude, new letters are claimed as 【接手中 · 终端】 before `claude -p` starts and handed back as 【待接】 if it fails.
"""
import fcntl
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime

HOME = os.path.expanduser("~")
D = os.path.join(HOME, ".grok-dispatch")
INBOX = os.path.join(D, "grok-inbox.jsonl")
STATE = os.path.join(D, "inbox-watch.json")
LOG = os.path.join(D, "inbox-watch.log")
RELAY_ENV = os.path.join(D, "relay-env.json")
LETTERS = os.environ.get("CLAUDE_LETTERS", os.path.join(D, "letters.md"))
DAILY_CAP = 30
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import project_route as pr  # noqa: E402


def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(datetime.now().strftime("%m-%d %H:%M:%S ") + msg + "\n")


def ensure_relay():
    try:
        env = json.load(open(RELAY_ENV, encoding="utf-8"))
    except (OSError, ValueError):
        return
    relay = env["relay"]
    if subprocess.run(["pgrep", "-f", relay], capture_output=True).returncode == 0:
        return
    if not os.path.exists(relay):
        log("转发器脚本不在：" + relay)
        return
    e = dict(os.environ, PATH=env["PATH"], GROK_BOT_RELAY_DIR=env["GROK_BOT_RELAY_DIR"])
    subprocess.Popen(["/usr/local/bin/node", relay], cwd=os.path.dirname(relay), env=e,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
    log("转发器没在跑，已拉起")


def load_state():
    try:
        return json.load(open(STATE, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(s):
    json.dump(s, open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


@contextmanager
def letters_lock():
    """改来信文件专用的短锁：记新信、认领、退回、标已接都先拿它，改完立刻放。
    和收信用的长锁（inbox-watch.lock，等 Claude 回信期间一直占着）分开。"""
    os.makedirs(D, exist_ok=True)
    with open(os.path.join(D, "letters.lock"), "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        yield


def read_letters(path=LETTERS):
    try:
        return open(path, encoding="utf-8").read()
    except FileNotFoundError:
        return ""


def letter_files():
    return [LETTERS] + [f for f in pr.all_letters() if f != LETTERS]


def route(m):
    """这封信该进哪个来信文件：(文件, 项目正名或 None, 单号或 None)。"""
    project, ticket, _ = pr.parse(m.get("body") or "")
    if not project and m.get("project"):
        project, ticket = pr.resolve(m["project"]), m.get("ticket")
    return (pr.letters(project) if project else LETTERS), project, ticket


def write_letters(text, path=LETTERS):
    """先写临时文件再整体替换：写到一半出错，原文件不受影响。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def record(msgs, note="【待接】"):
    kept = []
    with letters_lock():
        groups = {}
        for m in msgs:
            path, project, ticket = route(m)
            m["_letters"], m["_project"], m["_ticket"] = path, project, ticket
            groups.setdefault(path, []).append(m)
        for path, ms in groups.items():
            have = read_letters(path)
            ms = [m for m in ms if f"· {m.get('sourceId')}\n" not in have]
            if not ms:
                continue
            title = "Letters（没写信头的待分流信也在这里）" if path == LETTERS else "来信：" + (ms[0]["_project"] or "")
            text = have or f"# {title}\n\n收信脚本按信头【项目｜单号】自动存在这里（新的在下面）。接了用 grok_inbox_watch.py --done 编号 标已接。\n"
            for m in ms:
                who = "来自 GPT · " if m.get("from") == "gpt" else "来自 Grok · "
                tag = note if m["_project"] else note.replace("】", "·待分流】", 1)
                head = f"【{m['_project']}｜{m['_ticket']}】 " if m["_project"] else "【没写信头】 "
                text += f"\n## {tag} {head}{who}{datetime.now().strftime('%Y-%m-%d %H:%M')} · {m.get('sourceId')}\n\n{(m.get('body') or '').strip()}\n"
            write_letters(text, path)
            kept += ms
    return kept


TOOLS = os.path.dirname(os.path.abspath(__file__))
PROMPT_FILE = os.environ.get("CLAUDE_TASK_PROMPT", os.path.join(D, "claude-task-prompt.md"))
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
CLAUDE_CWD = os.environ.get("CLAUDE_WORKDIR", HOME)


def run_claude(msgs):
    """方案一：起一个终端版 Claude（claude -p）去接。起不来就把来信留着【待接】，交给定时任务（方案二）。"""
    try:
        prompt = open(PROMPT_FILE, encoding="utf-8").read()
    except OSError:
        log("没有提示词文件 " + PROMPT_FILE + "，留给定时任务")
        return
    tools = ",".join(["Read", "Grep", "Glob"] + [f"Bash(python3 {os.path.join(TOOLS, n)}:*)"
                                                  for n in ("grok_chat.py", "gpt_chat.py", "grok_inbox_watch.py")])
    ids = ",".join(str(m.get("sourceId")) for m in msgs)
    # 先认领：标成【接手中 · 终端】，定时任务（方案二）只接【待接】，不会重复回
    set_status([m.get("sourceId") for m in msgs], "【待接】", "【接手中 · 终端】")
    prompt += ("\n\n本轮由收信脚本（终端方案）启动。你负责的来信编号：" + ids +
               "（来信文件里标【接手中 · 终端】）。只处理这几条；收信脚本说「上一轮还在跑」是正常的，那是启动你的这一轮。")
    try:
        r = subprocess.run([CLAUDE_BIN, "-p", prompt, "--allowedTools", tools, "--no-session-persistence"],
                           cwd=CLAUDE_CWD, capture_output=True, text=True, timeout=3900)
        out = (r.stdout or r.stderr or "").strip()
        ok = r.returncode == 0 and not any(k in out for k in ("Not logged in", "Unable to connect", "ERR_BAD_REQUEST"))
    except FileNotFoundError:
        out, ok = "找不到 claude 命令", False
    except subprocess.TimeoutExpired:
        out, ok = "终端 Claude 超过 65 分钟没跑完，停了", False
    if ok:
        log("终端 Claude 接了 " + ids + " → " + out[-400:].replace("\n", " "))
        notify("已接点名：" + out[-80:])
    else:
        set_status([m.get("sourceId") for m in msgs], "【接手中 · 终端】", "【待接】")  # 退回，交给定时任务
        log("终端 Claude 没起来（" + out[-200:].replace("\n", " ") + "），" + ids + " 退回【待接】给定时任务")


def set_status(ids, frm, to):
    """把来信里这几条的标题状态从 frm 换成 to（终端方案认领 / 退回用）。"""
    import re
    with letters_lock():
        for path in letter_files():
            text = read_letters(path)
            if not text:
                continue
            new = text
            for i in ids:
                new = re.sub(r"^## " + re.escape(frm) + r"(.*· " + re.escape(str(i)) + r")\s*$", "## " + to + r"\1", new, count=1, flags=re.M)
            if new != text:
                write_letters(new, path)


def notify(text):
    subprocess.run(["osascript", "-e", f'display notification {json.dumps(text)} with title "Claude 收信"'],
                   capture_output=True)


def main(run=False):
    os.makedirs(D, exist_ok=True)
    lock = open(os.path.join(D, "inbox-watch.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("没有新的点名（上一轮还在跑）")
        return
    ensure_relay()
    s = load_state()
    size = os.path.getsize(INBOX) if os.path.exists(INBOX) else 0
    if "offset" not in s or s["offset"] > size:
        s["offset"] = 0  # 第一次跑或收件箱被清过：从头读，已经记进来信的会跳过
    if size == s["offset"]:
        print("没有新的点名")
        return
    with open(INBOX, "rb") as f:
        f.seek(s["offset"])
        chunk = f.read()
    end = chunk.rfind(b"\n") + 1  # 只处理写完整的行
    s["offset"] += end
    seen = s.get("seen", [])
    msgs = []
    for line in chunk[:end].decode("utf-8", "replace").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("to") == "claude" and r.get("sourceId") not in seen:
            seen.append(r.get("sourceId"))
            msgs.append(r)
    s["seen"] = seen[-200:]
    today = datetime.now().strftime("%Y-%m-%d")
    if s.get("day") != today:
        s["day"], s["runs"] = today, 0
    if not msgs:
        save_state(s)
        print("没有新的点名")
        return
    s["runs"] = s.get("runs", 0) + len(msgs)
    over = s["runs"] > DAILY_CAP
    msgs = record(msgs, "【待接·超当天上限，只记不回】" if over else "【待接】")  # 先写来信；写失败就抛错，读到哪不前移，下次重读
    save_state(s)
    if not msgs:
        print("没有新的点名（这几封之前已记过）")
        return
    log("收到点名 " + ",".join(str(m.get("sourceId")) for m in msgs) + ("（超上限）" if over else ""))
    if over:
        print(f"今天点名已超 {DAILY_CAP} 条，这几条只记进来信文件，不回，等人看。")
        return
    for m in msgs:
        who = "来自 GPT，用 gpt_chat.py 回" if m.get("from") == "gpt" else "来自 Grok，用 grok_chat.py 回"
        if m["_project"]:
            where = f"项目【{m['_project']}｜{m['_ticket']}】｜回信带 --project \"{m['_project']}\" --ticket \"{m['_ticket']}\"｜先读 {pr.handoff(m['_project'])} 最上面一节｜来信在 {m['_letters']}"
        else:
            where = f"没写信头（待分流）｜来信在 {m['_letters']}｜先看内容判断是哪个项目，回信时请对方以后第一行写【项目｜单号】"
        print(f"--- {m.get('sourceId')}（{who}）\n{where}\n{(m.get('body') or '').strip()}\n")
    if run:
        run_claude(msgs)  # 还拿着锁：两分钟后的下一次检查不会重复起


def mark_done(source_id, how):
    """把来信里这条的【待接…】标成【已接 · how】（在所有来信文件里找）。用法：grok_inbox_watch.py --done t146s470 "回了她…" """
    import re
    pat = re.compile(r"^## 【(?:待接|接手中)[^】]*】(.*· " + re.escape(source_id) + r")\s*$", re.M)
    n = 0
    with letters_lock():
        for path in letter_files():
            new, n = pat.subn(lambda m: "## 【已接 · " + how.strip().replace("\n", " ") + "】" + m.group(1), read_letters(path), count=1)
            if n:
                write_letters(new, path)
                break
    if not n:
        print("没找到标【待接】或【接手中】的 " + source_id)
        return
    log("标已接 " + source_id + "：" + how.strip()[:200])
    print("已标【已接】：" + source_id)


def pending():
    """列出所有来信文件里还没接的（【待接…】【接手中…】）。"""
    import re
    total = 0
    for path in letter_files():
        heads = [l for l in read_letters(path).splitlines() if re.match(r"^## 【(?:待接|接手中)", l)]
        if heads:
            print(f"== {path}（{len(heads)} 条）")
            for h in heads:
                print("  " + h[3:])
            total += len(heads)
    if not total:
        print("所有来信文件里都没有待接的")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--pending":
        pending()
        sys.exit(0)
    if len(sys.argv) >= 4 and sys.argv[1] == "--done":
        mark_done(sys.argv[2], " ".join(sys.argv[3:]))
        sys.exit(0)
    try:
        main(run="--run-claude" in sys.argv[1:])
    except Exception as e:  # 开机项里出错只记日志
        log("出错：" + repr(e))
        sys.exit(0)
