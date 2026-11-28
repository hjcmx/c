# coding=utf-8
"""SOOP 直播（https://wme.pp.ua）FongMi Python 源

只保留站点里的 SOOP 一路，其余平台全部剥离。

站点是纯前端 SPA，数据全部来自同域 /api 接口：
    /categories /recommend /rooms /room /play /search /danmaku

结构映射：
    class        = SOOP直播（文件夹）
    文件夹下钻   = 分类网格（站点 558 个分区，名字走内置中文映射）
    列表         = 分类下的直播间
    详情         = 直播间，清晰度做线路
    播放         = /api/play 直链（parse 0）
    弹幕         = /api/danmaku 给出的站点中继 wss（子协议 chat），
                   订阅帧/心跳/帧解析按站点前端 Play-*.js 同款复刻

弹幕协议要点（已用真实帧验通）：
    握手需 WebSocket 子协议 chat，否则服务端直接 400；
    开头发两帧（0001 初始化、0002 带 chatNo 的订阅），心跳 20s 一帧；
    帧结构 = ESC + TAB + 6 位类型 + 0x0c 分隔的字段（第一个分隔符在第 14 字节）；
    0005 是新弹幕（0 正文 / 1 账号 / 5 昵称），0002 是订阅确认，
    0004 是历史快照批（站点前端同样跳过，跟着收会把播放器刷爆）。
"""

import base64
import json
import os
import socket
import ssl
import struct
import threading
import time
from urllib.parse import unquote
from urllib.parse import urlsplit

from base.spider import Spider as BaseSpider

API = "https://wme.pp.ua/api"
HOST = "https://wme.pp.ua"
SITE = "soop"
SITE_NAME = "SOOP直播"
REFERER = "https://www.sooplive.com/"
UA = ("Mozilla/5.0 (Linux; Android 12; Pixel 5) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36")

TIMEOUT = 15000          # 站点正常 1-7s，卡住时会读到一半挂死，超时后重试一次
RETRY_DELAY = 1.0
MIN_INTERVAL = 0.4       # 相邻请求最小间隔，限速防风控
PAGE_LIMIT = 30          # 接口固定一页 30 条

