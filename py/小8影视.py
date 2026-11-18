# -*- coding: utf-8 -*-
"""
小八影视（https://www.xiao8.tv/）TVBox / LookPro Python 爬虫。

依赖：requests、pycryptodome
配置示例：
{"key":"py_xiao8","name":"小八影视(PY)","type":3,"api":"./py_xiao8.py","searchable":1,"quickSearch":1,"filterable":1}
"""

import base64
import copy
import hashlib
import json
import math
import random
import re
import uuid
from urllib.parse import quote, urljoin, urlsplit

import requests
from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.PublicKey import RSA
from Crypto.Util.Padding import pad, unpad


class Spider:
    hosts = ["https://www.xiao8.tv", "https://xiao8.tv"]
    user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/142.0.0.0 Safari/537.36"
    )
    public_key = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAxDGjAoinx62PWXuCliLM
Hq5TPrgIvAib+nsb9riac+ylLpVZTMpHkSI2CPmgz7ZMJY8/NQgtX42HHjV1qQj7
7ngHbwvYcpSXMwRuTiJL3uFr+1gSGH8pcPGonOe/zUSlE7CkA9JRUQUNW2BuQpQI
sCQ2MiwjRyxtADnS0Wh/pd+fkwa7x1l5Ke7sQMu13MOuzIHkckzaSjsSL9SroI9G
U2UT+0ja/9MdD9jg0vLEX0blTM5NGeHhAQXhCWDIAVkxYe7O7mZjoz1c5qjb1WnS
RjywrACJUmeYg5qtdz09T2FH5oa9zXwNlnCTUGFigZAxSBq1cEX8rBQKMurffYOp
JwIDAQAB
-----END PUBLIC KEY-----"""

    categories = [
        {"type_id": "dsj", "type_name": "电视剧"},
        {"type_id": "dy", "type_name": "电影"},
        {"type_id": "zy", "type_name": "综艺"},
        {"type_id": "hw", "type_name": "Netfix"},
        {"type_id": "kr", "type_name": "韩剧"},
        {"type_id": "dm", "type_name": "动漫"},
        {"type_id": "jlp", "type_name": "纪录片"},
        {"type_id": "se", "type_name": "少儿"},
        {"type_id": "fl", "type_name": "福利"},
    ]

    def __init__(self):
        self.session = requests.Session()
        self.hosts = list(self.hosts)
        self._host_index = 0
        self.host = self.hosts[0]
        self._navigation_data = None
        self.device_id = str(uuid.uuid4())
        self.timeout = 25
        self._set_host(self.host)

    def _set_host(self, host):
        self.host = host.rstrip("/")
        self.session.headers.update(
            {
                "User-Agent": self.user_agent,
                "Referer": self.host + "/",
                "Origin": self.host,
            }
        )

    def init(self, extend=""):
        pass

    def getName(self):
        return "小八影视"

    def destroy(self):
        self.session.close()

    @staticmethod
    def _text(data, *keys):
        if not isinstance(data, dict):
            return ""
        for key in keys:
            value = data.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return ""

    @staticmethod
    def _people(value):
        if isinstance(value, list):
            return ",".join(str(x).strip() for x in value if str(x).strip())
        return str(value or "").strip()

    def _pic(self, value, title=""):
        pic = str(value or "").strip().replace("\\/", "/")
        if not pic:
            return ""
        if pic.startswith("//"):
            pic = "https:" + pic
        else:
            pic = urljoin(self.host + "/", pic)
        # 与官网一致，优先使用 HTTPS，避免壳子拦截混合内容。
        if pic.lower().startswith("http://"):
            pic = "https://" + pic[7:]
        host = urlsplit(pic).netloc.lower()
        # 这两个源站图床目前已失效，直接回退为标题封面，避免长时间加载和破图。
        if host in {"static.yfsp.tv", "static.tripdata.app"}:
            return (
                "https://via.placeholder.com/400x560/202938/FFFFFF?text="
                + quote(title or "暂无封面", safe="")
            )
        # 图床不能带小八的 Referer，应按图片来源设置，否则部分封面会 403。
        referers = {
            "hdslb.com": "https://www.bilibili.com/",
            "iqiyipic.com": "https://www.iqiyi.com/",
        }
        for domain, referer in referers.items():
            if host == domain or host.endswith("." + domain):
                return f"{pic}@Referer={referer}@User-Agent={self.user_agent}"
        return pic

    def _decrypt(self, value, key, iv=b"0" * 16):
        try:
            raw = base64.b64decode(value.strip(), validate=True)
            if len(raw) < 16 or len(raw) % 16:
                return None
            decrypted = AES.new(key.encode("utf-8"), AES.MODE_CBC, iv).decrypt(raw)
            return unpad(decrypted, AES.block_size).decode("utf-8")
        except (ValueError, UnicodeDecodeError, TypeError):
            return None

    def _request_once(self, path, params):
        # 与网页一致：随机 AES 密钥加密查询串，再用 RSA 加密 AES 密钥。
        query = "&".join(
            f"{key}={value}"
            for key, value in params.items()
            if value is not None and str(value) != ""
        )
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
        aes_key = "".join(random.SystemRandom().choice(alphabet) for _ in range(16))
        iv = b"0" * 16
        encrypted = AES.new(aes_key.encode("ascii"), AES.MODE_CBC, iv).encrypt(
            pad(query.encode("utf-8"), AES.block_size)
        )
        rsa = PKCS1_v1_5.new(RSA.import_key(self.public_key))
        encrypted_key = base64.b64encode(rsa.encrypt(aes_key.encode("ascii"))).decode()
        iv_text = base64.b64encode(iv).decode()
        cipher_json = json.dumps(
            {
                "Key": encrypted_key,
                "Iv": iv_text,
                "Edata": base64.b64encode(encrypted).decode(),
            },
            separators=(",", ":"),
        )
        response = self.session.get(
            self.host + path,
            params={"data": cipher_json},
            headers={
                "AppId": "10011",
                "Language": "zh",
                "DeviceId": self.device_id,
                "ClientUserAgent": self.user_agent,
                "dt-aes-key": encrypted_key,
                "dt-aes-iv": iv_text,
                "dt-encrypted": "1",
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        response.encoding = "utf-8"
        text = response.text.strip()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            decrypted = self._decrypt(text, aes_key)
            if decrypted is None:
                raise ValueError("接口返回了无法识别的内容")
            payload = json.loads(decrypted)

        if isinstance(payload, dict) and isinstance(payload.get("Edata"), str):
            decrypted = self._decrypt(payload["Edata"], aes_key)
            if decrypted is not None:
                payload = json.loads(decrypted)

        if isinstance(payload, dict) and isinstance(payload.get("data"), str):
            decrypted = self._decrypt(payload["data"], aes_key)
            if decrypted is not None:
                try:
                    payload["data"] = json.loads(decrypted)
                except json.JSONDecodeError:
                    payload["data"] = decrypted
        return payload

    def _request(self, path, params):
        last_error = None
        # 每次请求从当前可用域名开始；网络错误、HTTP 错误或无效响应自动切换。
        for offset in range(len(self.hosts)):
            index = (self._host_index + offset) % len(self.hosts)
            self._set_host(self.hosts[index])
            try:
                payload = self._request_once(path, params)
                if not isinstance(payload, dict):
                    raise ValueError("接口返回格式错误")
                self._host_index = index
                return payload
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
        raise ValueError(f"所有可用域名均请求失败：{last_error}")

    def _data(self, path, params):
        payload = self._request(path, params)
        if not isinstance(payload, dict) or str(payload.get("code")) != "200":
            message = payload.get("msg", "接口请求失败") if isinstance(payload, dict) else "接口请求失败"
            raise ValueError(str(message))
        return payload.get("data") or {}

    @staticmethod
    def _items(data):
        if isinstance(data, list):
            return data
        if not isinstance(data, dict):
            return []
        for key in ("items", "list", "records", "rows"):
            if isinstance(data.get(key), list):
                return data[key]
        return []

    def _vod(self, item):
        vid = self._text(item, "cid", "id", "vod_id")
        if not vid:
            return None
        pic = self._text(
            item,
            "new_pic_vt",
            "new_pic_hz",
            "cover",
            "pic",
            "vod_pic",
            "pic_vt",
            "pic_hz",
        )
        remarks = self._text(
            item,
            "note",
            "remarks",
            "vod_remarks",
            "statusLabel",
            "status_label",
            "update_status",
        )
        if not remarks:
            episodes = self._text(item, "episode_count", "episodes")
            if episodes and episodes != "1":
                remarks = f"更新至{episodes}集"
        title = self._text(item, "title", "name", "vod_name") or "未知标题"
        return {
            "vod_id": vid,
            "vod_name": title,
            "vod_pic": self._pic(pic, title),
            "vod_remarks": remarks,
            "vod_year": self._text(item, "year", "vod_year"),
            "vod_area": self._text(item, "area_name", "area", "vod_area"),
            "vod_score": self._text(item, "v_score", "score", "douban_score"),
        }

    def _list_result(self, data, page=1, limit=24):
        items = [self._vod(item) for item in self._items(data)]
        videos = [item for item in items if item]
        total = 0
        if isinstance(data, dict):
            try:
                total = int(data.get("count") or data.get("total") or 0)
            except (TypeError, ValueError):
                total = 0
        return {
            "list": videos,
            "page": page,
            "pagecount": max(page, math.ceil(total / limit)) if total else page,
            "limit": limit,
            "total": total or len(videos),
        }

    @staticmethod
    def _build_filters(label):
        filters = []
        for key, name in (
            ("recommend", "类型"),
            ("area", "地区"),
            ("year", "年份"),
            ("sort", "排序"),
        ):
            values = label.get(key)
            if not isinstance(values, list) or not values:
                continue
            options = [] if key == "sort" else [{"n": "全部", "v": ""}]
            seen = set()
            for value in values:
                text = str(value or "").strip()
                if not text or text in seen:
                    continue
                seen.add(text)
                options.append({"n": text, "v": text})
            if options:
                filters.append({"key": key, "name": name, "value": options})
        return filters

    def _navigation(self):
        if self._navigation_data is None:
            self._navigation_data = self._data("/api/web/lb", {})
        return self._navigation_data

    def homeContent(self, filter=False):
        try:
            labels = self._navigation().get("video_labels") or []
        except (requests.RequestException, ValueError):
            labels = []
        if labels:
            categories, filters = [], {}
            for label in labels:
                if not isinstance(label, dict):
                    continue
                value = self._text(label, "value", "id")
                if not value:
                    continue
                name = self._text(label, "label", "name") or value
                categories.append({"type_id": value, "type_name": name})
                filters[value] = self._build_filters(label)
            if categories:
                return {"class": categories, "filters": filters}
        # 配置接口临时失败时只显示各分类共有的排序，不再套用错误的完整筛选。
        fallback = {"sort": ["最热", "最新上架", "高分好评"]}
        return {
            "class": copy.deepcopy(self.categories),
            "filters": {
                category["type_id"]: self._build_filters(fallback)
                for category in self.categories
            },
        }

    def homeVideoContent(self):
        data = self._data(
            "/api/web/f",
            {
                "videoType": "main",
                "sort": "最热",
                "page": 1,
                "size": 24,
                "actor_tags": "",
            },
        )
        return self._list_result(data)

    def categoryContent(self, tid, pg, filter, extend):
        try:
            page = max(1, int(pg))
        except (TypeError, ValueError):
            page = 1
        if isinstance(extend, str):
            try:
                extend = json.loads(extend) if extend.strip() else {}
            except json.JSONDecodeError:
                extend = {}
        extend = extend if isinstance(extend, dict) else {}
        video_type = str(tid).strip() or "dy"
        tag = extend.get("recommend") or extend.get("tag") or ""
        params = {
            "videoType": video_type or "dy",
            "sort": extend.get("sort") or "最热",
            "tag": tag,
            "recommend": tag,
            "page": page,
            "size": 24,
            "actor_tags": "",
            "year": extend.get("year") or "",
            "area": extend.get("area") or "",
        }
        data = self._data("/api/web/f", params)
        return self._list_result(data, page=page)

    def detailContent(self, ids):
        cid = ids[0] if isinstance(ids, (list, tuple)) else ids
        data = self._data(
            "/api/web/d", {"cid": str(cid), "page": 1, "size": 9999}
        )
        video = data.get("video") or data.get("detail") or {}
        episodes = data.get("episodes") or video.get("episodes") or []
        lines = data.get("lines") or video.get("lines") or []
        if not lines:
            lines = video.get("source") or [{"name": "默认线路", "siteId": ""}]
        platform = self._text(video, "playVidPlatform", "play_vid_platform") or "keke"
        play_from, play_url = [], []
        for line in lines:
            if not isinstance(line, dict):
                continue
            site = self._text(line, "siteId", "platform", "id")
            line_name = self._text(line, "name", "title") or site or "默认线路"
            line_episodes = line.get("list") or episodes
            episode_values = []
            for index, episode in enumerate(line_episodes):
                if not isinstance(episode, dict):
                    continue
                title = self._text(episode, "title", "play_title", "name")
                if not title:
                    title = "正片" if len(line_episodes) == 1 else f"第{index + 1}集"
                direct_url = self._text(episode, "url", "playUrl", "play_url")
                play_urls = episode.get("playUrls")
                if not direct_url and isinstance(play_urls, list):
                    for candidate in play_urls:
                        if isinstance(candidate, dict) and candidate.get("url"):
                            direct_url = str(candidate["url"])
                            break
                try:
                    number = int(episode.get("index", index + 1)) - 1
                except (TypeError, ValueError):
                    number = index
                token = self._encode_token(
                    {
                        "cid": str(cid),
                        "num": max(0, number),
                        "line": site,
                        "platform": platform,
                        "url": direct_url,
                    }
                )
                episode_values.append(
                    f"{title.replace('$', '').replace('#', '')}${token}"
                )
            if episode_values:
                play_from.append(line_name.replace("$", ""))
                play_url.append("#".join(episode_values))
        remarks = self._text(video, "note", "remarks", "statusLabel")
        if not remarks and episodes:
            remarks = f"共{len(episodes)}集"
        result = {
            "vod_id": str(cid),
            "vod_name": self._text(video, "title", "name", "vod_name"),
            "vod_sub": self._text(video, "second_title", "sub_title"),
            "vod_pic": self._text(video, "new_pic_vt", "new_pic_hz", "cover", "pic"),
            "vod_remarks": remarks,
            "vod_year": self._text(video, "year"),
            "vod_area": self._text(video, "area_name", "area"),
            "vod_lang": self._text(video, "language", "lang"),
            "vod_score": self._text(video, "v_score", "score", "douban_score"),
            "vod_actor": self._people(
                video.get("leading_actor_tags") or video.get("actors") or video.get("actor")
            ),
            "vod_director": self._people(
                video.get("director_tags") or video.get("director")
            ),
            "vod_class": self._text(video, "genre", "type", "channelCategory"),
            "vod_content": self._text(
                video, "cover_description", "desc", "description", "vod_content"
            ),
            "vod_play_from": "$$$".join(play_from),
            "vod_play_url": "$$$".join(play_url),
        }
        result["vod_pic"] = self._pic(result["vod_pic"], result["vod_name"])
        return {"list": [result]}

    def searchContent(self, key, quick=False, pg=1):
        data = self._data("/api/web/q", {"key": str(key).strip()})
        return self._list_result(data)

    @staticmethod
    def _encode_token(data):
        raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    @staticmethod
    def _decode_token(token):
        token += "=" * (-len(token) % 4)
        return json.loads(base64.urlsafe_b64decode(token).decode("utf-8"))

    def _find_url(self, value, depth=0):
        if depth > 6 or value is None:
            return ""
        if isinstance(value, str):
            text = value.strip().replace("\\/", "/")
            if text.startswith("//"):
                return "https:" + text
            if text.startswith("http://") or text.startswith("https://"):
                return text
            if text[:1] in "[{":
                try:
                    return self._find_url(json.loads(text), depth + 1)
                except json.JSONDecodeError:
                    pass
            match = re.search(r"https?://[^\s\"'<>\\]+", text)
            return match.group(0) if match else ""
        if isinstance(value, list):
            for item in value:
                found = self._find_url(item, depth + 1)
                if found:
                    return found
            return ""
        if isinstance(value, dict):
            keys = ("url", "playUrl", "play_url", "m3u8", "link", "data", "video", "result")
            for key in keys:
                if key in value:
                    found = self._find_url(value[key], depth + 1)
                    if found:
                        return found
            for item in value.values():
                found = self._find_url(item, depth + 1)
                if found:
                    return found
        return ""

    def playerContent(self, flag, id, vipFlags=None):
        if str(id).startswith(("http://", "https://")):
            url = str(id)
        else:
            token = self._decode_token(str(id))
            if token.get("url"):
                url = urljoin(self.host + "/", token["url"])
            else:
                cid = str(token["cid"])
                number = max(0, int(token.get("num", 0)))
                platform = token.get("platform") or "keke"
                vid = hashlib.md5(
                    f"{platform}{cid}{number}NEVteOSYZq".encode("utf-8")
                ).hexdigest()
                payload = self._request(
                    "/api/web/p",
                    {
                        "cid": cid,
                        "num": number,
                        "format": "m3u8",
                        "quality": "1",
                        "vid": vid,
                        "line": token.get("line") or "",
                    },
                )
                if not isinstance(payload, dict) or str(payload.get("code")) != "200":
                    message = payload.get("msg", "播放接口请求失败") if isinstance(payload, dict) else "播放接口请求失败"
                    raise ValueError(str(message))
                url = self._find_url(payload.get("data"))
                if not url:
                    url = self._find_url(payload)
        if not url:
            raise ValueError("未获取到播放地址")
        return {
            "parse": 0,
            "playUrl": "",
            "url": url,
            "header": {"User-Agent": self.user_agent, "Referer": self.host + "/"},
        }

    def playContent(self, flag, id, vipFlags=None):
        return self.playerContent(flag, id, vipFlags)
