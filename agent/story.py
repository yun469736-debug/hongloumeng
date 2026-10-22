# -*- coding: utf-8 -*-
"""房间小关目：每间房若干原著片段，进门时按概率被引出。

设计（见 LIN_DAIYU_AGENT_ACCEPTANCE.md 第六节）：
- 只在关目涉及的人物至少一人在场时才可能触发；
- 进门约 VIGNETTE_CHANCE 概率触发，同一次进门最多一条；
- 首次触发写 hlm_character_state（心绪 / 对你的态度 / 最近一件心事），
  并往 hlm_events 记一条已触发；之后再进同一间房，改用追忆口气说起；
- 回次与原文摘句逐条核对过工作区的《红楼梦》电子本，
  因此回目文字与该语料一致（可对照界面上的"原著依据"）。
"""

from __future__ import annotations

import os
import random
from dataclasses import dataclass, field


def _chance() -> float:
    try:
        value = float(os.getenv("VIGNETTE_CHANCE", "0.35"))
    except ValueError:
        return 0.35
    return min(1.0, max(0.0, value))


# 进门触发关目的概率，可用环境变量 VIGNETTE_CHANCE 覆盖
VIGNETTE_CHANCE = _chance()


@dataclass(frozen=True)
class Effect:
    """首触发时写进 hlm_character_state 的改动。"""

    character: str
    mood: str = ""
    secret: str = ""
    attitude: float = 0.0


@dataclass(frozen=True)
class Vignette:
    room: str
    title: str
    chapter: int
    chapter_title: str
    quote: str
    speakers: tuple[str, ...]
    summary: str
    recall: str
    effects: tuple[Effect, ...] = field(default_factory=tuple)

    @property
    def key(self) -> str:
        return self.room + "·" + self.title


