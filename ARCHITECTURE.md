# 红楼梦人物 Agent —— 项目总览与二次开发指南

> 写给**接手二次开发的 AI 编码助手**（Codex 等）。目标是不必通读源码就能安全改动：哪些是刻意的设计、哪些是踩过的坑、改哪里会连带影响什么。

---

## 一、这是什么

单机可玩的红楼梦角色对话系统。FastAPI 后端 + Vue 3 前端 + 本地 Ollama 推理 + Milvus 原著检索 + MySQL 持久化。

- **一位主角**（林黛玉）：七阶段情分、隐藏好感度、三层私有记忆、入席问候、会话结算。
- **十一位配角**（薛宝钗、贾宝玉、史湘云、贾探春、贾迎春、贾惜春、贾元春、李纨、妙玉、秦可卿、王熙凤）：能聊、能感知房间，但不建私有关系。
- **十四间房**：进房时在场人物由后端按 用户＋日＋时段＋场景 播种随机决定。
- **两套剧情**：41 条房间小关目（进门偶然引出）+ 14 章入梦择章（主动重走原著，分段做选择）。

角色扮演的最高约束（来自 `LIN_DAIYU_AGENT_SPEC.md`）：

> 原著是已经发生的过去，不可否认、不可篡改；与来客相遇之后的将来，可以自然展开。

人物有"全时期融合"记忆——他们**知道结局**。这条约束贯穿全部设计，改动前务必理解。

---

## 二、跑起来

### 前置

| 依赖 | 要求 |
| --- | --- |
| Ollama | 需有 `qwen3.5:4b`（对话）与 `bge-m3`（向量） |
| Milvus | 集合 `four_classics_chunks`，5494 个分片 |
| MySQL | 建库由启动时 `migrate()` 自动完成 |
| Python | 3.13（Anaconda），依赖见 `agent/requirements.txt` |
| Node | 前端 Vite |

### 配置

复制 `agent/.env.example` 到项目根目录 `.env`（已被 `.gitignore` 覆盖）。关键项：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `LLM_PROVIDER` | `ollama` | 改 `deepseek` 才走 DeepSeek（前端另有更高优先级的密钥通道） |
| `LLM_THINK` | `false` | **必须关闭**，否则单轮可超 90 秒 |
| `LLM_NUM_CTX` | `4096` | 提示词约 2300～2900 字，低于 2048 会被截断 |
| `LLM_NUM_PREDICT` | `260` | 单轮输出上限 |
| `RAG_TOP_K` | `4` | 检索片段数 |
| `SHORT_TERM_TURNS` | `6` | 房间记录保留条数 |
| `VIGNETTE_CHANCE` | `0.35` | 进门引出房间小关目的概率 |

### 启动（两个终端）

```powershell
# 后端
python -m uvicorn agent.main:app --host 127.0.0.1 --port 8000

# 前端
cd frontend; npm.cmd run dev
```

前端 <http://localhost:5173>，`/api` 由 Vite 代理到 8000。

### 自检（改完必跑）

```powershell
python -m agent.check_vocabulary   # 后端词表 vs 前端立绘，应 0 不一致
python agent/smoke_test.py         # 主角/配角/危机 共 7 个用例
cd frontend; npm.cmd run build     # vue-tsc 类型检查 + 构建
```

---

## 三、数据流