# 分区中文名：站点给的是韩文，这里按分区 id 固定映射（id 稳定，不会随接口改名漂移）。
# 只收录有公认中文名的分区；没有确定译名的保持原文，不臆造。
ZH_CATS = {
    "00040019": "英雄联盟", "00130000": "聊天/摄像头", "00040427": "魔兽世界：永恒",
    "00040437": "侠盗猎车手 VI", "00040017": "我的世界", "00810000": "虚拟主播",
    "00040001": "星际争霸", "00040066": "绝地求生", "00040005": "突击风暴",
    "00040121": "综合游戏", "00040032": "冒险岛", "00740000": "旅行",
    "00330000": "吃播/烹饪", "00040110": "无畏契约", "00040158": "冒险岛世界",
    "00030002": "音乐流媒体", "00040070": "FC Online", "00590000": "配音/电台",
    "00030001": "音乐/舞蹈", "00270006": "加密货币", "00020007": "爱好",
    "00360141": "鬼怪的世界", "00040058": "守望先锋", "00570005": "其他体育",
    "00360126": "永恒之塔 2", "00170000": "国内职业足球", "00040008": "复古游戏",
    "00040075": "云顶之弈", "00040425": "EA Sports FC 27", "00390013": "韩联社",
    "00040043": "超级跑跑", "00040184": "以撒的结合：重生", "00020009": "美术",
    "00040120": "永恒轮回", "00390024": "YTN 直播", "00040007": "特种部队",
    "00360100": "鸣潮", "00040035": "侠盗猎车手 V", "00040002": "魔兽争霸 III",
    "00040081": "暗黑破坏神 II", "00040163": "铁拳 8", "00020011": "算命",
    "00040389": "天堂 经典", "00040065": "风之国", "00290002": "知识",
    "00040179": "Roblox", "00040067": "失落的方舟", "00040195": "星露谷物语",
    "00040012": "天堂", "00390004": "MBN", "00570004": "解说/分析",
    "00570013": "脑力运动", "00040082": "Dota 2", "00040020": "暗黑破坏神 III",
    "00040285": "塞尔达传说：旷野之息", "00390030": "阿里郎 TV", "00040096": "巨商",
    "00040004": "地下城与勇士", "00040146": "腐蚀（Rust）", "00580000": "宠物直播",
    "00040078": "反恐精英 2", "00670000": "钓鱼/户外", "00040093": "仙境传说 Online",
    "00040080": "黎明杀机", "00140009": "中立", "00360003": "手游综合",
    "00190003": "Road FC", "00040426": "使命召唤：现代战争 4", "00040430": "影之刃 零",
    "00270009": "衍生品", "00360056": "英雄联盟手游", "00040069": "堡垒之夜",
    "00390031": "每日经济 TV", "00270008": "股票", "00290001": "自习",
    "00360055": "跑跑卡丁车 Rush+", "00040347": "英灵神殿", "00040085": "街头篮球",
    "00360022": "天堂M", "00040391": "DJMAX RESPECT V", "00040016": "星际争霸 II",
    "00040039": "炉石传说", "00040107": "逃离塔科夫", "00360114": "Com2uS 职业棒球 V25",
    "00040040": "洛奇", "00040050": "风暴英雄", "00040074": "流放之路",
    "00040087": "伊卡洛斯", "00040189": "僵尸毁灭工程", "00290007": "经济",
    "00040276": "最终幻想 7 重生", "00040294": "忍者龙剑传 2 黑", "00360129": "明日方舟：终末地",
    "00040401": "红色沙漠", "00360132": "冒险岛养成记", "00040015": "永恒之塔",
    "00040033": "Cyphers", "00040073": "Apex 英雄", "00040143": "暗黑破坏神 IV",
    "00040148": "博德之门 3", "00040160": "幻兽帕鲁", "00040206": "XCOM 2",
    "00270003": "海外股票", "00270004": "海外期货", "00290006": "宗教",
    "00570002": "台球", "00570006": "保龄球", "00570007": "高尔夫",
    "00040286": "塞尔达传说：王国之泪", "00040362": "战地 6", "00390029": "公共",
    "00020006": "美妆", "00040011": "魔兽世界", "00040022": "剑灵",
    "00040153": "EA Sports FC 24", "00040311": "马力欧卡丁车世界", "00940014": "其他剧集",
    "00040224": "欧洲卡车模拟 2", "00040092": "R2", "00040105": "黑色沙漠",
    "00040119": "赛博朋克 2077", "00030003": "卡拉OK", "00040042": "泡泡战士",
    "00040061": "铁拳 7", "00040076": "自走棋", "00040077": "方舟：生存进化",
    "00040079": "黑暗伊甸", "00040083": "艾尔之光", "00040090": "怪物猎人世界：冰原",
    "00040091": "osu!", "00040094": "彩虹六号：围攻", "00040095": "强打者",
    "00040099": "救世之树", "00040102": "坦克世界", "00040103": "符文之地传说",
    "00040106": "骷髅：英雄杀手", "00040108": "使命召唤", "00040111": "集合啦！动物森友会",
    "00040114": "糖豆人", "00040115": "我们之中", "00040117": "宝可梦 朱/紫",
    "00040124": "FIFA 23", "00040126": "上古世纪", "00040129": "Football Manager 2024",
    "00040131": "VRChat", "00040132": "战神：诸神黄昏", "00040133": "索尼克 未知边境",
    "00040134": "女神异闻录 5 皇家版", "00040135": "eFootball 2024", "00040136": "木卫四协议",
    "00040137": "游戏王 大师决斗", "00040138": "死亡空间", "00040139": "如龙 维新！极",
    "00040140": "卧龙：苍天陨落", "00040144": "星球大战 绝地：幸存者", "00040145": "逃生试炼",
    "00040147": "瑞奇与叮当：时空跳转", "00040150": "命运 2", "00040151": "P的谎言",
    "00040154": "Only Climb: Better Together", "00040155": "心灵杀手 2",
    "00040156": "王权与自由", "00040157": "街头霸王 6", "00040159": "Dark and Darker",
    "00040161": "如龙 8", "00040162": "致命公司", "00040164": "女神异闻录 3 Reload",
    "00040165": "碧蓝幻想 Relink", "00040166": "波比的游戏时间", "00040168": "拳皇 98",
    "00040169": "拳皇 2002", "00040171": "街头霸王 II", "00040172": "绝地潜兵 2",
    "00040173": "艾尔登法环", "00040174": "夜莺传说", "00040175": "泡泡堂",
    "00040176": "小丑牌", "00040177": "最后纪元", "00040178": "For The King II",
    "00040180": "斯普拉遁 3", "00040181": "洞窟探险 2", "00040183": "深岩银河：幸存者",
    "00040185": "逆转裁判 123 成步堂精选集", "00040186": "逆转裁判 456 王泥喜精选集",
    "00040187": "A Difficult Game About Climbing", "00040190": "龙之信条 II",
    "00040191": "杀戮尖塔", "00040192": "武装突袭 3", "00040193": "黑暗之魂 III",
    "00040194": "黑暗之魂：重制版", "00040196": "三国志 14", "00040197": "环世界",
    "00040198": "超市模拟器", "00040200": "神力科莎", "00040201": "No Rest for the Wicked",
    "00040203": "星刃", "00040204": "七日杀", "00040205": "庄园领主",
    "00040207": "MLB The Show 24", "00040209": "哈迪斯 2", "00040210": "女鬼桥 2：释魂路",
    "00040213": "地狱之刃 II：塞娜的传说", "00040215": "I Don't Fall",
    "00040216": "艾尔登法环：黄金树幽影", "00040219": "反恐精英 Online",
    "00140001": "斗山", "00140002": "韩华", "00140003": "乐天", "00140004": "培证英雄",
    "00140005": "三星", "00140006": "KIA", "00140007": "LG", "00140008": "SSG",
    "00140010": "NC", "00140011": "kt", "00180000": "海外职业棒球",
    "00270001": "国内股票", "00270002": "国内期货", "00270005": "房地产",
    "00270007": "其他金融", "00290004": "语言学习", "00290005": "时事",
    "00360012": "全民大富翁", "00360018": "皇室战争", "00360020": "宝可梦 GO",
    "00360021": "天堂 2：革命", "00360028": "仙境传说M", "00360030": "黑色沙漠M",
    "00360031": "绝地求生手游", "00360033": "第七史诗", "00360035": "十二之天M",
    "00360037": "明日之后", "00360038": "Fate/Grand Order", "00360040": "公主连结 Re:Dive",
    "00360041": "黑暗伊甸M", "00360043": "剑灵：革命", "00360044": "部落冲突",
    "00360046": "V4", "00360050": "天堂 2M", "00360052": "A3：Still Alive",
    "00360054": "风之国：Yeon", "00360057": "传奇 4", "00360058": "大航海时代 Origin",
    "00360060": "七骑士 2", "00360062": "跑跑姜饼人", "00360063": "原神",
    "00360066": "DK Mobile", "00360067": "暗黑破坏神 不朽", "00360069": "奥丁：英灵殿崛起",
    "00360070": "剑灵 2", "00360072": "Com2uS 职业棒球 2023", "00360073": "天堂W",
    "00360074": "宝可梦大集结", "00360077": "地下城与勇士手游", "00360078": "网石职业棒球 2022",
    "00360079": "传奇M", "00360080": "赛马娘 Pretty Derby", "00360081": "七骑士：革命",
    "00360082": "HIT 2", "00360084": "文明：Reign of Power", "00360085": "仙境传说X",
    "00360087": "剑与远征", "00360088": "夜鸦", "00360091": "真·三国无双 M",
    "00360092": "胜利女神：妮姬", "00360093": "蔚蓝档案", "00360094": "崩坏：星穹铁道",
    "00360095": "我独自升级 ARISE", "00360097": "阿斯达年代记：三势力",
    "00360098": "魔灵召唤：天空之役", "00360099": "黑鸦 2", "00360102": "绝区零",
    "00370010": "欧冠", "00370011": "英超", "00570003": "健身",
    "00690000": "海外职业篮球", "00720000": "LCK", "00840001": "业余棒球",
    "00840002": "业余足球", "00840003": "业余排球", "00840004": "业余篮球",
    "00880000": "SOOPER LEAGUE", "00040220": "风暴之门", "00360103": "使命召唤手游",
    "00040221": "WWE 2K24", "00040222": "七日世界", "00040223": "第一后裔",
    "00040225": "黑神话：悟空", "00040227": "inZOI", "00040228": "星球大战：亡命之徒",
    "00040229": "犯罪现场清洁工", "00040232": "逆转检察官", "00040233": "EA Sports FC 25",
    "00040234": "冰汽时代 2", "00040235": "塞尔达传说：智慧的再现", "00030005": "X2",
    "00040236": "寂静岭 2", "00360104": "帝国时代手游", "00040237": "PUBG：BLINDSPOT",
    "00040238": "怪物猎人 荒野", "00040240": "超级马力欧派对 空前盛会",
    "00360105": "宝可梦卡牌 Pocket", "00040244": "潜行者 2：切尔诺贝利之心",
    "00040246": "封锁协议", "00040247": "DEADLOCK", "00040248": "夺宝奇兵：古老之圈",
    "00040249": "流放之路 2", "00040250": "三角洲行动", "00040251": "科南 流放者",
    "00040253": "漫威争锋", "00040254": "真·三国无双：起源", "00040255": "边狱公司",
    "00040256": "高压清洗模拟器", "00040259": "米塔", "00360107": "明日方舟",
    "00040261": "主播人生模拟器 2", "00040262": "文明 VII", "00040263": "文明 V",
    "00040264": "文明 VI", "00040265": "天国拯救 II", "00360109": "雷顿教授与不可思议的小镇 HD",
    "00360110": "雷顿教授与恶魔之箱 HD", "00040266": "Hello Kitty 岛屿冒险",
    "00040267": "RF Online Next", "00040268": "骑马与砍杀 2：霸主",
    "00040269": "第一狂战士：卡赞", "00040270": "链在一起", "00040271": "核心守护者",
    "00040272": "都市传说解体中心", "00040273": "特技射击模拟器",
    "00040274": "怪物猎人 崛起：曙光", "00040275": "最终幻想 7 重制版",
    "00040277": "最终幻想 15", "00040278": "最终幻想 16", "00040279": "最终幻想 14",
    "00040280": "WWE 2K25", "00040281": "龙珠 破坏者", "00040282": "如龙 8 外传 Pirates in Hawaii",
    "00040283": "独角兽 Overlord", "00040284": "分裂小说", "00040287": "FragPunk",
    "00040290": "双点博物馆", "00040291": "动物园之星", "00040289": "Arc System Works",
    "00040292": "刺客信条：影", "00040293": "MLB The Show 25", "00040295": "仁王 2 完全版",
    "00040296": "GT 赛车 7", "00040298": "BLEACH 魂魄觉醒", "00040297": "R.E.P.O.",
    "00360113": "洛奇 Mobile", "00040300": "猎人：荒野的召唤", "00980000": "赛车运动",
    "00360115": "跑跑姜饼人：烤箱大逃亡", "00040304": "光与影：33 号远征队",
    "00040305": "毁灭战士：黑暗时代", "00360116": "雀魂", "00360117": "七骑士：重生",
    "00040306": "战舰世界", "00040309": "泰拉瑞亚", "00360118": "第五人格",
    "00040310": "艾尔登法环：夜之统治", "00040313": "死亡搁浅 2", "00040314": "鹅鸭杀",
    "00040315": "背包乱斗", "00040316": "机甲突破", "00040318": "沙丘：觉醒",
    "00040319": "影之诗：超凡世界", "00040317": "断箭", "00040320": "美少女梦工厂",
    "00040322": "美少女梦工厂：预言的孩子", "00040321": "美少女梦工厂 2 重生",
    "00040323": "Fantasy Life i 旋转的龙与偷时间的少女", "00040324": "PEAK",
    "00040325": "夜族崛起", "00040326": "全境封锁 2", "00040327": "彩虹六号：围攻 X",
    "00040328": "勇者斗恶龙 XI：寻觅逝去的时光", "00040329": "勇者斗恶龙 建造者 2",
    "00040330": "大金刚 Bananza", "00040331": "明末：渊虚之羽",
    "00570014": "橄榄球", "00040333": "黑手党：旧国度", "00570017": "羽毛球",
    "00040335": "潜水员戴夫", "00040336": "DNF Duel", "00040337": "洛奇英雄传",
    "00040338": "天翼之链", "00360119": "EA SPORTS FC 手游", "00360120": "冒险岛M",
    "00040339": "合金装备 Δ：食蛇者", "00040141": "最终决战（The Finals）",
    "00570019": "游泳", "00040342": "空洞骑士：丝之歌", "00040343": "合金弹头",
    "00040344": "2XKO", "00040345": "F1 25", "00040346": "无主之地 4",
    "00040348": "生化危机 启示录 2", "00040349": "生化危机 7", "00040350": "生化危机 村庄",
    "00570020": "美式足球", "00040351": "消逝的光芒：野兽", "00040354": "EA Sports FC 26",
    "00360123": "失落的方舟手游", "00040356": "寂静岭 f", "00040357": "超级人类",
    "00040359": "羊蹄山之魂", "00040360": "宝可梦传说 Z-A", "00040365": "NBA 2K26",
    "00040366": "忍者龙剑传 4", "00040367": "天外世界 2", "00040369": "十字军之王 3",
    "00040372": "欧陆风云 5", "00040374": "Football Manager 26",
    "00040375": "塞尔达无双 封印战记", "00040377": "纪元 117：罗马和平",
    "00040378": "燕云十六声", "00040380": "合租室友全是美女？1",
    "00040381": "合租室友全是美女？2", "00040382": "PUBG：BLACK BUDGET",
    "00570021": "田径", "00040386": "噬血代码 II", "00040388": "WASD：托莉的冒险",
    "00040395": "生化危机 安魂曲", "00040398": "杀戮尖塔 2", "01050000": "KBO",
    "00040399": "怪物猎人物语 3：命运双龙", "00040400": "MLB The Show 26",
    "00040403": "宝可梦 Champions", "00190004": "格斗内容", "00040410": "深海迷航 2",
    "00360134": "蓝色星原：旅谣", "00360135": "荒野乱斗", "00040411": "007 曙光初现",
    "00030007": "International Dance League", "00370014": "国家队",
    "00040412": "荒野大镖客 2", "00370015": "Dailynews Cup", "00040413": "刺客信条：黑旗 重制",
    "00360138": "三国志：天下决战", "00570022": "飞镖", "00040419": "星球大战：零号连队",
    "00370016": "足球内容", "00040421": "鬼武者 Way of the Sword", "00040428": "动物园之星 2",
    "00360143": "BanG Dream! Our Notes", "00040431": "紫菜包饭天国",
    "00040432": "BIGGER BANG", "00040433": "塞尔达传说：时之笛", "00040435": "AGF",
    "00040436": "Football Manager 27",
}

