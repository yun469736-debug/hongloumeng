"""人物配置注册表：一位主角 + 十一位配角。"""

from agent.persona.base import Persona, get_persona, list_personas, register
from agent.persona.lin_daiyu import LIN_DAIYU
from agent.persona.supporting_cast import PERSONAS as SUPPORTING_PERSONAS

register(LIN_DAIYU)
for _persona in SUPPORTING_PERSONAS:
    register(_persona)

PROTAGONIST = LIN_DAIYU
SUPPORTING = SUPPORTING_PERSONAS

__all__ = [
    "Persona",
    "get_persona",
    "list_personas",
    "register",
    "LIN_DAIYU",
    "PROTAGONIST",
    "SUPPORTING",
    "SUPPORTING_PERSONAS",
]
