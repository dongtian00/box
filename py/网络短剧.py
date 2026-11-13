# coding=utf-8
# QQ群：807916734
"""
目标站: 网络短剧 (https://535623.com)
SeaCMS 短剧模板，结构与爱短剧一致：
  分类: /dj/{tid}.html        分页: /dj/{tid}-{page}.html
  详情: /djok/{vod_id}.html
  搜索: /search.php?searchword=xxx
"""
import re
import sys
import json
import urllib.parse
from bs4 import BeautifulSoup

sys.path.append('..')
from base.spider import Spider


class Spider(Spider):
    # 每页大小（与站点一致）
    PAGE_SIZE = 30

    def init(self, extend=""):
        self.site_url = "https://535623.com"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': self.site_url + '/',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        }
        self.categories = [
            {"type_id": "1", "type_name": "重生"},
            {"type_id": "2", "type_name": "穿越"},
            {"type_id": "3", "type_name": "爽剧"},
            {"type_id": "4", "type_name": "言情"},
            {"type_id": "5", "type_name": "都市"},
            {"type_id": "6", "type_name": "古装"},
            {"type_id": "7", "type_name": "悬疑"},
            {"type_id": "8", "type_name": "剧情"},
        ]

    # ---------- 工具方法 ----------

    def _abs_url(self, href):
        """相对路径转绝对路径"""
        if not href or href.startswith(('http://', 'https://')):
            return href
        if href.startswith('//'):
            return 'https:' + href
        if href.startswith('/'):
            return self.site_url + href
        return self.site_url + '/' + href

    def _extract_m3u8(self, html):
        m = re.search(r'(https?://[^\s"\']+\.m3u8[^\s"\']*)', html)
        return m.group(1) if m else None

    def _extract_mp4(self, html):
        m = re.search(r'(https?://[^\s"\']+\.mp4[^\s"\']*)', html)
        return m.group(1) if m else None

    def _extract_video_src(self, html):
        m = re.search(r'<video[^>]+src="([^"]+)"', html)
        return m.group(1) if m else None

    def _parse_video_list(self, soup, max_count=0):
        """通用视频列表解析器（兼容 fed-list-item / fed-list-pics 两种结构）"""
        video_list = []
        items = soup.select('li.fed-list-item') or soup.select('.fed-list-info li')

        # 退化：直接拿 .fed-list-pics 节点
        if not items:
            for link in soup.select('.fed-list-pics'):
                vod_id = self._extract_vod_id(link.get('href', ''))
                if not vod_id:
                    continue
                title = link.get('title', '')
                pic = link.get('data-original', '')
                remark_elem = link.select_one('.fed-list-remarks')
                video_list.append({
                    "vod_id": vod_id,
                    "vod_name": title,
                    "vod_pic": self._abs_url(pic),
                    "vod_remarks": remark_elem.get_text(strip=True) if remark_elem else '',
                })
                if max_count > 0 and len(video_list) >= max_count:
                    break
            return video_list

        for item in items:
            link = item.select_one('a.fed-list-pics') or item.select_one('a[href*="/djok/"]')
            if not link:
                continue
            vod_id = self._extract_vod_id(link.get('href', ''))
            if not vod_id:
                continue

            title = link.get('title', '')
            if not title:
                title_elem = item.select_one('.fed-list-title a') or item.select_one('a[title]')
                if title_elem:
                    title = title_elem.get('title', '') or title_elem.get_text(strip=True)
            if not title:
                continue

            pic = link.get('data-original', '')
            if not pic:
                img = link.select_one('img')
                if img:
                    pic = img.get('data-original', '') or img.get('src', '')

            remark_elem = link.select_one('.fed-list-remarks')
            remark = remark_elem.get_text(strip=True) if remark_elem else ''

            video_list.append({
                "vod_id": vod_id,
                "vod_name": title,
                "vod_pic": self._abs_url(pic),
                "vod_remarks": remark,
            })
            if max_count > 0 and len(video_list) >= max_count:
                break
        return video_list

    @staticmethod
    def _extract_vod_id(href):
        m = re.search(r'/djok/(\d+)\.html', href)
        return m.group(1) if m else None

    # ---------- 标准接口 ----------

    def homeContent(self, filter):
        url = self.site_url + "/"
        resp = self.fetch(url, headers=self.headers)
        video_list = []
        if resp:
            soup = BeautifulSoup(resp.text, 'html.parser')
            video_list = self._parse_video_list(soup, max_count=36)
        return {"class": self.categories, "list": video_list, "filters": {}}

    def homeVideoContent(self):
        return self.homeContent(False)

    def categoryContent(self, tid, pg, filter, extend):
        try:
            page = int(pg) if pg else 1
        except (TypeError, ValueError):
            page = 1

        url = (f"{self.site_url}/dj/{tid}.html" if page <= 1
               else f"{self.site_url}/dj/{tid}-{page}.html")
        resp = self.fetch(url, headers=self.headers)
        if not resp:
            return {"list": [], "page": page, "pagecount": 1,
                    "limit": self.PAGE_SIZE, "total": 0}

        soup = BeautifulSoup(resp.text, 'html.parser')
        video_list = self._parse_video_list(soup)

        # 解析分页
        pagecount = page
        for a in soup.select('.fed-page-info a') or soup.select('.fed-page a'):
            text = a.get_text(strip=True)
            if text.isdigit():
                pagecount = max(pagecount, int(text))

        total = 0
        total_match = re.search(r'共\s*(\d+)\s*个影片', soup.get_text())
        if total_match:
            total = int(total_match.group(1))
            pagecount = max(pagecount, (total + self.PAGE_SIZE - 1) // self.PAGE_SIZE)

        return {
            "list": video_list,
            "page": page,
            "pagecount": pagecount,
            "limit": self.PAGE_SIZE,
            "total": total if total > 0 else len(video_list) * pagecount,
        }

    def detailContent(self, ids):
        if not ids:
            return {"list": []}
        vod_id = ids[0]
        url = f"{self.site_url}/djok/{vod_id}.html"
        resp = self.fetch(url, headers=self.headers)
        if not resp:
            return {"list": []}

        soup = BeautifulSoup(resp.text, 'html.parser')

        # 标题
        vod_name = vod_id
        title_elem = (soup.select_one('.fed-deta-content h1 a')
                      or soup.select_one('h1 a')
                      or soup.select_one('h1'))
        if title_elem:
            vod_name = title_elem.get('title', '') or title_elem.get_text(strip=True)
        if vod_name == vod_id:
            og = soup.select_one('meta[property="og:title"]')
            if og:
                vod_name = og.get('content', vod_id)

        # 封面
        vod_pic = ''
        og = soup.select_one('meta[property="og:image"]')
        if og:
            vod_pic = og.get('content', '')
        if not vod_pic:
            img = (soup.select_one('.fed-deta-images img')
                   or soup.select_one('.fed-list-pics img'))
            if img:
                vod_pic = img.get('data-original', '') or img.get('src', '')

        # 简介
        vod_content = ''
        desc = soup.select_one('.fed-deta-content .fed-part-esan') or soup.select_one('.fed-part-esan')
        if desc:
            vod_content = desc.get_text(' ', strip=True)
        if not vod_content:
            og = soup.select_one('meta[property="og:description"]')
            if og:
                vod_content = og.get('content', '')

        # 基本信息（li 文本匹配）
        vod_actor = vod_director = vod_area = vod_year = ''
        info_items = soup.select('.fed-deta-content li') or soup.select('dl.fed-deta-info dd li')
        for li in info_items:
            text = li.get_text(strip=True)
            if '主演' in text:
                vod_actor = self._field(text, '主演')
            elif '导演' in text:
                vod_director = self._field(text, '导演')
            elif '地区' in text:
                vod_area = self._field(text, '地区')
            elif '年份' in text:
                vod_year = self._field(text, '年份')

        # og:video:* 降级补齐
        if not vod_area:
            og = soup.select_one('meta[property="og:video:area"]')
            if og:
                vod_area = og.get('content', '')
        if not vod_director:
            og = soup.select_one('meta[property="og:video:director"]')
            if og:
                vod_director = og.get('content', '')
        if not vod_actor:
            og = soup.select_one('meta[property="og:video:actor"]')
            if og:
                vod_actor = og.get('content', '')

        # 播放列表
        play_from_list, play_url_list = self._parse_playlists(soup)

        vod_play_from = '$$$'.join(play_from_list) if play_from_list else '默认源'
        vod_play_url = '$$$'.join(play_url_list) if play_url_list else f"播放${vod_id}"

        return {"list": [{
            "vod_id": vod_id,
            "vod_name": vod_name,
            "vod_pic": self._abs_url(vod_pic),
            "vod_content": vod_content,
            "vod_actor": vod_actor,
            "vod_director": vod_director,
            "vod_area": vod_area,
            "vod_year": vod_year,
            "vod_play_from": vod_play_from,
            "vod_play_url": vod_play_url,
        }]}

    def _field(self, text, key):
        """从 '主演：xxx' 或 '主演xxx' 提取值"""
        if '：' in text:
            return text.split('：', 1)[-1].strip()
        return text.replace(key, '').strip()

    def _parse_playlists(self, soup):
        """解析播放源 + 剧集，依次尝试：tab 锚点 / 区块对应 / 直接链接"""
        play_from_list, play_url_list = [], []

        # 方式1：tab 锚点 + 播放区块
        tab_links = soup.select('.fed-tabs a') or soup.select('a[href*="#playlist"]')
        line_names = []
        for a in tab_links:
            name = a.get_text(strip=True)
            if name and name not in ('↑↓ 排序',):
                line_names.append(name)

        play_blocks = soup.select('.fed-play-list') or soup.select('.fed-tabs-list')
        if play_blocks:
            for idx, block in enumerate(play_blocks):
                line_name = line_names[idx] if idx < len(line_names) else f"线路{idx + 1}"
                episodes = self._parse_episodes(block)
                if episodes:
                    play_from_list.append(line_name)
                    play_url_list.append('#'.join(episodes))
            if play_url_list:
                return play_from_list, play_url_list

        # 方式2：锚点 ID 匹配
        tab_anchors = soup.select('.fed-tabs a')
        tab_map = {}
        for a in tab_anchors:
            href = a.get('href', '')
            name = a.get_text(strip=True)
            if name and name != '↑↓ 排序' and '#playlist' in href:
                tab_map[href.split('#')[-1]] = name
        if tab_map:
            for anchor, line_name in tab_map.items():
                block = soup.select_one(f'#{anchor}') or soup.select_one(f'[id="{anchor}"]')
                if not block:
                    continue
                episodes = self._parse_episodes(block)
                if episodes:
                    play_from_list.append(line_name)
                    play_url_list.append('#'.join(episodes))
            if play_url_list:
                return play_from_list, play_url_list

        # 方式3：直接抓 /play/ 链接
        for a in soup.select('a[href*="/play/"]'):
            href = a.get('href', '')
            ep_name = a.get_text(strip=True)
            if not href or not ep_name:
                continue
            episodes = [f"{ep_name}${self._abs_url(href)}"]
            play_from_list.append('默认线路')
            play_url_list.append('#'.join(episodes))
            break  # 只需要一组兜底

        return play_from_list, play_url_list

    def _parse_episodes(self, block):
        """从一个播放区块里抓所有集"""
        episodes = []
        for a in block.select('a'):
            href = a.get('href', '')
            ep_name = a.get_text(strip=True)
            if not href or 'javascript:' in href or href.startswith('#'):
                continue
            if not ep_name:
                continue
            episodes.append(f"{ep_name}${self._abs_url(href)}")
        return episodes

    def searchContent(self, key, quick, pg="1"):
        try:
            page = int(pg) if pg else 1
        except (TypeError, ValueError):
            page = 1
        encoded_key = urllib.parse.quote(key)
        url = f"{self.site_url}/search.php?searchword={encoded_key}"
        if page > 1:
            url += f"&page={page}"

        resp = self.fetch(url, headers=self.headers)
        # 第一次失败或页面还在加载，降级用 POST
        if (not resp) or ('页面加载中' in resp.text):
            resp = self.fetch(url, headers={
                **self.headers,
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-Requested-With': 'XMLHttpRequest',
            }, method='POST', data=f"searchword={encoded_key}&page={page}")

        if not resp:
            return {"list": [], "page": page, "pagecount": 1}

        soup = BeautifulSoup(resp.text, 'html.parser')
        video_list = self._parse_video_list(soup)
        return {"list": video_list, "page": page, "pagecount": 1}

    def playerContent(self, flag, vid, vipFlags):
        # 构造播放页 URL（注意参数改名 vid，避免遮蔽内置 id()）
        if vid.startswith(('http://', 'https://')):
            play_url = vid
        elif vid.startswith('/'):
            play_url = self.site_url + vid
        elif re.match(r'^\d+-\d+-\d+$', vid):
            # 已含集数：id-id-id
            play_url = f"{self.site_url}/play/{vid}.html"
        elif re.match(r'^\d+$', vid):
            # 仅 vod_id，默认第 1 集第 1 个源
            play_url = f"{self.site_url}/play/{vid}-1-1.html"
        else:
            play_url = f"{self.site_url}/play/{vid}.html"

        resp = self.fetch(play_url, headers=self.headers)
        if not resp:
            return {"parse": 1, "url": play_url, "header": self.headers}

        html = resp.text

        # 方式1：var now = "..."
        m = re.search(r'var\s+now\s*=\s*"([^"]+)"', html)
        if m and m.group(1).startswith(('http://', 'https://')):
            return {"parse": 0, "url": m.group(1), "header": self.headers}

        # 方式2：var player_aaaa = {...}
        marker = "var player_aaaa="
        if marker in html:
            try:
                data_str = html.split(marker, 1)[1].split('\n', 1)[0].strip().rstrip(';')
                data = json.loads(data_str)
                if data.get('url'):
                    return {"parse": 0, "url": data['url'], "header": self.headers}
            except Exception as e:
                print(f"[player_aaaa] 解析失败: {e}")

        # 方式3：iframe 嵌套（递归 1 层）
        m_iframe = re.search(r'<iframe[^>]+src="([^"]+)"', html)
        if m_iframe:
            iframe_url = self._abs_url(m_iframe.group(1))
            iframe_resp = self.fetch(iframe_url, headers=self.headers)
            if iframe_resp:
                iframe_html = iframe_resp.text
                for hit in (self._extract_m3u8(iframe_html),
                            self._extract_video_src(iframe_html)):
                    if hit:
                        return {"parse": 0, "url": hit, "header": self.headers}
                # 嵌套 iframe
                m_nested = re.search(r'<iframe[^>]+src="([^"]+)"', iframe_html)
                if m_nested:
                    nested_url = self._abs_url(m_nested.group(1))
                    nested_resp = self.fetch(nested_url, headers=self.headers)
                    if nested_resp:
                        nested_html = nested_resp.text
                        m3u8 = self._extract_m3u8(nested_html)
                        if m3u8:
                            return {"parse": 0, "url": m3u8, "header": self.headers}

        # 方式4：直接搜 video src / m3u8 / mp4
        for hit in (self._extract_video_src(html),
                    self._extract_m3u8(html),
                    self._extract_mp4(html)):
            if hit:
                return {"parse": 0, "url": hit, "header": self.headers}

        # 兜底：交给播放器解析
        return {"parse": 1, "url": play_url, "header": self.headers}
