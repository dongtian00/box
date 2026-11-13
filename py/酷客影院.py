# -*- coding: utf-8 -*-
"""
酷客影院 (www.199dy.com) Python Spider
兼容 FongMi/TV (T3) 与 WebHomeTV / PeekPro (T4)

2026-08-22 修复:
1. 详情页标题"未知"    -> h1 class 为 line1，改为通用 h1 提取
2. 剧集混入"观看更多视频" -> 仅保留 /gov-{id}-{sid}-{ep}.html 剧集链接
3. 父分类只有一页       -> 真实分页 /list/{tid}_{pg}.html，页数取"尾页"链接
4. 排序筛选无内容       -> 真实参数 ?order=hit|time（旧 vodshow 格式全 404）
5. 线路一/三播放不稳    -> 播放页为 iframe 嵌套，直接提取 m3u8 直链
                          + master playlist 自动解析子 m3u8 + 预校验可用性
"""
import sys
import json
import re
import base64
from urllib.parse import quote, unquote, urljoin
from html import unescape as _html_unescape

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

        def post(self, url, headers=None, data=None, **kw):
            kw.pop('timeout', None)
            r = rq.post(url, headers=headers, data=data, timeout=15, **kw)
            r.encoding = 'utf-8'
            return r


class Spider(Spider):
    HOST = 'https://www.199dy.com'
    UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
          '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

    def getName(self):
        return "酷客影院(终极修复版)"

    def init(self, extend=""):
        self.host = self.HOST
        self.header = {
            'User-Agent': self.UA,
            'Referer': self.host + '/',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        }
        # 站点导航: 电影/电视剧/动漫/综艺（伦理等违规栏目不收录）
        self.classes = [
            {"type_id": "1", "type_name": "电影"},
            {"type_id": "2", "type_name": "电视剧"},
            {"type_id": "3", "type_name": "动漫"},
            {"type_id": "4", "type_name": "综艺"},
        ]
        # 站点仅有 按时间/按人气 两种排序: ?order=time / ?order=hit
        by_vals = [{"n": "按时间", "v": "time"}, {"n": "按人气", "v": "hit"}]
        self.filters = {
            str(c["type_id"]): [{"key": "by", "name": "排序", "value": by_vals}]
            for c in self.classes
        }

    # ================= 工具 =================
    def _clean_text(self, s):
        if not s:
            return ""
        for _ in range(3):
            s = _html_unescape(s)
        return s.replace("\xa0", "").replace("&nbsp;", "").strip()

    def _clean_title(self, raw):
        raw = self._clean_text(raw)
        for marker in ("高清版", "预告片", "HD国语", "TC中字", "TC国语", "HD国语|粤语",
                       "_线上看", "| 酷客", "酷客影院"):
            raw = raw.replace(marker, "")
        raw = re.sub(r'(更新至)?(第?\d+[集话]|全集|已完结)\s*$', '', raw)
        return raw.strip()

    def _fetch(self, url, headers=None, timeout=15):
        try:
            return self.fetch(url, headers=headers or self.header, timeout=timeout)
        except Exception:
            return None

    def _encode_url(self, url):
        """仅编码非 ASCII 字符（如中文文件名），避免双重编码"""
        if not url:
            return url
        return re.sub(r'[^\x00-\x7f]+', lambda m: quote(m.group(0)), url)

    def _origin(self, url):
        m = re.match(r'(https?://[^/]+)', url or "")
        return m.group(1) + "/" if m else ""

    def _is_direct_media(self, url):
        url = (url or "").lower()
        return ".m3u8" in url or ".mp4" in url or ".flv" in url or ".mkv" in url

    def _is_official_source(self, url):
        url = (url or "").lower()
        keys = ("mgtv.com", "youku.com", "iqiyi.com", "qiyi.com", "v.qq.com", "qq.com",
                "bilibili.com", "le.com", "sohu.com", "pptv.com", "1905.com")
        return any(k in url for k in keys) and not self._is_direct_media(url)

    # ================= 首页 =================
    def homeContent(self, filter):
        return {'class': self.classes, 'filters': self.filters}

    def homeVideoContent(self):
        rsp = self._fetch(self.host)
        if rsp and rsp.status_code == 200:
            return {"list": self._parse_stui_cards(rsp.text)[:72]}
        return {"list": []}

    # ================= 分类列表 =================
    def categoryContent(self, tid, pg, filter, extend):
        pg = int(pg or 1)
        ext = {}
        if extend:
            if isinstance(extend, dict):
                ext = extend
            elif isinstance(extend, str):
                try:
                    ext = json.loads(extend)
                except Exception:
                    ext = {}
        order = ext.get('by') or ext.get('order') or ''

        # 真实分页: /list/{tid}_{pg}.html  排序: ?order=hit|time
        url = f"{self.host}/list/{tid}.html" if pg <= 1 else f"{self.host}/list/{tid}_{pg}.html"
        if order:
            url += "?order=" + quote(str(order), safe='')

        rsp = self._fetch(url)
        if not rsp or rsp.status_code != 200 or len(rsp.text) < 500:
            return {'list': [], 'page': pg, 'pagecount': 1, 'limit': 30, 'total': 0}

        videos = self._parse_stui_cards(rsp.text)
        pagecount = self._page_count(rsp.text, tid)
        return {"list": videos, "page": pg, "pagecount": pagecount,
                "limit": 30, "total": pagecount * 30}

    def _page_count(self, html, tid):
        # 尾页: <a href="/list/1_836.html?order=hit">尾页</a> (排序时带query后缀)
        m = re.search(rf'href="/list/{tid}_(\d+)\.html[^"]*"[^>]*>\s*尾页', html)
        if m:
            return int(m.group(1))
        pages = [int(x) for x in re.findall(rf'href="/list/{tid}_(\d+)\.html', html)]
        return max(pages) if pages else 1

    def _parse_stui_cards(self, html):
        videos = []
        seen = set()
        for m in re.finditer(r'<a\b([^>]*stui-vodlist__thumb[^>]*)>', html):
            attrs = m.group(1)
            href_m = re.search(r'href="([^"]*?/edu-(\d+)\.html[^"]*)"', attrs)
            if not href_m:
                continue
            vid = href_m.group(2)
            if vid in seen:
                continue

            title = ""
            tm = re.search(r'title="([^"]+)"', attrs)
            if tm:
                title = self._clean_title(tm.group(1))
            if not title:
                fwd = html[m.end():m.end() + 800]
                tm2 = re.search(r'class="[^"]*title[^"]*"[^>]*>([^<]+)<', fwd)
                if tm2:
                    title = self._clean_title(tm2.group(1))
            if not title or "酷客" in title:
                continue

            pic = ""
            pm = re.search(r'style="[^"]*background:\s*url\(([^)]+)\)', attrs)
            if not pm:
                pm = re.search(r'data-original="([^"]+)"', attrs)
            if not pm:
                pm = re.search(r'src="([^"]+)"', attrs)
            if pm:
                pic = pm.group(1).strip().strip("'\"")
                if pic.startswith("//"):
                    pic = "https:" + pic
                elif pic.startswith("/"):
                    pic = self.host + pic

            remarks = ""
            rm = re.search(r'class="[^"]*pic-text[^"]*"[^>]*>([^<]+)<', html[m.end():m.end() + 500])
            if rm:
                remarks = self._clean_text(rm.group(1))

            seen.add(vid)
            videos.append({"vod_id": vid, "vod_name": title,
                           "vod_pic": pic, "vod_remarks": remarks})
        return videos

    # ================= 详情 =================
    def detailContent(self, ids):
        if isinstance(ids, str):
            ids = [ids]
        vod_id = ids[0]
        rsp = self._fetch(f"{self.host}/edu-{vod_id}.html")
        if not rsp or rsp.status_code != 200:
            return {"list": []}
        html = rsp.text

        # 标题: <h1 class="line1">怒之杀</h1> -> 通用 h1 提取
        title = ""
        t_m = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.S)
        if t_m:
            title = self._clean_title(re.sub(r'<[^>]+>', '', t_m.group(1)))
        if not title:
            t_m = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', html, re.I)
            if not t_m:
                t_m = re.search(r'<meta[^>]+content="([^"]+)"[^>]+property="og:title"', html, re.I)
            if t_m:
                title = self._clean_title(t_m.group(1))
        if not title:
            t_m = re.search(r'<title>([^<]+)</title>', html)
            if t_m:
                title = self._clean_title(re.sub(r'[-_|].*$', '', t_m.group(1)))
        title = title or vod_id

        pic = ""
        pic_m = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html, re.I)
        if not pic_m:
            pic_m = re.search(r'data-original="([^"]+)"', html)
        if pic_m:
            pic = pic_m.group(1).strip()
            if pic.startswith("//"):
                pic = "https:" + pic
            elif pic.startswith("/"):
                pic = self.host + pic

        content = ""
        c_m = re.search(r'<span[^>]*class="[^"]*detail-content[^"]*"[^>]*>(.*?)</span>', html, re.S | re.I)
        if not c_m:
            c_m = re.search(r'<div[^>]*class="[^"]*stui-content__desc[^"]*"[^>]*>(.*?)</div>', html, re.S | re.I)
        if c_m:
            content = self._clean_text(re.sub(r'<[^>]+>', '', c_m.group(1)))
        if not content:
            c_m = re.search(r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']+)["\']', html, re.I)
            if c_m:
                content = self._clean_text(c_m.group(1))

        actor = self._extract_meta(html, "主演")
        director = self._extract_meta(html, "导演")
        type_name = self._extract_meta(html, "类型")
        area = self._extract_meta(html, "地区")
        year = self._extract_meta(html, "年份")

        play_from, play_url = self._parse_playlist(html, vod_id)

        vod = {
            "vod_id": vod_id, "vod_name": title, "vod_pic": pic, "type_name": type_name,
            "vod_year": year, "vod_area": area, "vod_remarks": "",
            "vod_actor": actor, "vod_director": director,
            "vod_content": content[:500] if content else "",
            "vod_play_from": "$$$".join(play_from) if play_from else "默认线路",
            "vod_play_url": "$$$".join(play_url),
        }
        return {"list": [vod]}

    def _extract_meta(self, html, label):
        # 结构: <span class="text-muted">类型：</span><a href=...>电视剧</a>
        # 取标签后第一个 <a> 或紧邻文本，遇到下一个 text-muted span 即停
        m = re.search(rf'<span[^>]*>\s*{label}\s*[：:]\s*</span>\s*(.*?)(?=<span[^>]*class="text-muted"|</p>|<p)', html, re.S)
        if m:
            frag = m.group(1)
            a_m = re.search(r'<a[^>]*>([^<]+)</a>', frag)
            if a_m:
                return self._clean_text(a_m.group(1))
            txt = re.sub(r'<[^>]+>', '', frag)
            txt = self._clean_text(txt)
            # 截断混入的其他标签文本（如 "电视剧  地区：大陆"）
            for nxt in ("地区", "年份", "主演", "导演", "类型"):
                cut = re.search(rf'{nxt}\s*[：:]', txt)
                if cut and nxt != label:
                    txt = txt[:cut.start()].strip()
            return txt.replace('/', ' / ').strip()
        return ""

    def _parse_playlist(self, html, vod_id):
        """剧集: /gov-{vid}-{sid}-{ep}.html，按线路(sid)分组，过滤外链按钮"""
        play_from, play_url = [], []
        if not html:
            return [], []

        # 线路名: <a data-toggle="tab" href="#down1">优酷视频</a>，down1 对应 sid=0
        tab_names = {}
        for m in re.finditer(r'<a\b([^>]*?)href="#(down|play)(\d+)"([^>]*)>([^<]*)<', html):
            num, nm = m.group(3), m.group(5)
            nm = self._clean_text(nm)
            if nm and not any(k in nm for k in ("搜索", "下载", "播放入口")):
                tab_names[int(num) - 1] = nm

        # 收集剧集链接（同集去重：优先带 title 属性的正式链接，跳过"立即播放"按钮）
        ep_map = {}
        for m in re.finditer(r'<a\b([^>]*?)href="(/gov-(\d+)-(\d+)-(\d+)\.html[^"]*)"([^>]*)>([^<]*)<', html):
            pre, link, vid, sid, ep, post, name = m.groups()
            if vid != str(vod_id):
                continue
            attrs = pre + " " + post
            sid_i, ep_i = int(sid), int(ep)
            name = self._clean_text(name)
            title_m = re.search(r'title="([^"]+)"', attrs)
            title_txt = self._clean_text(title_m.group(1)) if title_m else ""
            # 正式集名（第N集/高清版等）优先；按钮（"立即播放"/纯剧名）仅作兜底
            is_ep_name = bool(name) and (re.search(r'第?\d+|[集话]|HD|TC|高清|中字|国语|粤语|正片|预告|备用', name, re.I) or "集" in name)
            if not name and title_txt:
                name = title_txt
            bucket = ep_map.setdefault(sid_i, {})
            old = bucket.get(ep_i)
            if old is None or (is_ep_name and not old[2]):
                bucket[ep_i] = (name or f"第{ep_i + 1}集", link, is_ep_name)

        for sid in sorted(ep_map.keys()):
            eps = sorted(ep_map[sid].items())
            line_name = tab_names.get(sid, f"线路{sid + 1}")
            if line_name in play_from:
                line_name += f"-{sid + 1}"
            play_from.append(line_name)
            play_url.append("#".join(f"{nm}${self.host}{lk}" for _, (nm, lk, _) in eps))
        return play_from, play_url

    # ================= 搜索 =================
    def searchContent(self, key, quick, pg="1"):
        try:
            rsp = self.post(f"{self.host}/search.php", headers=self.header,
                            data={"searchword": key}, timeout=15)
            videos = self._parse_stui_cards(rsp.text) if rsp and rsp.status_code == 200 else []
            if not videos:
                rsp = self._fetch(f"{self.host}/search.php?searchword={quote(key, safe='')}")
                videos = self._parse_stui_cards(rsp.text) if rsp and rsp.status_code == 200 else []
            return {"list": videos, "page": 1, "pagecount": 1, "limit": 30, "total": len(videos)}
        except Exception:
            return {"list": []}

    # ================= 播放 =================
    def _extract_player_url(self, html):
        """从 iframe 内嵌页提取真实播放地址 (Artplayer/DPlayer/通用)"""
        if not html:
            return ""
        # Artplayer: id: "https://.../xx.m3u8"
        m = re.search(r'id:\s*["\'](https?://[^"\']+)["\']', html)
        if m:
            return m.group(1).replace("\\/", "/")
        # DPlayer: var vid = "https://...m3u8?auth_key=..."
        m = re.search(r'var\s+vid\s*=\s*["\'](https?://[^"\']+)["\']', html)
        if m:
            return m.group(1).replace("\\/", "/")
        # 通用: 页面里首个 m3u8/mp4 直链
        m = re.search(r'["\'](https?://[^"\']+\.(?:m3u8|mp4)[^"\']*)["\']', html, re.I)
        if m:
            return m.group(1).replace("\\/", "/")
        return ""

    def _probe_m3u8(self, url, src_page=""):
        """校验 m3u8: 返回 (播放地址, 是否有效)
        - master playlist -> 解析子 m3u8
        - media playlist -> 校验首分片魔数(TS=0x47)，PNG/JPEG 视为伪源
        - Referer 策略探测: 先空 Referer，403 再带 Referer
        """
        base_headers = [{"User-Agent": self.UA},
                        {"User-Agent": self.UA, "Referer": self._origin(src_page) or self.host + "/"}]
        for headers in base_headers:
            try:
                rsp = self._fetch(url, headers=headers, timeout=8)
            except Exception:
                rsp = None
            if not rsp or rsp.status_code != 200:
                continue
            text = rsp.text or ""
            if "#EXTM3U" not in text:
                continue

            if "#EXT-X-STREAM-INF" in text:
                # master playlist -> 解析子 m3u8
                lines = [l.strip() for l in text.splitlines()
                         if l.strip() and not l.strip().startswith("#")]
                if lines:
                    child = self._encode_url(urljoin(url, lines[-1]))
                    child_rsp = self._fetch(child, headers=headers, timeout=8)
                    if child_rsp and child_rsp.status_code == 200 and "#EXTM3U" in (child_rsp.text or ""):
                        if self._first_segment_valid(child, child_rsp.text, headers):
                            return child, True, headers
                continue

            # media playlist -> 校验首分片
            if self._first_segment_valid(url, text, headers):
                return url, True, headers
        return "", False, {}

    def _first_segment_valid(self, m3u8_url, m3u8_text, headers):
        """取首个非 EXTINF 行后的分片地址，请求前 16 字节校验魔数"""
        try:
            lines = [l.strip() for l in m3u8_text.splitlines()
                     if l.strip() and not l.strip().startswith("#")]
            if not lines:
                return False
            seg = lines[0]
            if not seg.lower().startswith("http"):
                # m3u8 本身不以 / 结尾, urljoin 直接基于其目录解析相对分片
                seg = urljoin(m3u8_url, seg)
            seg = self._encode_url(seg)
            if "?" not in seg and "?" in m3u8_url:
                seg += "?" + m3u8_url.split("?", 1)[1]
            rsp = self._fetch(seg, headers={**headers, "Range": "bytes=0-15"}, timeout=8)
            if not rsp or rsp.status_code not in (200, 206):
                return False
            head = (rsp.content or b"")[:4]
            if not head:
                return False
            # PNG / JPEG / GIF / HTML = 伪装源，播放器解码不出视频
            if head[:4] == b'\x89PNG' or head[:2] == b'\xff\xd8' or head[:3] == b'GIF' or head[:1] == b'<':
                return False
            return True
        except Exception:
            return False

    def playerContent(self, flag, id, vipFlags):
        url = id if str(id).startswith("http") else self.host + id
        try:
            html = ""
            rsp = self._fetch(url)
            if rsp and rsp.status_code == 200:
                html = rsp.text

            real = ""
            src_page = url
            ifr_headers = None

            # 1) iframe 嵌套页 (play.kukedy6.com/content.php?vid=...)
            if html:
                ifr = re.search(r'<iframe[^>]+src=["\']([^"\']+)["\']', html, re.I)
                if ifr:
                    ifr_url = ifr.group(1).strip()
                    if ifr_url.startswith("//"):
                        ifr_url = "https:" + ifr_url
                    elif ifr_url.startswith("/"):
                        ifr_url = self.host + ifr_url
                    sub = self._fetch(ifr_url, headers={**self.header, "Referer": url})
                    if sub and sub.status_code == 200:
                        src_page = ifr_url
                        real = self._extract_player_url(sub.text)

            # 2) player_aaaa 变量兜底
            if html and not real:
                m = re.search(r'var\s+player_aaaa\s*=\s*(\{.*?\});', html, re.S)
                if m:
                    try:
                        data = json.loads(m.group(1))
                        raw = data.get("url", "")
                        enc = data.get("encrypt", 0)
                        if enc == 2 and raw:
                            try:
                                raw = unquote(base64.b64decode(raw).decode('utf-8'))
                            except Exception:
                                pass
                        elif enc == 1 and raw:
                            try:
                                raw = base64.b64decode(raw).decode('utf-8')
                            except Exception:
                                pass
                        real = (raw or "").replace("\\/", "/")
                    except Exception:
                        pass

            if real:
                real = self._encode_url(real)
                if self._is_official_source(real):
                    resolved = self._resolve_official_to_media(real)
                    if resolved:
                        real = self._encode_url(resolved)
                    else:
                        return {"parse": 1, "playUrl": "", "url": url, "header": self.header}

                if self._is_direct_media(real):
                    ok_url, ok, used_headers = self._probe_m3u8(real, src_page)
                    if ok:
                        return {
                            "parse": 0, "playUrl": "", "url": ok_url,
                            "header": used_headers if used_headers else {"User-Agent": self.UA},
                            "format": "application/x-mpegURL" if ".m3u8" in ok_url else "",
                        }

            # 3) 当前线路不可用 -> 尝试同片其他线路同集 (自动换线)
            alt = self._try_alternative_lines(url, html)
            if alt:
                return alt

            # 4) 兜底: 交给壳子网页嗅探
            return {"parse": 1, "playUrl": "", "url": url, "header": self.header}
        except Exception:
            return {"parse": 1, "playUrl": "", "url": url, "header": self.header}

    def _try_alternative_lines(self, play_page_url, html):
        """当前线路死链/伪源时，从详情页提取其他线路同集链接逐个校验"""
        try:
            m = re.search(r'/gov-(\d+)-(\d+)-(\d+)\.html', play_page_url)
            if not m:
                return None
            vid, cur_sid, ep = m.group(1), int(m.group(2)), int(m.group(3))

            if not html:
                rsp = self._fetch(f"{self.host}/edu-{vid}.html")
                if not rsp or rsp.status_code != 200:
                    return None
                html = rsp.text
            if not html:
                return None

            # 其他线路同集: /gov-{vid}-{sid}-{ep}.html
            sids = set(int(x) for x in re.findall(rf'/gov-{vid}-(\d+)-\d+\.html', html))
            sids.discard(cur_sid)
            if not sids:
                return None

            for sid in sorted(sids):
                alt_url = f"{self.host}/gov-{vid}-{sid}-{ep}.html"
                rsp = self._fetch(alt_url)
                if not rsp or rsp.status_code != 200:
                    continue
                ifr = re.search(r'<iframe[^>]+src=["\']([^"\']+)["\']', rsp.text, re.I)
                if not ifr:
                    continue
                ifr_url = ifr.group(1).strip()
                if ifr_url.startswith("//"):
                    ifr_url = "https:" + ifr_url
                elif ifr_url.startswith("/"):
                    ifr_url = self.host + ifr_url
                sub = self._fetch(ifr_url, headers={**self.header, "Referer": alt_url})
                if not sub or sub.status_code != 200:
                    continue
                real = self._extract_player_url(sub.text)
                if not real or not self._is_direct_media(real):
                    continue
                real = self._encode_url(real)
                ok_url, ok, used_headers = self._probe_m3u8(real, ifr_url)
                if ok:
                    return {
                        "parse": 0, "playUrl": "", "url": ok_url,
                        "header": used_headers if used_headers else {"User-Agent": self.UA},
                        "format": "application/x-mpegURL" if ".m3u8" in ok_url else "",
                    }
        except Exception:
            pass
        return None

    def _resolve_official_to_media(self, src_url):
        try:
            page_url = "https://bfq.txnp.cn/player?url=" + quote(src_url, safe="")
            referer = "https://bfq.txnp.cn/excessive?url=" + quote(src_url, safe="")
            rsp = self._fetch(page_url, headers={"User-Agent": self.UA, "Referer": referer})
            result_m = re.search(r'let\s+result\s*=\s*"([^"]+)"', (rsp.text or ""), re.S)
            if not result_m:
                return ""
            from Crypto.Cipher import AES
            cipher = result_m.group(1)
            key = cipher[-32:-16].encode("utf-8")
            iv = cipher[-16:].encode("utf-8")
            raw = AES.new(key, AES.MODE_CBC, iv).decrypt(base64.b64decode(cipher[:-32]))
            pad = raw[-1] if raw else 0
            if 0 < pad <= 16:
                raw = raw[:-pad]
            data = json.loads(raw.decode("utf-8", "ignore"))
            media = (((data.get("video_info") or {}).get("video") or {}).get("url") or "").replace("\\/", "/")
            if media and self._is_direct_media(media):
                return media
        except Exception:
            pass
        return ""

    def destroy(self):
        pass
