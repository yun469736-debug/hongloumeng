# -*- coding: utf-8 -*-
"""原著文本的来源、切回与清洗。

工作区的《红楼梦》.txt 是 OCR 产物，有两类可机械修复的缺陷，和一类逐字乱码：

1. 引号体系被替换：左引号成了全角句号、右引号成了 &#039;。
   「南省俗谓作。辣子&#039;」其实是「南省俗谓作“辣子”」。
2. 书名号被转义成 lt;lt;…gt;gt;，另有 &quot; 一类的 HTML 实体残留。
3. 生僻字被换成了无关字符：「两弯似蹙非蹙ズ烟眉」应为「罥烟眉」、
   「寄言纨э与膏粱」应为「纨绔」、「一え净土掩风流」应为「一抔净土」。
   这一类只能逐字修，见 CHAR_FIXES——每一条都是对着通行本认出来的常用字，
   不做任何猜测：认不出的宁可留着，也不替古人改字。

清洗在读取时进行，不改动源文件：源文件同时是 RAG 语料的来源，
改了它反而会让本地文本与 Milvus 里的分片对不上。
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

TEXT_PATH = Path(__file__).resolve().parent.parent / "《红楼梦》.txt"

# 左引号被误写成句号时，这个句号前面通常是这样几个字
_QUOTE_VERBS = "作叫谓称唤名是道说"

# 逐字乱码 → 通行本用字。按长度倒序应用，避免短串先命中长串的一部分。
CHAR_FIXES: tuple[tuple[str, str], ...] = (
    ("翠幄青h车", "翠幄青䌷车"),
    ("红h软帘", "红䌷软帘"),
    ("窄e袄", "窄褃袄"),
    ("金ы彝", "金蜼彝"),
    ("玻璃ニ", "玻璃㼧"),
    ("猩红洋や", "猩红洋罽"),
    ("プ手毕", "盥手毕"),
    ("钗钏プ沐", "钗钏盥沐"),
    ("寄言纨э与膏粱", "寄言纨绔与膏粱"),
    ("似蹙非蹙ズ烟眉", "似蹙非蹙罥烟眉"),
    ("态生两ь之愁", "态生两靥之愁"),
    ("漆黑油光的シ儿", "漆黑油光的䰖儿"),
    ("二疗п疾", "二疗冤疾"),
    ("写字手打p儿", "写字手打颤儿"),
    ("c防问你的书", "提防问你的书"),
    ("狼o蠢大之物", "狼犺蠢大之物"),
    ("剩得自己孤в", "剩得自己孤凄"),
    ("上来д扶", "上来搀扶"),
    ("才г气的人", "才咽气的人"),
    ("贾琮，贾e，贾珩，贾e，贾琛，贾琼，贾ж，贾蔷",
     "贾琮，贾㻞，贾珩，贾珖，贾琛，贾琼，贾璘，贾蔷"),
    ("贾琛，贾ж，贾蔷四个人", "贾琛，贾璘，贾蔷四个人"),
    ("门栏窗k", "门栏窗槅"),
    ("白石Лo", "白石崚嶒"),
    ("雕h绣槛", "雕甍绣槛"),
    ("桔槔辘ち", "桔槔辘轳"),
    ("水声潺ざ", "水声潺湲"),
    ("翠带飘し", "翠带飘飖"),
    ("大约是じ兰", "大约是茝兰"),
    ("是金す草", "是金䔲草"),
    ("是玉ぁ藤", "是玉蕗藤"),
    ("藿ずぢ荨", "藿蒳姜荨"),
    ("吟成w蔻才犹艳", "吟成豆蔻才犹艳"),
    ("睡足酴せ梦也香", "睡足酴醾梦也香"),
    ("一k一k", "一槅一槅"),
    ("其k各式各样", "其槅各式各样"),
    ("纱厨锦k", "纱厨锦槅"),
    ("挡围ぜ", "挡围幕"),
    ("围ぜ挡严", "围幕挡严"),
    ("围ぜ之外", "围幕之外"),
    ("珠帘绣ぜ", "珠帘绣幕"),
    ("龙旌凤そ", "龙旌凤翣"),
    ("唐钱ぞ咏芭蕉诗", "唐钱珝咏芭蕉诗"),
    ("忙另プ手进去", "忙另盥手进去"),
    ("锦やむ衾睡未成", "锦罽鹴衾睡未成"),
    ("银样め枪头", "银样镴枪头"),
    ("满园里绣带飘し", "满园里绣带飘飖"),
    ("四面雕镂k子糊着纸", "四面雕镂槅子糊着纸"),
    ("把这k子都推开了", "把这槅子都推开了"),
    ("那些**狗盗的人", "那些鸡鸣狗盗的人"),
    ("茶炉子也不グ", "茶炉子也不爖"),
    ("不该我グ的班儿", "不该我爖的班儿"),
    ("一え净土掩风流", "一抔净土掩风流"),
)


# —— 第二轮：单字替换、拼音泄漏，以及 OCR 留下的位置标记（*）
#    凡通行本读法不能确定的，宁可留着不动，也不替古人改字。
CHAR_FIXES += (
    ("翠幄青h车*", "翠幄青䌷车"),
    ("即\ue7ba视而有情", "即瞋视而有情"),
    ("纨э", "纨绔"),
    ("一样，-却是", "一样，却是"),
    ("垂头丧气も些什么", "垂头丧气些什么"),
    ("自己chuang上", "自己床上"),
    ("满屋a黑", "满屋漆黑"),
    ("尺幅鲛あ劳解赠", "尺幅鲛绡劳解赠"),
    ("何ごr惠爱之深哉", "何痌瘝惠爱之深哉"),
    ("见k子上碟槽", "见槅子上碟槽"),
    ("那k子尽上头", "那槅子尽上头"),
    ("心下ゅ*频*", "心下敁敠"),
    ("把皮*橇*", "把皮籤"),
    ("赶了来*炔璩*", "赶了来撤茶"),
    ("镌着“べ*骚*”", "镌着“𤫫爮斝”"),
    ("镌着“点犀**”", "镌着“点犀䀉”"),
    ("斟了一*视膑煊*", "斟了一䀉递与黛玉"),
    ("一个大ニ出来", "一个大瓟斝出来"),
    ("袭人*破涞缆*", "袭人敁敠"),
    ("鼾*巳缋*", "鼾齁如雷"),
    ("谁敢**私", "谁敢徇私"),
    ("外间窗ァ不曾扣好", "外间窗屜不曾扣好"),
    ("温习l些", "温习些"),
    ("两ゴ红赤", "两颧红赤"),
    ("丰肩ガ体", "丰肩愌体"),
    ("眼キ息微", "眼瞤息微"),
    ("譬喻了一会。w袭人", "譬喻了一会。袭人"),
)

_FIXES_SORTED = tuple(sorted(CHAR_FIXES, key=lambda item: -len(item[0])))

_SEPARATOR = re.compile(r"-{2,}|―{2,}(?=-)|_{2,}")
_ENTITY = re.compile(r"&(?:#\d+|#x[0-9a-fA-F]+|[a-zA-Z]+);")
_TAG = re.compile(r"lt;+|gt;+")
_CHAPTER_HEAD = re.compile(r"^第([一二三四五六七八九十百零]+)回\s+(\S.*)$")

_CN_DIGITS = "零一二三四五六七八九"


def _cn_to_int(text: str) -> int:
    if "百" in text:
        head, rest = text.split("百", 1)
        value = (_CN_DIGITS.index(head) if head else 1) * 100
        if "十" in rest:
            tens, ones = rest.split("十")
            return value + (int(_CN_DIGITS.index(tens)) if tens else 1) * 10 + (
                _CN_DIGITS.index(ones) if ones else 0
            )
        return value + sum(
            _CN_DIGITS.index(char) * 10 ** (len(rest) - 1 - index)
            for index, char in enumerate(rest)
        )
    if "十" in text:
        tens, ones = text.split("十")
        return (int(_CN_DIGITS.index(tens)) if tens else 1) * 10 + (
            _CN_DIGITS.index(ones) if ones else 0
        )
    if len(text) == 1:
        return _CN_DIGITS.index(text)
    return sum(
        _CN_DIGITS.index(char) * 10 ** (len(text) - 1 - index)
        for index, char in enumerate(text)
    )


def normalize(text: str) -> str:
    """把一段原著文本清洗成可读的样子。可重复调用。"""
    if not text:
        return text
    out = text

    # 1. 引号体系：左引号被写成了句号，右引号被写成了 &#039;
    out = re.sub(r"(?<=[" + _QUOTE_VERBS + r"])。(?=[^\s。]{1,40}?&#039;)", "\u201c", out)
    out = re.sub(r"：。(?=[^\s。])", "：\u201c", out)
    out = out.replace("&#039;", "\u201d")

    # 2. 书名号与其余实体
    out = _TAG.sub(lambda m: "《" if m.group().startswith("lt") else "》", out)
    out = _ENTITY.sub(lambda m: html.unescape(m.group()), out)

    # 3. 分隔线与占位下划线
    out = _SEPARATOR.sub("", out)

    # 4. 逐字乱码
    for wrong, right in _FIXES_SORTED:
        if wrong in out:
            out = out.replace(wrong, right)

    # 5. 收尾：夹在引号前后的孤立连字符
    out = re.sub(r"(?<=[^\s])-(?=[\u201d，。])", "", out)
    out = re.sub(r"[ \t]+", " ", out)
    return out


@dataclass(frozen=True)
class ChapterText:
    number: int
    title: str
    body: str

    def paragraphs(self) -> list[str]:
        return [item.strip() for item in self.body.split("\n") if item.strip()]


@lru_cache(maxsize=1)
def all_chapters() -> dict[int, ChapterText]:
    """读入全书并按回切开（已清洗）。带缓存，读一次就够。"""
    raw = TEXT_PATH.read_text(encoding="utf-8", errors="replace")
    lines = raw.splitlines()

    marks: list[tuple[int, str, int]] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        match = _CHAPTER_HEAD.match(stripped)
        if match and len(stripped) < 80:
            marks.append((_cn_to_int(match.group(1)), match.group(2).rstrip("012"), index))

    chapters: dict[int, ChapterText] = {}
    for position, (number, title, index) in enumerate(marks):
        end = marks[position + 1][2] if position + 1 < len(marks) else len(lines)
        body = normalize("\n".join(lines[index + 1 : end]))
        if number in chapters:  # 同一回被拆成两段的情况，接上
            chapters[number] = ChapterText(
                number, chapters[number].title, chapters[number].body + body
            )
        else:
            chapters[number] = ChapterText(number, title, body)
    return chapters


def chapter_text(number: int) -> ChapterText | None:
    return all_chapters().get(number)


def combined_text(numbers: tuple[int, ...]) -> str:
    """把一回或多回接成一段连续正文（章可以跨回）。"""
    parts = []
    for number in numbers:
        item = chapter_text(number)
        if item:
            parts.append(item.body)
    return "\n".join(parts)


def residual_garbage(text: str) -> list[str]:
    """自检用：列出清洗后仍可疑的字符。"""
    bad = []
    for char in text:
        code = ord(char)
        if 0x4E00 <= code <= 0x9FFF:  # 基本汉字
            continue
        if 0x3400 <= code <= 0x4DBF or 0x20000 <= code <= 0x2FA1F:  # 扩展 A / B 及以上
            continue
        if 0x3000 <= code <= 0x303F or 0xFF00 <= code <= 0xFFEF:  # 中文标点与全角
            continue
        if char in "\u201c\u201d\u2018\u2019\u2014\u2015\u2026\u00b7\n\r \t":
            continue
        if char.isdigit():
            continue
        bad.append(char)
    return bad
