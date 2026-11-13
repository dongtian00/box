# coding=utf-8
# !/usr/bin/python
"""
@BNTB
起初笔者在摸鱼接口使用推送网盘链接会被覆盖，如果是多个网盘链接的话就在推送中，无法在壳子上保存。所以想找一个网盘推送管理的源，但是没找到，本小白只能自己写了。所以写了这么一个，没啥用。。。
默影视测试正常。
"""
import requests
import re
import json
import sys
import os
import time
import threading
import urllib.parse

sys.path.append('..')

from base.spider import Spider

# ═══════════════════════════════════════════════════════════════
# 配置，无须管，面板上面操作就行了
# ═══════════════════════════════════════════════════════════════

CFG_PATH = "/storage/emulated/0/easybox/box/data/pan_subs/subscriptions.json"
UA = "Mozilla/5.0 (Linux; Android 12; TV) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36"
HEADERS = {"User-Agent": UA}
REQUEST_TIMEOUT = 8

# 元配置文件（记录用户自定义的存储位置），与本 spider.py 同级
try:
    _SPIDER_DIR = os.path.dirname(os.path.abspath(__file__))
except Exception:
    _SPIDER_DIR = "/storage/emulated/0/easybox/box/py"
META_PATH = os.path.join(_SPIDER_DIR, "pan_sub_meta.json")

# 网盘域名集合（命中 → WebView 打开）
PAN_HOSTS = (
    "pan.quark.cn", "quark.cn",
    "alipan.com", "aliyundrive.com", "aliyundrive.net",
    "pan.baidu.com",
    "115.com", "u.115.com", "anxia.com",
    "pan.xunlei.com",
    "drive.uc.cn", "ucx.com",
    "123pan.com", "www.123pan.com", "123684.com", "123865.com", "123912.com",
    "cloud.189.cn",
    "lanzou.com", "lanzoui.com", "lanzoux.com", "lanzouw.com", "lanzouo.com", "lanzouj.com", "lanzoul.com",
    "cowtransfer.com", "weiyun.com", "drive.uc.cn",
)

VIDEO_EXT_RE = re.compile(r"\.(m3u8|mp4|flv|mkv|webm|mov|ts|avi|rmvb|wmv|m4v)(\?|$)", re.I)
YEAR_RE = re.compile(r"(19\d{2}|20\d{2})")

# 字段名映射（自适应订阅 JSON）
KEY_MAP = {
    "vod_id": ("vod_id", "id", "vid", "v_id", "vodId"),
    "vod_name": ("vod_name", "name", "title", "vod_title", "show_name", "media_name", "vodName"),
    "vod_pic": ("vod_pic", "pic", "pic_url", "image", "img", "thumb", "poster", "cover", "vod_pic_url", "vodPic"),
    "vod_remarks": ("vod_remarks", "remarks", "remark", "subtitle", "note", "desc", "description", "episode", "extra"),
    "vod_year": ("vod_year", "year", "vodYear"),
    "vod_play_from": ("vod_play_from", "play_from", "source", "from", "vodPlayFrom"),
    "vod_play_url": ("vod_play_url", "play_url", "playUrl", "vodPlayUrl", "url", "link", "share_url", "m3u8", "video"),
    "vod_content": ("vod_content", "content", "info", "vodContent"),
}


def _first_match(item, names, default=""):
    for n in names:
        v = item.get(n)
        if v is None:
            continue
        if isinstance(v, str):
            v = v.strip()
            if v:
                return v
        else:
            return v
    return default


# ═══════════════════════════════════════════════════════════════
# 弹窗基础设施（内联，无外部依赖）
# ═══════════════════════════════════════════════════════════════

_DIALOG_REFS = []


def _keep(*objs):
    _DIALOG_REFS.extend(objs)
    while len(_DIALOG_REFS) > 12:
        _DIALOG_REFS.pop(0)


def _current_activity():
    from java import jclass
    activity_class = jclass("android.app.Activity")
    modifier_class = jclass("java.lang.reflect.Modifier")
    activity_info = activity_class.getClass()

    # 尝试多个常见壳的 App 类名
    app_class_names = [
        "com.fongmi.android.tv.App",          # FongMi/TVBox
        "com.github.tvbox.osc.base.App",       # 影视仓/OK
        "com.hero.unused.App",                  # PeekPro 等
        "com.hero.unused.tvbox.App",            # 其他变体
        "android.app.ActivityThread",           # 通用方法
    ]
    app_class = None
    for name in app_class_names:
        try:
            app_class = jclass(name)
            # 验证是否真的是 App 类
            app_class.getClass()
            break
        except Exception:
            continue

    if app_class is not None:
        app_info = app_class.getClass()
        # 尝试通过静态方法获取 Activity
        for method in app_info.getDeclaredMethods():
            try:
                if not modifier_class.isStatic(method.getModifiers()):
                    continue
                if len(method.getParameterTypes()) != 0:
                    continue
                if not activity_info.isAssignableFrom(method.getReturnType()):
                    continue
                method.setAccessible(True)
                try:
                    activity = method.invoke(None, [])
                except Exception:
                    activity = method.invoke(None)
                if activity is not None:
                    return activity
            except Exception:
                continue

        # 尝试通过静态字段获取 App 实例，再反射 Activity
        app = None
        for field in app_info.getDeclaredFields():
            try:
                if not modifier_class.isStatic(field.getModifiers()):
                    continue
                if not app_info.isAssignableFrom(field.getType()):
                    continue
                field.setAccessible(True)
                app = field.get(None)
                if app is not None:
                    break
            except Exception:
                continue
        if app is not None:
            for field in app.getClass().getDeclaredFields():
                try:
                    if modifier_class.isStatic(field.getModifiers()):
                        continue
                    if not activity_info.isAssignableFrom(field.getType()):
                        continue
                    field.setAccessible(True)
                    activity = field.get(app)
                    if activity is not None:
                        return activity
                except Exception:
                    continue

    # 兜底：通过 ActivityThread 获取当前 Activity（通用方法）
    try:
        at_class = jclass("android.app.ActivityThread")
        at = at_class.currentActivityThread()
        if at is not None:
            activities = at.getActivities()
            if activities is not None:
                for ref in activities.values():
                    activity = ref.getActivity()
                    if activity is not None:
                        return activity
    except Exception:
        pass

    raise RuntimeError("未找到当前 Activity，请确认壳支持")


def _builder_class():
    from java import jclass
    try:
        return jclass("com.google.android.material.dialog.MaterialAlertDialogBuilder")
    except Exception:
        return jclass("android.app.AlertDialog$Builder")


def _toast(text):
    from java import jclass
    tc = jclass("android.widget.Toast")
    tc.makeText(_current_activity(), str(text), tc.LENGTH_LONG).show()


def _toast_ui(text):
    """任意线程安全 Toast（包装 runOnUiThread）"""
    from java import dynamic_proxy, jclass
    runnable_class = jclass("java.lang.Runnable")
    activity = _current_activity()

    class Show(dynamic_proxy(runnable_class)):
        def run(self):
            _toast(text)

    runner = Show()
    _keep(runner)
    try:
        activity.runOnUiThread(runner)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════
# Spider 类
# ═══════════════════════════════════════════════════════════════

