# -*- coding: utf-8 -*-
"""
全聚合（暴风线路）TVBox py 源
==========================================================
来源：全聚合 2.1.2 (com.vlive.vst) 登录后下发的 /api/v3/json 站点清单
      sites[2] 暴风 -> https://bfzyapi.com/api.php/provide/vod/
三底座：技能包12（方法论） / memory（历史档案） / 蜘蛛模板 v2 生成器（骨架契约）

实测（2026-11-14）：
  - 采集接口 ac=list：49 个真实分类 / 172164 条 / 8609 页
  - 筛选 year / area / lang 均实测有效，同分类不同 v 前 3 条不同
  - 搜索 ac=detail&wd= 中文 quote 编码：庆余年 1631 条、流浪地球 710 条
  - 筛选 + 翻页组合有效：t=21&year=2024 pg1/pg2 结果不同，pagecount=14
  - 详情线路真实为 1 条 bfzym3u8，不自造双线 / 不铺解析线
  - 播放直链实测 200 application/vnd.apple.mpegurl（中文路径需 quote）

2026-11-14 二轮复测（分类逐类抽样 144 条播放链）：
  - 49 个分类中「体育赛事」(t=53) 站点真实 0 条，点进去必然空白 -> homeContent 动态剔除
  - 48 个有效分类 138/144 抽样可播（95.8%），其余 6 条是站点自身单条死链
    （404 / CDN 超时），同一域名其它片仍 200，属数据问题，不在源内自造备用线
  - 全程零「整类不可播」分类；空分类即时剔除 + 后台复核（可自动恢复），异常 fail-open

契约：独立 class Spider（不继承 base.spider），header 为 dict，自带 _get；
      仅用 Python 3.8 及以下语法，壳内置无 requests 时自动降级 urllib。
"""
import json
import re
import time

try:
    from urllib.request import Request, urlopen
    from urllib.parse import urlencode, quote, urlsplit, urlunsplit
except ImportError:  # Python 2 兼容（老壳）
    from urllib2 import Request, urlopen
    from urllib import urlencode, quote
    from urlparse import urlsplit, urlunsplit

try:
    import requests
except Exception:
    requests = None

try:
    import ssl
    _SSL_CTX = ssl.create_default_context()
    _SSL_CTX.check_hostname = False
    _SSL_CTX.verify_mode = ssl.CERT_NONE
except Exception:
    _SSL_CTX = None


