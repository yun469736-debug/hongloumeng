# -*- coding: utf-8 -*-
"""十四间房的在场名册与播种抽取。

名册属于游戏逻辑，不放在前端：前端只管匾额、背景与热区，
"此刻这间房里都有谁"由 GET /api/room 按 用户＋日＋时段＋场景 播种决定。

规则：
- 常驻者权重 6、访客权重 2；名册外的人永不出场。
- 全局修正：贾元春 ×0.3（身在宫中）、秦可卿 ×0.3（第 13 回即亡）。
- 林黛玉单独一条：按房间给定概率先掷一次，中了即占一席，不参与权重抽签。
  潇湘馆是她的家，必在；其余按 0.80 / 0.50 分档，十四间平均正好 60.0%，
  对应"不保证在场、但显著加权"。
- 每次进门抽 1～3 人（不超过候选池），按权重无放回。

名册外的府中人物（贾母、平儿、贾政、紫鹃、袭人、晴雯、莺儿、龄官等）
一律"默认外出"：可以被人提起、可以加引号转述，但不出场、不开口。
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass

RESIDENT_WEIGHT = 6.0
GUEST_WEIGHT = 2.0

DAIYU = "林黛玉"

# 全局出场权重修正
GLOBAL_WEIGHT: dict[str, float] = {
    "贾元春": 0.3,
    "秦可卿": 0.3,
}


@dataclass(frozen=True)
class Room:
    """一间房的在场名册。黛玉不在 residents/guests 里出现，由 daiyu 概率单独决定。"""

    name: str
    residents: tuple[str, ...] = ()
    guests: tuple[str, ...] = ()
    mention_only: tuple[str, ...] = ()
    # 一次最多几人同席。房间里站着的人不影响速度——只有被抽中开口的才真的调用模型。
    capacity: int = 5
    daiyu: float = 0.50


ROOMS: dict[str, Room] = {
    "潇湘馆": Room(
        name="潇湘馆", residents=("林黛玉",),
        guests=("贾宝玉", "薛宝钗", "史湘云"),
        # 她自己家：必在。其余房间按概率，十四间平均正好 60%。
        mention_only=("紫鹃", "雪雁"), daiyu=1.0,
    ),
    "怡红院": Room(
        name="怡红院", residents=("贾宝玉",),
        guests=("薛宝钗", "史湘云"),
        mention_only=("袭人", "晴雯", "秋纹"), daiyu=0.80,
    ),
    "稻香村": Room(
        name="稻香村", residents=("李纨",),
        guests=("贾探春", "薛宝钗", "贾惜春"),
        mention_only=("贾兰",), daiyu=0.50,
    ),
    "沁芳亭": Room(
        name="沁芳亭",
        guests=("贾宝玉", "薛宝钗", "史湘云"), daiyu=0.80,
    ),
    "蘅芜苑": Room(
        name="蘅芜苑", residents=("薛宝钗",),
        guests=("史湘云", "贾探春"),
        mention_only=("莺儿", "香菱"), daiyu=0.50,
    ),
    "沁芳桥": Room(
        name="沁芳桥",
        guests=("贾宝玉", "薛宝钗"), daiyu=0.80,
    ),
    "秋爽斋": Room(
        name="秋爽斋", residents=("贾探春",),
        guests=("史湘云", "李纨", "薛宝钗", "贾惜春"),
        mention_only=("侍书",), daiyu=0.50,
    ),
    "缀锦楼": Room(
        name="缀锦楼", residents=("贾迎春",),
        guests=("贾探春", "贾惜春"),
        mention_only=("司棋",), daiyu=0.50,
    ),
    "栊翠庵": Room(
        name="栊翠庵", residents=("妙玉",),
        guests=("贾惜春", "贾宝玉"), daiyu=0.50,
    ),
    "贾母院": Room(
        name="贾母院", residents=("王熙凤",),
        guests=("贾宝玉", "贾探春", "秦可卿"),
        mention_only=("贾母", "平儿", "鸳鸯"), daiyu=0.50,
    ),
    "王熙凤院": Room(
        name="王熙凤院", residents=("王熙凤",),
        guests=("贾探春", "史湘云", "薛宝钗", "秦可卿"),
        mention_only=("平儿", "贾琏"), daiyu=0.50,
    ),
    "荣禧堂": Room(
        name="荣禧堂", residents=("王熙凤",),
        guests=("薛宝钗", "贾探春", "贾元春", "秦可卿"),
        mention_only=("贾母", "贾政", "王夫人"), daiyu=0.50,
    ),
    "省亲别墅": Room(
        name="省亲别墅", residents=("贾元春",),
        guests=("王熙凤", "贾宝玉", "薛宝钗"), daiyu=0.50,
    ),
    "梨香院": Room(
        name="梨香院",
        guests=("薛宝钗", "史湘云", "贾宝玉"),
        mention_only=("龄官", "芳官"), daiyu=0.50,
    ),
}

# 全部可玩人物（与前端 characterStates.ts 的十二位一致）
PLAYABLE: tuple[str, ...] = (
    "林黛玉", "贾宝玉", "薛宝钗", "史湘云", "贾探春", "贾迎春",
    "贾惜春", "贾元春", "李纨", "妙玉", "秦可卿", "王熙凤",
)


def average_daiyu_presence() -> float:
    """十四间房黛玉在场率的均值——用来核对"约 60%"。"""
    return sum(room.daiyu for room in ROOMS.values()) / len(ROOMS)


def seed_of(user_id: str, game_day: int, game_period: str, scene: str) -> int:
    """同一时段内进出同一间房，抽到的人必须一致，所以用确定性播种。"""
    raw = "%s|%s|%s|%s" % (user_id, game_day, game_period, scene)
    return int.from_bytes(hashlib.sha256(raw.encode("utf-8")).digest()[:8], "big")


def _weighted_draw(pool: list[tuple[str, float]], target: int, rng: random.Random) -> list[str]:
    """按权重无放回抽人。"""
    picked: list[str] = []
    while len(picked) < target and pool:
        total = sum(weight for _, weight in pool)
        if total <= 0:
            break
        point = rng.random() * total
        running = 0.0
        chosen = len(pool) - 1
        for index, (_, weight) in enumerate(pool):
            running += weight
            if point <= running:
                chosen = index
                break
        picked.append(pool.pop(chosen)[0])
    return picked


def cast_for(user_id: str, game_day: int, game_period: str, scene: str) -> dict:
    """算出这间房此刻有谁。结果在 用户＋日＋时段＋场景 相同时完全一致。"""
    room = ROOMS.get(scene)
    if room is None:  # 未知场景：给一个不空的最小池子，不至于让人唱独角戏
        room = Room(name=scene, guests=("贾宝玉", "薛宝钗", "贾探春"))

    rng = random.Random(seed_of(user_id, game_day, game_period, scene))

    picked: list[str] = []
    daiyu_present = room.daiyu > 0 and rng.random() < room.daiyu
    if daiyu_present:
        picked.append(DAIYU)

    pool: list[tuple[str, float]] = []
    for name in room.residents:
        if name != DAIYU:
            pool.append((name, RESIDENT_WEIGHT * GLOBAL_WEIGHT.get(name, 1.0)))
    for name in room.guests:
        if name != DAIYU:
            pool.append((name, GUEST_WEIGHT * GLOBAL_WEIGHT.get(name, 1.0)))

    ceiling = max(1, min(room.capacity, len(picked) + len(pool)))
    target = rng.randint(1, ceiling)
    picked.extend(_weighted_draw(pool, target - len(picked), rng))

    # 排序：黛玉 → 本房常驻 → 访客。首位即入席问候的人（问候沿用 present[0] 的约定）。
    ordered = [name for name in picked if name == DAIYU]
    ordered += [name for name in picked if name in room.residents and name != DAIYU]
    ordered += [name for name in picked if name not in room.residents and name != DAIYU]

    return {
        "scene": scene,
        "cast": ordered,
        "greeter": ordered[0] if ordered else "",
        "residents": [name for name in room.residents if name != DAIYU],
        "guests": [name for name in room.guests if name != DAIYU],
        "mention_only": list(room.mention_only),
        "daiyu_present": daiyu_present,
        "daiyu_chance": round(room.daiyu, 2),
        "known_room": scene in ROOMS,
    }
