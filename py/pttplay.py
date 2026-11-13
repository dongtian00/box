# -*- coding: utf-8 -*-
import sys
import re
import urllib.parse
sys.path.append('..')
try:
    from base.spider import Spider
except ImportError:
    class Spider:
        def init(self, extend=""):
            pass
        def getName(self):
            return ""
        def isVideoFormat(self, url):
            return False
        def manualVideoCheck(self):
            pass
        def destroy(self):
            pass
        def homeContent(self, filter):
            return {}
        def homeVideoContent(self):
            return {}
        def categoryContent(self, tid, pg, filter, extend):
            return {}
        def detailContent(self, ids):
            return {}
        def searchContent(self, key, quick, pg="1"):
            return {}
        def playerContent(self, flag, id, vipFlags):
            return {}
        def localProxy(self, param):
            return None
        def liveContent(self, url):
            pass
        def fetch(self, url, headers=None, timeout=15):
            import requests
            r = requests.get(url, headers=headers, timeout=timeout)
            r.raise_for_status()
            r.encoding = r.apparent_encoding or "utf-8"
            return r


class Spider(Spider):

    def init(self, extend=""):
        self.extend = extend

    def getName(self):
        return "PttPlay"

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        pass

    def destroy(self):
        pass

    host = 'https://pttplay.cc'

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                      'AppleWebKit/537.36 (KHTML, like Gecko) '
                      'Chrome/125.0.0.0 Safari/537.36',
        'Referer': 'https://pttplay.cc',
    }

    classes_config = [
        ("电影", "1"),
        ("电视剧", "2"),
        ("综艺", "3"),
        ("动漫", "4"),
        ("美剧", "21"),
    ]

    class_icons = {
        "电影": "",
        "电视剧": "",
        "综艺": "",
        "动漫": "",
        "美剧": "",
    }

    # ------------------------- 工具方法 -------------------------
    def _fix_url(self, url, base_host):
        if not url:
            return ''
        url = url.strip()
        if url.startswith('//'):
            return 'https:' + url
        if url.startswith('/'):
            return base_host + url
        if not url.startswith('http'):
            return base_host + '/' + url
        return url

    def _extract_pic(self, snippet):
        if not snippet:
            return ''
        # 1. <a> 标签上的 data-original（列表页懒加载）
        m = re.search(r'data-original=["\']?(//[^"\'>\s]+)["\']?', snippet, re.I)
        if m:
            return m.group(1)
        # 2. <a> 标签上的 data-background（轮播图）
        m = re.search(r'data-background=["\']?(//[^"\'>\s]+)["\']?', snippet, re.I)
        if m:
            return m.group(1)
        # 3. style 中的 background-image: url(...)
        m = re.search(r'background-image\s*:\s*url\(["\']?(//[^"\')\s]+)["\']?\)', snippet, re.I)
        if m:
            return m.group(1)
        # 4. 任意标签的 data-background / data-original
        m = re.search(r'(?:data-background|data-original)=["\']?([^"\'>\s]+)["\']?', snippet, re.I)
        if m:
            return m.group(1)
        # 5. <img> 标签的各种属性兜底
        for attr in ['data-original', 'data-src', 'data-img', 'data-bg',
                     'data-background', 'data-cover', 'data-poster', 'srcset', 'src']:
            m = re.search(r'<img[^>]+\b' + attr + r'=["\']?([^"\'>\s]+)["\']?', snippet, re.I)
            if m:
                url = m.group(1).strip()
                if attr in ('srcset', 'data-srcset'):
                    url = url.split(',')[0].split()[0]
                if url and url not in ('#', 'javascript:;'):
                    return url
        # 6. 通用 url() 兜底
        m = re.search(r'url\(["\']?([^"\')]+)["\']?\)', snippet, re.I)
        if m:
            return m.group(1).strip()
        return ''

    # ------------------------- 核心接口 -------------------------
    def homeContent(self, filter):
        result = {}
        classes = []
        vlist = []
        for name, tid in self.classes_config:
            classes.append({
                "type_name": name,
                "type_id": tid,
                "type_pic": self.class_icons.get(name, "")
            })
        rsp = self.fetch(self.host, headers=self.headers)
        vlist.extend(self.parse_list(rsp.text))
        result['class'] = classes
        result['list'] = vlist
        return result

    def homeVideoContent(self):
        return {}

    def categoryContent(self, tid, pg, filter, extend):
        p = f"-{pg}" if int(pg) > 1 else ""
        url = f'{self.host}/type/{tid}{p}.html'
        rsp = self.fetch(url, headers=self.headers)
        videos = self.parse_list(rsp.text)
        return {
            'list': videos,
            'page': pg,
            'pagecount': 9999,
            'limit': 90,
            'total': 999999
        }

    def detailContent(self, ids):
        vid = ids[0]
        if vid.startswith('http'):
            url = vid
        elif vid.startswith('/'):
            url = self.host + vid
        else:
            url = f'{self.host}/vod/{vid}.html'

        rsp = self.fetch(url, headers=self.headers)
        html = rsp.text

        title_m = re.search(r'<h1[^>]*>([^<]+)</h1>', html)
        name = title_m.group(1).strip() if title_m else ""

        meta = {}
        for m in re.finditer(r'([^\s:：]{1,8})[：:]\s*([^<\n]{1,80})', html):
            k, v = m.group(1).strip(), m.group(2).strip()
            if k in ("主演", "導演", "地區", "語言", "年份", "年代",
                     "類別", "類型", "狀態", "狀況", "更新時間") and len(v) > 1:
                meta.setdefault(k, v)

        tabs = []
        for m in re.finditer(r'<a[^>]+href="#con_playlist_(\d+)"[^>]*>([^<]+)</a>', html):
            src_num = int(m.group(1))
            tab_name = re.sub(r'<[^>]+>', '', m.group(2)).strip()
            if tab_name:
                tabs.append((src_num, tab_name))

        ep_pattern = re.compile(
            r'<li>\s*<a[^>]*href="(/v/\d+-(\d+)-(\d+)\.html)"[^>]*>([^<]+)</a>\s*</li>'
        )
        buckets = {}
        seen_ep = set()
        for m in ep_pattern.finditer(html):
            href = m.group(1)
            key = (href, m.group(4).strip())
            if key in seen_ep:
                continue
            seen_ep.add(key)
            src_n = int(m.group(2))
            ep_name = m.group(4).strip()
            full_url = self.host + href
            buckets.setdefault(src_n, []).append(f'{ep_name}${full_url}')

        play_from = []
        play_url = []
        for src_num, tab_name in tabs:
            if src_num in buckets and buckets[src_num]:
                play_from.append(tab_name)
                play_url.append('#'.join(buckets[src_num]))

        pic = ''
        block_m = re.search(r'<a[^>]*class="[^"]*(?:video-pic|slide-pic|poster)[^"]*"[^>]*>', html, re.I)
        if block_m:
            pic = self._extract_pic(block_m.group(0))
        if not pic:
            block_m = re.search(r'<div[^>]*class="[^"]*(?:video-pic|detail-pic|poster|cover)[^"]*"[^>]*>', html, re.I)
            if block_m:
                pic = self._extract_pic(block_m.group(0))
        if not pic:
            m = re.search(r'<a[^>]*href="[^"]*/vod/\d+\.html"[^>]*data-original="([^"]+)"', html, re.I)
            if m:
                pic = m.group(1)
        if not pic:
            m = re.search(r'(//img\.imgoss\.[a-z]+/upload/vod/[^"\'<>\s]+)', html, re.I)
            if m:
                pic = m.group(1)
        pic = self._fix_url(pic, self.host)

        vod = {
            'vod_id': vid,
            'vod_name': name,
            'vod_pic': pic,
            'type_name': meta.get('類別', meta.get('類型', '')),
            'vod_year': meta.get('年份', meta.get('年代', '')),
            'vod_area': meta.get('地區', ''),
            'vod_remarks': meta.get('狀態', meta.get('狀況', '')),
            'vod_actor': meta.get('主演', ''),
            'vod_director': meta.get('導演', ''),
            'vod_content': '',
            'vod_play_from': '$$$'.join(play_from),
            'vod_play_url': '$$$'.join(play_url),
        }
        return {'list': [vod]}

    def searchContent(self, key, quick, pg="1"):
        url = f'{self.host}/search.html?wd={urllib.parse.quote(key)}'
        rsp = self.fetch(url, headers=self.headers)
        videos = self.parse_list(rsp.text)
        return {
            'list': videos,
            'page': pg
        }

    def playerContent(self, flag, id, vipFlags):
        if id.startswith('http'):
            play_url = id
        else:
            play_url = self.host + id if id.startswith('/') else self.host + '/' + id

        if '.m3u8' in play_url:
            return {'parse': 0, 'url': play_url, 'header': self.headers}

        rsp = self.fetch(play_url, headers=self.headers)
        html = rsp.text

        m = re.search(r'<video[^>]*src="(https?://[^"]+?\.m3u8[^"]*)"', html)
        if m:
            return {'parse': 0, 'url': m.group(1), 'header': self.headers}

        m = re.search(r"""url\s*:\s*['"](https?://[^'"]+?\.m3u8[^'"]*)['"]""", html)
        if m:
            return {'parse': 0, 'url': m.group(1), 'header': self.headers}

        m = re.search(r'https?://[^\s\'"]+?\.m3u8[^\s\'"]*', html)
        if m:
            return {'parse': 0, 'url': m.group(0), 'header': self.headers}

        return {'parse': 1, 'url': play_url, 'header': self.headers}

    def localProxy(self, param):
        return None

    def liveContent(self, url):
        pass

    # ------------------------- 列表解析 -------------------------
    def parse_list(self, html):
        vlist = []
        seen = set()

        # pttplay: <a class="video-pic loading" data-original="//img.imgoss.space/..." href="/vod/xxx.html" title="标题">
        # pttplay: <a class="slide-pic swiper-lazy" data-background="//img.imgoss.space/..." href="/vod/xxx.html" title="标题">
        for m in re.finditer(r'<a[^>]*class="[^"]*(?:video-pic|slide-pic)[^"]*"[^>]*>', html, re.I):
            tag = m.group(0)

            href_m = re.search(r'href="(/vod/(\d+)\.html)"', tag)
            if not href_m:
                continue
            href = href_m.group(1)
            if href in seen:
                continue
            seen.add(href)

            title_m = re.search(r'title="([^"]+)"', tag)
            title = title_m.group(1).strip() if title_m else ''

            pic = self._extract_pic(tag)
            pic = self._fix_url(pic, self.host)

            remark = ''
            after = html[m.end():m.end() + 200]
            note_m = re.search(r'<span[^>]*class="[^"]*note[^"]*"[^>]*>([^<]+)</span>', after)
            if note_m:
                remark = note_m.group(1).strip()

            vlist.append({
                'vod_id': href,
                'vod_name': title,
                'vod_pic': pic,
                'vod_remarks': remark
            })

        return vlist[:30]


