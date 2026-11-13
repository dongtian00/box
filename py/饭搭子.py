# -*- coding: utf-8 -*-
# 饭搭子影视 Spider
# 兼容 FongMi/TV (T3) & WebHomeTV / PeekPro (T4)
#
# 数据源: Apple CMS API (fdzys.net)
# 发布页: fff666.site / fff666.xyz / fdzys666.xyz

import sys
import json
import re
import urllib.parse

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


class Spider(Spider):
    """
    饭搭子影视 Spider（Apple CMS API）

    发布页: fff666.site / fff666.xyz / fdzys666.xyz
    内容域名由发布页自动发现（当前: fdzys.net）
    """

    # ===== 内容域名（主域名在前） =====
    content_hosts = [
        'https://fdzys.net',
        'https://fdzys.com',
    ]

    # ===== 发布页（仅当内容域名全挂时才去发现新域名） =====
    publish_pages = [
        'https://fff666.site',
        'https://fff666.xyz',
        'https://fdzys666.xyz',
    ]

    host = 'https://fdzys.net'
    _discovered = False
    _api_path = '/api.php/provide/vod/'

    header = {
        'User-Agent': 'Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36',
        'Accept': 'application/json, text/html, */*',
        'Accept-Language': 'zh-CN,zh;q=0.9',
    }

    # ===== 播放源名称映射（拼音 → 网站显示名） =====
    play_source_names = {
        'hnm3u8': '红牛云',
        'ffm3u8': '非凡云',
        'dytt': '天堂云',
        'rym3u8': '星河云',
        'ruyi': '如意云',
        'wjm3u8': '无尽云',
        'qiyi': '爱奇艺',
        'liangzi': '量子云',
        '1080zyk': '优质云',
        'wsym3u8': '卫士云',
        'youku': '优酷',
        'qq': '腾讯',
        'bilibili': '哔哩哔哩',
    }

    # ===== 父分类（对齐站点实际导航） =====
    classes = [
        {'type_name': '电视剧', 'type_id': '2'},
        {'type_name': '电影', 'type_id': '1'},
        {'type_name': '动漫', 'type_id': '3'},
        {'type_name': '综艺', 'type_id': '4'},
        {'type_name': '体育', 'type_id': '5'},
        {'type_name': '短剧', 'type_id': '46'},
    ]

    # ===== 子类型 → type_id 映射 =====
    sub_type_map = {
        '动作': '6', '喜剧': '7', '爱情': '8', '科幻': '9',
        '恐怖片': '10', '剧情': '11', '战争': '12',
        '国产剧': '13', '欧美剧': '14', '日本剧': '15', '韩国剧': '16',
        '国漫': '20', '日韩': '21', '欧美': '22', '港台': '23', '海外': '24',
        '大陆': '25', '港台综艺': '26', '日韩综艺': '27', '欧美综艺': '28',
        '足球': '29', '篮球': '30', '网球': '31', '斯诺克': '32',
    }

    _year_list = [
        {'n': '全部', 'v': ''},
        {'n': '2026', 'v': '2026'}, {'n': '2025', 'v': '2025'},
        {'n': '2024', 'v': '2024'}, {'n': '2023', 'v': '2023'},
        {'n': '2022', 'v': '2022'}, {'n': '2021', 'v': '2021'},
        {'n': '2020', 'v': '2020'}, {'n': '2019', 'v': '2019'},
    ]

    filters = {
        '1': [
            {'key': 'class', 'name': '类型', 'value': [
                {'n': '全部', 'v': ''}, {'n': '动作', 'v': '动作'},
                {'n': '喜剧', 'v': '喜剧'}, {'n': '爱情', 'v': '爱情'},
                {'n': '科幻', 'v': '科幻'}, {'n': '恐怖片', 'v': '恐怖片'},
                {'n': '剧情', 'v': '剧情'}, {'n': '战争', 'v': '战争'},
            ]},
            {'key': 'year', 'name': '年份', 'value': _year_list},
        ],
        '2': [
            {'key': 'class', 'name': '类型', 'value': [
                {'n': '全部', 'v': ''}, {'n': '国产剧', 'v': '国产剧'},
                {'n': '欧美剧', 'v': '欧美剧'}, {'n': '日本剧', 'v': '日本剧'},
                {'n': '韩国剧', 'v': '韩国剧'},
            ]},
            {'key': 'year', 'name': '年份', 'value': _year_list},
        ],
        '3': [
            {'key': 'class', 'name': '类型', 'value': [
                {'n': '全部', 'v': ''}, {'n': '国漫', 'v': '国漫'},
                {'n': '日韩', 'v': '日韩'}, {'n': '欧美', 'v': '欧美'},
                {'n': '港台', 'v': '港台'}, {'n': '海外', 'v': '海外'},
            ]},
            {'key': 'year', 'name': '年份', 'value': _year_list},
        ],
        '4': [
            {'key': 'class', 'name': '类型', 'value': [
                {'n': '全部', 'v': ''}, {'n': '大陆', 'v': '大陆'},
                {'n': '港台综艺', 'v': '港台综艺'}, {'n': '日韩综艺', 'v': '日韩综艺'},
                {'n': '欧美综艺', 'v': '欧美综艺'},
            ]},
            {'key': 'year', 'name': '年份', 'value': _year_list},
        ],
        '5': [
            {'key': 'class', 'name': '类型', 'value': [
                {'n': '全部', 'v': ''}, {'n': '足球', 'v': '足球'},
                {'n': '篮球', 'v': '篮球'}, {'n': '网球', 'v': '网球'},
                {'n': '斯诺克', 'v': '斯诺克'},
            ]},
        ],
        '46': [
            {'key': 'year', 'name': '年份', 'value': _year_list},
        ],
    }

    # ===================================================================
    #  基础方法
    # ===================================================================

    def getName(self):
        return '饭搭子影视'

    def init(self, extend=''):
        if isinstance(extend, list):
            self.extend = ''
        else:
            self.extend = extend or ''
        self.host = self.content_hosts[0]
        self._discovered = False

    def isVideoFormat(self, url):
        return any(x in url for x in ['.m3u8', '.mp4', '.flv', '.avi', '.mkv', 'm3u8'])

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    # ===================================================================
    #  请求封装
    # ===================================================================

    def _get_header(self, host=None):
        h = dict(self.header)
        h['Referer'] = (host or self.host) + '/'
        return h

    def _discover_domains(self):
        """从发布页发现新域名（仅当所有已知域名都失败时调用）"""
        if self._discovered:
            return
        self._discovered = True
        for page_url in self.publish_pages:
            try:
                r = self.fetch(page_url, headers=self.header)
                html = r.text if hasattr(r, 'text') else r.content.decode('utf-8', errors='ignore')
                urls = re.findall(r"url:\s*['\"](https?://[^'\"]+)['\"]", html)
                for u in urls:
                    u = u.rstrip('/')
                    if any(skip in u for skip in ['t.me', 'umami', 'fff666', 'fdzys666',
                                                   '你的', 'example', 'your', 'domain']):
                        continue
                    if not re.match(r'https?://[a-zA-Z0-9\-]+\.[a-zA-Z]{2,}', u):
                        continue
                    if u not in self.content_hosts:
                        self.content_hosts.append(u)
                if urls:
                    break
            except Exception:
                continue

    def _build_api_url(self, host, params):
        """手动拼接 API URL 和查询参数（不依赖 requests 的 params）"""
        # 确保所有参数都是字符串
        str_params = {k: str(v) for k, v in params.items()}
        query = urllib.parse.urlencode(str_params)
        return host + self._api_path + '?' + query

    def _api_fetch(self, params):
        """通过 Apple CMS API 获取数据（不永久拉黑域名，每次都尝试）"""
        # 构建尝试顺序：当前 host 在前，其余在后
        all_hosts = list(self.content_hosts)
        if self.host in all_hosts:
            all_hosts.remove(self.host)
            all_hosts.insert(0, self.host)

        for h in all_hosts:
            try:
                url = self._build_api_url(h, params)
                r = self.fetch(url, headers=self._get_header(h))
                text = r.text if hasattr(r, 'text') else r.content.decode('utf-8', errors='ignore')
                data = json.loads(text)
                if data.get('code') == 1:
                    self.host = h
                    return data
            except Exception:
                continue

        # 所有已知域名失败，尝试发现新域名后重试
        if not self._discovered:
            self._discover_domains()
            for h in self.content_hosts:
                if h in all_hosts:
                    continue
                try:
                    url = self._build_api_url(h, params)
                    r = self.fetch(url, headers=self._get_header(h))
                    text = r.text if hasattr(r, 'text') else r.content.decode('utf-8', errors='ignore')
                    data = json.loads(text)
                    if data.get('code') == 1:
                        self.host = h
                        return data
                except Exception:
                    continue

        return None

    # ===================================================================
    #  首页
    # ===================================================================

    def homeContent(self, filter):
        return {
            'class': self.classes,
            'filters': self.filters,
        }

    def homeVideoContent(self):
        """首页推荐"""
        data = self._api_fetch({'ac': 'detail', 'pg': 1})
        if data and data.get('list'):
            vod_list = [self._api_vod_to_card(item) for item in data['list'][:30]]
            return {'list': vod_list}
        return {'list': []}

    # ===================================================================
    #  分类内容（用 ac=detail 获取封面）
    # ===================================================================

    def categoryContent(self, tid, pg, filter, extend):
        try:
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

            cls = ext.get('class', '')
            year = ext.get('year', '')

            actual_tid = tid
            if cls and cls in self.sub_type_map:
                actual_tid = self.sub_type_map[cls]

            # 父分类且无子类型筛选时，使用多页合并过滤解说/预告
            if tid in ('1', '2', '3', '4', '5') and not cls:
                return self._category_filtered(tid, pg, year)

            # 子分类直接请求（无解说问题）
            params = {'ac': 'detail', 't': actual_tid, 'pg': pg}
            if year:
                params['year'] = year

            data = self._api_fetch(params)
            if data:
                vod_list = [self._api_vod_to_card(item) for item in data.get('list', [])]
                return {
                    'page': int(data.get('page', pg)),
                    'pagecount': int(data.get('pagecount', 1)),
                    'limit': int(data.get('limit', len(vod_list))),
                    'total': int(data.get('total', len(vod_list))),
                    'list': vod_list,
                }

            return {'page': pg, 'pagecount': 1, 'limit': 20, 'total': 0, 'list': []}
        except Exception:
            return {'page': pg, 'pagecount': 1, 'limit': 20, 'total': 0, 'list': []}

    def _category_filtered(self, tid, pg, year):
        """父分类多页合并：过滤解说/预告后返回正片内容

        API 返回的内容约 84% 是「电影解说」，单页 20 条过滤后仅剩 ~3 条。
        此方法每显示页取最多 8 个 API 页，合并过滤后返回 20 条正片，
        各显示页覆盖不重叠的 API 页区间以避免重复。
        """
        MAX_API_PAGES = 8
        start_api_pg = (pg - 1) * MAX_API_PAGES + 1

        all_clean = []
        api_pagecount = 1

        for offset in range(MAX_API_PAGES):
            api_pg = start_api_pg + offset
            params = {'ac': 'detail', 't': tid, 'pg': api_pg}
            if year:
                params['year'] = year

            data = self._api_fetch(params)
            if not data or not data.get('list'):
                break

            api_pagecount = int(data.get('pagecount', 1))
            for item in data['list']:
                name = item.get('vod_name', '')
                if '解说' not in name and '预告' not in name:
                    all_clean.append(self._api_vod_to_card(item))

            if len(all_clean) >= 20:
                break

        display_pagecount = max(1, api_pagecount // MAX_API_PAGES)

        return {
            'page': pg,
            'pagecount': display_pagecount,
            'limit': 20,
            'total': display_pagecount * 20,
            'list': all_clean[:20],
        }

    # ===================================================================
    #  详情页
    # ===================================================================

    def detailContent(self, ids):
        try:
            vod_id = ids[0] if isinstance(ids, list) else str(ids)

            data = self._api_fetch({'ac': 'detail', 'ids': vod_id})
            if data and data.get('list'):
                item = data['list'][0]
                vod = {
                    'vod_id': str(item.get('vod_id', vod_id)),
                    'vod_name': item.get('vod_name', ''),
                    'vod_pic': self._fix_pic(item.get('vod_pic', '')),
                    'type_name': item.get('type_name', ''),
                    'vod_year': item.get('vod_year', ''),
                    'vod_area': item.get('vod_area', ''),
                    'vod_director': item.get('vod_director', ''),
                    'vod_actor': item.get('vod_actor', ''),
                    'vod_content': self._clean_html(item.get('vod_content', '')),
                    'vod_remarks': item.get('vod_remarks', ''),
                    'vod_play_from': self._convert_play_from(item.get('vod_play_from', '')),
                    'vod_play_url': item.get('vod_play_url', ''),
                }
                return {'list': [vod]}

            return {'list': []}
        except Exception:
            return {'list': []}

    # ===================================================================
    #  搜索
    # ===================================================================

    def searchContent(self, key, quick, pg=1):
        try:
            pg = int(pg or 1)
            data = self._api_fetch({'ac': 'detail', 'wd': key, 'pg': pg})
            if data and data.get('list'):
                return [self._api_vod_to_card(item) for item in data['list']]
            return []
        except Exception:
            return []

    # ===================================================================
    #  播放
    # ===================================================================

    def playerContent(self, flag, id, vipFlags):
        try:
            if not id.startswith('http'):
                return {}

            # B站: 通过API获取直链, 回退到嵌入播放器嗅探
            if 'bilibili.com' in id:
                result = self._resolve_bilibili(id)
                if result:
                    return result

            # 爱奇艺/优酷/腾讯/芒果 等网页链接需要通过解析器播放
            if 'iqiyi.com' in id or 'youku.com' in id or 'v.qq.com' in id or 'mgtv.com' in id:
                # 使用 web 解析器, 让播放器嗅探出 m3u8
                parse_url = 'https://jx.xmflv.com/?url=' + urllib.parse.quote(id, safe='')
                return {
                    'parse': 1,
                    'url': parse_url,
                    'header': {'User-Agent': self.header['User-Agent']},
                }

            # 分享页 URL（天堂云/量子云/如意云等）需要提取真实 m3u8
            if '/share/' in id:
                return self._parse_share_url(id)

            # 直接 m3u8/mp4 链接
            play_header = {
                'User-Agent': self.header['User-Agent'],
                'Referer': self.host + '/',
            }
            result = {
                'parse': 0,
                'url': id,
                'header': play_header,
            }
            if '.m3u8' in id:
                result['format'] = 'application/x-mpegURL'
                result['contentType'] = 'application/x-mpegURL'
                result['header']['MiaiHeader'] = json.dumps({
                    'User-Agent': self.header['User-Agent'],
                    'Referer': self.host + '/',
                })
            return result
        except Exception:
            return {}

    def _parse_share_url(self, share_url):
        """从分享页 HTML 中提取真实 m3u8 地址"""
        try:
            r = self.fetch(share_url, headers=self._get_header())
            html = r.text if hasattr(r, 'text') else r.content.decode('utf-8', errors='ignore')

            # 分享页 JS 中的 m3u8 路径变量：
            #   const url = "/xxx/index.m3u8?sign=..."
            #   var main = "/xxx/index.m3u8?sign=..."
            #   var main = "\/xxx\/index.m3u8?sign=..."
            m3u8_path = None

            m = re.search(r'(?:const\s+url|var\s+main)\s*=\s*["\']([^"\']*\.m3u8[^"\']*)["\']', html)
            if m:
                m3u8_path = m.group(1).replace('\\/', '/')

            if not m3u8_path:
                m = re.search(r'["\']([^"\']*\.m3u8[^"\']*)["\']', html)
                if m:
                    m3u8_path = m.group(1).replace('\\/', '/')

            if not m3u8_path:
                # 提取失败，返回 parse=1 让播放器自己处理
                return {
                    'parse': 1,
                    'url': share_url,
                    'header': {'User-Agent': self.header['User-Agent']},
                }

            # 拼接完整 URL
            if m3u8_path.startswith('http'):
                video_url = m3u8_path
            else:
                # 从分享页 URL 提取 origin
                parts = share_url.split('/')
                origin = 'https://' + parts[2]
                video_url = origin + m3u8_path

            # Referer 使用分享页的 origin (而非完整 URL)
            share_origin = 'https://' + share_url.split('/')[2]

            play_header = {
                'User-Agent': self.header['User-Agent'],
                'Referer': share_origin + '/',
            }

            return {
                'parse': 0,
                'url': video_url,
                'header': play_header,
                'format': 'application/x-mpegURL',
                'contentType': 'application/x-mpegURL',
                # MiaiHeader 供 FongMi/TV 内核使用
                'MiaiHeader': play_header,
            }
        except Exception:
            return {
                'parse': 1,
                'url': share_url,
                'header': {'User-Agent': self.header['User-Agent']},
            }

    def _resolve_bilibili(self, url):
        """解析B站视频URL，获取m3u8直链

        通过饭搭子站点的麒麟播放器(svip.qlplayer.cyou)解析:
        1. 加载播放器页面(Referer=fdzys.net通过授权), 获取apiToken和session cookie
        2. 调用resolve.php获取m3u8直链
        3. 失败时回退到parse=1让播放器嗅探

        注意: 必须用requests.Session保持cookie, self.fetch不支持session
        """
        try:
            import requests as _rq
        except ImportError:
            _rq = None

        if _rq:
            try:
                sess = _rq.Session()
                sess.headers.update({'User-Agent': self.header['User-Agent']})

                # Step 1: 加载播放器页面 (Referer=fdzys.net通过域名授权)
                player_url = ('https://svip.qlplayer.cyou/?url=%s&autoplay=1&muted=1'
                              % urllib.parse.quote(url, safe=''))
                r = sess.get(player_url, headers={'Referer': self.host + '/'},
                             timeout=15, verify=False)

                # 提取 apiToken
                token_match = re.search(r'apiToken:\s*"([^"]+)"', r.text)
                if token_match:
                    api_token = token_match.group(1)

                    # Step 2: resolve.php (同session自动带cookie)
                    resolve_url = ('https://svip.qlplayer.cyou/api/resolve.php?token=%s'
                                   % api_token)
                    r2 = sess.get(resolve_url,
                                  headers={'Referer': 'https://svip.qlplayer.cyou/'},
                                  timeout=15, verify=False)
                    resolve_data = r2.json()

                    if resolve_data.get('code') == 200 and resolve_data.get('url'):
                        m3u8_url = resolve_data['url']
                        play_header = {
                            'User-Agent': self.header['User-Agent'],
                            'Referer': 'https://svip.qlplayer.cyou/',
                            'Origin': 'https://svip.qlplayer.cyou',
                        }
                        return {
                            'parse': 0,
                            'url': m3u8_url,
                            'header': play_header,
                            'format': 'application/x-mpegURL',
                            'contentType': 'application/x-mpegURL',
                            'MiaiHeader': json.dumps(play_header),
                        }
            except Exception:
                pass

        # requests不可用或解析失败, 回退到 parse=1 让播放器嗅探
        parse_url = ('https://svip.qlplayer.cyou/?url=%s&autoplay=1&muted=1'
                     % urllib.parse.quote(url, safe=''))
        return {
            'parse': 1,
            'url': parse_url,
            'header': {
                'User-Agent': self.header['User-Agent'],
                'Referer': self.host + '/',
            },
        }

    def _build_bilibili_embed(self, url):
        """从bilibili URL构建嵌入播放器URL (备用方案)

        支持两种格式:
          https://www.bilibili.com/bangumi/play/epXXXXX  → ep_id
          https://www.bilibili.com/video/BVXXXXX          → bvid
        """
        # ep格式 (番剧/电影)
        m = re.search(r'ep(\d+)', url)
        if m:
            ep_id = m.group(1)
            return ('https://player.bilibili.com/player.html?ep_id=%s'
                    '&high_quality=1&autoplay=true&as_wide=1' % ep_id)

        # BV格式 (普通视频)
        m = re.search(r'(BV[\w]+)', url)
        if m:
            bvid = m.group(1)
            return ('https://player.bilibili.com/player.html?bvid=%s'
                    '&high_quality=1&autoplay=true&as_wide=1' % bvid)

        return None

    # ===================================================================
    #  辅助方法
    # ===================================================================

    def _convert_play_from(self, play_from):
        """将播放源拼音名称转换为网站显示的中文名"""
        if not play_from:
            return ''
        sources = play_from.split('$$$')
        names = []
        for s in sources:
            names.append(self.play_source_names.get(s, s))
        return '$$$'.join(names)

    def _api_vod_to_card(self, item):
        return {
            'vod_id': str(item.get('vod_id', '')),
            'vod_name': item.get('vod_name', ''),
            'vod_pic': self._fix_pic(item.get('vod_pic', '')),
            'vod_remarks': item.get('vod_remarks', ''),
        }

    def _fix_pic(self, pic):
        """修复封面URL: fdzys.com已挂需替换为fdzys.net, 同时修复双斜杠"""
        if not pic:
            return ''
        # fdzys.com 域名已失效, 替换为 fdzys.net
        pic = pic.replace('fdzys.com', 'fdzys.net')
        # 修复双斜杠路径 (https://xxx//upload -> https://xxx/upload)
        pic = re.sub(r'(https?://[^/]+)//+', r'\1/', pic)
        return pic

    def _clean_html(self, text):
        if not text:
            return ''
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text
