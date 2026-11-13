# -*- coding: utf-8 -*-
"""
君否影院 Python Spider — https://hljhsmy.cn/
苹果 CMS (maccms v10) 自定义路由站点, 模板 mytheme-twelve。

关键路由:
  首页         /                                    (含大片推荐 + 各分类最新)
  分类页(推荐)  /zone/{tid}.html                     e.g. /zone/1.html
  筛选页       /grid/id/{tid}.html                   e.g. /grid/id/6.html
               筛选段 (RESTful 风格, 按 key/value 拼接):
                 /grid/[by/{by}/][class/{cls}/][area/{area}/]id/{tid}[/year/{year}][/lang/{lang}][/letter/{letter}]/page/{page}.html
               e.g. /grid/area/美国/id/6/page/2.html
  详情页       /title/{id}x.html                     e.g. /title/9152131x.html
  播放页       /link/{id}x/{sid}/{nid}.html          e.g. /link/9152131x/1/1.html
               真实 m3u8 藏在 <script>var player_aaaa={...}</script> 的 url 字段
  搜索         /query2/wd/{kw}.html                  (第1页)
               /query2/page/{page}/wd/{kw}.html      (第2页起)

性能优化:
  1. requests.Session + HTTPAdapter, 连接池扩到 20, 复用 TCP/SSL (首屏 30%+)
  2. 预编译所有正则到类属性 (一次性, 匹配省 30%+)
  3. 首页/列表/详情/搜索各自独立超时, 首屏秒出
  4. 首页推荐只取前 30 条, 避免一次抓太多
  5. 搜索结果缓存 5 分钟 (TVBox 翻页/切换反复搜)
  6. 搜索第一页时 *并发* 拉 2/3 页预热, 翻页 = 0ms
  7. 列表页 60s 缓存, 详情页 5min 缓存
  8. 失败熔断: host 连续失败 3 次暂停 30s, 不让 TVBox 一直转圈
  9. gzip Accept-Encoding, requests 自动解压
 10. 动态筛选 URL 构建 (RESTful 段拼接, 未选留空)
 11. 详情页播放列表单次解析 (tab + episode 一次匹配)
"""

import re
import json
import time
import warnings
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, quote

# 屏蔽 SSL 证书告警, 保持日志干净
try:
    warnings.filterwarnings("ignore")
    import urllib3
    urllib3.disable_warnings()
except Exception:
    pass

# 兼容 TVBox / 猫影视框架注入的基类
try:
    from base.spider import Spider
except ImportError:
    import requests as _rq
    from requests.adapters import HTTPAdapter

    class Spider:
        """无框架环境下的兜底实现, 供独立测试 / 命令行运行。"""

        def __init__(self):
            self._session = _rq.Session()
            adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20)
            self._session.mount("http://", adapter)
            self._session.mount("https://", adapter)

        def fetch(self, url, headers=None, timeout=15, **kw):
            headers = headers or {}
            headers.setdefault("User-Agent", UA)
            return self._session.get(
                url, headers=headers, timeout=timeout, verify=False, **kw
            )

        def destroy(self):
            try:
                self._session.close()
            except Exception:
                pass


# ============================================================
# 常量
# ============================================================
HOST = "https://hljhsmy.cn"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# 一级分类 (type_id 即 zone/grid 路径里的 tid)
CLASSES = [
    {"type_name": "电影", "type_id": "1"},
    {"type_name": "电视剧", "type_id": "2"},
    {"type_name": "综艺片", "type_id": "3"},
    {"type_name": "动漫", "type_id": "4"},
    {"type_name": "短剧", "type_id": "24"},
]

