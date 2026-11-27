# -*- coding: utf-8 -*-
# 摔角网（www.shuaijiao.cn）TVBox / CatVod Python 源
# 列表：/video/{tag}/ 第 1 页，/video/{tag}/{n}.html 第 n 页（每页 32 条）
# 详情：/video/view/{id}.html
# 播放：站点本身不放流，线路为「微信公众号文章」或「v.qq.com 腾讯视频页」外链
import sys, re, time, json
from html import unescape
from urllib.parse import urljoin, quote, urlsplit, urlunsplit
import requests
sys.path.append('..')
try:
    from base.spider import Spider
except ImportError:
    class Spider:
        def fetch(self, url, headers=None, **kw):
            kw.pop('timeout', None)
            r = requests.get(url, headers=headers, timeout=15, **kw)
            r.encoding = 'utf-8'
            return r

HOST = 'https://www.shuaijiao.cn'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
UA_WX = 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.30'
PER_PAGE = 32

CATEGORIES = [
    ('wwe', 'WWE'), ('raw', 'RAW'), ('sd', 'SmackDown'), ('nxt', 'NXT'),
    ('me', 'ME'), ('205live', '205 Live'), ('ppv', 'WWE PPV'),
    ('tna', 'TNA'), ('aew', 'AEW'), ('roh', 'ROH'), ('lucha', 'Lucha'),
    ('owe', 'OWE'), ('ufc', 'UFC'), ('independent', '独立联盟'), ('single', '单场比赛'),
]


