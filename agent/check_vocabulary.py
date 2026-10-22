# -*- coding: utf-8 -*-
"""把每个人的词表与前端立绘清单对拍，确保后端不可能发出前端没有素材的状态。"""

import re
import sys
from pathlib import Path

# Windows 下 stdout 被重定向时默认走 GBK，会对 ✓/✗ 直接抛 UnicodeEncodeError
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from agent.persona import list_personas

TS = Path("frontend/src/data/characterStates.ts").read_text(encoding="utf-8")
lines = TS.split("\n")

STATE = re.compile(r"\['([^']+)',\s*'([^']+\.png)',\s*\[((?:[^\]']|'[^']*')*)\],\s*\[((?:[^\]']|'[^']*')*)\]")

owner_spans = []
for index, line in enumerate(lines):
    match = re.match(r"\s*makeCharacter\('([^']+)',\s*'([^']+)'", line)
    if match:
        owner_spans.append((match.group(2), index))
owner_spans.append(("<END>", len(lines)))

front: dict[str, dict[str, set]] = {}
for pos, (name, start) in enumerate(owner_spans[:-1]):
    end = owner_spans[pos + 1][1]
    emotions: set[str] = set()
    actions: set[str] = set()
    count = 0
    for line in lines[start:end]:
        match = STATE.search(line)
        if not match:
            continue
        count += 1
        emotions.update(item.strip().strip("'") for item in match.group(3).split(",") if item.strip())
        actions.update(item.strip().strip("'") for item in match.group(4).split(",") if item.strip())
    front[name] = {"emotions": emotions, "actions": actions, "states": count}

print("前端人物数:", len(front), " 立绘合计:", sum(v["states"] for v in front.values()))
print()

problems = 0
for persona in list_personas():
    data = front.get(persona.name)
    if data is None:
        print("✗ %s：前端没有这个人物" % persona.name)
        problems += 1
        continue
    back_em = set(persona.supported_emotions)
    back_ac = set(persona.supported_actions)
    extra_em = back_em - data["emotions"]
    extra_ac = back_ac - data["actions"]
    miss_em = data["emotions"] - back_em
    miss_ac = data["actions"] - back_ac
    status = "✓" if not (extra_em or extra_ac or miss_em or miss_ac) else "✗"
    if status == "✗":
        problems += 1
    print("%s %-6s 立绘%2d  后端情绪%2d/%2d  后端动作%2d/%2d" % (
        status, persona.name, data["states"], len(back_em), len(data["emotions"]),
        len(back_ac), len(data["actions"])))
    if extra_em:
        print("     后端多出情绪（前端无此素材，需删）:", "、".join(sorted(extra_em)))
    if extra_ac:
        print("     后端多出动作（前端无此素材，需删）:", "、".join(sorted(extra_ac)))
    if miss_em:
        print("     后端遗漏情绪（可用却没用上）:", "、".join(sorted(miss_em)))
    if miss_ac:
        print("     后端遗漏动作（可用却没用上）:", "、".join(sorted(miss_ac)))

print()
print("不一致项:", problems)
print("VOCAB_CHECK_OK" if problems == 0 else "VOCAB_CHECK_FAILED")
