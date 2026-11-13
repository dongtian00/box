# coding=utf-8
"""
目标站: 青麦视频 (qingmaisp.com)
版本: 15.0 - localProxy本地代理方案，绕开CDN 302和Content-Type问题
"""
import sys, json, time, urllib.request, urllib.error
from urllib.parse import quote, unquote, urljoin
sys.path.append('..')
from base.spider import Spider

class Spider(Spider):
    def init(self, extend=""):
        self.site_url = "https://qingmaisp.com"
        self.api_base = self.site_url + "/api/v1/pc"
        self.auth_base = self.site_url + "/api/auth"
        self.device_id = "tvbox" + str(int(time.time() * 1000))
        self.token = ""
        self.categories = []
        self.QUALITIES = ["4K","FHD","HD","LD","SD"]
        self.UA = 'Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36'

    def _post(self, url, data, headers=None):
        """使用urllib.request发送POST请求"""
        try:
            h = {
                'User-Agent': self.UA,
                'Content-Type': 'application/json;charset=UTF-8',
                'Referer': self.site_url + "/",
                'Origin': self.site_url,
                'client': 'pc',
                'useclient': 'pc',
                'deviceId': self.device_id,
                'devicetype': 'web',
            }
            if headers:
                h.update(headers)
            req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers=h, method='POST')
            resp = urllib.request.urlopen(req, timeout=15)
            return json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            print(f"[qm] post err: {e}")
            return None

    def _get_token(self):
        try:
            url = self.auth_base + "/deviceIdLogin?deviceId=" + self.device_id
            r = self._post(url, {"deviceId": self.device_id})
            if r and r.get("code") == 200:
                self.token = r.get("data", "")
                return True
        except: pass
        return False

    def _api(self, path, data=None, need_token=False):
        try:
            h = {}
            if need_token:
                if not self.token:
                    self._get_token()
                if self.token:
                    h['token'] = self.token
            return self._post(self.api_base + path, data or {}, h)
        except: return None

    def _get(self, url, timeout=20):
        """GET请求，返回(status, content_type, body_bytes)"""
        try:
            h = {
                'User-Agent': self.UA,
                'Referer': self.site_url + "/",
                'Accept': '*/*',
            }
            req = urllib.request.Request(url, headers=h, method='GET')
            resp = urllib.request.urlopen(req, timeout=timeout)
            body = resp.read()
            ctype = resp.headers.get('Content-Type', 'application/octet-stream')
            return resp.status, ctype, body
        except urllib.error.HTTPError as e:
            return e.code, e.headers.get('Content-Type', 'text/plain'), b''
        except Exception as e:
            print(f"[qm] get err: {e}")
            return 500, 'text/plain', str(e).encode('utf-8')

    def _fix_pic(self, url):
        if not url: return ""
        if url.startswith("//"): return "https:" + url
        return url

    def _get_cats(self):
        if self.categories: return self.categories
        cats = []
        try:
            r = self._api("/index/columnPage", {})
            if r and r.get("code")==200:
                for c in r.get("data",[]):
                    t,n = c.get("id",""),c.get("name","")
                    if t and n: cats.append({"type_id":t,"type_name":n})
        except: pass
        if cats: self.categories = cats; return cats
        self.categories = [{"type_id":"M16","type_name":"电影"},{"type_id":"M15","type_name":"电视剧"},{"type_id":"M17","type_name":"动漫"},{"type_id":"M18","type_name":"综艺"},{"type_id":"M416","type_name":"纪录片"}]
        return self.categories

    def _parse_url(self, s):
        m = {}
        if not s: return m
        for p in s.split("～"):
            p = p.strip()
            if "*" in p:
                c,u = p.split("*",1)
                m[c.strip()] = u.strip()
        return m

    def _find_best(self, cm):
        for q in ["4K","FHD","HD","LD","SD"]:
            if q in cm: return cm[q]
        if cm: return list(cm.values())[0]
        return ""

    def _proxy_url(self, media_url, referer=''):
        """生成TVBox本地代理URL"""
        if not hasattr(self, 'getProxyUrl'):
            return media_url
        try:
            base = self.getProxyUrl()
            ref = referer or self.site_url + "/"
            return base + '&url=' + quote(media_url, safe='') + '&referer=' + quote(ref, safe='')
        except Exception:
            return media_url

    def homeContent(self, filter):
        try:
            cats = self._get_cats()
            vlist, seen = [], set()
            for cat in cats[:5]:
                r = self._api("/screen/screenMovie", {"condition":{"typeId":cat["type_id"],"source":"0","sreecnTypeEnum":"NEWEST"},"pageNum":1,"pageSize":12})
                if r and r.get("code")==200:
                    for item in r.get("data",{}).get("records",[]):
                        vid = str(item.get("id",""))
                        if vid and vid not in seen:
                            seen.add(vid)
                            vt = item.get("typeId","")
                            vlist.append({"vod_id":vid+"|"+vt if vt else vid,"vod_name":item.get("name",""),"vod_pic":self._fix_pic(item.get("cover","")),"vod_remarks":item.get("remarks",""),"vod_year":item.get("year","")})
            return {"class":cats,"list":vlist[:30],"filters":{}}
        except: return {"class":self._get_cats(),"list":[],"filters":{}}

    def homeVideoContent(self): return self.homeContent(False)

    def categoryContent(self, tid, pg, filter, extend):
        page = int(pg) if pg else 1; limit = 24
        cond = {"typeId":tid,"source":"0","sreecnTypeEnum":"NEWEST"}
        vlist, total, pc = [], 0, page
        try:
            r = self._api("/screen/screenMovie", {"condition":cond,"pageNum":page,"pageSize":limit})
            if r and r.get("code")==200:
                for item in r.get("data",{}).get("records",[]):
                    vid = str(item.get("id",""))
                    if vid:
                        vt = item.get("typeId","")
                        vlist.append({"vod_id":vid+"|"+vt if vt else vid,"vod_name":item.get("name",""),"vod_pic":self._fix_pic(item.get("cover","")),"vod_remarks":item.get("remarks",""),"vod_year":item.get("year","")})
                total = r.get("data",{}).get("total",len(vlist))
                if total>0: pc = (total+limit-1)//limit
        except: pass
        return {"list":vlist,"page":page,"pagecount":pc or page,"limit":limit,"total":total or (pc*limit)}

    def detailContent(self, ids):
        if not ids: return {"list":[]}
        raw = ids[0].split("|")
        vid = raw[0]
        vt = raw[1] if len(raw)>1 else ""
        vn, vp, vc, va, vd, vr, vy, vs = vid, "", "", "", "", "", "", ""
        try:
            desc = self._api("/play/movieDesc", {"id":vid,"playerId":93,"episodeId":None,"typeId":vt}, need_token=True)
            det = self._api("/play/movieDetails", {"id":vid,"playerId":93,"episodeId":None,"typeId":vt}, need_token=True)
            if desc and desc.get("code")==200:
                d = desc.get("data",{})
                vn = d.get("name",vid); vp = self._fix_pic(d.get("cover","")); vc = d.get("introduce","")
                va = d.get("star",""); vd = d.get("director",""); vr = d.get("area",""); vy = d.get("year",""); vs = d.get("remarks","")
            if det and det.get("code")==200:
                dd = det.get("data",{})
                if vn==vid: vn = dd.get("name",vid)
                eps = dd.get("episodeList",[])
                if eps:
                    cm = self._parse_url(dd.get("url",""))
                    pf, pu = [], []
                    for q in self.QUALITIES:
                        if q in cm:
                            pf.append(q)
                            ep_parts = []
                            is_movie = (len(eps) <= 1)
                            for ep in eps[:50]:
                                ep_label = str(ep.get("episode","") or ep.get("episodeNum","") or "?")
                                if is_movie:
                                    en = "正片" if ep.get("episodeNum") in (None,"1","正片") else (ep_label if not ep_label.isdigit() else "正片")
                                else:
                                    en = "第"+str(ep.get("episodeNum","") or ep.get("episode","") or "?")+"集"
                                ep_parts.append(en + "$" + vid + "|" + vt + "|" + str(ep.get("id","")) + "|" + q)
                            pu.append("#".join(ep_parts))
                    if not pf:
                        pf.append("青麦")
                        ep_parts = []
                        for ep in eps[:50]:
                            en = "第"+str(ep.get("episodeNum","") or ep.get("episode","") or "?")+"集"
                            ep_parts.append(en + "$" + vid + "|" + vt + "|" + str(ep.get("id","")) + "|auto")
                        pu.append("#".join(ep_parts))
                    if pf and pu:
                        return {"list":[{"vod_id":vid,"vod_name":vn,"vod_pic":vp,"vod_content":vc,"vod_actor":va,"vod_director":vd,"vod_area":vr,"vod_year":vy,"vod_remarks":vs,"vod_play_from":"$$$".join(pf),"vod_play_url":"$$$".join(pu)}]}
        except: pass
        return {"list":[{"vod_id":vid,"vod_name":vn,"vod_pic":vp,"vod_content":vc,"vod_actor":va,"vod_director":vd,"vod_area":vr,"vod_year":vy,"vod_remarks":vs,"vod_play_from":"青麦","vod_play_url":"播放$"+vid}]}

    def searchContent(self, key, quick, pg="1"):
        page = int(pg) if pg else 1; limit = 24
        vlist, pc = [], page
        try:
            r = self._api("/search/searchMovie", {"condition":{"value":key},"pageNum":page,"pageSize":limit})
            if r and r.get("code")==200:
                for item in r.get("data",{}).get("records",[]):
                    vid = str(item.get("id",""))
                    if vid:
                        vt = item.get("typeId","")
                        vlist.append({"vod_id":vid+"|"+vt if vt else vid,"vod_name":item.get("name",""),"vod_pic":self._fix_pic(item.get("cover","")),"vod_remarks":item.get("remarks","")})
                total = r.get("data",{}).get("total",len(vlist))
                if total>0: pc = (total+limit-1)//limit
        except: pass
        return {"list":vlist,"page":page,"pagecount":pc or page,"limit":limit,"total":pc*limit}

    def playerContent(self, flag, id, vipFlags):
        play_url = id
        if "|" in play_url:
            parts = play_url.split("|")
            vod_id = parts[0]
            type_id = parts[1] if len(parts)>1 else ""
            ep_id = parts[2] if len(parts)>2 else ""
            quality = parts[3] if len(parts)>3 else "auto"
            if ep_id:
                try:
                    h = {}
                    if not self.token: self._get_token()
                    if self.token: h['token'] = self.token
                    r = self._post(self.api_base + "/play/movieDetails", {"id":vod_id,"playerId":93,"episodeId":int(ep_id) if ep_id.isdigit() else None,"typeId":type_id}, h)
                    if r and r.get("code")==200:
                        cm = self._parse_url(r.get("data",{}).get("url",""))
                        if quality != "auto" and quality in cm:
                            play_url = cm[quality]
                        else:
                            play_url = self._find_best(cm)
                        if play_url.startswith("//"): play_url = "https:" + play_url
                except: pass
        if play_url and not play_url.startswith("http"):
            if play_url.startswith("//"): play_url = "https:" + play_url
            elif play_url.startswith("/"): play_url = self.site_url + play_url
        # 通过localProxy代理m3u8，绕开CDN 302和错误Content-Type
        proxy = self._proxy_url(play_url)
        return {"parse": 0, "url": proxy, "header": {"User-Agent": self.UA, "Referer": self.site_url+"/"}}

    def localProxy(self, param):
        """本地代理：下载m3u8/TS，改写地址返回标准格式"""
        try:
            # 解析参数（dict或query string）
            raw_url = ''
            referer = self.site_url + "/"
            if isinstance(param, dict):
                raw_url = param.get('url', '') or param.get('u', '')
                referer = param.get('referer', '') or param.get('ref', '') or referer
            elif isinstance(param, str):
                import urllib.parse as up
                qs = up.parse_qs(param)
                raw_url = qs.get('url', [''])[0] or qs.get('u', [''])[0]
                referer = qs.get('referer', [''])[0] or qs.get('ref', [''])[0] or referer
            media_url = unquote(raw_url) if raw_url else ''
            referer = unquote(referer) if referer else self.site_url + "/"
            if not media_url:
                return [404, 'text/plain', b'not found']

            status, ctype, body = self._get(media_url, timeout=30)
            if status != 200:
                return [status, 'text/plain', b'fetch failed']

            # m3u8内容：改写TS地址为代理URL
            try:
                text = body.decode('utf-8')
            except Exception:
                text = ''
            if '#EXTM3U' in text:
                out = []
                for line in text.splitlines():
                    s = line.strip()
                    if not s or s.startswith('#'):
                        out.append(line)
                    else:
                        abs_url = urljoin(media_url, s)
                        out.append(self._proxy_url(abs_url, referer))
                data = '\n'.join(out).encode('utf-8')
                return [200, 'application/x-mpegURL', data]

            # 媒体分片（TS）：直接返回
            return [200, ctype or 'application/octet-stream', body]
        except Exception as e:
            print(f"[qm] localProxy err: {e}")
            return [500, 'text/plain', str(e).encode('utf-8')]

    def isVideoFormat(self, url):
        import re
        return bool(re.search(r'\.(m3u8|mp4|flv|mkv|avi)(\?|$)', url or '', re.I))

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass