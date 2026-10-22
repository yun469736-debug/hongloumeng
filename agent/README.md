# 红楼梦人物 Agent 后端

本地自托管的人物 Agent 服务：FastAPI + Ollama(`qwen3.5:4b` / `bge-m3`) + Milvus + MySQL，
按 `LIN_DAIYU_AGENT_SPEC.md` 与 `FRONTEND_DEVELOPMENT.md` 的逐句 NDJSON 协议输出。

## 角色分工

| | 林黛玉（主角） | 其余十一位（配角） |
| --- | --- | --- |
| 词表 | 自己的 10 张立绘 | **各自**的立绘（贾宝玉、薛宝钗、史湘云、贾探春、贾迎春、贾惜春、贾元春、李纨、妙玉、秦可卿） |
| 关系系统 | 七阶段 + 隐藏好感度 | 无（`has_relationship=false`，不发 `stage` 事件） |
| 记忆 | 三层记忆 + 私有长期记忆 + 定向遗忘 | 无私有记忆；只读房间公开记录与公开档案 |
| 原著检索 | 按需 + 依据 + 置信度 | 同一套检索器，同样带依据 |
| 入席问候 | 有 | 无（等来客先开口） |
| 人格守则 | 全部 | **全部沿用**（书中人认知、全时期融合、一梦归来、拒绝改扮身份、浅白古雅、称呼守卫、反重复），只砍掉爱情线 |

## 目录

```text
agent/
  config.py            全部配置来自环境变量（根目录 .env）
  schemas.py           请求模型与事件构造（DialogueRequest.speaker 声明本轮由谁应答）
  service.py           编排：状态装配 → 检索 → 生成 → 逐句下发 → 结算
  safety.py            现实危机识别（不发独立安全卡，只转成提示词守则）
  main.py              FastAPI 入口、健康检查、迁移、重置
  check_vocabulary.py  把每个人的词表与前端 108 张立绘对拍
  smoke_test.py        冒烟验收脚本（主角 + 配角）
  persona/
    base.py             Persona 基类：角色标记、词表归一、按角色生成 JSON Schema
    lin_daiyu.py        主角配置（七阶段、私有记忆、入席问候）
    supporting.py       配角的共享提示词模板与构建器
    supporting_cast.py  十一位配角的人设与词表
  rag/retriever.py     按需检索：规则路由 + 混合召回 + 原著专名精排
  llm/providers.py     模型提供器：Ollama（默认）/ DeepSeek（门控）
  llm/generator.py     提示词装配、结构化输出、流式逐句解析与词表归一
  db/                  connection / schema（含 hlm_* 迁移）/ repository
  memory/manager.py    公开档案抽取、私有候选记忆、压缩去重、定向遗忘
  affection/engine.py  隐藏好感度、七阶段、滞回缓冲、慢热门槛（仅主角）
  rooms.py             十四间房的在场名册与播种抽取（谁能出现在哪、以什么权重）
  story.py             41 条房间小关目（原著片段、回次、摘句、首触发写入的人物状态）
```

## 模型来源：本地 Ollama 与 DeepSeek 的优先级

前端顶栏那块状态条点开可以填自己的 DeepSeek 密钥（见 `frontend/src/services/agentClient.ts`）。
规则只有三条：

1. **没填密钥 → 本地 Ollama**（也就是 `.env` 的默认配置）。
2. **填了密钥 → 先校验，通过就走 DeepSeek**。密钥随 `X-DeepSeek-Key` 请求头逐次传入，
   不存在服务端、不落盘、不进数据库。
3. **密钥有误 → 当场发一条错误事件说明原因，然后退回本地模型继续把话说完**，对话不中断。

安全上的几条硬约定：

- `DeepSeekProvider.api_key` 是 `repr=False` 的，异常回溯与日志里都不会带出密钥。
- 校验结论按密钥的 SHA-256 前 16 位缓存 10 分钟——**缓存里只有指纹，没有密钥**。
- 校验用 `models.list()` 做只读探测，不消耗生成额度，也能把 401 与网络故障分辨开。
- 前端只在**校验通过时**才把密钥存进 localStorage；否则不保存，免得每一轮都弹一次密钥错误。

## 在场人物与房间小关目

- **名册归后端**：前端只持匾额、背景与热区；“此刻这间房里都有谁”由 `GET /api/room` 按
  `用户＋日＋时段＋场景` 播种决定，同一时段内反复进出结果完全一致，结束会谈推进时段后才换人。
