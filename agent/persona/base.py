# -*- coding: utf-8 -*-
"""人物配置基类与共享词表归一化。

每位人物只声明自己的情绪/动作词表与系统提示词；越界输出统一归一到最近可用状态，
使前端立绘匹配始终命中已登记素材。
"""

from __future__ import annotations

from dataclasses import dataclass, field

# 模型常见越界情绪 → 人物词表中的近义项
EMOTION_SYNONYMS: dict[str, str] = {
    "开心": "温柔", "欢喜": "温柔", "欣然": "温柔", "浅笑": "温柔", "畅快": "温柔",
    "快乐": "温柔", "欣喜": "温柔", "愉悦": "温柔", "高兴": "温柔",
    "生气": "冷淡", "不悦": "冷淡", "嗔怒": "冷淡", "恼怒": "冷淡", "严肃": "冷淡",
    "愤怒": "冷淡", "不满": "冷淡", "倔强": "冷淡", "冷傲": "冷淡",
    "惊讶": "迟疑", "意外": "迟疑", "微讶": "迟疑", "警觉": "迟疑", "一怔": "迟疑",
    "困惑": "迟疑", "疑惑": "迟疑",
    "平静": "沉静", "端静": "沉静", "从容": "沉静", "淡然": "沉静", "冷静": "沉静",
    "安静": "沉静", "自持": "沉静",
    "难过": "伤心", "悲伤": "伤心", "哀伤": "哀愁", "悲凉": "伤感", "凄凉": "伤感",
    "愁苦": "惆怅", "愁绪": "惆怅", "幽思": "思念", "惦念": "思念", "怀想": "思念",
    "害羞": "含羞", "羞涩": "含羞", "羞怯": "含羞",
    "流泪": "落泪", "哭泣": "落泪", "泪下": "落泪",
    "凄婉": "伤感",
    "凝望": "温柔", "含笑": "温柔", "展颜": "温柔", "关切": "温柔",
    # 王熙凤一类"笑里带锋"的常见越界写法
    "冷笑": "狡黠", "嗤笑": "狡黠", "讥笑": "狡黠", "讥诮": "狡黠", "讥讽": "狡黠",
    "厉色": "愠怒", "怒色": "愠怒", "呵斥": "愠怒",
    "忍泪": "隐忍", "强忍": "隐忍",
    "羞恼": "生气", "自得": "得意", "扬扬自得": "得意", "得意洋洋": "得意",
    "机敏": "清醒", "精明": "清醒", "算计": "筹谋", "盘算": "筹谋",
}

# 模型常见越界动作 → 人物词表中的近义项
ACTION_SYNONYMS: dict[str, str] = {
    "垂首": "低眉", "低首": "低眉", "低头": "低眉", "俯首": "低眉",
    "凝望": "垂眸", "注视": "垂眸", "望": "侧眸", "正视": "侧眸", "直视": "侧眸",
    "侧首": "侧眸", "侧身": "侧眸", "侧脸": "侧眸", "回头": "回眸", "回望": "回眸",
    "掩口": "掩唇", "捂嘴": "掩唇", "抿唇": "掩唇",
    "擦泪": "拭泪", "抹泪": "拭泪", "拭面": "拭泪", "含泪": "拭泪",
    "托面": "托腮", "支颐": "托腮", "托脸": "托腮",
    "握帕": "执帕", "拈帕": "执帕", "持帕": "执帕",
    "掩袖": "掩面", "掩脸": "掩面", "遮面": "掩面",
    "拈花": "捧花", "持花": "捧花", "赏花": "捧花", "弄花": "捧花",
    "思索": "沉思", "思量": "沉思", "出神": "沉思", "沉吟": "沉思",
    "询问": "侧眸", "发问": "侧眸", "轻抚袖口": "执帕", "捻帕": "执帕",
    "低头拭泪": "拭泪", "垂泪": "拭泪", "掩泣": "掩面", "啜泣": "掩面",
    # 同上：王熙凤的举止词
    "拍桌": "拍案", "击案": "拍案", "怒拍": "拍案",
    "抬头": "抬首", "扬首": "抬首", "仰头": "仰首", "举头": "仰首",
    "招手示意": "招手", "邀请": "相邀", "相请": "相邀",
    "责备": "斥责", "呵斥": "斥责", "训斥": "斥责", "叱责": "斥责",
    "掩口而笑": "掩唇", "以袖掩口": "掩唇",
}


