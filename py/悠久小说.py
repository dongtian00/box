# -*- coding: utf-8 -*-
"""
悠久小说 - TVBox Spider
基于悠久小说网 (www.ujxsw.org) 分析结果实现

修复清单：
  1. _parse_category_page: XPath完全不匹配实际HTML结构(#sitembox dl)，
     导致分类页无数据；同时避免从"热力推荐"区重复抓取
  2. _parse_chapter_list: 第三条XPath中 f"/read/{bid}/" 是Python f-string语法
     误写在XPath字符串内部，导致XPath语法错误，章节列表永远解析失败
  3. detailContent: 书名/封面/简介/状态的XPath均不匹配实际HTML结构
  4. fetch_online_chapter: 提取整个 mlfy_main_text div（含书签按钮、章节标题、
     作者信息、推荐按钮），应只提取 read-content 子div中的正文
  5. _parse_search_results: XPath不匹配搜索结果结构(div.shulist ul)
  6. _start_preload_adjacent: 传章节索引(idx)而非cid给_preload_chapter，
     导致预加载URL错误
  7. serve_chapter_data + fetch_online_chapter: 内容被双重净化，效率低且
     可能导致<p>标签被误删后重建
"""

import os
import re
import sys
import time
import json
import socket
import threading
import urllib.parse
import http.server
import socketserver
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from typing import Dict, List, Optional

import requests
from lxml import etree

# ============ 配置 ============
CONFIG = {
    "site_domain": "www.ujxsw.org",
    "protocol": "http",
    "book_dir": "/storage/emulated/0/ZWDF/books",
    "data_dir": "/storage/emulated/0/ZWDF/novel_data",
    "cache_dir": "/storage/emulated/0/ZWDF/novel_data/cache",
    "default_poster": "https://img.zcool.cn/community/0142135541f66b0000019ae9b8ee4a.jpg@1280w_1l_2o_100sh.jpg",
    "font_size": 22,
    "line_height": 2.0,
    "theme": "parchment",
    "auto_next": True,
    "text_purify": True,
    "reading_speed": 300,
}

_DEBUG = True

# 水印及广告清洗正则
WATERMARK_PATTERNS = [
    re.compile(r'【悠久小説網[^】]*】'),
    re.compile(r'免费小说无弹窗免费阅读！'),
    re.compile(r'佰度搜索.*?全集TXT电子书免费下载！'),
    re.compile(r'最新网址：www\.ujxsw\.org'),
    re.compile(r'http[s]?://(?:www\.)?ujxsw\.org'),
    re.compile(r'&nbsp;'),
]

def _log(msg):
    if _DEBUG:
        try:
            print(f"[UJXSW] {msg}")
        except Exception:
            pass

def _ensure_data_dir():
    for d in [CONFIG["data_dir"], CONFIG["cache_dir"], CONFIG["book_dir"]]:
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            pass
    return CONFIG["data_dir"]

# ============ 缓存管理器 ============
class CacheManager:
    _instance = None
    _lock = threading.Lock()
    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance
    def __init__(self):
        if self._initialized:
            return
        _ensure_data_dir()
        self._caches = {}
        self._initialized = True
    def _get_cache(self, name):
        if name not in self._caches:
            self._caches[name] = {}
        return self._caches[name]
    def _load(self, name):
        cache = self._get_cache(name)
        if not cache:
            filepath = os.path.join(CONFIG["cache_dir"], f"{name}.json")
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    cache.update(data)
            except Exception:
                pass
        return cache
    def _save(self, name, data):
        filepath = os.path.join(CONFIG["cache_dir"], f"{name}.json")
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception:
            pass
    def get(self, name, key=None):
        data = self._load(name)
        if key is None:
            return data
        return data.get(key)
    def set(self, name, key, value):
        data = self._load(name)
        data[key] = value
        self._save(name, data)

# ============ 进度 ============
class ProgressManager:
    def __init__(self):
        self._cache = CacheManager()
        self._name = "reading_progress"
    def get(self, bid):
        return self._cache.get(self._name, bid) or {"chapter_index": 0, "scroll": 0, "time": 0}
    def update(self, bid, chapter_index=None, scroll=None):
        current = self.get(bid)
        if chapter_index is not None:
            current["chapter_index"] = chapter_index
        if scroll is not None:
            current["scroll"] = scroll
        current["time"] = int(time.time())
        self._cache.set(self._name, bid, current)

# ============ 书签 ============
class BookmarkManager:
    def __init__(self):
        self._cache = CacheManager()
        self._name = "bookmarks"
    def get(self, bid):
        return self._cache.get(self._name, bid) or []
    def add(self, bid, chapter_idx, scroll=0, note=""):
        bookmarks = self.get(bid)
        for b in bookmarks:
            if b.get("chapter_idx") == chapter_idx and b.get("scroll") == scroll:
                return False
        bookmarks.append({"chapter_idx": chapter_idx, "scroll": scroll, "note": note, "time": int(time.time())})
        self._cache.set(self._name, bid, bookmarks)
        return True
    def remove(self, bid, index):
        bookmarks = self.get(bid)
        if 0 <= index < len(bookmarks):
            bookmarks.pop(index)
            self._cache.set(self._name, bid, bookmarks)
            return True
        return False

# ============ 统计 ============
class StatisticsManager:
    def __init__(self):
        self._cache = CacheManager()
        self._name = "statistics"
        self._today = time.strftime("%Y%m%d")
    def _get_today_data(self, bid):
        data = self._cache.get(self._name, bid) or {}
        if data.get("date") != self._today:
            data = {"date": self._today, "duration": 0, "chapters": 0, "words": 0, "speed": 0}
        return data
    def _save_today(self, bid, data):
        data["date"] = self._today
        self._cache.set(self._name, bid, data)
    def add_reading_time(self, bid, seconds):
        data = self._get_today_data(bid)
        data["duration"] += seconds
        self._save_today(bid, data)
    def add_chapter(self, bid, word_count):
        data = self._get_today_data(bid)
        data["chapters"] += 1
        data["words"] += word_count
        if data["duration"] > 0:
            data["speed"] = int(data["words"] / (data["duration"] / 60))
        self._save_today(bid, data)
    def get_today(self, bid):
        return self._get_today_data(bid)

# ============ 设置 ============
class SettingsManager:
    def __init__(self):
        self._cache = CacheManager()
        self._name = "reader_settings"
        self._data = dict(CONFIG)
        saved = self._cache.get(self._name, "settings")
        if isinstance(saved, dict):
            self._data.update(saved)
    def get(self, key=None, default=None):
        if key is None:
            return dict(self._data)
        return self._data.get(key, default)
    def update(self, key, value):
        self._data[key] = value
        self._cache.set(self._name, "settings", self._data)
    def update_batch(self, data):
        if isinstance(data, dict):
            self._data.update(data)
            self._cache.set(self._name, "settings", self._data)
    def all(self):
        return dict(self._data)

# ============ 章节缓存(LRU) ============
class ChapterCache:
    MAX_SIZE = 50
    def __init__(self):
        self._mem = OrderedDict()
        self._file_cache = CacheManager()
        self._file_name = "chapter_cache"
        self._lock = threading.Lock()
    def put(self, bid, chapters):
        with self._lock:
            if bid in self._mem:
                self._mem.move_to_end(bid)
            else:
                if len(self._mem) >= self.MAX_SIZE:
                    oldest = next(iter(self._mem))
                    self._mem.pop(oldest)
            self._mem[bid] = chapters
            serializable = [{"cid": c.get("cid", ""), "title": c.get("title", ""), "url": c.get("url", "")} for c in chapters]
            self._file_cache.set(self._file_name, bid, {"chapters": serializable, "time": int(time.time())})
    def get(self, bid):
        with self._lock:
            if bid in self._mem:
                self._mem.move_to_end(bid)
                return self._mem[bid]
            data = self._file_cache.get(self._file_name, bid)
            if data and "chapters" in data:
                chapters = data["chapters"]
                self._mem[bid] = chapters
                if len(self._mem) > self.MAX_SIZE:
                    oldest = next(iter(self._mem))
                    self._mem.pop(oldest)
                return chapters
            return None

