#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小八影视.py — www.xiao8.tv 单站 TVBox / AVBox / 懒猫 py 源（接口版 v3，2026-11-14）

站点是 Nuxt3 站，前端全走 /api/web/*。本版把这些接口逆出来直接用，不再解析网页 HTML。

接口契约（从站点 JS 逆出，逐条真发请求验过）：
    必要头  AppId: 10011    Language: zh      少这两个一律 400「参数不对」
    导航    /api/web/lb    → video_labels[]：label/value/channel_id/sort/area/year/act/recommend
    列表    /api/web/f?videoType={value}&sort=&tag=&year=&area=&recommend=&actor_tags=&page=&size=
    搜索    /api/web/q?key=
    详情    /api/web/d?cid={cid}&page=1&size=9999
            → data.video 片名/封面/简介…
              data.episodes[] 分集（单线路片才有意义）
              data.lines[]    ★ 全部线路：name/siteId/tag/tips/total + list[]（每集 playUrls[]）
    播放    /api/web/p?cid={cid}&num={集下标，从 0 起}&format=m3u8&quality=1
                      &vid={md5("keke"+cid+num+"NEVteOSYZq")}&line={siteId}
            → data.url

九个一级分类（/api/web/lb 实测，含各自条数）：
    电视剧 dsj 5862 · 电影 dy 8492 · 综艺 zy 2648 · Netfix hw 13214 · 韩剧 kr 657
    动漫 dm 4019 · 纪录片 jlp 1383 · 少儿 se 80 · 福利 fl 3118
    （福利 在站点自己的导航里就有，不是本脚本加的；不想要就把 CATS 里那行删掉）

多线路：详情接口的 data.lines 一次给全（如《兰香如故》18 条线路，各 47 集），
    每条线路在壳里就是一个「播放线路」，选集翻页都按各自集数走。

线路写法：
  TVBox： {"key":"xiao8","name":"小八影视","type":3,"api":"./py/小八影视.py",
           "searchable":1,"quickSearch":1,"filterable":1}
  AVBox／懒猫： {"key":"xiao8","name":"小八影视","type":3,"api":"小八影视",
                 "ext":"file:///sdcard/py/小八影视.py","searchable":1,"quickSearch":1}
文件里没有 cookie、token、账号密码；AppId 10011 是站点前端公开头。
"""

import sys
import json
import hashlib
import time

import requests

sys.path.append('..')
try:
    from base.spider import Spider
except ImportError:
    class Spider:
        def init(self, extend=""):
            pass

MOBILE_UA = ("Mozilla/5.0 (Linux; Android 11; M2007J3SC Build/RKQ1.200826.002; wv) "
             "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/77.0.3865.120 "
             "MQQBrowser/6.2 TBS/045714 Mobile Safari/537.36")
SITE = "https://www.xiao8.tv"
SALT = "NEVteOSYZq"
APP_ID = "10011"
API_HEADERS = {
    "User-Agent": MOBILE_UA,
    "AppId": APP_ID,
    "Language": "zh",
    "Referer": SITE + "/",
    "Origin": SITE,
}

# 站点九个一级分类，顺序与站点导航一致
CATS = [
    {"type_id": "dsj", "type_name": "电视剧"},
    {"type_id": "dy",  "type_name": "电影"},
    {"type_id": "zy",  "type_name": "综艺"},
    {"type_id": "hw",  "type_name": "Netfix"},
    {"type_id": "kr",  "type_name": "韩剧"},
    {"type_id": "dm",  "type_name": "动漫"},
    {"type_id": "jlp", "type_name": "纪录片"},
    {"type_id": "se",  "type_name": "少儿"},
    {"type_id": "fl",  "type_name": "福利"},
]
CAT_IDS = {c["type_id"] for c in CATS}
CAT_NAME = {c["type_name"]: c["type_id"] for c in CATS}

YEARS = [str(y) for y in range(2026, 2009, -1)]
AREAS = ["内地", "中国香港", "中国台湾", "美国", "韩国", "日本", "泰国", "英国", "其他"]
SORTS = ["最热", "最新上架", "高分好评"]

_LOG = []


def _log(msg):
    _LOG.append(str(msg))
    try:
        print("[小八] " + str(msg))
    except Exception:
        pass


def api_get(path, timeout=15, **params):
    try:
        r = requests.get(SITE + path, params=params, headers=API_HEADERS, timeout=timeout)
        js = r.json()
    except Exception as e:
        _log("接口 %s 失败：%s" % (path, e))
        return None
    if js.get("code") != 200:
        _log("接口 %s 业务码 %s %s" % (path, js.get("code"), js.get("msg")))
        return None
    return js.get("data")


def md5(s):
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def _pic(it):
    for k in ("new_pic_hz", "new_pic_vt", "image_url", "cover"):
        v = it.get(k)
        if v:
            return v.replace("http://", "https://", 1)
    return ""


def _vod(it):
    tags = it.get("show_video_tags") or it.get("video_tags") or []
    remark = (it.get("sub_title") or "").strip()
    if not remark and tags:
        remark = " / ".join([str(t) for t in tags[:3]])
    return {
        "vod_id": str(it.get("cid") or ""),
        "vod_name": (it.get("title") or "").strip(),
        "vod_pic": _pic(it),
        "vod_remarks": remark,
        "vod_year": str(it.get("year") or ""),
        "vod_area": (it.get("area_name") or "").strip(),
    }


class Spider(Spider):
    def getDependence(self):
        return []

    def getName(self):
        return "小八影视"

    def init(self, extend=""):
        try:
            ext = json.loads(extend) if isinstance(extend, str) and extend else (extend or {})
        except Exception:
            ext = {}
        self.ext = ext if isinstance(ext, dict) else {}
        self._home_cache = (None, 0.0)
        self._lb = (None, 0.0)

    def isVideoFormat(self, url):
        return str(url).lower().split("?")[0].endswith((".m3u8", ".mp4", ".ts", ".mkv"))

    def manualVideoCheck(self):
        return False

    def localProxy(self, params):
        return []

    # ---------- 首页 ----------
    def _labels(self):
        """分类与筛选能力取自 /api/web/lb，缓存 30 分钟；失败回落内置表"""
        ent = self._lb
        if ent[0] and time.time() - ent[1] < 1800:
            return ent[0]
        data = api_get("/api/web/lb", timeout=8)
        labs = (data or {}).get("video_labels") if isinstance(data, dict) else None
        self._lb = (labs or None, time.time())
        return labs or None

    def homeContent(self, filter):
        labs = self._labels() if filter else None
        out = {"class": [dict(c) for c in CATS], "list": []}
        if not filter:
            return out
        flt = {}
        for c in CATS:
            lab = None
            for l in (labs or []):
                if str(l.get("value") or "") == c["type_id"]:
                    lab = l
                    break
            groups = [{"key": "sort", "name": "排序",
                       "value": [{"n": s, "v": s} for s in (lab.get("sort") if lab else SORTS) or SORTS]}]
            rec = [str(x) for x in ((lab or {}).get("recommend") or [])][:40]
            if rec:
                groups.append({"key": "tag", "name": "类型",
                               "value": [{"n": t, "v": t} for t in rec]})
            area = [str(x) for x in ((lab or {}).get("area") or [])] or AREAS
            if area:
                groups.append({"key": "area", "name": "地区",
                               "value": [{"n": a, "v": a} for a in area]})
            year = [str(x) for x in ((lab or {}).get("year") or [])] or YEARS
            groups.append({"key": "year", "name": "年份",
                           "value": [{"n": y, "v": y} for y in year]})
            flt[c["type_id"]] = groups
        out["filters"] = flt
        return out

    def homeVideoContent(self):
        ent = self._home_cache
        if ent[0] and time.time() - ent[1] < 600:
            return {"list": ent[0]}
        vods = []
        for vt in ("dy", "dsj", "dm", "zy"):
            data = api_get("/api/web/f", videoType=vt, sort="最热", page=1, size=30,
                           tag="", year="", area="", recommend="", actor_tags="")
            vods = [_vod(i) for i in ((data or {}).get("items") or [])]
            if vods:
                break
        self._home_cache = (vods, time.time())
        return {"list": vods}

    # ---------- 分类 ----------
    def categoryContent(self, tid, pg, filter, extend):
        tid = str(tid or "").strip()
        if tid not in CAT_IDS:
            tid = CAT_NAME.get(tid, tid or "dy")
        if tid not in CAT_IDS:
            return {"list": [], "page": 1, "pagecount": 1, "limit": 20, "total": 0}
        try:
            p = max(1, int(pg or 1))
        except Exception:
            p = 1
        ext = extend or {}
        data = api_get("/api/web/f", videoType=tid,
                       sort=ext.get("sort") or "最热", page=p, size=20,
                       tag=ext.get("tag") or "", year=ext.get("year") or "",
                       area=ext.get("area") or "", recommend="",
                       actor_tags=ext.get("actor_tags") or "")
        items = (data or {}).get("items") or []
        total = int((data or {}).get("count") or 0)
        return {"list": [_vod(i) for i in items], "page": p,
                "pagecount": max(1, (total + 19) // 20), "limit": 20, "total": total}

    # ---------- 搜索 ----------
    def searchContent(self, key, quick, pg="1"):
        try:
            p = max(1, int(pg or 1))
        except Exception:
            p = 1
        if p > 1:
            return {"list": []}
        data = api_get("/api/web/q", key=(key or "").strip(), timeout=20)
        return {"list": [_vod(i) for i in ((data or {}).get("items") or [])]}

    # ---------- 详情 ----------
    def detailContent(self, array):
        if not array:
            return {"list": []}
        cid = str(array[0] or "").strip()
        if not cid:
            return {"list": []}
        data = api_get("/api/web/d", cid=cid, page=1, size=9999, timeout=20)
        if not data:
            return {"list": [{"vod_id": cid, "vod_name": "小八影视", "vod_pic": "",
                              "vod_play_from": "提示",
                              "vod_play_url": "详情接口没返回数据，请稍后重试$none"}]}
        v = data.get("video") or {}
        title = v.get("title") or ""
        content = v.get("cover_description") or v.get("ai_description") or ""
        info = " ".join(x for x in (str(v.get("publish_date") or "")[:4],
                                    v.get("area_name") or "", v.get("langue") or "") if x)
        if info:
            content = (info + "\n" + content).strip()

        froms, urls = [], []
        for ln in (data.get("lines") or []):
            lst = list(ln.get("list") or [])
            if not lst:
                continue
            site = str(ln.get("siteId") or "")
            name = str(ln.get("name") or site or "线路")
            tips = str(ln.get("tips") or "")
            lst.sort(key=lambda e: int(e.get("index") or 0))
            parts = []
            for i, e in enumerate(lst):
                num = int(e.get("index") or (i + 1)) - 1
                ep = (e.get("title") or "").strip() or ("第%d集" % (i + 1))
                parts.append("%s$%s|%s|%d" % (ep, cid, site, num))
            froms.append(name + ("(" + tips + ")" if tips else ""))
            urls.append("#".join(parts))
        if not froms:
            # 单线路片：只有顶层 episodes
            eps = sorted((data.get("episodes") or []),
                         key=lambda e: int(e.get("episode_number") or 0))
            parts = []
            for i, e in enumerate(eps):
                num = int(e.get("episode_number") or (i + 1)) - 1
                ep = (e.get("title") or "").strip() or ("第%d集" % (i + 1))
                parts.append("%s$%s||%d" % (ep, cid, num))
            if parts:
                froms.append("小八线路")
                urls.append("#".join(parts))
        if not froms:
            return {"list": [{"vod_id": cid, "vod_name": title, "vod_pic": _pic(v),
                              "vod_content": content, "vod_play_from": "提示",
                              "vod_play_url": "该片暂无分集$none"}]}
        return {"list": [{"vod_id": cid, "vod_name": title, "vod_pic": _pic(v),
                          "vod_content": content,
                          "vod_year": str(v.get("publish_date") or "")[:4],
                          "vod_area": v.get("area_name") or "",
                          "vod_play_from": "$$$".join(froms),
                          "vod_play_url": "$$$".join(urls)}]}

    # ---------- 播放 ----------
    def _play(self, cid, site, num):
        for line in ([site, ""] if site else [""]):
            sign = md5("keke%s%s%s" % (cid, num, SALT))
            data = api_get("/api/web/p", cid=cid, num=num, format="m3u8", quality="1",
                           vid=sign, line=line, timeout=20)
            if isinstance(data, dict):
                url = data.get("url") or ""
                if not url:
                    for o in (data.get("otherPlayUrls") or []):
                        if o.get("playUrl"):
                            url = o["playUrl"]
                            break
                if url:
                    return url
        return ""

    def playerContent(self, flag, play_id, vipFlags):
        pid = str(play_id or "")
        if pid.startswith("http"):
            return {"parse": 0, "url": pid,
                    "header": {"User-Agent": MOBILE_UA, "Referer": SITE + "/"}}
        bits = pid.split("|")
        if len(bits) != 3:
            return {"parse": 0, "msg": "播放地址格式不对：%s" % pid[:60]}
        cid, site, num = bits[0], bits[1], bits[2]
        url = self._play(cid, site, num)
        if url:
            return {"parse": 0, "url": url,
                    "header": {"User-Agent": MOBILE_UA, "Referer": SITE + "/"}}
        # 接口这条路挂了，退回去读详情里该线路该集的直链
        data = api_get("/api/web/d", cid=cid, page=1, size=9999, timeout=20)
        for ln in ((data or {}).get("lines") or []):
            if str(ln.get("siteId") or "") != site:
                continue
            for e in (ln.get("list") or []):
                if int(e.get("index") or 0) - 1 == int(num):
                    for pu in (e.get("playUrls") or []):
                        if pu.get("url"):
                            return {"parse": 0, "url": pu["url"],
                                    "header": {"User-Agent": MOBILE_UA, "Referer": SITE + "/"}}
        return {"parse": 0, "msg": "这一集站点没给出播放地址，请换线路或换集"}


if __name__ == "__main__":
    sp = Spider()
    sp.init("{}")
    hc = sp.homeContent(True)
    print("tab:", [(c["type_id"], c["type_name"]) for c in hc["class"]])
    print("筛选组条数:", {k: len(v) for k, v in (hc.get("filters") or {}).items()})
    hv = sp.homeVideoContent()
    print("首页:", len(hv["list"]), hv["list"][0]["vod_name"] if hv["list"] else "")
    for c in hc["class"]:
        r = sp.categoryContent(c["type_id"], "1", False, {})
        print(" ", c["type_name"], r["total"], len(r["list"]), r["list"][0]["vod_name"] if r["list"] else "")
