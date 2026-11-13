# -*- coding: utf-8 -*-
import sys
import re
import json
import logging
import time
from urllib.parse import urljoin, quote

sys.path.append('..')
try:
    from base.spider import Spider
except ImportError:
    class Spider:
        def fetch(self, url, headers=None, **kw):
            import requests as rq
            kw.pop('timeout', None)
            r = rq.get(url, headers=headers, timeout=15, **kw)
            r.encoding = 'utf-8'
            return r

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

HOST = "https://www.iysdq.tv"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

CATEGORIES = {
    "1": "电影", "2": "电视剧", "3": "综艺",
    "4": "动漫", "5": "短剧",
}


class Spider(Spider):
    def __init__(self):
        self.session = None
        self._host = HOST
        self._last_request_time = 0
        self._min_interval = 0.3  # 请求间隔，避免触发反爬

    def init(self, extend=""):
        """初始化：探测实际域名（处理跳转）"""
        try:
            r = self._fetch(self._host, timeout=15000, allow_redirects=True)
            if r and hasattr(r, 'url') and r.url:
                actual = r.url.rstrip("/")
                if actual != self._host.rstrip("/"):
                    logger.info(f"Host redirected: {self._host} -> {actual}")
                    self._host = actual
        except Exception as e:
            logger.warning(f"Init host detection failed: {e}")

    def homeContent(self, filter=False):
        """首页分类"""
        return {
            "class": [
                {"type_id": k, "type_name": v}
                for k, v in CATEGORIES.items()
            ],
            "list": []
        }

    def homeVideoContent(self):
        """首页推荐视频"""
        try:
            html = self._fetch_html(self._host, timeout=15000)
            return {"list": self._parse_items(html)}
        except Exception as e:
            logger.error(f"homeVideoContent error: {e}")
            return {"list": []}

    def categoryContent(self, tid, pg=1, filter=False, extend=""):
        """分类列表"""
        pn = 1
        try:
            pn = max(int(str(pg)), 1)
        except (ValueError, TypeError):
            pass

        cat = str(tid) if str(tid) in CATEGORIES else "1"
        url = f"{self._host}/vodtype/{cat}-{pn}.html"

        try:
            html = self._fetch_html(url, timeout=30000)
            items = self._parse_items(html)
            return {
                "page": pn,
                "pagecount": self._parse_pagecount(html, pn),
                "limit": 24,
                "total": len(items),
                "list": items
            }
        except Exception as e:
            logger.error(f"categoryContent error (tid={tid}, pg={pg}): {e}")
            return {
                "page": pn, "pagecount": 1, "limit": 24,
                "total": 0, "list": []
            }

    def detailContent(self, ids):
        """详情页"""
        vid = self._extract_id(ids)
        if not vid:
            return {"list": []}

        url = f"{self._host}/voddetail/{vid}.html"
        try:
            html = self._fetch_html(url, timeout=30000)
            detail = self._parse_detail(html, vid)
            return {"list": [detail]}
        except Exception as e:
            logger.error(f"detailContent error (id={vid}): {e}")
            return {"list": []}

    def searchContent(self, key, quick=False, pg="1"):
        """搜索"""
        pn = 1
        try:
            pn = max(int(str(pg)), 1)
        except (ValueError, TypeError):
            pass

        # 修复：搜索URL使用pn参数
        url = f"{self._host}/vodsearch/{pn}-------------.html?wd={quote(key)}"

        try:
            html = self._fetch_html(url, timeout=30000)
            items = self._parse_items(html)
            return {"list": items, "page": pn}
        except Exception as e:
            logger.error(f"searchContent error (key={key}): {e}")
            return {"list": [], "page": pn}

    def playerContent(self, flag, id, vipFlags=None):
        """播放器：解析真实播放地址"""
        url = str(id) if id else str(flag)
        if not url:
            return {"url": ""}

        # 直接是媒体地址
        if url.startswith("http") and "/vodplay/" not in url:
            if ".m3u8" in url or ".mp4" in url:
                return {"url": url}

        # 组装完整URL
        if url.startswith("http"):
            full_url = url
        else:
            full_url = urljoin(self._host, url if url.startswith("/") else f"/{url}")

        try:
            html = self._fetch_html(full_url, timeout=30000)
        except Exception as e:
            logger.error(f"playerContent fetch error: {e}")
            return {"url": ""}

        # 1. 优先解析 player_aaaa JSON
        play_url = self._extract_player_json(html)
        if play_url:
            return {"url": play_url}

        # 2. 兜底：正则匹配 m3u8 / mp4
        play_url = self._extract_media_url(html)
        if play_url:
            return {"url": play_url}

        logger.warning(f"No play url found for: {full_url}")
        return {"url": ""}

    def localProxy(self, param):
        pass

    # ==================== 私有工具方法 ====================

    def _fetch(self, url, timeout=15000, retries=2, **kwargs):
        """带重试、间隔控制的请求"""
        # 请求间隔控制
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)

        headers = kwargs.pop('headers', {})
        headers.setdefault("User-Agent", UA)
        headers.setdefault("Referer", self._host)

        last_err = None
        for attempt in range(retries + 1):
            try:
                # 转换毫秒为秒
                timeout_sec = timeout / 1000.0 if timeout > 1000 else timeout
                r = self.fetch(url, headers=headers, timeout=timeout_sec, **kwargs)
                self._last_request_time = time.time()
                if hasattr(r, 'text'):
                    r.encoding = 'utf-8'
                return r
            except Exception as e:
                last_err = e
                if attempt < retries:
                    wait = 0.5 * (attempt + 1)
                    logger.warning(f"Request retry {attempt + 1}/{retries} for {url}: {e}")
                    time.sleep(wait)
                else:
                    raise last_err

    def _fetch_html(self, url, timeout=15000, **kwargs):
        """获取HTML文本"""
        r = self._fetch(url, timeout=timeout, **kwargs)
        if hasattr(r, 'text'):
            return r.text
        return str(r)

    @staticmethod
    def _extract_id(ids):
        """从各种输入中提取视频ID"""
        if isinstance(ids, list):
            vid = ids[0] if ids else ""
        else:
            vid = str(ids) if ids else ""
        m = re.search(r'(\d+)', str(vid))
        return m.group(1) if m else ""

    @staticmethod
    def _clean_html(text):
        """去除HTML标签并规范化空白"""
        if not text:
            return ""
        text = re.sub(r'<[^>]+>', '', text)
        return re.sub(r'\s+', ' ', text).strip()

    @staticmethod
    def _safe_search(pattern, text, group=1, default="", flags=0):
        """安全的正则搜索"""
        if not text:
            return default
        m = re.search(pattern, text, flags)
        if m and group <= len(m.groups()):
            return m.group(group)
        return default

    # ==================== 解析方法 ====================

    def _parse_items(self, html):
        """解析视频列表项"""
        if not html:
            return []

        items, seen = [], set()
        # 匹配详情页链接和标题
        pattern = re.compile(r'href="/voddetail/(\d+)\.html"[^>]*title="([^"]*)"')
        for m in pattern.finditer(html):
            vid = m.group(1)
            if vid in seen:
                continue

            name = m.group(2).strip()
            if not name or len(name) > 100:
                continue

            # 提取后续800字符内的封面和备注
            after = html[m.end():m.end() + 800]

            # 封面图
            cover = ""
            cover_m = re.search(
                r'(?:data-original|data-src|original|src)="(https?://[^"]+\.(?:jpg|jpeg|png|webp))"',
                after, re.I
            )
            if not cover_m:
                cover_m = re.search(r'src="(https?://[^"]+)"', after)
            if cover_m:
                cover = cover_m.group(1)

            # 备注信息
            remark = ""
            remark_m = re.search(
                r'class="(?:module-item-note|pic-text|public-list-prb|remarks|status|myui-vodlist__thumb)[^"]*"[^>]*>([^<]+)<',
                after
            )
            if not remark_m:
                remark_m = re.search(
                    r'<div[^>]*class="[^"]*(?:note|text|remark)[^"]*"[^>]*>([^<]+)<',
                    after, re.I
                )
            if remark_m:
                remark = remark_m.group(1).strip()

            seen.add(vid)
            items.append({
                "vod_id": vid,
                "vod_name": name[:50],
                "vod_pic": cover,
                "vod_remarks": remark,
            })

        return items

    def _parse_pagecount(self, html, current_page=1):
        """解析总页数"""
        if not html:
            return current_page

        pages = re.findall(r'href="/vodtype/\d+-(\d+)\.html"', html)
        max_page = current_page
        for p in pages:
            try:
                n = int(p)
                if n > max_page:
                    max_page = n
            except ValueError:
                continue

        # 如果有下一页按钮，预估后续页数
        has_next = re.search(r'title="下一页"|class="[^"]*next[^"]*"', html)
        if has_next and max_page <= current_page + 5:
            max_page = current_page + 5

        return max_page

    def _parse_detail(self, html, vid):
        """解析详情页数据"""
        d = {
            "vod_id": vid, "vod_name": "", "vod_pic": "",
            "vod_year": "", "vod_area": "", "vod_class": "",
            "vod_director": "", "vod_actor": "", "vod_content": "",
            "vod_remarks": "", "vod_play_from": "", "vod_play_url": ""
        }

        # 标题：优先 this-desc-title，其次 title 标签
        title = self._safe_search(r'class="this-desc-title">([^<]+)<', html)
        if not title:
            title = self._safe_search(r'<title>(.*?)</title>', html)
            if title:
                # 清理 title 中的后缀
                title = title.split("-")[0] \
                    .replace("免费在线观看", "") \
                    .replace("高清完整版", "") \
                    .strip()
        if title:
            d["vod_name"] = self._clean_html(title)

        # 封面
        cover = self._safe_search(
            r'background-image:\s*url\([\'"]?(https?://[^\'")]+)', html
        )
        if not cover:
            cover = self._safe_search(
                r'data-src="(https?://[^"]+\.(?:jpg|jpeg|png|webp))"', html, flags=re.I
            )
        d["vod_pic"] = cover

        # 简介
        desc = self._safe_search(r'<meta name="description" content="([^"]*)"', html)
        if not desc:
            desc_block = self._safe_search(
                r'class="[^"]*this-desc[^"]*"[^>]*>([\s\S]*?)</div>', html
            )
            if desc_block:
                desc = desc_block
        if desc:
            d["vod_content"] = self._clean_html(desc)[:500]

        # 年份/地区/备注
        info = self._safe_search(
            r'class="this-desc-info"[^>]*>([\s\S]*?)</div>', html
        )
        if info:
            # 年份
            year_m = re.search(r'(\d{4})', info)
            if year_m:
                d["vod_year"] = year_m.group(1)

            # 地区（排除更新状态等词）
            area_m = re.search(r'([\u4e00-\u9fff]{2,8}?)(?:</span>|$)', info)
            if area_m:
                area = area_m.group(1)
                if not re.search(r'更新|状态|类型|地区', area):
                    d["vod_area"] = area

            # 更新备注
            remark_m = re.search(r'更新[至到]?([^<]+)', info)
            if remark_m:
                d["vod_remarks"] = remark_m.group(1).strip()

        # 分类标签
        tag = self._safe_search(
            r'class="[^"]*this-tag[^"]*bj2[^"]*"[^>]*>([^<]+)<', html
        )
        if not tag:
            tag_block = self._safe_search(
                r'class="this-desc-tags"[^>]*>([\s\S]*?)</div>', html
            )
            if tag_block:
                tag = self._clean_html(tag_block).rstrip('，')
        d["vod_class"] = tag

        # 导演
        director_block = self._safe_search(r'导演:</strong>([\s\S]*?)</div>', html)
        if director_block:
            d["vod_director"] = ','.join(
                re.findall(r'>([^<>]{1,30})</a>', director_block)
            )

        # 演员
        actor_block = self._safe_search(r'演员:</strong>([\s\S]*?)</div>', html)
        if actor_block:
            d["vod_actor"] = ','.join(
                re.findall(r'>([^<>]{1,30})</a>', actor_block)
            )

        # 播放源解析
        play_from, play_url = self._parse_play_sources(html)
        if play_from:
            d["vod_play_from"] = "$$$".join(play_from)
            d["vod_play_url"] = "$$$".join(play_url)

        return d

    def _parse_play_sources(self, html):
        """解析播放线路和集数"""
        pf, pu = [], []

        try:
            # 提取标签名
            tabs = []
            tab_block = self._safe_search(
                r'<div class="anthology-tab[^>]*>(.*?)</div>\s*</div>', html
            )
            if tab_block:
                tabs = re.findall(r'&nbsp;([\u4e00-\u9fffA-Za-z]+线)', tab_block)

            # 提取播放列表
            boxes = re.findall(
                r'<div class=["\']?anthology-list-box[^>]*>(.*?)</div>\s*</div>',
                html, re.S
            )

            # 方式1：按标签+盒子匹配
            for tab, box in zip(tabs, boxes):
                links = re.findall(
                    r'href="(/vodplay/\d+-\d+-\d+\.html)"[^>]*>([\s\S]*?)</a>',
                    box
                )
                if not links:
                    continue

                eps = []
                hrefs = []
                for u, nm in links:
                    eps.append(self._clean_html(nm))
                    hrefs.append(u)

                pf.append(tab)
                pu.append("#".join([
                    f"{ep}${urljoin(self._host, href)}"
                    for ep, href in zip(eps, hrefs)
                ]))

            # 方式2：兜底，按路由分组
            if not pf:
                play_urls = re.findall(
                    r'href="(/vodplay/\d+-(\d+)-(\d+)\.html)"[^>]*>([^<]+)</a>',
                    html
                )
                routes = {}
                for href, route, ep, name in play_urls:
                    if route not in routes:
                        routes[route] = []
                    routes[route].append(
                        f"{name.strip()}${urljoin(self._host, href)}"
                    )

                for idx, route in enumerate(sorted(
                    routes.keys(),
                    key=lambda x: int(x) if x.isdigit() else 999
                )):
                    name = tabs[idx] if idx < len(tabs) else f"线路{route}"
                    pf.append(name)
                    pu.append("#".join(routes[route]))

        except Exception as e:
            logger.error(f"Parse play sources error: {e}")

        return pf, pu

    @staticmethod
    def _extract_player_json(html):
        """从 player_aaaa 变量中提取播放地址"""
        if not html:
            return ""
        pd = re.search(r'var player_aaaa=(.*?)</script>', html, re.S)
        if pd:
            try:
                data = json.loads(pd.group(1))
                return data.get("url", "")
            except json.JSONDecodeError as e:
                logger.warning(f"player_aaaa JSON decode error: {e}")
        return ""

    @staticmethod
    def _extract_media_url(html):
        """从HTML中提取直接的媒体URL"""
        if not html:
            return ""
        # 优先 m3u8
        m3u8 = re.search(r'(https?://[^\s"\'<>]+\.m3u8)', html)
        if m3u8:
            return m3u8.group(1)
        # 其次 mp4
        mp4 = re.search(r'(https?://[^\s"\'<>]+\.mp4)', html)
        if mp4:
            return mp4.group(1)
        return ""
