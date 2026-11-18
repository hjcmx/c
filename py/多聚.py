# -*- coding: utf-8 -*-
"""
多聚短剧 · TVBox Python 爬虫（影视类）

适配支持 Python Spider 的 TVBox / 影视仓 / atv-player 等宿主：
    class Spider 需要实现
    init / homeContent / categoryContent / searchContent /
    detailContent / playerContent

数据来自 App 内使用的公开接口：
    {host}/maccms/meili/v2/list/{movies}/?pg=&limit=&order=&vod_class=
    {host}/maccms/meili/v2/search/{movies}/?wd=&pg=
    {host}/maccms/meili/v2/detail/{movies}/?group_key=

只使用 movies（电影/电视剧/短剧/动漫/综艺/纪录片/少儿/体育）
分类，不包含 App 里的 av 分类。

无第三方依赖，只用标准库。
"""

import json
import re
import time
import urllib.parse
import urllib.request

try:
    from base.spider import Spider as BaseSpider
except Exception:  # 本地调试时没有 base 模块
    class BaseSpider(object):
        pass


# ---------------------------------------------------------------------------
# 基础配置
# ---------------------------------------------------------------------------

HOSTS = [
    "https://macapi1.com",
    "https://macapi2.com",
    "https://macapi3.com",
    "https://macapi1.top",
    "https://macapi2.top",
    "https://macapi3.top",
]

UA = ("Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36")

API_PREFIX = "maccms/meili/v2"
CATEGORY = "movies"          # 影视分类；App 里另一个分类是 av，这里不用
PAGE_SIZE = 20               # 接口固定 20 条一页，和 App 一致

# 一级分类（接口里的 format 轴）
CLASSES = [
    {"type_id": "all", "type_name": "全部"},
    {"type_id": "movie", "type_name": "电影"},
    {"type_id": "tv", "type_name": "电视剧"},
    {"type_id": "short_drama", "type_name": "短剧"},
    {"type_id": "anime", "type_name": "动漫"},
    {"type_id": "variety", "type_name": "综艺"},
    {"type_id": "documentary", "type_name": "纪录片"},
    {"type_id": "kids", "type_name": "少儿"},
    {"type_id": "sports_event", "type_name": "体育"},
]

# 题材（genre 轴），不同一级分类使用不同的题材组
COMMON_GENRES = [
    ("action", "动作"), ("adventure", "冒险"), ("animation", "动画"),
    ("biography", "传记/纪实"), ("business", "商战/职场"), ("comedy", "喜剧"),
    ("costume", "古装"), ("disaster", "灾难"), ("drama", "剧情"),
    ("family", "家庭伦理"), ("fantasy", "奇幻/玄幻"), ("history", "历史/年代"),
    ("inspiration", "励志"), ("musical", "歌舞/音乐"), ("myth", "神话"),
    ("palace", "宫廷/权谋"), ("romance", "爱情"), ("rural", "乡村"),
    ("scifi", "科幻"), ("sports", "运动"), ("spy", "谍战"),
    ("suspense", "悬疑/犯罪"), ("thriller", "惊悚/恐怖"), ("timetravel", "穿越/重生"),
    ("urban", "都市"), ("war", "战争/军旅"), ("wuxia", "武侠/仙侠"),
    ("youth", "青春"),
]

SD_GENRES = [
    ("sd_abuse", "虐恋"), ("sd_ai", "AI漫剧"), ("sd_apocalypse", "末世/求生"),
    ("sd_baby", "萌宝/亲子"), ("sd_business", "职场商战"), ("sd_campus", "青春校园"),
    ("sd_ceo", "豪门霸总"), ("sd_comedy", "喜剧/沙雕"), ("sd_costume", "古装/古言"),
    ("sd_counter", "逆袭/打脸"), ("sd_doctor", "神医"), ("sd_ent", "娱乐圈"),
    ("sd_family", "家庭伦理"), ("sd_female", "大女主/女性成长"),
    ("sd_gameworld", "无限流/副本"), ("sd_horror", "灵异/恐怖"),
    ("sd_mafia", "黑道/谍战"), ("sd_mindread", "读心/听心声"),
    ("sd_overseas", "海外/译制"), ("sd_palace", "宫斗/宅斗"), ("sd_period", "年代"),
    ("sd_rebirth", "重生"), ("sd_revenge", "复仇"), ("sd_rural", "乡村种田"),
    ("sd_senior", "中老年/银发"), ("sd_soninlaw", "赘婿"), ("sd_suspense", "悬疑/推理"),
    ("sd_sweet", "甜宠"), ("sd_system", "系统/金手指"), ("sd_timetravel", "穿越"),
    ("sd_urban", "都市"), ("sd_warrior", "战神/兵王"), ("sd_xianxia", "玄幻/仙侠"),
]