class Spider(Spider):

    SETTINGS_TID = "pan_settings"
    ACTION_ADD = "pan_add"            # ➕ 手动添加（链接+分类多选）
    ACTION_PASTE = "pan_paste"        # 📋 粘贴分享消息自动识别
    ACTION_TOGGLE = "pan_toggle"      # ☷ 分类开关
    ACTION_CAT_ADD = "pan_cat_add"    # ➕ 新增自定义分类
    ACTION_CAT_DEL = "pan_cat_del"    # 🗑 删除分类
    ACTION_HELP = "pan_help"          # ⓘ 帮助
    ACTION_EDIT_PREFIX = "pan_edit:"  # ✏️ 编辑条目  pan_edit:<id>
    ACTION_DEL_PREFIX = "pan_del:"    # 🗑 删除条目  pan_del:<id>
    ACTION_MGR_PREFIX = "pan_mgr:"    # ⚙️ 管理分类  pan_mgr:<tid>
    ACTION_MGR_RENAME = "pan_mgr_rename:"   # 改备注名 pan_mgr_rename:<item_id>
    ACTION_MGR_OUT = "pan_mgr_out:"         # 移出分类 pan_mgr_out:<item_id>
    ACTION_MGR_COPY = "pan_mgr_copy:"       # 复制链接 pan_mgr_copy:<item_id>
    ACTION_SET_PATH = "pan_set_path"        # 📁 更改存储位置
    ACTION_COOKIE = "pan_cookie"          # 🍪 网盘 Cookie 管理
    ACTION_PUSHLOG = "pan_pushlog"        # 📝 推送日志开关

    def __init__(self):
        super().__init__()
        self.cache = {}  # sub_id -> items

    def init(self, extend=""):
        """壳加载时必调：接收扩展参数，重置缓存；
        extend 可指定数据文件路径（优先于元配置/默认）"""
        self.cache = {}
        if extend:
            e = str(extend).strip()
            if e.startswith("/") or e.startswith("file://"):
                e = e.replace("file://", "", 1)
                if e.endswith(".json"):
                    meta = self._load_meta()
                    meta["cfg_path"] = e
                    self._save_meta(meta)
                    global CFG_PATH
                    CFG_PATH = e

    def getDependence(self):
        return []

    # ── 基础工具 ─────────────────────────────────────────────

    def fetch(self, url, headers=None, timeout=None, body=None):
        """HTTP GET/POST，直接用 requests（兼容无基类 fetch 的壳）"""
        hd = headers or HEADERS
        try:
            if body is not None:
                return requests.post(url, headers=hd, data=body, timeout=timeout or REQUEST_TIMEOUT)
            return requests.get(url, headers=hd, timeout=timeout or REQUEST_TIMEOUT)
        except Exception:
            raise

    def isVideoFormat(self, url):
        return bool(VIDEO_EXT_RE.search(url or ""))

    # ── 配置读写（持久化） ───────────────────────────────────

    def _load_cfg(self):
        try:
            p = self._get_cfg_path()
            # 自动检测：.gz 文件解压读，.json 文件直接读
            if p.endswith(".gz"):
                import gzip
                try:
                    with gzip.open(p, "rb") as f:
                        return json.loads(f.read().decode("utf-8"))
                except FileNotFoundError:
                    # .gz 文件不存在，回退到 .json
                    json_p = p[:-3]  # 去掉 .gz
                    try:
                        with open(json_p, "r", encoding="utf-8") as f:
                            return json.load(f)
                    except FileNotFoundError:
                        return {}
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    # ── 元配置（自定义存储位置） ─────────────────────────────

    def _load_meta(self):
        try:
            with open(META_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_meta(self, meta):
        try:
            d = os.path.dirname(META_PATH)
            if d and not os.path.isdir(d):
                os.makedirs(d, exist_ok=True)
            tmp = META_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            os.replace(tmp, META_PATH)
            return True
        except Exception:
            return False

    def _get_cfg_path(self):
        """获取当前数据文件路径：优先 extend 指定，其次元配置，最后默认。
        自动转为 .gz 后缀（压缩存储）。"""
        meta = self._load_meta()
        p = meta.get("cfg_path", "") or ""
        if not p:
            p = CFG_PATH
        else:
            p = p.replace("file://", "", 1).strip()
        if not p.startswith("/"):
            p = CFG_PATH
        # 去掉尾部重复 .gz
        while p.endswith(".gz"):
            p = p[:-3]
        # 转为 .json 路径，再加 .gz
        if not p.endswith(".json"):
            p += ".json"
        return p + ".gz"

    def _save_cfg(self, data):
        try:
            p = self._get_cfg_path()
            d = os.path.dirname(p)
            if d and not os.path.isdir(d):
                os.makedirs(d, exist_ok=True)
            import gzip
            tmp = p + ".tmp"
            with gzip.open(tmp, "wb") as f:
                f.write(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            os.replace(tmp, p)
            return True
        except Exception:
            return False

    def _read_text_file(self, path):
        """读取文本文件内容（容错）"""
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return ""

    def _write_text_file(self, path, content):
        """原子写文本文件（带换行结尾）"""
        try:
            d = os.path.dirname(path)
            if d and not os.path.isdir(d):
                os.makedirs(d, exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp, path)
            return True
        except Exception:
            return False

    # ── 配置读写（持久化） ───────────────────────────────────

    # 内置分类（固定）；用户可新增自定义分类
    DEFAULT_CATS = [
        ("quark", "夸克"),
        ("baidu", "百度"),
        ("uc", "UC"),
        ("xunlei", "迅雷"),
        ("other", "其他"),
    ]

    # 网盘关键词（用于粘贴文本段识别：百度：链接 提取码：xxx）
    PAN_KW = [
        ("百度", "baidu", "百度网盘"),
        ("夸克", "quark", "夸克网盘"),
        ("UC", "uc", "UC网盘"),
        ("迅雷", "xunlei", "迅雷网盘"),
        ("阿里", "alipan", "阿里云盘"),
        ("115", "pan115", "115网盘"),
        ("123", "pan123", "123云盘"),
        ("天翼", "tianyi", "天翼云盘"),
        ("蓝奏", "lanzou", "蓝奏云"),
        ("其他", "other", "网盘"),
    ]

    def _load_categories(self):
        """全部分类（内置+自定义）：{cat_id: {"name":..., "enabled": bool, "builtin": bool}}"""
        cfg = self._load_cfg()
        cats = {}
        for cid, name in self.DEFAULT_CATS:
            cats[cid] = {"name": name, "enabled": True, "builtin": True}
        stored = cfg.get("categories") or {}
        for cid, conf in stored.items():
            if isinstance(conf, dict):
                if cid in cats:
                    cats[cid]["enabled"] = conf.get("enabled", True)
                else:
                    cats[cid] = {"name": conf.get("name", cid),
                                 "enabled": conf.get("enabled", True),
                                 "builtin": False}
        return cats

    def _save_categories(self, cats):
        cfg = self._load_cfg()
        cfg["categories"] = cats
        return self._save_cfg(cfg)

    def _load_items(self):
        """分享链接条目列表"""
        cfg = self._load_cfg()
        return cfg.get("items") or []

    def _save_items(self, items):
        # 归一化：去重（同URL只留一条，合并分类）+ 清理无分类孤儿 + 精简字段
        seen = {}
        out = []
        for it in items:
            u = self._normalize_share_url(it.get("url", "") or "")
            if not u:
                continue
            cats = self._item_cats(it)
            if not cats:
                continue  # 无分类孤儿丢弃
            if u in seen:
                # 合并分类到已有条目
                old = seen[u]
                oc = self._item_cats(old)
                merged = list(oc)
                for c in cats:
                    if c not in merged:
                        merged.append(c)
                old["cats"] = merged
            else:
                # 精简字段：仅保留常用
                slim = {
                    "id": it.get("id", self._gen_id()),
                    "name": it.get("name", "")[:120],
                    "url": u,
                    "cats": cats,
                    "remark": it.get("remark", "")[:200],
                }
                seen[u] = slim
                out.append(slim)
        cfg = self._load_cfg()
        cfg["items"] = out
        return self._save_cfg(cfg)

    def _item_cats(self, it):
        """条目所属分类 id 列表（兼容旧 pan_type 字符串）"""
        c = it.get("cats")
        if isinstance(c, list):
            return [str(x) for x in c if x]
        pt = it.get("pan_type")
        if pt:
            return [str(pt)]
        return []

    # 兼容旧字段
    def _load_subs(self):
        return self._load_items()

    def _save_subs(self, subs):
        # 清理无分类孤儿条目（cats 为空）→ 不保存
        cleaned = [s for s in subs if self._item_cats(s)]
        return self._save_items(cleaned)

    # ── 订阅内容读取 ─────────────────────────────────────────

    def _read_subscription(self, sub):
        """返回 (items, error)"""
        try:
            if sub.get("source") == "local":
                path = sub.get("path", "")
                if path.startswith("file://"):
                    path = path[len("file://"):]
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    data = json.load(f)
            else:
                url = sub.get("url", "").strip()
                if not url:
                    return [], "订阅地址为空"
                # 网盘分享链接（非 JSON 订阅）→ 直接作为单条目返回
                is_pan, pan_name, pwd, _pt = self._detect_pan(url)
                if is_pan:
                    item = {
                        "vod_id": "pan_" + url[-16:],
                        "vod_name": sub.get("name") or pan_name,
                        "vod_pic": "",
                        "vod_year": "",
                        "vod_remarks": "%s%s" % (pan_name, (" 提取码 " + pwd) if pwd else ""),
                        "vod_play_from": pan_name,
                        "vod_play_url": "在线播放$" + self._normalize_share_url(url),
                        "vod_content": url,
                    }
                    return [item], ""
                rsp = self.fetch(url)
                if rsp.status_code != 200:
                    return [], "HTTP %s" % rsp.status_code
                try:
                    data = rsp.json()
                except Exception:
                    # 返回的不是 JSON：可能是个资源页，尝试提取其中链接
                    text = getattr(rsp, "text", "") or ""
                    links = re.findall(r'https?://[^\s"\'<>]+', text)
                    items = []
                    for lnk in links[:50]:
                        lp = self._detect_pan(lnk)
                        if lp[0]:
                            items.append({
                                "vod_id": "pan_" + lnk[-16:],
                                "vod_name": sub.get("name") or lp[1],
                                "vod_pic": "",
                                "vod_year": "",
                                "vod_remarks": lp[1],
                                "vod_play_from": lp[1],
                                "vod_play_url": "在线播放$" + self._normalize_share_url(lnk),
                                "vod_content": lnk,
                            })
                    if items:
                        return items, ""
                    return [], "响应非 JSON（可能是登录/验证页）"
            return self._normalize_items(data), ""
        except Exception as e:
            return [], str(e)[:120]

    @staticmethod
    def _normalize_items(data):
        """自适应识别订阅 JSON 结构，返回归一化列表"""
        if data is None:
            return []
        if isinstance(data, list):
            raw = data
        elif isinstance(data, dict):
            raw = None
            for key in ("items", "list", "videos", "data", "channels", "vod_list", "vodlist", "rows", "results", "media_list"):
                v = data.get(key)
                if isinstance(v, list):
                    raw = v
                    break
            if raw is None:
                for key in ("vod", "media", "item"):
                    v = data.get(key)
                    if isinstance(v, list):
                        raw = v
                        break
                if raw is None:
                    raw = [data]
        else:
            return []

        items = []
        for it in raw:
            if not isinstance(it, dict):
                continue
            vod = {}
            vod["vod_id"] = str(_first_match(it, KEY_MAP["vod_id"], ""))
            name = _first_match(it, KEY_MAP["vod_name"], "")
            if not name:
                continue
            vod["vod_name"] = name
            vod["vod_pic"] = _first_match(it, KEY_MAP["vod_pic"], "")
            vod["vod_year"] = ""
            yr = _first_match(it, KEY_MAP["vod_year"], "")
            if isinstance(yr, str):
                m = YEAR_RE.search(yr)
                if m:
                    vod["vod_year"] = m.group(1)
            elif yr:
                vod["vod_year"] = str(yr)
            if not vod["vod_id"]:
                vod["vod_id"] = "p_" + urllib.parse.quote(name, safe="")
            vod["vod_remarks"] = _first_match(it, KEY_MAP["vod_remarks"], "")
            vod["vod_play_from"] = _first_match(it, KEY_MAP["vod_play_from"], "播放")
            play_url = _first_match(it, KEY_MAP["vod_play_url"], "")
            if play_url:
                if "$" not in str(play_url) and "#" not in str(play_url):
                    play_url = "在线播放$" + str(play_url)
            else:
                play_url = "在线播放$dodo"
            vod["vod_play_url"] = play_url
            vod["vod_content"] = _first_match(it, KEY_MAP["vod_content"], "")
            if not vod["vod_remarks"] and not vod["vod_year"]:
                vod["vod_remarks"] = _first_match(it, ("quality", "resolution", "hd", "format"), "")
            items.append(vod)
        return items

    # ── 订阅聚合 ─────────────────────────────────────────────

    def _get_sub_items(self, sub_id, force=False):
        if not force and sub_id in self.cache:
            return self.cache[sub_id]
        subs = self._load_subs()
        sub = next((s for s in subs if s.get("id") == sub_id), None)
        if not sub or not sub.get("enabled", True):
            return []
        items, _err = self._read_subscription(sub)
        self.cache[sub_id] = items
        return items

    def _all_enabled_subs(self):
        return [s for s in self._load_subs() if s.get("enabled", True)]

    # ── 首页 ──────────────────────────────────────────────────

    # 固定分类顺序：设置 + 常用网盘 + 其他兜底
    FIXED_TYPES = [
        ("quark", "夸克"),
        ("baidu", "百度"),
        ("uc", "UC"),
        ("xunlei", "迅雷"),
        ("other", "其他"),
    ]

    def getName(self):
        return "网盘订阅管理"

    def homeContent(self, filter):
        classes = [{"type_id": self.SETTINGS_TID, "type_name": "⚙️ 设置"}]
        cats = self._load_categories()
        for cid, conf in cats.items():
            if not conf.get("enabled", True):
                continue
            classes.append({"type_id": cid, "type_name": conf.get("name", cid)})
        return {"class": classes, "filters": {}}

    def homeVideoContent(self):
        # 无推荐
        return {"list": []}

    def _item_to_vod(self, it):
        """条目 dict → vod dict"""
        url = self._normalize_share_url(it.get("url", "") or it.get("path", ""))
        is_pan, pan_name, pwd, ptype = self._detect_pan(url)
        if not is_pan:
            return None
        name = it.get("name") or pan_name or url[:40]
        remark = it.get("remark", "") or pan_name
        if pwd and "提取码" not in remark:
            remark += (" " + ("提取码 " + pwd))
        return {
            "vod_id": "pan_item_" + str(it.get("id", url[-16:])),
            "vod_name": name,
            "vod_pic": "",
            "vod_remarks": remark,
            "vod_year": "",
            "vod_play_from": pan_name,
            "vod_play_url": "在线播放$" + url,
            "vod_content": url,
        }

    # ── 分类列表（tid = 订阅 id） ────────────────────────────

    def categoryContent(self, tid, pg, filter, extend):
        try:
            if tid == self.SETTINGS_TID:
                # 点击「⚙️ 设置」分类 → 直接返回设置项列表（带 action 按钮）
                return {"list": self._settings_items(), "pagecount": 1}
            # tid = 分类 id（内置或自定义）
            items = self._load_items()
            vods = []
            for it in items:
                if tid in self._item_cats(it):
                    d = self._item_to_vod(it)
                    if d:
                        d["vod_tag"] = tid  # 标记所属分类
                        vods.append(d)
            # 顶部管理入口
            cats = self._load_categories()
            cat_name = cats.get(tid, {}).get("name", tid)
            mgr = {
                "vod_id": "mgr_" + tid,
                "vod_name": "⚙️ 管理「%s」（%d条）" % (cat_name, len(vods)),
                "vod_remarks": "改备注名 / 移出 / 复制链接",
                "vod_pic": "",
                "action": self.ACTION_MGR_PREFIX + tid,
                "style": {"type": "list"},
            }
            vods.insert(0, mgr)
            return {"list": vods, "pagecount": 1 if vods else 1}
        except Exception as e:
            return {"list": self._error_chunks(e), "pagecount": 1}

    # ── 详情（拦截设置页；其余按条目返回） ───────────────────

    def detailContent(self, ids):
        vid = ids[0]
        if vid == self.SETTINGS_TID:
            return {"list": self._settings_items()}
        # 查找条目
        if vid.startswith("pan_item_"):
            iid = vid[len("pan_item_"):]
            for it in self._load_items():
                if str(it.get("id")) == iid:
                    d = self._item_to_vod(it)
                    if d:
                        d["type_name"] = "网盘分享"
                        return {"list": [d]}
        # 兼容旧订阅条目（按名称搜索）
        for it in self._load_items():
            d = self._item_to_vod(it)
            if d and str(d.get("vod_id")) == str(vid):
                d["type_name"] = "网盘分享"
                return {"list": [d]}
        return {"list": [{"vod_id": vid, "vod_name": "未找到资源",
                          "vod_pic": "", "vod_content": "该条目不存在",
                          "vod_play_from": "播放", "vod_play_url": vid + "$dodo"}]}

    def _settings_items(self):
        items = []
        items.append({"vod_id": "paste", "vod_name": "☯粘贴链接识别",
                      "vod_remarks": "粘贴带链接/提取码的分享文本，自动识别并入库", "action": self.ACTION_PASTE})
        items.append({"vod_id": "add", "vod_name": "⊕手动添加",
                      "vod_remarks": "自己填标题 + 链接 + 选分类", "action": self.ACTION_ADD})
        items.append({"vod_id": "cat_add", "vod_name": "⊕新增自定义分类",
                      "vod_remarks": "创建自己的分类（如 电影/剧集/音乐）", "action": self.ACTION_CAT_ADD})
        items.append({"vod_id": "cat_del", "vod_name": "⊗删除自定义分类",
                      "vod_remarks": "删除分类（条目会自动移出）", "action": self.ACTION_CAT_DEL})
        items.append({"vod_id": "toggle", "vod_name": "☷分类开关",
                      "vod_remarks": "启用/隐藏分类", "action": self.ACTION_TOGGLE})
        items.append({"vod_id": "setpath", "vod_name": "↻📁更改存储位置",
                      "vod_remarks": "当前：" + self._get_cfg_path(), "action": self.ACTION_SET_PATH})
        items.append({"vod_id": "cookie", "vod_name": "✴网盘Cookie管理",
                      "vod_remarks": "新增/修改/复制/清除 各网盘 Cookie", "action": self.ACTION_COOKIE})
        items.append({"vod_id": "pushlog", "vod_name": "ⓘ推送日志",
                      "vod_remarks": "当前：" + ("开" if self._get_pushlog() else "关"),
                      "action": self.ACTION_PUSHLOG})
        items.append({"vod_id": "help", "vod_name": "⍰帮助",
                      "vod_remarks": "使用方法说明", "action": self.ACTION_HELP})
        return items
    # ── 搜索（遍历所有启用订阅） ─────────────────────────────

    def searchContent(self, key, quick, pg="1"):
        try:
            kw = key.strip().lower()
            result = []
            for it in self._load_items():
                name = str(it.get("name", "")).lower()
                if kw and kw in name:
                    d = self._item_to_vod(it)
                    if d:
                        result.append(d)
            return {"list": result, "pagecount": 999}
        except Exception as e:
            return {"list": self._error_chunks(e), "pagecount": 1}

    # ── 播放分流 ─────────────────────────────────────────────

    @staticmethod
    def _normalize_share_url(url):
        """清理分享链接：去首尾空白、去末尾 #、确保 http 前缀"""
        u = (url or "").strip()
        # 去掉复制时带的尾部 #
        while u.endswith("#") or u.endswith("#/"):
            u = u[:-1].rstrip()
        return u

    @staticmethod
    def _detect_pan(url):
        """识别网盘/分享链接类型，返回 (is_pan, type_name, pwd, pan_type)
        is_pan: 是否网盘类链接
        type_name: 网盘显示名
        pwd: 提取码（若链接带 ?pwd=xxx）
        pan_type: 网盘类型标记（quark/baidu/uc/xunlei/alipan/pan115/pan123/tianyi/lanzou/other）
        """
        u = Spider._normalize_share_url(url)
        try:
            parsed = urllib.parse.urlparse(u)
            host = (parsed.netloc or "").lower()
            query = parsed.query or ""
        except Exception:
            host, query = "", ""
        # 提取码
        pwd = ""
        if query:
            for part in query.split("&"):
                if part.startswith("pwd="):
                    pwd = part[4:].strip()
                    break
        low = host
        if "xunlei.com" in low or "pan.xunlei" in low:
            return True, "迅雷网盘", pwd, "xunlei"
        if "quark.cn" in low or "pan.quark" in low:
            return True, "夸克网盘", pwd, "quark"
        if "pan.baidu.com" in low or ("baidu.com" in low and "pan" in low):
            return True, "百度网盘", pwd, "baidu"
        if "ucx.com" in low or "drive.uc.cn" in low or ("uc.cn" in low and "quark" not in low):
            return True, "UC网盘", pwd, "uc"
        if "alipan.com" in low or "aliyundrive.com" in low or "aliyundrive.net" in low:
            return True, "阿里云盘", pwd, "alipan"
        if "115.com" in low or "anxia.com" in low:
            return True, "115网盘", pwd, "pan115"
        if "123pan.com" in low or "123684.com" in low or "123865.com" in low or "123912.com" in low:
            return True, "123云盘", pwd, "pan123"
        if "189.cn" in low or "cloud.189" in low:
            return True, "天翼云盘", pwd, "tianyi"
        if "lanzou" in low:
            return True, "蓝奏云", pwd, "lanzou"
        if "cowtransfer.com" in low or "weiyun.com" in low:
            return True, "微云/奶牛快传", pwd, "other"
        if any(h in low for h in PAN_HOSTS):
            return True, "网盘", pwd, "other"
        return False, "", pwd, ""

    def playerContent(self, flag, id, vipFlags):
        url = self._normalize_share_url(id)
        # 调试日志（受"推送日志"开关控制）
        try:
            if self._get_pushlog():
                log_dir = os.path.dirname(self._get_cfg_path())
                with open(os.path.join(log_dir, "push_log.txt"), "a", encoding="utf-8") as _lf:
                    _lf.write("id=%s | flag=%s | url=%s\n" % (str(id)[:80], str(flag)[:20], str(url)[:80]))
        except Exception:
            pass
        if not url or url == "dodo":
            return {"parse": 1, "url": url}
        # 直链
        if url.startswith("http") and self.isVideoFormat(url):
            return {"parse": 0, "url": url, "header": HEADERS}
        # 网盘分享链接：推送到本地推送服务，带延迟防抖确保推送正常弹出
        is_pan, pan_name, _pwd, _pt = self._detect_pan(url)
        if is_pan:
            # 推送到 9978，返回后壳会显示提示
            self._push_to_pan(url)
            return {"parse": 0, "url": url,
                    "header": {"User-Agent": UA, "Referer": url},
                    "extra": {"status": "ok", "msg": "推送「%s」" % pan_name}}
        # 磁力
        if url.startswith("magnet:"):
            return {"parse": 1, "url": url}
        # 其他 http(s)：尝试嗅探页面内直链
        if url.startswith("http"):
            try:
                rsp = self.fetch(url, timeout=5)
                html = rsp.text
                m = re.search(r'https?://[^"\']+\.(?:m3u8|mp4)[^"\']*', html, re.I)
                if m:
                    return {"parse": 0, "url": m.group(0), "header": HEADERS}
            except Exception:
                pass
            return {"parse": 1, "url": url}
        return {"parse": 1, "url": url}

    def _push_to_pan(self, url):
        """把网盘链接推送到本地推送服务。
        防抖：1秒内重复推送只执行第一次，避免快速切换时覆盖弹窗。
        每次推送前先关闭旧推送（清状态），再推送新链接，确保弹窗正常弹出。"""
        now = time.time()
        last = getattr(self, "_last_push_time", 0)
        if last and now - last < 1.0:
            return True  # 跳过，1秒内防抖生效
        self._last_push_time = now
        try:
            import requests as _req
            endpoints = [
                "http://127.0.0.1:9978/action",
                "http://localhost:9978/action",
            ]
            for ep in endpoints:
                try:
                    # 第一步：先关闭/清除旧推送（清空当前弹窗）
                    try:
                        _req.post(ep, data={"do": "push", "url": ""}, timeout=0.5)
                    except Exception:
                        pass
                    # 第二步：推送新链接
                    r = _req.post(ep, data={"do": "push", "url": url}, timeout=2)
                    if r.status_code == 200:
                        txt = (r.text or "").strip()
                        if txt and "fail" in txt.lower():
                            continue
                        return True
                except Exception:
                    continue
        except Exception:
            pass
        return False

    @staticmethod
    def _error_chunks(e):
        s = str(e)
        items = []
        for i in range(0, len(s), 40):
            chunk = s[i:i + 40]
            items.append({"vod_id": chunk[:20], "vod_name": chunk[:20],
                          "vod_remarks": chunk[20:40], "vod_pic": "",
                          "style": {"type": "list"}})
        return items

    # ── action 分派（弹窗异步，立即返回） ────────────────────

    def action(self, action):
        action = str(action)
        if action == self.ACTION_ADD:
            # 手动添加：名称+链接+分类多选
            self._open_add_dialog()
            return {"code": 0, "msg": ""}
        if action == self.ACTION_PASTE:
            self._dialog_input(
                title="📋 粘贴分享消息",
                hint="粘贴 分享文件：xxx 链接：https://...？pwd=xxx 的多条消息，自动识别",
                default="",
                on_save=self._on_paste_saved,
            )
            return {"code": 0, "msg": ""}
        if action == self.ACTION_TOGGLE:
            # 分类开关
            cats = self._load_categories()
            items_list = [(conf.get("name", cid), conf.get("enabled", True))
                          for cid, conf in sorted(cats.items())]
            self._dialog_switches(
                title="☷ 分类开关",
                items=items_list,
                on_save=self._on_toggle_saved,
            )
            return {"code": 0, "msg": ""}
        if action == self.ACTION_CAT_ADD:
            self._dialog_input(
                title="➕ 新增自定义分类",
                hint="输入分类名称，如：电影 / 剧集 / 音乐",
                default="",
                on_save=self._on_cat_add_saved,
            )
            return {"code": 0, "msg": ""}
        if action == self.ACTION_CAT_DEL:
            cats = self._load_categories()
            custom = [(cid, conf.get("name", cid)) for cid, conf in cats.items()
                      if not conf.get("builtin", False)]
            if not custom:
                _toast("没有自定义分类")
                return {"code": 0, "msg": ""}
            self._dialog_switches(
                title="🗑 删除自定义分类",
                items=[(name, False) for _cid, name in custom],
                on_save=self._on_cat_del_saved,
            )
            return {"code": 0, "msg": ""}
        if action == self.ACTION_HELP:
            self._dialog_confirm(title="ⓘ 使用说明", message=self._help_text(), on_confirm=None)
            return {"code": 0, "msg": ""}
        if action == self.ACTION_SET_PATH:
            self._dialog_input(
                title="📁 更改存储位置",
                hint="输入新的 数据文件 绝对路径（.json）",
                default=self._get_cfg_path(),
                on_save=self._on_set_path_saved,
            )
            return {"code": 0, "msg": ""}
        if action == self.ACTION_COOKIE:
            self._open_cookie_dialog()
            return {"code": 0, "msg": ""}
        if action == self.ACTION_PUSHLOG:
            self._dialog_switches(
                title="📝 推送日志开关",
                items=[("记录播放日志（push_log.txt）", self._get_pushlog())],
                on_save=self._on_pushlog_saved,
            )
            return {"code": 0, "msg": ""}
        if action.startswith(self.ACTION_EDIT_PREFIX):
            self._open_edit_dialog(action[len(self.ACTION_EDIT_PREFIX):])
            return {"code": 0, "msg": ""}
        if action.startswith(self.ACTION_DEL_PREFIX):
            self._open_del_confirm(action[len(self.ACTION_DEL_PREFIX):])
            return {"code": 0, "msg": ""}
        if action.startswith(self.ACTION_MGR_PREFIX):
            tid = action[len(self.ACTION_MGR_PREFIX):]
            self._open_mgr_dialog(tid)
            return {"code": 0, "msg": ""}
        if action.startswith(self.ACTION_MGR_RENAME):
            self._mgr_rename(action[len(self.ACTION_MGR_RENAME):])
            return {"code": 0, "msg": ""}
        if action.startswith(self.ACTION_MGR_OUT):
            self._mgr_out(action[len(self.ACTION_MGR_OUT):])
            return {"code": 0, "msg": ""}
        if action.startswith(self.ACTION_MGR_COPY):
            self._mgr_copy(action[len(self.ACTION_MGR_COPY):])
            return {"code": 0, "msg": ""}
        return {"code": 0, "msg": "未知操作"}

    def _help_text(self):
        return (
            "📦 网盘订阅管理（本地版）\n\n"
            "🏠 首页分类：\n"
            "  ⚙️设置 + 各网盘分类（夸克/百度/UC/迅雷/自定义）\n"
            "  分类后括号内为条数\n\n"
            "📥 添加链接：\n"
            "  · 📋粘贴分享消息自动识别\n"
            "    粘贴 分享文件/链接/提取码/夸克口令 等任意混合文本，\n"
            "    自动提取每条 名称+链接+提取码，可设置权限说明\n"
            "  · ➕手动添加（自填标题）\n"
            "    填 名称+链接；链接处也可直接粘贴整段分享消息自动提取\n\n"
            "🗂 分类管理：\n"
            "  每个分类顶部「⚙️管理本分类」→ 勾选条目 →\n"
            "  修改名称 / 移出本分类 / 复制链接（名字：链接 多行）\n"
            "  支持全选/滚动；移出最后一个分类自动删除该条目\n"
            "  已存在的链接再添加 = 给该链接补充分类（可属多分类）\n\n"
            "⚙️ 设置：\n"
            "  · 新增/删除自定义分类\n"
            "  · 分类开关（隐藏不用的分类）\n"
            "  · 📁更改存储位置（数据迁移到新路径）\n"
            "  · 🍪网盘Cookie管理（增改/复制/清除）\n\n"
            "📄 配置存储：\n" + self._get_cfg_path() + "\n"
            "  所有修改即时写回，重启不丢失。"
        )

    # ═══════════════════════════════════════════════════════════
    # D1-D4 原生弹窗
    # ═══════════════════════════════════════════════════════════

    def _dialog_input(self, title, hint="", default="", on_save=None):
        from java import dynamic_proxy, jclass

        edit_text_class = jclass("android.widget.EditText")
        input_type = jclass("android.text.InputType")
        click_listener = jclass("android.content.DialogInterface$OnClickListener")
        runnable_class = jclass("java.lang.Runnable")
        activity = _current_activity()

        class SaveListener(dynamic_proxy(click_listener)):
            def __init__(self, edit):
                super().__init__()
                self.edit = edit

            def onClick(self, dialog, which):
                value = str(self.edit.getText().toString())
                if on_save:
                    on_save(value)

        class CancelListener(dynamic_proxy(click_listener)):
            def onClick(self, dialog, which):
                return None

        class ShowDialog(dynamic_proxy(runnable_class)):
            def run(self):
                edit = edit_text_class(activity)
                edit.setSingleLine(True)
                edit.setInputType(input_type.TYPE_CLASS_TEXT | input_type.TYPE_TEXT_VARIATION_URI)
                if hint:
                    edit.setHint(hint)
                if default:
                    edit.setText(default)
                    edit.setSelection(len(default))
                builder = _builder_class()(activity)
                builder.setTitle(title)
                builder.setView(edit)
                builder.setPositiveButton("保存", SaveListener(edit))
                builder.setNegativeButton("取消", CancelListener())
                dialog = builder.show()
                edit.requestFocus()
                _keep(edit, dialog)

        runner = ShowDialog()
        _keep(runner)
        activity.runOnUiThread(runner)

    def _dialog_form(self, title, fields, description="", on_save=None, input_types=None):
        """fields = [(hint, default), ...]；input_types：可选 [int,...]
        支持滚动：字段多时包 ScrollView"""
        from java import dynamic_proxy, jclass

        edit_text_class = jclass("android.widget.EditText")
        linear_layout_class = jclass("android.widget.LinearLayout")
        text_view_class = jclass("android.widget.TextView")
        scroll_view_class = jclass("android.widget.ScrollView")
        frame_layout_class = jclass("android.widget.FrameLayout")
        input_type = jclass("android.text.InputType")
        click_listener = jclass("android.content.DialogInterface$OnClickListener")
        runnable_class = jclass("java.lang.Runnable")
        activity = _current_activity()

        class SaveListener(dynamic_proxy(click_listener)):
            def __init__(self, edits):
                super().__init__()
                self.edits = edits

            def onClick(self, dialog, which):
                values = [str(e.getText().toString()) for e in self.edits]
                if on_save:
                    on_save(values)

        class CancelListener(dynamic_proxy(click_listener)):
            def onClick(self, dialog, which):
                return None

        class ShowDialog(dynamic_proxy(runnable_class)):
            def run(self):
                density = float(activity.getResources().getDisplayMetrics().density)
                padding = int(16 * density + 0.5)
                row_padding = int(8 * density + 0.5)
                container = linear_layout_class(activity)
                container.setOrientation(linear_layout_class.VERTICAL)
                container.setPadding(padding, row_padding, padding, 0)
                if description:
                    desc = text_view_class(activity)
                    desc.setText(description)
                    desc.setTextSize(13.0)
                    desc.setPadding(0, 0, 0, row_padding)
                    container.addView(desc)
                edits = []
                for idx, (hint, default) in enumerate(fields):
                    edit = edit_text_class(activity)
                    edit.setSingleLine(True)
                    edit.setHint(hint)
                    default_type = input_type.TYPE_CLASS_TEXT
                    if input_types and idx < len(input_types):
                        itype = input_types[idx]
                        if itype == "url":
                            default_type = input_type.TYPE_CLASS_TEXT | input_type.TYPE_TEXT_VARIATION_URI
                        elif itype == "number":
                            default_type = input_type.TYPE_CLASS_NUMBER | input_type.TYPE_NUMBER_FLAG_DECIMAL
                    edit.setInputType(default_type)
                    if default:
                        edit.setText(default)
                    container.addView(edit)
                    edits.append(edit)
                # 包 ScrollView（带高度上限：最多约 45% 屏高，超出可滚动）
                sv = scroll_view_class(activity)
                max_h = (int(0.45 * activity.getResources().getDisplayMetrics().heightPixels)
                         if len(fields) > 4 else 0)
                if max_h:
                    sv.setLayoutParams(frame_layout_class.LayoutParams(
                        frame_layout_class.LayoutParams.MATCH_PARENT, max_h))
                sv.addView(container)
                builder = _builder_class()(activity)
                builder.setTitle(title)
                builder.setView(sv)
                builder.setPositiveButton("保存", SaveListener(edits))
                builder.setNegativeButton("取消", CancelListener())
                dialog = builder.show()
                if edits:
                    edits[0].requestFocus()
                _keep(container, sv, dialog)

        runner = ShowDialog()
        _keep(runner)
        activity.runOnUiThread(runner)

    def _dialog_switches(self, title, items, on_save=None):
        from java import dynamic_proxy, jclass

        linear_layout_class = jclass("android.widget.LinearLayout")
        switch_class = jclass("android.widget.Switch")
        scroll_view_class = jclass("android.widget.ScrollView")
        frame_layout_class = jclass("android.widget.FrameLayout")
        click_listener = jclass("android.content.DialogInterface$OnClickListener")
        view_click_listener = jclass("android.view.View$OnClickListener")
        runnable_class = jclass("java.lang.Runnable")
        activity = _current_activity()

        class NoopListener(dynamic_proxy(click_listener)):
            def onClick(self, dialog, which):
                return None

        class SaveButtonListener(dynamic_proxy(view_click_listener)):
            def __init__(self, controls, dialog):
                super().__init__()
                self.controls = controls
                self.dialog = dialog

            def onClick(self, view):
                results = {idx: bool(ctrl.isChecked()) for idx, ctrl in self.controls.items()}
                if on_save:
                    on_save(results)
                self.dialog.dismiss()

        class ShowDialog(dynamic_proxy(runnable_class)):
            def run(self):
                density = float(activity.getResources().getDisplayMetrics().density)
                row_padding = int(8 * density + 0.5)
                container = linear_layout_class(activity)
                container.setOrientation(linear_layout_class.VERTICAL)
                container.setPadding(int(16 * density + 0.5), row_padding, int(16 * density + 0.5), 0)
                controls = {}
                for idx, (label, checked) in enumerate(items):
                    ctrl = switch_class(activity)
                    ctrl.setText(label)
                    ctrl.setTextSize(16.0)
                    ctrl.setChecked(bool(checked))
                    ctrl.setPadding(0, row_padding, 0, row_padding)
                    ctrl.setFocusable(True)
                    container.addView(ctrl)
                    controls[idx] = ctrl
                # 包 ScrollView
                sv = scroll_view_class(activity)
                if len(items) > 6:
                    max_h = int(0.5 * activity.getResources().getDisplayMetrics().heightPixels)
                    sv.setLayoutParams(frame_layout_class.LayoutParams(
                        frame_layout_class.LayoutParams.MATCH_PARENT, max_h))
                sv.addView(container)
                builder = _builder_class()(activity)
                builder.setTitle(title)
                builder.setView(sv)
                builder.setPositiveButton("保存", NoopListener())
                builder.setNegativeButton("取消", NoopListener())
                dialog = builder.show()
                dialog.getButton(-1).setOnClickListener(SaveButtonListener(controls, dialog))
                _keep(container, sv, dialog)

        runner = ShowDialog()
        _keep(runner)
        activity.runOnUiThread(runner)

    def _dialog_multi_choice(self, title, options, on_save=None):
        """D8 复选框多选弹窗
        options = [(label, checked), ...] → on_save([True/False,...])（或{idx:bool}）
        支持滚动：选项多时包 ScrollView
        """
        from java import dynamic_proxy, jclass

        linear_layout_class = jclass("android.widget.LinearLayout")
        check_box_class = jclass("android.widget.CheckBox")
        scroll_view_class = jclass("android.widget.ScrollView")
        frame_layout_class = jclass("android.widget.FrameLayout")
        checked_change_class = jclass("android.widget.CompoundButton$OnCheckedChangeListener")
        click_listener = jclass("android.content.DialogInterface$OnClickListener")
        view_click_listener = jclass("android.view.View$OnClickListener")
        runnable_class = jclass("java.lang.Runnable")
        activity = _current_activity()

        class NoopListener(dynamic_proxy(click_listener)):
            def onClick(self, dialog, which):
                return None

        class SaveButtonListener(dynamic_proxy(view_click_listener)):
            def __init__(self, controls, dialog):
                super().__init__()
                self.controls = controls
                self.dialog = dialog

            def onClick(self, view):
                results = {idx: bool(ctrl.isChecked()) for idx, ctrl in self.controls.items()}
                if on_save:
                    on_save(results)
                self.dialog.dismiss()

        class ShowDialog(dynamic_proxy(runnable_class)):
            def run(self):
                density = float(activity.getResources().getDisplayMetrics().density)
                row_padding = int(10 * density + 0.5)
                container = linear_layout_class(activity)
                container.setOrientation(linear_layout_class.VERTICAL)
                container.setPadding(int(16 * density + 0.5), row_padding, int(16 * density + 0.5), 0)
                # 全选选框（勾选/反选所有）
                select_all_cb = None
                if len(options) > 1:
                    select_all_cb = check_box_class(activity)
                    select_all_cb.setText("全选 / 全不选")
                    select_all_cb.setTextSize(16.0)
                    select_all_cb.setPadding(0, row_padding, 0, row_padding)
                    container.addView(select_all_cb)
                controls = {}
                for idx, (label, checked) in enumerate(options):
                    cb = check_box_class(activity)
                    cb.setText(label)
                    cb.setTextSize(16.0)
                    cb.setChecked(bool(checked))
                    cb.setPadding(0, row_padding, 0, row_padding)
                    cb.setFocusable(True)
                    container.addView(cb)
                    controls[idx] = cb
                # 全选联动
                if select_all_cb is not None:
                    class SelectAllListener(dynamic_proxy(checked_change_class)):
                        def __init__(self, cbs, master):
                            super().__init__()
                            self.cbs = cbs
                            self.master = master

                        def onCheckedChanged(self, button, isChecked):
                            for cbx in self.cbs.values():
                                cbx.setChecked(bool(isChecked))
                    sl = SelectAllListener(controls, select_all_cb)
                    select_all_cb.setOnCheckedChangeListener(sl)
                    _keep(sl)
                # 包 ScrollView
                sv = scroll_view_class(activity)
                if len(options) > 8:
                    max_h = int(0.55 * activity.getResources().getDisplayMetrics().heightPixels)
                    sv.setLayoutParams(frame_layout_class.LayoutParams(
                        frame_layout_class.LayoutParams.MATCH_PARENT, max_h))
                sv.addView(container)
                builder = _builder_class()(activity)
                builder.setTitle(title)
                builder.setView(sv)
                builder.setPositiveButton("保存", NoopListener())
                builder.setNegativeButton("取消", NoopListener())
                dialog = builder.show()
                dialog.getButton(-1).setOnClickListener(SaveButtonListener(controls, dialog))
                _keep(container, sv, dialog)

        runner = ShowDialog()
        _keep(runner)
        activity.runOnUiThread(runner)

    def _dialog_confirm(self, title, message, on_confirm=None):
        from java import dynamic_proxy, jclass

        click_listener = jclass("android.content.DialogInterface$OnClickListener")
        runnable_class = jclass("java.lang.Runnable")
        activity = _current_activity()

        class ConfirmListener(dynamic_proxy(click_listener)):
            def onClick(self, dialog, which):
                if on_confirm:
                    on_confirm()

        class CancelListener(dynamic_proxy(click_listener)):
            def onClick(self, dialog, which):
                return None

        class ShowDialog(dynamic_proxy(runnable_class)):
            def run(self):
                builder = _builder_class()(activity)
                builder.setTitle(title)
                builder.setMessage(message)
                builder.setPositiveButton("确定", ConfirmListener())
                builder.setNegativeButton("取消", CancelListener())
                dialog = builder.show()
                _keep(dialog)

        runner = ShowDialog()
        _keep(runner)
        activity.runOnUiThread(runner)

    # ═══════════════════════════════════════════════════════════
    # 业务回调（增 / 删 / 改 / 启停 / 测试）
    # ═══════════════════════════════════════════════════════════

    def _gen_id(self):
        import random
        return "sub_%d_%d" % (int(time.time() * 1000), random.randint(1000, 9999))

    def _open_add_dialog(self):
        """手动添加：表单(名称+链接+备注) → 分类多选 → 保存"""
        self._dialog_form(
            title="➕ 手动添加分享",
            fields=[("名称", ""), ("链接（网盘分享URL）", ""), ("备注（可选）", "")],
            on_save=self._on_add_form_saved,
        )

    def _on_add_form_saved(self, values):
        name = (values[0] if len(values) > 0 else "").strip()
        addr = (values[1] if len(values) > 1 else "").strip()
        remark = (values[2] if len(values) > 2 else "").strip()
        if not addr:
            _toast("链接不能为空")
            return
        # 自动提取：链接字段若含整段分享文本（非纯URL），解析出真实链接/名称
        is_pan, pan_name, pwd, ptype = self._detect_pan(self._normalize_share_url(addr))
        if not is_pan:
            # 可能粘贴了整段分享消息 → 尝试解析
            _, parsed = self._parse_share_text(addr)
            if len(parsed) == 1:
                p = parsed[0]
                name = name or p["name"]
                addr = p["url"]
                remark = remark or (("提取码 " + p["pwd"]) if p["pwd"] else p["pan_name"])
                is_pan, pan_name, pwd, ptype = self._detect_pan(self._normalize_share_url(addr))
            elif len(parsed) > 1:
                _toast("识别到 %d 条链接，请用「📋粘贴分享消息自动识别」批量添加" % len(parsed))
                return
            else:
                _toast("未识别到有效网盘链接")
                return
        if not name:
            _toast("名称不能为空（可粘贴带标题的分享消息自动识别）")
            return
        # 第二步：分类多选
        cats = self._load_categories()
        # 默认勾选自动识别的网盘分类
        options = []
        for cid, conf in cats.items():
            checked = (cid == ptype) if ptype else False
            options.append((conf.get("name", cid), checked))
        self._dialog_multi_choice(
            title="选择归属分类（可多选）",
            options=options,
            on_save=lambda res: self._on_add_cats_saved(name, addr, remark, res, cats),
        )

    def _on_add_cats_saved(self, name, addr, remark, results, cats):
        cats_ids = list(cats.keys())
        selected = [cats_ids[i] for i, v in results.items() if v]
        subs = self._load_subs()
        is_pan, pan_name, pwd, ptype = self._detect_pan(self._normalize_share_url(addr))
        url = self._normalize_share_url(addr)
        new_item = {
            "id": self._gen_id(),
            "name": name,
            "url": url,
            "cats": list(selected),
            "remark": remark or (("提取码 " + pwd) if pwd else pan_name),
        }
        # 已存在：合并分类（追加选中且原分类没有的）
        old = next((s for s in subs if self._normalize_share_url(s.get("url", "")) == url), None)
        if old:
            old_cats = self._item_cats(old)
            need = [c for c in selected if c not in old_cats]
            if need:
                old["cats"] = old_cats + need
                self.cache.clear()
                if self._save_subs(subs):
                    _toast("✅ 已在原条目上补充分类：%s" % name)
                else:
                    _toast("❌ 保存失败")
            else:
                _toast("该链接已存在且分类相同，未变更")
            return
        subs.append(new_item)
        if self._save_subs(subs):
            self.cache.pop(new_item["id"], None)
            _toast("✅ 已添加：" + name)
        else:
            _toast("❌ 保存失败")

    def _attach_pwd(self, url, pwd):
        """把提取码拼到链接（百度：?pwd=xxx，夸克：?pwd=xxx，迅雷？pwd=xxx）
        若链接已带 pwd 则不重复拼接。
        """
        url = self._normalize_share_url(url)
        pwd = (pwd or "").strip()
        if not pwd:
            return url
        if "pwd=" in url:
            return url
        url = url.rstrip("?&")
        sep = "&" if "?" in url else "?"
        return url + sep + "pwd=" + pwd

    @staticmethod
    def _extract_pwd(text, default=""):
        """从文本提取 提取码/密码，支持：提取码:xxx、提取码：xxx、密码xxx、?pwd=xxx"""
        m = re.search(r'(?:提取码|提取密码|密码|pwd)\s*[：:=\s]\s*([0-9a-zA-Z]{1,12})', text, re.I)
        if m:
            return m.group(1).strip()
        m = re.search(r'pwd=([0-9a-zA-Z]{1,12})', text, re.I)
        if m:
            return m.group(1).strip()
        return default

    def _extract_name(self, ctx, url, pan_name):
        """从 URL 前的段文本中提取名称（各分享格式）"""
        try:
            # 1. 分享文件：xxx
            m = re.search(r'分享文件\s*[：:]\s*([^\n「」]{1,80}?)(?=\s*链接|\s*$)', ctx, re.S)
            if m:
                return m.group(1).strip()
            # 2. 通过xx分享的文件：xxx（含【超级会员】）
            m = re.search(r'(?:分享的文件|分享文件)\s*[：:]\s*([^\n：]{1,80}?)(?=\s*链接|\s*(?:复制这段|打开「))', ctx, re.S)
            if m:
                return m.group(1).strip()
            # 3. 夸克口令「xxx」
            m = re.search(r'「([^」]{1,60})」', ctx)
            if m:
                return m.group(1).strip()
            # 4. 网盘词：前的标题（支持 百度：:https 双冒号）
            for m in re.finditer(r'([^\n：]{1,60}?)\s*(?:百度|夸克|迅雷|阿里|UC|uc|115|123|天翼|蓝奏)\s*[：:]{1,2}\s*(?:https?://)?$', ctx, re.S):
                t4 = m.group(1).strip()
                if t4 and len(t4) < 60 and '分享文件' not in t4 and '链接' not in t4:
                    return t4
            # 5. 口令尾 ~xxx~:/ 前的文本（牧神记更新至97集/~395a3aNqQk~:/）
            m = re.search(r'([^\n/~]{1,60}?)\s*/~[^/]*~?:?\s*(?:链接)?\s*$', ctx)
            if m:
                t5 = m.group(1).strip()
                if t5 and t5 not in (':', '/') and '提取码' not in t5 and len(t5) < 60:
                    return t5
            # 5b. 口令尾直接跟在文本后（无空白）：xxx/~395a3aNqQk~:/ 链接 ：
            m = re.search(r'([^\n/~]{1,60}?)/~[^/]*~?:?\s*(?:链接)?\s*[：:：]?\s*$', ctx)
            if m:
                t5b = m.group(1).strip()
                if t5b and t5b not in (':', '/') and '提取码' not in t5b and len(t5b) < 60:
                    return t5b
            # 6. 段内倒序取第一个可用行
            lines = [l.strip() for l in ctx.splitlines() if l.strip()]
            for t in reversed(lines):
                t2 = re.sub(r'^【[^】]*】\s*', '', t)
                t2 = re.sub(r'\s*复制这段内容.*$', '', t2)
                t2 = re.sub(r'\s*链接\s*[：:]?\s*$', '', t2)
                t2 = re.sub(r'/~[^/]*~?:?\s*$', '', t2)
                t2 = re.sub(r'\s*提取码\s*[：:]?\s*[0-9a-zA-Z]*\s*$', '', t2)
                t2 = re.sub(r'^(?:分享文件|分享的文件|提取码)\s*[：:]\s*', '', t2)
                t2 = t2.strip()
                if t2 and not t2.startswith('http') and len(t2) < 80 and '分享文件' not in t2 and '链接' not in t2 and '提取码' not in t2:
                    return t2
            # 7. 整段清理
            t = re.sub(r'^【[^】]*】\s*', '', ctx.strip())
            t = re.sub(r'\s*复制这段内容.*$', '', t)
            t = t.strip()
            if t and not t.startswith('http') and len(t) < 80 and '提取码' not in t and '链接' not in t:
                return t
        except Exception:
            pass
        return pan_name

    def _pick_name(self, ctx, url, pan_name):
        """取安全名称：过滤残渣"""
        n = self._extract_name(ctx, url, pan_name)
        if not n:
            return pan_name
        n2 = n.strip()
        # 清理口令残留 /~xxx~/、/~xxx~:/ 中段，只保留前部标题
        n2 = re.sub(r'/“[^”]*~[:：/]?', '', n2)
        m_kou = re.search(r'([^\n/~]{1,60}?)/~[^/\n]*~[:：/]?', n2)
        if m_kou:
            n2 = m_kou.group(1).strip()
        n2 = re.sub(r'/~[^/]*~?:?$', '', n2).strip()
        # 括号空格规整
        n2 = re.sub(r'[（(]\s*([^）)]*?)\s*[）)]', r'（\1）', n2)
        n2 = re.sub(r'\s{2,}', ' ', n2)
        if n2 in (':', '/', '-', '--', '：') or '提取码' in n2 or '百度' in n2 or '夸克' in n2 or '迅雷' in n2:
            return pan_name
        if n2.startswith('http') or len(n2) > 80:
            return pan_name
        return n2

    def _parse_share_text(self, text):
        """解析分享文本，按每条链接独立取名（段内取名称/提取码，不跨界）"""
        text = (text or '').strip()
        if not text:
            return '', []
        url_re = re.compile(
            r'https?://[^\s，,；;）)】\]"\'<>]*(?=[\s，,；;）)】\]"\'<>]|$|[-—–]{2,}|(?:百度|夸克|迅雷|阿里|UC|uc|115|123|天翼|蓝奏)\s*[：:]|提取码|密码)')
        matches = list(url_re.finditer(text))
        entries = []
        for i, m in enumerate(matches):
            raw = m.group(0).strip().rstrip('#')
            # 二次切割残留 --/网盘词/提取码
            raw = re.split(r'[-—–]{2,}|(?:百度|夸克|迅雷|阿里|UC|uc|115|123|天翼|蓝奏)\s*[：:]|提取码|密码', raw)[0].strip()
            url = self._normalize_share_url(raw)
            is_pan, pan_name, pwd0, ptype = self._detect_pan(url)
            if not is_pan:
                continue
            seg_start = matches[i - 1].end() if i > 0 else 0
            seg_text = text[seg_start:m.start()]
            seg_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            after_text = text[m.end():seg_end]
            pwd = self._extract_pwd(after_text, pwd0)
            url = self._attach_pwd(url, pwd)
            name = self._pick_name(seg_text, url, pan_name)
            entries.append({
                'name': name, 'url': url, 'pwd': pwd,
                'ptype': ptype, 'pan_name': pan_name,
            })
        seen = set()
        uniq = []
        for e in entries:
            if e['url'] in seen:
                continue
            seen.add(e['url'])
            uniq.append(e)
        return (uniq[0]['name'] if uniq else ''), uniq

    def _on_paste_saved(self, text):
        """解析粘贴的分享消息，支持多条；解析后先让人确认/修改名称，再弹分类多选。
        已存在链接也进入流程：选分类后合并（给该链接补充分类）。"""
        title, parsed = self._parse_share_text(text)
        if not parsed:
            _toast("未识别到网盘链接")
            return
        if len(parsed) == 1:
            # 单条：单行确认名称
            default_name = parsed[0]["name"] or title
            self._dialog_input(
                title="确认名称（可修改）",
                hint="识别出的名称，可修改后保存",
                default=default_name,
                on_save=lambda name: self._ask_paste_cats([name], parsed),
            )
        else:
            # 多条：一个表单，每条一个输入框（预填各自识别名，可分别改名，也可直接保存）
            fields = []
            for p in parsed:
                hint = p.get("pan_name") or (p.get("url", "")[:30])
                default_n = p.get("name") or title or ""
                fields.append((hint, default_n))
            self._dialog_form(
                title="确认各条名称（共 %d 条，可分别修改）" % len(parsed),
                fields=fields,
                on_save=lambda names: self._ask_paste_cats(names, parsed),
            )

    def _ask_paste_cats(self, names, new_parsed):
        """弹分类多选，保存；names 为各条目名称列表"""
        cats = self._load_categories()
        default_ids = set(p["ptype"] for p in new_parsed if p["ptype"])
        options = []
        for cid, conf in cats.items():
            options.append((conf.get("name", cid), cid in default_ids))
        self._dialog_multi_choice(
            title="选择归属分类（可多选，共 %d 条）" % len(new_parsed),
            options=options,
            on_save=lambda res: self._on_paste_cats_saved(names, new_parsed, res),
        )

    def _on_paste_cats_saved(self, names, parsed, results):
        cats = self._load_categories()
        cats_ids = list(cats.keys())
        selected = [cats_ids[i] for i, v in results.items() if v]
        subs = self._load_subs()
        # 已存在 URL 集合
        url_to_sub = {}
        for s in subs:
            u = self._normalize_share_url(s.get("url", ""))
            if u:
                url_to_sub[u] = s
        multi = len(parsed) > 1
        added = 0
        merged = 0
        for idx, p in enumerate(parsed):
            u = self._normalize_share_url(p["url"])
            # 该条名称：表单里对应输入框的值
            item_name = ""
            if isinstance(names, list) and idx < len(names):
                item_name = (names[idx] or "").strip()
            if not item_name:
                item_name = p.get("name") or ""
            if not item_name:
                item_name = (names[0] if isinstance(names, list) and names else p.get("name") or "")
            if multi and item_name:
                pn = p.get("pan_name") or ""
                if pn and pn not in item_name:
                    item_name = "%s（%s）" % (item_name, pn)
            if u in url_to_sub:
                old = url_to_sub[u]
                old_cats = self._item_cats(old)
                need = [c for c in selected if c not in old_cats]
                if need:
                    old["cats"] = old_cats + need
                    # 若是多表单且该条有名称，则同步更新原条目名称
                    if item_name:
                        old["name"] = item_name
                    merged += 1
                continue
            new_item = {
                "id": self._gen_id(),
                "name": item_name or "网盘分享",
                "url": u,
                "cats": list(selected),
                "remark": (("提取码 " + p["pwd"]) if p["pwd"] else p["pan_name"]),
            }
            subs.append(new_item)
            url_to_sub[u] = new_item
            added += 1
        if merged:
            self._save_subs(subs)
        if added == 0 and merged == 0:
            _toast("无新增（链接已存在且分类无变化）")
            return
        msg = []
        if added:
            msg.append("新增 %d 条" % added)
        if merged:
            msg.append("补充分类 %d 条" % merged)
        if self._save_subs(subs) if added else True:
            self.cache.clear()
            _toast("✅ " + "，".join(msg))
        else:
            _toast("❌ 保存失败")

    def _on_toggle_saved(self, results):
        cats = self._load_categories()
        sorted_ids = sorted(cats.keys())
        for idx, val in results.items():
            if idx < len(sorted_ids):
                cid = sorted_ids[idx]
                cats[cid]["enabled"] = bool(val)
        if self._save_categories(cats):
            self.cache.clear()
            _toast("✅ 分类开关已更新")
        else:
            _toast("❌ 保存失败")

    def _on_cat_add_saved(self, name):
        name = (name or "").strip()
        if not name:
            _toast("分类名称不能为空")
            return
        cats = self._load_categories()
        cid = "cat_" + str(int(time.time() * 1000))
        cats[cid] = {"name": name, "enabled": True, "builtin": False}
        if self._save_categories(cats):
            _toast("✅ 已新增分类：" + name)
        else:
            _toast("❌ 保存失败")

    def _on_set_path_saved(self, path):
        """更改持久化存储位置：写入元配置，并把现有数据迁移过去"""
        path = (path or "").strip().replace("file://", "", 1)
        # 兼容用户输入 .json 或 .json.gz
        if not path.endswith(".json") and not path.endswith(".json.gz"):
            _toast("请输入有效的 .json 或 .json.gz 绝对路径")
            return
        if not path.startswith("/"):
            _toast("请输入有效的绝对路径")
            return
        # 统一转为纯 .json 路径（_get_cfg_path 会自动加 .gz）
        if path.endswith(".gz"):
            path = path[:-3]
        try:
            d = os.path.dirname(path)
            if d and not os.path.isdir(d):
                os.makedirs(d, exist_ok=True)
        except Exception as e:
            _toast("创建目录失败：" + str(e)[:50])
            return
        old_path = self._get_cfg_path()
        # 迁移：若新文件不存在且旧有数据，复制过去
        new_path = path + ".gz"  # 实际压缩文件路径
        try:
            if not os.path.exists(new_path) and os.path.exists(old_path):
                import shutil
                shutil.copy2(old_path, new_path)
        except Exception:
            pass
        # 写入元配置（存纯 .json 路径）
        meta = self._load_meta()
        meta["cfg_path"] = path
        if self._save_meta(meta):
            self.cache.clear()
            _toast("✅ 已更改存储位置：" + path + ".gz")
        else:
            _toast("❌ 保存配置失败")

    # ── 网盘 Cookie 管理 ──────────────────────────────────────

    COOKIE_PANS = [
        ("quark", "夸克"),
        ("baidu", "百度"),
        ("uc", "UC"),
        ("xunlei", "迅雷"),
        ("alipan", "阿里"),
        ("other", "其他"),
    ]

    def _load_cookies(self):
        cfg = self._load_cfg()
        return cfg.get("cookies") or {}

    def _save_cookies(self, cookies):
        cfg = self._load_cfg()
        cfg["cookies"] = cookies
        return self._save_cfg(cfg)

    def _open_cookie_dialog(self):
        """Cookie 管理：选网盘 → 操作"""
        cookies = self._load_cookies()
        options = []
        for cid, cname in self.COOKIE_PANS:
            has = bool(cookies.get(cid))
            label = "%s%s" % (cname, "（已设）" if has else "（未设）")
            options.append((label, False))
        self._dialog_multi_choice(
            title="🍪 选择要管理的网盘 Cookie",
            options=options,
            on_save=lambda res: self._cookie_pick_pan(res),
        )

    def _cookie_pick_pan(self, results):
        selected = [i for i, v in results.items() if v]
        if len(selected) != 1:
            _toast("请选择一个网盘")
            return
        cid, cname = self.COOKIE_PANS[selected[0]]
        cookies = self._load_cookies()
        cur = cookies.get(cid, "")
        # 操作：修改/复制/清除（默认全不勾选，避免误操作）
        items_opts = [("✏️ 修改/设置 Cookie", False),
                      ("📋 复制当前 Cookie", False),
                      ("🗑 清除该网盘 Cookie", False)]
        self._dialog_switches(
            title="🍪 「%s」Cookie" % cname,
            items=items_opts,
            on_save=lambda r: self._cookie_do_pan(cid, cur, r),
        )

    def _cookie_do_pan(self, cid, cur, results):
        do_edit = results.get(0, False)
        do_copy = results.get(1, False)
        do_clear = results.get(2, False)
        if do_edit:
            self._dialog_form(
                title="🍪 Cookie（" + self._cookie_name(cid) + "）",
                fields=[("Cookie 内容", cur)],
                description="从网盘网页登录态获取，粘贴完整 Cookie；留空保存可清除",
                on_save=lambda v: self._cookie_save(cid, v[0] if v else ""),
            )
            return
        if do_copy:
            if not cur:
                _toast("该网盘未设置 Cookie")
                return
            self._copy_text(cur)
            _toast("已复制「%s」Cookie" % self._cookie_name(cid))
            return
        if do_clear:
            cookies = self._load_cookies()
            if cid in cookies:
                del cookies[cid]
                self._save_cookies(cookies)
            self.cache.clear()
            _toast("已清除「%s」Cookie" % self._cookie_name(cid))
            return
        _toast("未选择操作")

    def _cookie_name(self, cid):
        for c, n in self.COOKIE_PANS:
            if c == cid:
                return n
        return cid

    def _cookie_save(self, cid, value):
        value = (value or "").strip()
        cookies = self._load_cookies()
        if value:
            cookies[cid] = value
        elif cid in cookies:
            del cookies[cid]
        if self._save_cookies(cookies):
            self.cache.clear()
            if value:
                _toast("✅ 已保存「%s」Cookie" % self._cookie_name(cid))
            else:
                _toast("已清除「%s」Cookie" % self._cookie_name(cid))
        else:
            _toast("❌ 保存失败")

    # ── 推送日志开关 ──────────────────────────────────────────

    def _get_pushlog(self):
        """推送日志开关（默认开）"""
        cfg = self._load_cfg()
        opt = cfg.get("opt") or {}
        return opt.get("pushlog", True)

    def _on_pushlog_saved(self, results):
        enabled = bool(results.get(0, True))
        cfg = self._load_cfg()
        opt = cfg.get("opt") or {}
        opt["pushlog"] = enabled
        cfg["opt"] = opt
        if self._save_cfg(cfg):
            _toast("✅ 推送日志已" + ("开启" if enabled else "关闭"))
        else:
            _toast("❌ 保存失败")

    def _on_cat_del_saved(self, results):
        """删除选中的自定义分类（同时从条目中移除）"""
        cats = self._load_categories()
        custom_ids = [cid for cid, conf in cats.items() if not conf.get("builtin", False)]
        to_del = set()
        for idx, val in results.items():
            if val and idx < len(custom_ids):
                to_del.add(custom_ids[idx])
        if not to_del:
            _toast("未选择要删除的分类")
            return
        # 删除分类定义
        cats = {cid: conf for cid, conf in cats.items() if cid not in to_del}
        self._save_categories(cats)
        # 从条目中移除该分类
        items = self._load_items()
        changed = False
        for it in items:
            ic = self._item_cats(it)
            if any(c in to_del for c in ic):
                it["cats"] = [c for c in ic if c not in to_del]
                changed = True
        if changed:
            self._save_items(items)
        self.cache.clear()
        _toast("🗑 已删除 %d 个分类" % len(to_del))

    def _open_mgr_dialog(self, tid):
        """管理分类弹窗：勾选本分类条目 → 选操作"""
        cats = self._load_categories()
        cat_name = cats.get(tid, {}).get("name", tid)
        items = self._load_items()
        in_cat = [it for it in items if tid in self._item_cats(it)]
        if not in_cat:
            _toast("该分类下暂无条目")
            return
        options = [(it.get("name", "未命名"), False) for it in in_cat]
        self._dialog_multi_choice(
            title="选择要管理的条目（可多选）",
            options=options,
            on_save=lambda res: self._mgr_pick_action(tid, in_cat, res),
        )

    def _mgr_pick_action(self, tid, in_cat, results):
        selected = [in_cat[i] for i, v in results.items() if v]
        if not selected:
            _toast("未选择条目")
            return
        # 操作多选：改备注 / 移出 / 复制
        self._dialog_switches(
            title="选择操作（%d 条）" % len(selected),
            items=[("✏️ 修改备注名", False),
                   ("↩️ 移出本分类", False),
                   ("📋 复制链接", False)],
            on_save=lambda r: self._mgr_do_action(tid, selected, r),
        )

    def _mgr_do_action(self, tid, arr, results):
        do_rename = results.get(0, False)
        do_out = results.get(1, False)
        do_copy = results.get(2, False)
        if do_copy:
            # 批量复制：拼接成「名字：链接\n名字：链接」一次复制
            lines = []
            for it in arr:
                name = it.get("name", "").strip()
                url = it.get("url", "").strip()
                if url:
                    if name:
                        lines.append("%s：%s" % (name, url))
                    else:
                        lines.append(url)
            if lines:
                self._copy_text("\n".join(lines))
            _toast("已复制 %d 条到剪贴板" % len(arr))
            return
        if do_out:
            # 仅从当前分类（tid）移除，保留其他分类归属
            items = self._load_items()
            changed = False
            for it in items:
                for sel in arr:
                    if it.get("id") == sel.get("id"):
                        ic = self._item_cats(it)
                        it["cats"] = [c for c in ic if c != tid]
                        changed = True
                        break
            if changed:
                self._save_items(items)
                self.cache.clear()
                _toast("已将 %d 条移出本分类" % len(arr))
            return
        if do_rename:
            if len(arr) > 1:
                _toast("改备注名请一次选 1 条")
                return
            self._dialog_input(
                title="修改备注名",
                hint="输入新的名称",
                default=arr[0].get("name", ""),
                on_save=lambda v: self._mgr_rename_save(arr[0], v),
            )
            return
        _toast("未选择操作")

    def _mgr_rename_save(self, it, new_name):
        new_name = (new_name or "").strip()
        if not new_name:
            _toast("名称不能为空")
            return
        items = self._load_items()
        for x in items:
            if x.get("id") == it.get("id"):
                x["name"] = new_name
                break
        if self._save_items(items):
            self.cache.clear()
            _toast("✅ 已修改名称")
        else:
            _toast("❌ 保存失败")

    def _mgr_out(self, item_id):
        items = self._load_items()
        for x in items:
            if x.get("id") == item_id:
                x["cats"] = []
                break
        if self._save_items(items):
            self.cache.clear()
            _toast("已移出所有分类")
        else:
            _toast("❌ 保存失败")

    def _mgr_copy(self, item_id):
        it = next((x for x in self._load_items() if x.get("id") == item_id), None)
        if not it:
            _toast("条目不存在")
            return
        self._copy_text(it.get("url", ""))
        _toast("已复制链接")

    @staticmethod
    def _copy_text(text):
        try:
            from java import jclass
            activity = _current_activity()
            cm = activity.getSystemService("clipboard")
            cd = jclass("android.content.ClipData")
            clip = cd.newPlainText("share", str(text))
            cm.setPrimaryClip(clip)
        except Exception:
            pass

    def _open_edit_dialog(self, sub_id):
        subs = self._load_subs()
        sub = next((s for s in subs if s.get("id") == sub_id), None)
        if not sub:
            _toast("条目不存在")
            return
        addr = sub.get("url", "") or sub.get("path", "")
        self._dialog_form(
            title="✏️ 编辑条目",
            fields=[("名称", sub.get("name", "")),
                    ("链接/路径", addr),
                    ("备注（可选）", sub.get("remark", ""))],
            on_save=lambda values: self._on_edit_form_saved(sub_id, values),
        )

    def _on_edit_form_saved(self, sub_id, values):
        name = (values[0] if len(values) > 0 else "").strip()
        addr = (values[1] if len(values) > 1 else "").strip()
        remark = (values[2] if len(values) > 2 else "").strip()
        if not name or not addr:
            _toast("名称和地址不能为空")
            return
        # 分类多选（当前已选为默认勾选）
        cats = self._load_categories()
        subs = self._load_subs()
        sub = next((s for s in subs if s.get("id") == sub_id), None)
        cur_cats = set(self._item_cats(sub)) if sub else set()
        options = []
        for cid, conf in cats.items():
            options.append((conf.get("name", cid), cid in cur_cats))
        self._dialog_multi_choice(
            title="选择归属分类（可多选）",
            options=options,
            on_save=lambda res: self._on_edit_cats_saved(sub_id, name, addr, remark, res),
        )

    def _on_edit_cats_saved(self, sub_id, name, addr, remark, results):
        cats = self._load_categories()
        cats_ids = list(cats.keys())
        selected = [cats_ids[i] for i, v in results.items() if v]
        subs = self._load_subs()
        for s in subs:
            if s.get("id") == sub_id:
                s["name"] = name
                s["remark"] = remark
                s["cats"] = list(selected)
                if addr.startswith("http://") or addr.startswith("https://"):
                    s["url"] = self._normalize_share_url(addr)
                    s.pop("path", None)
                else:
                    s["path"] = addr
                    s.pop("url", None)
                break
        if self._save_subs(subs):
            self.cache.pop(sub_id, None)
            _toast("✅ 已更新")
        else:
            _toast("❌ 保存失败")

    def _open_del_confirm(self, sub_id):
        subs = self._load_subs()
        sub = next((s for s in subs if s.get("id") == sub_id), None)
        if not sub:
            _toast("订阅不存在")
            return
        self._dialog_confirm(
            title="🗑 删除确认",
            message="确定删除订阅「%s」吗？" % sub.get("name", "未命名"),
            on_confirm=lambda: self._on_del_confirmed(sub_id),
        )

    def _on_del_confirmed(self, sub_id):
        subs = self._load_subs()
        subs = [s for s in subs if s.get("id") != sub_id]
        if self._save_subs(subs):
            self.cache.pop(sub_id, None)
            _toast("🗑 已删除订阅")
        else:
            _toast("❌ 保存失败")

    def _do_test(self):
        subs = self._load_subs()
        if not subs:
            _toast("暂无订阅")
            return
        threading.Thread(target=self._test_worker, args=(subs,), daemon=True).start()

    def _test_worker(self, subs):
        lines = []
        for s in subs:
            name = s.get("name", "未命名")
            if not s.get("enabled", True):
                lines.append("⏸ %s（停用，跳过）" % name)
                continue
            items, err = self._read_subscription(s)
            if err:
                lines.append("❌ %s：%s" % (name, err))
            else:
                lines.append("✅ %s：%d 条" % (name, len(items)))
        _toast_ui("\n".join(lines) if lines else "（无订阅）")

    def destroy(self):
        pass


spider = Spider()