class Spider(Spider):
    def init(self, extend=''):
        self.base = HOST.rstrip('/')
        self.ua = UA
        self.ua_wx = UA_WX
        self.types = [{'type_id': t, 'type_name': n} for t, n in CATEGORIES]
        self._c = {}
        try:
            r = self._fetch(self.base + '/video/', headers={'User-Agent': self.ua}, t=15000)
            h = self._text(r)
            if h:
                self._c[self.base + '/video/'] = [time.time(), h]
        except:
            pass

    def _text(self, r):
        h = r.text if hasattr(r, 'text') else r
        if isinstance(h, bytes):
            h = h.decode('utf-8', 'ignore')
        return h or ''

    def _fetch(self, url, headers=None, t=15000):
        hd = headers or {'User-Agent': self.ua, 'Referer': self.base + '/'}
        try:
            return self.fetch(url, headers=hd, timeout=t)
        except TypeError:
            return self.fetch(url, headers=hd)

    def _get(self, url, ttl=0, t=18000, wx=False):
        k = url
        if ttl and k in self._c and time.time() - self._c[k][0] < ttl:
            return self._c[k][1]
        hd = {'User-Agent': self.ua_wx if wx else self.ua, 'Referer': self.base + '/'}
        for i in range(2):
            try:
                h = self._text(self._fetch(url, headers=hd, t=t))
                if h:
                    self._c[k] = [time.time(), h]
                    return h
            except:
                pass
            time.sleep(0.5)
        return ''

    def _enc(self, u):
        if not u or not re.search(r'[^\x00-\x7f]', u):
            return u
        try:
            p = urlsplit(u)
            return urlunsplit((p.scheme, p.netloc, quote(p.path, safe='/%:@'), p.query, ''))
        except:
            return u

    def _hdr(self, ref):
        return json.dumps({'User-Agent': self.ua, 'Referer': ref})

    def _alive(self, u, ref):
        # 微信 mp4 直链带防盗链，先探一次再决定给直链还是交给解析
        try:
            r = requests.get(u, headers={'User-Agent': self.ua, 'Referer': ref},
                             timeout=8, stream=True)
            st = r.status_code
            r.close()
            return st in (200, 206)
        except:
            return False

    # ---------- 列表解析 ----------
    def _items(self, h):
        out, seen = [], set()
        if not h:
            return out
        for blk in re.split(r'<dl[\s>]', h)[1:]:
            chunk = blk.split('</dl>')[0]
            m = re.search(r'/video/view/(\d+)\.html', chunk)
            if not m:
                continue
            vid = m.group(1)
            if vid in seen:
                continue
            nm = re.search(r'<p class="tit">\s*<a[^>]*>([^<]+)</a>', chunk)
            if not nm:
                nm = re.search(r'<a[^>]+title="([^"]+)"', chunk)
            name = unescape(nm.group(1)).strip() if nm else ''
            if not name:
                continue
            pm = re.search(r'<img[^>]+(?:src|data-original)="(https?://[^"]+)"', chunk)
            pic = pm.group(1) if pm else ''
            seen.add(vid)
            out.append({
                'vod_id': vid,
                'vod_name': name[:60],
                'vod_pic': pic,
                'vod_remarks': '',
            })
        return out

    def _page_info(self, h):
        m = re.search(r'<a class="a1">\s*(\d+)\s*条\s*</a>', h) or re.search(r'(\d+)\s*条', h)
        if not m:
            return 0, 1
        total = int(m.group(1))
        return total, max(1, (total + PER_PAGE - 1) // PER_PAGE)

    # ---------- 标准接口 ----------
    def homeContent(self, filter=False):
        return {'class': self.types, 'list': self.homeVideoContent().get('list', [])}

    def homeVideoContent(self):
        h = self._get(self.base + '/video/', ttl=300)
        items = self._items(h)
        return {'list': items[:60]}

    def categoryContent(self, tid, pg=1, filter=False, extend=''):
        tag = str(tid).split('|')[0]
        try:
            pg = max(1, int(pg or 1))
        except:
            pg = 1
        url = '%s/video/%s/' % (self.base, tag) if pg == 1 else '%s/video/%s/%d.html' % (self.base, tag, pg)
        h = self._get(url, ttl=600)
        items = self._items(h)
        total, pc = self._page_info(h)
        if not items:
            return {'page': pg, 'pagecount': max(pg, 1), 'limit': PER_PAGE, 'total': 0, 'list': []}
        return {
            'page': pg,
            'pagecount': pc if pc >= pg else pg,
            'limit': PER_PAGE,
            'total': total or len(items),
            'list': items,
        }

    def detailContent(self, ids, quick='1'):
        raw = str(ids[0] if isinstance(ids, list) else ids or '')
        m = re.search(r'(\d{2,})', raw)
        vid = m.group(1) if m else ''
        if not vid:
            return {'list': []}
        h = self._get('%s/video/view/%s.html' % (self.base, vid), ttl=300, t=25000)
        if not h:
            return {'list': []}
        d = {
            'vod_id': vid, 'vod_name': '', 'vod_pic': '', 'vod_year': '', 'vod_area': '',
            'vod_remarks': '', 'vod_actor': '', 'vod_director': '', 'vod_content': '',
            'vod_play_from': '', 'vod_play_url': '',
        }
        mm = re.search(r'<h1[^>]*>([\s\S]*?)</h1>', h)
        if mm:
            d['vod_name'] = unescape(re.sub(r'<[^>]+>', '', mm.group(1))).strip()[:60]
        mm = re.search(r'<meta property="og:image" content="([^"]+)"', h)
        if mm:
            d['vod_pic'] = mm.group(1)
        mm = re.search(r'<meta property="og:release_date" content="([^"]+)"', h)
        if mm:
            d['vod_year'] = mm.group(1)[:4]
        mm = re.search(r'更新时间：\s*([\d\-]+\s*[\d:]*)', h)
        if mm:
            d['vod_remarks'] = mm.group(1).strip()[:20]
        else:
            d['vod_remarks'] = d['vod_year']
        mm = re.search(r'<meta name="description" content="([^"]+)"', h)
        if mm:
            d['vod_content'] = unescape(mm.group(1)).strip()[:500]

        lines = self._lines(h)
        if lines:
            names, urls = [], []
            for i, (nm, u) in enumerate(lines):
                label = nm or ('线路%d' % (i + 1))
                names.append(label)
                urls.append('%s$%s' % (label, u))
            d['vod_play_from'] = '$$$'.join(names)
            d['vod_play_url'] = '$$$'.join(urls)
        return {'list': [d]}

    def _lines(self, h):
        t = unescape(h)
        out, seen = [], set()
        for m in re.finditer(r"openUrl\(\s*\\?['\"]([^'\"\\]+)\\?['\"]\s*\)", t):
            u = m.group(1).strip()
            if not u.startswith('http') or u in seen:
                continue
            seg = t[m.end():m.end() + 400]
            lb = re.search(r'<span>([^<]*)</span>', seg)
            nm = unescape(lb.group(1)).strip() if lb else ''
            seen.add(u)
            out.append((nm, u))
        if not out:
            for m in re.finditer(r'openVideo\("([^"]+)"', t):
                u = m.group(1).strip()
                if not u.startswith('http') or u in seen:
                    continue
                if not re.search(r'vid=[A-Za-z0-9_\-]{6,}', u):
                    continue
                seen.add(u)
                out.append(('线路', u))
        return out

    def searchContent(self, key, quick=False, pg='1'):
        kw = str(key or '').strip()
        if not kw:
            return {'list': [], 'page': 1}
        try:
            pg = max(1, int(pg or 1))
        except:
            pg = 1
        base = '%s/video/k/%s/' % (self.base, quote(kw))
        url = base if pg == 1 else base + '%d.html' % pg
        h = self._get(url, ttl=300)
        items = self._items(h)
        total, pc = self._page_info(h)
        return {
            'list': items,
            'page': pg,
            'pagecount': pc if pc >= pg else pg,
            'limit': PER_PAGE,
            'total': total or len(items),
        }

    def playerContent(self, flag, id, vipFlags=None):
        u = str(id or flag or '').strip()
        if not u:
            return {'parse': 0, 'url': ''}
        full = u if u.startswith('http') else urljoin(self.base, u)

        # 1) 已经是直链
        if re.search(r'\.(m3u8|mp4|flv)(\?|$)', full, re.I):
            return {'parse': 0, 'url': self._enc(full), 'header': self._hdr('https://mp.weixin.qq.com/')}

        # 2) 腾讯视频页：交给 App 自带解析
        if 'v.qq.com' in full or 'qq.com/x/page' in full:
            return {'parse': 1, 'url': full, 'header': self._hdr(self.base + '/')}

        # 3) 公众号文章：先探文章里的 mp4 直链，能直连就直连，否则回退解析
        if 'mp.weixin.qq.com' in full:
            h = self._get(full, ttl=0, t=30000, wx=True)
            if h:
                mp4s = [unescape(x) for x in re.findall(r'https?://mpvideo\.qpic\.cn/[^\s"\'<>\\]+', h)]
                mp4s = [x for x in dict.fromkeys(mp4s) if x]
                for cand in reversed(mp4s):
                    if self._alive(cand, full):
                        return {'parse': 0, 'url': self._enc(cand), 'header': self._hdr(full)}
                m3 = re.search(r'(https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*)', h)
                if m3:
                    return {'parse': 0, 'url': self._enc(m3.group(1)), 'header': self._hdr(full)}
            return {'parse': 1, 'url': full, 'header': self._hdr(full)}

        # 4) 其它页面：找 m3u8 / mp4
        h = self._get(full, ttl=120, t=25000)
        if h:
            m3 = re.search(r'(https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*)', h)
            if m3:
                return {'parse': 0, 'url': self._enc(m3.group(1)), 'header': self._hdr(full)}
            mp = re.search(r'(https?://[^\s"\'<>]+\.mp4[^\s"\'<>]*)', h)
            if mp:
                return {'parse': 0, 'url': self._enc(mp.group(1)), 'header': self._hdr(full)}
        return {'parse': 0, 'url': ''}