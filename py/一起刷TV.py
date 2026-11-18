# -*- coding: utf-8 -*-
# 本资源来源于互联网公开渠道，仅可用于个人学习爬虫技术。
# 严禁将其用于任何商业用途，下载后请于 24 小时内删除，搜索结果均来自源站，本人不承担任何责任。
# 一起刷TV v1.3.2 (com.example.movietv) 协议逆向:
#   salt="kandianying123"  sign=md5(md5(request_id+salt)+salt)
#   响应=base64(AES-128-CBC(JSON))  key=md5(salt)hex[:16] iv=hex[16:]
#   全端点 POST JSON: classify_id 必须传字符串

import base64
import gzip
import hashlib
import io
import json
import ssl
import urllib.error
import urllib.request
import uuid

try:
    from base.spider import Spider as _BaseSpider
except Exception:
    _BaseSpider = object

try:
    from Crypto.Cipher import AES as _AES

    def _aes_cbc_dec(key, iv, raw):
        c = _AES.new(key, _AES.MODE_CBC, iv)
        return c.decrypt(raw)
except Exception:
    _AES = None

    def _aes_cbc_dec(key, iv, raw):
        return _pure_aes_cbc_decrypt(key, iv, raw)

try:
    from Crypto.Util.Padding import unpad as _unpad
except Exception:
    def _unpad(data, k):
        return data[: -data[-1]]

SALT = "kandianying123"


# ---------------- 纯Python AES-128 解密兜底 (无 Crypto 环境时启用) ----------------
_SBOX = [
    0x63,0x7C,0x77,0x7B,0xF2,0x6B,0x6F,0xC5,0x30,0x01,0x67,0x2B,0xFE,0xD7,0xAB,0x76,
    0xCA,0x82,0xC9,0x7D,0xFA,0x59,0x47,0xF0,0xAD,0xD4,0xA2,0xAF,0x9C,0xA4,0x72,0xC0,
    0xB7,0xFD,0x93,0x26,0x36,0x3F,0xF7,0xCC,0x34,0xA5,0xE5,0xF1,0x71,0xD8,0x31,0x15,
    0x04,0xC7,0x23,0xC3,0x18,0x96,0x05,0x9A,0x07,0x12,0x80,0xE2,0xEB,0x27,0xB2,0x75,
    0x09,0x83,0x2C,0x1A,0x1B,0x6E,0x5A,0xA0,0x52,0x3B,0xD6,0xB3,0x29,0xE3,0x2F,0x84,
    0x53,0xD1,0x00,0xED,0x20,0xFC,0xB1,0x5B,0x6A,0xCB,0xBE,0x39,0x4A,0x4C,0x58,0xCF,
    0xD0,0xEF,0xAA,0xFB,0x43,0x4D,0x33,0x85,0x45,0xF9,0x02,0x7F,0x50,0x3C,0x9F,0xA8,
    0x51,0xA3,0x40,0x8F,0x92,0x9D,0x38,0xF5,0xBC,0xB6,0xDA,0x21,0x10,0xFF,0xF3,0xD2,
    0xCD,0x0C,0x13,0xEC,0x5F,0x97,0x44,0x17,0xC4,0xA7,0x7E,0x3D,0x64,0x5D,0x19,0x73,
    0x60,0x81,0x4F,0xDC,0x22,0x2A,0x90,0x88,0x46,0xEE,0xB8,0x14,0xDE,0x5E,0x0B,0xDB,
    0xE0,0x32,0x3A,0x0A,0x49,0x06,0x24,0x5C,0xC2,0xD3,0xAC,0x62,0x91,0x95,0xE4,0x79,
    0xE7,0xC8,0x37,0x6D,0x8D,0xD5,0x4E,0xA9,0x6C,0x56,0xF4,0xEA,0x65,0x7A,0xAE,0x08,
    0xBA,0x78,0x25,0x2E,0x1C,0xA6,0xB4,0xC6,0xE8,0xDD,0x74,0x1F,0x4B,0xBD,0x8B,0x8A,
    0x70,0x3E,0xB5,0x66,0x48,0x03,0xF6,0x0E,0x61,0x35,0x57,0xB9,0x86,0xC1,0x1D,0x9E,
    0xE1,0xF8,0x98,0x11,0x69,0xD9,0x8E,0x94,0x9B,0x1E,0x87,0xE9,0xCE,0x55,0x28,0xDF,
    0x8C,0xA1,0x89,0x0D,0xBF,0xE6,0x42,0x68,0x41,0x99,0x2D,0x0F,0xB0,0x54,0xBB,0x16]
