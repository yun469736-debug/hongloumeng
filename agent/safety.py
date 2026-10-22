# -*- coding: utf-8 -*-
"""现实危机的识别。

按已确认的设计：**不向前端发独立安全提示卡**，因此这里只保留识别能力，
由 service 把它转成系统提示里的守则——该角色须先温言安抚、不责备、不浪漫化悲剧、
不提供任何伤害自己的方法。求助电话不再出现在界面上。
"""

from __future__ import annotations

CRISIS_KEYWORDS = (
    "自杀", "轻生", "不想活", "活不下去", "去死", "想死", "死了算了",
    "结束生命", "自残", "割腕", "跳楼", "跳河", "上吊", "安眠药", "烧炭",
    "了断自己", "没有意义活", "活着没意思", "自我了断", "解脱自己",
)


def detect_crisis(text: str) -> bool:
    """识别自伤、轻生或现实紧急危险。"""
    if not text:
        return False
    return any(keyword in text for keyword in CRISIS_KEYWORDS)
