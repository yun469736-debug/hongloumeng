# -*- coding: utf-8 -*-
"""入梦择章的编排。

一次入梦的流程：
    enter  → 引梦（名单首位当事人开口）+ 第一段正文与第一个选择点
    choose → 结算预写后果（只结算一次）+ 在席的人表态，并带回下一段
    leave  → 中途退出，保留进度

太虚一梦：梦里可以选、可以变，原著一字不动；出梦只把心绪、心事与态度留下。
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Iterator

from agent import dream, schemas
from agent.db import repository
from agent.llm.generator import DialogueContext, generate_reply_stream
from agent.llm.providers import resolve_provider
from agent.persona import get_persona
from agent.rag.retriever import Evidence

logger = logging.getLogger(__name__)

DREAM_SCENE_PREFIX = "入梦·第"
EXIT_LINE = "这一段依旧如此，你我都只是又走了一遍。"

# 引梦与表态都只取正文末尾这一截，太长会把上下文挤爆
_EXCERPT_CHARS = 700


def scene_label(chapter: dream.Chapter) -> str:
    return DREAM_SCENE_PREFIX + chapter.chapter_label + "回"


def _excerpt(text: str) -> str:
    body = (text or "").strip().replace("\n", "")
    return body[-_EXCERPT_CHARS:] if len(body) > _EXCERPT_CHARS else body


def locate(chapter: dream.Chapter, choice: str | None = None) -> dict:
    """按当前进度取出一段与它后面的选择点。"""
    segments = dream.plan(chapter)
    return segments[0]


def _segment_at(chapter: dream.Chapter, index: int) -> dict | None:
    segments = dream.plan(chapter)
    if index < 0 or index >= len(segments):
        return None
    return segments[index]


def _resolve_cast(chapter: dream.Chapter, requested: list[str] | None) -> list[str]:
    """默认用该章涉及的当事人；来客增删过的以请求为准（不持久）。"""
    allowed = [name for name in (requested or []) if get_persona(name) is not None]
    if not allowed:
        return list(chapter.cast)
    return allowed


def _provider(api_key: str | None):
    try:
        provider, notice = resolve_provider(api_key)
    except Exception as exc:  # noqa: BLE001
        return None, f"模型不可用：{exc}"
    return provider, notice


def _context(
    uid: str,
    persona,
    chapter: dream.Chapter,
    node: dream.Node | None,
    option: dream.Option | None,
    segment_text: str,
    present: list[str],
    user: dict[str, Any],
    extra_notes: list[str],
) -> DialogueContext:
    where = f"第{chapter.chapter_label}回《{chapter.title}》"
    story = [f"{where}的这一段正文（节选，仅供你回忆情节，不要照念）：{_excerpt(segment_text)}"]
    if node is not None:
        story.append("眼下的关口：" + node.situation)
    notes = [
        "你们正一同在「太虚一梦」里重走原著的一段。梦里可以商议、可以动情，"
        "但原著是已经发生的过去，不可篡改；你们都知道后来发生了什么。",
        *extra_notes,
    ]
    return DialogueContext(
        speaker=persona.name,
        present=present,
        game_time=f"第{int(user.get('game_day') or 1)}日·{user.get('game_period') or '清晨'}（梦中）",
        profile=repository.get_profile_facts(uid),
        memory=[],
        room=[],
        evidence=[],
        user_text=(option.text if option is not None else ""),
        stage=repository.get_affection(uid, persona.name)["stage"] if persona.has_relationship else "",
        state=repository.state_lines(uid, persona.name),
        story=story,
        notes=notes,
    )


def _settle(uid: str, chapter: dream.Chapter, option: dream.Option) -> bool:
    """结算预写后果。整章只结算一次，重玩不再改状态。"""
    progress = repository.dream_progress(uid, chapter.key)
    if progress and progress.get("settled"):
        return False
    user = repository.ensure_user(uid)
    day = int(user.get("game_day") or 1)
    for effect in dream.effects_of(option):
        current = repository.ensure_character_state(uid, effect.character)
        repository.set_character_state(
            uid,
            effect.character,
            mood=effect.mood or None,
            secret=effect.secret or None,
            attitude=current["attitude"] + effect.attitude,
            game_day=day,
        )
    return True


def _responders(chapter: dream.Chapter, node: dream.Node, option: dream.Option, cast: list[str]) -> list[str]:
    """先让与这个选项有关的人开口，其次引梦人，最多两位。"""
    if option is None:  # 引梦那一步还没有选择，由名单首位开口
        for fallback in (chapter.invoker, *cast):
            if fallback:
                return [fallback]
        return []
    involved = [effect.character for effect in dream.effects_of(option)]
    picked = [name for name in involved if name in cast and name != "我"]
    for fallback in (chapter.invoker, *cast):
        if len(picked) >= 2:
            break
        if fallback in cast and fallback not in picked:
            picked.append(fallback)
    return picked[:2]


def _stream_reactions(
    uid: str,
    chapter: dream.Chapter,
    node: dream.Node | None,
    option: dream.Option | None,
    segment_text: str,
    cast: list[str],
    api_key: str | None,
    extra_first: list[str],
    extra_second: list[str],
    force: list[str] | None = None,
) -> Iterator[dict[str, Any]]:
    provider, notice = _provider(api_key)
    if notice:
        yield schemas.error_event(notice)
    if provider is None:
        return
    try:
        user = repository.ensure_user(uid)
    except Exception:  # noqa: BLE001
        user = {"game_day": 1, "game_period": "清晨"}

    if force:
        names = list(force)
    elif node is not None:
        names = _responders(chapter, node, option, cast)
    else:
        names = [chapter.invoker]
    for index, name in enumerate(names):
        persona = get_persona(name)
        if persona is None:
            continue
        notes = list(extra_first if index == 0 else extra_second)
        context = _context(
            uid, persona, chapter, node, option, segment_text, cast, user, notes
        )
        yield schemas.speaker_start(persona.name)
        emitted = False
        try:
            for label, payload in generate_reply_stream(provider, persona, context):
                if label != "sentence":
                    continue
                emitted = True
                yield schemas.sentence(
                    speaker=persona.name,
                    text=payload["text"],
                    emotion=payload["emotion"],
                    action=payload["action"],
                    intensity=payload["intensity"],
                    kind=payload["kind"],
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("梦境表态失败：%s", exc)
        if not emitted:
            yield schemas.error_event(f"{persona.name}一时未能开口。")
        yield schemas.speaker_end(persona.name)


def _context_event(
    chapter: dream.Chapter,
    segment: dict,
    cast: list[str],
    uid: str,
    finished: bool,
    choice_map: dict[str, str],
) -> dict[str, Any]:
    node = segment.get("node")
    return {
        "type": "dream",
        "chapter": dream.chapter_summary(chapter),
        "segment_index": segment["index"],
        "segment_total": len(dream.plan(chapter)),
        "text": segment["text"],
        "finished": finished,
        "exit_line": EXIT_LINE if finished else "",
        "cast": cast,
        "choices": choice_map,
        "node": None
        if node is None or finished
        else {
            "key": node.key,
            "title": node.title,
            "situation": node.situation,
            "options": [
                {"key": item.key, "text": item.text, "basis": item.basis} for item in node.options
            ],
        },
    }


def enter_events(
    uid: str,
    chapter_key: str,
    requested_cast: list[str] | None = None,
    api_key: str | None = None,
    restart: bool = False,
) -> Iterator[dict[str, Any]]:
    chapter = dream.find(chapter_key)
    if chapter is None:
        yield schemas.error_event("没有找到这一章。")
        yield schemas.round_end()
        return

    repository.ensure_user(uid)
    progress = repository.dream_progress(uid, chapter_key)
    if restart or progress is None:
        index = 0
        repository.dream_save_progress(
            uid, chapter_key, segment_index=0, status="started", cast=_resolve_cast(chapter, requested_cast)
        )
        choice_map: dict[str, str] = {}
        if restart:
            repository.dream_forget(uid, chapter_key)
            repository.dream_save_progress(
                uid, chapter_key, segment_index=0, status="started",
                settled=bool(progress and progress.get("settled")),
                cast=_resolve_cast(chapter, requested_cast),
            )
    else:
        index = int(progress["segment_index"])
        choice_map = repository.dream_choices(uid, chapter_key)

    cast = _resolve_cast(chapter, requested_cast) or (
        progress["cast"] if progress and progress.get("cast") else list(chapter.cast)
    )
    if requested_cast:
        repository.dream_save_progress(uid, chapter_key, cast=cast)

    segment = _segment_at(chapter, index)
    if segment is None:
        yield schemas.error_event("这一章已经走到头了。")
        yield schemas.round_end()
        return

    # 引梦：由名单首位当事人开口
    invoker = get_persona(chapter.invoker) or get_persona(cast[0] if cast else "")
    if invoker is not None:
        invoker = get_persona(chapter.invoker) or invoker
        yield from _stream_reactions(
            uid, chapter, segment.get("node"), None, segment["text"], cast, api_key,
            [
                f"你正替来客引一场「太虚一梦」，要带他重走{chapter.title}这一段。",
                "说一两句，把来客带进这一段的处境里；不要复述原文，用你自己的口吻。",
            ],
            [],
        )

    yield _context_event(chapter, segment, cast, uid, False, choice_map)
    yield schemas.round_end(settlement={"dream": chapter.key, "segment": segment["index"]})


def choose_events(
    uid: str,
    chapter_key: str,
    node_key: str,
    option_key: str,
    api_key: str | None = None,
) -> Iterator[dict[str, Any]]:
    chapter = dream.find(chapter_key)
    if chapter is None:
        yield schemas.error_event("没有找到这一章。")
        yield schemas.round_end()
        return

    node = next((item for item in chapter.nodes if item.key == node_key), None)
    option = next((item for item in node.options if item.key == option_key), None) if node else None
    if node is None or option is None:
        yield schemas.error_event("这个选择不认识。")
        yield schemas.round_end()
        return

    progress = repository.dream_progress(uid, chapter_key) or {
        "segment_index": 0, "status": "started", "settled": False, "cast": [],
    }
    cast = progress.get("cast") or list(chapter.cast)
    segment_index = int(progress["segment_index"])
    segment = _segment_at(chapter, segment_index) or {"index": segment_index, "text": "", "node": node}

    repository.dream_record_choice(uid, chapter_key, node.key, option.key)
    applied = _settle(uid, chapter, option)
    reaction_note = [
        "来客在这一段做了这样的选择：" + option.text,
        "原著里这一段的情形是：" + option.basis,
        "以你的性情对此表态；可以赞同，也可以反对，还可以替当事人说一句。",
    ]
    if not applied:
        reaction_note.append("（这是重走一遍，你已经历过，不必当成本回才有的事。）")

    yield from _stream_reactions(
        uid, chapter, node, option, segment["text"], cast, api_key, reaction_note,
        ["同席的另一个人也在场，你从自己的角度说，不必与他一致，也别替他把话说完。"],
    )

    next_index = segment_index + 1
    following = _segment_at(chapter, next_index)
    finished = following is None or following.get("node") is None and next_index >= len(dream.plan(chapter)) - 1
    if finished:
        repository.dream_save_progress(uid, chapter_key, segment_index=next_index, status="finished", settled=True)
        last = _segment_at(chapter, len(dream.plan(chapter)) - 1)
        # 出梦由引梦人收束——固定一句旁白每章都一样，不如让当事人自己说
        yield from _stream_reactions(
            uid, chapter, None, None, last["text"] if last else "", cast, api_key,
            [
                f"这一段（{chapter.title}）已经走完，来客要出梦了。",
                "用一两句收束：点出原著依旧如此、你们只是又陪他走了一遍。"
                "语气合你的性情，不要写成旁白或解说。",
            ],
            [],
            force=[chapter.invoker],
        )
        yield _context_event(chapter, last, cast, uid, True, repository.dream_choices(uid, chapter_key))
    else:
        repository.dream_save_progress(uid, chapter_key, segment_index=next_index)
        yield _context_event(chapter, following, cast, uid, False, repository.dream_choices(uid, chapter_key))
    yield schemas.round_end(settlement={"dream": chapter.key, "segment": next_index, "settled": applied})


def leave(uid: str, chapter_key: str) -> dict:
    chapter = dream.find(chapter_key)
    if chapter is None:
        return {"ok": False, "detail": "没有找到这一章。"}
    following = _segment_at(chapter, int((repository.dream_progress(uid, chapter_key) or {}).get("segment_index") or 0))
    return {"ok": True, "chapter": chapter.key, "resumable": following is not None}


def catalog(uid: str) -> dict:
    progress = repository.dream_all_progress(uid)
    items = []
    for chapter in dream.CHAPTERS:
        state = progress.get(chapter.key)
        items.append({
            **dream.chapter_summary(chapter),
            "status": (state or {}).get("status", "new"),
            "segment_index": (state or {}).get("segment_index", 0),
            "settled": bool((state or {}).get("settled")),
        })
    return {
        "ok": True,
        "chapters": items,
        "progress": {
            key: {"segment_index": value["segment_index"], "status": value["status"]}
            for key, value in progress.items()
        },
    }