# 关系信号事件类型（好感评估用，前端不可见）
AFFECTION_EVENT_TYPES = (
    "有意义互动", "普通闲聊", "重复恭维", "敷衍刷单",
    "轻度冒犯", "重大背弃", "关怀善意", "如约而至", "其他",
)


@dataclass
class Persona:
    """一位人物的角色底层配置。"""

    id: str
    name: str
    courtesy: str
    supported_emotions: list[str]
    supported_actions: list[str]
    default_emotion: str
    default_action: str
    default_intensity: float
    system_prompt: str
    greeting_prompt: str = ""
    # 别人怎么称呼他/她。既用于提示词里的"这些是别人唤你的名字"，
    # 也用于识别"来客这一句提到了谁"——所以必须是一处定义、前后端共用。
    aliases: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)
    # protagonist：主角，拥有七阶段关系与私有记忆；supporting：配角，能聊能感知但不建私有关系
    role: str = "supporting"
    has_relationship: bool = False
    has_private_memory: bool = False

    @property
    def is_protagonist(self) -> bool:
        return self.role == "protagonist"

    def normalize_emotion(self, value: str) -> str:
        text = (value or "").strip()
        if text in self.supported_emotions:
            return text
        mapped = EMOTION_SYNONYMS.get(text)
        if mapped and mapped in self.supported_emotions:
            return mapped
        return self.default_emotion

    def normalize_action(self, value: str) -> str:
        text = (value or "").strip()
        if text in self.supported_actions:
            return text
        mapped = ACTION_SYNONYMS.get(text)
        if mapped and mapped in self.supported_actions:
            return mapped
        return self.default_action

    def vocabulary_lines(self) -> str:
        return (
            "可用情绪：" + "、".join(self.supported_emotions) + "\n"
            "可用动作：" + "、".join(self.supported_actions)
        )

    def reply_schema(self) -> dict:
        """逐句回复的 JSON Schema：结构与词表都由服务端约束。

        只有主角才带 affection（关系暗记）；配角不参与好感结算，
        让它们也输出 affection 只会浪费 token 并诱发与关系无关的自我评价。
        """
        schema: dict = {
            "type": "object",
            "properties": {
                "sentences": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 4,
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "emotion": {"type": "string", "enum": list(self.supported_emotions)},
                            "action": {"type": "string", "enum": list(self.supported_actions)},
                            "intensity": {"type": "number"},
                            "kind": {"type": "string", "enum": ["原著事实", "性格推演", "书外知识"]},
                        },
                        "required": ["text", "emotion", "action", "intensity", "kind"],
                    },
                }
            },
            "required": ["sentences"],
        }
        if self.has_relationship:
            schema["properties"]["affection"] = {
                "type": "object",
                "properties": {
                    "delta": {"type": "number"},
                    "event_type": {"type": "string", "enum": list(AFFECTION_EVENT_TYPES)},
                    "reason": {"type": "string"},
                },
                "required": ["delta", "event_type", "reason"],
            }
            schema["required"] = ["sentences", "affection"]
        return schema


_PERSONAS: dict[str, Persona] = {}


def register(persona: Persona) -> Persona:
    _PERSONAS[persona.name] = persona
    _PERSONAS[persona.id] = persona
    return persona


def get_persona(name: str) -> Persona | None:
    if not name:
        return None
    return _PERSONAS.get(name)


def list_personas() -> list[Persona]:
    seen: dict[int, Persona] = {}
    for persona in _PERSONAS.values():
        seen[id(persona)] = persona
    return list(seen.values())
