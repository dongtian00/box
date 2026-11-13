# -*- coding: utf-8 -*-
# zlys9.py — 真狼影视 (zlys9.top) TVBox 爬虫
# Next.js SSR + RSC 解析 / AES-GCM 加密搜索 API / 外站播放链接
import json
import re
import base64
import struct

import requests

try:
    from base.spider import Spider as BaseSpider
except ImportError:
    class BaseSpider:
        pass


# ---- Pure-Python AES-128-GCM (no external deps) ----

_SBOX = [
    0x63,0x7c,0x77,0x7b,0xf2,0x6b,0x6f,0xc5,0x30,0x01,0x67,0x2b,0xfe,0xd7,0xab,0x76,
    0xca,0x82,0xc9,0x7d,0xfa,0x59,0x47,0xf0,0xad,0xd4,0xa2,0xaf,0x9c,0xa4,0x72,0xc0,
    0xb7,0xfd,0x93,0x26,0x36,0x3f,0xf7,0xcc,0x34,0xa5,0xe5,0xf1,0x71,0xd8,0x31,0x15,
    0x04,0xc7,0x23,0xc3,0x18,0x96,0x05,0x9a,0x07,0x12,0x80,0xe2,0xeb,0x27,0xb2,0x75,
    0x09,0x83,0x2c,0x1a,0x1b,0x6e,0x5a,0xa0,0x52,0x3b,0xd6,0xb3,0x29,0xe3,0x2f,0x84,
    0x53,0xd1,0x00,0xed,0x20,0xfc,0xb1,0x5b,0x6a,0xcb,0xbe,0x39,0x4a,0x4c,0x58,0xcf,
    0xd0,0xef,0xaa,0xfb,0x43,0x4d,0x33,0x85,0x45,0xf9,0x02,0x7f,0x50,0x3c,0x9f,0xa8,
    0x51,0xa3,0x40,0x8f,0x92,0x9d,0x38,0xf5,0xbc,0xb6,0xda,0x21,0x10,0xff,0xf3,0xd2,
    0xcd,0x0c,0x13,0xec,0x5f,0x97,0x44,0x17,0xc4,0xa7,0x7e,0x3d,0x64,0x5d,0x19,0x73,
    0x60,0x81,0x4f,0xdc,0x22,0x2a,0x90,0x88,0x46,0xee,0xb8,0x14,0xde,0x5e,0x0b,0xdb,
    0xe0,0x32,0x3a,0x0a,0x49,0x06,0x24,0x5c,0xc2,0xd3,0xac,0x62,0x91,0x95,0xe4,0x79,
    0xe7,0xc8,0x37,0x6d,0x8d,0xd5,0x4e,0xa9,0x6c,0x56,0xf4,0xea,0x65,0x7a,0xae,0x08,
    0xba,0x78,0x25,0x2e,0x1c,0xa6,0xb4,0xc6,0xe8,0xdd,0x74,0x1f,0x4b,0xbd,0x8b,0x8a,
    0x70,0x3e,0xb5,0x66,0x48,0x03,0xf6,0x0e,0x61,0x35,0x57,0xb9,0x86,0xc1,0x1d,0x9e,
    0xe1,0xf8,0x98,0x11,0x69,0xd9,0x8e,0x94,0x9b,0x1e,0x87,0xe9,0xce,0x55,0x28,0xdf,
    0x8c,0xa1,0x89,0x0d,0xbf,0xe6,0x42,0x68,0x41,0x99,0x2d,0x0f,0xb0,0x54,0xbb,0x16,
]

_RCON = [0x01,0x02,0x04,0x08,0x10,0x20,0x40,0x80,0x1b,0x36,0x6c,0xd8,0xab,0x4d,0x9a]

def _xtime(a):
    return (((a << 1) ^ 0x1b) & 0xff) if (a & 0x80) else (a << 1)

def _mul(a, b):
    r = 0
    for _ in range(8):
        if b & 1:
            r ^= a
        hi = a & 0x80
        a = (a << 1) & 0xff
        if hi:
            a ^= 0x1b
        b >>= 1
    return r

