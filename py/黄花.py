# -*- coding: utf-8 -*-
"""
TVBox Python 爬虫 - 播播影院 (malagbeer.com)
支持: 分类栏 / 子分类筛选 / 封面图海报 / 搜索 / 播放

反爬说明:
  该网站在服务端检测 User-Agent, 拦截以下特征:
  - 精确匹配 "Mozilla/5.0" (不带后续括号信息)
  - 含 "python-requests", "Python-urllib", "Python/", "Go-http-client",
    "Apache-HttpClient" 等编程库标识
  规避方法: 使用不含上述特征的 UA 即可正常请求, 无需安装额外库
"""

import sys
import re
import json

sys.path.append('..')

try:
    import requests as _requests
except ImportError:
    _requests = None

from base.spider import Spider


class Spider(Spider):

    HOST = 'https://www.malagbeer.com'

    # 关键: 该网站 WAF 检测 UA 中的 "Win64; x64" 子串并拒绝连接,
    # 以及精确匹配 "Mozilla/5.0"(无后续括号) 和编程库标识(python-requests/Python等)。
    # 解决: 用 Mac UA 避开 "Win64; x64", 无需安装任何额外库
    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                      'AppleWebKit/537.36 (KHTML, like Gecko) '
                      'Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'Referer': 'https://www.malagbeer.com/',
    }

    # ==================== 分类配置 ====================

    CATEGORIES = [
        {'type_id': '1',  'type_name': '电影'},
        {'type_id': '2',  'type_name': '电视剧'},
        {'type_id': '3',  'type_name': '综艺'},
        {'type_id': '4',  'type_name': '动漫'},
        {'type_id': '30', 'type_name': '短剧'},
        {'type_id': '55', 'type_name': '预告'},
    ]

    # 地区筛选选项 (各分类通用)
    AREA_FILTER = {'key': 'area', 'name': '地区', 'value': [
        {'n': '全部', 'v': ''},
        {'n': '大陆', 'v': '大陆'},
        {'n': '香港', 'v': '香港'},
        {'n': '台湾', 'v': '台湾'},
        {'n': '日本', 'v': '日本'},
        {'n': '韩国', 'v': '韩国'},
        {'n': '欧美', 'v': '欧美'},
        {'n': '泰国', 'v': '泰国'},
        {'n': '其他', 'v': '其他'},
    ]}

    # 年份筛选选项 (各分类通用)
    YEAR_FILTER = {'key': 'year', 'name': '年份', 'value': [
        {'n': '全部', 'v': ''},
        {'n': '2026', 'v': '2026'},
        {'n': '2025', 'v': '2025'},
        {'n': '2024', 'v': '2024'},
        {'n': '2023', 'v': '2023'},
        {'n': '2022', 'v': '2022'},
        {'n': '2021', 'v': '2021'},
        {'n': '2020', 'v': '2020'},
        {'n': '2019', 'v': '2019'},
        {'n': '2018', 'v': '2018'},
        {'n': '2017', 'v': '2017'},
        {'n': '2016', 'v': '2016'},
        {'n': '2015', 'v': '2015'},
    ]}

    def _build_filters(self):
        """构建各分类的子分类筛选器"""
        filters = {}

        # 电影
        filters['1'] = [
            {'key': 'class', 'name': '类型', 'value': [
                {'n': '全部',   'v': ''},
                {'n': '动作片', 'v': '5'},
                {'n': '爱情片', 'v': '6'},
                {'n': '科幻片', 'v': '7'},
                {'n': '恐怖片', 'v': '8'},
                {'n': '战争片', 'v': '9'},
                {'n': '喜剧片', 'v': '10'},
                {'n': '纪录片', 'v': '11'},
                {'n': '剧情片', 'v': '12'},
                {'n': '悬疑片', 'v': '28'},
                {'n': '犯罪片', 'v': '29'},
            ]},
            dict(self.AREA_FILTER),
            dict(self.YEAR_FILTER),
        ]

        # 电视剧
        filters['2'] = [
            {'key': 'class', 'name': '类型', 'value': [
                {'n': '全部',   'v': ''},
                {'n': '国产剧', 'v': '13'},
                {'n': '港剧',   'v': '14'},
                {'n': '欧美剧', 'v': '15'},
                {'n': '韩剧',   'v': '16'},
                {'n': '台湾剧', 'v': '32'},
                {'n': '日本剧', 'v': '33'},
                {'n': '海外剧', 'v': '34'},
                {'n': '泰剧',   'v': '42'},
                {'n': '亚洲剧', 'v': '60'},
            ]},
            dict(self.AREA_FILTER),
            dict(self.YEAR_FILTER),
        ]

        # 综艺
        filters['3'] = [
            {'key': 'class', 'name': '类型', 'value': [
                {'n': '全部',     'v': ''},
                {'n': '国产综艺', 'v': '45'},
                {'n': '日韩综艺', 'v': '46'},
                {'n': '港台综艺', 'v': '47'},
                {'n': '欧美综艺', 'v': '48'},
            ]},
            dict(self.AREA_FILTER),
            dict(self.YEAR_FILTER),
        ]

        # 动漫
        filters['4'] = [
            {'key': 'class', 'name': '类型', 'value': [
                {'n': '全部',     'v': ''},
                {'n': '国产动漫', 'v': '49'},
                {'n': '日韩动漫', 'v': '50'},
                {'n': '欧美动漫', 'v': '51'},
                {'n': '动漫电影', 'v': '52'},
                {'n': '港台动漫', 'v': '53'},
                {'n': '海外动漫', 'v': '54'},
            ]},
            dict(self.AREA_FILTER),
            dict(self.YEAR_FILTER),
        ]

        # 短剧
        filters['30'] = [
            dict(self.AREA_FILTER),
            dict(self.YEAR_FILTER),
        ]

        # 预告
        filters['55'] = [
            dict(self.AREA_FILTER),
            dict(self.YEAR_FILTER),
        ]

        return filters

    # ==================== 基础方法 ====================

    def getName(self):
        return "播播影院"

    def init(self, cfg=''):
        return self

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False

    def _fetch(self, url):
        """发起 HTTP GET 请求并返回 HTML 文本
        该网站检测 UA 拦截爬虫库, 用不含拦截特征的 UA 即可"""
        try:
            if _requests is not None:
                session = _requests.Session()
                resp = session.get(url, headers=self.HEADERS, timeout=15,
                                   verify=False, allow_redirects=True)
                resp.encoding = 'utf-8'
                return resp.text
            else:
                return ''
        except Exception:
            return ''

    # ==================== HTML 解析工具 ====================

    def _parse_video_list(self, html):
        """从 HTML 中解析视频列表, 返回 TVBox 格式的 list"""
        videos = []
        # 匹配包含 stui-vodlist__item 的 <li> 块
        items = re.findall(
            r'<li[^>]*stui-vodlist__item[^>]*>(.*?)</li>', html, re.S)
        for item in items:
            video = {}

            # 封面图 (data-original 属性)
            pic_match = re.search(r'data-original="([^"]*)"', item)
            if pic_match:
                video['vod_pic'] = pic_match.group(1)

            # 视频 ID (从 /malvod/xxx.html 提取)
            href_match = re.search(r'href="/malvod/(\d+)\.html"', item)
            if href_match:
                video['vod_id'] = href_match.group(1)

            # 标题 (优先从 stui-vodlist__title 中的 a 标签文本提取)
            title_match = re.search(
                r'stui-vodlist__title[^>]*>.*?<a[^>]*>([^<]*)</a>', item, re.S)
            if title_match:
                video['vod_name'] = title_match.group(1).strip()
            else:
                # 回退: 从 thumb 链接的 title 属性提取
                title_attr = re.search(
                    r'stui-vodlist__thumb[^>]*title="([^"]*)"', item)
                if title_attr:
                    video['vod_name'] = title_attr.group(1).strip()

            # 状态/集数 (pic-text)
            remark_match = re.search(r'pic-text[^>]*>([^<]*)</span>', item)
            if remark_match:
                video['vod_remarks'] = remark_match.group(1).strip()

            if video.get('vod_id') and video.get('vod_name'):
                videos.append(video)

        return videos

    def _parse_page_count(self, html):
        """从 HTML 中解析总页数"""
        # 匹配分页中的 "当前页/总页数" 格式, 如 "1/1845"
        match = re.search(r'class="num"[^>]*>\s*(\d+)/(\d+)\s*<', html)
        if match:
            return int(match.group(2))
        # 回退: 匹配尾页链接中的数字
        match = re.search(r'/mallist/\d+-(\d+)\.html"[^>]*>尾页', html)
        if match:
            return int(match.group(1))
        return 1

    # ==================== 首页 ====================

    def homeContent(self, filter):
        result = {}
        result['class'] = [dict(item) for item in self.CATEGORIES]
        if filter:
            result['filters'] = self._build_filters()

        # 获取首页推荐视频
        html = self._fetch(self.HOST)
        if html:
            videos = self._parse_video_list(html)
            if videos:
                result['list'] = videos

        return result

    def homeVideoContent(self):
        html = self._fetch(self.HOST)
        videos = self._parse_video_list(html) if html else []
        return {'list': videos}

    # ==================== 分类内容 ====================

    def categoryContent(self, tid, pg, filter, extend):
        result = {}
        page = int(pg) if pg else 1
        extend = extend or {}

        # 确定实际分类 ID (子分类覆盖一级分类)
        cat_id = extend.get('class', '') or tid

        # 是否有地区/年份筛选
        has_search_filter = bool(extend.get('area') or extend.get('year'))

        if has_search_filter:
            # 使用 search.php 搜索接口
            url = '%s/search.php?searchtype=5&tid=%s' % (self.HOST, cat_id)
            if extend.get('area'):
                url += '&area=' + extend['area']
            if extend.get('year'):
                url += '&year=' + extend['year']
            if page > 1:
                url += '&page=%d' % page
        else:
            # 使用 mallist 分类接口
            if page > 1:
                url = '%s/mallist/%s-%d.html' % (self.HOST, cat_id, page)
            else:
                url = '%s/mallist/%s.html' % (self.HOST, cat_id)

        html = self._fetch(url)
        if not html:
            return {'list': [], 'page': page, 'pagecount': 1, 'limit': 0}

        videos = self._parse_video_list(html)
        page_count = self._parse_page_count(html)

        result['list'] = videos
        result['page'] = page
        result['pagecount'] = page_count
        result['limit'] = len(videos)
        result['total'] = page_count * len(videos)

        return result

    # ==================== 详情页 ====================

    def detailContent(self, ids):
        vid = ids[0]
        url = '%s/malvod/%s.html' % (self.HOST, vid)
        html = self._fetch(url)

        if not html:
            return {'list': []}

        vod = {'vod_id': vid}

        # 标题
        title_match = re.search(
            r'<h1[^>]*title[^>]*>([^<]*)</h1>', html)
        if title_match:
            vod['vod_name'] = title_match.group(1).strip()

        # 封面图
        pic_match = re.search(
            r'data-original="([^"]*)"', html)
        if pic_match:
            vod['vod_pic'] = pic_match.group(1)

        # 分类
        type_match = re.search(
            r'class="[^"]*text-muted[^"]*"[^>]*>\s*分类.*?<a[^>]*>([^<]*)</a>', html, re.S)
        if type_match:
            vod['type_name'] = type_match.group(1).strip()

        # 地区
        area_match = re.search(
            r'class="[^"]*text-muted[^"]*"[^>]*>\s*地区.*?</span>\s*([^<\s]+)', html, re.S)
        if area_match:
            vod['vod_area'] = area_match.group(1).strip()

        # 年份
        year_match = re.search(
            r'class="[^"]*text-muted[^"]*"[^>]*>\s*年份.*?</span>\s*(\d{4})', html, re.S)
        if year_match:
            vod['vod_year'] = year_match.group(1)

        # 导演
        director_match = re.search(
            r'class="[^"]*text-muted[^"]*"[^>]*>\s*导演.*?</span>(.*?)</p>', html, re.S)
        if director_match:
            directors = re.findall(r'>([^<]+)</a>', director_match.group(1))
            vod['vod_director'] = ' '.join(d.strip() for d in directors if d.strip())

        # 主演
        actor_match = re.search(
            r'class="[^"]*text-muted[^"]*"[^>]*>\s*主演.*?</span>(.*?)</p>', html, re.S)
        if actor_match:
            actors = re.findall(r'>([^<]+)</a>', actor_match.group(1))
            vod['vod_actor'] = ' '.join(a.strip() for a in actors if a.strip())

        # 状态
        state_match = re.search(
            r'class="[^"]*text-muted[^"]*"[^>]*>\s*状态[：:]\s*([^<\s]+)', html, re.S)
        if state_match:
            vod['vod_remarks'] = state_match.group(1).strip()

        # 简介
        content_match = re.search(
            r'<span[^>]*class="[^"]*text-muted[^"]*"[^>]*>\s*(?:简介|剧情|内容)[：:]\s*</span>\s*(.*?)(?:</p>|<br)', html, re.S)
        if content_match:
            vod['vod_content'] = content_match.group(1).strip()

        # 播放列表
        vod['vod_play_from'] = ''
        vod['vod_play_url'] = ''

        # 解析播放源和剧集
        play_from_list = []
        play_url_list = []

        # 匹配所有播放源区块 (stui-pannel 内含 stui-content__playlist)
        # 每个播放源包含一个标题 h3.title 和一个 ul.stui-content__playlist
        pannel_pattern = re.compile(
            r'<h3[^>]*title[^>]*>(.*?)</h3>.*?'
            r'<ul[^>]*stui-content__playlist[^>]*>(.*?)</ul>', re.S)

        for match in pannel_pattern.finditer(html):
            source_name = match.group(1).strip()
            playlist_html = match.group(2)

            # 清理播放源名称 (去掉所有 HTML 标签和提示文字)
            source_name = re.sub(r'<[^>]+>.*?</[^>]+>', '', source_name).strip()
            source_name = re.sub(r'<[^>]+>', '', source_name).strip()
            if not source_name:
                continue

            # 提取剧集列表
            episodes = re.findall(
                r'<a[^>]*href="(/malplayer/[^"]*)"[^>]*>(.*?)</a>',
                playlist_html, re.S)

            if not episodes:
                continue

            # 构建播放列表: 剧集名$播放地址#剧集名$播放地址#...
            ep_list = []
            for ep_url, ep_name in episodes:
                ep_name = ep_name.strip()
                ep_list.append('%s$%s' % (ep_name, ep_url))

            if ep_list:
                play_from_list.append(source_name)
                play_url_list.append('#'.join(ep_list))

        vod['vod_play_from'] = '$$$'.join(play_from_list)
        vod['vod_play_url'] = '$$$'.join(play_url_list)

        return {'list': [vod]}

    # ==================== 搜索 ====================

    def searchContent(self, key, quick):
        url = '%s/search.php?searchword=%s' % (self.HOST, key)
        html = self._fetch(url)

        if not html:
            return {'list': []}

        videos = self._parse_video_list(html)

        # 搜索结果需要额外处理: 确保有 vod_name
        result = []
        for v in videos:
            if not v.get('vod_name'):
                continue
            result.append(v)

        return {'list': result}

    # ==================== 播放 ====================

    def playerContent(self, flag, id, vipFlags):
        # id 是播放页路径, 如 /malplayer/1323-3-1173.html
        if id.startswith('http'):
            url = id
        else:
            url = self.HOST + id if id.startswith('/') else self.HOST + '/' + id

        html = self._fetch(url)

        play_url = ''
        if html:
            # 从 JavaScript 中提取 now 变量的值 (实际播放地址)
            now_match = re.search(r'var\s+now\s*=\s*"([^"]+)"', html)
            if now_match:
                play_url = now_match.group(1)

        header = {
            'User-Agent': self.HEADERS['User-Agent'],
            'Referer': url,
        }

        return {
            'parse': 0,
            'playUrl': '',
            'url': play_url,
            'header': json.dumps(header),
        }

    def localProxy(self, params):
        return None
