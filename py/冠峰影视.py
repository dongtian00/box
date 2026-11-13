#coding=utf-8
import sys
import re
import json
import requests
sys.path.append('..')
from base.spider import Spider

class Spider(Spider):

    def __init__(self):
        super().__init__()
        self.site = 'https://www.cd-zj.com'
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://www.cd-zj.com/'
        })
        self.cateManual = {
            
            '腾讯SVIP': 'label/qq',
            '优酷SVIP': 'label/youku',
            'B站SVIP': 'label/bli',
        }

    def init(self, extend=""):
        pass

    def getName(self):
        return "枫叶4K备用"

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    def _clean(self, text):
        if not text:
            return ''
        text = re.sub(r'<[^>]+>', '', text)
        text = text.replace('&nbsp;', ' ').replace('&amp;', '&').replace('\u3000', ' ')
        text = ' '.join(text.split())
        return text.strip()

    def _get(self, url):
        try:
            r = self.session.get(url, timeout=15)
            r.encoding = 'utf-8'
            return r.text
        except:
            return ''

    def getVid(self, url):
        if not url:
            return ''
        m = re.search(r'/detail/(\d+)\.html', url)
        if m:
            return m.group(1)
        m = re.search(r'/play/(\d+)-', url)
        if m:
            return m.group(1)
        return ''

    def homeContent(self, filter):
        result = {'class': [], 'filters': {}, 'list': [], 'parse': 0, 'jx': 0}
        for k, v in self.cateManual.items():
            result['class'].append({'type_id': str(v), 'type_name': k})
        return result

    def homeVideoContent(self):
        videos = []
        try:
            html = self._get(self.site)
            seen = set()
            for m in re.finditer(r'class="public-list-exp"[^>]*href="([^"]+)"[^>]*title="([^"]*)"', html):
                href = m.group(1)
                title = m.group(2)
                vid = self.getVid(href)
                if not vid or vid in seen:
                    continue
                seen.add(vid)
                snippet = html[m.start():m.start()+500]
                pic = ''
                pm = re.search(r'data-src="([^"]+)"', snippet)
                if pm:
                    pic = pm.group(1).replace('&amp;', '&')
                note = ''
                nm = re.search(r'ft2">([^<]+)<', snippet)
                if nm:
                    note = nm.group(1)
                if title:
                    videos.append({
                        'vod_id': vid,
                        'vod_name': title,
                        'vod_pic': pic,
                        'vod_remarks': note
                    })
        except Exception as e:
            print(f'homeVideoContent error: {e}')
        return {'list': videos, 'parse': 0, 'jx': 0}

    def categoryContent(self, tid, pg, filter, extend):
        result = {'list': [], 'parse': 0, 'jx': 0}
        page = int(pg) if pg else 1
        try:
            if str(tid).startswith('label/'):
                if page == 1:
                    url = f'{self.site}/{tid}.html'
                else:
                    url = f'{self.site}/{tid}-{page}.html'
            else:
                if page == 1:
                    url = f'{self.site}/type/{tid}.html'
                else:
                    url = f'{self.site}/type/{tid}-{page}.html'

            html = self._get(url)
            seen = set()
            for m in re.finditer(r'class="public-list-exp"[^>]*href="([^"]+)"[^>]*title="([^"]*)"', html):
                href = m.group(1)
                title = m.group(2)
                vid = self.getVid(href)
                if not vid or vid in seen:
                    continue
                seen.add(vid)
                snippet = html[m.start():m.start()+500]
                pic = ''
                pm = re.search(r'data-src="([^"]+)"', snippet)
                if pm:
                    pic = pm.group(1).replace('&amp;', '&')
                note = ''
                nm = re.search(r'ft2">([^<]+)<', snippet)
                if nm:
                    note = nm.group(1)
                if title:
                    result['list'].append({
                        'vod_id': vid,
                        'vod_name': title,
                        'vod_pic': pic,
                        'vod_remarks': note
                    })
        except Exception as e:
            print(f'categoryContent error: {e}')

        result['page'] = page
        result['pagecount'] = page + 1 if len(result['list']) > 0 else page
        result['limit'] = len(result['list'])
        result['total'] = len(result['list'])
        return result

    def detailContent(self, ids):
        result = {'list': [], 'parse': 0, 'jx': 0}
        vid = ids[0] if ids else ''
        if not vid:
            return result
        try:
            html = self._get(f'{self.site}/detail/{vid}.html')

            title = ''
            tm = re.search(r'<title>《(.+?)》', html)
            if tm:
                title = tm.group(1)
            if not title:
                tm = re.search(r'<title>([^<]+)', html)
                if tm:
                    title = self._clean(tm.group(1))

            pic = ''
            pm = re.search(r'lazy1[^>]*data-src="([^"]+)"', html)
            if pm:
                pic = pm.group(1).replace('&amp;', '&')

            desc = ''
            dm = re.search(r'<meta name="description" content="(.+?)"', html)
            if dm:
                desc = dm.group(1).replace('剧情介绍：', '').strip()

            actor = ''
            director = ''
            info = re.search(r'slide-info(.*?)(?:anthology|swiper)', html, re.DOTALL)
            if info:
                block = info.group(1)
                am = re.search(r'主演[:：]\s*([^\n<]+)', block)
                if am:
                    actor = am.group(1).strip()
                dm2 = re.search(r'导演[:：]\s*([^\n<]+)', block)
                if dm2:
                    director = dm2.group(1).strip()

            play_from = []
            play_url = []

            tab_block = re.search(r'class="anthology-tab[^"]*"[^>]*>(.*?)</div>\s*</div>', html, re.DOTALL)
            if tab_block:
                tabs = re.findall(r'<a[^>]*class="swiper-slide"[^>]*>(.*?)</a>', tab_block.group(1), re.DOTALL)
            else:
                tabs = []

            panels = re.findall(r'class="anthology-list-box[^"]*"[^>]*>(.*?)</div>\s*</div>', html, re.DOTALL)

            for i, tab in enumerate(tabs):
                tab_name = self._clean(tab) or f'线路{i+1}'
                # 过滤：名称包含蓝光2k直接跳过该线路
                if "蓝光2k" in tab_name:
                    continue
                play_from.append(tab_name)
                episodes = []
                if i < len(panels):
                    for em in re.finditer(r'<a[^>]*href="([^"]+)"[^>]*>([^<]+)<', panels[i]):
                        ep_href = em.group(1)
                        ep_name = em.group(2).strip()
                        if ep_name and ep_href:
                            episodes.append(f'{ep_name}${ep_href}')
                # 反转，把剧集改为正序（1，2，3...）
                episodes.reverse()
                play_url.append('#'.join(episodes))

            vod = {
                'vod_id': vid,
                'vod_name': title,
                'vod_pic': pic,
                'type_name': '',
                'vod_year': '',
                'vod_area': '',
                'vod_remarks': '',
                'vod_actor': actor,
                'vod_director': director if director else '未知',
                'vod_content': desc,
                'vod_play_from': '$$$'.join(play_from) if play_from else '',
                'vod_play_url': '$$$'.join(play_url) if play_url else ''
            }
            result['list'].append(vod)
        except Exception as e:
            print(f'detailContent error: {e}')
        return result

    def playerContent(self, flag, id, vipFlags):
        result = {}
        try:
            play_url = id
            if id and not id.startswith('http'):
                play_url = self.site + id

            html = self._get(play_url)

            m = re.search(r'player_aaaa\s*=\s*(\{.+?\})\s*<', html)
            if m:
                try:
                    data = json.loads(m.group(1))
                    m3u8 = data.get('url', '')
                    if m3u8 and '.m3u8' in m3u8:
                        result['parse'] = 0
                        result['url'] = m3u8
                        result['jx'] = 0
                        result['header'] = {
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                            'Referer': self.site + '/'
                        }
                        return result
                except:
                    pass

            m = re.search(r'url":\s*"(https?://[^"]*\.m3u8[^"]*)"', html)
            if m:
                result['parse'] = 0
                result['url'] = m.group(1).replace('\\/', '/')
                result['jx'] = 0
                result['header'] = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Referer': self.site + '/'
                }
                return result

            m = re.search(r'<iframe[^>]+src="([^"]+)"', html)
            if m:
                result['parse'] = 1
                result['url'] = m.group(1)
                result['jx'] = 0
                result['header'] = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Referer': self.site + '/'
                }
            else:
                result['parse'] = 1
                result['url'] = play_url
                result['jx'] = 0
                result['header'] = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Referer': self.site + '/'
                }
        except Exception as e:
            print(f'playerContent error: {e}')
            result['parse'] = 1
            result['url'] = id
            result['jx'] = 0
            result['header'] = {}
        return result

    def searchContent(self, key, quick, pg='1'):
        result = {'list': [], 'parse': 0, 'jx': 0}
        page = int(pg) if pg else 1
        try:
            url = f'{self.site}/cupfox-search/-------------.html'
            params = {'wd': key}
            if page > 1:
                params['page'] = page

            html = self._get(url)
            seen = set()
            for m in re.finditer(r'href="(/detail/\d+\.html)"[^>]*title="([^"]*)"', html):
                href = m.group(1)
                title = m.group(2)
                vid = self.getVid(href)
                if not vid or vid in seen:
                    continue
                seen.add(vid)
                snippet = html[m.start():m.start()+500]
                pic = ''
                pm = re.search(r'data-src="([^"]+)"', snippet)
                if pm:
                    pic = pm.group(1).replace('&amp;', '&')
                note = ''
                nm = re.search(r'ft2">([^<]+)<', snippet)
                if nm:
                    note = nm.group(1)
                if title:
                    result['list'].append({
                        'vod_id': vid,
                        'vod_name': title,
                        'vod_pic': pic,
                        'vod_remarks': note
                    })
        except Exception as e:
            print(f'searchContent error: {e}')
        return result

    def localProxy(self, params):
        return [200, "video/MP2T", {}, ""]