```
前端 App.vue
  │
  ├─ 进院 ──► GET /api/room ──► rooms.cast_for() 播种出在场人物
  │                              └─ 决定立绘台上站谁、谁先开口问候
  │
  ├─ 发言 ──► POST /api/dialogue（NDJSON 流）
  │             ├─ 0. 定提供器（有 DeepSeek 密钥就校验，不通则回退本地并先报错）
  │             ├─ 1. 装配：公开档案 / 房间记录（按 scene 隔离）/ 私有记忆 / 关系阶段
  │             ├─ 2. 定向遗忘（仅主角）
  │             ├─ 3. 危机识别 → 写进提示词
  │             ├─ 4. 记下来客这句
  │             ├─ 5. 按需 RAG 检索（规则路由）
  │             ├─ 6. 人物状态 + 房间小关目
  │             ├─ 7. 生成：流式逐句 JSON 增量解析，第一句先发出去
  │             └─ 8. 写回房间记录 / 好感结算 / 事件流水
  │
  ├─ 问候 ──► POST /api/greeting（进院 / 入席 / 离席 三种口吻）
  │
  └─ 入梦 ──► GET  /api/dream/list
              POST /api/dream/enter   引梦 + 第一段正文与抉择点
              POST /api/dream/choose  结算预写后果 + 在场表态 + 带回下一段
              POST /api/dream/leave   中途退出
```

---

## 四、目录与模块职责

### 后端 `agent/`

| 文件 | 职责 |
| --- | --- |
| `main.py` | FastAPI 入口。14 个路由、`_uid()` 归一、`/health` 逐项报依赖 |
| `config.py` | env 驱动的 `Settings`，全部默认值在此 |
| `schemas.py` | 请求模型与事件构造函数 |
| `service.py` | **对话编排中枢**。`dialogue_events` / `greeting_events` / `state_of`，以及 `_room_snapshot`、`_mentioned_note`、`_drop_current_round`、`_room_story`、`_apply_vignette` |
| `rooms.py` | 十四间房的在场名册、权重、播种抽取 |
| `story.py` | 41 条房间小关目 |
| `dream.py` | 14 章入梦数据 + `plan()` 分段 |
| `dream_service.py` | 入梦编排：`enter_events` / `choose_events` / `leave` / `catalog` |
| `text_source.py` | 读入《红楼梦》.txt、切回、**清洗 OCR 缺陷** |
| `safety.py` | 仅危机关键词识别 |
| `check_vocabulary.py` | 自检：人物词表与前端立绘对拍 |
| `smoke_test.py` | 自检：7 个端到端用例 |
| `llm/providers.py` | Ollama / DeepSeek 两个提供器；密钥校验与回退 |
| `llm/generator.py` | **提示词装配**、占位符替换、流式 JSON 增量解析、词表归一、称呼守卫 |
| `db/schema.py` | 建库建表迁移（幂等，含旧表改名与补列） |
| `db/repository.py` | 全部数据访问 |
| `persona/base.py` | `Persona` 数据类 + 情绪/动作同义词表 |
| `persona/lin_daiyu.py` | 主角人格、词表、系统提示与问候提示 |
| `persona/supporting.py` | 配角共享模板与 `SupportingSpec` |
| `persona/supporting_cast.py` | 十一位配角的具体人设 |
| `memory/manager.py` | 公开档案抽取、候选记忆、压缩去重、定向遗忘 |
| `affection/engine.py` | 好感度、七阶段 `STAGES`、滞回缓冲（仅主角） |
| `rag/retriever.py` | 规则路由 + 混合召回 + 原著专名精排；`_clip()` 顺带清洗摘句 |

### 前端 `frontend/src/`

| 文件 | 职责 |
| --- | --- |
| `App.vue` | 主界面与全部交互状态（约 36KB，最大的文件） |
| `data.ts` | 十四间场景的匾额、说明、背景图、地图热区坐标 |
| `data/characterStates.ts` | 十二位的立绘状态表（**情绪/动作词表的唯一真源**） |
| `services/agentClient.ts` | 全部后端调用 + DeepSeek 密钥管理 |
| `services/mockDialogue.ts` | `planRound()` 回合规划、NDJSON 消费、离线模拟流 |
| `engine/stateMatcher.ts` | 按情绪/动作匹配立绘状态 |
| `components/PortraitActor.vue` | 单个立绘的转场与动作 |
| `components/MapCalibrator.vue` | `?calibrate=1` 地图热区校准页 |
| `components/DreamScroll.vue` | 全屏入梦界面 |
| `styles.css` | 全部样式（约 28KB） |