VIGNETTES: tuple[Vignette, ...] = (
    # ------------------------------------------------------------ 潇湘馆
    Vignette(
        room="潇湘馆", title="春困发幽情", chapter=26,
        chapter_title="蜂腰桥设言传心事 潇湘馆春困发幽情",
        quote="每日家情思睡昏昏", speakers=("林黛玉", "贾宝玉"),
        summary="午后你隔窗听见黛玉在屋里长叹了一声：“每日家情思睡昏昏。”她自觉忘情，红了脸翻身装睡。",
        recall="那日午后她忘情叹出的一句，被你听去了，如今提起她仍有些不好意思。",
        effects=(Effect("林黛玉", mood="情思昏昏", secret="午睡时说漏了一句心里话，被人听去了"),),
    ),
    Vignette(
        room="潇湘馆", title="题帕三绝", chapter=34,
        chapter_title="情中情因情感妹妹 错里错以错劝哥哥",
        quote="忽然好好的送两块旧帕子来", speakers=("林黛玉", "贾宝玉"),
        summary="宝玉挨打之后，悄悄托人送了两块旧帕子来。黛玉领会其中的意思，一时五内沸然，研墨蘸笔在帕上题诗。",
        recall="那两块旧帕子上的题诗，她始终收着，不肯给人看。",
        effects=(Effect("林黛玉", mood="神魂驰荡", secret="旧帕上题了诗，藏起来不敢给人看", attitude=1.0),),
    ),
    Vignette(
        room="潇湘馆", title="秋窗风雨夕", chapter=45,
        chapter_title="金兰契互剖金兰语 风雨夕闷制风雨词",
        quote="秋花惨淡秋草黄，耿耿秋灯秋夜长", speakers=("林黛玉", "贾宝玉"),
        summary="秋夜风雨，黛玉拟《春江花月夜》的格调作了一首《秋窗风雨夕》，灯下写罢，只觉秋意逼人。",
        recall="那首《秋窗风雨夕》是她在秋夜风雨里写下的，词句至今还在。",
        effects=(Effect("林黛玉", mood="秋夜凄凉", secret="灯下写了《秋窗风雨夕》，越写越冷"),),
    ),
    # ------------------------------------------------------------ 怡红院
    Vignette(
        room="怡红院", title="撕扇作千金一笑", chapter=31,
        chapter_title="撕扇子作千金一笑 因麒麟伏白首双星",
        quote="不防又把扇子失了手跌在地下，将股子跌折", speakers=("贾宝玉",),
        summary="晴雯失手跌折了扇股，宝玉说了两句重话，两人顶撞起来，一日闷闷不乐。",
        recall="那回为一把扇子跟晴雯动了气，宝玉心里一直过不去。",
        effects=(Effect("贾宝玉", mood="闷闷不乐", secret="为一把扇子跟晴雯动了气，心里过不去"),),
    ),
    Vignette(
        room="怡红院", title="病补雀金裘", chapter=52,
        chapter_title="俏平儿情掩虾须镯 勇晴雯病补雀金裘",
        quote="这叫作雀金呢，这是哦斯国拿孔雀毛拈了线织的", speakers=("贾宝玉",),
        summary="贾母把一件孔雀毛织的氅衣给了宝玉，后襟上烧了个洞，晴雯病中挣扎着替他补好了。",
        recall="那件孔雀毛的氅衣，是晴雯在病里一针一线补上的。",
        effects=(Effect("贾宝玉", mood="感念不舍", secret="那件氅衣上的洞，是晴雯病里补的"),),
    ),
    Vignette(
        room="怡红院", title="群芳开夜宴", chapter=63,
        chapter_title="寿怡红群芳开夜宴 死金丹独艳理亲丧",
        quote="咱们占花名儿好", speakers=("贾宝玉", "薛宝钗", "林黛玉", "贾探春", "李纨", "史湘云"),
        summary="夜里众人凑在一处替宝玉做生日，抽签占花名，签上的句子一句句都应着各人的命。",
        recall="那夜占花名，签上的话谁也没说破，可谁心里都存着。",
        effects=(
            Effect("贾宝玉", mood="欢喜里发沉", secret="夜宴占花名，签上的话让人心里发沉", attitude=1.0),
            Effect("薛宝钗", mood="端静自持", secret="牡丹签上那句“任是无情也动人”，她不愿多想"),
        ),
    ),
    # ------------------------------------------------------------ 稻香村
    Vignette(
        room="稻香村", title="稻香老农", chapter=37,
        chapter_title="秋爽斋偶结海棠社 蘅芜苑夜拟菊花题",
        quote="我是定了‘稻香老农’，再无人占的", speakers=("李纨", "贾探春", "贾宝玉", "林黛玉"),
        summary="众人起诗社，先要改别号。李纨自定了“稻香老农”，又自荐掌坛。",
        recall="那诗社是她一手掌的坛，别号也是她自己定下的。",
        effects=(Effect("李纨", mood="从容里有兴致", secret="诗社的坛是她掌的，比谁都上心", attitude=1.0),),
    ),
    Vignette(
        room="稻香村", title="芦雪庵联句", chapter=50,
        chapter_title="芦雪庵争联即景诗 暖香坞雅制春灯谜",
        quote="一夜北风紧", speakers=("李纨", "史湘云", "薛宝钗", "林黛玉", "王熙凤"),
        summary="雪天联句，凤姐起了句粗话“一夜北风紧”，众人反说这句留了多少地步与后人。",
        recall="联句那日，凤丫头一句粗话倒成了起法，众人笑到一处。",
        effects=(Effect("李纨", mood="兴致颇高", secret="雪天联句，连凤丫头都凑了趣", attitude=0.5),),
    ),
    Vignette(
        room="稻香村", title="贾兰下场", chapter=119,
        chapter_title="中乡魁宝玉却尘缘 沐皇恩贾家延世泽",
        quote="你们爷儿两个都是初次下场", speakers=("李纨", "贾宝玉"),
        summary="宝玉与贾兰一同下场赴考，王夫人嘱咐了又嘱咐。李纨一生的指望，都落在兰儿身上。",
        recall="兰儿下场那一日，她半生的指望都在里头。",
        effects=(Effect("李纨", mood="含悲带慰", secret="兰儿下场去了，她这一辈子只剩这一件事", attitude=1.0),),
    ),
    # ------------------------------------------------------------ 沁芳亭
    Vignette(
        room="沁芳亭", title="滴翠亭扑蝶", chapter=27,
        chapter_title="滴翠亭杨妃戏彩蝶 埋香冢飞燕泣残红",
        quote="一直跟到池中滴翠亭上，香汗淋漓，娇喘细细", speakers=("薛宝钗",),
        summary="宝钗追一双玉色蝴蝶，一直跟到池中的滴翠亭上；亭里恰有人在说私话，她听见了，却没声张。",
        recall="滴翠亭外听见的那些话，她到底没跟人提过。",
        effects=(Effect("薛宝钗", mood="从容自持", secret="滴翠亭外听见的私话，她没声张"),),
    ),
    Vignette(
        room="沁芳亭", title="共读西厢", chapter=23,
        chapter_title="西厢记妙词通戏语 牡丹亭艳曲警芳心",
        quote="花落水流红，闲愁万种", speakers=("贾宝玉", "林黛玉"),
        summary="宝玉在沁芳闸桥边桃花树下读《西厢记》，黛玉来了，两人一处看。宝玉拿书里的话比他们，黛玉红了脸。后来她独自听见《牡丹亭》的曲子，心痛神痴。",
        recall="那日桃花树下同看《西厢》，他拿来比他们；后来她独自听曲，落了泪。",
        effects=(Effect("林黛玉", mood="心动又心惊", secret="他把《西厢》上的话拿来比我们", attitude=1.0),),
    ),
    # ------------------------------------------------------------ 蘅芜苑
    Vignette(
        room="蘅芜苑", title="夜拟菊花题", chapter=37,
        chapter_title="秋爽斋偶结海棠社 蘅芜苑夜拟菊花题",
        quote="以菊花为宾，以人为主，竟拟出几个题目来", speakers=("薛宝钗", "史湘云"),
        summary="夜里湘云张罗着要做菊花诗，宝钗替她把题目拟了出来：以菊花为宾，以人为主。",
        recall="菊花那些题目是宝钗替湘云拟的，湘云当时比她还急。",
        effects=(Effect("薛宝钗", mood="端静自持", secret="菊花题是她替湘云拟的，湘云比她还急", attitude=1.0),),
    ),
    Vignette(
        room="蘅芜苑", title="兰言解疑癖", chapter=42,
        chapter_title="蘅芜君兰言解疑癖 潇湘子雅谑补余香",
        quote="最怕见了些杂书，移了性情，就不可救了", speakers=("薛宝钗", "林黛玉"),
        summary="宝钗劝黛玉别尽看杂书，说“最怕见了些杂书，移了性情，就不可救了”。黛玉垂头吃茶，心里暗伏。",
        recall="她劝黛玉的那番话，黛玉是听进去了的。",
        effects=(Effect("薛宝钗", mood="端静自持", secret="劝黛玉的那番话，黛玉竟听进去了", attitude=1.0),),
    ),
    Vignette(
        room="蘅芜苑", title="小惠全大体", chapter=56,
        chapter_title="敏探春兴利除宿弊 时宝钗小惠全大体",
        quote="使之以权，动之以利，再无不尽职的了", speakers=("薛宝钗", "贾探春"),
        summary="探春理家要兴利剔弊，宝钗补了一句“使之以权，动之以利”，又把园中人的体面一并顾全。",
        recall="园子里分利那桩事，她几句就把众人的体面都顾全了。",
        effects=(Effect("薛宝钗", mood="持重周全", secret="园中分利那桩事，她本不该多嘴", attitude=1.0),),
    ),
    # ------------------------------------------------------------ 沁芳桥
    Vignette(
        room="沁芳桥", title="埋香冢葬花", chapter=27,
        chapter_title="滴翠亭杨妃戏彩蝶 埋香冢飞燕泣残红",
        quote="花谢花飞花满天，红消香断有谁怜", speakers=("林黛玉", "贾宝玉"),
        summary="宝玉兜了落花，一直奔到那日同黛玉葬桃花的去处，未转过山坡便听见呜咽之声，正是黛玉在哭吟《葬花吟》。",
        recall="花冢前那几句，她不知道宝玉听见了多少。",
        effects=(Effect("林黛玉", mood="伤感难禁", secret="花冢前吟的那几句，不知他听见了多少"),),
    ),
    Vignette(
        room="沁芳桥", title="重建桃花社", chapter=70,
        chapter_title="林黛玉重建桃花社 史湘云偶填柳絮词",
        quote="就把海棠社改作桃花社", speakers=("林黛玉", "史湘云"),
        summary="黛玉作了《桃花行》，湘云说如今万物逢春，正该把海棠社改作桃花社，众人便往稻香村议定。",
        recall="桃花社重起那回，她写了《桃花行》，只是人事已非。",
        effects=(Effect("林黛玉", mood="略振又怅然", secret="桃花行写完了，社也重起了，只是人事已非", attitude=1.0),),
    ),
    # ------------------------------------------------------------ 秋爽斋
    Vignette(
        room="秋爽斋", title="偶结海棠社", chapter=37,
        chapter_title="秋爽斋偶结海棠社 蘅芜苑夜拟菊花题",
        quote="可巧才是海棠诗开端，就叫个海棠社罢", speakers=("贾探春", "贾宝玉"),
        summary="探春一封帖子起意结社，众人聚在秋爽斋，因是海棠诗开端，便定名海棠社。",
        recall="海棠社是她起的头，园子里着实热闹了好些日子。",
        effects=(Effect("贾探春", mood="兴致勃勃", secret="诗社是她起的头，她比谁都得意", attitude=1.0),),
    ),
    Vignette(
        room="秋爽斋", title="兴利除宿弊", chapter=56,
        chapter_title="敏探春兴利除宿弊 时宝钗小惠全大体",
        quote="大家商议两件兴利剔弊的事", speakers=("贾探春", "李纨"),
        summary="探春代凤姐理事，提出兴利剔弊，把园中花木出息分派给老成管事的人。",
        recall="她替府里省的这点钱，长辈未必放在心上。",
        effects=(Effect("贾探春", mood="清醒自持", secret="她替府里省的这点钱，太太未必放在心上", attitude=1.0),),
    ),
    Vignette(
        room="秋爽斋", title="抄检大观园", chapter=74,
        chapter_title="惑奸谗抄检大观园 矢孤介杜绝宁国府",
        quote="王善保家的便请了凤姐一并入园", speakers=("贾探春", "王熙凤"),
        summary="王善保家的撺掇着抄检大观园，一路抄到秋爽斋。探春当众抗辩，说“必须先从家里自杀自灭起来，才能一败涂地”，并给了王善保家的一记耳光。",
        recall="抄检那晚她在秋爽斋当众抗辩，那一巴掌至今不悔。",
        effects=(
            Effect("贾探春", mood="气愤难平", secret="那一巴掌，她至今不后悔"),
            Effect("王熙凤", mood="骑虎难下", secret="抄检那桩事，她心里并不情愿，却拦不住"),
        ),
    ),
    # ------------------------------------------------------------ 缀锦楼
    Vignette(
        room="缀锦楼", title="不问累金凤", chapter=73,
        chapter_title="痴丫头误拾绣春囊 懦小姐不问累金凤",
        quote="那一个攒珠累丝金凤竟不知那里去了", speakers=("贾迎春",),
        summary="迎春的攒珠累丝金凤被奶妈拿去典了银子，丫鬟绣桔回了几次，迎春只说“不问”，宁可自己吃亏。",
        recall="金凤丢了那桩事，她到底是没问。",
        effects=(Effect("贾迎春", mood="隐忍退让", secret="攒珠累丝金凤丢了，她没敢问"),),
    ),
    Vignette(
        room="缀锦楼", title="迎春灯谜", chapter=22,
        chapter_title="听曲文宝玉悟禅机 制灯迷贾政悲谶语",
        quote="因何镇日纷纷乱，只为阴阳数不同", speakers=("贾迎春", "贾探春"),
        summary="元宵制灯谜，迎春的谜底是算盘。贾政看了，心里只觉这些谜语都不是福寿之兆。",
        recall="她那个算盘谜，长辈看了只说不好。",
        effects=(Effect("贾迎春", mood="淡淡怅然", secret="她那个算盘谜，到底不是吉兆"),),
    ),
    Vignette(
        room="缀锦楼", title="误嫁中山狼", chapter=79,
        chapter_title="薛文龙悔娶河东狮 贾迎春误嫁中山狼",
        quote="此人名唤孙绍祖", speakers=("贾迎春",),
        summary="贾赦把迎春许给了世交之孙孙绍祖，贾母心里不十分称意，却也拦不住。",
        recall="那门亲事，她连问一句都不敢。",
        effects=(Effect("贾迎春", mood="含愁隐忍", secret="许给孙家那门亲事，她连问一句都不敢"),),
    ),
    # ------------------------------------------------------------ 栊翠庵
    Vignette(
        room="栊翠庵", title="茶品梅花雪", chapter=41,
        chapter_title="栊翠庵茶品梅花雪 怡红院劫遇母蝗虫",
        quote="妙玉忙接了进去", speakers=("妙玉",),
        summary="贾母带刘姥姥一行到栊翠庵，妙玉接了进去。她用的是旧年蠲的雨水，给宝钗黛玉吃的又是五年前梅花上的雪水。",
        recall="那杯茶用的雪水，她攒了五年。",
        effects=(Effect("妙玉", mood="清冷自持", secret="那杯茶用的雪水，她攒了五年"),),
    ),
    Vignette(
        room="栊翠庵", title="乞红梅", chapter=50,
        chapter_title="芦雪庵争联即景诗 暖香坞雅制春灯谜",
        quote="我才看见栊翠庵的红梅有趣", speakers=("妙玉", "贾宝玉"),
        summary="联句罚宝玉去栊翠庵折一枝红梅，李纨说“可厌妙玉为人，我不理他”。宝玉去了，到底讨了来。",
        recall="那枝红梅，她本是不该给的。",
        effects=(Effect("妙玉", mood="含蓄欣然", secret="那枝红梅她本不该给，到底还是给了", attitude=1.0),),
    ),
    Vignette(
        room="栊翠庵", title="坐禅走火", chapter=87,
        chapter_title="感深秋抚琴悲往事 坐禅寂走火入邪魔",
        quote="可惜我生在这种人家不便出家", speakers=("妙玉", "贾惜春"),
        summary="妙玉坐禅时走火入魔。惜春听了，暗想“妙玉虽然洁净，毕竟尘缘未断”，自己倒生出了出家的念头。",
        recall="坐禅走火那夜的事，她从不与人提。",
        effects=(
            Effect("妙玉", mood="心绪不宁", secret="坐禅那夜魔障入心，她从不与人提"),
            Effect("贾惜春", mood="冷眼向佛", secret="她动过出家的念头，只是不便说"),
        ),
    ),
    # ------------------------------------------------------------ 贾母院
    Vignette(
        room="贾母院", title="两宴大观园", chapter=40,
        chapter_title="史太君两宴大观园 金鸳鸯三宣牙牌令",
        quote="老太太留下我，叫我也热闹一天去", speakers=("王熙凤", "李纨"),
        summary="刘姥姥二进荣国府，贾母留她住下，在大观园里两番设宴，凤姐与鸳鸯拿她取笑凑趣。",
        recall="刘姥姥那两日，是府里难得的痛快日子。",
        effects=(Effect("王熙凤", mood="凑趣热闹", secret="老太太那点体面，全靠人凑趣撑着", attitude=1.0),),
    ),
    Vignette(
        room="贾母院", title="效戏彩斑衣", chapter=54,
        chapter_title="史太君破陈腐旧套 王熙凤效戏彩斑衣",
        quote="斑衣戏彩，他们不能来戏彩引老祖宗笑一笑", speakers=("王熙凤",),
        summary="元宵夜宴，凤姐拿《二十四孝》上“斑衣戏彩”打趣自己，逗得贾母痛痛快快笑了一场。",
        recall="她逗老太太笑那一节，一半是为自己。",
        effects=(Effect("王熙凤", mood="强撑体面", secret="她逗老太太笑，一半是为自己"),),
    ),
    Vignette(
        room="贾母院", title="鸳鸯抗婚", chapter=46,
        chapter_title="尴尬人难免尴尬事 鸳鸯女誓绝鸳鸯偶",
        quote="老太太离了鸳鸯，饭也吃不下去的", speakers=("王熙凤",),
        summary="贾赦看上鸳鸯要讨去做妾，邢夫人来同凤姐商议。凤姐一句“老太太离了鸳鸯，饭也吃不下去的”，先把这桩尴尬事推了开去。",
        recall="鸳鸯那桩事，她一句话就推开了，可心里有数。",
        effects=(Effect("王熙凤", mood="筹谋自保", secret="鸳鸯那桩事，她一句话就推开了"),),
    ),
    # ------------------------------------------------------------ 王熙凤院
    Vignette(
        room="王熙凤院", title="毒设相思局", chapter=12,
        chapter_title="王熙凤毒设相思局 贾天祥正照风月鉴",
        quote="凤姐儿也假意殷勤，让茶让坐", speakers=("王熙凤",),
        summary="贾瑞起了邪心，凤姐假意殷勤，暗中设下相思局，几番作弄，终于要了他的命。",
        recall="贾瑞那桩事，是她做下的，她从不说起。",
        effects=(Effect("王熙凤", mood="阴狠自持", secret="贾瑞那桩事是她做下的"),),
    ),
    Vignette(
        room="王熙凤院", title="协理宁国府", chapter=13,
        chapter_title="秦可卿死封龙禁尉 王熙凤协理宁国府",
        quote="府门洞开，两边灯笼照如白昼", speakers=("王熙凤",),
        summary="秦可卿死后，宁国府乱作一团，凤姐受命协理丧事，分派定规，把一府上下整治得人人服气。",
        recall="宁国府那场丧事是她办的，办得人人服气。",
        effects=(Effect("王熙凤", mood="自信得意", secret="宁国府那场丧事，她办得人人服气", attitude=1.0),),
    ),
    Vignette(
        room="王熙凤院", title="泼醋", chapter=44,
        chapter_title="变生不测凤姐泼醋 喜出望外平儿理妆",
        quote="凤姐听了，已气的浑身发软", speakers=("王熙凤",),
        summary="凤姐做生日那日，撞见贾琏与鲍二家的私会，气得浑身发软，一场大闹。",
        recall="那日撞见的事，她记在心里，从不曾忘。",
        effects=(Effect("王熙凤", mood="含怒隐忍", secret="那日撞见的事，她记在心里"),),
    ),
    Vignette(
        room="王熙凤院", title="可卿托梦", chapter=13,
        chapter_title="秦可卿死封龙禁尉 王熙凤协理宁国府",
        quote="如今从梦中听见说秦氏死了", speakers=("王熙凤", "秦可卿"),
        summary="秦可卿临终托梦给凤姐，嘱她趁今日富贵，在祖茔附近多置田庄房舍，以为将来退步。",
        recall="可卿托梦说的那些话，她没跟人提过。",
        effects=(
            Effect("王熙凤", mood="心里发怵", secret="可卿托梦说的那些话，她没跟人提过"),
            Effect("秦可卿", mood="幽渺难言", secret="她托付的那件后事，不知凤姐记不记得"),
        ),
    ),
    # ------------------------------------------------------------ 荣禧堂
    Vignette(
        room="荣禧堂", title="才选凤藻宫", chapter=16,
        chapter_title="贾元春才选凤藻宫 秦鲸卿夭逝黄泉路",
        quote="晋封为凤藻宫尚书，加封贤德妃", speakers=("王熙凤",),
        summary="夏太监出来道喜，说贾府大小姐晋封凤藻宫尚书，加封贤德妃。合府上下喜气盈腮，按品大妆入朝谢恩。",
        recall="大小姐封妃那日，合府上下都像换了个人。",
        effects=(Effect("王熙凤", mood="与有荣焉", secret="大小姐封妃那日，合府上下都像换了个人", attitude=1.0),),
    ),
    Vignette(
        room="荣禧堂", title="除夕祭宗祠", chapter=53,
        chapter_title="宁国府除夕祭宗祠 荣国府元宵开夜宴",
        quote="开了宗祠，着人打扫，收拾供器，请神主", speakers=("王熙凤",),
        summary="年关将近，王夫人与凤姐治办年事，宁国府开宗祠、请神主、悬供遗真影像，两府上下忙忙碌碌。",
        recall="年事排场看着热闹，账上早已吃紧。",
        effects=(Effect("王熙凤", mood="强撑体面", secret="年事排场，账上早就吃紧"),),
    ),
    Vignette(
        room="荣禧堂", title="元妃薨逝", chapter=95,
        chapter_title="因讹成实元妃薨逝 以假混真宝玉疯颠",
        quote="贾娘娘薨逝", speakers=("王熙凤",),
        summary="宫中传出信来，贾娘娘薨逝，存年四十三岁。贾母含悲出宫，合府悲戚。",
        recall="娘娘一去，这府里的天就变了。",
        effects=(Effect("王熙凤", mood="心里发凉", secret="娘娘一去，这府里的天就变了"),),
    ),
    # ------------------------------------------------------------ 省亲别墅
    Vignette(
        room="省亲别墅", title="试才题对额", chapter=17,
        chapter_title="大观园试才题对额 荣国府归省庆元宵",
        quote="有用‘泻玉’二字，则……", speakers=("贾宝玉",),
        summary="大观园落成，贾政带着清客们题匾额对联，命宝玉拟。宝玉说“泻玉”不妥，另拟了蕴藉的字眼。",
        recall="园中那些匾额，老爷嘴上骂，心里是认的。",
        effects=(Effect("贾宝玉", mood="得意又心虚", secret="那些匾额老爷嘴上骂，心里是认的"),),
    ),
    Vignette(
        room="省亲别墅", title="归省庆元宵", chapter=18,
        chapter_title="隔珠帘父女勉忠勤 搦湘管姊弟裁题咏",
        quote="上面有一匾灯，写着“体仁沐德”四字", speakers=("贾元春",),
        summary="元宵之夜元春归省，园中香烟缭绕、花彩缤纷。她与祖母母亲相见，只有垂泪无言；又命姊妹们题咏。",
        recall="回家那半日，比在宫里十年还短。",
        effects=(Effect("贾元春", mood="含悲承欢", secret="回家那半日，比在宫里十年还短"),),
    ),
    Vignette(
        room="省亲别墅", title="元妃染恙", chapter=83,
        chapter_title="省宫闱贾元妃染恙 闹闺阃薛宝钗吞声",
        quote="如系元妃，少不得终有信的", speakers=("贾元春",),
        summary="宫中传出元妃欠安的消息，贾政说“如系元妃，少不得终有信的”。合府悬着心，只等内相来传。",
        recall="她这身子，不敢让家里知道。",
        effects=(Effect("贾元春", mood="隐忍不发", secret="她这身子，不敢让家里知道"),),
    ),
    # ------------------------------------------------------------ 梨香院
    Vignette(
        room="梨香院", title="比通灵金锁", chapter=8,
        chapter_title="比通灵金莺微露意 探宝钗黛玉半含酸",
        quote="是个癞头和尚送的，他说必须錾在金器上", speakers=("薛宝钗", "贾宝玉"),
        summary="宝玉到梨香院探宝钗，两人互看通灵玉与金锁。莺儿说金锁上的字是个癞头和尚送的，宝钗不待她说完便嗔住。",
        recall="金锁上的字与他的是一对，她不愿人多问。",
        effects=(Effect("薛宝钗", mood="端静自持", secret="金锁上的字与他的是一对，她不愿人多问"),),
    ),
    Vignette(
        room="梨香院", title="情悟梨香院", chapter=36,
        chapter_title="绣鸳鸯梦兆绛芸轩 识分定情悟梨香院",
        quote="梨香院的十二个女孩子中有小旦龄官最是唱的好", speakers=("贾宝玉",),
        summary="宝玉慕名去梨香院找龄官，龄官却正色相对，只惦记着贾蔷。宝玉自此才明白，各人有各人的缘分，不能强求。",
        recall="龄官那件事，让他明白各人有各人的缘分。",
        effects=(Effect("贾宝玉", mood="怅然有悟", secret="龄官那件事，让他明白各人有各人的缘分"),),
    ),
    Vignette(
        room="梨香院", title="宝玉悟禅机", chapter=22,
        chapter_title="听曲文宝玉悟禅机 制灯迷贾政悲谶语",
        quote="赤条条来去无牵挂", speakers=("贾宝玉", "薛宝钗"),
        summary="宝钗念《寄生草》给宝玉听，一句“赤条条来去无牵挂”让他一时参悟，提笔立了一偈。",
        recall="那句“赤条条来去无牵挂”，他到现在还记着。",
        effects=(
            Effect("贾宝玉", mood="一时出世", secret="那句“赤条条来去无牵挂”，他到现在还记着"),
            Effect("薛宝钗", mood="端静自持", secret="那支《寄生草》，她本不该念给他听"),
        ),
    ),
)


