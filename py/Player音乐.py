# -*- coding: utf-8 -*-
"""
网易云音乐 (netease-cloud-music-api.fe-mm.com) Python Spider
基于 Binaryify/NeteaseCloudMusicApi
兼容 FongMi/TV (T3) 和 WebHomeTV/PeekPro (T4)

API 端点 (GET):
  - /search?keywords=KW&limit=N&offset=O      搜索歌曲
  - /song/url?id=ID                            获取播放链接
  - /song/detail?ids=ID                        获取歌曲详情(含封面)
  - /lyric?id=ID                               获取歌词
  - /playlist/detail?id=ID                     获取歌单详情
  - /toplist                                   获取排行榜列表
  - /toplist/detail                            获取排行榜详情
  - /personalized?limit=N                      推荐歌单

两种数据源格式:
  - 歌单 tracks: {id, name, ar:[{name}], al:{name, picUrl}}
  - 搜索结果:    {id, name, artists:[{name}], album:{name, picUrl}}
"""

import sys
import json
import base64
import time
from urllib.parse import quote, unquote

sys.path.append('..')

# ===== 兼容导入: FM 有基类, PeekPro 没有就自己定义 =====
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

    HOST = "https://netease-music.fe-mm.com"
    API = "https://netease-cloud-music-api.fe-mm.com"
    UA = "Mozilla/5.0 (Linux; Android 13; KB2000) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36"

    # 分类定义 (使用歌单 ID)
    # 精选: 热门推荐歌单 (通过 /personalized 获取)
    CLASSES = [
        {"type_id": "featured",  "type_name": "精选"},
        {"type_id": "hot",       "type_name": "热歌榜",   "playlist_id": "3778678"},
        {"type_id": "new",       "type_name": "新歌榜",   "playlist_id": "3779629"},
        {"type_id": "soar",      "type_name": "飙升榜",   "playlist_id": "19723756"},
        {"type_id": "douyin",    "type_name": "抖音榜",   "playlist_id": "2250011882"},
        {"type_id": "classic",   "type_name": "经典老歌", "playlist_id": "71384707"},
        {"type_id": "original",  "type_name": "原创榜",   "playlist_id": "2884035"},
        {"type_id": "dj",        "type_name": "DJ榜",     "playlist_id": "1978921795"},
        {"type_id": "rap",       "type_name": "说唱榜",   "playlist_id": "991319590"},
        {"type_id": "electro",   "type_name": "电音榜",   "playlist_id": "10520166"},
    ]

    CLASS_MAP = {c["type_id"]: c for c in CLASSES}

    # 无子分类筛选器

    # 缓存
    _cache = {}
    _cache_time = {}
    CACHE_TTL = 300  # 5 minutes

    # ===== 初始化 =====
    def init(self, extend=""):
        if isinstance(extend, list):
            self.extend = ""
        else:
            self.extend = extend or ""
        self.header = {
            "User-Agent": self.UA,
            "Referer": self.HOST + "/",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }

    def getName(self):
        return "网易云音乐"

    # ================================================================
    # 首页
    # ================================================================
    def homeContent(self, filter):
        classes = [{"type_id": c["type_id"], "type_name": c["type_name"]} for c in self.CLASSES]
        return {
            "class": classes,
            "filters": {},
        }

    def homeVideoContent(self):
        """首页推荐: 精选热门歌单"""
        return self._load_featured(1)

    # ================================================================
    # 分类列表
    # ================================================================
    def categoryContent(self, tid, pg, filter, extend):
        try:
            page = int(pg or 1)
            ext = {}
            if extend:
                if isinstance(extend, dict):
                    ext = extend
                elif isinstance(extend, str):
                    try:
                        ext = json.loads(extend)
                    except Exception:
                        ext = {}

            # 从 extend 或 tid 确定分类
            class_id = ext.get("class", tid)
            cls = self.CLASS_MAP.get(class_id, self.CLASS_MAP.get(tid, self.CLASSES[0]))

            # "featured" 分类: 加载热门推荐歌单
            if cls["type_id"] == "featured":
                return self._load_featured(page)

            # 榜单分类: 加载歌单
            playlist_id = cls.get("playlist_id", self.CLASSES[0].get("playlist_id", "3778678"))
            return self._load_playlist(playlist_id, page)
        except Exception:
            return {"list": [], "page": int(pg or 1), "pagecount": 1, "limit": 20, "total": 0}

    def _load_playlist(self, playlist_id, page):
        """加载歌单并分页返回"""
        try:
            cache_key = "pl_{}".format(playlist_id)
            now = time.time()

            if cache_key in self._cache and now - self._cache_time.get(cache_key, 0) < self.CACHE_TTL:
                data = self._cache[cache_key]
            else:
                url = "{}/playlist/detail?id={}".format(self.API, playlist_id)
                data = self._fetch_json(url)
                if not data or data.get("code") != 200:
                    return {"list": [], "page": page, "pagecount": 1, "limit": 20, "total": 0}
                self._cache[cache_key] = data
                self._cache_time[cache_key] = now

            tracks = data.get("playlist", {}).get("tracks", [])
            if not tracks:
                return {"list": [], "page": page, "pagecount": 1, "limit": 20, "total": 0}

            # 客户端分页
            per_page = 20
            total = len(tracks)
            pagecount = (total + per_page - 1) // per_page if total > 0 else 1
            start = (page - 1) * per_page
            end = start + per_page
            songs = tracks[start:end]

            videos = []
            for song in songs:
                vod_id = self._encode_song(song)
                artist = self._get_artist(song)
                pic = self._get_pic(song)
                videos.append({
                    "vod_id": vod_id,
                    "vod_name": song.get("name", ""),
                    "vod_pic": pic,
                    "vod_remarks": artist,
                })

            return {
                "list": videos,
                "page": page,
                "pagecount": pagecount,
                "limit": per_page,
                "total": total,
            }
        except Exception:
            return {"list": [], "page": page, "pagecount": 1, "limit": 20, "total": 0}

    def _load_featured(self, page):
        """加载热门推荐歌单列表"""
        try:
            cache_key = "featured"
            now = time.time()

            if cache_key in self._cache and now - self._cache_time.get(cache_key, 0) < self.CACHE_TTL:
                data = self._cache[cache_key]
            else:
                url = "{}/personalized?limit=30".format(self.API)
                data = self._fetch_json(url, timeout=30)
                if not data or data.get("code") != 200:
                    return {"list": [], "page": page, "pagecount": 1, "limit": 20, "total": 0}
                self._cache[cache_key] = data
                self._cache_time[cache_key] = now

            playlists = data.get("result", [])
            if not playlists:
                return {"list": [], "page": page, "pagecount": 1, "limit": 20, "total": 0}

            per_page = 20
            total = len(playlists)
            pagecount = (total + per_page - 1) // per_page if total > 0 else 1
            start = (page - 1) * per_page
            end = start + per_page
            items = playlists[start:end]

            videos = []
            for pl in items:
                pl_id = str(pl.get("id", ""))
                name = pl.get("name", "")
                pic = pl.get("picUrl", "")
                # 强制 HTTPS
                if pic and pic.startswith("http://"):
                    pic = "https://" + pic[7:]
                play_count = pl.get("playCount", 0)
                track_count = pl.get("trackCount", 0)
                remarks = "{}首 · {}播放".format(track_count, self._fmt_play_count(play_count))
                # 编码 vod_id: featured|playlist_id
                vod_id = base64.b64encode(json.dumps({
                    "type": "playlist",
                    "id": pl_id,
                    "name": name,
                }, ensure_ascii=False).encode("utf-8")).decode("utf-8")
                videos.append({
                    "vod_id": vod_id,
                    "vod_name": name,
                    "vod_pic": pic,
                    "vod_remarks": remarks,
                })

            return {
                "list": videos,
                "page": page,
                "pagecount": pagecount,
                "limit": per_page,
                "total": total,
            }
        except Exception:
            return {"list": [], "page": page, "pagecount": 1, "limit": 20, "total": 0}

    def _fmt_play_count(self, count):
        """格式化播放次数"""
        if count >= 10000:
            return "{:.1f}万".format(count / 10000)
        return str(count)

    # ================================================================
    # 搜索
    # ================================================================
    def searchContent(self, key, quick, pg="1"):
        try:
            page = int(pg or 1)
            offset = (page - 1) * 20
            encoded_kw = quote(key, safe="")
            url = "{}/search?keywords={}&limit=20&offset={}".format(self.API, encoded_kw, offset)
            data = self._fetch_json(url)

            if not data or data.get("code") != 200:
                return {"list": []}

            songs = data.get("result", {}).get("songs", [])
            # 搜索结果 album.picUrl 为空, 用 song/detail 批量补充封面
            songs = self._fill_search_pics(songs)

            videos = []
            for song in songs:
                vod_id = self._encode_song(song)
                artist = self._get_artist(song)
                pic = self._get_pic(song)
                videos.append({
                    "vod_id": vod_id,
                    "vod_name": song.get("name", ""),
                    "vod_pic": pic,
                    "vod_remarks": artist,
                })

            return {"list": videos}
        except Exception:
            return {"list": []}

    # ================================================================
    # 详情页
    # ================================================================
    def detailContent(self, ids):
        try:
            if isinstance(ids, str):
                ids = [ids]
            vod_id = ids[0]
            vod_id = unquote(vod_id)

            # 解码 vod_id 判断类型
            try:
                data = base64.b64decode(vod_id).decode("utf-8")
                info = json.loads(data)
            except Exception:
                return {"list": []}

            # 类型1: 歌单 (type="playlist")
            if info.get("type") == "playlist":
                return self._detail_playlist(info)

            # 类型2: 单曲
            return self._detail_song(info)
        except Exception:
            return {"list": []}

    def _detail_song(self, song):
        """返回单曲详情"""
        try:
            song_id = str(song.get("id", ""))
            name = song.get("name", "")
            artist = song.get("artist", "")
            album = song.get("album", "")
            pic = song.get("pic", "")

            # 获取歌词
            lyric = self._get_lyric(song_id)

            # 播放信息: song_id
            play_info = song_id

            vod = {
                "vod_id": base64.b64encode(json.dumps(song, ensure_ascii=False).encode("utf-8")).decode("utf-8"),
                "vod_name": name,
                "vod_pic": pic,
                "type_name": "网易云音乐",
                "vod_year": "",
                "vod_area": "",
                "vod_remarks": album,
                "vod_actor": artist,
                "vod_director": "",
                "vod_content": lyric[:1000] if lyric else "暂无歌词",
                "vod_play_from": "网易云音乐",
                "vod_play_url": "播放${}".format(play_info),
            }
            return {"list": [vod]}
        except Exception:
            return {"list": []}

    def _detail_playlist(self, info):
        """返回歌单详情 (歌单本身作为 vod, 内含所有歌曲作为播放列表)"""
        try:
            pl_id = info.get("id", "")
            pl_name = info.get("name", "歌单")

            # 获取歌单详情
            url = "{}/playlist/detail?id={}".format(self.API, pl_id)
            data = self._fetch_json(url, timeout=30)

            if not data or data.get("code") != 200:
                return {"list": []}

            playlist = data.get("playlist", {})
            tracks = playlist.get("tracks", [])
            cover = playlist.get("coverImgUrl", "")
            # 强制 HTTPS
            if cover and cover.startswith("http://"):
                cover = "https://" + cover[7:]

            if not tracks:
                return {"list": []}

            # 构建播放列表 (所有歌曲作为集数)
            episodes = []
            for track in tracks[:100]:  # 最多100首
                song_id = str(track.get("id", ""))
                name = track.get("name", "")
                artist = self._get_artist(track)
                pic = self._get_pic(track)

                # 编码歌曲信息
                song_info = {
                    "id": song_id,
                    "name": name,
                    "artist": artist,
                    "album": self._get_album(track),
                    "pic": pic,
                }
                song_vod_id = base64.b64encode(json.dumps(song_info, ensure_ascii=False).encode("utf-8")).decode("utf-8")
                episodes.append("{}${}".format(name, song_vod_id))

            vod = {
                "vod_id": base64.b64encode(json.dumps(info, ensure_ascii=False).encode("utf-8")).decode("utf-8"),
                "vod_name": pl_name,
                "vod_pic": cover,
                "type_name": "歌单",
                "vod_year": "",
                "vod_area": "",
                "vod_remarks": "{}首歌曲".format(len(tracks)),
                "vod_actor": playlist.get("creator", {}).get("nickname", ""),
                "vod_director": "",
                "vod_content": playlist.get("description", "")[:500] if playlist.get("description") else "",
                "vod_play_from": "网易云音乐",
                "vod_play_url": "#".join(episodes) if episodes else "",
            }
            return {"list": [vod]}
        except Exception:
            return {"list": []}

    # ================================================================
    # 播放解析
    # ================================================================
    def playerContent(self, flag, id, vipFlags):
        try:
            song_id = str(id)
            # 如果 id 不是纯数字, 可能是 base64 编码的歌曲信息 (来自歌单详情)
            if not song_id.isdigit():
                try:
                    data = base64.b64decode(song_id).decode("utf-8")
                    info = json.loads(data)
                    song_id = str(info.get("id", ""))
                except Exception:
                    return {"parse": 1, "playUrl": "", "url": id}

            if not song_id or not song_id.isdigit():
                return {"parse": 1, "playUrl": "", "url": id}

            url = "{}/song/url?id={}".format(self.API, song_id)
            data = self._fetch_json(url)

            mp3_url = ""
            if data and data.get("code") == 200:
                urls = data.get("data", [])
                if urls:
                    mp3_url = urls[0].get("url", "")

            # 网易云外链兜底
            if not mp3_url:
                mp3_url = "https://music.163.com/song/media/outer/url?id={}.mp3".format(song_id)

            if not mp3_url:
                return {"parse": 1, "playUrl": "", "url": id}

            return {
                "parse": 0,
                "playUrl": "",
                "url": mp3_url,
                "header": {
                    "Referer": self.HOST + "/",
                    "User-Agent": self.UA,
                },
            }
        except Exception:
            return {"parse": 1, "playUrl": "", "url": id}

    # ================================================================
    # 工具函数
    # ================================================================
    def _fetch_json(self, url, timeout=30):
        """请求 API 并解析 JSON, 失败返回 None"""
        try:
            rsp = self.fetch(url, headers=self.header, timeout=timeout)
            try:
                rsp.encoding = "utf-8"
            except Exception:
                pass
            return json.loads(rsp.text)
        except Exception:
            return None

    def _encode_song(self, song):
        """将歌曲信息编码为 base64 JSON 字符串作为 vod_id"""
        try:
            artist = self._get_artist(song)
            pic = self._get_pic(song)
            data = json.dumps({
                "id": str(self._get_id(song)),
                "name": song.get("name", ""),
                "artist": artist,
                "album": self._get_album(song),
                "pic": pic,
            }, ensure_ascii=False)
            return base64.b64encode(data.encode("utf-8")).decode("utf-8")
        except Exception:
            return ""

    def _decode_song(self, vod_id):
        """解码 vod_id 为歌曲信息 dict"""
        try:
            vod_id = unquote(vod_id)
            data = base64.b64decode(vod_id).decode("utf-8")
            return json.loads(data)
        except Exception:
            return None

    def _get_id(self, song):
        """获取歌曲 ID"""
        return song.get("id", 0)

    def _get_name(self, song):
        """获取歌曲名"""
        return song.get("name", "")

    def _get_artist(self, song):
        """获取歌手名 (兼容两种格式)"""
        # 格式1: ar (来自歌单 tracks)
        ar = song.get("ar", [])
        if ar:
            if isinstance(ar, list) and len(ar) > 0:
                return ar[0].get("name", "")
            elif isinstance(ar, dict):
                return ar.get("name", "")
        # 格式2: artists (来自搜索结果)
        artists = song.get("artists", [])
        if artists:
            if isinstance(artists, list) and len(artists) > 0:
                return artists[0].get("name", "")
            elif isinstance(artists, dict):
                return artists.get("name", "")
        return ""

    def _get_album(self, song):
        """获取专辑名 (兼容两种格式)"""
        # 格式1: al (来自歌单 tracks)
        al = song.get("al", {})
        if al and isinstance(al, dict):
            return al.get("name", "")
        # 格式2: album (来自搜索结果)
        album = song.get("album", {})
        if album and isinstance(album, dict):
            return album.get("name", "")
        return ""

    def _get_pic(self, song):
        """获取封面图 URL (兼容两种格式, 强制 HTTPS)"""
        pic = ""
        # 格式1: al.picUrl (来自歌单 tracks)
        al = song.get("al", {})
        if al and isinstance(al, dict):
            pic = al.get("picUrl", "")
        # 格式2: album.picUrl (来自搜索结果)
        if not pic:
            album = song.get("album", {})
            if album and isinstance(album, dict):
                pic = album.get("picUrl", "")
        # 强制 HTTPS (TVBox 客户端安全策略阻止 HTTP 图片)
        if pic and pic.startswith("http://"):
            pic = "https://" + pic[7:]
        return pic

    def _fill_search_pics(self, songs):
        """批量补充搜索结果的封面图 (搜索结果 album.picUrl 为空)"""
        try:
            if not songs:
                return songs
            # 收集所有有 picId 但无 picUrl 的歌曲
            ids_to_fetch = []
            id_to_index = {}
            for i, s in enumerate(songs):
                album = s.get("album", {})
                if album and isinstance(album, dict):
                    pic_url = album.get("picUrl", "")
                    pic_id = album.get("picId", 0)
                    if not pic_url and pic_id:
                        sid = str(s.get("id", 0))
                        if sid and sid != "0":
                            ids_to_fetch.append(sid)
                            id_to_index[sid] = i

            if not ids_to_fetch:
                return songs

            # 批量请求 song/detail (最多 50 个 ID)
            batch_size = 50
            for batch_start in range(0, len(ids_to_fetch), batch_size):
                batch_ids = ids_to_fetch[batch_start:batch_start + batch_size]
                ids_param = ",".join(batch_ids)
                url = "{}/song/detail?ids={}".format(self.API, ids_param)
                data = self._fetch_json(url, timeout=15)
                if data and data.get("code") == 200:
                    for detail in data.get("songs", []):
                        sid = str(detail.get("id", 0))
                        idx = id_to_index.get(sid)
                        if idx is not None:
                            al = detail.get("al", {})
                            if al and isinstance(al, dict):
                                pic = al.get("picUrl", "")
                                if pic:
                                    songs[idx]["album"]["picUrl"] = pic
            return songs
        except Exception:
            return songs

    def _get_lyric(self, song_id):
        """获取歌词"""
        try:
            url = "{}/lyric?id={}".format(self.API, song_id)
            data = self._fetch_json(url, timeout=10)
            if data and data.get("code") == 200:
                lrc = data.get("lrc", {})
                if lrc:
                    return lrc.get("lyric", "")
            return ""
        except Exception:
            return ""

    def _txt(self, url, referer=None, timeout=30):
        """安全获取文本内容"""
        headers = dict(self.header)
        if referer:
            headers["Referer"] = referer
        try:
            rsp = self.fetch(url, headers=headers, timeout=timeout)
            try:
                rsp.encoding = "utf-8"
            except Exception:
                pass
            return rsp.text
        except Exception:
            return ""

    # ===== 清理 =====
    def destroy(self):
        pass

    def close(self):
        self.destroy()
