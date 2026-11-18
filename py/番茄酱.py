# -*- coding: utf-8 -*-
"""
番茄酱影视（fanqe.cc）TVBox / FongMi type=3 单文件 Python 源
================================================================

站点侦察结论（2026-11-15 实测）：
    1. 站点类型：macCMS10 二次开发 + 自建模板（SSR，非 SPA），页面由服务端直出，
       无 CSRF/签名参数，仅需普通浏览器 UA 即可访问；/static/ds3/js/fq_guard.js
       只是防 F12 的前端脚本，对 urllib 无影响。
    2. 首页：/  返回分类导航（电影 1 / 电视剧 2 / 综艺 3 / 动漫 4 / 体育 46）
       与 72 张卡片，卡片自带 分类 · 备注。
    3. 分类页：/index.php/vod/show/id/<tid>.html，每页 40 条，
       总条数在 `$('.hl-total').html('51623')`，尾页在 `/page/<n>.html` 链接。
       筛选项以路径段形式生效：/show/area/<地区>/year/<年份>/id/<tid>/page/<n>.html。
    4. 详情页：/index.php/vod/detail/id/<vod_id>.html，线路以
       `a.vod-playerUrl[data-form]` 呈现，每线路对应一个 `.anthology-list-box`，
       两者位置一一对应（已用 5 线路剧集与 2 线路电影交叉验证）。
       4K 线路是没有 data-form 的弹窗按钮（需 App），不在本源代码内。
    5. 播放页：/index.php/vod/play/id/<id>/sid/<线路>/nid/<集>.html，
       页内 `var player_aaaa = {...}` 携带真实播放地址。
       实测 jsm3u8 线路返回可直连 m3u8（AES-128，key 为相对路径 enc.key），
       xiguam3u8 返回 `na:xiguam3u8:...` 占位符，kkytest/kky2/kky3 返回
       `dNmhhk-2-1` 形式的播放器代码，均需站点前端播放器参与，无法直接取直链。
    6. 搜索：/index.php/vod/search.html?wd=<关键词>，单页出结果（实测 3 条），
       带 page 段翻页返回空列表 —— 因此 pg>1 直接返回空，不再发请求。
    7. ajax/data 接口（/index.php/ajax/data?mid=1&tid=<type_id>&limit=20&page=1）
       只在 tid 为叶子分类时可用，父分类（1/2/3/4/46）会被忽略并返回全站数据，
       因此分类列表统一走 HTML 解析，不使用该接口。

已处理的坑（对应模板第四节，按频率）：
    FIX-01 解析成功但黑屏：playerContent 取到 http 直链后必须真下头部校验
           （m3u8 校验 #EXTM3U，mp4 校验非图片魔数），失败回退 parse=1。
    FIX-02 图片流伪装视频：mp4/mkv 分支读取前 512 字节，命中 PNG/JPEG/GIF/BMP/WEBP
           魔数即判失败，不下发给客户端。
    FIX-03 探测/播放不带站点 Referer：分片在 p.jisuts.com 第三方 CDN，实测带站点
           Referer 反而易被 403，header 只给 UA。
    FIX-04 m3u8 相对路径：enc.key 为相对路径，TVBox 以 m3u8 地址为基准解析，
           因此直链必须保持原样，不能自行拼接或改写。
    FIX-05 搜索分页：站点不支持搜索结果翻页，pg>1 直接空列表，避免重复请求第 1 页。
    FIX-06 ids 双类型：detailContent 的 ids 兼容 list 与 str（含 "a,b" 逗号形式）。
    FIX-07 &amp; 转义：所有文本字段统一走 html.unescape，避免标题/简介带实体残渣。
    FIX-08 分页重复：列表按 vod_id 去重（同卡片图片与标题各有一个链接），
           实测第 1/2 页无交集，total 与 pagecount 来自站点自身数据。

实测耗时（沙箱 Python 3.12，2026-11-15，单次冷请求，单位秒）：
    homeContent      1.2s / 72 条（首次冷启动 8.5s，站点首包较慢）
    categoryContent  0.9~2.2s / 40 条（pagecount=1291，total=51623）
    detailContent    1.0~2.2s / 5 线路（含 31 集剧集与单集电影两种排版）
    searchContent    2.7s / 3 条（关键词「热搜」；pg>1 不发请求）
    playerContent    2.7~3.5s（含真下 m3u8 头校验），parse=0
"""