---

## 五、数据表

前缀 `hlm_` 是中性的——房间里同时有十几个人说话，叫 `daiyu_*` 会误导。

| 表 | 归属 | 说明 |
| --- | --- | --- |
| `hlm_users` | 共享 | 用户与全局游戏时钟（`game_day` / `game_period`） |
| `hlm_chat` | 共享 | 房间公开发言记录。**带 `scene` 列**，房间记录按房隔离 |
| `hlm_user_profile` | 共享 | 来客自报的公开事实 |
| `hlm_character_state` | 共享 | 十二位的 `mood` / `attitude`(0~5) / `secret` |
| `hlm_memory_long` / `hlm_memory_candidate` | 主角专属 | 私有长期与候选记忆（带 `character_id`） |
| `hlm_affection` / `hlm_events` | 主角专属 | 隐藏好感度、七阶段、事件流水 |
| `hlm_dream_progress` | 共享 | 入梦进度：段号、状态、是否已结算、邀请名单 |
| `hlm_dream_choice` | 共享 | 入梦做过的选择 |

`migrate()` 幂等：旧版 `daiyu_*` 自动改名；缺列自动补（`character_id`、`scene`）。

游戏时钟：清晨 → 午后 → 黄昏 → 夜间 → 次日清晨，只在 `POST /api/session/end` 推进。

---

## 六、接口契约

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | 逐项报告 Ollama / Milvus / MySQL 与人物名册 |
| GET | `/api/state` | 关系阶段与游戏内时间（配角返回空 stage、`has_relationship=false`） |
| GET | `/api/characters` | 十二位的 `name` / `courtesy` / `aliases` / `role` |
| GET | `/api/room` | `cast` / `greeter` / `residents` / `guests` / `mention_only` / `daiyu_present` |
| POST | `/api/dialogue` | 逐句 NDJSON。须带 `speaker` 与 `round_index` |
| POST | `/api/greeting` | 逐句 NDJSON。`speaker` + `greeting_kind`(room/entry/leave) |
| POST | `/api/provider/check` | 校验 DeepSeek 密钥；空密钥不算错，只表示用本地 |
| POST | `/api/session/end` | 压缩主角候选记忆 + 推进一个时段（跨日顺带做态度回归） |
| GET | `/api/history` | 全量聊天回看（**不带 scene 过滤**） |
| POST | `/api/reset` | 完整世界重置，必须带 `confirm: true` |
| GET | `/api/dream/list` | 十四章目录与本机进度 |
| POST | `/api/dream/enter` | 引梦 + 第一段 + 抉择点（NDJSON） |
| POST | `/api/dream/choose` | 结算 + 表态 + 下一段（NDJSON） |
| POST | `/api/dream/leave` | 中途退出，保留进度 |

**DeepSeek 密钥**走 `X-DeepSeek-Key` 请求头，不放进 body（免得进日志）。

### 事件协议（NDJSON，一行一个 JSON）

```json
{"type":"speaker_start","speaker":"薛宝钗"}
{"type":"sentence","speaker":"薛宝钗","emotion":"冷静","action":"端坐","intensity":0.5,"text":"…","kind":"性格推演","confidence":0.6,"evidence":[]}
{"type":"stage","speaker":"林黛玉","stage":"留意"}
{"type":"error","message":"DeepSeek 密钥错误：密钥无效或无权访问。已改用本地模型。"}
{"type":"dream","chapter":{},"segment_index":0,"segment_total":3,"text":"…","node":{},"finished":false,"exit_line":""}
{"type":"round_end","settlement":{}}
```

**协议只允许追加，不允许改动已有字段**——前端按 type 分发，老事件的行为不能变。

---

## 七、人物系统

### Persona 结构（`agent/persona/base.py`）