_INV_SBOX = [0] * 256
for _i, _v in enumerate(_SBOX):
    _INV_SBOX[_v] = _i


def _xtime(a):
    a <<= 1
    return (a ^ 0x1B) & 0xFF if a & 0x100 else a


def _mul(a, b):
    r = 0
    while b:
        if b & 1:
            r ^= a
        a = _xtime(a)
        b >>= 1
    return r


def _expand_key(key):
    rcon = 1
    w = [list(key[i:i + 4]) for i in range(0, 16, 4)]
    for i in range(4, 44):
        t = list(w[i - 1])
        if i % 4 == 0:
            t = t[1:] + t[:1]
            t = [_SBOX[b] for b in t]
            t[0] ^= rcon
            rcon = _xtime(rcon)
        w.append([w[i - 4][j] ^ t[j] for j in range(4)])
    return [b for r in range(11) for c in range(4) for b in w[4 * r + c]]


def _inv_shift_rows(s):
    # 列主序: 元素 i -> 行 i%4, 列 i//4; 行 r 循环右移 r
    for r in range(1, 4):
        row = [s[r + 4 * c] for c in range(4)]
        row = row[-r:] + row[:-r]
        for c in range(4):
            s[r + 4 * c] = row[c]


def _inv_mix_columns(s):
    # state[r][c] = s[r+4c]: 列 c 是连续 4 字节 s[4c..4c+3]
    for c in range(4):
        a0, a1, a2, a3 = s[4 * c], s[4 * c + 1], s[4 * c + 2], s[4 * c + 3]
        s[4 * c + 0] = _mul(a0, 14) ^ _mul(a1, 11) ^ _mul(a2, 13) ^ _mul(a3, 9)
        s[4 * c + 1] = _mul(a0, 9) ^ _mul(a1, 14) ^ _mul(a2, 11) ^ _mul(a3, 13)
        s[4 * c + 2] = _mul(a0, 13) ^ _mul(a1, 9) ^ _mul(a2, 14) ^ _mul(a3, 11)
        s[4 * c + 3] = _mul(a0, 11) ^ _mul(a1, 13) ^ _mul(a2, 9) ^ _mul(a3, 14)


def _pure_aes_cbc_decrypt(key, iv, raw):
    rk = _expand_key(key)
    out = bytearray()
    prev = bytes(iv)
    for off in range(0, len(raw) - len(raw) % 16, 16):
        blk = bytearray(raw[off:off + 16])
        for i in range(16):
            blk[i] ^= rk[160 + i]          # AddRoundKey(rk[10])
        for rnd in range(9, -1, -1):
            _inv_shift_rows(blk)
            for i in range(16):
                blk[i] = _INV_SBOX[blk[i]]
            for i in range(16):
                blk[i] ^= rk[rnd * 16 + i]
            if rnd:
                _inv_mix_columns(blk)
        for i in range(16):
            blk[i] ^= prev[i]
        out += blk
        prev = raw[off:off + 16]
    return bytes(out)
# ---------------- AES 兜底结束 ----------------
_MD5HEX = hashlib.md5(SALT.encode()).hexdigest().lower()
AES_KEY = _MD5HEX[:16].encode()
AES_IV = _MD5HEX[16:].encode()

OSS_HOST_URL = "http://yqshost.oss-accelerate.aliyuncs.com/host.json"
HOSTS = ["https://yqsb.ejjjaakq.com", "https://ansj.ejjjaakq.com"]
PHOTO_HOSTS = ["https://fmt.fhsafwd.com", "https://nsp.lnaahhj.com", "https://ysf.ctecdn.com"]
UA = "okhttp/4.9.3"
VERSION = "1.3.2"
TIMEOUT = 12