import gzip
import html
import json
import math
import re
import time
import zlib
from urllib import error
from urllib import parse
from urllib import request

try:  # 真机由 TVBox 注入 base.spider；本地自测时可缺省
    from base.spider import Spider as BaseSpider
except Exception:  # pragma: no cover - 仅本地 stub 生效
    class BaseSpider(object):
        """本地 stub：真机上由 TVBox 的 base.spider.Spider 替代。"""

        def __init__(self, *args, **kwargs):
            pass


# =============================================================================
# 一、常量区（所有可调参数集中在此，便于换域名/调超时）
# =============================================================================

HOST_DEFAULT = 'https://fanqe.cc'

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

# 分级超时：列表页最慢（6~10s），详情/播放页 2~6s，探测只能给 4s
TIMEOUT_PAGE = 15
TIMEOUT_DETAIL = 15
TIMEOUT_PLAY = 12
TIMEOUT_PROBE = 4

PER_PAGE = 40            # 站点分类页固定 40 条/页
MAX_LIST_ITEMS = 72      # 首页卡片上限（实测 72，多取无益）
MAX_DETAIL_IDS = 10      # 单次详情最多解析的 ids 数
MAX_EPISODES = 600       # 单线路集数上限，防止异常页面撑爆客户端

# 缓存 TTL（秒）
TTL_HOME = 1800
TTL_CATEGORY = 1800
TTL_DETAIL = 3600
TTL_SEARCH = 600
TTL_PLAY = 900

CACHE_MAX = 200          # 缓存条目上限，超出按写入时间淘汰一批
CACHE_EVICT = 40         # 每批淘汰条数

# 线路优先级：数值越小越靠前，直连线路必须排第一，客户端默认播第一条
LINE_PRIORITY = {
    'jsm3u8': 0,
    'kkytest': 2,
    'kky2': 3,
    'kky3': 4,
    'xiguam3u8': 8,
}

# 分类兜底（首页导航解析失败时使用，与站点导航一致）
FALLBACK_CLASSES = [
    ('1', '电影'),
    ('2', '电视剧'),
    ('3', '综艺'),
    ('4', '动漫'),
    ('46', '体育'),
]

# 地区筛选项来自站点 /show/area/... 链接，补齐“全部”
AREAS = [
    '大陆', '香港', '台湾', '美国', '日本', '韩国', '英国', '法国',
    '德国', '意大利', '西班牙', '俄罗斯', '加拿大', '泰国', '印度', '其它',
]

# 图片扩展名（用于识别“视频地址其实是图片”）
IMAGE_MAGICS = (
    b'\x89PNG',
    b'\xff\xd8\xff',
    b'GIF87a',
    b'GIF89a',
    b'BM',
)

VIDEO_EXTS = ('.m3u8', '.mp4', '.mkv', '.flv', '.m4v', '.mp3', '.m4a')

VOD_KEYS = (
    'vod_id', 'vod_name', 'vod_pic', 'vod_remarks', 'vod_year', 'vod_area',
    'vod_actor', 'vod_director', 'vod_content', 'type_name',
    'vod_play_from', 'vod_play_url',
)

TAG_RE = re.compile(r'<[^>]+>')
SPACE_RE = re.compile(r'[\s\u00a0]+')