```python
@dataclass
class Persona:
    id, name, courtesy
    supported_emotions: list[str]   # 必须与前端立绘完全一致
    supported_actions:  list[str]   # 同上
    default_emotion, default_action, default_intensity
    system_prompt, greeting_prompt
    aliases: list[str]              # 别人怎么称呼他/她，前后端共用
    role: str = "supporting"        # protagonist | supporting
    has_relationship: bool = False  # 只有主角
    has_private_memory: bool = False
```

### 词表约束（重要）

**前端 `characterStates.ts` 的立绘清单是词表的唯一真源。** 后端人物的 `supported_emotions` / `supported_actions` 必须与它**完全相等**（不多不少），否则后端可能输出前端没有素材的状态，立绘匹配不上。

`python -m agent.check_vocabulary` 会对拍，**改完必跑**。

模型越界输出的归一在 `EMOTION_SYNONYMS` / `ACTION_SYNONYMS`，映射不到就退回该人物的默认值。

### 好感度与七阶段（仅主角）

`STAGES = ["初识","留意","相熟","信赖","知己","情动","相守"]`，带滞回缓冲与"有意义的互动"计数门槛，防止闲聊刷分。

---

## 八、提示词结构

**布局刻意分两段**（见 `lin_daiyu.py` 顶部注释）：

1. **静态人格段在前**——人设、铁律、词表，每次调用都一样。
2. **动态处境段在后**——时间、关系阶段、心境、在场人物、房里的话、检索片段。

这样同一人物连续对话时 Ollama 可复用前缀 KV 缓存。实测第二轮延迟从 65 秒降到 24 秒。

### 占位符清单（`generator._fill` 负责替换）

| 占位符 | 内容 |
| --- | --- |
| `<<NAME>>` `<<COURTESY>>` `<<ALIASES>>` | 姓名、别号、别名 |
| `<<SELF>>` `<<MANNER>>` `<<EDGE>>` `<<PAST>>` `<<STANCE>>` | 配角人设五段 |
| `<<VOCABULARY>>` | 该人物的情绪与动作词表 |
| `<<STAGE>>` | 关系阶段（配角为空） |
| `<<STATE>>` | 人物状态：心绪、心事、对你的取向 |
| `<<STORY>>` | 房间小关目 / 入梦段落 |
| `<<NOTES>>` | 本轮特别提示 |
| `<<PRESENT>>` `<<GAME_TIME>>` `<<PROFILE>>` `<<MEMORY>>` `<<ROOM>>` `<<EVIDENCE>>` | 处境 |

**注意**：`<<ALIASES>>` 与配角人设五段由 `supporting.py` 的 `fill()` 在**构建时**替换，其余由 `generator._fill` 在**发消息时**替换。

---

## 九、房间与在场人物

名册在**后端**（`agent/rooms.py`），前端只持匾额与热区。

- **常驻者权重 6、访客权重 2**，名册外的人永不出场。
- **全局修正**：贾元春 ×0.3（身在宫中）、秦可卿 ×0.3（第 13 回即亡）。
- **林黛玉单独一条**：先按房间概率掷一次，中了占一席，不参与权重抽签。潇湘馆 1.00（她的家，必在）、怡红院/沁芳亭/沁芳桥 0.80、其余十间 0.50，**十四间平均正好 60%**。
- **播种**：由 用户|日|时段|场景 取 sha256，同一时段内反复进出同一间房结果完全一致；结束会谈推进时段后才换人。
- **同席上限 5 人**（`Room.capacity`）。实测分布：1 人 24%、2 人 26%、3 人 26%、4 人 17%、5 人 6%。

**名册外的人物**（贾母、平儿、贾政、紫鹃、袭人、晴雯、莺儿、龄官等）一律"默认外出"：可以被提起、可以加引号转述，但不出场、不开口。这条写在提示词铁律里（通用一条，不枚举人名）。
---

## 十、两套剧情内容

### A. 房间小关目（`agent/story.py`，41 条）