def for_room(room: str) -> tuple[Vignette, ...]:
    return tuple(item for item in VIGNETTES if item.room == room)


# mode：进门时只首启没经历过的（"fresh"）；谈话中只回望已经历过的（"recall"）
PICK_FRESH = "fresh"
PICK_RECALL = "recall"


def pick(
    room: str,
    present: list[str],
    triggered: set[str],
    rng: random.Random,
    chance: float | None = None,
    mode: str = PICK_FRESH,
) -> Vignette | None:
    """挑一条可触发的关目。

    - 涉及人物至少一人在场，否则不触发；
    - fresh：只挑没经历过的，作为"正在发生的事"；recall：只挑经历过的，作为追忆；
    - 同一次进门最多一条。
    """
    threshold = VIGNETTE_CHANCE if chance is None else chance
    if not room or rng.random() >= threshold:
        return None
    onstage = set(present)
    candidates = [
        item
        for item in for_room(room)
        if onstage.intersection(item.speakers)
        and ((item.key not in triggered) if mode == PICK_FRESH else (item.key in triggered))
    ]
    if not candidates:
        return None
    return rng.choice(candidates)


def story_lines(vignette: Vignette, fresh: bool) -> list[str]:
    """渲染进提示词的处境说明。"""
    where = f"第{_cn(vignette.chapter)}回《{vignette.chapter_title}》"
    if fresh:
        return [
            f"这间屋子里正在发生的一件事（{where}）：{vignette.summary}",
            f"原著原话：“{vignette.quote}”。你可以自然地带出这件事，"
            "也可以等来客问起再说；不要整段背诵原文，用你自己的口吻讲。",
        ]
    return [
        f"这间屋子里曾发生过的一件事（{where}）：{vignette.recall}",
        f"原著原话：“{vignette.quote}”。这件事你已经历过，如今是回头说起，"
        "用“那日”“后来”这类口气，不要当成正在发生的事。",
    ]


_CN_DIGITS = "零一二三四五六七八九"


def _cn(number: int) -> str:
    """回次的中文写法。

    写法要合规范：13 是"十三"，113 是"一百十三"（不是"一百十三"的省写），
    101 是"一百零一"，119 是"一百一十九"。
    """
    if number <= 0:
        return "零"
    if number < 10:
        return _CN_DIGITS[number]
    if number < 20:  # 十～十九：省去前导的"一"
        ones = number % 10
        return "十" + ("" if ones == 0 else _CN_DIGITS[ones])
    if number < 100:
        tens, ones = divmod(number, 10)
        return _CN_DIGITS[tens] + "十" + ("" if ones == 0 else _CN_DIGITS[ones])
    hundreds, rest = divmod(number, 100)
    head = _CN_DIGITS[hundreds] + "百"
    if rest == 0:
        return head
    if rest < 10:
        return head + "零" + _CN_DIGITS[rest]
    if rest < 20:  # 百位在场时，"一十"不能省成"十"
        ones = rest % 10
        return head + "一十" + ("" if ones == 0 else _CN_DIGITS[ones])
    return head + _cn(rest)
