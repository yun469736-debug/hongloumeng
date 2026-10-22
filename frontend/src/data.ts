import type { Scene } from './types'

export { characters } from './data/characterStates'

/**
 * 场景只保留“看得见”的东西：匾额、题句、说明、背景图、地图热区。
 *
 * hotspot 是 2026 年本轮用 ?calibrate=1 的校准页在 贾府.png（1448×1086）上逐个点定的：
 * 坐标即图上画好的房间名中心，热区 130×48 正好压在字上。换图之后需要重新标定一次。
 *
 * 谁能出现在这间房里、以什么权重出现，属于游戏逻辑，归后端 agent/rooms.py，
 * 由 GET /api/room 按 用户＋日＋时段＋场景 播种下发，前端不再持有名册。
 */
export const scenes: Scene[] = [
  { id:'xiaoxiang', name:'潇湘馆', subtitle:'凤尾森森，龙吟细细', description:'千百竿翠竹遮映，最宜与黛玉谈诗、思念与未尽之言。', background:'潇湘馆.png', hotspot:[25.87, 12.34] },
  { id:'yihong', name:'怡红院', subtitle:'绛芸轩里说闲情', description:'海棠映阶，蕉叶带露。此处宜清谈、品诗，也最常遇见宝玉。', background:'怡红院.png', hotspot:[73.72, 13.21] },
  { id:'daoxiang', name:'稻香村', subtitle:'杏帘在望，田舍清幽', description:'篱落田畦，柴门木槿，是园中最质朴的一处清境。', background:'稻香村.png', hotspot:[88.26, 25.97] },
  { id:'qinting', name:'沁芳亭', subtitle:'水心亭畔，荷风送香', description:'湖心小亭宜歇脚听风，也宜开一场临水诗会。', background:'沁芳亭.png', hotspot:[50.38, 22.62] },
  { id:'hengwu', name:'蘅芜苑', subtitle:'异草清香，素壁无华', description:'清雅持重的所在，宜谈人情世故，也宜听宝钗从容剖析。', background:'蘅芜苑.png', hotspot:[31.9, 28.66] },
  { id:'qinfangqiao', name:'沁芳桥', subtitle:'曲桥分水，花气袭人', description:'一桥横卧碧水，连接园中诸处，是偶遇与闲谈之所。', background:'沁芳亭.png', hotspot:[51.69, 32.14] },
  { id:'qiushuang', name:'秋爽斋', subtitle:'梧桐疏朗，秋气高华', description:'探春居所，爽阔疏朗，最宜议事与结社。', background:'秋爽斋.png', hotspot:[71.17, 34.35] },
  { id:'zhuijin', name:'缀锦楼', subtitle:'朱栏绣户，登楼望园', description:'楼阁临水，登临可览园中春色，也可静听远处笑语。', background:'缀锦楼.png', hotspot:[89.59, 39.05] },
  { id:'longcui', name:'栊翠庵', subtitle:'红梅映雪，禅意清寂', description:'妙玉所居，院落清幽，茶香与禅意相伴。', background:'栊翠庵.png', hotspot:[15.61, 30.89] },
  { id:'jiamu', name:'贾母院', subtitle:'慈晖堂前，福寿安和', description:'贾母起居之所，亲眷往来，最见贾府日常礼序。', background:'贾母院.png', hotspot:[15.88, 55.75] },
  { id:'fengyuan', name:'王熙凤院', subtitle:'粉面含春，机锋藏笑', description:'凤姐理事之所，账册、人情与府中消息皆汇于此。', background:'王熙凤院.png', hotspot:[41.2, 56.81] },
  { id:'rongxi', name:'荣禧堂', subtitle:'钟鸣鼎食，礼序森严', description:'贾府正堂，宜议家事、礼法与那些身不由己的抉择。', background:'荣禧堂.png', hotspot:[28.83, 60.08] },
  { id:'shengqin', name:'省亲别墅', subtitle:'天恩祖德，金碧辉煌', description:'元妃省亲所建的宏阔院落，繁华背后自有离情。', background:'省亲别墅.png', hotspot:[75.01, 56.14] },
  { id:'lixiang', name:'梨香院', subtitle:'梨花一院，曲韵悠长', description:'清静小院中偶闻曲声，适合听戏、闲叙旧事。', background:'梨香院.png', hotspot:[15.64, 67.82] },
]