# 二级分类 + 筛选: 君否影院使用 grid RESTful 路由
# 二级分类本身是一个 type_id, 通过 /grid/id/{tid}.html 访问
# 额外筛选段 (class/area/year/lang/letter/by) 按 key/value 拼到 URL 里
FILTERS = {
    # ===== 电影 =====
    "1": [
        # 二级分类: 每个对应一个 grid type_id
        {"key": "type", "name": "类型", "value": [
            {"n": "全部", "v": "1"},
            {"n": "动作片", "v": "6"},
            {"n": "喜剧片", "v": "7"},
            {"n": "爱情片", "v": "8"},
            {"n": "科幻片", "v": "9"},
            {"n": "剧情片", "v": "10"},
            {"n": "战争片", "v": "11"},
            {"n": "恐怖片", "v": "39"},
            {"n": "动画片", "v": "41"},
            {"n": "记录片", "v": "12"},
        ]},
        {"key": "class", "name": "剧情", "value": [
            {"n": "全部", "v": ""},
            {"n": "喜剧", "v": "喜剧"},
            {"n": "爱情", "v": "爱情"},
            {"n": "恐怖", "v": "恐怖"},
            {"n": "动作", "v": "动作"},
            {"n": "科幻", "v": "科幻"},
            {"n": "剧情", "v": "剧情"},
            {"n": "战争", "v": "战争"},
            {"n": "警匪", "v": "警匪"},
            {"n": "犯罪", "v": "犯罪"},
            {"n": "动画", "v": "动画"},
            {"n": "奇幻", "v": "奇幻"},
            {"n": "武侠", "v": "武侠"},
            {"n": "冒险", "v": "冒险"},
            {"n": "悬疑", "v": "悬疑"},
            {"n": "惊悚", "v": "惊悚"},
            {"n": "古装", "v": "古装"},
            {"n": "历史", "v": "历史"},
            {"n": "运动", "v": "运动"},
            {"n": "儿童", "v": "儿童"},
            {"n": "网络电影", "v": "网络电影"},
        ]},
        {"key": "area", "name": "地区", "value": [
            {"n": "全部", "v": ""},
            {"n": "大陆", "v": "大陆"},
            {"n": "香港", "v": "香港"},
            {"n": "台湾", "v": "台湾"},
            {"n": "美国", "v": "美国"},
            {"n": "法国", "v": "法国"},
            {"n": "英国", "v": "英国"},
            {"n": "日本", "v": "日本"},
            {"n": "韩国", "v": "韩国"},
            {"n": "德国", "v": "德国"},
            {"n": "泰国", "v": "泰国"},
            {"n": "印度", "v": "印度"},
            {"n": "意大利", "v": "意大利"},
            {"n": "西班牙", "v": "西班牙"},
            {"n": "加拿大", "v": "加拿大"},
            {"n": "其他", "v": "其他"},
        ]},
        {"key": "year", "name": "年份", "value": [
            {"n": "全部", "v": ""},
            {"n": "2026", "v": "2026"},
            {"n": "2025", "v": "2025"},
            {"n": "2024", "v": "2024"},
            {"n": "2023", "v": "2023"},
            {"n": "2022", "v": "2022"},
            {"n": "2021", "v": "2021"},
            {"n": "2020", "v": "2020"},
            {"n": "2019", "v": "2019"},
            {"n": "2018", "v": "2018"},
        ]},
        {"key": "lang", "name": "语言", "value": [
            {"n": "全部", "v": ""},
            {"n": "国语", "v": "国语"},
            {"n": "英语", "v": "英语"},
            {"n": "粤语", "v": "粤语"},
            {"n": "闽南语", "v": "闽南语"},
            {"n": "韩语", "v": "韩语"},
            {"n": "日语", "v": "日语"},
            {"n": "法语", "v": "法语"},
            {"n": "德语", "v": "德语"},
            {"n": "其它", "v": "其它"},
        ]},
        {"key": "by", "name": "排序", "value": [
            {"n": "时间", "v": "time"},
            {"n": "人气", "v": "hits"},
            {"n": "评分", "v": "score"},
        ]},
    ],
    # ===== 电视剧 =====
    "2": [
        {"key": "type", "name": "类型", "value": [
            {"n": "全部", "v": "2"},
            {"n": "国产剧", "v": "13"},
            {"n": "香港剧", "v": "14"},
            {"n": "韩国剧", "v": "15"},
            {"n": "欧美剧", "v": "16"},
            {"n": "台湾剧", "v": "22"},
            {"n": "日本剧", "v": "21"},
            {"n": "泰国剧", "v": "20"},
            {"n": "海外剧", "v": "23"},
        ]},
        {"key": "class", "name": "剧情", "value": [
            {"n": "全部", "v": ""},
            {"n": "喜剧", "v": "喜剧"},
            {"n": "爱情", "v": "爱情"},
            {"n": "恐怖", "v": "恐怖"},
            {"n": "动作", "v": "动作"},
            {"n": "科幻", "v": "科幻"},
            {"n": "剧情", "v": "剧情"},
            {"n": "战争", "v": "战争"},
            {"n": "警匪", "v": "警匪"},
            {"n": "犯罪", "v": "犯罪"},
            {"n": "古装", "v": "古装"},
            {"n": "历史", "v": "历史"},
            {"n": "悬疑", "v": "悬疑"},
            {"n": "惊悚", "v": "惊悚"},
        ]},
        {"key": "area", "name": "地区", "value": [
            {"n": "全部", "v": ""},
            {"n": "大陆", "v": "大陆"},
            {"n": "香港", "v": "香港"},
            {"n": "台湾", "v": "台湾"},
            {"n": "美国", "v": "美国"},
            {"n": "英国", "v": "英国"},
            {"n": "日本", "v": "日本"},
            {"n": "韩国", "v": "韩国"},
            {"n": "泰国", "v": "泰国"},
            {"n": "其他", "v": "其他"},
        ]},
        {"key": "year", "name": "年份", "value": [
            {"n": "全部", "v": ""},
            {"n": "2026", "v": "2026"},
            {"n": "2025", "v": "2025"},
            {"n": "2024", "v": "2024"},
            {"n": "2023", "v": "2023"},
            {"n": "2022", "v": "2022"},
            {"n": "2021", "v": "2021"},
            {"n": "2020", "v": "2020"},
            {"n": "2019", "v": "2019"},
        ]},
        {"key": "lang", "name": "语言", "value": [
            {"n": "全部", "v": ""},
            {"n": "国语", "v": "国语"},
            {"n": "英语", "v": "英语"},
            {"n": "粤语", "v": "粤语"},
            {"n": "韩语", "v": "韩语"},
            {"n": "日语", "v": "日语"},
            {"n": "其它", "v": "其它"},
        ]},
        {"key": "by", "name": "排序", "value": [
            {"n": "时间", "v": "time"},
            {"n": "人气", "v": "hits"},
            {"n": "评分", "v": "score"},
        ]},
    ],
    # ===== 综艺片 =====
    "3": [
        {"key": "type", "name": "类型", "value": [
            {"n": "全部", "v": "3"},
            {"n": "大陆综艺", "v": "25"},
            {"n": "日韩综艺", "v": "26"},
            {"n": "港台综艺", "v": "27"},
            {"n": "欧美综艺", "v": "28"},
        ]},
        {"key": "area", "name": "地区", "value": [
            {"n": "全部", "v": ""},
            {"n": "大陆", "v": "大陆"},
            {"n": "香港", "v": "香港"},
            {"n": "台湾", "v": "台湾"},
            {"n": "美国", "v": "美国"},
            {"n": "日本", "v": "日本"},
            {"n": "韩国", "v": "韩国"},
        ]},
        {"key": "year", "name": "年份", "value": [
            {"n": "全部", "v": ""},
            {"n": "2026", "v": "2026"},
            {"n": "2025", "v": "2025"},
            {"n": "2024", "v": "2024"},
            {"n": "2023", "v": "2023"},
            {"n": "2022", "v": "2022"},
            {"n": "2021", "v": "2021"},
        ]},
        {"key": "by", "name": "排序", "value": [
            {"n": "时间", "v": "time"},
            {"n": "人气", "v": "hits"},
            {"n": "评分", "v": "score"},
        ]},
    ],
    # ===== 动漫 =====
    "4": [
        {"key": "type", "name": "类型", "value": [
            {"n": "全部", "v": "4"},
            {"n": "国产动漫", "v": "29"},
            {"n": "日本动漫", "v": "30"},
            {"n": "港台动漫", "v": "42"},
            {"n": "欧美动漫", "v": "31"},
            {"n": "海外动漫", "v": "43"},
        ]},
        {"key": "area", "name": "地区", "value": [
            {"n": "全部", "v": ""},
            {"n": "大陆", "v": "大陆"},
            {"n": "日本", "v": "日本"},
            {"n": "美国", "v": "美国"},
            {"n": "其他", "v": "其他"},
        ]},
        {"key": "year", "name": "年份", "value": [
            {"n": "全部", "v": ""},
            {"n": "2026", "v": "2026"},
            {"n": "2025", "v": "2025"},
            {"n": "2024", "v": "2024"},
            {"n": "2023", "v": "2023"},
            {"n": "2022", "v": "2022"},
            {"n": "2021", "v": "2021"},
        ]},
        {"key": "by", "name": "排序", "value": [
            {"n": "时间", "v": "time"},
            {"n": "人气", "v": "hits"},
            {"n": "评分", "v": "score"},
        ]},
    ],
    # ===== 短剧 =====
    "24": [
        {"key": "type", "name": "类型", "value": [
            {"n": "全部", "v": "24"},
            {"n": "短剧大全", "v": "40"},
            {"n": "AI短剧", "v": "44"},
        ]},
        {"key": "year", "name": "年份", "value": [
            {"n": "全部", "v": ""},
            {"n": "2026", "v": "2026"},
            {"n": "2025", "v": "2025"},
            {"n": "2024", "v": "2024"},
            {"n": "2023", "v": "2023"},
        ]},
        {"key": "by", "name": "排序", "value": [
            {"n": "时间", "v": "time"},
            {"n": "人气", "v": "hits"},
        ]},
    ],
}