DEVICE_ID = str(uuid.uuid4())
_CUR = [0]
_CONFIG = {}
_FILTERS = {}
_SEARCH_CUR = {}

_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE


def _decrypt_b64(b64text):
    raw = base64.b64decode(b64text.strip())
    data = _aes_cbc_dec(AES_KEY, AES_IV, raw)
    data = _unpad(data, 16)
    return data.decode("utf-8")


def _sign(rid):
    return hashlib.md5((hashlib.md5((rid + SALT).encode()).hexdigest() + SALT).encode()).hexdigest()


def _refresh_hosts():
    try:
        req = urllib.request.Request(OSS_HOST_URL, headers={"User-Agent": UA})
        raw = urllib.request.urlopen(req, timeout=8, context=_ctx).read()
        arr = json.loads(base64.b64decode(raw)).get("url") or []
        hosts = [h.rstrip("/") for h in arr if h.startswith("http")]
        if hosts:
            HOSTS[:] = hosts
    except Exception:
        pass


def _api(path, extra=None, retry=True):
    """带域名轮换的 API 调用；返回 data 或 None"""
    total = len(HOSTS)
    last = None
    for attempt in range(total + 1):
        i = _CUR[0] % total
        host = HOSTS[i]
        rid = str(uuid.uuid4())
        body = {
            "app_id": "1",
            "device_info": "tv",
            "uuid": DEVICE_ID,
            "version": VERSION,
            "request_id": rid,
            "sign": _sign(rid),
        }
        if extra:
            body.update(extra)
        data = json.dumps(body, separators=(",", ":")).encode()
        req = urllib.request.Request(
            host + "/" + path, data=data,
            headers={"User-Agent": UA, "Content-Type": "application/json; charset=UTF-8",
                     "Accept-Encoding": "gzip"})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ctx) as r:
                raw = r.read()
                if (r.headers.get("Content-Encoding") or "") == "gzip":
                    raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
                txt = raw.decode("utf-8", "ignore")
                try:
                    obj = json.loads(txt)
                except Exception:
                    obj = json.loads(_decrypt_b64(txt))
                if isinstance(obj, dict) and obj.get("code") == 200:
                    _CUR[0] = i
                    return obj.get("data")
                last = obj.get("msg") if isinstance(obj, dict) else "bad response"
                # 业务错误换重试无意义
                if isinstance(obj, dict) and obj.get("code") == 400:
                    return None
        except Exception as e:
            last = str(e)
            _CUR[0] = i + 1
            continue
    # 全部域名失败: 刷新域名池后重试一轮
    if retry:
        _refresh_hosts()
        return _api(path, extra, retry=False)
    if last:
        raise RuntimeError(last)
    return None


def _pic(url):
    u = (url or "").strip()
    if not u:
        return ""
    if u.startswith("http"):
        return u
    for ph in PHOTO_HOSTS:
        return ph.rstrip("/") + "/" + u.lstrip("/")
    return u


_ZW = "\u200b\u200c\u200d\ufeff"


def _clean(s):
    s = (s or "").strip().strip(_ZW).strip()
    return s


def _vod(v):
    return {
        "vod_id": str(v.get("videoid", "")),
        "vod_name": _clean(v.get("title")),
        "vod_pic": _pic(v.get("verticalurl") or v.get("horizontalurl")),
        "vod_remarks": _clean(v.get("remark") or v.get("hdvideomark")),
    }


def _filters_of(classify_id):
    if classify_id in _FILTERS:
        return _FILTERS[classify_id]
    out = []
    try:
        d = _api("api/filter", {"classify_id": str(classify_id)})
        names = {"region_val": "地区", "year": "年份", "tags": "类型", "filter_type": "排序"}
        for flt in (d or {}).get("filters") or []:
            key = flt.get("filter_param")
            if key not in names:
                continue
            vals = [{"n": t.get("name"), "v": str(t.get("id", ""))}
                    for t in flt.get("filter_tag") or []]
            if vals:
                out.append({"key": key, "name": names[key], "value": vals})
    except Exception:
        pass
    if not out:
        out = [
            {"key": "region_val", "name": "地区", "value": [{"n": "全部", "v": ""}]},
            {"key": "year", "name": "年份", "value": [{"n": "全部", "v": ""}]},
            {"key": "tags", "name": "类型", "value": [{"n": "全部", "v": ""}]},
            {"key": "filter_type", "name": "排序", "value": [
                {"n": "最新", "v": "new"}, {"n": "人气", "v": "popularity"}, {"n": "评分", "v": "score"}]},
        ]
    _FILTERS[classify_id] = out
    return out


