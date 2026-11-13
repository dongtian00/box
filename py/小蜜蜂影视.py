# -*- coding: utf-8 -*-
"""
小蜜蜂影院 (xmfyy.vip) Python Spider
兼容 FongMi/TV (T3) 与 WebHomeTV / PeekPro (T4)
基于苹果CMS conch 模板 HTML 解析
"""
import sys
import re
import json
import time
import base64

sys.path.append('..')

try:
    from base.spider import Spider
except ImportError:
    import requests as rq

    class Spider:
        def fetch(self, url, headers=None, **kw):
            kw.pop('timeout', None)
            r = rq.get(url, headers=headers, timeout=15, **kw)
            r.encoding = 'utf-8'
            return r


class Spider(Spider):

    # ===== 多域名探测 =====
    DOMAINS = [
        "https://www.xmfyy.vip",
        "https://www.xmfyy.cc",
    ]

    UA = (
        'Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36'
    )

    # ===== 解析接口映射（来自 playerconfig.js）=====
    # from 值 -> 解析器 URL（playUrl）
    PARSE_MAP = {
        'mgtv':       'https://svip.qlplayer.cyou/?url=',
        'bilibili':   'https://svip.qlplayer.cyou/?url=',
        'qiyi':       'https://svip.qlplayer.cyou/?url=',
        'qq':         'https://svip.qlplayer.cyou/?url=',
        'youku':      'https://svip.qlplayer.cyou/?url=',
        'sohu':       'https://www.xmfyy.com/static/player/artplayer.html?url=',
        'hnm3u8':     'https://www.hnjiexi.com/m3u8/?url=',
        'jsm3u8':     'https://svip.ffzyplay.com/?url=',
        'rym3u8':     'https://ruyiplayer.com?url=',
        'liangzi':    'https://jisuzyjx.com/play/?url=',
        'dytt':       'https://vip.dyttzyplay.com/?url=',
        'dyttm3u8':   'https://vip.dyttzyplay.com/?url=',
    }

    # ===== 父分类（只放顶层，子分类写在 filters 里）=====
    classes = [
        {'type_name': '连续剧', 'type_id': '2'},
        {'type_name': '电影', 'type_id': '1'},
        {'type_name': '动漫', 'type_id': '4'},
        {'type_name': '综艺', 'type_id': '3'},
    ]

    # ===== 子分类筛选器 =====
    filters = {
        # 连续剧
        '2': [
            {'key': 'type', 'name': '类型', 'value': [
                {'n': '全部', 'v': ''},
                {'n': '国产剧', 'v': '13'},
                {'n': '港台剧', 'v': '14'},
                {'n': '日韩剧', 'v': '15'},
                {'n': '欧美剧', 'v': '16'},
                {'n': '纪录片', 'v': '38'},
                {'n': '其他剧', 'v': '37'},
            ]},
            {'key': 'by', 'name': '排序', 'value': [
                {'n': '最新', 'v': 'time'},
                {'n': '最热', 'v': 'hits'},
                {'n': '评分', 'v': 'score'},
            ]},
            {'key': 'area', 'name': '地区', 'value': [
                {'n': '全部', 'v': ''},
                {'n': '内地', 'v': '内地'},
                {'n': '香港', 'v': '香港'},
                {'n': '韩国', 'v': '韩国'},
                {'n': '日本', 'v': '日本'},
                {'n': '美国', 'v': '美国'},
                {'n': '英国', 'v': '英国'},
            ]},
            {'key': 'year', 'name': '年份', 'value': [
                {'n': '全部', 'v': ''},
                {'n': '2026', 'v': '2026'},
                {'n': '2025', 'v': '2025'},
                {'n': '2024', 'v': '2024'},
                {'n': '2023', 'v': '2023'},
            ]},
        ],
        # 电影
        '1': [
            {'key': 'type', 'name': '类型', 'value': [
                {'n': '全部', 'v': ''},
                {'n': '动作片', 'v': '6'},
                {'n': '喜剧片', 'v': '7'},
                {'n': '爱情片', 'v': '8'},
                {'n': '科幻片', 'v': '9'},
                {'n': '恐怖片', 'v': '10'},
                {'n': '剧情片', 'v': '11'},
                {'n': '战争片', 'v': '12'},
                {'n': '悬疑片', 'v': '21'},
            ]},
            {'key': 'by', 'name': '排序', 'value': [
                {'n': '最新', 'v': 'time'},
                {'n': '最热', 'v': 'hits'},
                {'n': '评分', 'v': 'score'},
            ]},
            {'key': 'area', 'name': '地区', 'value': [
                {'n': '全部', 'v': ''},
                {'n': '大陆', 'v': '大陆'},
                {'n': '香港', 'v': '香港'},
                {'n': '美国', 'v': '美国'},
                {'n': '韩国', 'v': '韩国'},
                {'n': '日本', 'v': '日本'},
                {'n': '法国', 'v': '法国'},
                {'n': '英国', 'v': '英国'},
            ]},
            {'key': 'year', 'name': '年份', 'value': [
                {'n': '全部', 'v': ''},
                {'n': '2026', 'v': '2026'},
                {'n': '2025', 'v': '2025'},
                {'n': '2024', 'v': '2024'},
                {'n': '2023', 'v': '2023'},
            ]},
        ],
        # 动漫
        '4': [
            {'key': 'type', 'name': '类型', 'value': [
                {'n': '全部', 'v': ''},
                {'n': '动漫', 'v': '28'},
                {'n': '番剧', 'v': '39'},
                {'n': '动画片', 'v': '19'},
            ]},
            {'key': 'by', 'name': '排序', 'value': [
                {'n': '最新', 'v': 'time'},
                {'n': '最热', 'v': 'hits'},
                {'n': '评分', 'v': 'score'},
            ]},
        ],
        # 综艺（无子分类，只放排序）
        '3': [
            {'key': 'by', 'name': '排序', 'value': [
                {'n': '最新', 'v': 'time'},
                {'n': '最热', 'v': 'hits'},
                {'n': '评分', 'v': 'score'},
            ]},
        ],
    }

    # 父分类选"全部"时无直接内容，用第一个子分类兜底
    DEFAULT_SUBTYPE = {
        '2': '13',
        '1': '6',
        '4': '28',
    }

    # 需要跳过的搜索引擎线路关键词
    SKIP_KEYWORDS = (
        "搜索", "百度", "搜狗", "神马", "360",
        "baidu", "google", "sogou",
    )

    def init(self, extend=""):
        if isinstance(extend, list):
            self.extend = ''
        else:
            self.extend = extend or ''
        self.host = self.DOMAINS[0]
        self.header = {
            'User-Agent': self.UA,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Referer': self.host + '/',
            'Connection': 'keep-alive',
        }
        self._home_cache = []
        self._home_cache_time = 0
        self._probe_domain()

    # ===== 域名探测 =====
    def _probe_domain(self):
        for domain in self.DOMAINS:
            try:
                text = self._txt(domain, timeout=10)
                if text and len(text) > 500:
                    self.host = domain
                    self.header['Referer'] = self.host + '/'
                    return
            except Exception:
                continue

    # ===== 网络请求封装（带超时和异常兜底）=====
    def _txt(self, url, referer=None, timeout=30):
        headers = dict(self.header)
        if referer:
            headers['Referer'] = referer
        try:
            rsp = self.fetch(url, headers=headers, timeout=timeout)
            try:
                rsp.encoding = 'utf-8'
            except Exception:
                pass
            return rsp.text
        except Exception:
            return ''

    # ===== URL 拼接 =====
    def _url(self, path):
        if not path:
            return ''
        if path.startswith('http'):
            return path
        if path.startswith('//'):
            return 'https:' + path
        if path.startswith('/'):
            return self.host + path
        return self.host + '/' + path

    # ===== 正则匹配辅助 =====
    @staticmethod
    def _match(pattern, text, flags=0):
        m = re.search(pattern, text, flags)
        return m.group(1).strip() if m else ''

    @staticmethod
    def _strip_tags(html_text):
        if not html_text:
            return ''
        return re.sub(r'<[^>]+>', '', html_text).strip()

    # ================================================================
    #  首页
    # ================================================================
    def homeContent(self, filter):
        return {
            'class': self.classes,
            'filters': self.filters,
        }

    def homeVideoContent(self):
        now = int(time.time())
        if self._home_cache and now - self._home_cache_time < 300:
            return {'list': self._home_cache[:72]}

        tids = ['1', '2', '3', '4']
        videos = []
        seen = set()

        for tid in tids:
            url = f'{self.host}/index.php/vod/type/id/{tid}.html'
            html = self._txt(url, timeout=12)
            cards = self._parse_video_list(html)
            for v in cards:
                vid = v.get('vod_id')
                if vid and vid not in seen:
                    seen.add(vid)
                    videos.append(v)
                if len(videos) >= 72:
                    break
            if len(videos) >= 72:
                break

        self._home_cache = videos[:72]
        self._home_cache_time = now
        return {'list': self._home_cache}

    # ================================================================
    #  分类列表
    # ================================================================
    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg or 1)

            # 解析 extend 参数
            ext = {}
            if extend:
                if isinstance(extend, dict):
                    ext = extend
                elif isinstance(extend, str):
                    try:
                        ext = json.loads(extend)
                    except Exception:
                        ext = {}

            sub_type = ext.get('type', '')
            sort_by = ext.get('by', '')
            area = ext.get('area', '')
            year = ext.get('year', '')

            # 确定查询分类
            query_type = sub_type if sub_type else tid

            # 父分类兜底
            if not sub_type and query_type in self.DEFAULT_SUBTYPE:
                query_type = self.DEFAULT_SUBTYPE[query_type]

            # 构建 HTML 分类页 URL
            # conch 模板: 纯分类浏览用 type 路由，带筛选排序用 show 路由
            if sort_by or area or year:
                url = f'{self.host}/index.php/vod/show/id/{query_type}'
                if sort_by:
                    url += f'/by/{sort_by}'
                if area:
                    url += f'/area/{area}'
                if year:
                    url += f'/year/{year}'
                url += f'/page/{pg}.html'
            else:
                url = f'{self.host}/index.php/vod/type/id/{query_type}/page/{pg}.html'

            html = self._txt(url, timeout=15)
            videos = self._parse_video_list(html)

            # 解析分页
            pagecount = self._parse_pagecount(html, pg)

            return {
                'list': videos,
                'page': pg,
                'pagecount': pagecount,
                'limit': 20,
                'total': pagecount * 20,
            }
        except Exception:
            return {
                'page': int(pg or 1),
                'pagecount': 1,
                'limit': 20,
                'total': 0,
                'list': [],
            }

    def _parse_pagecount(self, html, pg):
        """从 HTML 中解析总页数"""
        # 尝试匹配最大页码链接
        page_nums = re.findall(r'/page/(\d+)\.html', html)
        if page_nums:
            return max(int(p) for p in page_nums)

        # 有内容但找不到分页，至少返回当前页
        return pg

    # ================================================================
    #  视频卡片列表解析
    # ================================================================
    def _parse_video_list(self, html):
        """从分类页/首页 HTML 解析视频卡片列表"""
        videos = []
        if not html:
            return videos

        # conch 模板: 优先从 hl-list-wrap（主列表容器）中提取
        # 避免拾取侧边栏/排行榜等非主列表内容
        main_sections = re.findall(
            r'<div\s+class="hl-list-wrap[^"]*">\s*<ul\s+class="hl-vod-list[^"]*">(.*?)</ul>',
            html, re.S
        )
        if main_sections:
            seen_ids = set()
            for section in main_sections:
                items = re.findall(
                    r'<li\s+class="hl-list-item[^"]*">(.*?)</li>',
                    section, re.S
                )
                for item in items:
                    video = self._parse_video_card(item)
                    if video and video['vod_id'] not in seen_ids:
                        seen_ids.add(video['vod_id'])
                        videos.append(video)
            # 如果从 hl-list-wrap 提取到内容，直接返回
            if videos:
                return videos

        # fallback: 全局提取（首页等非标准布局）
        items = re.findall(
            r'<li\s+class="hl-list-item[^"]*">(.*?)</li>',
            html, re.S
        )
        seen_ids = set()
        for item in items:
            video = self._parse_video_card(item)
            if video and video['vod_id'] not in seen_ids:
                seen_ids.add(video['vod_id'])
                videos.append(video)
        return videos

    def _parse_video_card(self, html):
        """解析单个视频卡片"""
        # 1. 提取链接和 vod_id
        href_match = re.search(
            r'href="(/index\.php/vod/detail/id/(\d+)\.html)"',
            html
        )
        if not href_match:
            return None
        vod_id = href_match.group(2)

        # 2. 封面：优先 data-original
        pic = ''
        pic_match = re.search(r'data-original="([^"]+)"', html)
        if pic_match:
            pic = pic_match.group(1)
        if not pic:
            bg_match = re.search(
                r'background-image:\s*url\([\'"]?([^\'"()]+)',
                html
            )
            if bg_match:
                pic = bg_match.group(1)
        # 补全协议
        if pic and pic.startswith('//'):
            pic = 'https:' + pic

        # 3. 标题
        title = ''
        title_match = re.search(
            r'class="hl-item-title[^"]*"[^>]*>[^<]*<a[^>]*title="([^"]+)"',
            html
        )
        if title_match:
            title = title_match.group(1).strip()
        if not title:
            title_match2 = re.search(r'title="([^"]+)"', html)
            if title_match2:
                title = title_match2.group(1).strip()

        # 4. 备注（集数信息）
        remarks = ''
        remarks_match = re.search(
            r'class="hl-pic-text[^"]*"[^>]*>.*?<span[^>]*class="remarks"[^>]*>([^<]+)',
            html, re.S
        )
        if remarks_match:
            remarks = remarks_match.group(1).strip()
        if not remarks:
            remarks_match2 = re.search(
                r'class="remarks"[^>]*>([^<]+)',
                html
            )
            if remarks_match2:
                remarks = remarks_match2.group(1).strip()

        return {
            'vod_id': vod_id,
            'vod_name': title or vod_id,
            'vod_pic': pic,
            'vod_remarks': remarks,
        }

    # ================================================================
    #  详情页
    # ================================================================
    def detailContent(self, ids):
        # 兼容 list 和 str
        if isinstance(ids, str):
            ids = [ids]
        vod_id = str(ids[0]) if ids else ''

        url = f'{self.host}/index.php/vod/detail/id/{vod_id}.html'
        html = self._txt(url, timeout=15)
        if not html:
            return {'list': []}

        vod = self._parse_detail(html, vod_id)
        return {'list': [vod] if vod else []}

    def _parse_detail(self, html, vod_id):
        """解析详情页"""
        # 1. 标题
        title = self._match(
            r'<h2\s+class="hl-dc-title[^"]*"[^>]*>([^<]+)',
            html
        )
        if not title:
            title = self._match(r'<title>([^<|-]+)', html)
            if title:
                title = title.strip()

        # 2. 封面
        pic = ''
        pic_match = re.search(
            r'class="hl-dc-pic".*?data-original="([^"]+)"',
            html, re.S
        )
        if pic_match:
            pic = pic_match.group(1)
        if not pic:
            pic_match2 = re.search(
                r'class="hl-item-thumb[^"]*"[^>]*data-original="([^"]+)"',
                html
            )
            if pic_match2:
                pic = pic_match2.group(1)
        if pic and pic.startswith('//'):
            pic = 'https:' + pic

        # 3. 信息列表 - 解析 li 中的 em 标签和内容
        info_items = re.findall(
            r'<em\s+class="hl-text-muted">([^<：:]+)[：:]?</em>(.*?)</li>',
            html, re.S
        )
        actor, director, area, year, type_name, remarks, content = '', '', '', '', '', '', ''

        for label, content_html in info_items:
            label = label.strip()
            text = self._strip_tags(content_html).strip()
            if '主演' in label:
                actor = text
            elif '导演' in label:
                director = text
            elif '地区' in label:
                area = text
            elif '年份' in label:
                year = text
            elif '类型' in label:
                type_name = text
            elif '状态' in label:
                remarks = text
            elif '简介' in label:
                content = text

        # 4. 剧情简介 fallback
        if not content:
            content = self._match(
                r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']+)',
                html
            )

        # 5. 播放列表
        play_from, play_url = self._parse_playlist(html, vod_id)

        return {
            'vod_id': vod_id,
            'vod_name': title or vod_id,
            'vod_pic': pic,
            'type_name': type_name,
            'vod_year': year,
            'vod_area': area,
            'vod_remarks': remarks,
            'vod_actor': actor,
            'vod_director': director,
            'vod_content': content[:500] if content else '',
            'vod_play_from': '$$$'.join(play_from),
            'vod_play_url': '$$$'.join(play_url),
        }

    def _parse_playlist(self, html, vod_id):
        """解析播放列表（多线路 + 集数）"""
        play_from = []
        play_url = []

        # 1. 找线路按钮 (conch: hl-plays-from > a.hl-tabs-btn[alt])
        source_items = re.findall(
            r'<a\s+class="hl-tabs-btn[^"]*"[^>]*alt="([^"]+)"',
            html
        )
        source_names = [s.strip() for s in source_items]

        if not source_names:
            # 没有线路选择器，直接找播放链接
            play_links = re.findall(
                r'href="(/index\.php/vod/play/id/\d+/sid/\d+/nid/\d+\.html)"',
                html
            )
            if play_links:
                episodes = []
                seen_eps = set()
                for link in play_links:
                    if link not in seen_eps:
                        seen_eps.add(link)
                        nid_match = re.search(r'/nid/(\d+)\.html', link)
                        ep_name = f'第{nid_match.group(1)}集' if nid_match else '播放'
                        episodes.append(f'{ep_name}${self._url(link)}')
                if episodes:
                    play_from.append('默认线路')
                    play_url.append('#'.join(episodes))
            return play_from, play_url

        # 2. 提取各线路的集数块 (conch: ul.hl-plays-list)
        play_items_raw = re.split(r'class="hl-plays-list', html)
        play_items = play_items_raw[1:] if len(play_items_raw) > 1 else []

        # 3. 逐线路匹配集数
        for idx, source_name in enumerate(source_names):
            # 跳过搜索引擎线路
            if any(kw in source_name.lower() for kw in self.SKIP_KEYWORDS):
                continue

            episodes = []
            if idx < len(play_items):
                item_html = play_items[idx]
                ep_links = re.findall(
                    r'<a\s+href="(/index\.php/vod/play/id/\d+/sid/(\d+)/nid/(\d+)\.html)"[^>]*>([^<]*)</a>',
                    item_html
                )
                for link, sid, nid, ep_name in ep_links:
                    ep_name = self._strip_tags(ep_name).strip()
                    if not ep_name:
                        ep_name = f'第{nid}集'
                    elif not ep_name.startswith('第') and ep_name.isdigit():
                        ep_name = f'第{ep_name}集'
                    episodes.append(f'{ep_name}${self._url(link)}')

            if episodes:
                play_from.append(source_name)
                play_url.append('#'.join(episodes))

        return play_from, play_url

    # ================================================================
    #  搜索
    # ================================================================
    def searchContent(self, key, quick, pg="1"):
        try:
            pg = int(pg or 1)
            # 搜索 URL: /index.php/vod/search/page/{pg}/wd/{keyword}.html
            from urllib.parse import quote
            url = f'{self.host}/index.php/vod/search/page/{pg}/wd/{quote(key, safe="")}.html'
            html = self._txt(url, timeout=15)
            videos = self._parse_video_list(html)
            return {'list': videos}
        except Exception:
            return {'list': []}

    # ================================================================
    #  播放解析
    # ================================================================
    def playerContent(self, flag, id, vipFlags):
        if not id:
            return {'parse': 1, 'playUrl': '', 'url': ''}

        url = id if str(id).startswith('http') else self._url(id)

        # 1. 直链检测（普通线路的 m3u8/mp4 直链直接播放）
        if self._is_direct_media(url):
            return {
                'parse': 0,
                'playUrl': '',
                'url': url,
                'header': {
                    'User-Agent': self.header['User-Agent'],
                    'Referer': self.host + '/',
                },
                'format': 'application/x-mpegURL' if '.m3u8' in url.lower() else '',
                'contentType': 'application/x-mpegURL' if '.m3u8' in url.lower() else '',
            }

        # 2. 官源解析（优先级最高，在页面解析之前）
        #    不看线路名，只看 URL 是否指向官方播放页
        if self._is_official_source(url):
            resolved = self._resolve_official_to_media(url)
            if resolved:
                return {
                    'parse': 0,
                    'playUrl': '',
                    'url': resolved,
                    'header': {
                        'User-Agent': self.header['User-Agent'],
                        'Referer': 'https://bfq.txnp.cn/',
                    },
                    'format': 'application/x-mpegURL' if '.m3u8' in resolved.lower() else '',
                    'contentType': 'application/x-mpegURL' if '.m3u8' in resolved.lower() else '',
                }

        # 3. 播放页解析（player_aaaa → iframe → 全局 m3u8 匹配）
        html = self._txt(url, referer=self.host + '/', timeout=30)
        if not html:
            return {'parse': 1, 'playUrl': '', 'url': url}

        real = ''

        # 3a. player_aaaa JSON
        m = re.search(
            r'var\s+player_[a-zA-Z0-9_]+\s*=\s*(\{.*?\})\s*</script>',
            html, re.S
        )
        if not m:
            m = re.search(
                r'var\s+player_[a-zA-Z0-9_]+\s*=\s*(\{.*?\})',
                html, re.S
            )
        if m:
            try:
                raw = m.group(1)
                data = json.loads(raw)
                real = data.get('url', '') or ''
                encrypt = data.get('encrypt', 0)
                if encrypt in [1, 2] and real:
                    try:
                        real = base64.b64decode(real).decode('utf-8')
                    except Exception:
                        pass
                # 如果 url 不是真实媒体地址（如站点域名），清空
                if real and not real.startswith('http') and not self._is_direct_media(real):
                    real = ''
            except Exception:
                real = self._match(r'"url"\s*:\s*"([^"]+)"', m.group(1))
                if real and not real.startswith('http'):
                    real = ''

        # 3b. iframe 嵌套
        if not real:
            iframe = re.search(
                r'<iframe[^>]+src=["\']([^"\']+)["\']',
                html, re.S
            )
            if iframe:
                iframe_url = self._url(iframe.group(1))
                if self._is_direct_media(iframe_url):
                    real = iframe_url
                else:
                    iframe_html = self._txt(iframe_url, referer=url, timeout=30)
                    if iframe_html:
                        real = self._match(
                            r'"url"\s*:\s*"(https?://[^"]+)"',
                            iframe_html
                        )

        # 3c. 全局匹配 m3u8/mp4
        if not real:
            m2 = re.search(
                r'["\'](https?://[^"\']+\.(?:m3u8|mp4)[^"\']*)["\']',
                html, re.I
            )
            if m2:
                real = m2.group(1)

        if real:
            real = real.replace('\\/', '/')
            is_m3u8 = '.m3u8' in real.lower()

            # 直链媒体直接播放
            if self._is_direct_media(real):
                if is_m3u8:
                    real = self._resolve_m3u8_child(real, referer=url)
                return {
                    'parse': 0,
                    'playUrl': '',
                    'url': real,
                    'header': {
                        'User-Agent': self.header['User-Agent'],
                        'Referer': url,
                    },
                    'format': 'application/x-mpegURL' if is_m3u8 else '',
                    'contentType': 'application/x-mpegURL' if is_m3u8 else '',
                }

            # player_aaaa 中拿到的 URL 是官源但第一次没命中（伪官源）
            if self._is_official_source(real):
                resolved = self._resolve_official_to_media(real)
                if resolved:
                    return {
                        'parse': 0,
                        'playUrl': '',
                        'url': resolved,
                        'header': {
                            'User-Agent': self.header['User-Agent'],
                            'Referer': 'https://bfq.txnp.cn/',
                        },
                        'format': 'application/x-mpegURL' if '.m3u8' in resolved.lower() else '',
                        'contentType': 'application/x-mpegURL' if '.m3u8' in resolved.lower() else '',
                    }

        # 4. 兜底交给壳子嗅探
        return {'parse': 1, 'playUrl': '', 'url': url}

    # ================================================================
    #  辅助方法
    # ================================================================
    def _is_direct_media(self, url):
        url = (url or '').lower()
        return '.m3u8' in url or '.mp4' in url or '.flv' in url or '.mkv' in url

    def _is_official_source(self, url):
        url = (url or '').lower()
        keys = (
            'mgtv.com', 'youku.com', 'iqiyi.com', 'qiyi.com',
            'v.qq.com', 'qq.com', 'bilibili.com', 'le.com',
            'sohu.com', 'pptv.com', '1905.com',
        )
        return any(k in url for k in keys) and not self._is_direct_media(url)

    def _aes_cbc_decrypt_text(self, cipher_text):
        """bfq.txnp.cn 的 AES-CBC 解密
        密文结构: base64(encrypted) + key(16字节) + iv(16字节)
        key = cipher_text[-32:-16], iv = cipher_text[-16:]
        """
        try:
            from Crypto.Cipher import AES
            key = cipher_text[-32:-16].encode('utf-8')
            iv = cipher_text[-16:].encode('utf-8')
            data = base64.b64decode(cipher_text[:-32])
            raw = AES.new(key, AES.MODE_CBC, iv).decrypt(data)
            pad = raw[-1] if raw else 0
            if 0 < pad <= 16:
                raw = raw[:-pad]
            return raw.decode('utf-8', 'ignore')
        except Exception:
            return ''

    def _decode_bfq_result(self, result):
        """解密 bfq.txnp.cn 的 result 变量为 JSON dict"""
        text = self._aes_cbc_decrypt_text(result or '')
        if not text:
            return {}
        try:
            return json.loads(text)
        except Exception:
            return {}

    def _resolve_official_to_media(self, src_url):
        """通过 bfq.txnp.cn 解析官源 URL 为真实媒体直链
        流程: player?url=<src> → 取 let result = "..." → AES-CBC 解密 → video_info.video.url
        """
        if not src_url or not self._is_official_source(src_url):
            return ''
        try:
            from urllib.parse import quote
            page_url = 'https://bfq.txnp.cn/player?url=' + quote(src_url, safe='')
            referer = 'https://bfq.txnp.cn/excessive?url=' + quote(src_url, safe='')
            html = self._txt(page_url, referer=referer, timeout=20)
            if not html:
                return ''
            result = self._match(r'let\s+result\s*=\s*"([^"]+)"', html, re.S)
            if not result:
                return ''
            data = self._decode_bfq_result(result)
            video = ((data.get('video_info') or {}).get('video') or {})
            media = (video.get('url') or '').replace('\\/', '/')
            if media and self._is_direct_media(media):
                # IP + 非标端口的 HTTPS 会出现 SSL 证书不匹配
                # （如 https://219.154.71.13:10000/...），播放器握手失败
                # 降级为 HTTP 即可正常访问
                if re.match(r'https://\d+\.\d+\.\d+\.\d+:\d+', media):
                    media = media.replace('https://', 'http://', 1)
                if '.m3u8' in media.lower():
                    media = self._resolve_m3u8_child(media, referer=page_url)
                return media
        except Exception:
            pass
        return ''

    def _resolve_m3u8_child(self, m3u8_url, referer=''):
        """Exo 对部分主 m3u8 的相对跳转兼容差，优先解析到子 m3u8"""
        try:
            from urllib.parse import urljoin
            text = self._txt(m3u8_url, referer=referer or self.host + '/', timeout=20)
            if not text or '#EXTM3U' not in text:
                return m3u8_url
            lines = [x.strip() for x in text.splitlines() if x.strip()]
            for i, line in enumerate(lines):
                if line.startswith('#EXT-X-STREAM-INF'):
                    for nxt in lines[i + 1:]:
                        if nxt and not nxt.startswith('#'):
                            return urljoin(m3u8_url, nxt)
        except Exception:
            pass
        return m3u8_url

    # ================================================================
    #  本地代理（可选）
    # ================================================================
    def localProxy(self, param):
        return [200, 'video/MP2T', b'', '']

    # ================================================================
    #  清理
    # ================================================================
    def destroy(self):
        pass

    def close(self):
        self.destroy()
