# coding=utf-8
"""
目标站: 奇客影院 (qikeyingyuan.msfqs.com)
站点: http://qikeyingyuan.msfqs.com/
海洋CMS架构 - 完整爬虫实现
"""
import re
import sys
import json
import urllib.parse
from bs4 import BeautifulSoup

sys.path.append('..')
from base.spider import Spider


class Spider(Spider):
    def init(self, extend=""):
        self.site_url = "http://qikeyingyuan.msfqs.com"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': self.site_url,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'
        }
        self.categories = self._fetch_categories()

    def _fetch_categories(self):
        """获取网站分类"""
        try:
            resp = self.fetch(self.site_url, headers=self.headers)
            if not resp:
                return self._default_categories()
            
            soup = BeautifulSoup(resp.text, 'html.parser')
            categories = []
            seen = set()
            
            # 从导航菜单获取分类
            nav_links = soup.select('.new-dy-nav-left a')
            if not nav_links:
                nav_links = soup.select('header a[href*="/msfqry/"]')
            
            for a in nav_links:
                href = a.get('href', '')
                # 匹配分类链接格式: /msfqry/1.html, /msfqry/2.html 等
                match = re.search(r'/msfqry/(\d+)\.html', href)
                if not match:
                    continue
                tid = match.group(1)
                name = a.get_text(strip=True)
                if not name or tid in seen or name in ['首页', '更多']:
                    continue
                seen.add(tid)
                categories.append({"type_id": tid, "type_name": name})
            
            if categories:
                return categories
        except Exception as e:
            print(f"[奇客影院] 获取分类失败: {e}")
        
        return self._default_categories()

    def _default_categories(self):
        """默认分类"""
        return [
            {"type_id": "1", "type_name": "电影"},
            {"type_id": "2", "type_name": "连续剧"},
            {"type_id": "3", "type_name": "综艺"},
            {"type_id": "4", "type_name": "动漫"},
            {"type_id": "20", "type_name": "短剧"},
        ]

    def _fix_url(self, url):
        """修复URL"""
        if not url:
            return ""
        if url.startswith("//"):
            return "http:" + url
        if not url.startswith("http"):
            return urllib.parse.urljoin(self.site_url + "/", url)
        return url

    def _parse_video_list(self, html):
        """解析视频列表"""
        if not html:
            return []
        
        soup = BeautifulSoup(html, 'html.parser')
        results = []
        seen = set()
        
        # 查找所有视频链接 - 奇客影院使用 /msfqde/ 格式
        for a in soup.select('a[href*="/msfqde/"]'):
            href = a.get('href', '')
            vod_id = re.search(r'/msfqde/(\d+)\.html', href)
            if not vod_id:
                continue
            vid = vod_id.group(1)
            if vid in seen:
                continue
            seen.add(vid)
            
            # 获取标题
            title = a.get('title', '')
            if not title:
                title = a.get_text(strip=True)
            if not title:
                continue
            
            # 获取图片
            img = a.select_one('img')
            pic = ''
            if img:
                pic = img.get('data-original') or img.get('src') or ''
            if not pic:
                # 尝试从父级查找图片
                parent = a.parent
                for _ in range(3):
                    if parent:
                        img_in_parent = parent.select_one('img')
                        if img_in_parent:
                            pic = img_in_parent.get('data-original') or img_in_parent.get('src') or ''
                            if pic:
                                break
                        parent = parent.parent
            
            # 获取备注（如"已完结"）
            remark = ''
            parent = a.parent
            for _ in range(3):
                if parent:
                    note = parent.select_one('.pic-text, .remarks, .vod-remarks, .text-muted')
                    if note:
                        remark = note.get_text(strip=True)
                        break
                    parent = parent.parent
            
            results.append({
                "vod_id": vid,
                "vod_name": title.strip(),
                "vod_pic": self._fix_url(pic),
                "vod_remarks": remark
            })
        
        return results

    def homeContent(self, filter):
        """首页内容"""
        url = self.site_url + "/"
        resp = self.fetch(url, headers=self.headers)
        video_list = []
        if resp:
            video_list = self._parse_video_list(resp.text)
            video_list = video_list[:30]  # 取前30个
        
        # 添加分类过滤信息
        filters = {}
        for cat in self.categories:
            filters[cat["type_id"]] = []
        
        return {"class": self.categories, "list": video_list, "filters": filters}

    def homeVideoContent(self):
        return self.homeContent(False)

    def categoryContent(self, tid, pg, filter, extend):
        """分类内容"""
        page = int(pg) if pg else 1
        
        # 构建分类URL
        if page == 1:
            url = f"{self.site_url}/msfqry/{tid}.html"
        else:
            url = f"{self.site_url}/msfqry/{tid}-{page}.html"
        
        resp = self.fetch(url, headers=self.headers)
        if not resp:
            return {"list": [], "page": page, "pagecount": 1, "limit": 24, "total": 0}
        
        video_list = self._parse_video_list(resp.text)
        
        # 解析分页
        pagecount = page
        soup = BeautifulSoup(resp.text, 'html.parser')
        pagination = soup.select('.page a, .pagination a, .stui-page a')
        if pagination:
            nums = []
            for a in pagination:
                text = a.get_text(strip=True)
                if text.isdigit():
                    nums.append(int(text))
            if nums:
                pagecount = max(nums)
        
        return {
            "list": video_list,
            "page": page,
            "pagecount": pagecount,
            "limit": 24,
            "total": len(video_list) * pagecount
        }

    def detailContent(self, ids):
        """详情内容"""
        if not ids:
            return {"list": []}
        
        vod_id = ids[0]
        url = f"{self.site_url}/msfqde/{vod_id}.html"
        resp = self.fetch(url, headers=self.headers)
        if not resp:
            return {"list": []}
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # 获取标题
        title_elem = soup.select_one('h1, .title, .vod-title')
        vod_name = title_elem.get_text(strip=True) if title_elem else vod_id
        
        # 获取图片
        vod_pic = ''
        img_elem = soup.select_one('.stui-vodlist__thumb img, .vod-pic img, .detail-pic img')
        if img_elem:
            vod_pic = img_elem.get('data-original') or img_elem.get('src') or ''
            vod_pic = self._fix_url(vod_pic)
        
        # 获取简介
        vod_content = ''
        content_elem = soup.select_one('.vod-content, .detail-content, .desc, .stui-content__desc')
        if content_elem:
            vod_content = content_elem.get_text(' ', strip=True)
        
        # 获取演员
        vod_actor = ''
        actor_elem = soup.select_one('.vod-actor, .actor, .stui-content__actor')
        if actor_elem:
            vod_actor = actor_elem.get_text(strip=True)
        
        # 获取导演
        vod_director = ''
        director_elem = soup.select_one('.vod-director, .director, .stui-content__director')
        if director_elem:
            vod_director = director_elem.get_text(strip=True)
        
        # 获取年份
        vod_year = ''
        year_elem = soup.select_one('.vod-year, .year, .stui-content__year')
        if year_elem:
            vod_year = year_elem.get_text(strip=True)
        
        # 解析播放列表
        play_from_list = []
        play_url_list = []
        
        # 寻找播放列表
        play_blocks = soup.select('.stui-vodlist__text, .play-list, .vod-play-list, .episode-list, .playlist')
        if not play_blocks:
            play_blocks = soup.select('.stui-play__list, .ul.clearfix')
        
        if play_blocks:
            for idx, block in enumerate(play_blocks):
                line_name = f"线路{idx+1}"
                # 查找线路名称
                name_elem = block.select_one('.play-title, .line-name, .playlist-title, h4')
                if name_elem:
                    line_name = name_elem.get_text(strip=True)
                
                episodes = []
                for a in block.select('a'):
                    href = a.get('href', '')
                    if not href or 'javascript:' in href or '#' in href:
                        continue
                    # 检查是否是播放链接
                    if '/msfqde/' in href and '.html' in href:
                        # 这是详情页链接，不是播放链接
                        continue
                    ep_name = a.get_text(strip=True) or f"第{len(episodes)+1}集"
                    full_url = self._fix_url(href)
                    if full_url:
                        episodes.append(f"{ep_name}${full_url}")
                
                if episodes:
                    play_from_list.append(line_name)
                    play_url_list.append('#'.join(episodes))
        
        # 如果没有找到播放列表，尝试从详情页链接提取
        if not play_url_list:
            all_links = soup.select('a[href*="/msfqde/"]')
            play_links = []
            for a in all_links:
                href = a.get('href', '')
                if href and '/msfqde/' in href and '.html' in href:
                    # 过滤掉当前页面链接
                    if vod_id not in href:
                        play_links.append(a)
            
            if play_links:
                episodes = []
                for a in play_links[:20]:  # 限制数量
                    href = a.get('href', '')
                    ep_name = a.get_text(strip=True) or f"第{len(episodes)+1}集"
                    full_url = self._fix_url(href)
                    if full_url:
                        episodes.append(f"{ep_name}${full_url}")
                if episodes:
                    play_from_list.append('默认线路')
                    play_url_list.append('#'.join(episodes))
        
        vod_play_from = '$$$'.join(play_from_list) if play_from_list else '默认源'
        vod_play_url = '$$$'.join(play_url_list) if play_url_list else f"播放${vod_id}"
        
        result = [{
            "vod_id": vod_id,
            "vod_name": vod_name,
            "vod_pic": vod_pic,
            "vod_content": vod_content,
            "vod_actor": vod_actor,
            "vod_director": vod_director,
            "vod_area": "",
            "vod_year": vod_year,
            "vod_play_from": vod_play_from,
            "vod_play_url": vod_play_url
        }]
        
        return {"list": result}

    def searchContent(self, key, quick, pg="1"):
        """搜索内容"""
        page = int(pg) if pg else 1
        encoded_key = urllib.parse.quote(key)
        
        # 奇客影院的搜索URL格式
        url = f"{self.site_url}/search/{encoded_key}.html"
        if page > 1:
            # 如果有分页参数，尝试添加
            url = f"{self.site_url}/search/{encoded_key}-{page}.html"
        
        resp = self.fetch(url, headers=self.headers)
        if not resp:
            return {"list": [], "page": page, "pagecount": 1}
        
        video_list = self._parse_video_list(resp.text)
        return {"list": video_list, "page": page, "pagecount": 1}

    def playerContent(self, flag, id, vipFlags):
        """
        播放解析 - 针对奇客影院的播放链接
        """
        play_url = self._fix_url(id)
        
        # 如果已经是直链，直接返回
        if re.search(r'\.(m3u8|mp4|flv)(\?|$)', play_url, re.I):
            return {"parse": 0, "url": play_url, "header": self.headers}
        
        headers = dict(self.headers)
        headers['Referer'] = self.site_url + '/'
        max_depth = 8
        
        def _extract(url, depth):
            if depth > max_depth:
                return None
            if re.search(r'\.(m3u8|mp4|flv)(\?|$)', url, re.I):
                return url
            
            resp = self.fetch(url, headers=headers)
            if not resp:
                return None
            html = resp.text
            
            # 1. 查找 iframe
            iframe = re.search(r'<iframe[^>]+src="([^"]+)"', html)
            if iframe:
                iframe_url = self._fix_url(iframe.group(1))
                if iframe_url != url:
                    return _extract(iframe_url, depth + 1)
            
            # 2. 查找 video 标签
            video_src = re.search(r'<video[^>]+src="([^"]+)"', html)
            if video_src:
                return video_src.group(1)
            
            # 3. 查找 source 标签
            source_src = re.search(r'<source[^>]+src="([^"]+)"', html)
            if source_src:
                return source_src.group(1)
            
            # 4. 直接匹配 m3u8
            m3u8 = re.search(r'(https?://[^\s"\']+\.m3u8[^\s"\']*)', html)
            if m3u8:
                return m3u8.group(1)
            
            # 5. 直接匹配 mp4
            mp4 = re.search(r'(https?://[^\s"\']+\.mp4[^\s"\']*)', html)
            if mp4:
                return mp4.group(1)
            
            # 6. 匹配各种播放变量
            var_patterns = [
                r'var\s+playurl\s*=\s*["\']([^"\']+)["\']',
                r'var\s+url\s*=\s*["\']([^"\']+)["\']',
                r'var\s+video\s*=\s*["\']([^"\']+)["\']',
                r'var\s+src\s*=\s*["\']([^"\']+)["\']',
                r'var\s+play_url\s*=\s*["\']([^"\']+)["\']',
                r'var\s+v_url\s*=\s*["\']([^"\']+)["\']',
            ]
            for pat in var_patterns:
                match = re.search(pat, html, re.I)
                if match:
                    p = match.group(1)
                    if re.search(r'\.(m3u8|mp4|flv)', p, re.I):
                        return p
            
            return None
        
        final_url = _extract(play_url, 0)
        
        if final_url:
            final_url = self._fix_url(final_url)
            if re.search(r'\.(m3u8|mp4|flv)', final_url, re.I):
                return {"parse": 0, "url": final_url, "header": headers}
            else:
                return self.playerContent(flag, final_url, vipFlags)
        
        # 兜底：交给客户端解析
        return {"parse": 1, "url": play_url, "header": headers}