# -*- coding: utf-8 -*-
"""按需检索《红楼梦》原文片段，并整理为可展开的"原著依据"。

只在涉及原著事实、人物关系、往事与命运时才检索；日常闲谈、情绪回应与现实任务跳过检索。
检索采用"稠密向量 + BM25 稀疏向量 + RRF 融合"的混合检索：
问"黛玉葬花是哪一回"这类问题，关键词命中的回目能稳定排在前面，
不至于被语义相近但并非所问的章节挤掉。
检索置信度不足时如实返回低分，交由人物坦率保留，不用猜测冒充原著事实。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from agent.config import settings
from agent.text_source import normalize as normalize_text

logger = logging.getLogger(__name__)

# 需要查证原著的人物、地点、关目与器物
ENTITY_KEYWORDS = (
    "宝玉", "黛玉", "宝钗", "湘云", "探春", "迎春", "惜春", "元春", "李纨", "妙玉",
    "可卿", "凤姐", "王熙凤", "贾母", "贾政", "贾赦", "贾琏", "贾珍", "贾蓉", "贾环",
    "袭人", "晴雯", "紫鹃", "平儿", "香菱", "鸳鸯", "金钏", "司棋", "雪雁", "莺儿",
    "刘姥姥", "薛蟠", "贾雨村", "甄士隐", "林如海", "贾敏", "尤二姐", "尤三姐",
    "警幻", "一僧一道", "茫茫大士", "渺渺真人", "甄宝玉",
)
PLACE_KEYWORDS = (
    "大观园", "潇湘馆", "怡红院", "蘅芜苑", "稻香村", "秋爽斋", "栊翠庵", "暖香坞",
    "荣国府", "宁国府", "荣禧堂", "太虚幻境", "沁芳", "凹晶馆", "凸碧堂", "梨香院",
    "省亲别墅", "天香楼", "铁槛寺", "馒头庵",
)
PLOT_KEYWORDS = (
    "葬花", "还泪", "木石前盟", "金玉良缘", "通灵宝玉", "金锁", "判词", "红楼梦曲",
    "好了歌", "金陵十二钗", "抄检大观园", "省亲", "元妃", "诗社", "菊花诗", "柳絮词",
    "桃花社", "焚稿", "断痴情", "泪尽", "夭亡", "出家", "白雪红梅", "琉璃世界",
    "护官符", "葫芦僧", "海棠社", "螃蟹咏", "芙蓉女儿诔", "五美吟", "题帕三绝",
    "情榜", "千红一哭", "万艳同悲", "离恨天", "灌愁海", "绛珠", "神瑛",
)
# 明确指向原著的问法：单独出现即可触发检索
STRONG_PATTERNS = (
    "原著", "原文", "哪一回", "第几回", "回目", "判词", "身世", "结局",
    "前世", "来历", "典故", "出处", "命运", "金陵十二钗", "红楼梦曲",
)

# 泛问句：只有在同时带有红楼语境时才触发，避免现实事务被误检索
WEAK_PATTERNS = (
    "书里", "书外", "后来", "什么来头", "怎么回事", "亲戚", "什么关系",
    "为什么", "怎么会", "当年", "从前", "小时候", "最后",
)
BOOK_CONTEXT = ("红楼梦", "红楼", "大观园", "贾府", "荣国府", "宁国府", "园中", "书中", "书里", "石头记")

MIN_QUOTE_CHARS = 120
MAX_QUOTE_CHARS = 84
OUTPUT_FIELDS = ("id", "chapter_no", "chapter_title", "chunk_no", "content")


@dataclass
class Evidence:
    """一条原著依据。"""

    id: str
    chapter: int
    title: str
    quote: str
    score: float
    rank_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "chapter": self.chapter,
            "title": self.title,
            "quote": self.quote,
            "score": round(float(self.score), 4),
        }

    def to_prompt_line(self) -> str:
        return f"【第{self.chapter}回 {self.title}】（相关度 {self.score:.2f}）\n{self.quote}"


_CLIENT_CACHE: dict[str, Any] = {}


def _milvus_client():
    from pymilvus import MilvusClient

    client = _CLIENT_CACHE.get("milvus")
    if client is None:
        client = MilvusClient(uri=settings.milvus_uri, token=settings.milvus_token, timeout=30)
        _CLIENT_CACHE["milvus"] = client
    return client


def _ollama_client():
    import ollama

    client = _CLIENT_CACHE.get("ollama")
    if client is None:
        client = ollama.Client(host=settings.ollama_host, trust_env=False, timeout=180)
        _CLIENT_CACHE["ollama"] = client
    return client


def should_retrieve(text: str) -> bool:
    """判断本轮是否需要查证原著。

    人物、地点、关目一旦出现即检索；明确问原著的问法也检索；
    "为什么""后来"这类泛问句只有在同时提到红楼语境时才检索，
    以免现代事务、情绪闲聊被无关片段拖慢并带偏。
    """
    if not text:
        return False
    if any(keyword in text for keyword in ENTITY_KEYWORDS):
        return True
    if any(keyword in text for keyword in PLACE_KEYWORDS):
        return True
    if any(keyword in text for keyword in PLOT_KEYWORDS):
        return True
    if any(keyword in text for keyword in STRONG_PATTERNS):
        return True
    if any(keyword in text for keyword in BOOK_CONTEXT):
        return True
    return False


def _clip(content: str) -> str:
    """裁短检索片段。

    Milvus 里的分片与本地的《红楼梦》.txt 同源，都带着 OCR 留下的引号错位、
    书名号转义与逐字乱码。界面上的"原著依据"直接展示这段文字，
    所以这里过一遍 text_source.normalize()——不必重新导入语料就能修好显示。
    """
    text = " ".join((content or "").split())
    text = normalize_text(text)
    if len(text) <= MAX_QUOTE_CHARS:
        return text
    return text[:MAX_QUOTE_CHARS] + "……"


def _book_filter() -> str:
    return f'book_name == "{settings.rag_book}"'


def _dense_hits(client, vector: list[float], limit: int) -> list[dict[str, Any]]:
    results = client.search(
        collection_name=settings.milvus_collection,
        data=[vector],
        anns_field="embedding",
        search_params={"metric_type": "COSINE", "params": {"ef": 64}},
        filter=_book_filter(),
        limit=limit,
        output_fields=list(OUTPUT_FIELDS),
    )
    return list(results[0]) if results else []


def _hybrid_hits(client, query: str, vector: list[float], limit: int) -> list[dict[str, Any]]:
    """稠密 + BM25 稀疏的 RRF 混合检索，提升关键词精确命中。"""
    from pymilvus import AnnSearchRequest, Function, FunctionType

    dense = AnnSearchRequest(
        data=[vector],
        anns_field="embedding",
        param={"metric_type": "COSINE", "params": {"ef": 64}},
        limit=max(limit, 10),
        expr=_book_filter(),
    )
    sparse = AnnSearchRequest(
        data=[query],
        anns_field="sparse_vector",
        param={"metric_type": "BM25"},
        limit=max(limit, 10),
        expr=_book_filter(),
    )
    ranker = Function(
        name="rrf",
        input_field_names=[],
        function_type=FunctionType.RERANK,
        params={"reranker": "rrf", "k": 60},
    )
    results = client.hybrid_search(
        collection_name=settings.milvus_collection,
        reqs=[dense, sparse],
        ranker=ranker,
        limit=limit,
        output_fields=list(OUTPUT_FIELDS),
    )
    return list(results[0]) if results else []


def retrieve_evidence(query: str, top_k: int | None = None) -> list[Evidence]:
    """检索原著片段；任何依赖不可用时返回空列表，绝不抛出到对话主流程。"""
    limit = top_k or settings.rag_top_k
    try:
        vector = _ollama_client().embed(model=settings.embed_model, input=[query]).embeddings[0]
    except Exception as exc:  # noqa: BLE001 - 依赖不可用需降级而非中断
        logger.warning("嵌入失败，跳过原著检索：%s", exc)
        return []

    try:
        client = _milvus_client()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Milvus 不可用，跳过原著检索：%s", exc)
        return []

    # 稠密检索用于相关度评分与兜底
    try:
        dense = _dense_hits(client, vector, max(limit, 10))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Milvus 稠密检索失败，跳过原著检索：%s", exc)
        return []

    dense_scores: dict[str, float] = {}
    for hit in dense:
        entity = hit.get("entity") or {}
        key = str(entity.get("id") or "")
        if key:
            dense_scores[key] = float(hit.get("distance", 0.0))

    # 混合检索用于排序；失败则退回稠密结果
    try:
        hits = _hybrid_hits(client, query, vector, limit)
        if not hits:
            hits = dense[:limit]
    except Exception as exc:  # noqa: BLE001
        logger.warning("混合检索失败，退回稠密检索：%s", exc)
        hits = dense[:limit]

    evidence: list[Evidence] = []
    seen: set[str] = set()
    for hit in hits:
        entity = hit.get("entity") or {}
        key = str(entity.get("id") or "")
        if key and key in seen:
            continue
        content = entity.get("content") or ""
        if len(content.strip()) < 20:
            continue
        # 混合检索的 distance 是 RRF 融合分，不能当相关度用；优先取稠密余弦相似度
        score = dense_scores.get(key, float(hit.get("distance", 0.0)))
        if key and key not in dense_scores:
            score = max(0.0, min(1.0, float(hit.get("distance", 0.0))))
        if score < 0.2 and key in dense_scores:
            continue
        seen.add(key)
        evidence.append(
            Evidence(
                id=key,
                chapter=int(entity.get("chapter_no") or 0),
                title=str(entity.get("chapter_title") or "").strip(),
                quote=_clip(content),
                score=score,
                rank_score=float(hit.get("distance", 0.0)),
            )
        )
    return evidence


def retrieve_for_answer(query: str, top_k: int | None = None) -> tuple[list[Evidence], float]:
    """对话主链路使用：混合召回 + 原著专名精排，返回依据与总体置信度。"""
    limit = top_k or settings.rag_top_k
    candidates = retrieve_evidence(query, top_k=max(limit * 3, 9))
    if not candidates:
        return [], 0.0

    terms = query_terms(query)
    if terms:
        candidates.sort(
            key=lambda item: (item.score + _keyword_bonus(terms, item.title, item.quote), item.score),
            reverse=True,
        )
    selected = candidates[:limit]
    return selected, confidence_of(selected)


def query_terms(query: str) -> list[str]:
    """从问句里取出原著专名与关目词，用于回目精排。"""
    terms: list[str] = []
    for keyword in (*PLOT_KEYWORDS, *ENTITY_KEYWORDS, *PLACE_KEYWORDS):
        if keyword in query and keyword not in terms:
            terms.append(keyword)
    return terms


def _keyword_bonus(terms: list[str], title: str, content: str) -> float:
    """回目标题命中权重最高；正文命中次之。"""
    bonus = 0.0
    for term in terms:
        if term in title:
            bonus += 0.3
        elif term in content:
            bonus += 0.14
    return bonus


def confidence_of(evidence: list[Evidence]) -> float:
    if not evidence:
        return 0.0
    top = max(item.score for item in evidence)
    return max(0.0, min(1.0, top))