# 弹幕帧：ESC + TAB + 6 位类型，字段以 0x0c 分隔，正文从第 14 字节起
SOOP_SUB1 = b"\x1b\t000100000600" + b"\x0c" * 3 + b"16" + b"\x0c"
SOOP_HB = b"\x1b\t000000000100" + b"\x0c"
DANMAKU_INTERVAL = 20.0   # 心跳间隔，站点前端是 20s


def _soop_sub2(chat_no):
    """0002 订阅帧：长度 = chatNo 字节数 + 6，左补零到 6 位"""
    total = len(chat_no.encode("utf-8")) + 6
    return (b"\x1b\t0002" + str(total).zfill(6).encode("ascii") + b"00\x0c"
            + chat_no.encode("utf-8") + b"\x0c" * 5)


def _soop_bytes(content):
    if isinstance(content, (bytes, bytearray)):
        return bytes(content)
    if content is None:
        return b""
    try:
        return str(content).encode("utf-8")
    except Exception:
        return b""


def _soop_frame(content):
    """返回 (类型, 弹幕列表)。类型取帧头第 2-5 字节：0001/0002/0004/0005..."""
    data = _soop_bytes(content)
    if len(data) < 14:
        return "", []
    kind = data[2:6].decode("ascii", "ignore")
    if kind != "0005":
        # 只有 0005 是新弹幕。0004（历史快照批）/0127（用户列表）这类帧每秒几十上百条，
        # 先按类型剪掉，连字段都不解，避免把回调线程拖住
        return kind, []
    fields = [x.decode("utf-8", "replace").strip() for x in data[14:].split(b"\x0c")]
    # 14 字节头后面紧跟一个分隔符，split 出来的第 0 项是空串，先摘掉
    if fields and not fields[0]:
        fields = fields[1:]

    def _keep(user, text):
        text = (text or "").strip()
        user = (user or "").strip()
        if not text or not user:
            return None
        # 站点前端同样跳过：系统占位值、带竖线的合成串
        if text in ("-1", "1") or "|" in text:
            return None
        return {"text": text, "userName": user}

    items = []
    # 站点前端同样只渲染 0005；0004 是整批历史快照（每秒几十帧、每帧 40 条），
    # 跟进去等于把播放器刷爆，这里照站点的做法直接丢掉
    if len(fields) >= 6:
        # 0=正文 1=账号 5=昵称 7/8=昵称配色（站点不给颜色，这里也不用）
        item = _keep(fields[5] or fields[1], fields[0])
        if item:
            items.append(item)
    return kind, items


