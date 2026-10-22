#!/usr/bin/env python3
"""Keep each project's messages apart (header 【project｜ticket】).

Different projects must not share one conversation. Rules:
  - Every message to another agent, and every task slip, starts with the header 【project｜ticket】.
    The project must be a name (or alias) in projects.json; with no ticket, write 「无单号」.
  - The send tools (ask_claude.py, gpt_chat.py, grok_chat.py) refuse to send without --project and --ticket.
  - Codex gets one chat per project (gpt-link.json "threads").
  - The collector files each letter into that project's letters file; letters without a header go to the
    default letters file marked 【待接·待分流】.

projects.json lives in ~/.grok-dispatch/ (override with GROK_LINK_HOME); see projects.example.json.
"""
import json
import os
import re
import sys

LINK_HOME = os.environ.get("GROK_LINK_HOME", os.path.expanduser("~/.grok-dispatch"))
REG = os.path.join(LINK_HOME, "projects.json")
HEADER_RE = re.compile(r"【\s*([^｜|】]+?)\s*[｜|]\s*([^】]+?)\s*】")


def registry():
    try:
        return json.load(open(REG, encoding="utf-8"))["projects"]
    except (OSError, ValueError, KeyError):
        sys.exit("cannot read project list " + REG + " (copy tools/projects.example.json there)")


def resolve(name):
    """Name or alias -> canonical name; None if unknown."""
    n = (name or "").strip()
    reg = registry()
    if n in reg:
        return n
    for k, v in reg.items():
        if n in v.get("aliases", []):
            return k
    return None


def names():
    return "、".join(registry().keys())


def require(project, ticket):
    """For send tools: both are required and the project must be known. Returns (canonical, ticket)."""
    if not project or not ticket:
        sys.exit("发信要带信头：--project 项目名 --ticket 单号（没有单号写「无单号」）。项目名单：" + names())
    p = resolve(project)
    if not p:
        sys.exit(f"不认识项目「{project}」。项目名单：{names()}（新项目先加进 {REG}）")
    t = " ".join(ticket.split())
    if "】" in t or "｜" in t:
        sys.exit("单号里不能有「】」或「｜」")
    return p, t


def header(project, ticket):
    return f"【{project}｜{ticket}】"


def parse(text):
    """Find the header in the first three lines. Returns (canonical or None, ticket or None, as written or None)."""
    head = "\n".join((text or "").strip().splitlines()[:3])
    m = HEADER_RE.search(head)
    if not m:
        return None, None, None
    raw = m.group(1).strip()
    return resolve(raw), m.group(2).strip(), raw


def letters(project):
    v = registry()[project]
    return os.path.expanduser(v.get("letters") or os.path.join(LINK_HOME, "letters", project.replace("/", "_") + ".md"))


def handoff(project):
    return os.path.expanduser(registry()[project].get("handoff", ""))


def all_letters():
    return sorted({letters(k) for k in registry()})
