#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kanjuww.com 爬虫 - TVBox/影视仓 Spider 插件
支持分类浏览、搜索、详情获取、播放链接解析
选集正序排列，海报封面补充，m3u8 链接 base64 解码
"""

import re
import json
import base64
import logging
import urllib.parse
import os
import sys
import requests
from bs4 import BeautifulSoup

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
try:
    from base.spider import Spider as BaseSpider
except ImportError:
    BaseSpider = object

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class Spider(BaseSpider):
    """kanjuww.com 爬虫"""

    BASE_URL = "https://www.kanjuww.com"

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 12; SM-S908U) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://www.kanjuww.com/",
    }

    # 分类：键为网站分类ID，对应 /list/?{id}.html
    CATEGORY_MAP = {
        "1": {"name": "电影"},
        "2": {"name": "电视剧"},
        "3": {"name": "综艺"},
        "4": {"name": "动漫"},
        "5": {"name": "动作片"},
        "6": {"name": "爱情片"},
        "7": {"name": "科幻片"},
        "8": {"name": "恐怖片"},
        "9": {"name": "战争片"},
        "10": {"name": "喜剧片"},
        "11": {"name": "纪录片"},
        "12": {"name": "剧情片"},
        "13": {"name": "国产剧"},
        "14": {"name": "港剧"},
        "15": {"name": "欧美剧"},
        "16": {"name": "日剧"},
        "28": {"name": "奇幻片"},
        "29": {"name": "其他剧"},
        "30": {"name": "台剧"},
        "31": {"name": "韩剧"},
        "60": {"name": "体育"},
        "67": {"name": "短剧"},
    }

    def __init__(self):
        try:
            super().__init__()
        except Exception:
            pass
        self.session = requests.Session()
        self.session.verify = False
        self.session.headers.update(self.HEADERS)

    def init(self, extend):
        pass

    def getName(self):
        return "kanjuww影视"

    def _parse_ext(self, ext):
        """解析ext参数，兼容dict和JSON字符串"""
        if not ext:
            return {}
        if isinstance(ext, dict):
            return ext
        if isinstance(ext, str):
            try:
                return json.loads(ext)
            except Exception:
                return {}
        return {}

    def _get(self, url):
        try:
            resp = self.session.get(url, timeout=30)
            resp.encoding = "utf-8"
            return resp
        except Exception as e:
            logger.error(f"请求失败 {url}: {e}")
            return None

    def _fix_url(self, url):
        """将相对URL转为绝对URL，过滤占位图"""
        if not url:
            return ''
        # 过滤懒加载占位图
        if 'load.png' in url or 'loading' in url or 'lazyload' in url:
            return ''
        url = url.strip()
        if url.startswith('http://') or url.startswith('https://'):
            return url
        if url.startswith('//'):
            return 'https:' + url
        if url.startswith('/'):
            return self.BASE_URL + url
        # 处理 ../ 开头的相对路径
        url = re.sub(r'^(\.\./)+', '', url)
        return self.BASE_URL + '/' + url

    # ==================== 首页 ====================
    def homeContent(self, filter=False):
        try:
            url = f"{self.BASE_URL}/"
            resp = self._get(url)
            if not resp:
                return {}

            classes = [{"type_id": cid, "type_name": info["name"]}
                       for cid, info in self.CATEGORY_MAP.items()]

            home_list = self._parse_video_list(resp.text)

            return {
                "class": classes,
                "filters": self._get_filters(),
                "list": home_list,
            }
        except Exception as e:
            logger.error(f"获取首页失败: {e}")
            return {}

    def homeVideoContent(self):
        home = self.homeContent()
        return {"list": home.get("list", [])}

    # ==================== 筛选 ====================
    def _get_filters(self):
        """筛选配置：该站以分类ID本身作为筛选维度，无额外URL参数筛选"""
        filters = {}
        # 地区筛选
        area_values = [
            {"n": "全部", "v": ""},
            {"n": "大陆", "v": "大陆"}, {"n": "香港", "v": "香港"},
            {"n": "台湾", "v": "台湾"}, {"n": "美国", "v": "美国"},
            {"n": "法国", "v": "法国"}, {"n": "英国", "v": "英国"},
            {"n": "日本", "v": "日本"}, {"n": "韩国", "v": "韩国"},
            {"n": "德国", "v": "德国"}, {"n": "泰国", "v": "泰国"},
            {"n": "印度", "v": "印度"}, {"n": "其他", "v": "其他"},
        ]
        # 年份筛选
        year_values = [{"n": "全部", "v": ""}]
        for y in range(2026, 1999, -1):
            year_values.append({"n": str(y), "v": str(y)})

        for cate_id in self.CATEGORY_MAP:
            filters[cate_id] = [
                {"key": "area", "name": "地区", "value": area_values},
                {"key": "year", "name": "年份", "value": year_values},
            ]
        return filters

    # ==================== 分类 ====================
    def categoryContent(self, tid, pg, filter, ext):
        try:
            page = int(pg) if pg else 1
            type_id = str(tid)

            if type_id not in self.CATEGORY_MAP:
                return {"list": [], "page": page, "pagecount": 1, "limit": 20, "total": 0}

            ext_dict = self._parse_ext(ext)
            area_filter = ext_dict.get('area', '')
            year_filter = ext_dict.get('year', '')

            # 分类URL: /list/?{id}.html 或 /list/?{id}-{page}.html
            if page > 1:
                url = f"{self.BASE_URL}/list/?{type_id}-{page}.html"
            else:
                url = f"{self.BASE_URL}/list/?{type_id}.html"

            resp = self._get(url)
            if not resp:
                return {"list": [], "page": page, "pagecount": 1, "limit": 20, "total": 0}

            videos = self._parse_video_list(resp.text)
            # 如有筛选条件，在内存中过滤
            if area_filter:
                videos = [v for v in videos if area_filter in v.get('vod_remarks', '')]
            if year_filter:
                videos = [v for v in videos if year_filter in v.get('vod_remarks', '')]

            pagecount = self._parse_total_pages(resp.text, type_id)

            return {
                "list": videos,
                "page": page,
                "pagecount": pagecount,
                "limit": 20,
                "total": len(videos) * pagecount if pagecount else len(videos),
            }
        except Exception as e:
            logger.error(f"获取分类内容失败: {e}")
            return {"list": [], "page": 1, "pagecount": 1, "limit": 20, "total": 0}

    def _parse_total_pages(self, html, type_id):
        """解析总页数，从分页链接中提取最大页码"""
        # 匹配 /list/?{id}-{page}.html 格式的分页链接
        pattern = rf'/list/\?{re.escape(type_id)}-(\d+)\.html'
        matches = re.findall(pattern, html)
        if matches:
            return max(int(m) for m in matches)
        # 兜底：匹配通用分页
        m = re.search(r'class="num"[^>]*>\s*(\d+)\s*/\s*(\d+)', html)
        if m:
            return int(m.group(2))
        return 1

    def _parse_video_list(self, html):
        """解析视频列表（首页/分类/搜索通用）
        卡片: a.myui-vodlist__thumb (含 data-original, title, href)
        """
        videos = []
        soup = BeautifulSoup(html, 'html.parser')

        # 匹配 myui-vodlist__thumb 类的链接
        items = soup.find_all('a', class_=re.compile(r'vodlist__thumb'))
        if not items:
            items = soup.find_all('a', class_=re.compile(r'myui-vodlist__thumb'))

        seen_ids = set()
        for item in items:
            href = item.get('href', '')
            if not href:
                continue

            # 详情页URL: /detail/?{id}.html
            vid_match = re.search(r'/detail/\?(\d+)\.html', href)
            if not vid_match:
                continue
            vid_id = vid_match.group(1)
            if vid_id in seen_ids:
                continue
            seen_ids.add(vid_id)

            title = item.get('title', '')
            # 从 <img> 标签获取海报，优先 data-original（懒加载真实地址）
            poster = ''
            img = item.find('img')
            if img:
                poster = img.get('data-original', '') or img.get('src', '')
            # 兜底1：从 <a> 标签的 data-original 获取
            if not poster:
                poster = item.get('data-original', '')
            # 兜底2：从 style 的 background:url(...) 提取背景图
            if not poster:
                style = item.get('style', '')
                bg_match = re.search(r'background:\s*url\(["\']?([^"\')]+)["\']?\)', style)
                if bg_match:
                    poster = bg_match.group(1)
            # 转为绝对URL，过滤占位图
            poster = self._fix_url(poster)
            if not title:
                if img:
                    title = img.get('alt', '') or item.get('title', '')

            # 集数/状态备注: span.pic-text
            remark_tag = item.find(class_=re.compile(r'pic-text|pic_tag'))
            remarks = remark_tag.get_text(strip=True) if remark_tag else ''

            # 年份: span.pic-tag
            year_tag = item.find(class_=re.compile(r'pic-tag'))
            year = year_tag.get_text(strip=True) if year_tag else ''

            # 组合备注
            if year and remarks:
                remarks = f"{year} {remarks}"
            elif year:
                remarks = year

            if title:
                videos.append({
                    "vod_id": vid_id,
                    "vod_name": title,
                    "vod_pic": poster,
                    "vod_remarks": remarks,
                })
        return videos

    # ==================== 详情 ====================
    def detailContent(self, ids):
        try:
            vod_id = ids[0] if isinstance(ids, list) else str(ids)
            url = f"{self.BASE_URL}/detail/?{vod_id}.html"
            resp = self._get(url)
            if not resp:
                return {"list": []}

            html = resp.text
            soup = BeautifulSoup(html, 'html.parser')

            # 标题: h1.title 内文本（去除 font 标签中的集数信息）
            title = ''
            h1 = soup.find('h1', class_=re.compile(r'title'))
            if h1:
                # 取第一个文本节点，排除 font 标签内容
                for content in h1.contents:
                    if isinstance(content, str) and content.strip():
                        title = content.strip()
                        break
                if not title:
                    title = h1.get_text(strip=True)
            if not title:
                h1 = soup.find('h1')
                if h1:
                    title = h1.get_text(strip=True)

            # 海报: div.myui-content__thumb 内 img[data-original]
            poster = ''
            thumb_box = soup.find(class_=re.compile(r'content__thumb'))
            if thumb_box:
                img = thumb_box.find('img')
                if img:
                    poster = img.get('data-original', '') or img.get('src', '')
            # 转为绝对URL，过滤占位图
            poster = self._fix_url(poster)

            # 评分
            score = ''

            # 信息: p.data 列表，含 span.text-muted 标签
            year = area = type_name = actor = director = content = remarks = ''
            data_ps = soup.find_all('p', class_=re.compile(r'data'))
            for p in data_ps:
                labels = p.find_all('span', class_=re.compile(r'text-muted'))
                for idx, label_tag in enumerate(labels):
                    label = label_tag.get_text(strip=True)
                    nxt = labels[idx + 1] if idx + 1 < len(labels) else None
                    val = ''
                    for sib in label_tag.next_siblings:
                        if sib is nxt:
                            break
                        if hasattr(sib, 'get_text'):
                            t = sib.get_text(strip=True)
                        else:
                            t = str(sib).strip()
                        if t and t != '&nbsp;':
                            val += t
                    val = val.strip().replace('\xa0', '').strip()
                    if not val:
                        continue

                    if label.startswith('类型') or label.startswith('分类'):
                        type_name = val
                    elif label.startswith('地区'):
                        area = val
                    elif label.startswith('年份'):
                        year_match = re.search(r'(\d{4})', val)
                        year = year_match.group(1) if year_match else val
                    elif label.startswith('主演'):
                        actor = val
                    elif label.startswith('导演'):
                        director = val
                    elif label.startswith('更新') or label.startswith('状态'):
                        remarks = val
                    elif label.startswith('评分'):
                        score = val

            # 评分兜底：从 pic-tag2 中提取
            if not score:
                pgz = soup.find('div', class_='pgz')
                if pgz:
                    score_text = pgz.get_text(strip=True)
                    score_match = re.search(r'([\d.]+)', score_text)
                    if score_match:
                        score = score_match.group(1)

            # 简介: p.desc 或隐藏的 p.data
            desc_tag = soup.find('p', class_=re.compile(r'desc'))
            if desc_tag:
                content = desc_tag.get_text(strip=True)
            if not content:
                # 兜底：查找隐藏的包含长文本的 data 段
                for p in data_ps:
                    text = p.get_text(strip=True)
                    if len(text) > 50:
                        content = text
                        break
            if content:
                # 清理简介尾部广告语
                content = re.sub(r'(本页底部.*?相关推荐影片。?)', '', content)
                content = re.sub(r'(在线追剧就上.*)', '', content)
                content = content.strip()

            # 播放源和集数（正序）
            play_from_list, play_url_list = self._parse_play_sources(html, vod_id)

            vod_item = {
                "vod_id": vod_id,
                "vod_name": title,
                "vod_pic": poster,
                "type_name": type_name,
                "vod_year": year,
                "vod_area": area,
                "vod_remarks": remarks,
                "vod_actor": actor,
                "vod_director": director,
                "vod_content": content,
                "vod_score": score,
                "vod_play_from": '$$$'.join(play_from_list),
                "vod_play_url": '$$$'.join(play_url_list),
            }
            return {"list": [vod_item]}
        except Exception as e:
            logger.error(f"获取详情失败: {e}")
            return {"list": []}

    def _parse_play_sources(self, html, vod_id):
        """解析播放源和集数 - 正序排列
        结构: ul.nav-tabs > li > a[href="#playlist{sid}"] (源名)
              div.tab-pane#playlist{sid} > ul > a[href="/video/?{vid}-{sid}-{nid}.html"] (集数)
        """
        play_from_list = []
        play_url_list = []

        soup = BeautifulSoup(html, 'html.parser')

        # 源名映射: {sid: 源名}
        source_names = {}
        nav = soup.find('ul', class_=re.compile(r'nav-tabs'))
        if nav:
            for a in nav.find_all('a', href=True):
                m = re.search(r'#playlist(\w+)', a.get('href', ''))
                if m:
                    source_names[m.group(1)] = a.get_text(strip=True)

        # 每个 tab-pane 为一个源
        panes = soup.find_all('div', class_=re.compile(r'tab-pane'))
        if not panes:
            return self._parse_play_sources_fallback(html, vod_id)

        for pane in panes:
            pane_id = pane.get('id', '')
            sid_match = re.search(r'playlist(\w+)', pane_id)
            if not sid_match:
                continue
            sid = sid_match.group(1)
            from_name = source_names.get(sid, f"线路{sid}")

            ul = pane.find('ul')
            if not ul:
                # 兜底：直接在 pane 中查找
                ul = pane

            episodes = []
            seen_nid = set()
            for a in ul.find_all('a', href=True):
                href = a.get('href', '')
                m = re.search(r'/video/\?(\d+)-(\w+)-(\d+)\.html', href)
                if not m:
                    continue
                # 确认 vid 匹配
                if m.group(1) != vod_id:
                    continue
                nid = int(m.group(3))
                if nid in seen_nid:
                    continue
                seen_nid.add(nid)
                ep_name = a.get_text(strip=True) or f"第{nid + 1}集"
                full_url = href if href.startswith('http') else self.BASE_URL + href
                episodes.append((nid, ep_name, full_url))

            if not episodes:
                continue
            # 正序排列
            episodes = sorted(episodes, key=lambda x: x[0])

            play_from_list.append(from_name)
            urls = [f"{name}${u}" for _, name, u in episodes]
            play_url_list.append('#'.join(urls))

        if not play_from_list:
            return self._parse_play_sources_fallback(html, vod_id)
        return play_from_list, play_url_list

    def _parse_play_sources_fallback(self, html, vod_id):
        """兜底：从所有 video 链接按 sid 分组"""
        play_from_list = []
        play_url_list = []
        links = re.findall(r'/video/\?\d+-\w+-\d+\.html', html)
        sources = {}
        for link in links:
            m = re.match(r'/video/\?(\d+)-(\w+)-(\d+)\.html', link)
            if not m or m.group(1) != vod_id:
                continue
            sid = m.group(2)
            nid = int(m.group(3))
            sources.setdefault(sid, {})[nid] = link

        # 源名映射兜底
        source_names = {}
        for a in re.findall(r'href="#playlist(\w+)"[^>]*>(.*?)</a>', html, re.S):
            name = re.sub(r'<[^>]+>', '', a[1]).strip()
            if name:
                source_names[a[0]] = name

        for sid in sorted(sources.keys(), key=lambda x: int(x) if x.isdigit() else 0):
            eps = sources[sid]
            episodes = sorted(eps.items())
            from_name = source_names.get(sid, f"线路{sid}")
            play_from_list.append(from_name)
            urls = [f"第{nid + 1}集${self.BASE_URL}{link}" for nid, link in episodes]
            play_url_list.append('#'.join(urls))
        return play_from_list, play_url_list

    # ==================== 播放 ====================
    def playerContent(self, flag, id, vipFlags):
        """解析播放页 m3u8 链接
        播放页将 m3u8 地址 base64 编码存储在 var now=base64decode("...") 中
        """
        try:
            url = id
            # 兼容相对路径
            if url.startswith('/'):
                url = self.BASE_URL + url
            elif not url.startswith('http'):
                url = self.BASE_URL + '/video/?' + url

            resp = self._get(url)
            if not resp:
                return {}

            m3u8_url = self._extract_m3u8(resp.text)
            if not m3u8_url:
                return {}

            return {
                "parse": 0,
                "playUrl": "",
                "url": m3u8_url,
                "header": "",
            }
        except Exception as e:
            logger.error(f"解析播放失败: {e}")
            return {}

    def _extract_m3u8(self, html):
        """从播放页提取 m3u8 链接
        优先解析 var now=base64decode("...") 变量
        兜底：直接匹配 m3u8 URL
        """
        # 优先：解析 base64 编码的 m3u8 地址
        match = re.search(r'var\s+now\s*=\s*base64decode\(["\']([A-Za-z0-9+/=]+)["\']\)', html)
        if match:
            try:
                decoded = base64.b64decode(match.group(1)).decode('utf-8')
                if decoded.startswith('http') and '.m3u8' in decoded:
                    return decoded
            except Exception:
                pass

        # 兜底1：直接匹配 m3u8 URL
        m = re.search(r'(https?://[^"\'\s]+\.m3u8[^"\'\s]*)', html)
        if m:
            return m.group(1)

        # 兜底2：从 player_aaaa JSON 中提取
        match = re.search(r'player_aaaa\s*=\s*(\{[^<]+\})', html)
        if match:
            try:
                data = json.loads(match.group(1))
                m3u8_url = data.get('url', '')
                if m3u8_url:
                    return m3u8_url
            except Exception:
                pass

        return ''

    # ==================== 搜索 ====================
    def searchContent(self, key, quick, pg="1"):
        """搜索内容 - TVBox标准接口(key, quick, pg)
        优先使用AJAX建议接口（JSON格式），失败则回退到HTML搜索页
        """
        try:
            page = int(pg) if pg else 1
            encoded_key = urllib.parse.quote(key)

            # 优先尝试 AJAX 建议接口
            ajax_url = f"{self.BASE_URL}/index.php/ajax/suggest?mid=1&wd={encoded_key}"
            resp = self._get(ajax_url)
            if resp and 'json' in resp.headers.get('content-type', ''):
                try:
                    data = resp.json()
                    if data.get('code') == 1 and data.get('list'):
                        videos = []
                        for item in data['list']:
                            videos.append({
                                "vod_id": str(item.get('id', '')),
                                "vod_name": item.get('name', ''),
                                "vod_pic": self._fix_url(item.get('pic', '')),
                                "vod_remarks": item.get('note', ''),
                            })
                        return {
                            "list": videos,
                            "page": data.get('page', page),
                            "pagecount": data.get('pagecount', 1),
                            "limit": data.get('limit', 20),
                            "total": data.get('total', len(videos)),
                        }
                except Exception:
                    pass

            # 回退到HTML搜索页
            url = f"{self.BASE_URL}/search.php?searchword={encoded_key}"
            if page > 1:
                url += f"&page={page}"

            resp = self._get(url)
            if not resp:
                return {"list": [], "page": page, "pagecount": 1, "limit": 20, "total": 0}

            # 检测安全验证拦截
            if any(k in resp.text for k in ['验证码', '人机验证', '安全验证', 'just_a_test']):
                logger.warning("搜索被安全验证拦截")
                return {"list": [], "page": page, "pagecount": 1, "limit": 20, "total": 0}

            videos = self._parse_video_list(resp.text)

            return {
                "list": videos,
                "page": page,
                "pagecount": 1,
                "limit": 20,
                "total": len(videos),
            }
        except Exception as e:
            logger.error(f"搜索失败: {e}")
            return {"list": [], "page": 1, "pagecount": 1, "limit": 20, "total": 0}

    def isBT(self, url):
        """判断是否为磁力/BT链接"""
        return url.startswith('magnet:') or url.endswith('.torrent')