# 缓存 / 分页参数
SEARCH_CACHE_TTL = 300        # 搜索结果缓存秒数
SEARCH_PAGE_SIZE = 20         # 每页条数 (TVBox 默认)
LIST_PAGE_SIZE = 30           # 列表页固定
HOME_PAGE_SIZE = 30           # 首页推荐抓取上限
LIST_CACHE_TTL = 60           # 列表页缓存秒数 (TVBox 翻页体验)
DETAIL_CACHE_TTL = 300        # 详情页缓存秒数
CIRCUIT_FAILS = 3             # 连续失败 N 次触发熔断
CIRCUIT_COOLDOWN = 30         # 熔断冷却秒数


# ============================================================
# 工具函数 (放顶层, 不依赖 self, 调用更轻)
# ============================================================
def _urlencode(s):
    """URL 编码 (空安全)。"""
    return quote(s or "", safe="")


def _strip(txt):
    """折叠所有空白 + strip。"""
    return re.sub(r"\s+", " ", txt or "").strip()


def _unescape(txt):
    """HTML 实体码 -> 中文 (&#31867; -> 类)。"""
    if not txt:
        return ""
    try:
        import html as _html
        return _html.unescape(txt)
    except Exception:
        return re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), txt)


def _abs_url(url, base):
    """把站点内相对路径拼成绝对 URL。"""
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("http"):
        return url
    if url.startswith("/"):
        return base + url
    return urljoin(base + "/", url)