def _key_expansion(key):
    nk = len(key) // 4   # 4 for AES-128, 8 for AES-256
    nr = nk + 6          # 10 or 14
    total_words = 4 * (nr + 1)
    w = [list(key[i*4:i*4+4]) for i in range(nk)]
    for i in range(nk, total_words):
        temp = list(w[i-1])
        if i % nk == 0:
            temp = temp[1:] + temp[:1]
            temp = [_SBOX[t] for t in temp]
            temp[0] ^= _RCON[i//nk - 1]
        elif nk > 6 and i % nk == 4:
            temp = [_SBOX[t] for t in temp]
        w.append([w[i-nk][j] ^ temp[j] for j in range(4)])
    return [w[i*4:i*4+4] for i in range(nr + 1)]

def _aes_encrypt_block(rk, block):
    nr = len(rk) - 1
    # State is 16 bytes in column-major order: s[r + 4*c]
    s = list(block)
    # AddRoundKey 0
    for c in range(4):
        for r in range(4):
            s[r + 4*c] ^= rk[0][c][r]
    for rnd in range(1, nr):
        # SubBytes
        s = [_SBOX[b] for b in s]
        # ShiftRows: row r shifted left by r
        t = list(s)
        for r in range(4):
            for c in range(4):
                s[r + 4*c] = t[r + 4*((c + r) % 4)]
        # MixColumns
        for c in range(4):
            a = [s[r + 4*c] for r in range(4)]
            s[0 + 4*c] = _mul(a[0],2) ^ _mul(a[1],3) ^ a[2] ^ a[3]
            s[1 + 4*c] = a[0] ^ _mul(a[1],2) ^ _mul(a[2],3) ^ a[3]
            s[2 + 4*c] = a[0] ^ a[1] ^ _mul(a[2],2) ^ _mul(a[3],3)
            s[3 + 4*c] = _mul(a[0],3) ^ a[1] ^ a[2] ^ _mul(a[3],2)
        # AddRoundKey
        for c in range(4):
            for r in range(4):
                s[r + 4*c] ^= rk[rnd][c][r]
    # Final round (no MixColumns)
    s = [_SBOX[b] for b in s]
    t = list(s)
    for r in range(4):
        for c in range(4):
            s[r + 4*c] = t[r + 4*((c + r) % 4)]
    for c in range(4):
        for r in range(4):
            s[r + 4*c] ^= rk[nr][c][r]
    return bytes(s)

def _ghash(h, data):
    """GHASH over data (must be padded to block boundaries by caller)."""
    y = bytearray(16)
    for i in range(0, len(data), 16):
        block = data[i:i+16]
        for j in range(16):
            y[j] ^= block[j]
        y = bytearray(_gf_mul(bytes(y), h))
    return bytes(y)

def _gf_mul(x, y):
    """Multiply in GF(2^128) with reduction polynomial x^128 + x^7 + x^2 + x + 1."""
    R = 0xe1 << 120
    z = 0
    v = int.from_bytes(y, 'big')
    for i in range(128):
        if (x[i // 8] >> (7 - i % 8)) & 1:
            z ^= v
        if v & 1:
            v = (v >> 1) ^ R
        else:
            v >>= 1
    return z.to_bytes(16, 'big')

def _aes_gcm_decrypt(key, iv, ciphertext, tag, aad=b''):
    """AES-128-GCM decrypt. Returns plaintext or raises on auth failure."""
    rk = _key_expansion(key)
    h = _aes_encrypt_block(rk, b'\x00' * 16)
    j0 = iv + b'\x00\x00\x00\x01'
    # CTR decrypt
    plaintext = bytearray()
    counter = int.from_bytes(j0, 'big')
    for i in range(0, len(ciphertext), 16):
        counter = (counter + 1) & ((1 << 128) - 1)
        ctr_block = counter.to_bytes(16, 'big')
        ks = _aes_encrypt_block(rk, ctr_block)
        chunk = ciphertext[i:i+16]
        plaintext.extend(c ^ k for c, k in zip(chunk, ks))
    # GHASH
    ghash_input = bytearray()
    ghash_input.extend(aad)
    if len(aad) % 16:
        ghash_input.extend(b'\x00' * (16 - len(aad) % 16))
    ghash_input.extend(ciphertext)
    if len(ciphertext) % 16:
        ghash_input.extend(b'\x00' * (16 - len(ciphertext) % 16))
    ghash_input.extend(struct.pack('>QQ', len(aad) * 8, len(ciphertext) * 8))
    s = _ghash(h, bytes(ghash_input))
    # Tag
    tag_calc = bytes(a ^ b for a, b in zip(_aes_encrypt_block(rk, j0), s))
    if tag_calc != tag:
        raise ValueError("GCM auth tag mismatch")
    return bytes(plaintext)


def _decode_rsc(block):
    """Decode RSC push string (JSON string literal content) to plain text."""
    try:
        return json.loads('"' + block + '"')
    except Exception:
        try:
            text = re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1), 16)), block)
            text = text.replace('\\"', '"').replace('\\n', '\n').replace('\\t', '\t').replace('\\\\', '\\')
            return text
        except Exception:
            return block