ANIME_GENRES = [
    ("an_bl", "百合/BL"), ("an_comedy", "搞笑"), ("an_daily", "日常"),
    ("an_fantasy", "奇幻/异世界"), ("an_guochuang", "国漫"), ("an_heal", "治愈"),
    ("an_hot", "热血"), ("an_kids", "子供向"), ("an_mecha", "机战/机甲"),
    ("an_romance", "恋爱"), ("an_sports", "运动"), ("an_suspense", "悬疑"),
]

DOC_GENRES = [
    ("documentary_crime", "罪案纪实"), ("documentary_food", "美食"),
    ("documentary_history", "军事/历史"), ("documentary_nature", "自然/动物"),
    ("documentary_science", "科技/探索"), ("documentary_society", "人文/社会"),
]

VARIETY_GENRES = [
    ("va_culture", "文化"), ("va_food", "美食"), ("va_game", "竞技/游戏"),
    ("va_love", "恋综"), ("va_music", "音乐综艺"), ("va_reality", "真人秀"),
    ("va_talent", "选秀"), ("va_talk", "脱口秀"),
]

REGIONS = [
    ("region_mainland", "大陆"), ("region_hongkong", "香港"), ("region_taiwan", "台湾"),
    ("region_japan", "日本"), ("region_korea", "韩国"), ("region_us", "美国"),
    ("region_uk", "英国"), ("region_euro", "欧洲"), ("region_sea", "东南亚"),
    ("region_thailand", "泰国"), ("region_india", "印度"), ("region_other", "其它"),
]

STATUSES = [
    ("completed", "已完结"), ("ongoing", "连载中"),
    ("trailer", "预告"), ("upcoming", "即将上线"),
]

ORDERS = [("time", "最新"), ("hits", "最热"), ("score", "评分")]

GENRE_BY_TID = {
    "all": COMMON_GENRES,
    "movie": COMMON_GENRES,
    "tv": COMMON_GENRES,
    "kids": COMMON_GENRES,
    "sports_event": COMMON_GENRES,
    "short_drama": SD_GENRES,
    "anime": ANIME_GENRES,
    "documentary": DOC_GENRES,
    "variety": VARIETY_GENRES,
}

# 线路名美化（接口返回形如 baofeng-bfzym3u8）
LINE_NAMES = {
    "baofeng": "暴风", "bfzym3u8": "暴风", "uku": "U酷", "ukm3u8": "U酷",
    "jinying": "金鹰", "jinyingm3u8": "金鹰", "hongniu": "红牛", "hnm3u8": "红牛",
    "huohu": "火狐", "hhm3u8": "火狐", "guagnsu": "江苏", "gsm3u8": "江苏",
    "youzhi": "优质", "1080zyk": "优质", "subo": "速播", "subm3u8": "速播",
    "dyttzy_caiji": "电影天堂", "dyttm3u8": "电影天堂", "feifan": "非凡",
    "ffm3u8": "非凡", "suoniapi": "索尼", "snm3u8": "索尼", "wujinapi": "无尽",
    "wjm3u8": "无尽", "wsyzy": "王师爷", "wsym3u8": "王师爷", "baidu": "百度",
    "dbm3u8": "百度", "zuida": "最大", "zuidam3u8": "最大", "yaya": "丫丫",
    "yym3u8": "丫丫", "xinlang": "新浪", "xlm3u8": "新浪", "modu": "魔都",
    "modum3u8": "魔都", "360zyzz": "360", "360zy": "360", "xgzyapi": "西瓜",
    "xiguam3u8": "西瓜", "maotaizy": "茅台", "mtm3u8": "茅台", "liangzi": "量子",
    "lzm3u8": "量子", "ikunzyapi": "IKUN", "ikm3u8": "IKUN", "apiyhzy": "一号",
    "yhm3u8": "一号", "rytvapi": "如意", "rym3u8": "如意", "kuaikan": "快看",
    "kkm3u8": "快看", "hongniuzy": "红牛", "wujin": "无尽",
}