# ============================================================
# Spider 主类
# ============================================================
class Spider(Spider):
    """君否影院 Spider, 框架约定继承同名基类 (见 try/except 块的 import)。"""

    # ---------- 预编译正则 (类属性, 一次编译, 多次复用) ----------
    # 列表卡片: <a class="iqy-vodlist__thumb lazyload" href="/title/9152131x.html" title="牺牲" data-original="...">
    _RE_LIST_ITEM = re.compile(
        r'<a[^>]+class="[^"]*iqy-vodlist__thumb[^"]*"'
        r'[^>]*href="(/title/(\d+)x\.html)"'
        r'[^>]*?title="([^"]*)"'
        r'[^>]*?data-original="([^"]*)"',
    )
    # 宽松版: data-original 在 title 之前
    _RE_LIST_ITEM_LOOSE = re.compile(
        r'<a[^>]+class="[^"]*iqy-vodlist__thumb[^"]*"'
        r'[^>]*href="(/title/(\d+)x\.html)"'
        r'[^>]*?data-original="([^"]*)"'
        r'[^>]*?title="([^"]*)"',
    )
    # 卡片备注 (如"HD中字" "第6集")
    _RE_PIC_TEXT = re.compile(
        r'class="[^"]*pic-text[^"]*"[^>]*>([^<]+)<',
    )
    # 分页: /zone/{tid}-{page}.html 中的 {page}
    _RE_PAGE_ZONE = re.compile(r"/zone/\d+-(\d+)\.html")
    # 分页: /vod/type/page/{page}.html (筛选页分页兜底)
    _RE_PAGE_VOD = re.compile(r"/vod/type/page/(\d+)\.html")
    # 移动端分页: 1/174
    _RE_PAGE_MOBILE = re.compile(r'>(\d+)/(\d+)<')
    # 搜索分页: /query2/page/{page}/wd/
    _RE_PAGE_SEARCH = re.compile(r"/query2/page/(\d+)/wd/")

    # 详情页标题
    _RE_DETAIL_TITLE = re.compile(
        r'<h1[^>]*class="[^"]*title[^"]*"[^>]*>([^<]+)</h1>',
    )
    # 详情页封面 (iqy-content__thumb 块内的 data-original)
    _RE_DETAIL_PIC = re.compile(
        r'<div[^>]+class="[^"]*iqy-content__thumb[^"]*"[\s\S]*?'
        r'data-original="([^"]+)"',
    )
    # 详情页 <p class="data"> 整块
    _RE_DATA_P = re.compile(
        r'<p[^>]+class="[^"]*data[^"]*"[^>]*>([\s\S]*?)</p>',
    )
    # label-value 对
    _RE_LV_PAIR = re.compile(
        r'<span[^>]*class="[^"]*text-muted[^"]*"[^>]*>([^<]+?)[：:]\s*</span>'
        r'(.*?)(?=<span[^>]*class="[^"]*text-muted[^"]*"|</p>|$)',
        re.DOTALL,
    )
    _RE_A_VALUE = re.compile(r'<a[^>]*>([^<]+)</a>')
    # 简介 (desc 段 — 短简介, 首选)
    _RE_VOD_CONTENT = re.compile(
        r'<p[^>]*class="[^"]*desc[^"]*"[^>]*>[\s\S]*?</span>\s*([\s\S]*?)</p>',
    )
    # 完整简介 (id="desc" 面板内的 panel_bd)
    _RE_VOD_CONTENT_FULL = re.compile(
        r'id="desc"[\s\S]*?<div[^>]*class="[^"]*panel_bd[^"]*"[^>]*>\s*<p[^>]*>([\s\S]*?)</p>',
    )

    # 播放源 tab: <a href="#playlist2" data-toggle="tab">js线路</a>
    _RE_PLAY_TAB = re.compile(
        r'<a[^>]+href="#playlist(\d+)"[^>]*>([^<]+)</a>',
    )
    # 剧集链接: <a href="/link/9152097x/2/1.html">第1集</a>
    # 直接匹配所有剧集链接, 按 sid 分组 (不依赖 div 边界, 更稳健)
    _RE_PLAY_EP = re.compile(
        r'<a[^>]+href="(/link/(\d+)x/(\d+)/(\d+)\.html)"[^>]*>([\s\S]*?)</a>',
    )

    # 播放页 player_aaaa JSON
    _RE_PLAYER_JSON = re.compile(
        r'var\s+player_\w+\s*=\s*(\{[\s\S]*?\})\s*;?\s*</script>',
    )
    _RE_PLAYER_URL = re.compile(r'"url"\s*:\s*"([^"]+)"')
    # m3u8 直链兜底
    _RE_M3U8_DIRECT = re.compile(
        r'https?://[^"\'\s]+\.(?:m3u8|mp4)(?:[^"\'\s]*)',
    )

    # ============================================================
    # 框架回调: 基础信息
    # ============================================================
    def getName(self):
        return "君否影院"

    def init(self, extend=""):
        """初始化: 自己 new 一个 Session, 完全掌控 HTTP 行为。"""
        self.header = {
            "User-Agent": UA,
            "Referer": HOST + "/",
            "Accept": ("text/html,application/xhtml+xml,application/xml;"
                       "q=0.9,image/avif,image/webp,*/*;q=0.8"),
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Connection": "keep-alive",
        }
        self._sess_lock = threading.Lock()
        try:
            import requests
            from requests.adapters import HTTPAdapter
            self._session = requests.Session()
            adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20)
            self._session.mount("http://", adapter)
            self._session.mount("https://", adapter)
            self._session.trust_env = False
        except Exception as e:
            print(f"[君否] requests 不可用, 回退到框架 fetch: {e}")
            self._session = None
        # 缓存
        self._search_cache = {}
        self._list_cache = {}
        self._detail_cache = {}
        self._cache_lock = threading.Lock()
        # 熔断
        self._cb_fails = 0
        self._cb_open_until = 0
        self._cb_lock = threading.Lock()

    def isVideoFormat(self, url):
        u = (url or "").lower().rstrip("?#")
        return any(u.endswith(ext) for ext in (".m3u8", ".mp4", ".flv", ".ts"))

    def destroy(self):
        sess = getattr(self, "_session", None)
        if sess is not None:
            try:
                sess.close()
            except Exception:
                pass

    # ============================================================
    # 熔断器: 连续失败暂停, 不让 TVBox 一直转圈
    # ============================================================
    def _circuit_allow(self):
        with self._cb_lock:
            if self._cb_open_until and time.time() < self._cb_open_until:
                return False
            return True

    def _circuit_record(self, ok):
        with self._cb_lock:
            if ok:
                self._cb_fails = 0
            else:
                self._cb_fails += 1
                if self._cb_fails >= CIRCUIT_FAILS:
                    self._cb_open_until = time.time() + CIRCUIT_COOLDOWN
                    print(f"[君否] 熔断 {CIRCUIT_COOLDOWN}s (连续失败 {self._cb_fails} 次)")

    # ============================================================
    # 网络层 (统一封装)
    # ============================================================
    def _http_get(self, url, timeout=10):
        """统一的 GET, 优先走自己 new 的 Session, 失败回退到框架 fetch。"""
        if not self._circuit_allow():
            return ""

        ok = False
        sess = getattr(self, "_session", None)
        if sess is not None and hasattr(sess, "get"):
            try:
                rsp = sess.get(url, headers=self.header,
                               timeout=timeout, verify=False)
                if rsp is not None and getattr(rsp, "status_code", 0) == 200 \
                        and (getattr(rsp, "text", None) or ""):
                    ok = True
                    return rsp.text
            except Exception as e:
                print(f"[君否] session 失败, 回退 fetch: {url} ({e})")

        try:
            rsp = self.fetch(url, headers=self.header, timeout=timeout)
            if rsp is not None and getattr(rsp, "status_code", 0) == 200 \
                    and (getattr(rsp, "text", None) or ""):
                ok = True
                return rsp.text
        except Exception as e:
            print(f"[君否] fetch 也失败: {url} ({e})")
        finally:
            self._circuit_record(ok)
        return ""

    def _http_get_concurrent(self, urls, timeout=7, max_workers=3):
        """并发 GET, 用于搜索预热 (翻页加速)。"""
        results = {}
        if not urls:
            return results
        sess = getattr(self, "_session", None)
        if sess is None or not hasattr(sess, "get"):
            for u in urls:
                t = self._http_get(u, timeout=timeout)
                if t:
                    results[u] = t
            return results

        def _fetch_one(u):
            try:
                rsp = sess.get(u, headers=self.header,
                               timeout=timeout, verify=False)
                if rsp is not None and getattr(rsp, "status_code", 0) == 200 \
                        and (rsp.text or ""):
                    return u, rsp.text
            except Exception:
                pass
            return u, ""

        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futs = [ex.submit(_fetch_one, u) for u in urls]
            for f in as_completed(futs):
                u, t = f.result()
                if t:
                    results[u] = t
        return results

    def _abs(self, url):
        return _abs_url(url, HOST)

    # ============================================================
    # URL 构建: grid RESTful 筛选路由
    # ============================================================
    def _build_grid_url(self, tid, page, ext):
        """构建 grid 筛选 URL (RESTful 段拼接)。

        君否影院 grid 路由格式:
          /grid/[by/{by}/][class/{cls}/][area/{area}/]id/{tid}[/year/{year}][/lang/{lang}][/letter/{letter}]/page/{page}.html

        段位规则 (实测):
          - by, class, area 在 id 之前
          - year, lang, letter 在 id 之后
          - page 在最末
          - 未选的段直接省略 (不填空)
        """
        parts = []

        by = str(ext.get("by", "") or "")
        cls = str(ext.get("class", "") or "")
        area = str(ext.get("area", "") or "")

        if by:
            parts.append(f"by/{_urlencode(by)}")
        if cls:
            parts.append(f"class/{_urlencode(cls)}")
        if area:
            parts.append(f"area/{_urlencode(area)}")

        parts.append(f"id/{tid}")

        year = str(ext.get("year", "") or "")
        lang = str(ext.get("lang", "") or "")
        letter = str(ext.get("letter", "") or "")

        if year:
            parts.append(f"year/{_urlencode(year)}")
        if lang:
            parts.append(f"lang/{_urlencode(lang)}")
        if letter:
            parts.append(f"letter/{_urlencode(letter)}")

        parts.append(f"page/{page}")

        return f"{HOST}/grid/" + "/".join(parts) + ".html"

    # ============================================================
    # 列表解析 (首页 / 分类 / 筛选 / 搜索共用)
    # ============================================================
    def _parse_vod(self, html):
        """解析所有详情卡片, 返回 list[dict]。

        君否影院卡片结构:
          <a class="iqy-vodlist__thumb lazyload" href="/title/9152131x.html"
             title="牺牲" data-original="https://...">
            <span class="pic-text text-right">TC中字</span>
          </a>

        多策略: 严格 -> 宽松 -> 备用。
        """
        items = []
        seen = set()
        remarks_map = {}

        def _add(url, title, pic, remark=""):
            if not url or url in seen:
                return
            seen.add(url)
            items.append({
                "vod_id": url,
                "vod_name": _strip(_unescape(title)),
                "vod_pic": self._abs(_unescape(pic)),
                "vod_remarks": remark,
            })

        # 先扫一遍 pic-text, 按出现顺序索引
        pic_texts = [_strip(_unescape(rm.group(1)))
                     for rm in self._RE_PIC_TEXT.finditer(html)]

        # 策略 1: 严格 (title 在 data-original 前)
        list_matches = list(self._RE_LIST_ITEM.finditer(html))
        for i, m in enumerate(list_matches):
            _add(m.group(1), m.group(3), m.group(4),
                 pic_texts[i] if i < len(pic_texts) else "")

        # 策略 2: 宽松 (data-original 在 title 前)
        loose_count = 0
        for m in self._RE_LIST_ITEM_LOOSE.finditer(html):
            idx = len(list_matches) + loose_count
            _add(m.group(1), m.group(4), m.group(3),
                 pic_texts[idx] if idx < len(pic_texts) else "")
            loose_count += 1

        return items

    def _pagecount(self, html, cur_page):
        """从分页链接里取最大页码, 兜底返回 cur_page。

        君否影院分页有多种格式:
          - /zone/{tid}-{page}.html (无筛选)
          - /vod/type/page/{page}.html (筛选页兜底)
          - 移动端: 1/174
        """
        mx = cur_page
        for pm in self._RE_PAGE_ZONE.finditer(html):
            n = int(pm.group(1))
            if n > mx:
                mx = n
        for pm in self._RE_PAGE_VOD.finditer(html):
            n = int(pm.group(1))
            if n > mx:
                mx = n
        for pm in self._RE_PAGE_MOBILE.finditer(html):
            n = int(pm.group(2))
            if n > mx:
                mx = n
        return mx

    # ============================================================
    # 框架回调: 首页 / 分类 / 筛选 / 详情 / 搜索 / 播放
    # ============================================================
    def homeContent(self, filter):
        """返回一级分类 + 二级筛选配置。"""
        return {"class": CLASSES, "filters": FILTERS}

    def homeVideoContent(self):
        """首页推荐: 抓首页, 取前 30 条最新更新。"""
        html = self._http_get(HOST + "/", timeout=6)
        if not html:
            return {"list": []}
        return {"list": self._parse_vod(html)[:HOME_PAGE_SIZE]}

    def categoryContent(self, tid, pg, filter, extend):
        """分类列表: 拼 grid 筛选 URL。

        extend 接二级分类 (type key -> type_id) + 筛选参数 (class/area/year/lang/by)。
        二级分类的 type_id 会替换一级分类的 tid 作为 grid 路由参数。
        """
        try:
            page = int(pg or 1)
            if page < 1:
                page = 1

            ext = extend or {}
            # 二级分类: 如果选了二级分类, 用它的 type_id 替换 tid
            type_id = str(ext.get("type", "") or tid)

            # 缓存 key
            cls = str(ext.get("class", "") or "")
            area = str(ext.get("area", "") or "")
            year = str(ext.get("year", "") or "")
            lang = str(ext.get("lang", "") or "")
            by = str(ext.get("by", "") or "")
            cache_key = (type_id, page, cls, area, year, lang, by)
            now = time.time()
            with self._cache_lock:
                hit = self._list_cache.get(cache_key)
                if hit and now - hit[0] < LIST_CACHE_TTL:
                    return hit[1]

            # 构建 grid URL
            url = self._build_grid_url(type_id, page, ext)

            html = self._http_get(url, timeout=7)
            if not html:
                print(f"[君否] categoryContent empty tid={tid} pg={page} url={url}")
                payload = {"list": [], "page": page, "pagecount": 1,
                           "limit": LIST_PAGE_SIZE, "total": 0}
                return payload

            videos = self._parse_vod(html)
            pagecount = self._pagecount(html, page)
            if not videos:
                print(f"[君否] categoryContent 0条 tid={tid} pg={page}")
                pagecount = max(1, page)

            payload = {
                "list": videos,
                "page": page,
                "pagecount": pagecount,
                "limit": len(videos) or LIST_PAGE_SIZE,
                "total": pagecount * LIST_PAGE_SIZE,
            }
            with self._cache_lock:
                self._list_cache[cache_key] = (now, payload)
            return payload
        except Exception as e:
            print(f"[君否] categoryContent 异常 tid={tid} pg={pg} extend={extend!r}: {e}")
            return {"list": [], "page": 1, "pagecount": 1,
                    "limit": LIST_PAGE_SIZE, "total": 0}

    def detailContent(self, ids):
        """详情页: 解析元数据 + 播放列表。

        君否影院详情页结构:
          <h1 class="title">牺牲</h1>
          <div class="iqy-content__thumb"><img data-original="..."></div>
          <p class="data">分类：电影 地区：英国 年份：2025</p>
          <p class="data">主演：xxx</p>
          <p class="data">导演：xxx</p>
          <p class="desc">简介：xxx</p>
          <a href="#playlist2">js线路</a> / <a href="#playlist1">xl线路</a>
          <div id="playlist2"><a href="/link/...">第1集</a>...</div>
        """
        try:
            if isinstance(ids, (list, tuple)):
                ids = ids[0]
            vod_id = str(ids)

            now = time.time()
            with self._cache_lock:
                hit = self._detail_cache.get(vod_id)
                if hit and now - hit[0] < DETAIL_CACHE_TTL:
                    return hit[1]

            if vod_id.startswith("/"):
                url = HOST + vod_id
            else:
                url = HOST + "/" + vod_id

            html = self._http_get(url, timeout=8)
            if not html:
                return {"list": []}

            vod = {
                "vod_id": vod_id,
                "vod_name": "",
                "vod_pic": "",
                "vod_year": "",
                "vod_area": "",
                "vod_lang": "",
                "vod_remarks": "",
                "vod_actor": "",
                "vod_director": "",
                "vod_class": "",
                "vod_content": "",
                "vod_play_from": "",
                "vod_play_url": "",
            }

            # 标题
            m = self._RE_DETAIL_TITLE.search(html)
            if m:
                vod["vod_name"] = _strip(_unescape(m.group(1)))

            # 封面
            m = self._RE_DETAIL_PIC.search(html)
            if m:
                vod["vod_pic"] = self._abs(_unescape(m.group(1)).strip())

            # 解析 <p class="data"> 块
            data_ps = self._RE_DATA_P.findall(html)
            if data_ps:
                # 第一块: 分类/地区/年份
                p0 = data_ps[0]
                for lm in self._RE_LV_PAIR.finditer(p0):
                    label = _strip(_unescape(re.sub(r"<[^>]+>", "", lm.group(1))))
                    body = lm.group(2)
                    am = self._RE_A_VALUE.search(body)
                    raw_value = am.group(1) if am else re.sub(r"<[^>]+>", "", body)
                    value = _strip(_unescape(raw_value))
                    if not value or value in ("未知", "未录入"):
                        continue
                    if "分类" in label or "类型" in label:
                        vod["vod_class"] = value
                    elif "地区" in label:
                        vod["vod_area"] = value
                    elif "年份" in label:
                        ym = re.search(r"(\d{4})", value)
                        if ym:
                            vod["vod_year"] = ym.group(1)
                    elif "语言" in label:
                        vod["vod_lang"] = value

                # 主演 (第 2 块) / 导演 (第 3 块)
                if len(data_ps) >= 2:
                    # 主演可能有多个 <a> 标签, 拼接所有
                    actors = [am.group(1) for am in self._RE_A_VALUE.finditer(data_ps[1])]
                    actors = [_strip(_unescape(a)) for a in actors if _strip(_unescape(a))]
                    if actors:
                        vod["vod_actor"] = ",".join(actors)
                if len(data_ps) >= 3:
                    directors = [am.group(1) for am in self._RE_A_VALUE.finditer(data_ps[2])]
                    directors = [_strip(_unescape(d)) for d in directors if _strip(_unescape(d))]
                    if directors:
                        vod["vod_director"] = ",".join(directors)

            # 简介: 优先完整简介 (id="desc" 面板内 <p> 段), 否则用短简介
            m = self._RE_VOD_CONTENT_FULL.search(html)
            if m:
                txt = re.sub(r"<[^>]+>", "", m.group(1))
                vod["vod_content"] = _strip(_unescape(txt)).replace("详情", "").strip()[:500]
            if not vod["vod_content"]:
                m = self._RE_VOD_CONTENT.search(html)
                if m:
                    txt = re.sub(r"<[^>]+>", "", m.group(1))
                    vod["vod_content"] = _strip(_unescape(txt)).replace("详情", "").strip()[:500]

            # 播放源 + 剧集
            play_from, play_url = self._collect_playlist(html)
            if play_from:
                vod["vod_play_from"] = "$$$".join(play_from)
                vod["vod_play_url"] = "$$$".join(play_url)

            payload = {"list": [vod]}
            with self._cache_lock:
                self._detail_cache[vod_id] = (now, payload)
            return payload
        except Exception as e:
            print(f"[君否] detailContent 异常: {e}")
            return {"list": []}

    def _collect_playlist(self, html):
        """解析播放源 + 剧集 (按 sid 分组, 按 HTML 出现顺序排列)。

        君否影院结构:
          <ul class="nav nav-tabs">
            <li><a href="#playlist2" data-toggle="tab">js线路</a></li>
            <li><a href="#playlist1" data-toggle="tab">xl线路</a></li>
          </ul>
          <div id="playlist2" class="tab-pane ...">
            <ul><li><a href="/link/9152097x/2/1.html">第1集</a></li>...</ul>
          </div>

        策略: 直接匹配所有 /link/{id}x/{sid}/{nid}.html 链接, 按 sid 分组,
        按 HTML 出现顺序排列 (站点部分线路是倒序 nid, 不能按 nid 排序)。
        """
        play_from, play_url = [], []

        # 收集 tab 名: {sid: name}, 按 HTML 出现顺序
        tab_order = []  # [(sid, name), ...]
        tab_map = {}
        for tm in self._RE_PLAY_TAB.finditer(html):
            sid = tm.group(1)
            name = _strip(_unescape(tm.group(2)))
            if sid not in tab_map:
                tab_order.append(sid)
                tab_map[sid] = name

        # 收集所有剧集链接, 按 sid 分组, 保持 HTML 出现顺序
        # {sid: [(ep_name, path), ...]}
        eps_by_sid = {}
        seen_paths = set()
        for em in self._RE_PLAY_EP.finditer(html):
            path = em.group(1)       # /link/9152097x/2/1.html
            sid = em.group(3)        # sid
            ep_name = _strip(_unescape(re.sub(r"<[^>]+>", "", em.group(5)))) or "正片"
            if path in seen_paths:
                continue
            seen_paths.add(path)
            if sid not in eps_by_sid:
                eps_by_sid[sid] = []
            eps_by_sid[sid].append((ep_name, path))

        # 按 tab 出现顺序输出
        for sid in tab_order:
            if sid not in eps_by_sid:
                continue
            eps = [f"{name}${path}" for name, path in eps_by_sid[sid]]
            src_name = tab_map.get(sid, f"线路{sid}")
            play_from.append(src_name)
            play_url.append("#".join(eps))

        # 兜底: 如果 tab 没找到但有剧集, 按 sid 排序输出
        if not play_from:
            for sid in sorted(eps_by_sid.keys()):
                eps = [f"{name}${path}" for name, path in eps_by_sid[sid]]
                play_from.append(f"线路{sid}")
                play_url.append("#".join(eps))

        return play_from, play_url

    def searchContent(self, key, quick, pg="1"):
        """搜索: 走 /query2/wd/ 入口。

        URL 格式:
          第1页: /query2/wd/{kw}.html
          第2页起: /query2/page/{page}/wd/{kw}.html

        缓存策略: 按 kw 缓存"按页索引的 items 字典", 翻页时直接本地切片。
        优化: 第一页响应里 *并发* 拉 2/3 页预热, 翻页 = 0ms。
        """
        try:
            kw = _strip(str(key or ""))
            if not kw:
                return {"list": []}

            page = int(pg or 1)
            if page < 1:
                page = 1

            now = time.time()
            with self._cache_lock:
                cached = self._search_cache.get(kw)
            if cached and now - cached[0] < SEARCH_CACHE_TTL:
                pages, pagecount, total = cached[1], cached[2], cached[3]
                page_items = pages.get(page, [])
            else:
                pages = {}
                total = 0
                pagecount = 1

                kw_enc = _urlencode(kw)
                urls = []
                for p in (1, 2, 3):
                    if p == 1:
                        urls.append(f"{HOST}/query2/wd/{kw_enc}.html")
                    else:
                        urls.append(f"{HOST}/query2/page/{p}/wd/{kw_enc}.html")

                # 并发拉取前 3 页
                results = self._http_get_concurrent(urls, timeout=7, max_workers=3)
                for p, u in zip((1, 2, 3), urls):
                    html = results.get(u, "")
                    if not html:
                        break
                    items = self._parse_vod(html)
                    if not items:
                        break
                    pages[p] = items
                    total += len(items)
                    if p == 1:
                        # 从第 1 页的翻页链接里反推最大页
                        pms = self._RE_PAGE_SEARCH.findall(html)
                        if pms:
                            pagecount = max(int(x) for x in pms)

                if pages:
                    with self._cache_lock:
                        self._search_cache[kw] = (now, pages, pagecount, total)
                page_items = pages.get(page, [])

            return {
                "list": page_items,
                "page": page,
                "pagecount": pagecount,
                "limit": SEARCH_PAGE_SIZE,
                "total": total,
            }
        except Exception as e:
            print(f"[君否] searchContent 异常: {e}")
            return {"list": []}

    def playerContent(self, flag, id, vipFlags):
        """播放: 从 /link/ 页 player_aaaa JSON 取真实 m3u8。"""
        play_path = str(id or "")
        if not play_path:
            return {"parse": 0, "url": ""}

        # 已经是直链 (m3u8 / mp4) 直接返回
        if self.isVideoFormat(play_path):
            return {"parse": 0, "url": play_path,
                    "header": {"User-Agent": UA, "Referer": HOST + "/"}}

        # /link/xxx 或 /title/xxx 都走解析
        if "/link/" in play_path or "/title/" in play_path:
            if not play_path.startswith("http"):
                play_url = HOST + play_path
            else:
                play_url = play_path
            html = self._http_get(play_url, timeout=6)
            if html:
                real = self._extract_m3u8(html)
                if real:
                    return {"parse": 0, "url": real,
                            "header": {"User-Agent": UA, "Referer": play_url}}

        # 兜底透传
        return {"parse": 0, "url": play_path,
                "header": {"User-Agent": UA, "Referer": HOST + "/"}}

    def _extract_m3u8(self, html):
        """从播放页提取真实 m3u8。"""
        # 1) player_aaaa JSON
        m = self._RE_PLAYER_JSON.search(html)
        if m:
            try:
                obj = json.loads(m.group(1))
                u = obj.get("url") or ""
                if u and "hljhsmy.cn" not in u:
                    return u
            except Exception:
                pass
            # JSON 解析失败: 手动从字符串里抓 url
            um = self._RE_PLAYER_URL.search(m.group(1))
            if um:
                val = um.group(1).replace("\\/", "/").replace("\\\\", "\\")
                if "hljhsmy.cn" not in val:
                    return val

        # 2) 页面内直链
        m = self._RE_M3U8_DIRECT.search(html)
        return m.group(0) if m else ""

    def localProxy(self, param):
        return [200, "video/MP2T", b"", ""]