- **权重**：常驻者 6、访客 2；贾元春 ×0.3、秦可卿 ×0.3；名册外的人永不出场。
- **林黛玉单独一条**：按房间给定概率先掷一次（潇湘馆 1.00——她的家，必在；
  怡红院/沁芳亭/沁芳桥 0.80；其余十间 0.50），十四间平均正好 60.0%。她中了就占一席，不参与权重抽签。
- **名册外的人物**（贾母、平儿、贾政、紫鹃、袭人、晴雯、莺儿、龄官等）一律“默认外出”：
  可以被人提起、可以加引号转述，但不出场、不开口。
- **小关目**：进门约 35% 引出“没经历过的”一桩，首触发即写 `hlm_character_state`
  并在 `hlm_events` 记一条 `关目:房间·标题`；谈话中另有较低频率回望“已经历过的”，
  改用追忆口气。涉及人物一个都不在场时不触发。

## 房间记录、清屏与"提到谁"

- **房间记录按房隔离**：`hlm_chat.scene` 标出每条公开发言发生在哪间房，
  `_room_snapshot()` 只读本房。换院子之后，上一间房说过的话不会再被当成"房里说过的话"。
  `/api/history` 不带 scene，仍是全量回看；迁移前的老记录 `scene` 为空，只在那里出现。
- **换院子/离开即清屏**：前端 `resetDialogue()` 把这一间的对话从界面上收起，
  再进来由本房名册首位重新问候。只是不显示——后端仍按房记着，人物照样记得。
- **提到在场的人 → 大概率接话**：前端 `planRound` 决定谁开口（`@` 点名必答；
  用名字或别号提到则 90% 接话）。别名取自 `GET /api/characters`，不在前端另存一份。
- **提到不在场的人 → 只被谈论，不自己开口**：后端 `_mentioned_note()` 扫出
  "被提到但不在席"的人写进本轮提示；配合提示词里那条"除在席诸位之外，府中其余人
  此刻都不在这间屋子里"，人物会以第三人称去谈，并自然说出此人不在。

## 数据表

| 表 | 归属 | 说明 |
| --- | --- | --- |
| `hlm_users` | 共享 | 用户与全局游戏时钟 |
| `hlm_chat` | 共享 | 房间公开发言记录，所有人的台词都在这里，任何真实角色都能读 |
| `hlm_user_profile` | 共享 | 来客自报的**公开**身份事实（姓名、姓氏、称呼、性别、身份、所在地、生日） |
| `hlm_character_state` | 共享 | 十二位人物的**心绪 / 对你的态度（0～5）/ 最近一件心事**；只注入提示词，界面完全不露 |
| `hlm_memory_long` / `hlm_memory_candidate` | 主角专属 | 私有长期记忆与候选记忆（带 `character_id`） |
| `hlm_affection` / `hlm_events` | 主角专属 | 隐藏好感度与关系事件流水 |

旧版 `daiyu_*` 表在迁移时会自动整体改名到 `hlm_*`（幂等，数据保留）。

## 环境变量

复制 `agent/.env.example` 到项目根目录 `.env`（该文件已被 `.gitignore` 覆盖）。

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `LLM_PROVIDER` | `ollama` | 默认自托管；改为 `deepseek` 才启用 DeepSeek |
| `OLLAMA_MODEL` | `qwen3.5:4b` | 本机对话模型 |
| `LLM_THINK` | `false` | 必须关闭，否则单轮可超 90 秒 |
| `LLM_NUM_CTX` | `4096` | 上下文上限；提示词约 1900 token，低于 2048 会被截断 |
| `RAG_TOP_K` | `4` | 检索片段数 |
| `SHORT_TERM_TURNS` | `6` | 房间记录保留的最近条数 |
| `VIGNETTE_CHANCE` | `0.35` | 进门时引出房间小关目的概率（谈话中的回望另按 0.4 倍计） |
| `MYSQL_*` | — | 连接信息只写在本地 `.env` |

## 启动

两个都要起。前后端分开的两个终端：

```powershell
# 终端一：后端（FastAPI，127.0.0.1:8000）
python -m uvicorn agent.main:app --host 127.0.0.1 --port 8000

# 终端二：前端（Vite，http://localhost:5173，/api 自动代理到 8000）
cd frontend
npm.cmd run dev
```

打开 <http://localhost:5173> 即可。依赖：Ollama 里要有 `qwen3.5:4b` 与 `bge-m3`；
MySQL 建库由 `agent/db/schema.py` 的 `migrate()` 在启动时自动完成。
地图要重标时用 <http://localhost:5173/?calibrate=1>。