class _RawWS:
    """极简 WSS 客户端（标准库 socket + ssl 实现）。

    站点弹幕中继强制要求子协议 chat（不带就 400），而宿主 net.connect 的子协议选项
    不在公开契约里、实机上很可能被忽略，所以这里自己握手，保证 Sec-WebSocket-Protocol
    一定带得上；事件模型与宿主 net.connect 对齐（open / message / error）。
    """

    def __init__(self, url, protocols, headers, on_event, timeout=12.0):
        self.on_event = on_event
        self._send_lock = threading.Lock()
        self._closed = False
        self._sock = None
        self._buf = b""
        parts = urlsplit(url)
        self._secure = parts.scheme == "wss"
        self._host = parts.hostname or ""
        self._port = parts.port or (443 if self._secure else 80)
        self._path = (parts.path or "/") + (("?" + parts.query) if parts.query else "")
        self._protocols = list(protocols or [])
        self._headers = dict(headers or {})
        self._timeout = timeout
        threading.Thread(target=self._run, daemon=True).start()

    # ---------------- 连接 ----------------
    def _connect(self):
        raw = socket.create_connection((self._host, self._port), timeout=self._timeout)
        raw.settimeout(self._timeout)
        if not self._secure:
            return raw
        try:
            return ssl.create_default_context().wrap_socket(raw, server_hostname=self._host)
        except ssl.SSLError:
            # 设备上没有系统 CA 时退回不校验证书，否则弹幕整条链路直接连不上
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            return ctx.wrap_socket(raw, server_hostname=self._host)

    def _handshake(self):
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        lines = [
            "GET %s HTTP/1.1" % self._path,
            "Host: %s" % self._host,
            "Upgrade: websocket",
            "Connection: Upgrade",
            "Sec-WebSocket-Key: %s" % key,
            "Sec-WebSocket-Version: 13",
        ]
        if self._protocols:
            lines.append("Sec-WebSocket-Protocol: %s" % ", ".join(self._protocols))
        for name, value in self._headers.items():
            lines.append("%s: %s" % (name, value))
        self._sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("utf-8"))

        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise RuntimeError("握手连接被关闭")
            head += chunk
            if len(head) > 16384:
                raise RuntimeError("握手响应异常")
        status_line, _, rest = head.partition(b"\r\n\r\n")
        first = status_line.split(b"\r\n", 1)[0].decode("latin1", "replace")
        if " 101 " not in first + " ":
            raise RuntimeError("握手失败：%s" % first.strip())
        self._buf = rest

    # ---------------- 帧 ----------------
    def _read(self, size):
        while len(self._buf) < size:
            chunk = self._sock.recv(65536)
            if not chunk:
                raise RuntimeError("连接已关闭")
            self._buf += chunk
        out, self._buf = self._buf[:size], self._buf[size:]
        return out

    def _frame(self):
        b1, b2 = self._read(2)
        fin = b1 & 0x80
        op = b1 & 0x0F
        masked = b2 & 0x80
        length = b2 & 0x7F
        if length == 126:
            length = struct.unpack(">H", self._read(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", self._read(8))[0]
        key = self._read(4) if masked else b""
        payload = self._read(length) if length else b""
        if masked and key:
            payload = bytes(b ^ key[i % 4] for i, b in enumerate(payload))
        return fin, op, payload

    def _send_frame(self, op, payload):
        with self._send_lock:
            if self._sock is None or self._closed:
                raise RuntimeError("未连接")
            head = bytearray([0x80 | op])
            length = len(payload)
            if length < 126:
                head.append(0x80 | length)
            elif length < 65536:
                head.append(0x80 | 126)
                head += struct.pack(">H", length)
            else:
                head.append(0x80 | 127)
                head += struct.pack(">Q", length)
            mask = os.urandom(4)
            head += mask
            self._sock.sendall(bytes(head) + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def send(self, data):
        payload = data if isinstance(data, (bytes, bytearray)) else str(data).encode("utf-8")
        self._send_frame(0x1, bytes(payload))

    def close(self):
        self._closed = True
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass

    # ---------------- 读循环 ----------------
    def _run(self):
        pending = b""
        pending_op = 0x1
        try:
            self._sock = self._connect()
            self._handshake()
            if self._closed:
                return
            self.on_event(self, {"type": "open"})
            while not self._closed:
                try:
                    fin, op, payload = self._frame()
                except socket.timeout:
                    continue
                if op == 0x9:                       # ping -> pong
                    try:
                        self._send_frame(0x0A, payload)
                    except Exception:
                        return
                    continue
                if op == 0x8:                       # close
                    raise RuntimeError("服务端关闭连接")
                if op == 0xA:
                    continue
                if op in (0x0, 0x1, 0x2):
                    if op == 0x0:
                        pending += payload
                    else:
                        pending, pending_op = payload, op
                    if fin:
                        self.on_event(self, {"type": "message", "content": pending,
                                             "binary": pending_op == 0x2})
                        pending = b""
        except Exception as error:
            if not self._closed:
                self.on_event(self, {"type": "error",
                                     "msg": "%s: %s" % (type(error).__name__, error)})
        finally:
            self.close()


class Spider(BaseSpider):
    def init(self, extend=""):
        if not isinstance(extend, str):
            raise ValueError("Site.ext 必须是 JSON 对象")
        try:
            options = json.loads(extend) if extend else {}
        except json.JSONDecodeError:
            raise ValueError("Site.ext 必须是 JSON 对象") from None
        if not isinstance(options, dict):
            raise ValueError("Site.ext 必须是 JSON 对象")
        self.options = options
        self._cats = None
        self._last = 0.0
        self._seq = 0
        self._lock = threading.Lock()
        self._active_stop = None

    # ---------------- 网络 ----------------
    def _fetch(self, path, params):
        gap = MIN_INTERVAL - (time.time() - self._last)
        if gap > 0:
            time.sleep(gap)
        self._last = time.time()
        return self.net.req(API + path, {
            "params": params or {},
            "headers": {
                "User-Agent": UA,
                "Referer": HOST + "/",
                "Accept": "application/json, text/plain, */*",
            },
            "timeout": TIMEOUT,
        })

    def _raw(self, path, params):
        """返回 (状态码, JSON)；传输层失败重试一次，HTTP 业务错误照原样交回。"""
        resp = self._fetch(path, params)
        if resp.get("error"):
            time.sleep(RETRY_DELAY)
            resp = self._fetch(path, params)
        if resp.get("error"):
            raise RuntimeError("请求失败：%s" % resp["error"])
        code = resp.get("code") or 0
        if code in (502, 503, 504):
            time.sleep(RETRY_DELAY)
            resp = self._fetch(path, params)
            if resp.get("error"):
                raise RuntimeError("请求失败：%s" % resp["error"])
            code = resp.get("code") or 0
        body = resp.get("content") or ""
        try:
            data = json.loads(body) if body else None
        except ValueError:
            data = None
        return code, data

    def _api(self, path, params=None):
        code, data = self._raw(path, params)
        if not 200 <= code < 300:
            detail = ""
            if isinstance(data, dict):
                detail = data.get("error") or data.get("code") or ""
            raise RuntimeError("接口 HTTP %s%s" % (code, ("：" + str(detail)) if detail else ""))
        if not isinstance(data, dict):
            raise RuntimeError("接口返回不是 JSON 对象：%s%s" % (API, path))
        return data

    # ---------------- 通用 ----------------
    def _paged(self, items, page, has_more):
        if not isinstance(items, list):
            raise RuntimeError("接口返回缺少 items 列表")
        return {
            "list": items,
            "page": page,
            "pagecount": page + 1 if has_more else page,
            "limit": PAGE_LIMIT,
        }

    def _count(self, value):
        try:
            num = int(value or 0)
        except (TypeError, ValueError):
            return ""
        if num <= 0:
            return ""
        if num >= 100000000:
            return "%.1f亿" % (num / 100000000.0)
        if num >= 10000:
            return "%.1f万" % (num / 10000.0)
        return str(num)

    def _clean(self, text):
        if not text:
            return ""
        return " ".join(str(text).split())

    def _ep(self, name):
        return str(name).replace("$", "＄").replace("#", "＃").strip()

    def _cover(self, url):
        if not url or not isinstance(url, str):
            return ""
        url = url.strip()
        if url.startswith("//"):
            url = "https:" + url
        return url

    def _cat_name(self, cat_id, name):
        return ZH_CATS.get(str(cat_id)) or self._clean(name) or str(cat_id)

    # ---------------- 分类 ----------------    
    def _categories(self):
        if self._cats is not None:
            return self._cats
        data = self._api("/categories", {"site": SITE})
        cats = data.get("categories")
        if not isinstance(cats, list):
            raise RuntimeError("站点没有返回 SOOP 的分类结构")
        leaves = []
        for cat in cats:
            for child in cat.get("children") or []:
                cid = str(child.get("id") or "")
                if cid:
                    leaves.append(child)
        if not leaves:
            raise RuntimeError("站点没有返回 SOOP 的子分区")
        self._cats = leaves
        return leaves

    def _cat_folders(self):
        items = [{
            "vod_id": "hot",
            "vod_name": "热门推荐",
            "vod_remarks": "按人气排序",
            "vod_tag": "folder",
            "style": {"type": "list"},
        }]
        for child in self._categories():
            cid = str(child.get("id") or "")
            items.append({
                "vod_id": "rooms|%s" % cid,
                "vod_name": self._cat_name(cid, child.get("name")),
                "vod_pic": self._cover(child.get("pic")),
                "vod_tag": "folder",
                "style": {"type": "rect", "ratio": 1.78},
            })
        return items

    def _room_card(self, record):
        if not isinstance(record, dict):
            return None
        room_id = str(record.get("roomId") or "")
        if not room_id:
            return None
        user = self._clean(record.get("userName"))
        online = self._count(record.get("online"))
        return {
            "vod_id": "room|%s" % room_id,
            "vod_name": self._clean(record.get("title")) or user or room_id,
            "vod_pic": self._cover(record.get("cover")),
            "vod_remarks": " · ".join(x for x in (user, online) if x),
            "style": {"type": "rect", "ratio": 1.78},
        }

    def _cards(self, records):
        raw = records if isinstance(records, list) else []
        items = [card for card in (self._room_card(x) for x in raw) if card]
        if raw and not items:
            raise RuntimeError("接口返回的直播间数据全都缺少 roomId")
        return items

    def _room_list(self, area_id, page):
        data = self._api("/rooms", {
            "site": SITE, "areaId": area_id, "parentAreaId": "popular", "page": page,
        })
        return self._paged(self._cards(data.get("items")), page, bool(data.get("hasMore")))

    def _hot_list(self, page):
        data = self._api("/recommend", {"site": SITE, "page": page})
        return self._paged(self._cards(data.get("items")), page, bool(data.get("hasMore")))

    # ---------------- 详情 ----------------
    def _detail(self, room_id):
        data = self._api("/room", {"site": SITE, "roomId": room_id})
        living = data.get("living")
        user = self._clean(data.get("userName"))
        online = self._count(data.get("online"))

        head = []
        if living is False:
            head.append("当前未开播，播放地址可能无流")
        intro = self._clean(data.get("introduction"))
        page_url = data.get("url") or ""
        if page_url:
            head.append("直播间：" + page_url)

        flags = []
        lines = []
        for quality in data.get("qualities") or []:
            key = str(quality.get("key") or "")
            if not key:
                continue
            name = self._ep(self._clean(quality.get("name")) or key)
            if name in flags:
                name = "%s·%d" % (name, len(flags) + 1)
            flags.append(name)
            lines.append("直播$room|%s|%s" % (room_id, key))
        if not flags:
            flags.append("直播")
            lines.append("直播$room|%s|" % room_id)

        remarks = " · ".join(x for x in (
            "直播中" if living else ("未开播" if living is False else ""), online) if x)

        return {
            "vod_id": "room|%s" % room_id,
            "vod_name": self._clean(data.get("title")) or user or room_id,
            "vod_pic": self._cover(data.get("cover")),
            "vod_remarks": remarks,
            "type_name": SITE_NAME,
            "vod_actor": user,
            "vod_director": SITE_NAME,
            "vod_content": "\n".join(head + ([intro] if intro else [])),
            "vod_play_from": "$$$".join(flags),
            "vod_play_url": "$$$".join(lines),
        }

    # ---------------- 播放 ----------------
    def _play(self, ident):
        parts = str(ident).split("|")
        if len(parts) < 2 or parts[0] != "room":
            raise RuntimeError("无效的播放 ID：%s" % ident)
        room_id = parts[1].strip()
        if not room_id:
            raise RuntimeError("无效的播放 ID：%s" % ident)
        params = {"site": SITE, "roomId": room_id}
        if len(parts) >= 3 and parts[2]:
            params["quality"] = parts[2]
        data = self._api("/play", params)
        urls = data.get("urls")
        if not isinstance(urls, list) or not urls:
            raise RuntimeError("没有取到播放地址（%s）" % (data.get("error") or "空响应"))
        # 站点已按自己的优先级排好线路，照抄第一条，不自行按格式挑
        picked = next((u for u in urls if u.get("url")), None)
        if picked is None:
            raise RuntimeError("播放地址列表里没有可用链接")

        result = {
            "parse": 0,
            "jx": 0,
            "url": picked["url"],
            "header": {"User-Agent": UA, "Referer": REFERER},
        }
        if picked.get("format") == "hls":
            result["format"] = "application/x-mpegURL"
        result["danmaku"] = [{
            "name": "弹幕",
            "url": self.danmakuUrl("soop:%s" % room_id),
        }]
        return result

    # ---------------- 弹幕 ----------------
    def _emit(self, emit, payload):
        try:
            emit(payload)
        except Exception:
            pass

    def danmaku(self, id, emit):
        room = unquote(str(id or "")).strip()
        if not room:
            return lambda: None
        if ":" in room:
            room = room.rsplit(":", 1)[-1].strip()
        if not room:
            return lambda: None
        with self._lock:
            self._seq += 1
            seq = self._seq
            previous, self._active_stop = self._active_stop, None
        if previous:
            try:
                previous()
            except Exception:
                pass
        try:
            stop = self._subscribe(room, emit)
        except Exception as error:
            self._emit(emit, {"state": "error", "msg": "弹幕启动失败：%s" % error})
            return lambda: None
        with self._lock:
            if seq != self._seq:
                try:
                    stop()
                except Exception:
                    pass
                return lambda: None
            self._active_stop = stop
        return stop

    def _subscribe(self, room_id, emit):
        conf = self._api("/danmaku", {"site": SITE, "roomId": room_id})
        url = str(conf.get("url") or "")
        chat_no = str(conf.get("chatNo") or "")
        if not url or not chat_no:
            raise RuntimeError("弹幕参数不完整")
        stopped = threading.Event()
        ready = [False]
        # conn 会被看门狗换掉，状态放字典里给各线程共用
        state = {"conn": None, "live": False, "opened": time.time(), "attempts": 0}

        def _ready():
            if not ready[0] and not stopped.is_set():
                ready[0] = True
                self._emit(emit, {"state": "ready"})

        def _on_event(link, event):
            if stopped.is_set():
                return
            kind = event.get("type")
            if kind == "open":
                try:
                    link.send(SOOP_SUB1)
                    # 站点前端发完初始化帧等 200ms 再发订阅帧
                    timer = threading.Timer(0.2, lambda: _send_sub(link))
                    timer.daemon = True
                    timer.start()
                except Exception as error:
                    self._emit(emit, {"state": "error", "msg": "弹幕握手失败：%s" % error})
                return
            if kind == "message":
                try:
                    frame, items = _soop_frame(event.get("content"))
                except Exception:
                    return
                # 0110/0054/0090/0094 是上游会话初始化帧：只发快照不发这些，说明没挂上实时流
                if frame in ("0110", "0054", "0090", "0094", "0005"):
                    state["live"] = True
                if frame == "0002":       # 订阅确认
                    _ready()
                    return
                for item in items:
                    _ready()
                    self._emit(emit, {
                        "text": item["text"][:4096],
                        "color": 0xFFFFFF,
                        "type": 1,
                        "size": 0,
                        "userName": item["userName"],
                    })
                return
            if kind == "retry":
                self._emit(emit, {"state": "retrying", "msg": "弹幕连线中断，等待恢复"})
            elif kind in ("error", "close"):
                # 自建客户端没有宿主那层自动重连，自己补两次，之后才报错收工
                if stopped.is_set() or state["attempts"] >= 2:
                    self._emit(emit, {"state": "error", "msg": "弹幕连线已关闭"})
                    return
                state["attempts"] += 1
                self._emit(emit, {"state": "retrying", "msg": "弹幕连线中断，等待恢复"})

                def _later():
                    if stopped.is_set():
                        return
                    try:
                        _open()
                    except Exception:
                        pass

                timer = threading.Timer(2.0, _later)
                timer.daemon = True
                timer.start()

        def _send_sub(link):
            if stopped.is_set():
                return
            try:
                link.send(_soop_sub2(chat_no))
            except Exception:
                pass

        def _open():
            state["opened"] = time.time()
            state["live"] = False
            # 中继要求子协议 chat，宿主 net.connect 的子协议选项不在公开契约里，
            # 所以走自带的标准库 WSS 客户端，保证握手头一定带 Sec-WebSocket-Protocol
            state["conn"] = _RawWS(url, ["chat"], {
                "User-Agent": UA, "Referer": HOST + "/", "Origin": HOST,
            }, _on_event)

        _open()

        def _pulse():
            while not stopped.wait(DANMAKU_INTERVAL):
                link = state["conn"]
                if link is None:
                    continue
                try:
                    link.send(SOOP_HB)
                except Exception:
                    # 断线重连期间 send 会失败，心跳线程不能因此自尽，否则重连回来就没心跳了
                    continue

        def _watch():
            # 中继偶发只挂到缓存快照（一直发 0004/0127、没有实时弹幕），10s 没实时帧就重挂一次
            while not stopped.wait(3.0):
                if state["live"] or state["attempts"] >= 2:
                    continue
                if time.time() - state["opened"] < 10:
                    continue
                state["attempts"] += 1
                link = state["conn"]
                if link is not None:
                    try:
                        link.close()
                    except Exception:
                        pass
                try:
                    _open()
                except Exception as error:
                    self._emit(emit, {"state": "retrying", "msg": "弹幕重连失败：%s" % error})

        threading.Thread(target=_pulse, daemon=True).start()
        threading.Thread(target=_watch, daemon=True).start()

        def stop():
            stopped.set()
            link = state["conn"]
            if link is not None:
                try:
                    link.close()
                except Exception:
                    pass

        return stop

    # ---------------- 入口 ----------------
    def homeContent(self, filter):
        return {"class": [{"type_id": SITE, "type_name": SITE_NAME}]}

    def homeVideoContent(self):
        return {"list": self._hot_list(1)["list"]}

    def _page_no(self, value):
        try:
            return max(1, int(value or 1))
        except (TypeError, ValueError):
            return 1

    def categoryContent(self, tid, pg, filter, extend):
        page = self._page_no(pg)
        parts = str(tid).split("|")
        kind = parts[0]
        if len(parts) == 1:
            if kind != SITE:
                raise RuntimeError("无效的分类 ID：%s" % tid)
            # 分区网格一次给全，由壳自己滚动；不分页避免后段分区摸不到
            folders = self._cat_folders()
            return {"list": folders, "page": 1, "pagecount": 1, "limit": len(folders)}
        if kind == "hot":
            return self._hot_list(page)
        if kind == "rooms" and len(parts) >= 2:
            return self._room_list(parts[1], page)
        raise RuntimeError("无效的分类 ID：%s" % tid)

    def searchContent(self, key, quick, pg="1"):
        keyword = self._clean(key)[:64]
        if not keyword:
            return {"list": [], "page": 1, "pagecount": 1, "limit": PAGE_LIMIT}
        page = self._page_no(pg)
        data = self._api("/search", {"site": SITE, "kw": keyword, "page": page})
        return self._paged(self._cards(data.get("items")), page, bool(data.get("hasMore")))

    def detailContent(self, ids):
        if not ids:
            return {"list": []}
        items = []
        for vid in ids:
            parts = str(vid).split("|")
            if len(parts) != 2 or parts[0] != "room":
                raise RuntimeError("无效的详情 ID：%s" % vid)
            items.append(self._detail(parts[1]))
        return {"list": items}

    def playerContent(self, flag, id, vipFlags):
        return self._play(id)

    def destroy(self):
        self._cats = None
        with self._lock:
            stop, self._active_stop = self._active_stop, None
            self._seq += 1
        if stop:
            try:
                stop()
            except Exception:
                pass
