#coding=utf-8
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TVBox / 影视仓  Python源脚本
站点: 8090电影网 (www.8090hub.cc)
技术栈: maccms (苹果CMS) + stui 速腾模板
策略: 优先使用 maccms 自带 JSON API,HTML 解析作为降级方案
"""

import sys
import re
import json
import requests
from urllib.parse import quote
from pyquery import PyQuery as pq
sys.path.append('..')
from base.spider import Spider


class Spider(Spider):

    def __init__(self):
        super().__init__()
        # 站点配置
        self.site = 'https://www.8090hub.cc'
        self.api_url = f'{self.site}/api.php/provide/vod'
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                          'AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/120.0.0.0 Safari/537.36',
            'Referer': f'{self.site}/'
        })
        # 手动分类 (与站点导航栏一致)
        self.cateManual = {
            '剧集': '21',
            '电影': '20',
            '动漫': '22',
            '综艺': '23'
        }

    def init(self, extend=""):
        pass

    def getName(self):
        return "8090电影网"

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    # ============================================================
    #  首页: 返回分类列表 + 首页推荐数据
    # ============================================================
    def homeContent(self, filter):
        result = {'class': [], 'filters': {}, 'list': [], 'parse': 0, 'jx': 0}

        # 填充分类
        for k, v in self.cateManual.items():
            result['class'].append({
                'type_id': str(v),
                'type_name': k
            })

        # 尝试通过 API 获取最新影片 (电影分类第1页)
        try:
            api_data = self._fetch_api_list(tid='20', page=1)
            if api_data:
                result['list'] = api_data
        except Exception as e:
            print(f'homeContent API error: {e}')
            # API 失败则降级到 HTML 解析
            try:
                result['list'] = self._parse_html_list('20', 1)
            except Exception as e2:
                print(f'homeContent HTML fallback error: {e2}')

        return result

    # ============================================================
    #  分类页: 分页获取分类下的影片列表
    # ============================================================
    def categoryContent(self, tid, pg, filter, extend):
        result = {'list': [], 'parse': 0, 'jx': 0}
        page = int(pg) if pg else 1

        # 优先使用 JSON API
        try:
            vod_list, total, pagecount = self._fetch_api_list_paged(tid, page)
            result['list'] = vod_list
            result['page'] = page
            result['pagecount'] = pagecount
            result['limit'] = len(vod_list)
            result['total'] = total
            return result
        except Exception as e:
            print(f'categoryContent API error: {e}')

        # 降级: HTML 解析
        try:
            vod_list = self._parse_html_list(tid, page)
            result['list'] = vod_list
        except Exception as e2:
            print(f'categoryContent HTML fallback error: {e2}')

        result['page'] = page
        result['pagecount'] = page + 1 if len(result['list']) > 0 else page
        result['limit'] = len(result['list'])
        result['total'] = len(result['list'])
        return result

    # ============================================================
    #  详情页: 获取影片完整信息 + 播放线路与剧集
    # ============================================================
    def detailContent(self, ids):
        result = {'list': [], 'parse': 0, 'jx': 0}
        vid = ids[0] if ids else ''
        if not vid:
            return result

        # 优先使用 JSON API 获取详情
        try:
            vod = self._fetch_api_detail(vid)
            if vod:
                result['list'].append(vod)
                return result
        except Exception as e:
            print(f'detailContent API error: {e}')

        # 降级: HTML 解析
        try:
            vod = self._parse_html_detail(vid)
            if vod:
                result['list'].append(vod)
        except Exception as e2:
            print(f'detailContent HTML fallback error: {e2}')

        return result

    # ============================================================
    #  播放解析: 获取真实播放地址
    # ============================================================
    def playerContent(self, flag, id, vipFlags):
        result = {
            'parse': 0,
            'jx': 0,
            'header': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                              'AppleWebKit/537.36 (KHTML, like Gecko) '
                              'Chrome/120.0.0.0 Safari/537.36',
                'Referer': f'{self.site}/'
            }
        }

        try:
            play_url = id.strip()

            # 如果已经是直链 (m3u8/mp4) 直接返回
            if play_url.startswith('http') and re.search(r'\.(m3u8|mp4)', play_url):
                result['url'] = play_url
                result['parse'] = 0
                return result

            # 如果是相对路径,拼接站点地址
            if play_url and not play_url.startswith('http'):
                play_url = self.site + play_url

            # 请求播放页,提取真实地址
            r = self.session.get(play_url, timeout=15, verify=False)
            r.encoding = 'utf-8'
            html = r.text

            video_url = self._extract_video_url(html)

            if video_url:
                result['url'] = video_url
                result['parse'] = 0
            else:
                # 无法提取直链,交给播放器嗅探
                result['url'] = play_url
                result['parse'] = 1

        except Exception as e:
            print(f'playerContent error: {e}')
            result['url'] = id if id.startswith('http') else self.site + id
            result['parse'] = 1

        return result

    # ============================================================
    #  搜索
    # ============================================================
    def searchContent(self, key, quick, pg='1'):
        result = {'list': [], 'parse': 0, 'jx': 0}
        page = int(pg) if pg else 1

        # 优先使用 JSON API 搜索
        try:
            vod_list, total, pagecount = self._api_search(key, page)
            result['list'] = vod_list
        except Exception as e:
            print(f'searchContent API error: {e}')
            # 降级: HTML 搜索
            try:
                result['list'] = self._html_search(key, page)
            except Exception as e2:
                print(f'searchContent HTML fallback error: {e2}')

        result['page'] = page
        result['pagecount'] = page + 1 if len(result['list']) > 0 else page
        result['limit'] = len(result['list'])
        result['total'] = len(result['list'])
        return result

    def localProxy(self, params):
        return [200, "video/MP2T", {}, ""]

    # ============================================================
    #  === maccms JSON API 方法 ===
    # ============================================================

    def _fetch_api_list(self, tid, page):
        """通过 API 获取列表 (简版,只返回 vod 基本字段)"""
        params = {
            'ac': 'list',
            't': str(tid),
            'pg': str(page)
        }
        r = self.session.get(self.api_url, params=params, timeout=15, verify=False)
        data = r.json()

        vod_list = []
        for item in data.get('list', []):
            vod_list.append({
                'vod_id': str(item.get('vod_id', '')),
                'vod_name': item.get('vod_name', ''),
                'vod_pic': item.get('vod_pic', ''),
                'vod_remarks': item.get('vod_remarks', '')
            })
        return vod_list

    def _fetch_api_list_paged(self, tid, page):
        """通过 API 获取分页列表,同时返回分页信息"""
        params = {
            'ac': 'detail',
            't': str(tid),
            'pg': str(page)
        }
        r = self.session.get(self.api_url, params=params, timeout=15, verify=False)
        data = r.json()

        vod_list = []
        for item in data.get('list', []):
            vod_list.append({
                'vod_id': str(item.get('vod_id', '')),
                'vod_name': item.get('vod_name', ''),
                'vod_pic': item.get('vod_pic', ''),
                'vod_remarks': item.get('vod_remarks', '')
            })

        pagecount = int(data.get('pagecount', page + 1))
        total = int(data.get('total', len(vod_list)))
        return vod_list, total, pagecount

    def _fetch_api_detail(self, vid):
        """通过 API 获取影片完整详情 (含播放地址)"""
        params = {
            'ac': 'detail',
            'ids': str(vid)
        }
        r = self.session.get(self.api_url, params=params, timeout=15, verify=False)
        data = r.json()

        items = data.get('list', [])
        if not items:
            return None

        item = items[0]

        # 解析播放线路
        # maccms 格式: 线路名$剧集1$地址1#剧集2$地址2$$$线路名2$...
        play_from = []
        play_url = []

        raw_play_from = item.get('vod_play_from', '')
        raw_play_url = item.get('vod_play_url', '')

        if raw_play_from and raw_play_url:
            lines_from = raw_play_from.split('$$$')
            lines_url = raw_play_url.split('$$$')

            for i, line_name in enumerate(lines_from):
                line_name = line_name.strip()
                if not line_name:
                    continue
                if i < len(lines_url):
                    play_from.append(line_name)
                    play_url.append(lines_url[i].strip())

        vod = {
            'vod_id': str(item.get('vod_id', vid)),
            'vod_name': item.get('vod_name', ''),
            'vod_pic': item.get('vod_pic', ''),
            'type_name': item.get('vod_class', ''),
            'vod_year': item.get('vod_year', ''),
            'vod_area': item.get('vod_area', ''),
            'vod_remarks': item.get('vod_remarks', ''),
            'vod_actor': item.get('vod_actor', ''),
            'vod_director': item.get('vod_director', ''),
            'vod_content': item.get('vod_content', '').strip(),
            'vod_play_from': '$$$'.join(play_from),
            'vod_play_url': '$$$'.join(play_url)
        }
        return vod

    def _api_search(self, key, page):
        """通过 API 搜索"""
        params = {
            'ac': 'detail',
            'wd': key,
            'pg': str(page)
        }
        r = self.session.get(self.api_url, params=params, timeout=15, verify=False)
        data = r.json()

        vod_list = []
        for item in data.get('list', []):
            vod_list.append({
                'vod_id': str(item.get('vod_id', '')),
                'vod_name': item.get('vod_name', ''),
                'vod_pic': item.get('vod_pic', ''),
                'vod_remarks': item.get('vod_remarks', '')
            })

        pagecount = int(data.get('pagecount', page + 1))
        total = int(data.get('total', len(vod_list)))
        return vod_list, total, pagecount

    # ============================================================
    #  === HTML 解析降级方法 ===
    # ============================================================

    def _parse_html_list(self, tid, page):
        """HTML 解析分类列表 (stui 模板)"""
        url = f'{self.site}/show/{tid}-----------{page}---.html'
        r = self.session.get(url, timeout=15, verify=False)
        r.encoding = 'utf-8'
        doc = pq(r.text)

        vod_list = []
        # stui 模板: .stui-vodlist__box 内含封面链接和详情
        for box in doc('.stui-vodlist__box').items():
            a = box.find('.stui-vodlist__thumb')
            href = a.attr('href') or ''
            vid = self._extract_vid(href)
            if not vid:
                continue

            title = a.attr('title') or ''
            if not title:
                title = box.find('.stui-vodlist__detail h4 a').attr('title') or \
                        box.find('.stui-vodlist__detail h4 a').text() or ''
            title = title.strip()
            if not title:
                continue

            pic = a.attr('data-original') or ''
            if pic and pic.startswith('//'):
                pic = 'https:' + pic
            elif pic and pic.startswith('/'):
                pic = self.site + pic

            note = box.find('.pic-text').eq(0).text().strip()

            vod_list.append({
                'vod_id': vid,
                'vod_name': title,
                'vod_pic': pic,
                'vod_remarks': note
            })

        # 同时处理文字列表 (.stui-vodlist__text)
        for li in doc('.stui-vodlist__text li').items():
            a = li.find('a')
            href = a.attr('href') or ''
            vid = self._extract_vid(href)
            if not vid:
                continue
            title = a.attr('title') or a.text().strip()
            if not title:
                continue
            note = li.find('span.text-muted').eq(0).text().strip()
            vod_list.append({
                'vod_id': vid,
                'vod_name': title,
                'vod_pic': '',
                'vod_remarks': note
            })

        return vod_list

    def _parse_html_detail(self, vid):
        """HTML 解析详情页 (stui 模板)"""
        url = f'{self.site}/video/{vid}.html'
        r = self.session.get(url, timeout=15, verify=False)
        r.encoding = 'utf-8'
        html = r.text
        doc = pq(html)

        # 标题
        title = ''
        title_match = re.search(r'<title>(.+?)</title>', html)
        if title_match:
            title = title_match.group(1).split('-')[0].strip()

        # 封面
        pic = ''
        pic_elem = doc('.stui-vodlist__thumb').eq(0)
        if pic_elem.length:
            pic = pic_elem.attr('data-original') or ''
            if pic and pic.startswith('//'):
                pic = 'https:' + pic
            elif pic and pic.startswith('/'):
                pic = self.site + pic

        # 详情字段 (stui 模板: .stui-content__detail 内的 p 标签)
        detail = doc('.stui-content__detail')
        type_name = ''
        vod_year = ''
        vod_area = ''
        vod_actor = ''
        vod_director = ''
        vod_remarks = ''
        desc = ''

        # 遍历详情行的 label: value 结构
        for p in detail.find('p').items():
            text = p.text().strip()
            if '导演' in text:
                vod_director = re.sub(r'^导演[:：]?\s*', '', text).strip()
            elif '主演' in text:
                vod_actor = re.sub(r'^主演[:：]?\s*', '', text).strip()
            elif '类型' in text:
                type_name = re.sub(r'^类型[:：]?\s*', '', text).strip()
            elif '地区' in text:
                vod_area = re.sub(r'^地区[:：]?\s*', '', text).strip()
            elif '年份' in text:
                vod_year = re.sub(r'^年份[:：]?\s*', '', text).strip()
            elif '备注' in text:
                vod_remarks = re.sub(r'^备注[:：]?\s*', '', text).strip()

        # 简介
        desc_elem = doc('.stui-content__desc, .desc, [class*="content-desc"]').eq(0)
        if desc_elem.length:
            desc = desc_elem.text().strip()
        else:
            desc_match = re.search(r'<meta\s+name="description"\s+content="([^"]+)"', html)
            if desc_match:
                desc = desc_match.group(1).strip()

        # 播放线路与剧集 (stui 模板: .stui-play__list)
        play_from = []
        play_url = []

        # stui 播放源结构: .stui-pannel__box .stui-play__list
        play_tabs = doc('.stui-pannel__head .title a, .module-player-tab, .stui-player__list .title')
        play_lists = doc('.stui-content__playlist, .stui-play__list, ul[class*="playlist"]')

        # 方式1: 遍历所有播放列表
        if play_lists.length:
            for i, playlist in enumerate(play_lists.items()):
                episodes = []
                for ep in playlist.find('li a').items():
                    ep_text = ep.text().strip()
                    ep_href = ep.attr('href') or ''
                    if ep_text and ep_href:
                        episodes.append(f'{ep_text}${ep_href}')

                if episodes:
                    line_name = f'线路{i + 1}'
                    # 尝试从对应的 tab 获取线路名
                    if i < play_tabs.length:
                        tab_text = play_tabs.eq(i).text().strip()
                        if tab_text:
                            line_name = tab_text
                    play_from.append(line_name)
                    play_url.append('#'.join(episodes))

        # 方式2: 正则匹配播放链接 (降级)
        if not play_from:
            all_play = re.findall(
                r'<a[^>]+href="(/play/(\d+)-(\d+)-(\d+)\.html)"[^>]*>(.*?)</a>',
                html, re.DOTALL
            )
            episodes_by_sid = {}
            sids_in_order = []
            seen_sids = set()

            for href, sid, nid, link_html in all_play:
                text = re.sub(r'<[^>]+>', '', link_html).strip()
                if not text:
                    continue
                if sid not in episodes_by_sid:
                    episodes_by_sid[sid] = []
                episodes_by_sid[sid].append(f'{text}${href}')
                if sid not in seen_sids:
                    seen_sids.add(sid)
                    sids_in_order.append(sid)

            for i, sid in enumerate(sids_in_order):
                if episodes_by_sid.get(sid):
                    play_from.append(f'线路{sid}')
                    play_url.append('#'.join(episodes_by_sid[sid]))

        vod = {
            'vod_id': str(vid),
            'vod_name': title,
            'vod_pic': pic,
            'type_name': type_name,
            'vod_year': vod_year,
            'vod_area': vod_area,
            'vod_remarks': vod_remarks,
            'vod_actor': vod_actor,
            'vod_director': vod_director,
            'vod_content': desc,
            'vod_play_from': '$$$'.join(play_from),
            'vod_play_url': '$$$'.join(play_url)
        }
        return vod

    def _html_search(self, key, page):
        """HTML 搜索解析 (stui 模板)"""
        url = f'{self.site}/search/-------------.html?wd={quote(key)}'
        if page > 1:
            url = f'{self.site}/search/{quote(key)}----------{page}---.html'

        r = self.session.get(url, timeout=15, verify=False)
        r.encoding = 'utf-8'
        doc = pq(r.text)

        vod_list = []
        for box in doc('.stui-vodlist__box, .stui-vodlist__item').items():
            a = box.find('.stui-vodlist__thumb')
            if not a.length:
                a = box.find('a').eq(0)
            href = a.attr('href') or ''
            vid = self._extract_vid(href)
            if not vid:
                continue

            title = a.attr('title') or box.find('h4 a').text() or ''
            title = title.strip()
            if not title:
                continue

            pic = a.attr('data-original') or ''
            if pic and pic.startswith('//'):
                pic = 'https:' + pic
            elif pic and pic.startswith('/'):
                pic = self.site + pic

            note = box.find('.pic-text').eq(0).text().strip()

            vod_list.append({
                'vod_id': vid,
                'vod_name': title,
                'vod_pic': pic,
                'vod_remarks': note
            })

        return vod_list

    # ============================================================
    #  === 工具方法 ===
    # ============================================================

    def _extract_vid(self, url):
        """从 URL 中提取影片 ID"""
        if not url:
            return ''
        m = re.search(r'/video/(\d+)\.html', url)
        if m:
            return m.group(1)
        m = re.search(r'/play/(\d+)-', url)
        if m:
            return m.group(1)
        m = re.search(r'/detail/(\d+)\.html', url)
        if m:
            return m.group(1)
        return ''

    def _extract_video_url(self, html):
        """从播放页 HTML 中提取真实视频地址"""
        patterns = [
            r'src["\']?\s*[:=]\s*["\']([^"\']+\.(?:m3u8|mp4)[^"\']*)["\']',
            r'"url"\s*:\s*"([^"]+\.(?:m3u8|mp4)[^"]*)"',
            r"url\s*:\s*'([^']+\.(?:m3u8|mp4)[^']*)'",
            r'data-url="([^"]+\.(?:m3u8|mp4)[^"]*)"',
        ]

        for pat in patterns:
            m = re.search(pat, html, re.DOTALL | re.IGNORECASE)
            if m:
                return m.group(1)

        # 全文扫描所有 m3u8/mp4 链接
        all_urls = re.findall(
            r'https?://[^\s"\'<>]+\.(?:m3u8|mp4)[^\s"\'<>]*',
            html, re.IGNORECASE
        )
        if all_urls:
            for u in all_urls:
                if 'index.m3u8' in u or 'video.m3u8' in u or '.mp4' in u:
                    return u
            return all_urls[0]

        return ''