class Spider(_BaseSpider):

    def getName(self):
        return "一起刷TV┃[py]"

    def init(self, extend=""):
        try:
            cfg = _api("api/init") or {}
            if isinstance(cfg, dict):
                _CONFIG.update(cfg)
                ph = cfg.get("photo_domain")
                if isinstance(ph, list) and ph:
                    PHOTO_HOSTS[:] = [h.rstrip("/") for h in ph if h]
        except Exception:
            pass

    def homeContent(self, filter):
        cats = []
        try:
            d = _api("api/index/header") or {}
            for c in d.get("classifylist") or []:
                cats.append({"type_id": str(c.get("classifyid")),
                             "type_name": c.get("classifyname")})
        except Exception:
            cats = [{"type_id": "1", "type_name": "电影"},
                    {"type_id": "2", "type_name": "电视剧"}]
        rank = {"电影": 0, "电视剧": 1, "动漫": 2, "综艺": 3, "短剧": 4, "奈飞Netflix": 5}
        cats.sort(key=lambda c: rank.get(c["type_name"], 9))
        filters = {}
        for c in cats:
            try:
                filters[c["type_id"]] = _filters_of(c["type_id"])
            except Exception:
                pass
        lst = []
        try:
            body = _api("api/tv/index/body", {"page_num": 1}) or {}
            lst = [_vod(v) for v in (body.get("hotvodlist") or [])[:40]]
        except Exception:
            pass
        out = {"class": cats, "list": lst}
        if filter and filters:
            out["filters"] = filters
        return out

    def homeVideoContent(self):
        lst = []
        try:
            body = _api("api/tv/index/body", {"page_num": 1}) or {}
            lst = [_vod(v) for v in (body.get("hotvodlist") or [])[:40]]
        except Exception:
            pass
        return {"list": lst}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            page = max(1, int(pg))
        except Exception:
            page = 1
        ext = extend if isinstance(extend, dict) else {}
        if isinstance(extend, str) and extend.strip():
            try:
                ext = json.loads(extend)
            except Exception:
                ext = {}
        params = {
            "classify_id": str(tid),
            "region_val": str(ext.get("region_val", "") or ""),
            "year": str(ext.get("year", "") or ""),
            "tags": str(ext.get("tags", "") or ""),
            "filter_type": str(ext.get("filter_type", "") or "popularity"),
            "page_num": page,
        }
        items, nxt = [], page
        try:
            d = _api("api/vod/search", params) or {}
            items = [_vod(v) for v in (d.get("video_list") or [])]
        except Exception:
            pass
        # 排序值拉满时后端会自然返回空列表, 用空列表截断翻页
        pagecount = page + 1 if items else page
        return {"page": page, "pagecount": pagecount, "limit": 20,
                "total": pagecount * 20, "list": items}

    def detailContent(self, array):
        vid = str(array[0])
        try:
            d = _api("api/vod/info", {"video_id": int(vid)}) or {}
        except Exception:
            d = {}
        if not d:
            return {"list": []}
        shows, urls = [], []
        for line in d.get("player_list") or []:
            name = line.get("player_name") or "线路"
            if line.get("remark"):
                name += "·" + str(line["remark"])
            if line.get("is_vip"):
                name += "[VIP]"
            eps = []
            for ep in line.get("ep_list") or []:
                eid = str(ep.get("ep_id", ""))
                if eid:
                    eps.append("%s$%s|%s" % (ep.get("ep_name") or "播放", eid, line.get("play_line_id")))
            if eps:
                shows.append(name)
                urls.append("#".join(eps))
        actors = "/".join(a.get("name", "") for a in (d.get("actor_list") or [])[:8])
        directors = "/".join(a.get("name", "") for a in (d.get("director_list") or [])[:3])
        tags = "/".join(t.get("tag_name", "") for t in (d.get("tag_list") or []))
        return {"list": [{
            "vod_id": vid,
            "vod_name": _clean(d.get("video_name")) or vid,
            "vod_pic": _pic(d.get("vertical_url") or d.get("horizontal_url")),
            "type_name": tags,
            "vod_year": str(d.get("year") or ""),
            "vod_area": str(d.get("area_name") or ""),
            "vod_remarks": str(d.get("update_remark") or ""),
            "vod_actor": actors,
            "vod_director": directors,
            "vod_content": (d.get("introduction") or "").strip()[:800],
            "vod_play_from": "$$$".join(shows),
            "vod_play_url": "$$$".join(urls),
        }]}

    def searchContent(self, key, quick, pg="1"):
        try:
            page = max(1, int(pg))
        except Exception:
            page = 1
        kw = str(key or "").strip()
        if not kw:
            return {"list": [], "page": page}
        if page == 1:
            _SEARCH_CUR[kw] = ""
        nxt = _SEARCH_CUR.get(kw, "")
        if page > 1 and not nxt:
            return {"list": [], "page": page}
        items = []
        try:
            d = _api("api/search/search",
                     {"keyword": kw, "next_value": str(nxt), "page_num": page}) or {}
            items = [_vod(v) for v in (d.get("video_list") or [])]
            nv = str(d.get("next_value") or "")
            if nv:
                _SEARCH_CUR[kw] = nv
            else:
                _SEARCH_CUR[kw] = ""
        except Exception:
            pass
        return {"list": items, "page": page}

    def playerContent(self, flag, id, vipFlags):
        raw = str(id or "")
        parts = raw.split("|")
        ep_id = parts[0] if parts and parts[0].isdigit() else "0"
        line_id = parts[1] if len(parts) > 1 and parts[1].isdigit() else "0"
        resolution = "sd"
        try:
            d = _api("api/vod/epDetail", {"ep_id": int(ep_id)}) or {}
            res_list = d.get("ep_detail_list") or []
            pick = ""
            for r in res_list:
                if r.get("default_select"):
                    pick = r.get("resolution") or ""
                    break
            if not pick and res_list:
                pick = res_list[0].get("resolution") or ""
            if pick:
                resolution = pick
        except Exception:
            pass
        url = ""
        try:
            d = _api("api/vod/play_url",
                     {"ep_id": int(ep_id), "resolution": resolution,
                      "play_line_id": int(line_id)}) or {}
            url = str(d.get("play_url") or "")
        except Exception:
            pass
        if not url:
            return {"parse": 1, "url": ""}
        hdr = {"User-Agent": UA}
        ct = "video/mp4" if ".mp4" in url.lower().split("?")[0] else "application/vnd.apple.mpegurl"
        return {"parse": 0, "url": url, "header": hdr, "contentType": ct}

    def isVideoFormat(self, url):
        return False

    def isTextFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False

    def destroy(self):
        return "destroy"


if __name__ == "__main__":
    # 本地自测
    sp = Spider()
    sp.init("")
    hc = sp.homeContent(True)
    print("cats:", [(c["type_id"], c["type_name"]) for c in hc["class"]])
    print("home:", len(hc["list"]), hc["list"][:2])
    cc = sp.categoryContent("2", "1", True, {"filter_type": "popularity"})
    print("cat2 p1:", len(cc["list"]), cc["list"][:2])
    sc = sp.searchContent("谷雨", False, "1")
    print("search:", len(sc["list"]), sc["list"][:2])
    dc = sp.detailContent([sc["list"][0]["vod_id"]]) if sc["list"] else {"list": []}
    if dc["list"]:
        v = dc["list"][0]
        print("detail:", v["vod_name"], v["vod_play_from"])
        flag0 = v["vod_play_url"].split("$$$")[0].split("#")[0]
        rid = flag0.split("$")[1]
        pc = sp.playerContent("", rid, "")
        print("play:", pc.get("url"))