# ============ 文本净化 ============
class TextPurifier:
    @staticmethod
    @lru_cache(maxsize=256)
    def _purify_cached(text):
        if not text:
            return ""
        # 去除水印
        for pat in WATERMARK_PATTERNS:
            text = pat.sub('', text)
        # 去掉多余的<br>，转为换行
        lines = re.split(r'<br\s*/?>', text)
        result = []
        prev_empty = False
        for line in lines:
            line = line.strip().replace("\u3000", "").replace("\r", "").replace("&nbsp;", " ")
            # 去除残留的HTML标签（但保留内容）
            line = re.sub(r'<[^>]+>', '', line)
            if not line:
                if not prev_empty:
                    result.append("")
                    prev_empty = True
                continue
            # 去除明显的广告或空行
            if len(line) < 2 and not re.search(r'[\u4e00-\u9fa5a-zA-Z]', line):
                continue
            result.append(line)
            prev_empty = False
        while result and not result[0].strip():
            result.pop(0)
        while result and not result[-1].strip():
            result.pop()
        return "\n".join(result)
    @classmethod
    def purify(cls, text):
        return cls._purify_cached(text)
    @staticmethod
    def count_words(text):
        clean = re.sub(r'<[^>]+>', '', text)
        return len(re.findall(r'[\u4e00-\u9fa5]', clean))

# ============ Web 服务器 ============
class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

class NovelHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        if _DEBUG:
            print(f"[HTTP] {args[0]}")
    def do_GET(self):
        spider = getattr(self.server, 'spider', None)
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        if path == '/read.html':
            self.serve_reader_ui()
        elif path == '/api/chapter':
            self.serve_chapter_data(spider, query)
        elif path == '/api/chapters':
            self.serve_chapter_list(spider, query)
        elif path == '/api/progress':
            self.serve_progress(spider, query)
        elif path == '/api/settings':
            self.serve_settings(spider)
        elif path == '/api/bookmarks':
            self.serve_bookmarks(spider, query)
        elif path == '/api/statistics':
            self.serve_statistics(spider, query)
        elif path == '/api/health':
            self.send_json({'code': 200, 'status': 'ok', 'ts': int(time.time())})
        else:
            self.send_error(404)
    def do_POST(self):
        spider = getattr(self.server, 'spider', None)
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else '{}'
            data = json.loads(body) if body else {}
        except Exception:
            data = {}
        if path == '/api/progress':
            bid = data.get('bid', '')
            idx = data.get('idx')
            scroll = data.get('scroll')
            if bid and spider:
                spider.progress_mgr.update(bid, idx, scroll)
            self.send_json({'code': 200})
        elif path == '/api/settings':
            if spider:
                spider.settings.update_batch(data)
            self.send_json({'code': 200})
        elif path == '/api/bookmarks':
            action = data.get('action', '')
            bid = data.get('bid', '')
            if not bid or not spider:
                self.send_json({'code': 400, 'msg': 'missing bid'})
                return
            if action == 'add':
                spider.bookmark_mgr.add(bid, data.get('chapter_idx', 0), data.get('scroll', 0), data.get('note', ''))
                self.send_json({'code': 200})
            elif action == 'remove':
                spider.bookmark_mgr.remove(bid, data.get('index', -1))
                self.send_json({'code': 200})
            else:
                self.send_json({'code': 400, 'msg': 'invalid action'})
        elif path == '/api/statistics':
            bid = data.get('bid', '')
            if bid and spider:
                seconds = data.get('duration', 0)
                if seconds > 0:
                    spider.stat_mgr.add_reading_time(bid, seconds)
                words = data.get('words', 0)
                if words > 0:
                    spider.stat_mgr.add_chapter(bid, words)
            self.send_json({'code': 200})
        else:
            self.send_error(404)

    def serve_reader_ui(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        self.wfile.write(READER_HTML.encode('utf-8'))

    def serve_chapter_data(self, spider, query):
        try:
            bid = query.get('bid', [''])[0]
            idx = int(query.get('idx', ['0'])[0])
            if not spider:
                self.send_json({'code': 500, 'msg': 'Spider不可用'})
                return
            chapter_list = spider.chapter_cache.get(bid)
            if not chapter_list:
                chapter_list = self._reload_chapters(spider, bid)
            if not chapter_list:
                self.send_json({'code': 400, 'msg': f'章节列表为空 (bid={bid})'})
                return
            if idx < 0 or idx >= len(chapter_list):
                self.send_json({'code': 400, 'msg': f'索引越界: {idx}/{len(chapter_list)}'})
                return
            current = chapter_list[idx]
            cid = current.get('cid', '')
            title = current.get('title', '未知章节')
            # 获取原始内容HTML
            raw_content = spider.fetch_online_chapter(bid, cid)
            # 统一在此处做净化和<p>包装，避免双重处理
            if spider.settings.get('text_purify', True):
                content = TextPurifier.purify(raw_content)
            else:
                # 即使关闭净化也做基本清理
                content = re.sub(r'<br\s*/?>', '\n', raw_content)
                content = re.sub(r'<[^>]+>', '', content)
                content = content.replace('&nbsp;', ' ')
            content = "".join([f"<p>{line.strip()}</p>" for line in content.split('\n') if line.strip()])
            word_count = TextPurifier.count_words(content)
            if idx + 1 < len(chapter_list):
                next_cid = chapter_list[idx + 1].get('cid', '')
                if not spider._get_cached_content(bid, next_cid):
                    threading.Thread(target=spider._preload_chapter, args=(bid, next_cid), daemon=True).start()
            self.send_json({
                'code': 200,
                'title': title,
                'content': content,
                'total': len(chapter_list),
                'idx': idx,
                'bid': bid,
                'word_count': word_count,
            })
        except Exception as e:
            _log(f"serve_chapter error: {e}")
            self.send_json({'code': 500, 'msg': str(e)})

    def _reload_chapters(self, spider, bid):
        try:
            catalog_url = f"{spider.base_url}/read/{bid}/"
            html = spider._fetch_page(catalog_url)
            if not html:
                return None
            chapters = spider._parse_chapter_list(html, bid)
            if not chapters:
                return None
            spider.chapter_cache.put(bid, chapters)
            return chapters
        except Exception as e:
            _log(f"_reload_chapters error: {e}")
            return None

    def serve_chapter_list(self, spider, query):
        try:
            bid = query.get('bid', [''])[0]
            chapter_list = spider.chapter_cache.get(bid) if spider else None
            if not chapter_list:
                chapter_list = self._reload_chapters(spider, bid) or []
            chapters = [{"title": c.get('title', ''), "idx": i} for i, c in enumerate(chapter_list)]
            self.send_json({'code': 200, 'chapters': chapters, 'total': len(chapters)})
        except Exception as e:
            self.send_json({'code': 500, 'msg': str(e)})

    def serve_progress(self, spider, query):
        try:
            bid = query.get('bid', [''])[0]
            progress = spider.progress_mgr.get(bid) if (bid and spider) else {}
            self.send_json({'code': 200, 'progress': progress})
        except Exception as e:
            self.send_json({'code': 500, 'msg': str(e)})

    def serve_settings(self, spider):
        try:
            settings = spider.settings.all() if spider else dict(CONFIG)
            self.send_json({'code': 200, 'settings': settings})
        except Exception as e:
            self.send_json({'code': 500, 'msg': str(e)})

    def serve_bookmarks(self, spider, query):
        try:
            bid = query.get('bid', [''])[0]
            bookmarks = spider.bookmark_mgr.get(bid) if (bid and spider) else []
            self.send_json({'code': 200, 'bookmarks': bookmarks})
        except Exception as e:
            self.send_json({'code': 500, 'msg': str(e)})

    def serve_statistics(self, spider, query):
        try:
            bid = query.get('bid', [''])[0]
            stats = spider.stat_mgr.get_today(bid) if (bid and spider) else {}
            self.send_json({'code': 200, 'statistics': stats})
        except Exception as e:
            self.send_json({'code': 500, 'msg': str(e)})

    def send_json(self, data):
        self.send_response(200)
        self.send_header('Content-type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

# ============ 阅读器 HTML ============
READER_HTML = r"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
<title>阅读器</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{font-family:"PingFang SC","Microsoft YaHei",sans-serif;transition:background .3s,color .3s}
.theme-parchment{background:#f8f1e3;color:#3e3e3e}
.theme-night{background:#1a1a1a;color:#b0b0b0}
.theme-eye{background:#c7edcc;color:#333}
.theme-white{background:#fff;color:#333}
#app{max-width:100%;padding:20px 16px 140px}
h2{text-align:center;font-size:1.25em;font-weight:700;padding-bottom:12px;margin:10px 0 25px;border-bottom:1px solid rgba(128,128,128,.3)}
#chapter-text p{margin-bottom:1.2em;text-align:justify;text-indent:2em;font-size:var(--fs,22px);line-height:var(--lh,2.0)}
.controls{position:fixed;bottom:0;left:0;right:0;z-index:100;padding:10px 12px 14px;display:flex;flex-direction:column;gap:6px;border-top:1px solid rgba(128,128,128,.2);backdrop-filter:blur(8px)}
.theme-parchment .controls{background:rgba(248,241,227,.95)}
.theme-night .controls{background:rgba(26,26,26,.95)}
.theme-eye .controls{background:rgba(199,237,204,.95)}
.theme-white .controls{background:rgba(255,255,255,.95)}
.controls-row{display:flex;gap:4px;align-items:center;width:100%;justify-content:space-between}
.btn{border:1px solid rgba(128,128,128,.3);border-radius:20px;padding:6px 10px;font-size:13px;cursor:pointer;outline:none;background:transparent;color:inherit;white-space:nowrap;transition:all .15s;flex-shrink:0}
.btn:active{transform:scale(.95);opacity:.7}
.btn-primary{background:#6495ed;color:#fff;border-color:#6495ed}
.btn-wide{flex:1;text-align:center;padding:8px 0}
.page-info{font-size:13px;opacity:.7;font-family:monospace;flex:1;text-align:center;min-width:60px}
.settings-panel,.bookmark-panel,.search-panel{position:fixed;bottom:0;left:0;right:0;z-index:200;padding:16px 16px 28px;border-radius:16px 16px 0 0;box-shadow:0 -4px 20px rgba(0,0,0,.1);transform:translateY(100%);transition:transform .3s;max-height:80vh;overflow-y:auto}
.theme-parchment .settings-panel,.theme-parchment .bookmark-panel,.theme-parchment .search-panel{background:#f0e6d0}
.theme-night .settings-panel,.theme-night .bookmark-panel,.theme-night .search-panel{background:#2a2a2a;color:#ddd}
.theme-eye .settings-panel,.theme-eye .bookmark-panel,.theme-eye .search-panel{background:#b8e0bc}
.theme-white .settings-panel,.theme-white .bookmark-panel,.theme-white .search-panel{background:#f5f5f5}
.settings-panel.show,.bookmark-panel.show,.search-panel.show{transform:translateY(0)}
.settings-panel h3,.bookmark-panel h3,.search-panel h3{font-size:16px;margin-bottom:12px;text-align:center}
.settings-row{display:flex;align-items:center;justify-content:space-between;padding:8px 0;border-bottom:1px solid rgba(128,128,128,.1)}
.settings-row label{font-size:14px}
.settings-row input[type=range]{width:130px}
.settings-row input[type=number]{width:70px;background:transparent;border:1px solid rgba(128,128,128,.3);border-radius:8px;padding:4px 6px;color:inherit;text-align:center}
.settings-row .value{font-size:12px;opacity:.6;min-width:40px;text-align:right}
.theme-buttons{display:flex;gap:8px;flex-wrap:wrap}
.theme-btn{width:36px;height:36px;border-radius:50%;border:2px solid transparent;cursor:pointer;flex-shrink:0}
.theme-btn.active{border-color:#6495ed}
.theme-btn[data-theme=parchment]{background:#f8f1e3}
.theme-btn[data-theme=night]{background:#1a1a1a}
.theme-btn[data-theme=eye]{background:#c7edcc}
.theme-btn[data-theme=white]{background:#fff;border:1px solid #ccc}
.chapter-list-panel{position:fixed;top:0;right:-280px;bottom:0;width:260px;z-index:200;overflow-y:auto;padding:12px;transition:right .3s;box-shadow:-2px 0 10px rgba(0,0,0,.1)}
.theme-parchment .chapter-list-panel{background:#f0e6d0}
.theme-night .chapter-list-panel{background:#2a2a2a;color:#ddd}
.theme-eye .chapter-list-panel{background:#b8e0bc}
.theme-white .chapter-list-panel{background:#f5f5f5}
.chapter-list-panel.show{right:0}
.chapter-list-panel h3{font-size:14px;margin-bottom:8px;padding-bottom:8px;border-bottom:1px solid rgba(128,128,128,.2)}
.chapter-item{padding:8px 6px;font-size:13px;cursor:pointer;border-radius:6px;transition:background .15s;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.chapter-item:active{background:rgba(100,149,237,.15)}
.chapter-item.current{color:#6495ed;font-weight:700}
.overlay{position:fixed;top:0;left:0;right:0;bottom:0;z-index:150;background:rgba(0,0,0,.3);display:none}
.overlay.show{display:block}
#loading{position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);background:rgba(0,0,0,.75);color:#fff;padding:14px 22px;border-radius:10px;display:none;z-index:300;font-size:14px}
.error-box{position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);background:#ffe0e0;color:#c00;padding:16px 20px;border-radius:10px;max-width:80%;z-index:400;display:none;font-size:14px;line-height:1.6}
.error-box button{margin-top:10px;padding:6px 16px;background:#c00;color:#fff;border:none;border-radius:16px;cursor:pointer}
.progress-bar{width:100%;height:4px;background:rgba(128,128,128,.2);border-radius:2px;cursor:pointer;position:relative;margin-bottom:4px}
.progress-bar .fill{height:100%;background:#6495ed;border-radius:2px;width:0}
.status-bar{display:flex;justify-content:space-between;font-size:11px;opacity:.6;padding:0 4px 2px}
</style>
</head>
<body class="theme-parchment">

<div id="loading">加载中...</div>
<div class="error-box" id="error-box" onclick="hideError()">
  <div id="error-msg">出错了</div>
  <button onclick="hideError();location.reload()">重试</button>
</div>

<div id="app">
  <div class="status-bar"><span id="stat-duration">今日阅读: 0分钟</span><span id="stat-speed">速度: 0字/分</span></div>
  <h2 id="chapter-title">准备加载...</h2>
  <div class="progress-bar" onclick="jumpProgress(event)"><div class="fill" id="progress-fill"></div></div>
  <div id="chapter-text"></div>
</div>

<div class="controls">
  <div class="controls-row">
    <button class="btn btn-wide" onclick="prevChapter()">上一章</button>
    <button class="btn btn-wide" onclick="nextChapter()">下一章</button>
  </div>
  <div class="controls-row">
    <button class="btn" onclick="toggleBookmark()">★</button>
    <button class="btn" onclick="toggleSearch()">🔍</button>
    <span class="page-info" id="page-info">0/0</span>
    <button class="btn" id="btn-auto" onclick="toggleAutoRead()">▶</button>
    <button class="btn" onclick="toggleSettings()">⚙</button>
    <button class="btn" onclick="toggleChapterList()">📑</button>
  </div>
</div>

<div class="overlay" id="overlay" onclick="closeAllPanels()"></div>

<div class="settings-panel" id="settings-panel">
  <h3>阅读设置</h3>
  <div class="settings-row"><label>字号</label><input type="range" id="font-size" min="14" max="32" value="22" oninput="updateFontSize(this.value)"><span class="value" id="font-size-val">22px</span></div>
  <div class="settings-row"><label>行距</label><input type="range" id="line-height" min="15" max="30" value="20" oninput="updateLineHeight(this.value)"><span class="value" id="line-height-val">2.0</span></div>
  <div class="settings-row"><label>主题</label><div class="theme-buttons"><div class="theme-btn active" data-theme="parchment" onclick="setTheme('parchment')"></div><div class="theme-btn" data-theme="night" onclick="setTheme('night')"></div><div class="theme-btn" data-theme="eye" onclick="setTheme('eye')"></div><div class="theme-btn" data-theme="white" onclick="setTheme('white')"></div></div></div>
  <div class="settings-row"><label>自动下一章</label><input type="checkbox" id="auto-next" checked onchange="updateAutoNext(this.checked)"></div>
  <div class="settings-row"><label>文本净化</label><input type="checkbox" id="text-purify" checked onchange="updatePurify(this.checked)"></div>
  <div class="settings-row"><label>阅读速度(字/分)</label><input type="number" id="reading-speed" min="100" max="800" value="300" onchange="updateReadingSpeed(this.value)"></div>
  <div class="settings-row"><button class="btn btn-primary" onclick="closeAllPanels()">完成</button></div>
</div>

<div class="bookmark-panel" id="bookmark-panel">
  <h3>书签列表</h3>
  <div id="bookmark-list"><div style="opacity:.6;padding:10px;text-align:center">暂无书签</div></div>
  <div class="settings-row"><button class="btn btn-primary" onclick="closeAllPanels()">关闭</button></div>
</div>

<div class="search-panel" id="search-panel">
  <h3>搜索当前章节</h3>
  <input type="text" id="search-input" placeholder="输入关键词..." style="width:100%;padding:8px 12px;border:1px solid rgba(128,128,128,.3);border-radius:20px;background:transparent;color:inherit;font-size:14px;outline:none;">
  <div style="margin-top:10px;max-height:200px;overflow-y:auto;" id="search-results"></div>
  <div class="settings-row"><button class="btn btn-primary" onclick="closeAllPanels()">关闭</button></div>
</div>

<div class="chapter-list-panel" id="chapter-list-panel">
  <h3>章节目录</h3>
  <div id="chapter-list-items"></div>
</div>

<script>
const bid = new URLSearchParams(location.search).get('bid') || '';
let currentIdx = parseInt(new URLSearchParams(location.search).get('idx') || '0');
let totalChapters = 0, loadRetries = 0, autoNext = true;
let wordCount = 0, readingSpeed = 300;
let autoReading = false, readingTimer = null, isProgrammaticScroll = false;
let manualScrollTimer = null;
let readStartTime = Date.now();

window.onerror = function(m,u,l){showError('JS错误: '+m+'\n行号: '+l);};

window.onload = async function() {
  try {
    await loadSettings();
    await loadProgress();
    await loadStatistics();
    loadChapter(currentIdx);
    setInterval(saveStatistics, 30000);
  } catch(e){showError('初始化失败: '+e.message);}
};

async function loadSettings() {
  try {
    const res = await fetch('/api/settings');
    const data = await res.json();
    if (data.code===200 && data.settings) {
      const s = data.settings;
      applyTheme(s.theme||'parchment');
      applyFontSize(parseInt(s.font_size)||22);
      applyLineHeight(parseFloat(s.line_height)||2.0);
      autoNext = s.auto_next!==false;
      document.getElementById('auto-next').checked = autoNext;
      document.getElementById('text-purify').checked = s.text_purify!==false;
      readingSpeed = parseInt(s.reading_speed)||300;
      document.getElementById('reading-speed').value = readingSpeed;
    }
  } catch(e){}
}

async function saveSettings() {
  try {
    await fetch('/api/settings', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({
        theme: document.body.className.replace('theme-',''),
        font_size: parseInt(document.getElementById('font-size').value),
        line_height: parseFloat(document.getElementById('line-height-val').textContent),
        auto_next: autoNext,
        text_purify: document.getElementById('text-purify').checked,
        reading_speed: readingSpeed
      })
    });
  } catch(e){}
}

async function loadProgress() {
  try {
    const res = await fetch('/api/progress?bid='+encodeURIComponent(bid));
    const data = await res.json();
    if (data.code===200 && data.progress && data.progress.chapter_index>0) {
      currentIdx = data.progress.chapter_index;
    }
  } catch(e){}
}

async function saveProgress() {
  try {
    await fetch('/api/progress', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({bid:bid, idx:currentIdx, scroll:Math.round(window.scrollY)})
    });
  } catch(e){}
}

async function loadStatistics() {
  try {
    const res = await fetch('/api/statistics?bid='+encodeURIComponent(bid));
    const data = await res.json();
    if (data.code===200 && data.statistics) {
      const st = data.statistics;
      document.getElementById('stat-duration').textContent = '今日阅读: '+Math.round(st.duration/60)+'分钟';
      document.getElementById('stat-speed').textContent = '速度: '+ (st.speed||0) +'字/分';
    }
  } catch(e){}
}

async function saveStatistics(duration, words) {
  try {
    await fetch('/api/statistics', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({bid:bid, duration:duration||0, words:words||0})
    });
  } catch(e){}
}

async function loadChapter(idx) {
  if (idx<0){showToast('已是第一章');return;}
  if (totalChapters>0 && idx>=totalChapters){showToast('已是最后一章');return;}
  showLoading(true); hideError();
  stopAutoRead();
  try {
    const res = await fetch('/api/chapter?bid='+encodeURIComponent(bid)+'&idx='+idx);
    const data = await res.json();
    if (data.code!==200) {
      if (loadRetries<2){loadRetries++;showLoading(true,'重试 '+loadRetries+'/2');setTimeout(()=>loadChapter(idx),1000);return;}
      loadRetries=0; showError('加载失败: '+data.msg); showLoading(false); return;
    }
    loadRetries=0;
    document.getElementById('chapter-title').textContent = data.title;
    document.getElementById('chapter-text').innerHTML = data.content;
    document.getElementById('page-info').textContent = (idx+1)+'/'+data.total;
    totalChapters = data.total; currentIdx = idx;
    wordCount = data.word_count||0;
    window.scrollTo(0,0);
    updateProgress();
    updateBookmarks();
    saveProgress();
    saveStatistics(0, wordCount);
    readStartTime = Date.now();
    updateChapterListCurrent();
    if (autoReading) {
      setTimeout(startAutoRead, 300);
    }
  } catch(e){
    if (loadRetries<2){loadRetries++;showLoading(true,'网络重试 '+loadRetries+'/2');setTimeout(()=>loadChapter(idx),1500);return;}
    loadRetries=0; showError('网络错误: '+e.message); showLoading(false);
  } finally { showLoading(false); }
}

function prevChapter(){ stopAutoRead(); loadChapter(currentIdx-1); }
function nextChapter(){ stopAutoRead(); loadChapter(currentIdx+1); }

function updateProgress() {
  if (totalChapters>0) {
    const pct = ((currentIdx+1)/totalChapters*100).toFixed(1);
    document.getElementById('progress-fill').style.width = pct+'%';
  }
}

function jumpProgress(e) {
  const bar = e.currentTarget;
  const rect = bar.getBoundingClientRect();
  const pct = (e.clientX - rect.left) / rect.width;
  const idx = Math.floor(pct * totalChapters);
  if (idx>=0 && idx<totalChapters) loadChapter(idx);
}

function setTheme(t){applyTheme(t);saveSettings();}
function applyTheme(t){document.body.className='theme-'+t;document.querySelectorAll('.theme-btn').forEach(el=>el.classList.toggle('active',el.dataset.theme===t));}
function updateFontSize(v){applyFontSize(parseInt(v));saveSettings();}
function applyFontSize(v){document.documentElement.style.setProperty('--fs',v+'px');document.getElementById('font-size').value=v;document.getElementById('font-size-val').textContent=v+'px';}
function updateLineHeight(v){var lh=(parseInt(v)/10).toFixed(1);applyLineHeight(parseFloat(lh));saveSettings();}
function applyLineHeight(v){document.documentElement.style.setProperty('--lh',v);document.getElementById('line-height').value=Math.round(v*10);document.getElementById('line-height-val').textContent=v.toFixed(1);}
function updateAutoNext(v){autoNext=v;saveSettings();}
function updatePurify(v){saveSettings();}
function updateReadingSpeed(v){readingSpeed=parseInt(v)||300; if(readingSpeed<100) readingSpeed=100; if(readingSpeed>800) readingSpeed=800; document.getElementById('reading-speed').value=readingSpeed; saveSettings(); if(autoReading){stopAutoRead();startAutoRead();}}

function toggleSettings(){const p=document.getElementById('settings-panel');p.classList.toggle('show');document.getElementById('overlay').classList.toggle('show',p.classList.contains('show'));closeOtherPanels('settings-panel');}
function toggleChapterList(){const p=document.getElementById('chapter-list-panel');if(p.classList.contains('show')){closeAllPanels();return;}closeAllPanels();p.classList.add('show');document.getElementById('overlay').classList.add('show');loadChapterList();}
function toggleBookmark(){const p=document.getElementById('bookmark-panel');p.classList.toggle('show');document.getElementById('overlay').classList.toggle('show',p.classList.contains('show'));closeOtherPanels('bookmark-panel');if(p.classList.contains('show')) loadBookmarks();}
function toggleSearch(){const p=document.getElementById('search-panel');p.classList.toggle('show');document.getElementById('overlay').classList.toggle('show',p.classList.contains('show'));closeOtherPanels('search-panel');if(p.classList.contains('show')) document.getElementById('search-input').focus();}
function closeOtherPanels(id){document.querySelectorAll('.settings-panel,.bookmark-panel,.search-panel,.chapter-list-panel').forEach(el=>{if(el.id!==id) el.classList.remove('show');});}
function closeAllPanels(){document.querySelectorAll('.settings-panel,.bookmark-panel,.search-panel,.chapter-list-panel').forEach(el=>el.classList.remove('show'));document.getElementById('overlay').classList.remove('show');}

async function loadBookmarks() {
  try {
    const res = await fetch('/api/bookmarks?bid='+encodeURIComponent(bid));
    const data = await res.json();
    if (data.code===200 && data.bookmarks) {
      const list = document.getElementById('bookmark-list');
      if (!data.bookmarks.length) {list.innerHTML='<div style="opacity:.6;padding:10px;text-align:center">暂无书签</div>';return;}
      let html = '';
      data.bookmarks.forEach((b,i)=>{
        html += '<div style="padding:6px 0;border-bottom:1px solid rgba(128,128,128,.1);display:flex;justify-content:space-between;align-items:center;">'+
          '<span onclick="loadChapter('+b.chapter_idx+');closeAllPanels();" style="cursor:pointer;">第'+(b.chapter_idx+1)+'章'+(b.note?' ('+b.note+')':'')+'</span>'+
          '<button onclick="removeBookmark('+i+')" style="background:transparent;border:none;color:inherit;font-size:16px;cursor:pointer;">✕</button>'+
        '</div>';
      });
      list.innerHTML = html;
    }
  } catch(e){}
}
async function removeBookmark(index) {
  try {
    await fetch('/api/bookmarks', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({action:'remove', bid:bid, index:index})
    });
    loadBookmarks();
  } catch(e){}
}
function updateBookmarks(){ if(document.getElementById('bookmark-panel').classList.contains('show')) loadBookmarks(); }

document.getElementById('search-input').addEventListener('input', function() {
  const keyword = this.value.trim();
  const container = document.getElementById('search-results');
  if (!keyword) {container.innerHTML='';return;}
  const paragraphs = document.querySelectorAll('#chapter-text p');
  let results = [];
  paragraphs.forEach((p,i)=>{
    if (p.textContent.includes(keyword)) {
      results.push('<div style="padding:4px 0;border-bottom:1px solid rgba(128,128,128,.1);cursor:pointer;" onclick="scrollToParagraph('+i+')">'+
        p.textContent.substring(0,80)+'...</div>');
    }
  });
  container.innerHTML = results.length ? results.join('') : '<div style="opacity:.6;padding:8px;">未找到</div>';
});
function scrollToParagraph(idx) {
  const ps = document.querySelectorAll('#chapter-text p');
  if (ps[idx]) { ps[idx].scrollIntoView({behavior:'smooth', block:'center'}); closeAllPanels(); }
}

async function loadChapterList() {
  const itemsDiv = document.getElementById('chapter-list-items');
  if (itemsDiv.children.length) return;
  try {
    const res = await fetch('/api/chapters?bid='+encodeURIComponent(bid));
    const data = await res.json();
    if (data.code===200 && data.chapters) {
      let html = '';
      data.chapters.forEach(ch=>{
        html += '<div class="chapter-item" data-idx="'+ch.idx+'" onclick="loadChapter('+ch.idx+');closeAllPanels();">'+ch.title+'</div>';
      });
      itemsDiv.innerHTML = html || '<div style="opacity:.6;padding:20px;text-align:center">暂无章节</div>';
      updateChapterListCurrent();
    }
  } catch(e){itemsDiv.innerHTML='<div style="color:red;padding:20px">加载失败</div>';}
}
function updateChapterListCurrent(){document.querySelectorAll('.chapter-item').forEach(el=>el.classList.toggle('current',parseInt(el.dataset.idx)===currentIdx));}

function toggleAutoRead() {
  if (autoReading) {
    stopAutoRead();
  } else {
    startAutoRead();
  }
}

function startAutoRead() {
  if (autoReading) return;
  if (!totalChapters || currentIdx >= totalChapters) { showToast('没有可阅读的内容'); return; }
  if (wordCount === 0) { showToast('当前章节字数为0'); return; }
  const scrollHeight = document.documentElement.scrollHeight - window.innerHeight;
  if (scrollHeight <= 0) { showToast('页面内容高度不足'); return; }
  const wordsPerSecond = readingSpeed / 60;
  const pixelsPerWord = scrollHeight / wordCount;
  const pixelsPerSecond = pixelsPerWord * wordsPerSecond;
  if (pixelsPerSecond < 0.1) { showToast('速度过慢，调整阅读速度'); return; }
  
  autoReading = true;
  document.getElementById('btn-auto').textContent = '⏸';
  showToast('自动阅读已启动');
  
  if (manualScrollTimer) { clearTimeout(manualScrollTimer); manualScrollTimer = null; }
  
  isProgrammaticScroll = true;
  setTimeout(() => { if (autoReading) isProgrammaticScroll = false; }, 500);
  
  const interval = 50;
  const step = pixelsPerSecond * (interval / 1000);
  const maxStep = 15;
  const finalStep = Math.min(step, maxStep);
  
  function doScroll() {
    if (!autoReading) {
      isProgrammaticScroll = false;
      return;
    }
    isProgrammaticScroll = true;
    
    const currentScroll = window.scrollY;
    const maxScroll = document.documentElement.scrollHeight - window.innerHeight;
    if (currentScroll >= maxScroll - 3) {
      isProgrammaticScroll = false;
      if (currentIdx < totalChapters - 1) {
        const nextIdx = currentIdx + 1;
        stopAutoRead();
        loadChapter(nextIdx);
        setTimeout(() => { if (!autoReading) startAutoRead(); }, 500);
        return;
      } else {
        showToast('已阅读至最后一章');
        stopAutoRead();
        return;
      }
    }
    window.scrollBy(0, finalStep);
    setTimeout(() => {
      if (autoReading) isProgrammaticScroll = false;
    }, 80);
    
    readingTimer = setTimeout(doScroll, interval);
  }
  
  readingTimer = setTimeout(doScroll, interval);
}

function stopAutoRead() {
  autoReading = false;
  if (readingTimer) {
    clearTimeout(readingTimer);
    readingTimer = null;
  }
  if (manualScrollTimer) {
    clearTimeout(manualScrollTimer);
    manualScrollTimer = null;
  }
  isProgrammaticScroll = false;
  document.getElementById('btn-auto').textContent = '▶';
}

window.addEventListener('scroll', function() {
  if (autoReading && !isProgrammaticScroll) {
    if (manualScrollTimer) clearTimeout(manualScrollTimer);
    manualScrollTimer = setTimeout(() => {
      if (autoReading) {
        stopAutoRead();
        showToast('手动滚动，自动阅读已暂停');
      }
      manualScrollTimer = null;
    }, 300);
  }
});

function showLoading(show,msg){const el=document.getElementById('loading');el.textContent=msg||'加载中...';el.style.display=show?'block':'none';}
function showError(msg){const el=document.getElementById('error-box');document.getElementById('error-msg').textContent=msg;el.style.display='block';}
function hideError(){document.getElementById('error-box').style.display='none';}
function showToast(msg){const el=document.getElementById('loading');el.textContent=msg;el.style.display='block';setTimeout(()=>el.style.display='none',1500);}

let touchStartX=0, touchStartY=0;
document.addEventListener('touchstart', function(e){touchStartX=e.touches[0].clientX; touchStartY=e.touches[0].clientY;});
document.addEventListener('touchend', function(e){
  if (!touchStartX) return;
  const dx = e.changedTouches[0].clientX - touchStartX;
  const dy = e.changedTouches[0].clientY - touchStartY;
  if (Math.abs(dx)>50 && Math.abs(dx)>Math.abs(dy)*1.5) {
    if (autoReading) stopAutoRead();
    dx>0 ? prevChapter() : nextChapter();
  }
  touchStartX=0;
});

setInterval(function(){
  if (totalChapters>0) {
    const dur = Math.round((Date.now() - readStartTime)/1000);
    saveStatistics(dur, 0);
    readStartTime = Date.now();
  }
}, 60000);

window.addEventListener('beforeunload', function(){
  if (readingTimer) clearTimeout(readingTimer);
  const dur = Math.round((Date.now() - readStartTime)/1000);
  saveStatistics(dur, 0);
  saveProgress();
});
</script>
</body>
</html>
"""

# ============ Spider 主类 ============
sys.path.append('..')
try:
    from base.spider import Spider as BaseSpider
except ImportError:
    try:
        from base.spider import BaseSpider
    except ImportError:
        class BaseSpider:
            pass

class Spider(BaseSpider):
    home_url = ''
    default_poster = CONFIG["default_poster"]

    server = None
    server_port = 0
    server_started = False
    chapter_cache = None
    last_auto_open = {"bid": None, "t": 0}

    def __init__(self):
        self._session = requests.Session()
        self.base_url = f"{CONFIG['protocol']}://{CONFIG['site_domain']}"
        self.home_url = self.base_url
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 Chrome/114.0.0.0 Mobile Safari/537.36",
            "Referer": self.base_url,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        }
        self._content_cache = {}
        self._content_cache_lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=6, thread_name_prefix="spider")
        self._preload_threads = set()

    def getName(self):
        return "悠久小说"

    def init(self, extend=""):
        _log("init start")
        _ensure_data_dir()
        self.progress_mgr = ProgressManager()
        self.settings = SettingsManager()
        self.chapter_cache = ChapterCache()
        self.bookmark_mgr = BookmarkManager()
        self.stat_mgr = StatisticsManager()
        CONFIG.update(self.settings.all())
        self._start_server()
        _log("init done, server_port=" + str(self.server_port))

    def destroy(self):
        if self.server:
            try:
                self.server.shutdown()
            except Exception:
                pass
            self.server = None
            self.server_started = False
        if hasattr(self, '_session'):
            self._session.close()
        if hasattr(self, '_executor'):
            self._executor.shutdown(wait=False)
        self._content_cache.clear()
        _log("destroyed")

    def getDependence(self):
        return []
    def isVideoFormat(self, url):
        return False
    def manualVideoCheck(self):
        pass
    def localProxy(self, params):
        pass

    # ---- 辅助方法 ----
    def _fetch_page(self, url, timeout=15):
        try:
            r = self._session.get(url, headers=self.headers, timeout=timeout)
            r.encoding = 'utf-8'
            return r.text
        except Exception as e:
            _log(f"fetch error {url}: {e}")
            return None

    def _get_cached_content(self, bid, cid):
        key = f"{bid}::{cid}"
        with self._content_cache_lock:
            return self._content_cache.get(key)

    def _set_cached_content(self, bid, cid, content):
        key = f"{bid}::{cid}"
        with self._content_cache_lock:
            if len(self._content_cache) > 200:
                oldest = next(iter(self._content_cache))
                del self._content_cache[oldest]
            self._content_cache[key] = content

    def _preload_chapter(self, bid, cid):
        try:
            content = self.fetch_online_chapter(bid, cid)
            self._set_cached_content(bid, cid, content)
        except Exception:
            pass

    def _start_preload_adjacent(self, bid, current_idx, total):
        """预加载相邻章节 - 修复：传cid而非索引"""
        chapters = self.chapter_cache.get(bid)
        if not chapters:
            return
        for delta in [-1, 1, -2, 2]:
            target = current_idx + delta
            if 0 <= target < total and target < len(chapters):
                cid = chapters[target].get('cid', '')
                if cid:
                    t = threading.Thread(target=self._preload_chapter, args=(bid, cid), daemon=True)
                    t.start()
                    self._preload_threads.add(t)

    # ---- 分类页解析 ----
    def _parse_category_page(self, html):
        """
        解析分类页，返回书籍列表
        修复：使用 #sitembox dl 精确定位"最近更新列表"区域
        原代码XPath完全不匹配实际HTML结构，且可能从"热力推荐"区重复抓取
        """
        root = etree.HTML(html)
        items = []
        seen = set()

        # 实际结构: <div id="sitembox"><dl>...</dl></div>
        book_blocks = root.xpath('//div[@id="sitembox"]//dl')
        if not book_blocks:
            # 备用：匹配所有包含 /book/ 链接的 dl
            book_blocks = root.xpath('//dl[.//a[contains(@href, "/book/")]]')

        for block in book_blocks:
            try:
                # 书名和链接 - 从 dd > h3 > a 或 dt > a
                title_a = block.xpath('.//dd//h3//a')
                if not title_a:
                    title_a = block.xpath('.//dt//a')
                if not title_a:
                    continue

                title = "".join(title_a[0].xpath('.//text()')).strip()
                if not title:
                    # 从 img alt 属性获取书名
                    img_alt = block.xpath('.//dt//a/img/@alt')
                    title = img_alt[0].strip() if img_alt else ""
                if not title:
                    continue

                href = title_a[0].get('href', '')
                match = re.search(r'/book/(\d+)/', href)
                if not match:
                    continue
                bid = match.group(1)
                # 去重
                if bid in seen:
                    continue
                seen.add(bid)

                if not href.startswith('http'):
                    href = self.base_url + href

                # 封面 - 从 dt > a > img@src
                img = block.xpath('.//dt//a/img/@src')
                pic = img[0].strip() if img else self.default_poster
                if pic and not pic.startswith('http'):
                    pic = self.base_url + pic

                # 作者和状态 - 从 dd.book_other
                book_dds = block.xpath('.//dd[@class="book_other"]')
                author = ""
                status = ""
                latest_chapter = ""
                if book_dds:
                    # 第一个 book_other dd 包含作者和状态
                    author_a = book_dds[0].xpath('.//a[contains(@href, "/author/")]/text()')
                    author = author_a[0].strip() if author_a else ""
                    # 状态：从 dd 全文中用正则提取（作者在<a>内，span/text() 不含作者文本）
                    dd_text = "".join(book_dds[0].xpath('.//text()'))
                    status_match = re.search(r'状态：(.+)', dd_text)
                    if status_match:
                        status = status_match.group(1).strip()
                    # 第二个 book_other dd 包含最新章节
                    if len(book_dds) >= 2:
                        latest_a = book_dds[1].xpath('.//a/text()')
                        latest_chapter = latest_a[0].strip() if latest_a else ""

                # 简介 - 从 dd.book_des
                intro = "".join(block.xpath('.//dd[@class="book_des"]/text()')).strip()

                # remarks 显示状态或最新章节
                remarks = status or latest_chapter

                items.append({
                    "vod_id": bid,
                    "vod_name": title,
                    "vod_pic": pic,
                    "vod_author": author,
                    "vod_remarks": remarks,
                    "vod_content": intro
                })
            except Exception as e:
                _log(f"parse category item error: {e}")

        _log(f"_parse_category_page: 解析到 {len(items)} 本书")
        return items

    # ---- TVBox 接口 ----
    def homeContent(self, filter):
        categories = [
            {'type_id': 'xuanhuan', 'type_name': '玄幻奇幻'},
            {'type_id': 'wuxia', 'type_name': '仙侠修真'},
            {'type_id': 'dushi', 'type_name': '都市青春'},
            {'type_id': 'lishi', 'type_name': '历史军事'},
            {'type_id': 'youxi', 'type_name': '游戏动漫'},
            {'type_id': 'kehuan', 'type_name': '科幻灵异'},
            {'type_id': 'yanqing', 'type_name': '女生言情'},
        ]
        return {'class': categories, 'filters': {}}

    def homeVideoContent(self):
        return self.categoryContent('xuanhuan', '1', None, {})

    def categoryContent(self, cid, pg, filter, extend):
        page = int(pg) if pg else 1
        if page == 1:
            url = f"{self.base_url}/{cid}/"
        else:
            url = f"{self.base_url}/{cid}/{page}/"
        html = self._fetch_page(url)
        if not html:
            return {'list': []}
        items = self._parse_category_page(html)
        # 获取总页数（从分页链接）
        root = etree.HTML(html)
        last_page_link = root.xpath('//a[contains(text(), "尾页")]/@href')
        total_pages = 1
        if last_page_link:
            match = re.search(r'/(\d+)/$', last_page_link[0])
            if match:
                total_pages = int(match.group(1))
        return {'list': items, 'page': page, 'pagecount': total_pages, 'limit': 20, 'total': total_pages * 20}

    # ---- 章节列表解析 ----
    def _parse_chapter_list(self, html, bid):
        """
        解析 /read/{bid}/ 页面，返回所有章节
        修复：原代码第三条XPath中 f"/read/{bid}/" 是 f-string 语法误写在XPath字符串内
        导致XPath语法错误，章节列表永远解析失败
        实际结构: <div id="readerlist"><ul><li><a href="/read/{bid}/{cid}.html">章节名</a></li></ul></div>
        """
        root = etree.HTML(html)
        # 章节在 #readerlist > ul > li > a
        links = root.xpath('//div[@id="readerlist"]//li/a')
        if not links:
            # 备用：使用Python f-string 正确构建XPath
            links = root.xpath(f'//a[contains(@href, "/read/{bid}/") and contains(@href, ".html")]')
        chapters = []
        seen = set()
        for a in links:
            title = "".join(a.xpath('.//text()')).strip()
            if not title:
                continue
            href = a.get('href', '')
            match = re.search(r'/(\d+)\.html$', href)
            if not match:
                continue
            cid = match.group(1)
            if cid in seen:
                continue
            seen.add(cid)
            if not href.startswith('http'):
                href = self.base_url + href
            chapters.append({"title": title, "url": href, "cid": cid})
        _log(f"_parse_chapter_list: 解析到 {len(chapters)} 章")
        return chapters

    # ---- 详情页 ----
    def detailContent(self, ids):
        """
        修复：所有XPath均不匹配实际HTML结构
        实际结构:
          书名: <div class="d_title"><h1>书名<em>作者：<a>作者名</a></em></h1>
          封面: <div id="bookimg"><a><img src="..." /></a></div>
          简介: <div id="bookintro">...</div>
          状态: <div class="novel_status" data-status="1">
          分类: <div id="count"><span>玄幻奇幻</span>...</div>
        """
        bid = ids[0] if isinstance(ids, list) else ids
        if not bid.isdigit():
            match = re.search(r'/book/(\d+)/', bid)
            if match:
                bid = match.group(1)
            else:
                return {'list': []}
        detail_url = f"{self.base_url}/book/{bid}/"
        html = self._fetch_page(detail_url)
        if not html:
            return {'list': []}
        root = etree.HTML(html)

        # 书名 - 从 d_title > h1 的直接文本节点（不含 <em> 内的作者信息）
        name = ""
        h1_texts = root.xpath('//div[@class="d_title"]//h1/text()')
        if h1_texts:
            name = h1_texts[0].strip()
        if not name:
            h1_texts = root.xpath('//h1/text()')
            if h1_texts:
                name = h1_texts[0].strip()

        # 作者 - 从 d_title > h1 > em > a 或通用 author 链接
        author = ""
        author_nodes = root.xpath('//div[@class="d_title"]//h1//em//a/text()')
        if not author_nodes:
            author_nodes = root.xpath('//a[contains(@href, "/author/")]/text()')
        if author_nodes:
            author = author_nodes[0].strip()

        # 封面 - 从 #bookimg > img@src
        pic = ""
        pic_nodes = root.xpath('//div[@id="bookimg"]//img/@src')
        if not pic_nodes:
            pic_nodes = root.xpath('//img[contains(@src, "files/article/image")]/@src')
        if pic_nodes:
            pic = pic_nodes[0].strip()
            if pic and not pic.startswith('http'):
                pic = self.base_url + pic
        if not pic:
            pic = self.default_poster

        # 简介 - 从 #bookintro
        intro = ""
        intro_nodes = root.xpath('//div[@id="bookintro"]//text()')
        if intro_nodes:
            intro = "".join(intro_nodes).strip()

        # 分类 - 从 #count 第一个 span
        category = ""
        cat_nodes = root.xpath('//div[@id="count"]//span[1]/text()')
        if cat_nodes:
            category = cat_nodes[0].strip()

        # 状态 - 从 novel_status data-status 属性
        status = ""
        status_attr = root.xpath('//div[@class="novel_status"]/@data-status')
        if status_attr:
            status = "连载中" if status_attr[0] == "1" else "已完结"

        # 获取完整目录
        catalog_url = f"{self.base_url}/read/{bid}/"
        catalog_html = self._fetch_page(catalog_url)
        if not catalog_html:
            return {'list': []}
        chapters = self._parse_chapter_list(catalog_html, bid)
        if not chapters:
            return {'list': []}
        self.chapter_cache.put(bid, chapters)

        # 构建播放URL
        play_urls = []
        for idx, ch in enumerate(chapters):
            play_urls.append(f"{ch['title']}${bid}@@{idx}")
        play_url = "#".join(play_urls)

        vod = {
            "vod_id": bid,
            "vod_name": name,
            "vod_pic": pic,
            "vod_actor": author,
            "vod_content": f"分类：{category}\n状态：{status}\n\n{intro}",
            "vod_play_from": "悠久小说",
            "vod_play_url": play_url
        }

        # 自动打开阅读器
        progress = self.progress_mgr.get(bid)
        start_idx = int(progress.get("chapter_index", 0))
        self._ensure_server()
        self._auto_open_reader(bid, str(start_idx))
        self._start_preload_adjacent(bid, start_idx, len(chapters))

        return {"list": [vod]}

    # ---- 搜索 ----
    def searchContent(self, key, quick, pg="1"):
        page = int(pg) if pg else 1
        try:
            r = self._session.post(
                self.base_url + '/searchbooks.php',
                data={'searchkey': key},
                headers=self.headers,
                timeout=10
            )
            r.encoding = 'utf-8'
            items = self._parse_search_results(r.text)
            return {'list': items, 'page': page}
        except Exception as e:
            _log(f"search error: {e}")
            return {'list': []}

    def _parse_search_results(self, html):
        """
        修复：XPath不匹配搜索结果结构
        实际结构:
          <div class="shulist">
            <ul>
              <li class="one">序号</li>
              <li class="two">类别</li>
              <li class="three"><a href="/book/{bid}/">书名</a>
                <span class="gray"><a href="/read/...">最新章节</a></span></li>
              <li class="four"><a href="/author/...">作者</a></li>
              <li class="five">更新时间</li>
              <li class="six">状态</li>
            </ul>
          </div>
        """
        root = etree.HTML(html)
        items = []
        seen = set()

        # 搜索结果在 div.shulist > ul
        result_rows = root.xpath('//div[@class="shulist"]//ul')
        for row in result_rows:
            try:
                # 书名链接在 li.three > a[href*="/book/"]
                title_a = row.xpath('.//li[@class="three"]//a[contains(@href, "/book/")]')
                if not title_a:
                    continue
                title = "".join(title_a[0].xpath('.//text()')).strip()
                if not title:
                    continue
                href = title_a[0].get('href', '')
                match = re.search(r'/book/(\d+)/', href)
                if not match:
                    continue
                bid = match.group(1)
                if bid in seen:
                    continue
                seen.add(bid)
                if not href.startswith('http'):
                    href = self.base_url + href

                # 作者在 li.four
                author_nodes = row.xpath('.//li[@class="four"]//a/text()')
                author = author_nodes[0].strip() if author_nodes else ""

                # 类别在 li.two
                cat_nodes = row.xpath('.//li[@class="two"]/text()')
                category = cat_nodes[0].strip() if cat_nodes else ""

                # 状态在 li.six
                status_nodes = row.xpath('.//li[@class="six"]/text()')
                status = status_nodes[0].strip() if status_nodes else ""

                # 最新章节在 li.three > span.gray > a
                latest_nodes = row.xpath('.//li[@class="three"]//span[@class="gray"]//a/text()')
                latest = latest_nodes[0].strip() if latest_nodes else ""

                items.append({
                    "vod_id": bid,
                    "vod_name": title,
                    "vod_pic": self.default_poster,
                    "vod_remarks": status or latest,
                    "vod_content": f"作者：{author}\n分类：{category}\n最新：{latest}"
                })
            except Exception:
                continue

        # 备用：如果上面的方式没有匹配到，尝试通用匹配
        if not items:
            all_book_links = root.xpath('//a[contains(@href, "/book/")]')
            for a in all_book_links:
                try:
                    title = "".join(a.xpath('.//text()')).strip()
                    if not title or len(title) > 50:
                        continue
                    href = a.get('href', '')
                    match = re.search(r'/book/(\d+)/', href)
                    if not match:
                        continue
                    bid = match.group(1)
                    if bid in seen:
                        continue
                    seen.add(bid)
                    if not href.startswith('http'):
                        href = self.base_url + href
                    items.append({
                        "vod_id": bid,
                        "vod_name": title,
                        "vod_pic": self.default_poster,
                        "vod_remarks": "",
                        "vod_content": ""
                    })
                except Exception:
                    continue

        _log(f"_parse_search_results: 搜索到 {len(items)} 本书")
        return items

    # ---- 正文获取 ----
    def fetch_online_chapter(self, bid, cid):
        """
        修复：原代码提取整个 mlfy_main_text div（含书签按钮、章节标题、作者信息、推荐按钮）
        实际正文在 mlfy_main_text > div.read-content 中
        修复：返回原始HTML，由 serve_chapter_data 统一净化，避免双重处理
        """
        try:
            cached = self._get_cached_content(bid, cid)
            if cached:
                return cached
            chapter_url = f"{self.base_url}/read/{bid}/{cid}.html"
            html = self._fetch_page(chapter_url)
            if not html:
                return "<p style='color:red'>章节加载失败</p>"
            root = etree.HTML(html)

            # 正文在 mlfy_main_text > div.read-content
            content_div = root.xpath('//div[@id="mlfy_main_text"]//div[@class="read-content"]')
            if not content_div:
                # 备用：直接找 read-content
                content_div = root.xpath('//div[@class="read-content"]')
            if not content_div:
                # 备用：找 mlfy_main_text（包含标题等额外内容）
                content_div = root.xpath('//div[@id="mlfy_main_text"]')
            if not content_div:
                return "<p style='color:red'>未找到正文内容</p>"

            inner_html = etree.tostring(content_div[0], method='html', encoding='unicode')

            # 缓存原始HTML（不含净化和<p>包装），由调用方按需处理
            self._set_cached_content(bid, cid, inner_html)
            return inner_html
        except Exception as e:
            _log(f"fetch_online_chapter error: {e}")
            return f"<p style='color:red'>加载失败: {str(e)}</p>"

    # ---- playerContent ----
    def playerContent(self, flag, id, vipFlags):
        try:
            parts = id.split('$')
            if len(parts) != 2:
                return {'parse': 0, 'playUrl': '', 'url': '', 'header': ''}
            bid_idx = parts[1]
            bid, idx = bid_idx.split('@@')
            self.progress_mgr.update(bid, int(idx))
            self._ensure_server()
            threading.Thread(target=self._show_popup_dialog, args=(bid, idx), daemon=True).start()
            return {'parse': 0, 'playUrl': '', 'url': 'http://127.0.0.1/dummy', 'header': ''}
        except Exception as e:
            _log(f"playerContent error: {e}")
            return {'parse': 0, 'playUrl': '', 'url': '', 'header': ''}

    # ---- 服务器 ----
    def _ensure_server(self):
        if self.server_started and self.server:
            return True
        return self._start_server()

    def _start_server(self):
        if self.server_started and self.server:
            return True
        _ensure_data_dir()
        if self.chapter_cache is None:
            self.chapter_cache = ChapterCache()
        port_range = list(range(10800, 10900)) + list(range(8080, 8100))
        for port in port_range:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                if sock.connect_ex(('127.0.0.1', port)) == 0:
                    sock.close()
                    continue
                sock.close()
                self.server = ThreadedHTTPServer(('127.0.0.1', port), NovelHandler)
                self.server.spider = self
                self.server_port = port
                t = threading.Thread(target=self.server.serve_forever, daemon=True)
                t.start()
                time.sleep(0.3)
                test = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                test.settimeout(1)
                if test.connect_ex(('127.0.0.1', port)) == 0:
                    test.close()
                    self.server_started = True
                    _log(f"服务器启动成功，端口: {port}")
                    return True
                test.close()
            except Exception:
                continue
        return False

    def _auto_open_reader(self, bid, index):
        try:
            now = time.time()
            if self.last_auto_open.get("bid") != bid or (now - self.last_auto_open.get("t", 0)) > 3:
                self.last_auto_open = {"bid": bid, "t": now}
                threading.Thread(target=self._show_popup_dialog, args=(bid, index), daemon=True).start()
        except Exception:
            pass

    def _show_popup_dialog(self, bid, index):
        if not self.server_started and not self._start_server():
            return
        try:
            from java import jclass, dynamic_proxy
            from java.lang import Runnable
            AT = jclass("java.lang.Class").forName("android.app.ActivityThread")
            currentAT = AT.getMethod("currentActivityThread").invoke(None)
            mActivities = AT.getDeclaredField("mActivities")
            mActivities.setAccessible(True)
            # 修复“需返回一次才显示阅读器”：弹窗在后台线程触发时，TVBox 详情/播放页 Activity 可能尚未 resumed，
            # 旧逻辑只取“第一个未销毁”的 Activity（常是被覆盖的上一页），导致 Dialog 被压在新页面之下。
            # 这里短暂等待并优先选择 isResumed() 的前台 Activity，确保阅读器直接置顶显示。
            act = None
            for _wait_i in range(10):
                try:
                    _vals = mActivities.get(currentAT).values()
                    try:
                        _recs = _vals.toArray()
                    except Exception:
                        _recs = _vals.getClass().getMethod("toArray").invoke(_vals)
                    _fallback = None
                    for r in _recs:
                        try:
                            _af = r.getClass().getDeclaredField("activity")
                            _af.setAccessible(True)
                            _a = _af.get(r)
                            if _a and not _a.isFinishing() and not _a.isDestroyed():
                                if _fallback is None:
                                    _fallback = _a
                                try:
                                    if _a.isResumed():
                                        act = _a
                                        break
                                except Exception:
                                    pass
                        except Exception:
                            continue
                    if act is None:
                        act = _fallback
                    if act is not None:
                        try:
                            if act.isResumed():
                                break
                        except Exception:
                            break
                except Exception:
                    pass
                time.sleep(0.1)
            if not act:
                return
            port = self.server_port
            cache_bid = bid
            cache_idx = index

            class UiRunner(dynamic_proxy(Runnable)):
                def __init__(self, func):
                    super().__init__()
                    self.func = func
                def run(self):
                    try:
                        self.func()
                    except Exception as e:
                        _log(f"UI runner error: {e}")

            def show():
                try:
                    Dialog = jclass("android.app.Dialog")
                    WebView = jclass("android.webkit.WebView")
                    ColorDrawable = jclass("android.graphics.drawable.ColorDrawable")
                    Color = jclass("android.graphics.Color")
                    d = Dialog(act)
                    d.requestWindowFeature(1)
                    win = d.getWindow()
                    if win:
                        win.getDecorView().setPadding(0, 0, 0, 0)
                        win.setBackgroundDrawable(ColorDrawable(Color.parseColor("#f8f1e3")))
                        win.setLayout(-1, -1)
                    w = WebView(act)
                    ws = w.getSettings()
                    ws.setJavaScriptEnabled(True)
                    ws.setDomStorageEnabled(True)
                    ws.setSupportZoom(True)
                    ws.setBuiltInZoomControls(True)
                    ws.setDisplayZoomControls(False)
                    ws.setUseWideViewPort(True)
                    ws.setLoadWithOverviewMode(True)
                    ws.setTextZoom(100)
                    ws.setAllowFileAccess(True)
                    ws.setAllowContentAccess(True)
                    w.setBackgroundColor(Color.parseColor("#f8f1e3"))
                    url = f"http://127.0.0.1:{port}/read.html?bid={urllib.parse.quote(str(cache_bid))}&idx={cache_idx}"
                    w.loadUrl(url)
                    d.setContentView(w)
                    d.show()
                except Exception as e:
                    _log(f"show dialog error: {e}")

            act.runOnUiThread(UiRunner(show))
        except Exception as e:
            _log(f"popup error: {e}")
