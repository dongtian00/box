# coding=utf-8
"""
目标站: 柚子影视 (youziys.cc) - 苹果CMS 采集API 直连
备用域名: youzi5.com
架构:
  - 列表/分页/筛选: ac=videolist&t=<tid>&pg=<n> (+ area/class/year 筛选)  → 翻页正确
  - 详情:          ac=detail&ids=<id>  → 直接从API取真实 m3u8 直链(线路⑨等均能播, parse=0 秒开)
  - 播放:          m3u8/mp4 直链 parse=0; 网页线路(youku/qiyi/qq...) parse=1 交TVBox解析
  - 线路名/顺序:   按网站线路名(线路①/4K高清/线路⑨.../YK/TX/QY)重命名并排序
  - 兼容性:        init 秒回 + 后台域名择优; 入口方法带默认参数; SSL不校验
"""
import sys
sys.path.append('../')
from base.spider import Spider

import re
import json
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, unquote

try:
    import requests
    USE_REQUESTS = True
    try:
        requests.packages.urllib3.disable_warnings()
    except Exception:
        pass
except ImportError:
    import urllib.request
    import urllib.parse
    USE_REQUESTS = False

try:
    import ssl
    _SSL_CTX = ssl._create_unverified_context()
except Exception:
    _SSL_CTX = None

UA = 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36'
HEADERS = {'User-Agent': UA, 'Referer': 'https://www.youziys.cc/'}

HOST_POOL = ['https://www.youziys.cc', 'https://youzi5.com', 'http://youzi5.com']
# 坏CDN主机: img.test.com 是站点坏图占位(双图格式前半段), youzi5/youziys 同理
BAD_PIC_HOST = ['youzi5.com', 'youziys.cc', 'img.test.com']
API_PATH = '/api.php/provide/vod/?'

CLASSES = [
    ('1', '电影'), ('2', '电视剧'), ('3', '综艺'), ('4', '动漫'),
    ('39', '短剧'), ('7', '纪录片'), ('53', '体育'),
]

# 网站线路名映射(flag->名称)与展示顺序(与官网 ddys-source-tabs 一致)
SITE_LINE_NAMES = {
    'qq': 'TX线路', 'qiyi': 'QY线路', 'bilibili': 'BL线路', 'mgtv': 'MG线路',
    'youku': 'YK线路', 'okm3u8': '线路①', 'dyttm3u8': '4K高清',
    '1080zyk': '线路②', 'bfzym3u8': '线路⑨',
}
SITE_LINE_ORDER = ['qq', 'qiyi', 'bilibili', 'mgtv', 'youku',
                   'okm3u8', 'dyttm3u8', '1080zyk', 'bfzym3u8']


