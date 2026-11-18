# -*- coding: utf-8 -*-
"""
看剧AI（kanju46.com）TVBox / FongMi / 默影视 通用 py 源
==========================================================
与本本地包内其它 py 源保持同一契约：
  - 独立 class Spider（不强制继承 base.spider，缺失时自动降级）
  - 方法：init / getName / homeContent / categoryContent / detailContent /
          searchContent / playerContent
  - 只依赖标准库，壳内无 requests 也能跑；兼容 Python 3.8 语法

设计要点：
  1. 站点播放地址由私有签名接口下发（HMAC-SHA256：路径 + 时间戳 + nonce），
     这里在前端签名规则基础上直接生成请求头。
  2. 详情页不预解析直链：vod_play_url 只存「剧集 token|集号」，等真正点播时
     在 playerContent 里现解析。原因有两个——
       · 站点直链是带 x-expires 的 CDN 签名地址，约 50 分钟失效，预存必过期；
       · 一季十几集，预解析会让详情页等待十几秒甚至超时。
  3. 解析不到可播地址时不伪造地址，返回空 url，由客户端提示，避免"能点不能看"。
"""

import hashlib
import hmac
import json
import secrets
import ssl
import time

from concurrent.futures import ThreadPoolExecutor

try:
    from urllib.request import Request, urlopen
    from urllib.parse import urlencode, quote
except ImportError:  # Python 2 老壳兜底
    from urllib2 import Request, urlopen
    from urllib import urlencode, quote

try:
    from base.spider import Spider as BaseSpider
except Exception:
    class BaseSpider(object):
        pass


BASE = "https://kanju46.com"
SIGN_KEY = "557d0e4ae929f438da6bd84412374e6086b8af09b3fed54bf22601d5bf8c54a0"
BUILD_VERSION = "dianyingtiantang-v2026.11.12.3-worker-flag-fix-46f791897b69-web"
PROTOCOL_VERSION = "2026-07-05.library-v2.playback-v1"
UA = ("Mozilla/5.0 (Linux; Android 12; Pixel 6) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36")

CLASSES = [
    {"type_id": "movie", "type_name": "电影"},
    {"type_id": "series", "type_name": "电视剧"},
    {"type_id": "variety", "type_name": "综艺"},
    {"type_id": "anime", "type_name": "动漫"},
    {"type_id": "documentary", "type_name": "纪录片"},
]

# 解析线路优先顺序（实测能出 mp4 / m3u8 的线路靠前）
LINE_ORDER = [
    "bytevod-lv3", "bytedance", "bytevod-lv2", "official-mj-hls",
    "bytevod-yun-1080", "dong", "bytevod-cloudflare",
]
MEDIA_HOSTS = ("bytetos.com", "onewsvod.com", "samtory.cn", "byteimg.com")
IMAGE_HINTS = (".image", "-image", ".webp", ".jpg", ".jpeg", ".png", ".gif")

try:
    _SSL = ssl.create_default_context()
    _SSL.check_hostname = False
    _SSL.verify_mode = ssl.CERT_NONE
except Exception:
    _SSL = None