每间房 2～4 条，带回次与**逐条核对过原文的摘句**。

- 进门约 `VIGNETTE_CHANCE`(0.35) 引出"没经历过的"一桩；
- 首触发即写 `hlm_character_state` 并在 `hlm_events` 记一条 `关目:房间·标题`；
- 谈话中按 **0.4 倍**频率回望"已经历过的"，改用追忆口气；
- 涉及人物一个都不在场则不触发。

### B. 入梦择章（`agent/dream.py`，14 章）

**「章」不等于「回」**——省亲跨 17–18、挨打跨 33–34。

- 14 章 / 27 个抉择点 / 79 个选项。
- **分段由抉择点决定**：两个抉择点之间为一段，切自 `text_source` 清洗过的正文。
- **选项后果全部预写**（`Effect(角色, 态度增减, 心绪, 心事)`），模型只负责把后果说成人话，不参与定数。
- **太虚一梦**：梦里可选可变，原著一字不动；出梦只留心绪、心事与态度。
- **整章只结算一次**：重玩不再改状态（`hlm_dream_progress.settled`）。
- 入梦对话写进 `hlm_chat`，`scene` 记为 `入梦·第N回`，所以房间记录天然读不到。

---

## 十一、人物状态与结算

`hlm_character_state` 三项：`mood` 心绪、`attitude` 对你的态度（0～5，中点 2.5）、`secret` 最近一件心事。

- **只注入提示词，界面完全不露**。`repository.state_lines()` 把数值翻成取向行（如"你对这位来客略有好感"），**数值本身不下发**。
- **每过一个游戏日，态度向中点线性回归 0.5**：从满值 5.0 或见底 0.0 回到 2.5 需整整五天，不会越过中点。
- 写入方只有两处：房间小关目首触发（`_apply_vignette`）、入梦选项结算（`_settle`）。

---

## 十二、模型提供器与密钥

三条规则：

1. **没填密钥 → 本地 Ollama**（`.env` 的默认）。
2. **填了密钥 → 先校验，通过就走 DeepSeek**。
3. **密钥有误 → 当场发一条 error 事件说明原因，再退回本地把话说完**，对话不中断。

安全约定（**改动时不要破坏**）：

- `DeepSeekProvider.api_key` 是 `repr=False`，`repr` 与异常回溯都不含密钥。
- 校验结论按密钥的 **SHA-256 前 16 位**缓存 10 分钟——缓存里只有指纹，没有密钥。
- 不落盘、不入库、不进日志。
- 校验用 `models.list()` 只读探测，不消耗生成额度。
- 前端只在校验通过时才写 localStorage。

密钥校验发生在 `dialogue_events` 的**第 0 步**——不能等检索与生成跑完才告诉用户密钥错了。

---

## 十三、原著文本清洗（`agent/text_source.py`）

工作区的《红楼梦》.txt 是 OCR 产物，有三类缺陷：

1. **引号体系被替换**：左引号成了全角句号、右引号成了 `&#039;`。例：南省俗谓作。辣子`&#039;` 实为 南省俗谓作"辣子"。
2. **书名号被转义**成 `lt;lt;…gt;gt;`，另有 HTML 实体残留。
3. **生僻字被换成无关字符**：罥烟眉→ズ烟眉、纨绔→纨э、一抔净土→一え净土、鸡鸣狗盗→两个星号加狗盗。

**清洗在读取时进行，不改源文件**——源文件同时是 RAG 语料来源，改了会与 Milvus 分片对不上。

`CHAR_FIXES` 共 78 条，每条都能对着上下文复核。**凡通行本读法不能确定的，宁可留着不动，也不替古人改字。**

- 入梦所用 17 回：清洗后残留字符为 **0**。
- 其余 103 回未处理（全书尚有 335 处）。
- `retriever._clip()` 也调用了 `normalize()`，所以界面上的"原著依据"摘句一并修好，**不必重导 Milvus**。