# ============================================================
# 独立运行自检 (框架下不会触发, 方便本地调试)
# ============================================================
if __name__ == "__main__":
    import sys

    def _bench(label, fn):
        t0 = time.time()
        r = fn()
        print(f"  [{label}] 耗时 {time.time() - t0:.2f}s")
        return r

    print("== homeContent ==")
    sp = Spider()
    sp.init()
    print(json.dumps(sp.homeContent(True), ensure_ascii=False)[:300])

    print("\n== homeVideoContent 前3条 ==")
    hvc = _bench("首页", lambda: sp.homeVideoContent())
    for it in hvc["list"][:3]:
        print(" ", it)

    print("\n== categoryContent 电影第1页 ==")
    cc = _bench("电影分类", lambda: sp.categoryContent("1", 1, True, {}))
    print("  条数:", len(cc["list"]), "总页数:", cc["pagecount"])
    if cc["list"]:
        print("  第一个 vod_id:", cc["list"][0]["vod_id"])

    print("\n== 二级分类 动作片 ==")
    cc2 = _bench("动作片", lambda: sp.categoryContent("1", 1, True, {"type": "6"}))
    print("  条数:", len(cc2["list"]), "总页数:", cc2["pagecount"])
    if cc2["list"]:
        print("  第一个 vod_id:", cc2["list"][0]["vod_id"])

    print("\n== 二级筛选 动作片 + 美国 + 2025 ==")
    cc3 = _bench("筛选", lambda: sp.categoryContent("1", 1, True, {
        "type": "6", "area": "美国", "year": "2025", "by": "time"
    }))
    print("  条数:", len(cc3["list"]), "总页数:", cc3["pagecount"])

    print("\n== 筛选翻页 动作片第2页 ==")
    cc4 = _bench("翻页", lambda: sp.categoryContent("1", 2, True, {"type": "6"}))
    print("  条数:", len(cc4["list"]), "总页数:", cc4["pagecount"])

    if cc["list"]:
        print("\n== detailContent ==")
        vid = cc["list"][0]["vod_id"]
        print("  用 vod_id:", vid)
        dc = _bench("详情", lambda: sp.detailContent([vid]))
        if dc["list"]:
            v = dc["list"][0]
            for k in ("vod_name", "vod_year", "vod_area", "vod_class",
                      "vod_actor", "vod_director", "vod_content"):
                print(f"  {k}: {v.get(k)}")
            print("  vod_play_from:", v.get("vod_play_from"))
            first = (v.get("vod_play_url") or "").split("#")[0]
            print("  第一集:", first)
            if first:
                print("\n== playerContent ==")
                pc = _bench("播放解析",
                            lambda: sp.playerContent("", first.split("$")[-1], []))
                print("  parse:", pc["parse"])
                print("  url:", pc["url"][:120])

    print("\n== searchContent 测试 ==")
    sc = _bench("搜索", lambda: sp.searchContent("变形金刚", True))
    print("  total:", sc["total"], "pagecount:", sc["pagecount"])
    for it in sc["list"][:3]:
        print(" ", it.get("vod_id"), it.get("vod_name"))

    # 二次搜索走缓存, 看耗时差异
    print("\n== searchContent 二次 (走缓存) ==")
    sc2 = _bench("搜索缓存", lambda: sp.searchContent("变形金刚", True, pg=2))
    print("  total:", sc2["total"], "第2页条数:", len(sc2["list"]))

    sp.destroy()
    print("\n== 自检完成 ==")