class Spider(Spider):
    host = ''
    session = None
    cache = {}
    _host_lock = threading.Lock()
    _host_ts = 0
    _host_idx = 0

    # ---------- 初始化: 立即可用, 后台择优 ----------
    def init(self, extend=''):
        if not self.host:
            self.host = HOST_POOL[0]
        if USE_REQUESTS and not self.session:
            try:
                self.session = requests.Session()
                self.session.headers.update(HEADERS)
                self.session.verify = False
            except Exception:
                self.session = None
        try:
            t = threading.Thread(target=self._bgPickHost, daemon=True)
            t.start()
        except Exception:
            pass
        return ''

    def _bgPickHost(self):
        with self._host_lock:
            now = time.time()
            if now - self._host_ts < 1800:
                return
            self._host_ts = now
        # 主域名健康则不动
        try:
            if self._ok(HOST_POOL[0]):
                return
        except Exception:
            pass
        pool = list(HOST_POOL[1:])
        try:
            html = self._get(HOST_POOL[0] + '/', 5)
            for d in re.findall(r'https?://[A-Za-z0-9.-]*youzi[A-Za-z0-9.-]*(?:\.[a-z]{2,3})?', html or ''):
                if d not in pool and d != HOST_POOL[0] and not any(b in d for b in BAD_PIC_HOST):
                    pool.append(d.rstrip('/'))
        except Exception:
            pass
        best, best_cost = None, 999
        for h in pool[:5]:
            try:
                t0 = time.time()
                if self._ok(h):
                    cost = time.time() - t0
                    if cost < best_cost:
                        best, best_cost = h, cost
            except Exception:
                continue
        if best:
            self.host = best

    def _ok(self, host):
        txt = self._get(host + API_PATH + 'ac=list', 4)
        return bool(txt and '"code":1' in txt.replace(' ', ''))

    # ---------- 底层请求 ----------
    def _get(self, url, timeout=10):
        if USE_REQUESTS:
            s = self.session or requests
            r = s.get(url, timeout=timeout)
            r.encoding = 'utf-8'
            return r.text
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
            return resp.read().decode('utf-8', 'ignore')

    def fetch(self, url, timeout=10):
        ck = 'url:' + url
        hit = self.cache.get(ck)
        if hit is not None:
            return hit
        text = ''
        try:
            text = self._get(url, timeout)
        except Exception:
            text = ''
        if not text:
            # 按序快速切备用域名重试一次(不触发全量重测速)
            try:
                with self._host_lock:
                    self._host_idx = (self._host_idx + 1) % len(HOST_POOL)
                    alt = HOST_POOL[self._host_idx]
                if url.startswith(self.host):
                    self.host = alt
                    try:
                        text = self._get(alt + url[len(HOST_POOL[0]):], min(timeout, 8))
                    except Exception:
                        text = ''
            except Exception:
                text = ''
        if text:
            self.cache[ck] = text
        return text

    def getJson(self, url, timeout=10):
        try:
            return json.loads(self.fetch(url, timeout))
        except Exception:
            return {}

    @staticmethod
    def fixPic(pic):
        if not pic:
            return ''
        # 苹果CMS双图格式: 坏CDN#好CDN → 优先后者
        if '#' in pic:
            parts = [p for p in pic.split('#') if p]
            for p in parts:
                if not any(b in p for b in BAD_PIC_HOST):
                    pic = p
                    break
            else:
                pic = parts[-1]
        pic = pic.strip()
        # http→https 统一升级: TVBox内核加载https页面里的明文http图会被mixed-content拦截
        if pic.startswith('http://'):
            pic = 'https://' + pic[len('http://'):]
        return pic

    @staticmethod
    def parseVods(items):
        out = []
        for it in items or []:
            try:
                out.append({
                    'vod_id': str(it.get('vod_id') or ''),
                    'vod_name': it.get('vod_name', '') or '',
                    'vod_pic': Spider.fixPic(it.get('vod_pic', '') or ''),
                    'vod_remarks': it.get('vod_remarks', '') or '',
                })
            except Exception:
                continue
        return out

    # ---------- 首页 ----------
    def homeContent(self, filter=1):
        classes = [{'type_id': str(t), 'type_name': n} for t, n in CLASSES]
        filters = {}
        if filter:
            areas = [{'n': '全部', 'v': ''}, {'n': '大陆', 'v': '大陆'}, {'n': '香港', 'v': '香港'},
                     {'n': '台湾', 'v': '台湾'}, {'n': '美国', 'v': '美国'}, {'n': '韩国', 'v': '韩国'},
                     {'n': '日本', 'v': '日本'}, {'n': '英国', 'v': '英国'}, {'n': '泰国', 'v': '泰国'}]
            cls = [{'n': '全部', 'v': ''}, {'n': '喜剧', 'v': '喜剧'}, {'n': '爱情', 'v': '爱情'},
                   {'n': '恐怖', 'v': '恐怖'}, {'n': '动作', 'v': '动作'}, {'n': '科幻', 'v': '科幻'},
                   {'n': '剧情', 'v': '剧情'}, {'n': '战争', 'v': '战争'}]
            by = [{'n': '更新时间', 'v': 'time'}, {'n': '周热播', 'v': 'hits_week'}]
            for t, _ in CLASSES:
                filters[str(t)] = [
                    {'key': 'area', 'name': '地区', 'value': areas},
                    {'key': 'class', 'name': '类型', 'value': cls},
                    {'key': 'by', 'name': '排序', 'value': by},
                    {'key': 'year', 'name': '年份', 'value':
                        [{'n': '全部', 'v': ''}] + [{'n': str(y), 'v': str(y)} for y in range(2026, 2014, -1)]},
                ]
        result = {'class': classes, 'filters': filters, 'list': []}
        # 首页推荐: 从多个分类各取几条, 并发抓取+短超时, 交错混排(避免与单个分类雷同)
        try:
            mix_tids = [('1', 8), ('2', 8), ('3', 2), ('4', 2)]  # (分类tid, 取条数)
            results = {}
            def _one(tid):
                try:
                    j = self.getJson(self.host + API_PATH + 'ac=videolist&t=%s&pg=1' % tid, 5)
                    return self.parseVods(j.get('list', []))[:8]
                except Exception:
                    return []
            try:
                with ThreadPoolExecutor(max_workers=len(mix_tids)) as ex:
                    futs = {ex.submit(_one, tid): tid for tid, _ in mix_tids}
                    for fu in futs:
                        try:
                            results[futs[fu]] = fu.result(timeout=6)
                        except Exception:
                            results[futs[fu]] = []
            except Exception:
                for tid, _ in mix_tids:
                    results[tid] = _one(tid)
            # 交错混排
            mixed = []
            m = max((len(v) for v in results.values()), default=0)
            for i in range(m):
                for tid, _ in mix_tids:
                    b = results.get(tid, [])
                    if i < len(b):
                        mixed.append(b[i])
            result['list'] = mixed
        except Exception:
            result['list'] = []
        return result

    def homeVideoContent(self):
        return self.homeContent(False)

    # ---------- 分类(API直连+分页+筛选) ----------
    def categoryContent(self, tid, pg=1, filter=1, extend=None):
        extend = extend or {}
        try:
            pg = max(1, int(pg))
        except Exception:
            pg = 1
        params = 'ac=videolist&t=%s&pg=%d' % (tid, pg)
        for k, v in [('area', 'area'), ('class', 'class'), ('year', 'year')]:
            val = str(extend.get(k) or '').strip()
            if val:
                params += '&' + v + '=' + quote(val)
        j = self.getJson(self.host + API_PATH + params)
        return {
            'list': self.parseVods(j.get('list', [])),
            'page': pg,
            'pagecount': j.get('pagecount', 0) or 0,
            'limit': j.get('limit', 20) or 20,
            'total': j.get('total', 0) or 0,
        }

    # ---------- 详情(API直取m3u8直链) ----------
    def detailContent(self, ids):
        try:
            vid = str(ids[0]) if isinstance(ids, (list, tuple)) else str(ids)
        except Exception:
            vid = ''
        if not vid or not vid.isdigit():
            return {'list': []}
        j = self.getJson(self.host + API_PATH + 'ac=detail&ids=' + vid)
        vod = (j.get('list') or [{}])[0]
        if not vod or not (vod.get('vod_name') or ''):
            return {'list': []}

        src = vod.get('vod_play_from', '') or ''
        url = vod.get('vod_play_url', '') or ''
        play_from, play_url = [], []
        if src and url:
            froms = src.split('$$$')
            urls = url.split('$$$')
            for i, f in enumerate(froms):
                if i < len(urls) and urls[i].strip():
                    play_from.append(f)
                    play_url.append(urls[i])
        play_from, play_url = self._siteLines(play_from, play_url)

        item = {
            'vod_id': vid,
            'vod_name': vod.get('vod_name', ''),
            'vod_pic': self.fixPic(vod.get('vod_pic', '') or ''),
            'type_name': vod.get('type_name', '') or vod.get('vod_type', '') or '',
            'vod_year': vod.get('vod_year', '') or '',
            'vod_area': vod.get('vod_area', '') or '',
            'vod_actor': vod.get('vod_actor', '') or '',
            'vod_director': vod.get('vod_director', '') or '',
            'vod_remarks': vod.get('vod_remarks', '') or '',
            'vod_content': re.sub(r'<[^>]+>', '',
                                  vod.get('vod_content', '') or vod.get('vod_blurb', '') or '').strip(),
            'vod_play_from': '$$$'.join(play_from),
            'vod_play_url': '$$$'.join(play_url),
        }
        return {'list': [item]}

    def _siteLines(self, play_from, play_url):
        """按网站顺序重排线路并重命名为网站线路名"""
        pairs = list(zip(play_from, play_url))

        def rank(p):
            f = p[0]
            return SITE_LINE_ORDER.index(f) if f in SITE_LINE_ORDER else len(SITE_LINE_ORDER)
        pairs.sort(key=rank)
        out_from = [SITE_LINE_NAMES.get(f, f) for f, _ in pairs]
        out_url = [u for _, u in pairs]
        return out_from, out_url

    # ---------- 搜索 ----------
    def searchContent(self, key, quick=1, *args, **kwargs):
        try:
            key = str(key or '').strip()
        except Exception:
            return {'list': []}
        if not key:
            return {'list': []}
        cands = [key]
        if ' ' in key:
            cands.append(re.sub(r'\s+', '', key))
        if '%' in key:
            try:
                dec = unquote(key)
                if dec and dec != key:
                    cands.append(dec)
                    if ' ' in dec:
                        cands.append(re.sub(r'\s+', '', dec))
            except Exception:
                pass
        for kw in cands:
            try:
                j = self.getJson(self.host + API_PATH + 'ac=videolist&wd=' + quote(kw))
                lst = self.parseVods(j.get('list', []))
                if lst:
                    return {'list': lst}
            except Exception:
                continue
        return {'list': []}

    # ---------- 播放 ----------
    # 官方网页线路(优酷/爱奇艺/腾讯等)无法从本站解出直链, 内嵌虾米解析接口兜底
    XIA_MI = 'https://jx.xmflv.com/?url='

    def playerContent(self, flag, id, vipFlags=1):
        headers = {'User-Agent': UA, 'Referer': self.host + '/'}
        is_direct = any(ext in (id or '') for ext in ('.m3u8', '.m3u', '.mp4', '.mkv', '.flv', 'magnet:'))
        if is_direct:
            # m3u8/mp4 等真实直链 → 直接播(parse=0 秒开)
            return {
                'parse': 0,
                'playUrl': '',
                'url': id,
                'header': headers,
            }
        # 官方网页线路 → 走虾米解析(parse=1): url 直接拼完整虾米地址, playUrl 置空
        # (与"帧不戳4K"同机制: 由TVBox按网页解析方式处理带虾米前缀的url)
        jx_url = self.XIA_MI + quote(id, safe='')
        return {
            'parse': 1,
            'playUrl': '',
            'url': jx_url,
            'header': headers,
        }

    def localProxy(self, param):
        url = ''
        if isinstance(param, dict):
            url = param.get('url') or param.get('video') or ''
        elif param is not None:
            url = getattr(param, 'url', '') or getattr(param, 'video', '')
        if not url:
            return [500, 'text/plain', 'no url', '']
        try:
            r = self.fetch(url, 12)
            if not r:
                return [500, 'text/plain', 'fetch failed', '']
            text = r if isinstance(r, str) else ''
        except Exception as e:
            return [500, 'text/plain', 'fetch err: %s' % e, '']
        if '#EXTM3U' in text[:30]:
            base = url.rsplit('/', 1)[0] + '/'
            lines = []
            for ln in text.splitlines():
                s = ln.strip()
                if not s or s.startswith('#'):
                    lines.append(ln)
                    continue
                seg = s if s.startswith('http') else base + s
                lines.append('proxy?url=' + quote(seg))
            return [200, 'application/vnd.apple.mpegurl', '\n'.join(lines), '']
        return [200, 'application/octet-stream', text, '']

    # ---------- 生命周期 ----------
    def getName(self):
        return '柚子影视'

    def isVideoFormat(self, url):
        return any(e in (url or '') for e in ['.m3u8', '.m3u', '.mp4', '.mkv'])

    def manualVideoArithmetic(self, url):
        return None

    def liveContent(self, url):
        return ''


# 独立测试入口
if __name__ == '__main__':
    t0 = time.time()
    s = Spider()
    s.init('')
    print('init: %.2fs host: %s' % (time.time() - t0, s.host))
    h = s.homeContent(True)
    print('home: class=%d list=%d filters=%d' % (len(h['class']), len(h['list']), len(h.get('filters') or {})))
    c1 = s.categoryContent('1', 1, 1, {})
    c2 = s.categoryContent('1', 2, 1, {})
    print('分类 p1=%d p2=%d pc=%s' % (len(c1['list']), len(c2['list']), c1['pagecount']))
    cf = s.categoryContent('1', 1, 1, {'area': '大陆', 'year': '2025'})
    print('筛选(大陆/2025):', len(cf['list']), cf['list'][0]['vod_name'] if cf['list'] else '')
    sr = s.searchContent('九门', 0)
    print('搜索:', len(sr['list']))
    if sr['list']:
        d = s.detailContent([sr['list'][0]['vod_id']])
        if d['list']:
            v = d['list'][0]
            print('详情:', v['vod_name'], '| 线路:', v['vod_play_from'].split('$$$'))