class Spider(BaseSpider):
    """TVBox type=3 单文件源主体。"""

    # -------------------------------------------------------------------------
    # 生命周期与初始化
    # -------------------------------------------------------------------------

    def init(self, extend=''):
        """初始化。extend 支持 {"host": "https://xxx"} 换域名，兼容 dict / JSON 字符串。"""
        self.extend = self._parse_extend(extend)
        self.host = HOST_DEFAULT

        host = self.extend.get('host') or self.extend.get('site') or ''
        if host:
            self.host = self._normalize_host(host)

        self.headers = {
            'User-Agent': UA,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Encoding': 'gzip, deflate',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.6',
            'Connection': 'keep-alive',
        }
        self._cache = {}
        self._classes = []
        return None

    def getName(self):
        return '番茄酱影视'

    def isVideoFormat(self, url):
        """客户端嗅探回调：明确是媒体地址才返回 True，避免把网页当视频。"""
        if not url or not isinstance(url, str):
            return False
        low = url.lower()
        return any(ext in low for ext in VIDEO_EXTS)

    def manualVideoCheck(self):
        return False

    # -------------------------------------------------------------------------
    # 通用工具：extend 解析、URL 归一化、文本清洗
    # -------------------------------------------------------------------------

    def _parse_extend(self, extend):
        """extend 兼容 dict / JSON 字符串 / k=v&k=v 三种形态，异常时返回空 dict。"""
        if isinstance(extend, dict):
            return dict(extend)
        if not extend or not isinstance(extend, str):
            return {}
        text = extend.strip()
        if not text:
            return {}
        if text.startswith('{'):
            try:
                data = json.loads(text)
                return data if isinstance(data, dict) else {}
            except Exception:
                return {}
        result = {}
        for pair in text.split('&'):
            if '=' in pair:
                key, value = pair.split('=', 1)
                result[key.strip()] = parse.unquote(value.strip())
        return result

    def _normalize_host(self, host):
        """把用户填写的域名补全为 https:// 形式，去掉尾部斜杠。"""
        host = str(host).strip()
        if host.startswith('//'):
            host = 'https:' + host
        if not host.lower().startswith('http'):
            host = 'https://' + host
        return host.rstrip('/')

    def _text(self, raw):
        """去标签 + 反转义 + 压缩空白。"""
        if not raw:
            return ''
        return SPACE_RE.sub(' ', html.unescape(TAG_RE.sub('', raw))).strip()

    def _abs(self, path):
        """相对路径转绝对地址。"""
        if not path:
            return ''
        if path.startswith('http'):
            return path
        if path.startswith('//'):
            return 'https:' + path
        if not path.startswith('/'):
            path = '/' + path
        return self.host + path

    def _blank_vod(self):
        """生成 vod 骨架：所有字段先给空字符串，杜绝 None。"""
        return dict((key, '') for key in VOD_KEYS)

    def _clean_ep(self, name):
        """集名清洗：去掉会破坏 $$$ / # / $ 结构的分隔符。"""
        name = (name or '').replace('$$$', ' ').replace('#', ' ').replace('$', ' ')
        name = SPACE_RE.sub(' ', name).strip()
        return name or '正片'

    # -------------------------------------------------------------------------
    # 网络层：gzip/deflate 手动解压 + 分级超时 + 失败降级旧缓存
    # -------------------------------------------------------------------------

    def _http(self, url, timeout, binary=False, limit=0):
        """单次请求，返回 str（binary=True 时返回 bytes）。失败抛异常，由调用方决定降级。"""
        headers = dict(self.headers)
        if binary:
            # 二进制探测不要 gzip，省一次解压且便于按魔数判断
            headers.pop('Accept-Encoding', None)
        req = request.Request(url, headers=headers)
        resp = request.urlopen(req, timeout=timeout)
        try:
            data = resp.read(limit) if limit else resp.read()
            encoding = (resp.headers.get('Content-Encoding') or '').lower()
            if encoding and not binary:
                data = self._decompress(data, encoding)
            if binary:
                return data
            charset = resp.headers.get_content_charset() or 'utf-8'
            return data.decode(charset, 'ignore')
        finally:
            resp.close()

    def _decompress(self, data, encoding):
        """按 Content-Encoding 手动解压；deflate 兼容裸流与 zlib 头两种实现。"""
        if 'gzip' in encoding:
            try:
                return gzip.decompress(data)
            except Exception:
                return data
        if 'deflate' in encoding:
            try:
                return zlib.decompress(data)
            except Exception:
                try:
                    return zlib.decompress(data, -zlib.MAX_WBITS)
                except Exception:
                    return data
        return data

    def _fetch(self, key, url, timeout, ttl, binary=False, limit=0):
        """带 TTL 缓存的请求：命中直接返回；异常或空页回退到过期缓存（接口抖动不空屏）。"""
        cached = self._cache_get(key, ttl)
        if cached is not None:
            return cached
        try:
            data = self._http(url, timeout, binary=binary, limit=limit)
        except error.HTTPError:
            # 4xx/5xx 视为接口抖动，走旧缓存
            return self._cache_get(key, 0, allow_stale=True) or (b'' if binary else '')
        except Exception:
            return self._cache_get(key, 0, allow_stale=True) or (b'' if binary else '')
        if data:
            self._cache_put(key, data)
            return data
        return self._cache_get(key, 0, allow_stale=True) or (b'' if binary else '')

    # -------------------------------------------------------------------------
    # 缓存层：TTL + 容量上限 + 批量淘汰
    # -------------------------------------------------------------------------

    def _cache_get(self, key, ttl, allow_stale=False):
        item = self._cache.get(key)
        if not item:
            return None
        stamp, value = item
        if allow_stale:
            return value
        if time.time() - stamp <= ttl:
            return value
        return None

    def _cache_put(self, key, value):
        if len(self._cache) >= CACHE_MAX:
            self._evict()
        self._cache[key] = (time.time(), value)

    def _evict(self):
        """按写入时间淘汰最旧的一批，避免运行数小时后缓存无限膨胀。"""
        if not self._cache:
            return
        ordered = sorted(self._cache.items(), key=lambda kv: kv[1][0])
        for key, _ in ordered[:CACHE_EVICT]:
            self._cache.pop(key, None)

    # -------------------------------------------------------------------------
    # 解析层：分类导航 / 卡片列表 / 详情字段 / 线路选集 / 播放数据
    # -------------------------------------------------------------------------

    def _parse_classes(self, page):
        """从首页导航提取顶级分类，失败时退回固定表。"""
        classes = []
        seen = set()
        pattern = r'href="/index\.php/vod/show/id/(\d+)\.html"[^>]*>([^<]{1,12})</a>'
        for tid, name in re.findall(pattern, page):
            name = self._text(name)
            if not name or name in ('首页', '全部') or tid in seen:
                continue
            if len(classes) >= 10:
                break
            seen.add(tid)
            classes.append({'type_id': str(tid), 'type_name': name})
        if len(classes) < 3:
            classes = [{'type_id': tid, 'type_name': name} for tid, name in FALLBACK_CLASSES]
        self._classes = classes
        return classes

    def _split_cards(self, page):
        """按卡片容器切块；同卡片内图片链接与标题链接各有一个，务必按 vod_id 去重。"""
        blocks = page.split('<div class="public-list-box')[1:]
        items = []
        seen = set()
        for block in blocks:
            vod = self._parse_card(block)
            if not vod or not vod['vod_id'] or vod['vod_id'] in seen:
                continue
            seen.add(vod['vod_id'])
            items.append(vod)
        return items

    def _parse_card(self, block):
        """解析单张卡片：兼容首页（分类·备注）、分类页（年份·类型）、搜索页（thumb-txt）三种排版。"""
        match = re.search(r'/index\.php/vod/detail/id/(\d+)\.html', block)
        if not match:
            return None
        vod = self._blank_vod()
        vod['vod_id'] = match.group(1)

        vod['vod_name'] = self._card_name(block)
        vod['vod_pic'] = self._card_pic(block)

        subtitle = ''
        sub_match = re.search(r'class="public-list-subtitle[^"]*"[^>]*>(.*?)</div>', block, re.S)
        if sub_match:
            subtitle = self._text(sub_match.group(1))

        year, class_name, remarks = self._split_subtitle(subtitle)
        vod['vod_year'] = year
        vod['type_name'] = class_name

        span_match = re.search(r'class="public-list-prb[^"]*"[^>]*>(.*?)</span>', block, re.S)
        if span_match:
            span_text = self._text(span_match.group(1))
            if span_text and not re.match(r'^\d+(\.\d+)?$', span_text):
                # 搜索页把“第30集完结”放在 prb 里
                remarks = remarks or span_text
        vod['vod_remarks'] = remarks

        area_match = re.search(r'/area/([^"/]+?)\.html', block)
        if area_match:
            vod['vod_area'] = parse.unquote(area_match.group(1))
        return vod

    def _card_name(self, block):
        """标题三处兜底：time-title 的 title 属性 → thumb-txt 内链文本 → alt 去后缀。"""
        match = re.search(r'class="time-title[^"]*"[^>]*title="([^"]+)"', block)
        if match:
            return self._text(match.group(1))
        match = re.search(r'class="thumb-txt[^"]*"[^>]*>\s*<a[^>]*>(.*?)</a>', block, re.S)
        if match:
            return self._text(match.group(1))
        match = re.search(r'alt="([^"]+?)封面图"', block)
        if match:
            return self._text(match.group(1))
        return ''

    def _card_pic(self, block):
        """封面三处兜底：懒加载 data-src → 内联 background-image → 图片 src。"""
        match = re.search(r'data-src="(https?://[^"]+)"', block)
        if match:
            return match.group(1)
        match = re.search(r'background-image:[^;]*url\((https?://[^)]+)\)', block)
        if match:
            return match.group(1)
        match = re.search(r'<img[^>]+src="(https?://[^"]+)"', block)
        return match.group(1) if match else ''

    def _split_subtitle(self, subtitle):
        """把 “2026 · 惊悚 · 恐怖片” 或 “国产剧 · 已更新至31集” 拆成年份/类型/备注。"""
        if not subtitle:
            return '', '', ''
        parts = [part.strip() for part in subtitle.split('·') if part.strip()]
        year = ''
        if parts and re.match(r'^(19|20)\d{2}$', parts[0]):
            year = parts[0]
            parts = parts[1:]
        remarks = ''
        classes = []
        for part in parts:
            if re.search(r'(更新|完结|集|HD|BD|TC|抢先|正片|预告)', part, re.I):
                remarks = part
            else:
                classes.append(part)
        return year, ','.join(classes), remarks

    def _parse_detail(self, page, vod_id):
        """详情页字段解析：标题/封面/年份/地区/备注/导演/演员/简介/线路。"""
        vod = self._blank_vod()
        vod['vod_id'] = str(vod_id)

        match = re.search(r'<h1[^>]*>(.*?)</h1>', page, re.S)
        vod['vod_name'] = self._text(match.group(1)) if match else ''

        match = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', page)
        if not match:
            match = re.search(r'class="[^"]*detail-pic[^"]*".*?data-src="(https?://[^"]+)"', page, re.S)
        vod['vod_pic'] = match.group(1) if match else ''

        # “2025 · 澳大利亚 · 惊悚 · 恐怖 · 恐怖片” 这一行最省事，字段一次拿全
        dep_match = re.search(r'class="deployment[^"]*"[^>]*>(.*?)</a>', page, re.S)
        if dep_match:
            parts = [part.strip() for part in self._text(dep_match.group(1)).split('·') if part.strip()]
            if parts and re.match(r'^(19|20)\d{2}$', parts[0]):
                vod['vod_year'] = parts[0]
                parts = parts[1:]
            if parts:
                vod['vod_area'] = parts[0]
                vod['type_name'] = ','.join(parts[1:])

        match = re.search(r'备注\s*:</strong>([^<]*)', page)
        vod['vod_remarks'] = self._text(match.group(1)) if match else ''

        vod['vod_director'] = self._detail_people(page, '导演')
        vod['vod_actor'] = self._detail_people(page, '演员')

        match = re.search(r'id="height_limit"[^>]*>(.*?)</div>', page, re.S)
        vod['vod_content'] = self._text(match.group(1)) if match else ''

        lines = self._parse_play_lines(page)
        vod['vod_play_from'] = '$$$'.join(line['name'] for line in lines)
        vod['vod_play_url'] = '$$$'.join(
            '#'.join('%s$%s' % (ep_name, ep_url) for ep_name, ep_url in line['eps'])
            for line in lines
        )
        return vod

    def _detail_people(self, page, label):
        """解析“导演 : / 演员 :”后面的演员表，多个人名用逗号连接。"""
        match = re.search(label + r'\s*:</strong>(.*?)</div>', page, re.S)
        if not match:
            return ''
        names = [self._text(item) for item in re.findall(r'<a[^>]*>(.*?)</a>', match.group(1), re.S)]
        names = [name for name in names if name]
        return ','.join(names)

    def _parse_play_lines(self, page):
        """线路与选集：tab 与 anthology-list-box 按出现顺序一一对应，直连线路排最前。"""
        tabs = []
        for attrs, inner in re.findall(
                r'<a([^>]*class="[^"]*vod-playerUrl[^"]*"[^>]*)>(.*?)</a>', page, re.S):
            form_match = re.search(r'data-form="([^"]+)"', attrs)
            # 标签里混着 <span class="badge">31</span> 的集数角标，先摘掉再取线路名
            label_html = re.sub(r'<span[^>]*class="[^"]*badge[^"]*"[^>]*>.*?</span>', '', inner, flags=re.S)
            tabs.append((
                form_match.group(1) if form_match else '',
                self._text(label_html),
            ))

        boxes = re.split(r'<div class="anthology-list-box', page)[1:]
        lines = []
        for index, box in enumerate(boxes):
            end = box.find('</ul>')
            if end > 0:
                box = box[:end]
            eps = []
            for href, name in re.findall(
                    r'href="([^"]*?/vod/play/id/\d+/sid/\d+/nid/\d+\.html)"[^>]*>(.*?)</a>',
                    box, re.S):
                eps.append((self._clean_ep(self._text(name)), href))
                if len(eps) >= MAX_EPISODES:
                    break
            if not eps:
                continue
            form, label = tabs[index] if index < len(tabs) else ('', '线路%d' % (index + 1))
            lines.append({
                'form': form,
                'name': label or ('线路%d' % (index + 1)),
                'eps': eps,
            })

        # 稳定排序：直连线路（jsm3u8）优先，其余保持站点原始顺序
        lines.sort(key=lambda line: LINE_PRIORITY.get(line['form'], 5))
        return lines

    def _player_data(self, page):
        """从播放页提取 player_aaaa 的 JSON 片段。"""
        match = re.search(r'var\s+player_aaaa\s*=\s*(\{.*?\})\s*</script>', page, re.S)
        if not match:
            return {}
        text = match.group(1).strip().rstrip(';')
        try:
            data = json.loads(text)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    # -------------------------------------------------------------------------
    # 播放地址真实性校验（防黑屏的核心）
    # -------------------------------------------------------------------------

    def _probe_media(self, url):
        """真下头部校验：m3u8 必须含 #EXTM3U，mp4/mkv 必须不是图片魔数。返回 (ok, format)。"""
        low = url.lower()
        if '.m3u8' in low:
            head = self._fetch('probe:%s' % url, url, TIMEOUT_PROBE, TTL_PLAY,
                               binary=True, limit=2048)
            if not head or b'#EXTM3U' not in head[:64]:
                return False, ''
            # 只含 master 列表也算可用（客户端会自行解析子列表）
            return True, 'm3u8'
        for ext in ('.mp4', '.mkv', '.flv', '.m4v'):
            if ext in low:
                head = self._fetch('probe:%s' % url, url, TIMEOUT_PROBE, TTL_PLAY,
                                   binary=True, limit=512)
                if not head:
                    return False, ''
                if head[:4] == b'\x89PNG' or head[:3] == b'\xff\xd8\xff':
                    return False, ''
                if head[:6] in (b'GIF87a', b'GIF89a') or head[:2] == b'BM':
                    return False, ''
                if head[:4] == b'RIFF' and head[8:12] == b'WEBP':
                    return False, ''
                return True, ext.lstrip('.')
        return False, ''

    # -------------------------------------------------------------------------
    # TVBox 接口：home / category / detail / search / player
    # -------------------------------------------------------------------------

    def homeContent(self, filter):
        """首页：分类 + 筛选 + 推荐列表。"""
        page = self._fetch('home', self.host + '/', TIMEOUT_PAGE, TTL_HOME)
        classes = self._parse_classes(page)
        videos = self._split_cards(page)[:MAX_LIST_ITEMS] if page else []
        return {
            'class': classes,
            'filters': self._build_filters(),
            'list': videos,
        }

    def homeVideoContent(self):
        """首页推荐位（TVBox 首页首屏会先调它，直接复用 home 缓存）。"""
        page = self._fetch('home', self.host + '/', TIMEOUT_PAGE, TTL_HOME)
        return {'list': self._split_cards(page)[:MAX_LIST_ITEMS]} if page else {'list': []}

    def _build_filters(self):
        """筛选只做站点真实支持的“地区 + 年份”，不做站点没有的排序项。"""
        year_now = time.localtime().tm_year
        years = [{'n': str(y), 'v': str(y)} for y in range(year_now, year_now - 9, -1)]
        area_items = [{'n': '全部', 'v': ''}] + [{'n': a, 'v': a} for a in AREAS]
        year_items = [{'n': '全部', 'v': ''}] + years
        block = [
            {'key': 'area', 'name': '地区', 'value': area_items},
            {'key': 'year', 'name': '年份', 'value': year_items},
        ]
        # 每个顶级分类共用同一组筛选项
        return dict((item['type_id'], block) for item in (self._classes or [
            {'type_id': tid} for tid, _ in FALLBACK_CLASSES
        ]))

    def _category_url(self, tid, pg, area='', year=''):
        """拼分类页地址：/show[/area/x][/year/y]/id/<tid>[/page/<n>].html（已实测可组合）。"""
        path = '/index.php/vod/show'
        if area:
            path += '/area/' + parse.quote(area)
        if year:
            path += '/year/' + parse.quote(str(year))
        path += '/id/%s' % tid
        if pg > 1:
            path += '/page/%d' % pg
        return self.host + path + '.html'

    def categoryContent(self, tid, pg, filter, extend):
        """分类列表：40 条/页，pagecount 取自站点尾页链接，total 取自 hl-total。"""
        tid = str(tid or '').strip()
        try:
            pg = int(pg or 1)
        except Exception:
            pg = 1
        if pg < 1:
            pg = 1

        ext = self._parse_extend(extend)
        area = (ext.get('area') or '').strip()
        year = (ext.get('year') or '').strip()

        url = self._category_url(tid, pg, area, year)
        key = 'cat:%s:%s:%s:%s:%s' % (self.host, tid, pg, area, year)
        page = self._fetch(key, url, TIMEOUT_PAGE, TTL_CATEGORY)

        videos = self._split_cards(page) if page else []
        total, pagecount = self._page_meta(page, pg, len(videos))
        return {
            'page': pg,
            'pagecount': pagecount,
            'limit': PER_PAGE,
            'total': total,
            'list': videos,
        }

    def _page_meta(self, page, pg, got):
        """分页元信息：优先站点尾页，其次按 total/40 计算，绝不让 pagecount 小于当前页。"""
        total = 0
        match = re.search(r"\.html\('(\d+)'\)", page) if page else None
        if match:
            total = int(match.group(1))
        pagecount = 0
        tail = re.search(r'/page/(\d+)\.html"\s*title="尾页"', page) if page else None
        if tail:
            pagecount = int(tail.group(1))
        if not pagecount and total:
            pagecount = int(math.ceil(total / float(PER_PAGE)))
        if not pagecount:
            # 尾页与总数都缺失时按本页是否满页推断，避免客户端提前停止翻页
            pagecount = pg if got >= PER_PAGE else pg
        if pagecount < pg:
            pagecount = pg
        if total and total < (pg - 1) * PER_PAGE:
            total = (pg - 1) * PER_PAGE + got
        return total, pagecount

    def detailContent(self, ids):
        """详情：ids 兼容 list / str / "a,b"，逐条解析并合并线路选集。"""
        if isinstance(ids, (list, tuple)):
            id_list = [str(item).strip() for item in ids]
        else:
            id_list = [part.strip() for part in str(ids or '').split(',')]
        id_list = [item for item in id_list if item][:MAX_DETAIL_IDS]

        result = []
        for vod_id in id_list:
            match = re.search(r'(\d+)', vod_id)
            if not match:
                continue
            real_id = match.group(1)
            url = self.host + '/index.php/vod/detail/id/%s.html' % real_id
            key = 'detail:%s:%s' % (self.host, real_id)
            page = self._fetch(key, url, TIMEOUT_DETAIL, TTL_DETAIL)
            if not page:
                continue
            result.append(self._parse_detail(page, real_id))
        return {'list': result}

    def searchContent(self, key, quick, pg=1):
        """搜索：站点结果不分页，pg>1 直接返回空列表，不重复请求第 1 页。"""
        keyword = (key or '').strip()
        try:
            pg = int(pg or 1)
        except Exception:
            pg = 1
        if not keyword or pg > 1:
            return {'list': []}

        url = self.host + '/index.php/vod/search.html?wd=' + parse.quote(keyword)
        cache_key = 'search:%s:%s' % (self.host, keyword)
        page = self._fetch(cache_key, url, TIMEOUT_PAGE, TTL_SEARCH)
        return {'list': self._split_cards(page)[:PER_PAGE]} if page else {'list': []}

    def playerContent(self, flag, id, vipFlags=None):
        """播放：取 player_aaaa.url，能直连且真校验通过才 parse=0，否则一律回退 parse=1。"""
        page_url = id if str(id).startswith('http') else self._abs(str(id))
        header = json.dumps({'User-Agent': UA})
        result = {
            'parse': 1,
            'url': page_url,
            'header': header,
            'playUrl': '',
            'format': '',
        }
        if not page_url:
            return result

        key = 'play:%s:%s' % (self.host, page_url)
        page = self._fetch(key, page_url, TIMEOUT_PLAY, TTL_PLAY)
        if not page:
            return result

        data = self._player_data(page)
        play_url = (data.get('url') or '').strip()
        if not play_url.startswith('http'):
            # na: 占位符 / 播放器代码，交给客户端解析页面
            return result

        ok, fmt = self._probe_media(play_url)
        if not ok:
            return result

        result['parse'] = 0
        result['url'] = play_url
        result['format'] = fmt
        return result