---

## 十四、一条贯穿全项目的设计哲学

**能用代码约束的，不要指望提示词。**

4B 模型对"别这样"这类软约束基本不听。凡是被它反复违反的规则，最后都落成了代码：

| 问题 | 提示词方案 | 最终方案 |
| --- | --- | --- |
| 臆测来客性别（"陈先生"） | 试了三次，失败 | `sanitize_address()` 程序化削掉"姓氏加称谓" |
| 输出格式跑偏 | 反复改提示词 | Ollama JSON Schema `format=` 锁死结构与枚举 |
| 越界情绪/动作 | — | `EMOTION_SYNONYMS` 归一 |
| JSON 碎片当台词输出 | — | `_looks_like_json()` 过滤 |
| 同一轮复述前一个人 | 加了规则，**无效** | `_drop_current_round()` 从上下文里拿掉 |

同理，**规则的位置也重要**：口吻指令放在提示词末尾会被整段人设压过去，必须放在最前面（见 `GREETING_KINDS`）。

---

## 十五、踩过的坑（二次开发时注意）

### 写代码时

1. **单括号不是元组。** `dream.py` 里单后果选项写成 `(Effect(...))`，结果 68 个选项的 `effects` 是裸的 `Effect`，一结算就 TypeError。已加 `dream.effects_of()` 归一——新增选项时靠它兜底，但最好还是写对：`(Effect(...),)` 才有逗号。
2. **`Decimal('0.00')` 是 falsy。** `row.get("attitude") or 2.5` 会把"态度见底"静默读成中点。已修，改 `_state_row` 时注意。
3. **中文数字**：19 是"十九"不是"九十"；百位在场时 119 要写"一百一十九"。
4. **Ollama 结构化输出必须 `think=False`**，否则单轮超 90 秒且内容为空。
5. **Vite dev server 会崩于 EBUSY**：编辑工具在 `src/` 下留的临时目录被 fs watcher 拿到锁。已在 `vite.config.ts` 的 `server.watch.ignored` 里挡住。
6. **`check_vocabulary.py` 在输出被重定向时走 GBK 会崩在勾号上**，已加 `sys.stdout.reconfigure`。
7. **前端 `mentionIndex` 已被 @ 候选菜单占用**（键盘游标）。提及判断的变量名叫 `mentionRoster`，别混。

### 用脚本生成源码时（对 AI 助手）

用 JS 模板字符串生成 Python/TS 源码时：换行转义会被解释成真换行、**反引号会截断模板**、美元符号加花括号会插值。**这个项目里因此出过三次语法错误。**

可靠做法：正文里先用占位符，写完再统一替换（本文档就是这么生成的）。

### 内容数据时

8. **分段锚句必须出现在正文里。** 一开始拿回目里的话当锚句（协理宁国府、焚稿、出闺成大礼），那些词正文里根本没有，导致 14 章里 6 章切出空段。新增章时：锚句要实测能在正文里命中，且位置递增。
9. **节点顺序必须与正文顺序一致。** "探春理家"里宝钗补台那段实际早于探春提议；"焚稿·成婚"里出闺成大礼早于焚稿。两处已各并掉一个节点。
10. **问候提示词原先没有处境。** 只有人设与词表，模型无从分辨场合，入席离席会说成一样的话。已把在场人物、时间、心境的、来客公开信息、房里的话补进两套问候模板。

---

## 十六、二次开发的常见改动点

### 加一位人物

1. 素材 PNG 放进 `素材/红楼梦/<姓名>/`，跑 `python frontend/scripts/build_character_assets.py` 生成 webp。
2. 在 `frontend/src/data/characterStates.ts` 加一条 `makeCharacter(...)`，含十个左右的立绘状态与各自的情绪/动作词表。
3. 在 `agent/persona/supporting_cast.py` 加一个 `SupportingSpec`，`emotions` / `actions` **必须与上一步完全一致**。
4. `python -m agent.check_vocabulary` 应报 0 不一致。
5. 若要让他出现在某些房间，改 `agent/rooms.py` 的 `ROOMS`。