class Spider(object):
    def __init__(self):
        self.site = "https://bfzyapi.com"
        self.api = "https://bfzyapi.com/api.php/provide/vod/"
        self.header = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/108.0.0.0 Safari/537.36",
            "Referer": "https://bfzyapi.com/",
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        self._classes = None
        self._filters = None
        self._active = None
        self._active_key = None
        self._probe_done = False

    # ---------------- 基础方法 ----------------
    def getName(self):
        return "全聚合·暴风"

    def init(self, extend=""):
        return ""

    def getDependence(self):
        return []

    def manualVideoCheck(self):
        return False

    def isVideoFormat(self, url):
        if not url:
            return False
        u = str(url).lower()
        return ".m3u8" in u or ".mp4" in u or u.endswith((".flv", ".mkv", ".ts"))

    def destroy(self):
        pass

    def action(self, action):
        return {}

    def _get(self, url, timeout=12):
        """requests 优先，urllib 降级；返回文本，失败返回空串。"""
        if requests is not None:
            try:
                r = requests.get(url, headers=self.header, timeout=timeout)
                if r.status_code < 400:
                    return r.text
            except Exception:
                pass
        for _ in range(2):
            try:
                req = Request(url, headers=self.header)
                if _SSL_CTX is not None:
                    resp = urlopen(req, timeout=timeout, context=_SSL_CTX)
                else:
                    resp = urlopen(req, timeout=timeout)
                raw = resp.read()
                try:
                    return raw.decode("utf-8", "ignore")
                except Exception:
                    return raw.decode("gbk", "ignore")
            except Exception:
                time.sleep(0.2)
        return ""

    def _json(self, params, timeout=12):
        """params 为 [(k, v), ...]，中文一律 urlencode（内部 quote）。"""
        url = self.api + "?" + urlencode(params)
        txt = self._get(url, timeout)
        if not txt:
            return {}
        try:
            return json.loads(txt)
        except Exception:
            return {}

    @staticmethod
    def _enc_url(u):
        """播放链含中文路径时按 UTF-8 quote，否则壳内会报 ascii 编码错。"""
        if not u:
            return u
        try:
            p = urlsplit(u)
            return urlunsplit((p.scheme, p.netloc, quote(p.path, "/%"), p.query, p.fragment))
        except Exception:
            return u

    @staticmethod
    def _vod(x):
        """列表项 -> TVBox VOD 字典。"""
        return {
            "vod_id": str(x.get("vod_id", "")),
            "vod_name": str(x.get("vod_name", "")),
            "vod_pic": str(x.get("vod_pic", "") or x.get("vod_pic_thumb", "") or ""),
            "vod_remarks": str(x.get("vod_remarks", "") or x.get("vod_serial", "") or ""),
            "vod_year": str(x.get("vod_year", "") or ""),
            "vod_area": str(x.get("vod_area", "") or ""),
        }

    # ---------------- 分类 + 筛选器 ----------------
    def _build_filters(self, classes):
        """三个维度全部逐 v 实测有效；无效果的排序/字母维度不做。"""
        years = ["2026", "2025", "2024", "2023", "2022", "2021", "2020", "2019", "2018"]
        areas = ["大陆", "香港", "台湾", "美国", "日本", "韩国", "英国", "泰国", "印度", "法国"]
        langs = ["国语", "粤语", "英语", "日语", "韩语", "法语", "泰语"]

        def opts(vals):
            out = [{"n": "全部", "v": ""}]
            for v in vals:
                out.append({"n": v, "v": v})
            return out

        groups = [
            {"key": "year", "name": "年份", "value": opts(years)},
            {"key": "area", "name": "地区", "value": opts(areas)},
            {"key": "lang", "name": "语言", "value": opts(langs)},
        ]
        out = {}
        for c in classes:
            out[str(c["type_id"])] = groups
        return out

    # 2026-11-14 逐类实测 total=0 的分类，首页即时剔除（零网络开销）
    KNOWN_EMPTY = {("53", "体育赛事")}

    def _active_types(self, classes):
        """剔除站点真实 0 条的分类（点进去空白，最容易被当成「播放不了」）。

        同步：按实测名单即时过滤，首页零额外延迟。
        后台：并发复核全部分类（含已剔除者，恢复后自动加回），结果供下次首页用。
        任何异常 / 无线程库一律 fail-open 保留原分类，绝不误删。
        """
        key = tuple(c["type_id"] for c in classes)
        if self._active_key == key and self._active is not None:
            return self._active
        fast = [c for c in classes
                if (c["type_id"], c["type_name"]) not in self.KNOWN_EMPTY] or classes
        self._active_key = key
        self._active = fast
        self._spawn_probe(key, classes)
        return fast

    def _spawn_probe(self, key, classes):
        try:
            from threading import Thread
            from concurrent.futures import ThreadPoolExecutor
        except Exception:
            return

        def probe(c):
            d = self._json([("ac", "list"), ("t", c["type_id"]), ("pg", "1")], 3)
            if not d:  # 接口抖动：保守保留
                return c
            try:
                if int(d.get("total") or 0) == 0 and not d.get("list"):
                    return None
            except Exception:
                pass
            return c

        def work():
            try:
                with ThreadPoolExecutor(max_workers=6) as ex:
                    got = list(ex.map(probe, classes))
                fresh = [c for c in got if c is not None] or classes
                self._active = fresh
                self._active_key = key
                self._filters = self._build_filters(fresh)
                self._probe_done = True
            except Exception:
                self._probe_done = True

        try:
            t = Thread(target=work)
            t.daemon = True
            t.start()
        except Exception:
            pass

    def homeContent(self, filter):
        data = self._json([("ac", "list"), ("pg", "1")])
        classes = []
        for c in data.get("class", []):
            tid = c.get("type_id")
            name = c.get("type_name")
            if tid is None or not name:
                continue
            classes.append({"type_id": str(tid), "type_name": str(name)})
        classes = self._active_types(classes)
        self._classes = classes
        self._filters = self._build_filters(classes)
        result = {
            "class": classes,
            "list": [self._vod(x) for x in data.get("list", [])],
        }
        if filter:
            result["filters"] = self._filters
        return result

    def homeVideoContent(self):
        data = self._json([("ac", "list"), ("pg", "1")])
        return {"list": [self._vod(x) for x in data.get("list", [])]}

    @staticmethod
    def _parse_extend(extend):
        """extend 兼容 dict / str(JSON 或 k=v&k=v) / list[(k,v)]。"""
        out = {}
        if not extend:
            return out
        if isinstance(extend, dict):
            for k, v in extend.items():
                if v not in (None, ""):
                    out[str(k)] = str(v)
            return out
        if isinstance(extend, (list, tuple)):
            for item in extend:
                try:
                    k, v = item[0], item[1]
                    if v not in (None, ""):
                        out[str(k)] = str(v)
                except Exception:
                    pass
            return out
        s = str(extend).strip()
        if s.startswith("{"):
            try:
                for k, v in json.loads(s).items():
                    if v not in (None, ""):
                        out[str(k)] = str(v)
                return out
            except Exception:
                return out
        for part in re.split(r"[&,;]", s):
            if "=" in part:
                k, v = part.split("=", 1)
                if v.strip():
                    out[k.strip()] = v.strip()
        return out

    def categoryContent(self, tid, pg, filter, extend):
        ext = self._parse_extend(extend)
        params = [("ac", "list"), ("t", str(tid)), ("pg", str(pg or 1))]
        # 只拼实测有效的三个维度，多余参数不传（传了会污染结果）
        for key in ("year", "area", "lang"):
            if ext.get(key):
                params.append((key, ext[key]))
        data = self._json(params)
        videos = [self._vod(x) for x in data.get("list", [])]
        try:
            pagecount = int(data.get("pagecount") or 0)
        except Exception:
            pagecount = 0
        if pagecount < 1:
            try:
                total = int(data.get("total") or 0)
                limit = max(len(videos), 1)
                pagecount = (total + limit - 1) // limit
            except Exception:
                pagecount = 1
        try:
            page = int(pg or 1)
        except Exception:
            page = 1
        return {
            "list": videos,
            "page": page,
            "pagecount": pagecount,
            "limit": max(len(videos), 20),
            "total": int(data.get("total") or 0),
        }

    # ---------------- 详情（线路按真实条数） ----------------
    def detailContent(self, array):
        ids = []
        for item in array or []:
            if isinstance(item, (list, tuple)):
                item = item[0] if item else ""
            vid = str(item).split("$")[-1]
            if vid and vid not in ids:
                ids.append(vid)
        if not ids:
            return {"list": []}
        data = self._json([("ac", "detail"), ("ids", ",".join(ids))])
        out = []
        for x in data.get("list", []):
            # 站点真实几条线路就几条：原样透传，不拆分、不自造、不加备用线
            play_from = str(x.get("vod_play_from", "") or "")
            play_url = str(x.get("vod_play_url", "") or "")
            out.append({
                "vod_id": str(x.get("vod_id", "")),
                "vod_name": str(x.get("vod_name", "")),
                "vod_pic": str(x.get("vod_pic", "") or ""),
                "type_name": str(x.get("type_name", "") or ""),
                "vod_year": str(x.get("vod_year", "") or ""),
                "vod_area": str(x.get("vod_area", "") or ""),
                "vod_remarks": str(x.get("vod_remarks", "") or ""),
                "vod_actor": str(x.get("vod_actor", "") or ""),
                "vod_director": str(x.get("vod_director", "") or ""),
                "vod_content": str(x.get("vod_blurb", "") or x.get("vod_content", "") or ""),
                "vod_play_from": play_from,
                "vod_play_url": play_url,
            })
        return {"list": out}

    # ---------------- 搜索（站点自己的 wd 路由，中文 quote） ----------------
    def searchContent(self, key, quick, pg=1):
        if not key:
            return {"list": []}
        try:
            kw = key.encode("utf-8")
        except Exception:
            kw = key
        url = self.api + "?ac=detail&wd=" + quote(kw) + "&pg=" + str(pg or 1)
        txt = self._get(url)
        try:
            data = json.loads(txt)
        except Exception:
            data = {}
        return {"list": [self._vod(x) for x in data.get("list", [])],
                "page": int(pg or 1),
                "pagecount": int(data.get("pagecount") or 1),
                "total": int(data.get("total") or 0)}

    # ---------------- 播放（直链 parse=0） ----------------
    def playerContent(self, flag, id, vipFlags):
        url = str(id or "")
        if "$" in url:
            url = url.split("$")[-1]
        url = self._enc_url(url)
        return {
            "parse": 0,
            "play": "",
            "url": url,
            "header": {
                "User-Agent": self.header["User-Agent"],
                "Referer": self.site + "/",
            },
        }