## 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | 逐项报告 Ollama / Milvus / MySQL 可用性与人物名册 |
| GET | `/api/state` | 关系阶段与游戏内时间（主角返回阶段，配角返回空 stage 与 `has_relationship=false`） |
| GET | `/api/room` | 这间房此刻有谁：`cast` / `greeter` / `residents` / `guests` / `mention_only` / `daiyu_present` |
| GET | `/api/characters` | 十二位人物的 `name` / `courtesy` / `aliases` / `role`，供前端判断"来客提到了谁" |
| POST | `/api/provider/check` | 校验前端填的 DeepSeek 密钥；空密钥不算错误，只表示用本地 |
| POST | `/api/dialogue` | 一次发言 → NDJSON 逐句事件流，须带 `speaker`；可选 `X-DeepSeek-Key` 头 |
| POST | `/api/greeting` | 入席问候，由 `present_characters` 首位开口（黛玉在场即黛玉，否则本房常驻者） |
| POST | `/api/session/end` | 会谈结算：压缩主角候选记忆并推进一个时段 |
| GET | `/api/history` | 聊天记录回看（长期记忆与公开档案不提供读取入口） |
| POST | `/api/reset` | 完整世界重置，必须带 `{"confirm": true}` |

## 事件协议

```json
{"type":"speaker_start","speaker":"薛宝钗"}
{"type":"sentence","speaker":"薛宝钗","emotion":"冷静","action":"端坐","intensity":0.5,
 "stageDirection":"","text":"……","kind":"原著事实","confidence":0.64,
 "evidence":[{"chapter":8,"title":"……","quote":"……","score":0.62}],"source":"agent"}
{"type":"speaker_end","speaker":"薛宝钗"}
{"type":"stage","speaker":"林黛玉","stage":"留意","previous":"初识"}
{"type":"error","message":"……","detail":"……"}
{"type":"round_end","settlement":{"speaker":"薛宝钗","role":"supporting","retrieved":4}}
```

- `emotion` / `action` 由 Ollama 结构化输出（JSON Schema 枚举）锁定在**该角色自己**的词表内，
  越界值再由 `Persona.normalize_*` 归一；`agent/check_vocabulary.py` 可随时与前端立绘对拍。
- `stage` 事件只有主角会发；配角不参与好感结算。
- 模型、Milvus 或 MySQL 任一项不可用时只发 `error` 事件，**不伪造角色回复、不改记忆与好感**。
- 现实危机**不再发独立安全卡**；后端只识别危机并把它转成本轮提示词守则（先温言安抚、不责备、
  不浪漫化悲剧、不给方法）。

## 生成方式

一次调用同时产出台词（主角另带关系暗记），避免第二次模型往返：

1. 按需检索（仅在涉及原著事实/人物关系/往事/命运时触发）
2. `ollama.chat(think=False, num_ctx, num_predict, format=<该角色的 JSON Schema>, keep_alive=30m)`
3. 流式增量截取 `sentences` 数组里已完成的句子对象 → 立刻下发 `sentence` 事件
4. 房间记录（带说话人姓名，自己说过的标注"（你方才说的）"）与公开档案统一放进系统提示的
   本轮处境段，用户当前这句才是 `user` 轮次——这样配角既能听见主角说了什么，又不会冒认别人的话
5. 提示词把「静态人格段」放最前、「本轮处境段」放最后，同一角色的静态前缀逐字节一致，
   Ollama 可复用 KV 缓存

## 自检

```powershell
python -m agent.check_vocabulary   # 每个人的词表 vs 前端 108 张立绘（应 0 不一致）
python agent/smoke_test.py --quick # 健康检查 + 前两例
python agent/smoke_test.py         # 全量用例（主角与配角）
```

## 已知限制

- 本机为 CPU 推理，单轮约 24～93 秒；三人串行应答一轮最长可到三两分钟。
  房间可站 5 人（`Room.capacity`），但一轮真正开口的上限是 3（前端 `MAX_RESPONDERS`）——这是唯一的成本开关。
- 4B 模型的细节仍可能出偏差（回目、人情往来的分寸），建议按固定测试集人工调参。
- 配角不持有私有记忆，跨会话只认房间公开记录与公开档案，不会像主角那样记得你没说出口的事。
- 长期记忆的压缩仍是规则抽槽 + 去重，未接入模型摘要。
- 多人房间主持器（后端统一选下一位发言者）与情绪衰减留待下一迭代；
  "这间房有谁"已由后端 `GET /api/room` 播种决定，"这一轮谁开口"仍由前端 `selectResponders` 随机（1～3 人，`@` 点名者必答）。