def _line_name(raw):
    """把 baofeng-bfzym3u8 这种线路名换成中文短名。"""
    raw = (raw or "").strip()
    if not raw:
        return "默认"
    key = raw.lower()
    if key in LINE_NAMES:
        return LINE_NAMES[key]
    head = re.split(r"[-_]", key)[0]
    return LINE_NAMES.get(head, raw)


def _int(v, default=0):
    try:
        return int(v)
    except Exception:
        return default


class Spider(BaseSpider):
    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def __init__(self):
        self.host = HOSTS[0]
        self.extend = ""
        self.timeout = 10
        self._host_ok = False
        self._home_cache = (0, None)
        self._detail_cache = {}

    def init(self, extend=""):
        """extend 支持 JSON：{"host": "https://macapi1.com"}；留空自动选线。"""
        self.extend = extend or ""
        if self.extend.strip():
            try:
                cfg = json.loads(self.extend)
                if isinstance(cfg, dict):
                    h = (cfg.get("host") or "").strip().rstrip("/")
                    if h.startswith("http"):
                        self.host = h
                        self._host_ok = True
                    t = cfg.get("timeout")
                    if t:
                        self.timeout = max(5, min(30, _int(t, 10)))
            except Exception:
                # 也允许直接传一个域名
                h = self.extend.strip().rstrip("/")
                if h.startswith("http"):
                    self.host = h
                    self._host_ok = True
        return None

    def getName(self):
        return "多聚短剧"

    def isVideoFormat(self, url):
        return True

    def getDependence(self):
        return []

    def manualVideoCheck(self):
        return False

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------

    def _header(self):
        return {
            "User-Agent": UA,
            "Accept": "application/json, text/plain, */*",
            "Accept-Encoding": "identity",
            "Referer": self.host.rstrip("/") + "/",
        }

    def _candidate_hosts(self):
        hosts = [self.host] + [h for h in HOSTS if h != self.host]
        return hosts

    def _get(self, path, params=None):
        """带域名故障转移的 GET，返回解析后的 JSON dict。"""
        last_err = None
        for host in self._candidate_hosts():
            url = host.rstrip("/") + "/" + path.lstrip("/")
            if params:
                url += "?" + urllib.parse.urlencode(params, doseq=True)
            try:
                req = urllib.request.Request(url, headers=self._header())
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read()
                data = json.loads(raw.decode("utf-8", "ignore"))
                if isinstance(data, dict):
                    self.host = host
                    self._host_ok = True
                    return data
                last_err = ValueError("bad response")
            except Exception as e:  # 换下一个域名
                last_err = e
                continue
        if last_err:
            raise last_err
        raise RuntimeError("request failed")

    def _api(self, action, params=None):
        return self._get(API_PREFIX + "/" + action, params)

    # ------------------------------------------------------------------
    # 数据映射
    # ------------------------------------------------------------------

    def _vod_from_item(self, it):
        """列表项 -> TVBox 列表卡片。"""
        gk = it.get("group_key") or ("wk:%s:%s" % (CATEGORY, it.get("work_id", "")))
        name = it.get("vod_name") or ""
        item = {
            "vod_id": gk,
            "vod_name": name,
            "vod_pic": it.get("vod_pic") or "",
            "vod_remarks": it.get("vod_remarks") or "",
            "vod_year": str(it.get("vod_year") or ""),
            "type_name": it.get("type_name") or "",
        }
        score = it.get("vod_score")
        if score:
            item["vod_score"] = str(score)
        return item

    @staticmethod
    def _split_play(play_from, play_url):
        """把 maccms 的 $$ / # 播放串拆成 [(线路名, [(集名, 地址)])]。"""
        froms = (play_from or "").split("$$$")
        groups = (play_url or "").split("$$$")
        result = []
        for idx, group in enumerate(groups):
            line = froms[idx] if idx < len(froms) else ""
            line = _line_name(line)
            if not line or line in [r[0] for r in result]:
                line = "%s%d" % (line or "线路", idx + 1)
            eps = []
            for part in group.split("#"):
                part = part.strip()
                if not part:
                    continue
                if "$" in part:
                    ep_name, ep_url = part.split("$", 1)
                else:
                    ep_name, ep_url = "", part
                ep_url = ep_url.strip()
                if not ep_url:
                    continue
                if ep_url.startswith("//"):
                    ep_url = "https:" + ep_url
                eps.append(((ep_name or "正片").strip(), ep_url))
            if eps:
                result.append((line, eps))
        return result

    def _detail(self, group_key):
        now = time.time()
        cached = self._detail_cache.get(group_key)
        if cached and now - cached[0] < 600:
            return cached[1]
        data = self._api("detail/%s/" % CATEGORY, {"group_key": group_key})
        items = data.get("list") or []
        if not items:
            raise RuntimeError("detail empty")
        vod = items[0]
        self._detail_cache[group_key] = (now, vod)
        return vod

    # ------------------------------------------------------------------
    # 首页
    # ------------------------------------------------------------------

    def _filters(self):
        filters = {}
        for cls in CLASSES:
            tid = cls["type_id"]
            group = []
            if tid in GENRE_BY_TID:
                group.append({
                    "key": "genre",
                    "name": "题材",
                    "init": "",
                    "value": [{"n": "全部", "v": ""}] +
                             [{"n": n, "v": v} for v, n in GENRE_BY_TID[tid]],
                })
            group.append({
                "key": "region",
                "name": "地区",
                "init": "",
                "value": [{"n": "全部", "v": ""}] +
                         [{"n": n, "v": v} for v, n in REGIONS],
            })
            group.append({
                "key": "status",
                "name": "状态",
                "init": "",
                "value": [{"n": "全部", "v": ""}] +
                         [{"n": n, "v": v} for v, n in STATUSES],
            })
            group.append({
                "key": "order",
                "name": "排序",
                "init": "time",
                "value": [{"n": n, "v": v} for v, n in ORDERS],
            })
            filters[tid] = group
        return filters

    def homeContent(self, filter=False):
        result = {"class": CLASSES, "filters": self._filters(), "list": []}

        now = time.time()
        if self._home_cache[1] is not None and now - self._home_cache[0] < 600:
            result["list"] = self._home_cache[1]
            return result

        try:
            data = self._api("list/%s/" % CATEGORY,
                             {"pg": 1, "limit": PAGE_SIZE, "order": "time"})
            items = [self._vod_from_item(x) for x in (data.get("list") or [])]
            result["list"] = items
            self._home_cache = (now, items)
        except Exception:
            pass
        return result

    def homeVideoContent(self):
        return {"list": self.homeContent(False).get("list", [])}

    # ------------------------------------------------------------------
    # 分类
    # ------------------------------------------------------------------

    @staticmethod
    def _extend_dict(extend):
        if isinstance(extend, dict):
            return extend
        if isinstance(extend, str) and extend.strip():
            try:
                v = json.loads(extend)
                if isinstance(v, dict):
                    return v
            except Exception:
                pass
        return {}

    def categoryContent(self, tid, pg, filter, extend):
        tid = str(tid or "all")
        pg = max(1, _int(pg, 1))
        ext = self._extend_dict(extend)

        order = ext.get("order") or "time"
        if order not in ("time", "hits", "score"):
            order = "time"

        classes = []
        if tid and tid not in ("all", "0"):
            classes.append(tid)
        for key in ("genre", "region", "status"):
            val = (ext.get(key) or "").strip()
            if val and val not in classes:
                classes.append(val)

        params = {"pg": pg, "limit": PAGE_SIZE, "order": order}
        if classes:
            params["vod_class"] = ",".join(classes)

        try:
            data = self._api("list/%s/" % CATEGORY, params)
        except Exception:
            return {"page": pg, "pagecount": pg, "limit": PAGE_SIZE,
                    "total": 0, "list": []}

        items = [self._vod_from_item(x) for x in (data.get("list") or [])]
        pagecount = _int(data.get("pagecount"), 0) or 500
        return {
            "page": pg,
            "pagecount": pagecount,
            "limit": _int(data.get("limit"), PAGE_SIZE) or PAGE_SIZE,
            "total": _int(data.get("total"), 0),
            "list": items,
        }

    # ------------------------------------------------------------------
    # 搜索
    # ------------------------------------------------------------------

    def searchContent(self, key, quick, pg=1, category=""):
        pg = max(1, _int(pg, 1))
        if not key:
            return {"page": pg, "pagecount": 0, "limit": PAGE_SIZE,
                    "total": 0, "list": []}
        try:
            data = self._api("search/%s/" % CATEGORY, {"wd": key, "pg": pg})
        except Exception:
            return {"page": pg, "pagecount": pg, "limit": PAGE_SIZE,
                    "total": 0, "list": []}

        items = [self._vod_from_item(x) for x in (data.get("list") or [])]
        return {
            "page": pg,
            "pagecount": _int(data.get("pagecount"), 0) or 500,
            "limit": _int(data.get("limit"), PAGE_SIZE) or PAGE_SIZE,
            "total": _int(data.get("total"), 0),
            "list": items,
        }

    # ------------------------------------------------------------------
    # 详情
    # ------------------------------------------------------------------

    def detailContent(self, ids):
        if isinstance(ids, (list, tuple)):
            group_key = str(ids[0]) if ids else ""
        else:
            group_key = str(ids or "")

        empty = {"list": []}
        if not group_key:
            return empty

        try:
            vod = self._detail(group_key)
        except Exception:
            return empty

        play_from = vod.get("vod_play_from") or ""
        play_url = vod.get("vod_play_url") or ""

        # 个别条目只有 members 里的分集，兜底合并
        groups = self._split_play(play_from, play_url)
        if not groups:
            for m in (vod.get("members") or []):
                groups += self._split_play(m.get("vod_play_from"), m.get("vod_play_url"))
        if not groups:
            return empty

        out_from = []
        out_url = []
        for line, eps in groups:
            out_from.append(line)
            out_url.append("#".join("%s$%s" % (n, u) for n, u in eps))

        content = (vod.get("vod_content") or vod.get("vod_blurb") or "").strip()
        content = re.sub(r"<[^>]+>", "", content)

        item = {
            "vod_id": group_key,
            "vod_name": vod.get("vod_name") or "",
            "vod_pic": vod.get("vod_pic") or "",
            "vod_year": str(vod.get("vod_year") or ""),
            "vod_area": str(vod.get("vod_area") or ""),
            "vod_lang": str(vod.get("vod_lang") or ""),
            "vod_remarks": str(vod.get("vod_remarks") or ""),
            "type_name": str(vod.get("type_name") or ""),
            "vod_actor": str(vod.get("vod_actor") or ""),
            "vod_director": str(vod.get("vod_director") or ""),
            "vod_content": content,
            "vod_play_from": "$$$".join(out_from),
            "vod_play_url": "$$$".join(out_url),
        }
        score = vod.get("vod_score")
        if score:
            item["vod_score"] = str(score)
        return {"list": [item]}

    # ------------------------------------------------------------------
    # 播放
    # ------------------------------------------------------------------

    def playerContent(self, flag, id, vipFlags=None):
        url = ""
        if isinstance(id, dict):
            url = id.get("url") or ""
        else:
            url = str(id or "")

        url = url.strip()
        if url.startswith("//"):
            url = "https:" + url

        header = {
            "User-Agent": UA,
            "Referer": self.host.rstrip("/") + "/",
            "Accept": "*/*",
        }

        if url.startswith("http"):
            return {"parse": 0, "url": url, "header": header, "flag": flag}

        # 不是直链就交给宿主解析
        return {"parse": 1, "url": url, "header": header, "flag": flag}