def _extract_json_object(text, start_key):
    """Find start_key (e.g. '"detail":') and brace-match the following JSON object.
    Handles string-aware brace matching to avoid false matches inside string values."""
    idx = text.find(start_key)
    if idx < 0:
        return None
    brace_start = idx + len(start_key)
    # skip whitespace
    while brace_start < len(text) and text[brace_start] in ' \t\n\r':
        brace_start += 1
    if brace_start >= len(text) or text[brace_start] != '{':
        return None
    depth = 0
    in_str = False
    esc = False
    for j in range(brace_start, min(brace_start + 100000, len(text))):
        c = text[j]
        if esc:
            esc = False
            continue
        if c == '\\':
            esc = True
            continue
        if c == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return text[brace_start:j + 1]
    return None


class Spider(BaseSpider):
    HOST = "https://zlys9.top"

    CATS = {
        "movie": "电影",
        "tv": "电视剧",
        "variety": "综艺",
        "anime": "动漫",
        "children": "儿童",
    }

    CAT_NUM = {
        "movie": 1, "tv": 2, "variety": 3, "anime": 4, "children": 5,
    }

    # (label, value) pairs — value is what gets sent as query param
    FILTERS = {
        "movie": {
            "type": [("喜剧","喜剧"),("爱情","爱情"),("动作","动作"),("恐怖","恐怖"),("科幻","科幻"),
                     ("剧情","剧情"),("犯罪","犯罪"),("奇幻","奇幻"),("战争","战争"),("悬疑","悬疑"),
                     ("动画","动画"),("文艺","文艺"),("纪录","纪录"),("传记","传记"),("歌舞","歌舞"),
                     ("古装","古装"),("历史","历史"),("惊悚","惊悚"),("伦理","伦理")],
            "area": [("内地","大陆"),("香港","香港"),("台湾","台湾"),("泰国","泰国"),("美国","美国"),
                     ("韩国","韩国"),("日本","日本"),("法国","法国"),("英国","英国"),("德国","德国"),
                     ("印度","印度"),("其他","其他")],
        },
        "tv": {
            "type": [("古装","古装"),("言情","言情"),("悬疑","悬疑"),("伦理","伦理"),("警匪","警匪"),
                     ("喜剧","喜剧"),("家庭","家庭"),("历史","历史"),("军事","军事"),("武侠","武侠"),
                     ("科幻","科幻"),("奇幻","奇幻"),("都市","都市"),("其他","其他")],
            "area": [("内地","大陆"),("香港","香港"),("台湾","台湾"),("韩国","韩国"),("日本","日本"),
                     ("美国","美国"),("其他","其他")],
        },
        "variety": {
            "type": [("真人秀","真人秀"),("情感","情感"),("生活","生活"),("音乐","音乐"),("搞笑","搞笑"),
                     ("选秀","选秀"),("晚会","晚会"),("访谈","访谈"),("脱口秀","脱口秀"),("八卦","八卦")],
            "area": [("内地","大陆"),("台湾","台湾"),("日本","日本"),("美国","美国"),("其他","其他")],
        },
        "anime": {
            "type": [("热血","热血"),("推理","推理"),("搞笑","搞笑"),("治愈","治愈"),("冒险","冒险"),
                     ("校园","校园"),("机战","机战"),("科幻","科幻"),("奇幻","奇幻"),("运动","运动")],
            "area": [("日本","日本"),("内地","大陆"),("美国","美国"),("其他","其他")],
        },
        "children": {
            "type": [("益智","益智"),("亲子","亲子"),("玩具","玩具"),("早教","早教"),("动画","动画")],
            "area": [("内地","大陆"),("欧美","美国"),("其他","其他")],
        },
    }

    RANK_OPTIONS = [
        {"n": "全部", "v": ""},
        {"n": "最近热映", "v": "rankhot"},
        {"n": "最近上映", "v": "ranklatest"},
        {"n": "最受好评", "v": "rankpoint"},
    ]

    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": self.HOST + "/",
        })
        self._token = ""
        self._key = None
        self._cookie_ok = False

    def getName(self):
        return "真狼影视"

    def init(self, extend=""):
        pass

    def isVideoFormat(self, url):
        return bool(url and any(x in url.lower() for x in (".m3u8", ".mp4", ".flv", ".mkv", ".mpd")))

    def manualVideoCheck(self):
        pass

    def destroy(self):
        self.s.close()

    # ---- internal helpers ----

    def _ensure_cookie(self):
        if self._cookie_ok:
            return
        try:
            self.s.get(self.HOST + "/", timeout=15)
        except Exception:
            pass
        self._cookie_ok = True

    def _handshake(self):
        if self._token and self._key:
            return
        self._ensure_cookie()
        try:
            r = self.s.get(self.HOST + "/api/crypto/handshake", timeout=15)
            data = r.json().get("data", {})
            self._token = data.get("token", "")
            self._key = base64.b64decode(data.get("key", ""))
        except Exception:
            pass

    def _enc_get(self, path, **params):
        self._handshake()
        if not self._token or not self._key:
            return {}
        try:
            r = self.s.get(
                self.HOST + path, params=params,
                headers={"X-Enc-Token": self._token}, timeout=15,
            )
            resp = r.json()
            if resp.get("enc") and resp.get("data"):
                raw = base64.b64decode(resp["data"])
                iv, tag, ct = raw[:12], raw[12:28], raw[28:]
                decrypted = _aes_gcm_decrypt(self._key, iv, ct, tag)
                return json.loads(decrypted.decode("utf-8"))
            return resp
        except Exception:
            return {}

    def _html(self, path):
        self._ensure_cookie()
        url = path if path.startswith("http") else self.HOST + path
        try:
            r = self.s.get(url, timeout=15)
            r.raise_for_status()
            return r.text
        except Exception:
            return ""

    def _decode_all_rsc(self, html):
        """Decode all RSC push blocks and return concatenated text."""
        blocks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', html, re.DOTALL)
        parts = []
        for block in blocks:
            parts.append(_decode_rsc(block))
        return "".join(parts)

    @staticmethod
    def _parse_cat_items(text):
        """Extract video card items from decoded RSC text.
        Tries href-format first, then JSON-format."""
        items = []
        seen = set()
        # Format 1: "href":"/detail/{cat}/{id}","title":"xxx","cover":"xxx"
        for m in re.finditer(
            r'"href":"(/detail/([^/]+)/([^"]+))","title":"([^"]*)","cover":"([^"]*)"',
            text,
        ):
            path, cat, vid, title, cover = m.groups()
            if vid not in seen:
                seen.add(vid)
                items.append({"id": vid, "cat": cat, "title": title, "cover": cover})
        if items:
            return items
        # Format 2: "id":"xxx","cat":"1","title":"xxx","cover":"xxx"
        for m in re.finditer(
            r'"id":"([^"]+)","cat":"([^"]+)","title":"([^"]*)","cover":"([^"]*)"',
            text,
        ):
            vid, cat_num, title, cover = m.groups()
            cat_name = next((k for k, v in {"movie":1,"tv":2,"variety":3,"anime":4,"children":5}.items()
                            if v == int(cat_num) if cat_num.isdigit()), "movie")
            if vid not in seen:
                seen.add(vid)
                items.append({"id": vid, "cat": cat_name, "title": title, "cover": cover})
        return items

    # ---- TVBox interfaces ----

    def homeContent(self, filter):
        html = self._html("/")
        text = self._decode_all_rsc(html)
        items = self._parse_cat_items(text)

        classes = [{"type_id": k, "type_name": v} for k, v in self.CATS.items()]
        filters = {}
        for tid in self.CATS:
            f = self.FILTERS.get(tid, {})
            fl = []
            if f.get("type"):
                fl.append({"key": "type", "name": "类型",
                           "value": [{"n": "全部", "v": ""}] + [{"n": lbl, "v": val} for lbl, val in f["type"]]})
            if f.get("area"):
                fl.append({"key": "area", "name": "地区",
                           "value": [{"n": "全部", "v": ""}] + [{"n": lbl, "v": val} for lbl, val in f["area"]]})
            fl.append({"key": "rank", "name": "排序", "value": list(self.RANK_OPTIONS)})
            filters[tid] = fl

        list_items = []
        for it in items[:20]:
            list_items.append({
                "vod_id": it["cat"] + "/" + it["id"],
                "vod_name": it["title"],
                "vod_pic": it["cover"],
                "vod_remarks": "",
            })
        return {"class": classes, "list": list_items, "filters": filters}

    def homeVideoContent(self):
        html = self._html("/")
        text = self._decode_all_rsc(html)
        items = self._parse_cat_items(text)
        return {"list": [{
            "vod_id": it["cat"] + "/" + it["id"],
            "vod_name": it["title"],
            "vod_pic": it["cover"],
            "vod_remarks": "",
        } for it in items[:20]]}

    def categoryContent(self, tid, pg, filter, extend):
        page = int(pg or 1)
        # Build query params — let requests handle URL encoding
        params = {"page": str(page)}
        if extend:
            vtype = extend.get("type", "") if isinstance(extend, dict) else ""
            area = extend.get("area", "") if isinstance(extend, dict) else ""
            rank = extend.get("rank", "") if isinstance(extend, dict) else ""
            if vtype:
                params["type"] = vtype
            if area:
                params["area"] = area
            if rank:
                params["rank"] = rank

        self._ensure_cookie()
        try:
            r = self.s.get(self.HOST + "/category/" + tid + "/filter", params=params, timeout=15)
            html = r.text
        except Exception:
            html = ""
        text = self._decode_all_rsc(html)
        items = self._parse_cat_items(text)

        list_items = []
        for it in items:
            list_items.append({
                "vod_id": it["cat"] + "/" + it["id"],
                "vod_name": it["title"],
                "vod_pic": it["cover"],
                "vod_remarks": "",
            })

        total = len(list_items)
        pagecount = page + 1 if total >= 20 else page
        return {
            "page": page,
            "pagecount": pagecount,
            "limit": total,
            "total": total * 10 if total >= 20 else total,
            "list": list_items,
        }

    def detailContent(self, ids):
        vod_id_raw = str(ids[0])
        parts = vod_id_raw.split("/", 1)
        if len(parts) == 2:
            cat_name, vid = parts
        else:
            vid = vod_id_raw
            cat_name = "movie"

        html = self._html("/detail/" + cat_name + "/" + vid)
        text = self._decode_all_rsc(html)

        # Extract detail JSON
        detail_json_str = _extract_json_object(text, '"detail":')
        detail = {}
        if detail_json_str:
            try:
                detail = json.loads(detail_json_str)
            except Exception:
                pass

        title = detail.get("title", "")
        cover = detail.get("cdncover", "")
        year = ""
        pubdate = detail.get("pubdate", "")
        if pubdate:
            year = str(pubdate)[:4]
        area = detail.get("area", [])
        area_str = " ".join(area) if isinstance(area, list) else str(area)
        actor = detail.get("actor", [])
        actor_str = " ".join(actor) if isinstance(actor, list) else str(actor)
        director = detail.get("director", [])
        director_str = " ".join(director) if isinstance(director, list) else str(director)
        content = detail.get("description", "")
        total_eps = detail.get("total", 0)

        # Extract source name mapping from sources array
        source_names = {}
        for m in re.finditer(r'\{"site":"([^"]+)","name":"([^"]*)"', text):
            site, name = m.groups()
            source_names[site] = name

        # Build play_from and play_url from allepidetail
        allep = detail.get("allepidetail", {})
        play_from_parts = []
        play_url_parts = []

        for site, eps in allep.items():
            if not eps or not isinstance(eps, list):
                continue
            display_name = source_names.get(site, site)
            play_from_parts.append(display_name)
            ep_strs = []
            for ep in eps:
                if isinstance(ep, dict):
                    ep_num = ep.get("playlink_num", "")
                    ep_url = ep.get("url", "")
                    ep_name = "第" + str(ep_num) + "集" if ep_num else "第" + str(len(ep_strs) + 1) + "集"
                    if ep_url:
                        ep_strs.append(ep_name + "$" + ep_url)
                elif isinstance(ep, str):
                    ep_strs.append("第" + str(len(ep_strs) + 1) + "集$" + ep)
            if ep_strs:
                play_url_parts.append("#".join(ep_strs))

        # Fallback 1: use playlinksdetail (movies — single URL per source)
        if not play_url_parts:
            plsdetail = detail.get("playlinksdetail", {})
            if isinstance(plsdetail, dict):
                for site, sdata in plsdetail.items():
                    if not isinstance(sdata, dict):
                        continue
                    url = sdata.get("default_url", "")
                    if not url:
                        continue
                    display_name = source_names.get(site, site)
                    play_from_parts.append(display_name)
                    play_url_parts.append("正片$" + url)

        # Fallback 2: use playlinks (single URL per source)
        if not play_url_parts:
            playlinks = detail.get("playlinks", {})
            for site, url in playlinks.items():
                if url:
                    display_name = source_names.get(site, site)
                    play_from_parts.append(display_name)
                    play_url_parts.append("正片$" + url)

        play_from = "$$$".join(play_from_parts) if play_from_parts else "默认"
        play_url = "$$$".join(play_url_parts) if play_url_parts else ""

        remarks = "全" + str(total_eps) + "集" if total_eps else ""

        return {"list": [{
            "vod_id": vod_id_raw,
            "vod_name": title,
            "vod_pic": cover,
            "vod_year": year,
            "vod_area": area_str,
            "vod_actor": actor_str[:200] if actor_str else "",
            "vod_director": director_str,
            "vod_content": content[:500] if content else "",
            "vod_remarks": remarks,
            "vod_play_from": play_from,
            "vod_play_url": play_url,
        }]}

    def searchContent(self, key, quick, pg="1"):
        page = int(pg or 1)
        result = self._enc_get("/api/search", q=key, page=str(page), size="36")
        data = result.get("data", {})
        items = data.get("items", [])
        list_items = []
        for it in items:
            cat = it.get("cat", 1)
            cat_name = next((k for k, v in self.CAT_NUM.items() if v == cat), "movie")
            list_items.append({
                "vod_id": cat_name + "/" + it.get("id", ""),
                "vod_name": it.get("title", ""),
                "vod_pic": it.get("cover", ""),
                "vod_remarks": "",
            })
        total = data.get("total", len(items))
        pagecount = max(1, (total + 35) // 36) if total else 1
        return {"page": page, "pagecount": pagecount, "list": list_items}

    def playerContent(self, flag, id, vipFlags):
        url = id if id.startswith("http") else ""
        if not url:
            return {"parse": 0, "url": "", "header": ""}
        direct = self.isVideoFormat(url)
        headers = {"User-Agent": "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36"}
        if not direct:
            # External site URL (youku/iqiyi/qq) — needs parsing
            return {"parse": 1, "url": url, "header": json.dumps(headers, ensure_ascii=False)}
        return {"parse": 0, "url": url, "header": json.dumps(headers, ensure_ascii=False)}
