# -*- coding: utf-8 -*-
import json
import re
import time
from urllib.parse import quote

try:
    import requests
except Exception:
    requests = None

try:
    from base.spider import Spider as BaseSpider
except Exception:
    class BaseSpider(object):
        pass


class Spider(BaseSpider):
    # 多多追剧 接口域名列表（按优先级排序）
    HOSTS = [
        "https://323433ssdfd.top",
        "https://duoduosdf12223234334.top",
        "https://xds2435u23422342342u.top",
        "https://dduotv01.top",
    ]

    # 新版 web API 签名（来自前端 JS 逆向）
    X_CLIENT = "8f3d2a1c7b6e5d4c9a0b1f2e3d4c5b6a"
    WEB_SIGN = "ddtvf65f3a83d6d9ad6f"

    def getName(self):
        return "三秋影视"

    def init(self, extend=""):
        host = self.HOSTS[0]
        if isinstance(extend, dict):
            host = str(extend.get("host", host) or host)
        elif isinstance(extend, str) and extend.strip():
            text = extend.strip()
            if text.startswith("http"):
                host = text
            else:
                try:
                    obj = json.loads(text)
                    if isinstance(obj, dict):
                        host = str(obj.get("host", host) or host)
                except Exception:
                    pass

        self.host = host.rstrip("/")
        self.session = requests.Session() if requests else None
        self.timeout = 15

    def isVideoFormat(self, url):
        return bool(re.search(
            r"(?i)(m3u8|mp4|flv|avi|mov|mkv|mpd)",
            str(url or "")
        ))

    def manualVideoCheck(self):
        return False

    # -------------------- 请求与签名 --------------------

    def _check_runtime(self):
        if requests is None:
            raise RuntimeError("缺少 requests 模块")

    def _get_headers(self):
        return {
            "Accept": "application/json",
            "X-Client": self.X_CLIENT,
            "web-sign": self.WEB_SIGN,
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

    def _request(self, method, path, params=None, data=None):
        self._check_runtime()
        url = path if path.startswith("http") else self.host + path
        headers = self._get_headers()

        for attempt in range(len(self.HOSTS) + 2):
            try:
                if method == "GET":
                    resp = self.session.get(
                        url, headers=headers, params=params,
                        timeout=self.timeout
                    )
                else:
                    resp = self.session.post(
                        url, headers=headers, data=data,
                        timeout=self.timeout
                    )

                if resp.status_code == 200:
                    ct = resp.headers.get("content-type", "")
                    if "json" in ct:
                        return resp.json()
                    return resp.text
                else:
                    idx = self.HOSTS.index(self.host) if self.host in self.HOSTS else -1
                    if idx >= 0 and idx < len(self.HOSTS) - 1:
                        self.host = self.HOSTS[idx + 1]
                    url = self.host + path
                    continue
            except Exception:
                idx = self.HOSTS.index(self.host) if self.host in self.HOSTS else -1
                if idx >= 0 and idx < len(self.HOSTS) - 1:
                    self.host = self.HOSTS[idx + 1]
                url = self.host + path
                continue

        raise RuntimeError("所有域名均无法访问")

    # -------------------- 数据转换 --------------------

    @staticmethod
    def _vod_item(item):
        if not isinstance(item, dict):
            return {}
        return {
            "vod_id": str(item.get("vod_id", "") or ""),
            "vod_name": str(item.get("vod_name", "") or ""),
            "vod_pic": str(item.get("vod_pic", "") or ""),
            "vod_remarks": str(item.get("vod_remarks", "") or "")
        }

    def _parse_vod_list(self, items):
        if not isinstance(items, list):
            return []
        return [self._vod_item(item) for item in items if isinstance(item, dict)]

    # -------------------- 首页 --------------------

    def homeContent(self, filter=False):
        try:
            obj = self._request("GET", "/api.php/web/index/home")
            if not isinstance(obj, dict) or obj.get("code") != 200:
                return {"class": [], "list": [], "error": "接口返回异常"}

            data = obj.get("data", {})
            if not isinstance(data, dict):
                data = {}

            classes = []
            for item in data.get("categories", []) or []:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("type_name", "") or "")
                if name:
                    classes.append({"type_id": name, "type_name": name})

            videos = []
            for cat in data.get("categories", []) or []:
                if isinstance(cat, dict):
                    videos.extend(cat.get("videos", []))
            videos = self._parse_vod_list(videos)

            return {"class": classes, "list": videos}
        except Exception as exc:
            return {"class": [], "list": [], "error": str(exc)}

    def homeVideoContent(self):
        try:
            obj = self._request("GET", "/api.php/web/index/home")
            if not isinstance(obj, dict) or obj.get("code") != 200:
                return {"list": [], "error": "接口返回异常"}
            data = obj.get("data", {})
            if not isinstance(data, dict):
                data = {}
            videos = []
            for cat in data.get("categories", []) or []:
                if isinstance(cat, dict):
                    videos.extend(cat.get("videos", []))
            return {"list": self._parse_vod_list(videos)}
        except Exception as exc:
            return {"list": [], "error": str(exc)}

    # -------------------- 分类 --------------------

    def categoryContent(self, tid, pg="1", filt=False, ext={}):
        try:
            page = max(int(pg or 1), 1)
            params = {"page": page, "sort": "hits"}
            params["type_name"] = str(tid)

            obj = self._request("GET", "/api.php/web/filter/vod", params=params)
            if not isinstance(obj, dict):
                return self._empty_cat_result(pg)

            if obj.get("code") != 200:
                return self._empty_cat_result(pg)

            videos = self._parse_vod_list(obj.get("data", []))

            return {
                "page": page,
                "pagecount": page + 1 if videos else page,
                "limit": len(videos),
                "total": 999999 if videos else 0,
                "list": videos
            }
        except Exception as exc:
            return self._empty_cat_result(pg)

    def _empty_cat_result(self, pg):
        return {
            "page": int(pg or 1),
            "pagecount": int(pg or 1),
            "limit": 0,
            "total": 0,
            "list": []
        }

    # -------------------- 详情 --------------------

    def detailContent(self, ids):
        try:
            vod_id = ids[0] if isinstance(ids, list) else ids
            obj = self._request(
                "GET", "/api.php/web/vod/get_detail",
                params={"vod_id": str(vod_id)}
            )

            if not isinstance(obj, dict) or obj.get("code") != 200:
                return {"list": [], "error": "获取详情失败"}

            data = obj.get("data", [])
            info = data[0] if isinstance(data, list) and data else {}
            if not isinstance(info, dict):
                info = {}

            video = {
                "vod_id": str(vod_id),
                "vod_name": str(info.get("vod_name", "") or ""),
                "vod_pic": str(info.get("vod_pic", "") or ""),
                "type_name": str(info.get("vod_class", "") or ""),
                "vod_remarks": str(info.get("vod_remarks", "") or ""),
                "vod_content": str(info.get("vod_content", "") or "").strip(),
                "vod_actor": str(info.get("vod_actor", "") or ""),
                "vod_director": str(info.get("vod_director", "") or "")
            }

            # 通过 internal_search_aggregate 获取可播放的 m3u8 链接
            play_sources = self._get_play_sources(info.get("vod_id"))

            if play_sources:
                display_froms = []
                output_urls = []
                vod_name = video["vod_name"]

                for source_from, episodes in play_sources:
                    display_froms.append(source_from)
                    ep_list = []
                    for ep_name, ep_url in episodes:
                        ep_list.append(f"{ep_name}${ep_url}")
                    output_urls.append("#".join(ep_list))

                video["vod_play_from"] = "$$$".join(display_froms)
                video["vod_play_url"] = "$$$".join(output_urls)
            else:
                # 降级：使用原始 vod_play_url
                source_name_map = {}
                for item in obj.get("vodplayer", []) or []:
                    if not isinstance(item, dict):
                        continue
                    source_from = str(item.get("from", "") or "")
                    source_show = str(item.get("show", "") or "")
                    if source_from:
                        source_name_map[source_from] = source_show or source_from

                raw_froms = str(info.get("vod_play_from", "") or "").split("$$$")
                raw_urls = str(info.get("vod_play_url", "") or "").split("$$$")

                display_froms = []
                output_urls = []
                vod_name = video["vod_name"]

                for index, source_urls in enumerate(raw_urls):
                    source_from = raw_froms[index] if index < len(raw_froms) else ""
                    display_name = source_name_map.get(source_from, source_from)
                    display_froms.append(display_name)

                    episodes = []
                    for episode in source_urls.split("#"):
                        if not episode or "$" not in episode:
                            continue
                        ep_name, ep_url = episode.split("$", 1)
                        digits = re.sub(r"\D+", "", ep_name)
                        vod_index = digits if digits else "1"
                        payload = "@".join([ep_url, source_from, vod_name, vod_index])
                        episodes.append(f"{ep_name}${payload}")

                    output_urls.append("#".join(episodes))

                video["vod_play_from"] = "$$$".join(display_froms)
                video["vod_play_url"] = "$$$".join(output_urls)

            return {"list": [video]}
        except Exception as exc:
            return {"list": [], "error": str(exc)}

    def _get_play_sources(self, vod_id):
        """通过 internal_search_aggregate 获取可播放的 m3u8 链接"""
        if not vod_id:
            return []
        try:
            obj = self._request(
                "GET", "/api.php/web/internal/search_aggregate",
                params={"vod_id": str(vod_id)}
            )
            if not isinstance(obj, dict) or obj.get("code") != 200:
                return []

            data = obj.get("data", [])
            if not isinstance(data, list):
                return []

            sources = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                decode_status = item.get("decode_status", "")
                vod_play_from = str(item.get("vod_play_from", "") or "")
                vod_play_url = str(item.get("vod_play_url", "") or "")

                # decode_status=0 表示无需解码，可直接播放
                if decode_status == 0 and vod_play_url:
                    episodes = []
                    for episode in vod_play_url.split("#"):
                        if not episode or "$" not in episode:
                            continue
                        ep_name, ep_url = episode.split("$", 1)
                        if ep_url and self.isVideoFormat(ep_url):
                            episodes.append((ep_name, ep_url))
                    if episodes:
                        sources.append((vod_play_from, episodes))

            return sources
        except Exception:
            return []

    # -------------------- 搜索 --------------------

    def searchContent(self, key, quick=False, pg="1"):
        return self.searchContentPage(key, quick, pg)

    def searchContentPage(self, key, quick=False, pg="1"):
        try:
            page = max(int(pg or 1), 1)
            obj = self._request(
                "GET", "/api.php/web/search/index",
                params={"wd": key, "page": page, "limit": 15}
            )

            if not isinstance(obj, dict) or obj.get("code") != 200:
                return self._empty_search_result(pg)

            videos = self._parse_vod_list(obj.get("data", []))

            return {
                "page": page,
                "pagecount": page + 1 if videos else page,
                "limit": len(videos),
                "total": 999999 if videos else 0,
                "list": videos
            }
        except Exception as exc:
            return self._empty_search_result(pg)

    def _empty_search_result(self, pg):
        return {
            "page": int(pg or 1),
            "pagecount": int(pg or 1),
            "limit": 0,
            "total": 0,
            "list": []
        }

    # -------------------- 播放 --------------------

    def playerContent(self, flag, id, vipFlags):
        try:
            id_str = str(id or "")
            # id 格式: "名称$https://xxx.m3u8" (TVBox 封装) 或 "名称@from@name@index" (payload)
            if "@" in id_str:
                parts = id_str.split("@")
                parts += [""] * (4 - len(parts))
                play_url = parts[0].strip()
                if self.isVideoFormat(play_url):
                    return {
                        "parse": 0,
                        "playUrl": "",
                        "url": play_url
                    }
                return {
                    "parse": 1,
                    "playUrl": "",
                    "url": play_url,
                    "error": f"播放链接需要解码（{parts[1]}源），当前暂不支持WASM解码，请尝试其他线路"
                }
            elif "$" in id_str:
                # TVBox 传入 "名称$url"，取最后一个 $ 后面的纯 URL
                play_url = id_str.rsplit("$", 1)[-1].strip()
                return {
                    "parse": 0,
                    "playUrl": "",
                    "url": play_url
                }
            else:
                # 直接返回 m3u8 链接
                return {
                    "parse": 0,
                    "playUrl": "",
                    "url": id_str
                }
        except Exception as exc:
            return {
                "parse": 1,
                "playUrl": "",
                "url": str(id or ""),
                "error": str(exc)
            }

    # -------------------- Challenge 算法（保留接口，新版不再使用）--------------------

    @staticmethod
    def _challenge_token(js_text):
        return ""

    def localProxy(self, param):
        return [404, "text/plain", "Not Found"]


# TVBox入口
spider = Spider()