### 加一间房

1. `frontend/public/assets/buildings/` 放背景图。
2. `frontend/src/data.ts` 加一条（含 `hotspot` 坐标）——**用 `?calibrate=1` 标定，别手估**。
3. `agent/rooms.py` 的 `ROOMS` 加同名条目（**键是中文房间名**，必须与 `data.ts` 一致）。

### 加一条房间小关目

在 `agent/story.py` 的 `VIGNETTES` 里追加。`quote` 必须**在原文里实际存在**——用 `text_source.combined_text()` 核一遍。

### 加一章入梦

在 `agent/dream.py` 的 `CHAPTERS` 里追加。注意：

- `numbers` 是回次元组（可跨回）；
- 每个 `Node.marker` 必须能在正文里命中，且**依次递增**（写完跑一次 `plan()`，看有没有长度过短的段）；
- `Option.effects` 用 `(Effect(...), Effect(...))`，**单后果也要写逗号**。

### 调整节奏（延迟）

CPU 推理单轮 24～93 秒，这是硬成本。三个开关：

| 开关 | 位置 | 效果 |
| --- | --- | --- |
| `MAX_RESPONDERS` | `frontend/src/services/mockDialogue.ts` | 房间一轮最多几人开口（当前 3） |
| `picked[:2]` | `agent/dream_service.py` 的 `_responders()` | 入梦每次抉择最多几人表态 |
| `LLM_NUM_PREDICT` | `.env` | 单轮输出长度上限 |

问候（进院/入席/离席）只要约 22 秒，比正式回话便宜得多。

---

## 十七、已知限制（刻意的取舍，不是 bug）

- **延迟**：CPU 推理，单轮 24～93 秒；入梦一章 8～12 分钟。
- **4B 模型在原著细节上会出错**：薛宝钗两次把金锁说成"疯女子/父亲薛蟠"所赠（原著是癞头和尚）。提示词层面修不动。
- **同一轮内互不可见**：后开口的人看不到同轮前面人的答复——为了**杜绝逐字复述**（实测有效）。代价是他们不会当场互相接话。若要接话，需改 `_drop_current_round`。
- **配角没有私有记忆**：跨会话只认房间公开记录与公开档案。
- **长期记忆压缩仍是规则抽槽加去重**，未接模型摘要。
- **房间主持人与情绪衰减未做**：这一轮谁开口由前端 `planRound` 随机决定。
- **其余 103 回原著未清洗**（入梦用不到）。
- **Milvus 里 `chapter_no` 与 `chapter_title` 有对不齐的历史数据**（导入时留下，界面上的回次与标题可能不一致）。

---

## 十八、仓库与版本

- 分支 `main`，远端 `yun469736-debug/embedding`。
- 回退点：**`v0.3.0`**（可玩版本，含本文档描述的全部功能）。
- `.gitignore` 已挡：`.env`、`node_modules`、`dist`、模型权重、被 webp 取代的旧立绘目录。
- 素材源图在 `素材/红楼梦/`（约 284MB，已入库），是 `build_character_assets.py` 的输入，也是 `characterStates.ts` 里 `sourceFile` 的指向——**不要删**。

---

## 十九、相关文档

| 文件 | 内容 |
| --- | --- |
| `LIN_DAIYU_AGENT_SPEC.md` | 最初的设计规格（**最高约束来源**，尤其"原著不可篡改"那条） |
| `LIN_DAIYU_AGENT_ACCEPTANCE.md` | 验收清单、自检命令、逐项验证记录 |
| `agent/README.md` | 后端模块、数据表、接口、事件协议的技术说明 |
| `FRONTEND_DEVELOPMENT.md` | 前端开发说明 |
| `ARCHITECTURE.md` | 本文档 |