# ============================================================
# 本地调试用
# ============================================================
if __name__ == "__main__":
    import requests

    Spider.fetch = lambda self, url, headers=None, timeout=15: (
        (lambda r: (r.raise_for_status(), setattr(r, 'encoding', r.apparent_encoding or 'utf-8'), r)[2])
        (requests.get(url, headers=headers, timeout=timeout))
    )
    sp = Spider()
    sp.init()

    print("=" * 40)
    print("首页测试")
    print("=" * 40)
    home = sp.homeContent(False)
    print("分类:", [c['type_name'] for c in home.get('class', [])])
    for v in home.get('list', [])[:10]:
        print(f"  {v['vod_name']} [{v['vod_remarks']}] pic={v['vod_pic'] or '无'}")

    print("\n" + "=" * 40)
    print("搜索测试: 海贼王")
    print("=" * 40)
    search = sp.searchContent("海贼王", False)
    for v in search.get('list', [])[:5]:
        print(f"  {v['vod_name']} [{v['vod_remarks']}] pic={v['vod_pic'] or '无'}")

    print("\n" + "=" * 40)
    print("详情测试")
    print("=" * 40)
    if search.get('list'):
        first_id = search['list'][0]['vod_id']
        detail = sp.detailContent([first_id])
        vod = detail['list'][0]
        print(f"标题: {vod['vod_name']}")
        print(f"图片: {vod['vod_pic'] or '无'}")
        print(f"简介: {vod['vod_content'][:100] if vod['vod_content'] else '无'}")
        print(f"播放源: {vod['vod_play_from']}")
        print(f"源数量: {len(vod['vod_play_url'].split('$$$')) if vod['vod_play_url'] else 0}")