class Spider(BaseSpider):
    def __init__(self):
        self.name = "看剧AI"
        self.host = BASE
        self.header = {"User-Agent": UA, "Referer": BASE + "/"}
        self._cache = {}

    def init(self, extend=""):
        self._cache = {}
        return None

    def getName(self):
        return self.name

    # ------------------------------------------------------------------ #
    # 列表
    # ------------------------------------------------------------------ #
    def homeContent(self, filter):
        out = {"class": CLASSES, "filters": {}, "parse": 0, "jx": 0, "list": []}
        try:
            cards = self._browse("movie", 1, 20)
            if not cards:
                cards = self._browse("series", 1, 20)
            out["list"] = [self._vod(c) for c in cards]
        except Exception:
            pass
        return out

    def homeVideoContent(self):
        return {"list": [self._vod(c) for c in self._browse("movie", 1, 20)]}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            page = int(pg or 1)
        except Exception:
            page = 1
        cards = self._browse(tid or "movie", page, 20)
        lst = [self._vod(c) for c in cards]
        return {
            "page": page,
            "pagecount": page + 1 if len(lst) >= 20 else page,
            "limit": 20,
            "total": 9999,
            "list": lst,
            "parse": 0,
            "jx": 0,
        }

    def searchContent(self, key, quick, pg="1"):
        if not key:
            return {"list": [], "page": 1, "pagecount": 1, "total": 0}
        try:
            page = int(pg or 1)
        except Exception:
            page = 1
        cards = self._search(key, 20)
        lst = [self._vod(c) for c in cards]
        return {
            "page": page,
            "pagecount": 1,
            "limit": 20,
            "total": len(lst),
            "list": lst,
            "parse": 0,
            "jx": 0,
        }

    # ------------------------------------------------------------------ #
    # 详情：只登记剧集 token，不预先解析直链
    # ------------------------------------------------------------------ #
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

        out = []
        for public_id in ids[:3]:
            try:
                data = self._api("GET", "/v1/catalog/" + quote(public_id))
            except Exception:
                continue
            if not isinstance(data, dict) or not data.get("id"):
                continue
            eps = [e for e in (data.get("episodes") or []) if e.get("token")]
            eps.sort(key=lambda e: e.get("number") or 0)
            if not eps:
                continue
            # 站点播放器里的「线路」在这里铺成多个播放源，可在客户端里直接切换
            shows, groups = self._play_groups(eps)
            out.append({
                "vod_id": data.get("id") or public_id,
                "vod_name": data.get("title") or "",
                "vod_pic": data.get("poster_url") or "",
                "type_name": data.get("content_kind") or "",
                "vod_year": str(data.get("year") or ""),
                "vod_area": data.get("area") or "",
                "vod_remarks": data.get("remarks") or "",
                "vod_actor": "、".join(data.get("actors") or []),
                "vod_director": "、".join(data.get("directors") or []),
                "vod_content": data.get("description") or "",
                "vod_play_from": "$$$".join(shows),
                "vod_play_url": "$$$".join(groups),
            })
        return {"list": out, "parse": 0, "jx": 0}

    # ------------------------------------------------------------------ #
    # 播放：点播时才解析，拿到的是带时效的真实直链
    # ------------------------------------------------------------------ #
    def playerContent(self, flag, id, vipFlags):
        header = {"User-Agent": UA, "Referer": BASE + "/"}
        raw = str(id or "")
        if "$" in raw:
            raw = raw.split("$")[-1]
        if "|" not in raw:
            return {"parse": 0, "playUrl": "", "url": raw, "jx": 0, "header": header}

        parts = raw.split("|")
        if len(parts) < 2:
            return {"parse": 0, "playUrl": "", "url": raw, "jx": 0, "header": header}

        token = parts[0]
        try:
            number = int(parts[1] or 1)
        except Exception:
            number = 1
        provider = parts[2] if len(parts) > 2 and parts[2] else None

        url = self._resolve(token, number, provider)
        return {"parse": 0, "playUrl": "", "url": url, "jx": 0, "header": header}

    # ------------------------------------------------------------------ #
    # 线路：详情里铺成多播放源，点播时按选中的线路解析
    # ------------------------------------------------------------------ #
    def _play_groups(self, eps):
        """把每集 token 组装成「自动」+ 可用线路 多个播放源分组。

        站点给的线路里混着大量已失效 / 需登录的线，直接全铺开会在客户端里
        出现一堆点了不能播的源。这里先用第一集做一次探活，只保留真能出流的
        线路，外加 4K 线路（4K 稀缺，失败也留一条备选）。
        """
        first = eps[0]
        number = first.get("number") or 0
        lines = self._line_options(first.get("token"), number)
        kept = self._keep_lines(first.get("token"), number, lines)

        shows = ["自动"]
        groups = ["#".join("第%s集$%s|%s" % (e.get("number") or 0, e.get("token"), e.get("number") or 0)
                           for e in eps)]
        for line in kept:
            pid = str(line.get("provider_id") or "")
            label = str(line.get("label") or pid)
            shows.append(label)
            groups.append("#".join(
                "第%s集$%s|%s|%s" % (e.get("number") or 0, e.get("token"), e.get("number") or 0, pid)
                for e in eps))
        return shows, groups

    def _keep_lines(self, token, number, lines):
        """并发探活：留下能出流的线路，以及 4K 线路。"""
        cands, seen = [], set()
        for line in sorted(lines, key=self._rank):
            pid = str(line.get("provider_id") or "")
            if not pid or pid in seen:
                continue
            seen.add(pid)
            cands.append(line)
            if len(cands) >= 6:
                break

        def alive(line):
            pid = str(line.get("provider_id") or "")
            try:
                return pid, bool(self._resolve(token, number, pid, fast=True))
            except Exception:
                return pid, False

        status = {}
        try:
            with ThreadPoolExecutor(max_workers=6) as pool:
                for pid, ok in pool.map(alive, cands):
                    status[pid] = ok
        except Exception:
            status = dict((str(l.get("provider_id") or ""), True) for l in cands)

        order = [str(l.get("provider_id") or "") for l in cands if status.get(str(l.get("provider_id") or ""))]
        self._cache["alive|%s|%s" % (token, number)] = (time.time() + 600, order)

        kept = []
        for line in cands:
            pid = str(line.get("provider_id") or "")
            label = str(line.get("label") or "")
            if status.get(pid) or "4k" in label.lower():
                kept.append(line)
        # 一条都探不通时只保留 4K（如果站点给了）；否则线路区只留「自动」，
        # 不再把死线摆出来假装能播
        if not kept:
            kept = [l for l in cands if "4k" in str(l.get("label") or "").lower()][:2]
        return kept

    @staticmethod
    def _rank(line):
        provider = str(line.get("provider_id") or "")
        try:
            pref = LINE_ORDER.index(provider)
        except ValueError:
            pref = len(LINE_ORDER)
        return (pref, 0 if line.get("selected") else 1, -(line.get("preference_weight") or 0))

    def _line_options(self, token, number):
        cache_key = "lines|%s|%s" % (token, number)
        hit = self._cache.get(cache_key)
        if hit and hit[0] > time.time():
            return hit[1]
        q = urlencode({"view": "compact", "episode_index": number})
        data = self._api("GET", "/v1/playback/resolve/%s?%s" % (quote(token), q))
        lines = data.get("line_options") or [] if isinstance(data, dict) else []
        self._cache[cache_key] = (time.time() + 600, lines)
        return lines

    # ------------------------------------------------------------------ #
    # 站点接口
    # ------------------------------------------------------------------ #
    def _api(self, method, path_query, payload=None, timeout=8, retry=True):
        headers = {
            "accept": "application/json",
            "user-agent": UA,
            "referer": BASE + "/",
            "x-ai-movie-client-name": "dianyingtiantang-frontend",
            "x-ai-movie-client-version": "1.0.0",
            "x-ai-movie-build-version": BUILD_VERSION,
            "x-ai-movie-protocol-version": PROTOCOL_VERSION,
        }
        headers.update(self._sign(method, path_query))
        body = None
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["content-type"] = "application/json"
        req = Request(BASE + path_query, data=body, headers=headers, method=method)
        try:
            resp = urlopen(req, timeout=timeout, context=_SSL) if _SSL else urlopen(req, timeout=timeout)
            return json.loads(resp.read().decode("utf-8", "replace"))
        except Exception:
            if retry:
                time.sleep(0.4)
                return self._api(method, path_query, payload, timeout, False)
            return {}

    def _sign(self, method, path_query):
        ts = str(int(time.time() * 1000))
        nonce = secrets.token_hex(16) if hasattr(secrets, "token_hex") else hashlib.md5(
            ("%s%s" % (time.time(), ts)).encode()).hexdigest()
        canon = "%s\n%s\n%s\n%s" % (method, path_query, ts, nonce)
        sig = hmac.new(SIGN_KEY.encode("utf-8"), canon.encode("utf-8"), hashlib.sha256).hexdigest()
        return {
            "x-ai-movie-timestamp": ts,
            "x-ai-movie-nonce": nonce,
            "x-ai-movie-signature": sig,
        }

    def _browse(self, kind, page, limit):
        q = urlencode({"kind": kind, "page": page, "limit": limit})
        data = self._api("GET", "/v1/browse/catalog?" + q)
        return data.get("cards") or [] if isinstance(data, dict) else []

    def _search(self, keyword, limit):
        q = urlencode({"q": keyword, "page": 1, "limit": limit})
        data = self._api("GET", "/v1/browse/catalog?" + q)
        return data.get("cards") or [] if isinstance(data, dict) else []

    def _resolve(self, token, number, provider=None, fast=False):
        """剧集 token -> 真实直链。

        provider 指定时只走该线路；否则先走探活确认可用的线路，再退回按优先级试。
        fast=True 供探活使用：超时更短且不重试，免得详情页被一批死线拖住。
        """
        cache_key = "%s|%s|%s" % (token, number, provider or "auto")
        hit = self._cache.get(cache_key)
        if hit and hit[0] > time.time():
            return hit[1]

        lines = self._line_options(token, number)
        if not lines:
            return ""

        if provider:
            picked = [l for l in lines if str(l.get("provider_id") or "") == provider][:1]
        else:
            alive = self._cache.get("alive|%s|%s" % (token, number))
            order = alive[1] if alive and alive[0] > time.time() else []
            if order:
                for pid in order[:3]:
                    url = self._resolve(token, number, pid)
                    if url:
                        self._cache[cache_key] = (time.time() + 600, url)
                        return url
            picked = sorted(lines, key=self._rank)[:2]

        for line in picked:
            raw = str(line.get("resolve_ticket") or line.get("url") or "")
            ticket = raw[len("resolve://"):] if raw.startswith("resolve://") else raw
            if not ticket:
                continue
            got = self._api("POST", "/v1/playback/resolve-line?view=compact", {"ticket": ticket},
                            4 if fast else 6, not fast)
            # 地址在返回体的 line 节点里；个别情况也可能平铺在顶层，两种都兼容
            node = got.get("line") if isinstance(got, dict) else None
            if not isinstance(node, dict):
                node = got if isinstance(got, dict) else {}
            url = str(node.get("url") or "").strip()
            if url and not url.startswith("resolve://") and self._is_media(url):
                self._cache[cache_key] = (time.time() + 600, url)
                return url
        # 失败也短缓存，避免探活与点播反复打同一批死线
        if not fast:
            self._cache[cache_key] = (time.time() + 300, "")
        return ""

    @staticmethod
    def _is_media(url):
        low = url.lower()
        if any(h in low for h in IMAGE_HINTS):
            return False
        if ".m3u8" in low or ".mp4" in low:
            return True
        try:
            host = low.split("://", 1)[1].split("/", 1)[0]
        except Exception:
            host = low
        return any(h in host for h in MEDIA_HOSTS)

    @staticmethod
    def _vod(card):
        avail = card.get("availability") or {}
        return {
            "vod_id": card.get("id") or "",
            "vod_name": card.get("title") or "",
            "vod_pic": card.get("poster_url") or "",
            "type_name": card.get("content_kind") or "",
            "vod_year": str(card.get("year") or ""),
            "vod_area": card.get("area") or "",
            "vod_lang": card.get("language") or "",
            "vod_remarks": card.get("remarks") or avail.get("label") or "",
            "vod_actor": "、".join(card.get("actors") or []),
            "vod_director": "、".join(card.get("directors") or []),
            "vod_content": "",
        }