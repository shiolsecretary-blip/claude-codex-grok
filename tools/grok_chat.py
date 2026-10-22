#!/usr/bin/env python3
"""Talk to a Grok Bot bot from the command line, waking the cloud computer when it is asleep.

gbot can send and read, but the Grok Bot cloud computer sleeps a few minutes after it goes idle;
while it sleeps gbot fails with 417 / "agents directory" errors. This wrapper:
  1. probes with gbot; if it works, sends right away;
  2. if asleep, POSTs a short "wake slip" to a Grok Bot routine webhook (optional), waits 60 s,
     restarts the local Grok Bot app so it re-writes its gateway descriptor, and probes again;
  3. sends, then polls the thread until the bot has replied and gone quiet.

Config (all optional except bots), in ~/.grok-dispatch/ (override with GROK_LINK_HOME):
  bots.json     {"default": "<bot-id>", "lead": "<bot-id>", ...}   short names -> bot ids
  webhook.json  {"url": "https://.../webhook/<routine-id>", "key": "crsr_... or whsec_..."}  chmod 600
Usage:
  python3 grok_chat.py lead "hello"            send and wait for the reply (default 5 min)
  python3 grok_chat.py lead --read 6           show the last 6 messages
  python3 grok_chat.py --status | --wake       probe only / wake only
  python3 grok_chat.py --inbox 10              show the local inbox written by the patched relay
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
import secrets
import ssl
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

HOME = os.environ.get("GROK_LINK_HOME", os.path.expanduser("~/.grok-dispatch"))
GBOT = os.environ.get("GBOT", os.path.expanduser("~/.codex/tools/grok-clean-bridge/0.12.4-shared/bin/gbot.mjs"))
BOTS_FILE = os.path.join(HOME, "bots.json")
WEBHOOK = os.path.join(HOME, "webhook.json")
STATE = os.path.join(HOME, "chat-wake.json")
INBOX = os.path.join(HOME, "grok-inbox.jsonl")
DESC = os.path.expanduser("~/Library/Application Support/Grok Bot/gateway-descriptor.json")
APP = "Grok Bot"
PREFIX = os.environ.get("GROK_CHAT_PREFIX", "[Claude Code] ")
ALLOWED_HOSTS = ("cursor.sh", "cursor.com", "x.ai")
ASLEEP = ("417", "Expectation Failed", "agents directory", "gateway auth", "session: not found",
          "ECONNREFUSED", "503", "Service Unavailable", "aborted due to timeout", "deadline_exceeded")


def die(msg):
    print("error: " + msg, file=sys.stderr)
    sys.exit(2)


def say(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def bots():
    try:
        b = json.load(open(BOTS_FILE, encoding="utf-8"))
    except (OSError, ValueError):
        die(f"create {BOTS_FILE} first, e.g. {{\"default\": \"<bot-id>\"}} (ids: gbot bots list --json)")
    if "default" not in b:
        die(f"{BOTS_FILE} needs a \"default\" entry")
    return b


def gbot(*args, timeout=60):
    cmd = ["node", GBOT, *args, "--json"]
    if args and args[0] in ("send", "thread"):
        cmd.append("--no-history")
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, None, "gbot timeout"
    out = (p.stdout or "") + (p.stderr or "")
    try:
        data = json.loads(p.stdout)
    except (ValueError, TypeError):
        data = None
    ok = p.returncode == 0 and not (isinstance(data, dict) and data.get("error"))
    return ok, data, out


def resolve(name):
    b = bots()
    if name in b.values() or len(name) == 36:
        return name
    if name.lower() in {k.lower(): v for k, v in b.items()}:
        return {k.lower(): v for k, v in b.items()}[name.lower()]
    die(f"unknown bot '{name}'. Known: {', '.join(b)} (or a full id)")


def probe():
    ok, data, out = gbot("thread", bots()["default"], "--limit", "1")
    if ok:
        return True
    if any(s in out for s in ASLEEP):
        return False
    die("gbot failed (not a sleep error): " + out.strip()[:400])


def ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def webhook_conf():
    if not os.path.exists(WEBHOOK):
        return None
    if stat.S_IMODE(os.stat(WEBHOOK).st_mode) & 0o077:
        die(f"{WEBHOOK} is readable by others; chmod 600 it")
    c = json.load(open(WEBHOOK, encoding="utf-8"))
    url, key = str(c.get("url", "")).strip(), str(c.get("key", "")).strip()
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if not url.startswith("https://") or not any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS):
        die("webhook url must be https on " + ", ".join(ALLOWED_HOSTS))
    if not key.startswith(("crsr_", "whsec_")):
        die("webhook key should start with crsr_ or whsec_")
    return url, key


def headers_for(key, body):
    h = {"Content-Type": "application/json", "User-Agent": "grok-chat/1"}
    if key.startswith("crsr_"):
        h["Authorization"] = "Bearer " + key
    else:
        msg_id, ts = "msg_" + secrets.token_hex(12), str(int(time.time()))
        raw = base64.b64decode(key[len("whsec_"):])
        sig = hmac.new(raw, f"{msg_id}.{ts}.".encode() + body, hashlib.sha256).digest()
        h.update({"webhook-id": msg_id, "webhook-timestamp": ts, "webhook-signature": "v1," + base64.b64encode(sig).decode()})
    return h


def send_wake_slip():
    conf = webhook_conf()
    if not conf:
        say("no webhook.json; skipping the wake slip, only restarting the app")
        return False
    task_id = "wake-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    body = json.dumps({"from": "grok_chat", "task_id": task_id,
                       "task": "Wake-up only: stay active for about 10 minutes and answer any direct chat "
                               "messages that arrive meanwhile. No other work needed."}).encode()
    url, key = conf
    req = urllib.request.Request(url, data=body, method="POST", headers=headers_for(key, body))
    try:
        with urllib.request.urlopen(req, timeout=30, context=ssl_context()) as r:
            status = r.status
    except urllib.error.HTTPError as e:
        status = e.code
    except urllib.error.URLError as e:
        die(f"wake slip failed: {e.reason}")
    if status != 200:
        die(f"wake slip returned {status}")
    os.makedirs(HOME, exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump({"last_wake": time.time(), "task_id": task_id}, f)
    os.chmod(STATE, 0o600)
    say(f"wake slip sent ({task_id}); waiting for the cloud computer")
    return True


def restart_app():
    subprocess.run(["osascript", "-e", f'tell application "{APP}" to quit'], capture_output=True)
    for _ in range(10):
        if subprocess.run(["pgrep", "-x", APP], capture_output=True).returncode != 0:
            break
        time.sleep(1)
    else:
        subprocess.run(["pkill", "-x", APP], capture_output=True)
        time.sleep(2)
    subprocess.run(["open", "-g", "-a", APP], capture_output=True)


def wake():
    try:
        last = json.load(open(STATE, encoding="utf-8")).get("last_wake", 0)
    except (OSError, ValueError):
        last = 0
    if time.time() - last > 300 and send_wake_slip():
        time.sleep(60)
    for attempt in (1, 2):
        say(f"restarting {APP} (attempt {attempt})")
        restart_app()
        deadline = time.time() + 75
        while time.time() < deadline:
            time.sleep(5)
            if os.path.exists(DESC) and probe():
                say("connected")
                return
        time.sleep(30)
    die("still not connected after two wake attempts")


def ensure_awake():
    if not probe():
        say("Grok Bot is asleep; waking it (1-2 minutes)")
        wake()


def entries(data):
    rows = []
    for e in ((data or {}).get("transcript") or {}).get("entries") or []:
        at = datetime.fromtimestamp(e.get("timestampMs", 0) / 1000).strftime("%m-%d %H:%M:%S")
        if e.get("kind") == "send-message":
            rows.append((e.get("seq", 0), "bot", at, (e.get("message") or {}).get("content") or ""))
        elif e.get("kind") == "message" and e.get("role") == "user" and e.get("content"):
            rows.append((e.get("seq", 0), "agent" if e.get("fromAgent") else "you", at, e["content"]))
    return rows


def show(rows):
    for seq, who, at, text in rows:
        print(f"\n— {who} {at} (seq {seq})\n{text}")


def last_seq(bot):
    ok, data, _ = gbot("thread", bot, "--limit", "1")
    es = ((data or {}).get("transcript") or {}).get("entries") or [] if ok else []
    return max([e.get("seq", 0) for e in es] or [0])


def follow(bot, before, wait_min, quiet):
    deadline, got, quiet_since = time.time() + wait_min * 60, [], None
    while time.time() < deadline:
        time.sleep(5)
        ok, data, out = gbot("thread", bot, "--limit", "30")
        if not ok:
            if any(s in out for s in ASLEEP):
                wake()
            continue
        new = [r for r in entries(data) if r[0] > before and r[1] == "bot"]
        if len(new) > len(got):
            got, quiet_since = new, time.time()
        elif got and time.time() - quiet_since >= quiet:
            break
    show(got) if got else say(f"no reply within {wait_min:g} min; check later with --read instead of resending")


def chat(bot, msg, wait_min, quiet):
    ensure_awake()
    before = last_seq(bot)
    ok, _, out = gbot("send", bot, PREFIX + msg, timeout=90)
    if not ok and any(s in out for s in ASLEEP):
        wake()
        before = last_seq(bot)
        ok, _, out = gbot("send", bot, PREFIX + msg, timeout=90)
    if not ok:
        die("send failed: " + out.strip()[:400])
    say("sent; waiting for the reply")
    follow(bot, before, wait_min, quiet)


def show_inbox(n):
    if not os.path.exists(INBOX):
        print("inbox is empty")
        return
    seen, rows = set(), []
    for line in open(INBOX, encoding="utf-8"):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("sourceId") not in seen:
            seen.add(r.get("sourceId"))
            rows.append(r)
    for r in rows[-n:]:
        print(f"--- {r.get('at', '')[:16]} UTC · {r.get('sourceId')} · to={r.get('to')}\n{(r.get('body') or '').strip()}")


def main():
    ap = argparse.ArgumentParser(description="Talk to a Grok Bot bot (auto-wake)")
    ap.add_argument("bot", nargs="?")
    ap.add_argument("message", nargs="?")
    ap.add_argument("--wait", type=float, default=5, help="minutes to wait for a reply")
    ap.add_argument("--quiet", type=float, default=60, help="seconds of silence that end the reply")
    ap.add_argument("--read", type=int, default=0)
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--wake", action="store_true")
    ap.add_argument("--inbox", type=int, default=0)
    a = ap.parse_args()
    if a.inbox:
        return show_inbox(a.inbox)
    if a.status:
        return print("awake" if probe() else "asleep")
    if a.wake:
        return ensure_awake()
    if not a.bot:
        ap.error("bot name required")
    bot = resolve(a.bot)
    if a.read:
        ensure_awake()
        ok, data, out = gbot("thread", bot, "--limit", str(a.read), "--full")
        return show(entries(data)) if ok else die(out.strip()[:400])
    if not a.message:
        ap.error("message required (or --read N)")
    chat(bot, a.message, a.wait, a.quiet)


if __name__ == "__main__":
    main()
