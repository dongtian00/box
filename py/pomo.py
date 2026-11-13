# coding=utf-8
# !/usr/bin/python
# Pomo 4K原盘 TVBox爬虫
# 支持在线m3u8播放 + 磁力链接 + 夸克网盘
import re
import sys
from urllib.parse import quote

sys.path.append('..')
from base.spider import Spider


class Spider(Spider):

    def init(self, extend=""):
        pass

    def getName(self):
        return "Pomo4K"

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        pass

    def destroy(self):
        pass

    host = 'https://pomo.mom'

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36',
        'Referer': 'https://pomo.mom/',
    }

    # 分类配置
    CATEGORIES = {
        'home': {'name': '首页', 'url': ''},
        'huayu': {'name': '华语热门', 'url': 'huayurm'},
        'jiating': {'name': '家庭影院', 'url': 'jiating'},
        'donghua': {'name': '动画大电影', 'url': 'donghuadadiany'},
        'lengmen': {'name': '冷门佳片', 'url': 'lengmenjiapian'},
        'top250': {'name': 'TOP250', 'url': 'paihangbang'},
        'languang': {'name': '蓝光原盘', 'url': 'sort/12'},
        'dianshiju': {'name': '剧集', 'url': 'dianshiju'},
    }

    def homeContent(self, filter):
        result = {}
        classes = []
        for tid, info in self.CATEGORIES.items():
            classes.append({
                'type_name': info['name'],
                'type_id': tid
            })
        result['class'] = classes
        result['filters'] = {}
        return result

    def homeVideoContent(self):
        return self._parse_list(f'{self.host}/')

    def categoryContent(self, tid, pg, filter, extend):
        cat = self.CATEGORIES.get(tid)
        if not cat:
            return {'list': [], 'page': pg, 'pagecount': 1, 'limit': 16, 'total': 0}

        if cat['url']:
            url = f'{self.host}/{cat["url"]}'
        else:
            url = f'{self.host}/'

        if int(pg) > 1:
            if cat['url']:
                url = f'{self.host}/{cat["url"]}/page/{pg}'
            else:
                url = f'{self.host}/page/{pg}'

        result = self._parse_list(url)
        result['page'] = pg
        result['pagecount'] = 9999
        result['limit'] = 16
        result['total'] = 999999
        return result

    def _parse_list(self, url):
        """解析列表页，返回视频列表"""
        try:
            resp = self.fetch(url, headers=self.headers)
            text = self._get_text(resp)
            videos = []
            seen = set()

            start = text.find('All 4K Movies')
            if start == -1:
                start = text.find('<main')
            if start == -1:
                start = 0
            section = text[start:]

            img_pattern = r'<img[^>]*src="([^"]*uploadfile[^"]*)"[^>]*alt="([^"]*)"[^>]*>'
            pos = 0
            while True:
                img_match = re.search(img_pattern, section[pos:])
                if not img_match:
                    break

                img_src = img_match.group(1)
                img_alt = img_match.group(2)
                img_start = pos + img_match.start()
                img_end = pos + img_match.end()

                before = section[max(0, img_start - 2000):img_start]
                a_match = None
                for m in re.finditer(r'<a\s+href="https://pomo\.mom/(\d+)(?:\.html)?"', before):
                    a_match = m

                if a_match:
                    vid = a_match.group(1)
                    if vid not in seen:
                        seen.add(vid)
                        videos.append({
                            'vod_id': vid,
                            'vod_name': img_alt,
                            'vod_pic': img_src,
                            'vod_remarks': ''
                        })

                pos = img_end

            return {'list': videos}
        except Exception as e:
            print(f'[Pomo] 解析列表出错: {e}')
            return {'list': []}

    def _get_player_routes(self, vid):
        """
        访问播放器页面，提取m3u8播放源
        返回: { '线路1': [(title, url), ...], '线路2': [(title, url), ...] }
        """
        routes = {}
        try:
            player_url = f'{self.host}/?plugin=plyr_player&gid={vid}'
            resp = self.fetch(player_url, headers=self.headers)
            text = self._get_text(resp)

            # 提取 route1Data
            route1_match = re.search(r'route1Data\s*=\s*(\[[^\]]*\])', text)
            if route1_match:
                try:
                    import json
                    route1 = json.loads(route1_match.group(1))
                    if route1:
                        items = []
                        for item in route1:
                            if '$' in item:
                                parts = item.split('$', 1)
                                items.append((parts[0], parts[1]))
                            else:
                                items.append(('播放', item))
                        if items:
                            routes['线路1'] = items
                except Exception as e:
                    print(f'[Pomo] 解析route1Data失败: {e}')

            # 提取 route2Data
            route2_match = re.search(r'route2Data\s*=\s*(\[[^\]]*\])', text)
            if route2_match:
                try:
                    import json
                    route2 = json.loads(route2_match.group(1))
                    if route2:
                        items = []
                        for item in route2:
                            if '$' in item:
                                parts = item.split('$', 1)
                                items.append((parts[0], parts[1]))
                            else:
                                items.append(('播放', item))
                        if items:
                            routes['线路2'] = items
                except Exception as e:
                    print(f'[Pomo] 解析route2Data失败: {e}')

        except Exception as e:
            print(f'[Pomo] 获取播放器路由失败: {e}')

        return routes

    def detailContent(self, ids):
        try:
            vid = ids[0]
            url = f'{self.host}/{vid}.html'
            resp = self.fetch(url, headers=self.headers)
            text = self._get_text(resp)

            # 标题
            title_match = re.search(r'<h2 class="x-dbjs-title">([^<]+)</h2>', text)
            title = title_match.group(1).strip() if title_match else ''

            # 海报
            poster_match = re.search(r'<div class="x-dbjs-poster"><img src="([^"]+)"', text)
            poster = poster_match.group(1) if poster_match else ''

            # 元信息
            meta = {}
            meta_rows = re.findall(r'<div class="meta-row[^"]*"><span>([^<]+)</span>([^<]+)</div>', text)
            for label, value in meta_rows:
                label = label.strip().replace('：', '')
                meta[label] = value.strip()

            # 演员
            actors_match = re.search(r'<div class="meta-row actors[^"]*"><span>演员阵容：</span>([^<]+)</div>', text)
            actors = actors_match.group(1).strip() if actors_match else meta.get('演员阵容', '')

            # 导演
            director = meta.get('导演', '')

            # 类型
            type_name = meta.get('类型', '')

            # 年份
            year = ''
            time_str = meta.get('时间', '')
            if time_str:
                year_match = re.search(r'(\d{4})', time_str)
                if year_match:
                    year = year_match.group(1)

            # 简介
            desc_match = re.search(r'<div class="x-dbjs-desc-block[^"]*"><h3[^>]*>剧情简介</h3><p>([^<]+)</p>', text)
            desc = desc_match.group(1).strip() if desc_match else ''

            # === 获取在线播放源（m3u8直链）===
            online_routes = self._get_player_routes(vid)

            # === 磁力链接（去重）===
            magnets = re.findall(r'data-url="(magnet:\?xt=urn:btih:[^"]+)"', text)
            unique_magnets = []
            seen_mag = set()
            for m in magnets:
                if m not in seen_mag:
                    seen_mag.add(m)
                    unique_magnets.append(m)

            # 提取每个磁力链接对应的文件名和大小
            mag_playlists = []
            items = re.findall(r'<div class="download-item">(.*?)</div>\s*</div>', text, re.DOTALL)
            seen_items = set()
            for item in items:
                mag_match = re.search(r'data-url="(magnet:\?xt=urn:btih:[^"]+)"', item)
                if not mag_match:
                    continue
                mag = mag_match.group(1)
                if mag in seen_items:
                    continue
                seen_items.add(mag)

                name_match = re.search(r'class="x-dbjs-download-link[^"]*"[^>]*>([^<]+)</a>', item)
                file_name = name_match.group(1).strip() if name_match else ''

                size_match = re.search(r'<span class="file-size">\[([^\]]+)\]</span>', item)
                size = size_match.group(1).strip() if size_match else ''

                if file_name and size:
                    play_title = f"{file_name} [{size}]"
                elif file_name:
                    play_title = file_name
                elif size:
                    play_title = f"磁力 [{size}]"
                else:
                    play_title = f"磁力{len(mag_playlists)+1}"

                mag_playlists.append({
                    'title': play_title[:80],
                    'url': mag
                })

            # 兜底
            if not mag_playlists and unique_magnets:
                for i, mag in enumerate(unique_magnets):
                    mag_playlists.append({
                        'title': f'磁力{i+1}',
                        'url': mag
                    })

            # === 网盘链接（夸克网盘）===
            pan_links = re.findall(r'data-url="(https://pan\.quark\.cn/s/[^"]+)"', text)
            pan_list = []
            seen_pan = set()
            for pan in pan_links:
                if pan not in seen_pan:
                    seen_pan.add(pan)
                    pan_list.append(pan)

            # === 构建多播放源 ===
            play_from = []
            play_url = []

            # 1. 在线播放源（m3u8直链）- 优先
            for route_name, items in online_routes.items():
                episode_urls = []
                for idx, (ep_title, ep_url) in enumerate(items):
                    # 清理标题中的特殊字符，避免TVBox解析出错
                    clean_title = ep_title.replace('$', ' ').replace('#', ' ').replace('$$$', ' ')
                    episode_urls.append(f"{clean_title}${ep_url}")
                if episode_urls:
                    play_from.append(route_name)
                    play_url.append('#'.join(episode_urls))

            # 2. 磁力链接
            if mag_playlists:
                mag_play_url = '#'.join([f"{p['title'].replace('$', ' ')}${p['url']}" for p in mag_playlists])
                play_from.append('磁力')
                play_url.append(mag_play_url)

            # 3. 夸克网盘
            if pan_list:
                pan_play_url = '#'.join([f"夸克网盘{i+1}${url}" for i, url in enumerate(pan_list)])
                play_from.append('夸克网盘')
                play_url.append(pan_play_url)

            # 保底
            if not play_from:
                play_from = ['暂无播放源']
                play_url = [f'暂无${vid}']

            vod = {
                'vod_id': vid,
                'vod_name': title,
                'type_name': type_name,
                'vod_year': year,
                'vod_remarks': f"IMDB {meta.get('IMDB', '')}" if meta.get('IMDB') else '',
                'vod_actor': actors,
                'vod_director': director,
                'vod_content': desc,
                'vod_pic': poster,
                'vod_play_from': '$$$'.join(play_from),
                'vod_play_url': '$$$'.join(play_url),
            }

            return {'list': [vod]}
        except Exception as e:
            print(f'[Pomo] 解析详情出错: {e}')
            return {'list': []}

    def searchContent(self, key, quick, pg="1"):
        try:
            url = f'{self.host}/?keyword={quote(key)}'
            if int(pg) > 1:
                url = f'{self.host}/page/{pg}?keyword={quote(key)}'
            result = self._parse_list(url)
            result['page'] = pg
            result['pagecount'] = 9999
            result['limit'] = 16
            result['total'] = 999999
            return result
        except Exception as e:
            print(f'[Pomo] 搜索出错: {e}')
            return {'list': [], 'page': pg, 'pagecount': 1, 'limit': 16, 'total': 0}

    def playerContent(self, flag, id, vipFlags):
        """
        TVBox/OK影视播放逻辑：
        - m3u8/mp4/http直链: parse=0 直接播放（TVBox内置播放器支持）
        - 磁力链接: parse=0, jx=1 触发OK影视内置磁力解析（需配置磁力引擎）
        - 夸克网盘: parse=1 走外部网页解析
        """
        if not id:
            return {'parse': 0, 'url': '', 'header': ''}

        # m3u8直链 / mp4 / 其他http视频直链
        if id.startswith('http://') or id.startswith('https://'):
            # 判断是否是m3u8或mp4直链
            is_direct_video = any(id.endswith(ext) for ext in ['.m3u8', '.mp4', '.ts', '.flv', '.mkv'])
            if is_direct_video or 'm3u8' in id or 'mp4' in id:
                return {
                    'parse': 0,
                    'url': id,
                    'header': {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                        'Referer': 'https://pomo.mom/'
                    }
                }
            else:
                # 非视频直链（如夸克网盘）走外部解析
                return {
                    'parse': 1,
                    'url': id,
                    'header': ''
                }

        # 磁力链接
        if id.startswith('magnet:'):
            return {
                'parse': 0,
                'jx': 1,
                'url': id,
                'header': ''
            }

        # ed2k / thunder 等其他协议
        if id.startswith('ed2k:') or id.startswith('thunder:'):
            return {
                'parse': 0,
                'jx': 1,
                'url': id,
                'header': ''
            }

        # 默认
        return {
            'parse': 0,
            'url': id,
            'header': ''
        }

    def localProxy(self, param):
        """
        本地代理：可用于代理m3u8/ts请求，解决跨域或防盗链问题
        """
        try:
            if param.get('type') == 'proxy':
                url = param.get('url', '')
                if url:
                    resp = self.fetch(url, headers=self.headers)
                    return resp
        except Exception as e:
            print(f'[Pomo] 代理出错: {e}')
        return None

    def _get_text(self, resp):
        """兼容不同返回类型获取文本"""
        if hasattr(resp, 'text'):
            return resp.text
        elif hasattr(resp, '_data'):
            return resp._data.decode('utf-8') if hasattr(resp._data, 'decode') else str(resp._data)
        else:
            return resp.decode('utf-8') if hasattr(resp, 'decode') else str(resp)
