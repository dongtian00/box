"""
@header({
  searchable: 1,
  filterable: 1,
  quickSearch: 1,
  title: '瓜子影视',
  lang: 'hipy',
})
"""
import re
import sys
import json
import time
import base64
import hashlib
import random
import urllib.parse
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5

sys.path.append('..')
from base.spider import Spider

class Spider(Spider):
    def getName(self):
        return "瓜子"

    def init(self, extend=''):
        self.api_ua = 'okhttp/3.12.0'
        self.media_ua = 'Lavf/57.83.100'
        self.media_referer = 'http://WJiZxLXA2.com/'
        
        self.hosts = [
            'https://api.anctjd.com',
            'https://apinew.uozvr.com',
            'https://api.w32z7vtd.com',
            'https://api.6a7nnf7.com',
            'https://api.umygrx3.com',
            'https://api.rmedphk.com'
        ]
        
        self.init_control_urls = [
            'https://api.rqqakqyn.com'
        ]

        self.host_index = 0
        self.host = self.hosts[self.host_index]

        self.AES_KEY = 'OITxa5OqAYjhswxx'
        self.AES_IV = 'rCMNwZASNBKZ8mXV'

        self.RSA_PUBLIC_KEY = "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDUM5+/y8sPsWkd1/RQS64X259EUwxFXFE5HlA65MqrxnPs0JqoSRojSDy5QhwvROlaD6TwRQHKMY2OAZ6SnQeUJsChTEFIR9qUkwrs3/MVUMxjsv6JS6Oe/juclyJGTgVmDhB55EafXsD0SQYVj/QXXsxR6ewR5E2kL52yAAD4yQIDAQAB"
        self.RSA_PRIVATE_KEY = """-----BEGIN RSA PRIVATE KEY-----
MIICdgIBADANBgkqhkiG9w0BAQEFAASCAmAwggJcAgEAAoGAe6hKrWLi1zQmjTT1
ozbE4QdFeJGNxubxld6GrFGximxfMsMB6BpJhpcTouAqywAFppiKetUBBbXwYsYU
1wNr648XVmPmCMCy4rY8vdliFnbMUj086DU6Z+/oXBdWU3/b1G0DN3E9wULRSwcK
ZT3wj/cCI1vsCm3gj2R5SqkA9Y0CAwEAAQKBgAJH+4CxV0/zBVcLiBCHvSANm0l7
HetybTh/j2p0Y1sTXro4ALwAaCTUeqdBjWiLSo9lNwDHFyq8zX90+gNxa7c5EqcW
V9FmlVXr8VhfBzcZo1nXeNdXFT7tQ2yah/odtdcx+vRMSGJd1t/5k5bDd9wAvYdI
DblMAg+wiKKZ5KcdAkEA1cCakEN4NexkF5tHPRrR6XOY/XHfkqXxEhMqmNbB9U34
saTJnLWIHC8IXys6Qmzz30TtzCjuOqKRRy+FMM4TdwJBAJQZFPjsGC+RqcG5UvVM
iMPhnwe/bXEehShK86yJK/g/UiKrO87h3aEu5gcJqBygTq3BBBoH2md3pr/W+hUM
WBsCQQChfhTIrdDinKi6lRxrdBnn0Ohjg2cwuqK5zzU9p/N+S9x7Ck8wUI53DKm8
jUJE8WAG7WLj/oCOWEh+ic6NIwTdAkEAj0X8nhx6AXsgCYRql1klbqtVmL8+95KZ
K7PnLWG/IfjQUy3pPGoSaZ7fdquG8bq8oyf5+dzjE/oTXcByS+6XRQJAP/5ciy1b
L3NhUhsaOVy55MHXnPjdcTX0FaLi+ybXZIfIQ2P4rb19mVq1feMbCXhz+L1rG8oa
t5lYKfpe8k83ZA==
-----END RSA PRIVATE KEY-----"""

        self.DEVICE_OLD_KEY = "aLFBMWpxBrIDAD1Si/KVvm41"
        self.deviceId = str(864150060000000 + random.randint(0, 9999))
        self.deviceKey = ''.join(random.choices('0123456789ABCDEF', k=40))
        self.token = ""
        self.token_id = ""
        self.registered = False

        self.header = {
            'User-Agent': self.api_ua,
            'code': 'GZ0055',
            'deviceId': self.deviceId,
            'lang': 'zh_cn',
            'Cache-Control': 'no-cache',
            'Content-Type': 'application/x-www-form-urlencoded',
            'Version': '2608011',
            'PackageName': 'com.xf4a1daee2.g3520dce0d.f8a8ed889d20260813',
            'Ver': '3.0.5.2',
            'api-ver': '3.0.5.2',
            'Referer': self.host
        }

        self.cache = {}
        self.cache_timeout = 300
        
        # 主动触发初始化生命周期
        self.fetch_latest_hosts()
        self.init_token()

    def fetch_latest_hosts(self):
        for control_url in self.init_control_urls:
            try:
                url = f"{control_url}/gz/initialize/getApiUrlList?parameter=key"
                response = requests.post(url, timeout=5, verify=False)
                if response.status_code == 200:
                    resp_json = response.json()
                    if resp_json.get('code') == 200 and 'data' in resp_json:
                        encrypted_data = resp_json['data']
                        decrypted_str = self._try_decrypt_init_data(encrypted_data)
                        if decrypted_str:
                            hosts_data = json.loads(decrypted_str)
                            if isinstance(hosts_data, list) and len(hosts_data) > 0:
                                self.hosts = hosts_data
                                return
                            elif isinstance(hosts_data, dict):
                                possible_list = hosts_data.get('list') or hosts_data.get('urls')
                                if possible_list and isinstance(possible_list, list):
                                    self.hosts = possible_list
                                    return
            except Exception:
                pass

    def _try_decrypt_init_data(self, encrypted_text):
        try:
            try:
                decoded_test = base64.b64decode(encrypted_text).decode('utf-8')
                if decoded_test.startswith('[') or decoded_test.startswith('{'):
                    return decoded_test
            except:
                pass
            return base64.b64decode(encrypted_text).decode('utf-8')
        except Exception:
            return encrypted_text

    def init_token(self):
        try:
            if not self.registered:
                self.sign_up()
        except Exception as e:
            self.token = '024212ef0975c5306a1434e113a46463.bc77313e11a248558a6ca244ca980944ec3421fa480c50e0229ad91f1cb15aea582603202cd71796885c9e5163e500f1b72f737059aff1ddb8beea47c5a331d6760540345b7f88b2302a0e6e09589f9dcf3ff9175d8c905f990203f5fc04748008ea7a366571cbf5b09509a873dcfba3cf1d5590385f5f7ef6e01d1850974aa220eb5178c89e61c24411af9b9a19435e.06fde789ece48d9b33c5dc857e04e9b5838f08264d928b87237d3476c4484b46'

    def sign_up(self):
        params = {"new_key": self.deviceKey, "old_key": self.DEVICE_OLD_KEY, "phone_type": 1, "code": ""}
        result = self._auth_request('/App/Authentication/Device/signUp', params)
        if result:
            self._apply_auth(result)
            self.registered = True

    def sign_in(self):
        params = {"new_key": self.deviceKey, "old_key": self.DEVICE_OLD_KEY}
        result = self._auth_request('/App/Authentication/Device/signIn', params)
        if result:
            self._apply_auth(result)

    def _apply_auth(self, result):
        new_token = result.get('token', '')
        if new_token:
            self.token = new_token
            new_token_id = result.get('app_user_id', '')
            if new_token_id:
                self.token_id = new_token_id

    def refresh_token(self):
        result = self._auth_request('/App/Authentication/Authenticator/refresh', {})
        if result:
            self._apply_auth(result)

    def _auth_request(self, path, params):
        return self._send_encrypted_request(params, path, is_auth=True)

    def ensure_token(self):
        if not self.token:
            if self.registered:
                self.sign_in()
            else:
                self.sign_up()

    def _send_encrypted_request(self, data, path, is_auth=False):
        try:
            if not is_auth:
                self.ensure_token()

            json_params = json.dumps(data)
            encrypted = self.aes_encrypt(json_params, self.AES_KEY, self.AES_IV)
            request_key = encrypted.upper()

            key_json = json.dumps({"iv": self.AES_IV, "key": self.AES_KEY})
            keys = self.rsa_encrypt(key_json, self.RSA_PUBLIC_KEY)

            t = str(int(time.time()))
            sign_str = f"token_id=,token={self.token},phone_type=1,request_key={request_key},app_id=1,time={t},keys={keys}*&zvdvdvddbfikkkumtmdwqppp?|4Y!s!2br"
            signature = self.get_md5(sign_str)

            body = {
                'token': self.token,
                'token_id': '',
                'phone_type': '1',
                'time': t,
                'phone_model': 'xiaomi-25031',
                'keys': keys,
                'request_key': request_key,
                'signature': signature,
                'app_id': '1',
                'ad_version': '1'
            }

            url = f"{self.host}{path}"
            response = requests.post(url, headers=self.header, data=body, timeout=6, verify=False)

            if response.status_code != 200:
                return None

            resp_json = response.json()
            if 'code' in resp_json and resp_json['code'] != 200:
                return None

            data_section = resp_json.get('data')
            if not data_section:
                return None

            encrypted_response = data_section.get('response_key', '')
            encrypted_keys = data_section.get('keys', '')

            decrypted_keys_json = self.rsa_decrypt(encrypted_keys, self.RSA_PRIVATE_KEY)
            key_info = json.loads(decrypted_keys_json)
            resp_key = key_info['key']
            resp_iv = key_info['iv']
            decrypted_data = self.aes_decrypt(encrypted_response, resp_key, resp_iv)
            return json.loads(decrypted_data)
        except Exception as e:
            return None
    def get_data(self, data, path, use_cache=True):
        try:
            cache_key = f"{path}_{hash(str(data))}" if use_cache else None
            if use_cache and cache_key in self.cache:
                cached_data, timestamp = self.cache[cache_key]
                if time.time() - timestamp < self.cache_timeout:
                    return cached_data

            for attempt in range(1):
                tried = 0
                while tried < min(3, len(self.hosts)):
                    self.host = self.hosts[self.host_index]
                    self.header['Referer'] = self.host
                    result = self._send_encrypted_request(data, path)
                    if result is not None:
                        if use_cache and cache_key:
                            self.cache[cache_key] = (result, time.time())
                        return result

                    self.host_index = (self.host_index + 1) % len(self.hosts)
                    tried += 1

                if attempt < 2:
                    try:
                        self.ensure_token()
                    except:
                        pass
                    self.host_index = 0
                else:
                    break
            return None
        except Exception:
            return None

    def aes_encrypt(self, text, key, iv):
        try:
            key_bytes = key.encode('utf-8')
            iv_bytes = iv.encode('utf-8')
            cipher = AES.new(key_bytes, AES.MODE_CBC, iv_bytes)
            encrypted = cipher.encrypt(pad(text.encode('utf-8'), AES.block_size))
            return encrypted.hex().upper()
        except Exception:
            return ""

    def aes_decrypt(self, text, key, iv):
        try:
            key_bytes = key.encode('utf-8')
            iv_bytes = iv.encode('utf-8')
            cipher = AES.new(key_bytes, AES.MODE_CBC, iv_bytes)
            encrypted_bytes = bytes.fromhex(text)
            decrypted = unpad(cipher.decrypt(encrypted_bytes), AES.block_size)
            return decrypted.decode('utf-8')
        except Exception:
            return ""

    def rsa_encrypt(self, text, public_key_str):
        try:
            key = RSA.import_key("-----BEGIN PUBLIC KEY-----\n" + public_key_str + "\n-----END PUBLIC KEY-----")
            cipher = PKCS1_v1_5.new(key)
            encrypted = cipher.encrypt(text.encode('utf-8'))
            return base64.b64encode(encrypted).decode('utf-8')
        except Exception:
            return ""

    def rsa_decrypt(self, encrypted_data, private_key_str):
        try:
            encrypted_bytes = base64.b64decode(encrypted_data)
            rsa_key = RSA.import_key(private_key_str)
            cipher = PKCS1_v1_5.new(rsa_key)
            decrypted = cipher.decrypt(encrypted_bytes, None)
            return decrypted.decode('utf-8') if decrypted else ""
        except Exception:
            return ""

    def get_md5(self, text):
        return hashlib.md5(text.encode()).hexdigest().upper()

    def homeContent(self, filter):
        result = {}
        classes = [
            {"type_name": "精选", "type_id": "home"},
            {"type_name": "热门", "type_id": "999"},
            {"type_name": "电影", "type_id": "1"},
            {"type_name": "电视剧", "type_id": "2"},
            {"type_name": "动漫", "type_id": "4"},
            {"type_name": "综艺", "type_id": "3"},
            {"type_name": "短剧", "type_id": "64"},
            {"type_name": "漫剧", "type_id": "74"},
            {"type_name": "儿童", "type_id": "33"},
            {"type_name": "海外剧", "type_id": "5"},
            {"type_name": "AI漫剧", "type_id": "74"},
            {"type_name": "音乐", "type_id": "72"},
            {"type_name": "电影解说", "type_id": "73"},
            {"type_name": "电竞解说", "type_id": "70"},
            {"type_name": "体育解说", "type_id": "71"}
        ]
        result['class'] = classes
        filters = {}
        for cate in classes:
            tid = cate['type_id']
            if tid == 'home':
                continue
                
            filters[tid] = [
                {"key": "area", "name": "地区", "value": [
                    {"n": "全部", "v": "0"}, {"n": "大陆", "v": "大陆"}, {"n": "香港", "v": "香港"},
                    {"n": "台湾", "v": "台湾"}, {"n": "美国", "v": "美国"}, {"n": "韩国", "v": "韩国"},
                    {"n": "日本", "v": "日本"}, {"n": "英国", "v": "英国"}, {"n": "法国", "v": "法国"},
                    {"n": "泰国", "v": "泰国"}, {"n": "印度", "v": "印度"}, {"n": "其他", "v": "其他"}
                ]},
                {"key": "year", "name": "年份", "value": [
                    {"n": "全部", "v": "0"}, {"n": "2025", "v": "2025"}, {"n": "2024", "v": "2024"},
                    {"n": "2023", "v": "2023"}, {"n": "2022", "v": "2022"}, {"n": "2021", "v": "2021"},
                    {"n": "2020", "v": "2020"}, {"n": "2019", "v": "2019"}, {"n": "2018", "v": "2018"},
                    {"n": "2017", "v": "2017"}, {"n": "2016", "v": "2016"}, {"n": "2015", "v": "2015"},
                    {"n": "2014", "v": "2014"}, {"n": "2013", "v": "2013"}, {"n": "2012", "v": "2012"},
                    {"n": "2011", "v": "2011"}, {"n": "2010", "v": "2010"}, {"n": "2009", "v": "2009"},
                    {"n": "2008", "v": "2008"}, {"n": "2007", "v": "2007"}, {"n": "2006", "v": "2006"},
                    {"n": "2005", "v": "2005"}, {"n": "更早", "v": "2004"}
                ]},
                {"key": "sort", "name": "排序", "value": [
                    {"n": "最新", "v": "d_id"}, {"n": "最热", "v": "d_hits"}, {"n": "推荐", "v": "d_score"}
                ]}
            ]
        result['filters'] = filters
        return result

    def homeVideoContent(self):
        return self.categoryContent('home', 1, False, {})

    def categoryContent(self, tid, pg, filter, extend):
        videos = []
        try:
            tid = str(tid or '0')
            try:
                page = max(1, int(pg))
            except (TypeError, ValueError):
                page = 1

            if not isinstance(extend, dict):
                try:
                    extend = json.loads(extend) if extend else {}
                except (TypeError, ValueError, json.JSONDecodeError):
                    extend = {}
            if not isinstance(extend, dict):
                extend = {}

            request_tid = '0' if tid in ['999', 'home'] else tid
            
            if tid == 'home':
                request_sort = 'd_score' 
            elif tid == '999':
                request_sort = 'd_hits'
            else:
                request_sort = extend.get('sort', 'd_id')

            body = {
                "area": extend.get('area', '0'),
                "year": extend.get('year', '0'),
                "pageSize": "30",
                "sort": request_sort,
                "page": str(page),
                "tid": request_tid
            }
            cache_key = f"category_{tid}_{page}_{hash(str(body))}"
            data = self.get_cached_data(cache_key, body, '/App/IndexList/indexList')
            
            if data and 'list' in data:
                for index, item in enumerate(data['list']):
                    vod_continu = item.get('vod_continu', 0)
                    remarks = '电影' if vod_continu == 0 else f'更新至{vod_continu}集'
                    
                    video = {
                        "vod_id": f"{item.get('vod_id', '')}/{vod_continu}",
                        "vod_name": item.get('vod_name', ''),
                        "vod_pic": item.get('vod_pic', ''),
                        "vod_remarks": remarks
                    }
                    videos.append(video)
        except Exception as e:
            print(f"获取分类内容失败: {e}")
            
        return {'list': videos, 'page': page if 'page' in locals() else 1, 'pagecount': 9999, 'limit': 30, 'total': 999999}

    def detailContent(self, ids):
        try:
            vod_id = ids[0].split('/')[0]
            t = str(int(time.time()))
            body1 = {"token_id": self.token_id, "vod_id": vod_id, "mobile_time": t, "token": self.token}
            qdata = self.get_data(body1, '/App/IndexPlay/playInfo')
            body2 = {"vurl_cloud_id": "2", "vod_d_id": vod_id}
            jdata = self.get_data(body2, '/App/Resource/Vurl/show')
            if not qdata or 'vodInfo' not in qdata:
                return {'list': []}
            vod = qdata['vodInfo']
            video_detail = {
                "vod_id": vod_id,
                "vod_name": vod.get('vod_name', ''),
                "vod_pic": vod.get('vod_pic', ''),
                "vod_year": vod.get('vod_year', ''),
                "vod_area": vod.get('vod_area', ''),
                "vod_actor": vod.get('vod_actor', ''),
                "vod_director": vod.get('vod_director', ''),
                "vod_content": vod.get('vod_use_content', '').strip(),
                "vod_play_from": "冬天瓜子"
            }
            play_list = []
            if jdata and 'list' in jdata:
                for index, item in enumerate(jdata['list']):
                    if 'play' in item:
                        n, p = [], []
                        for key, value in item['play'].items():
                            if 'param' in value and value['param']:
                                n.append(key)
                                p.append(value['param'])
                        if p:
                            play_name = str(index + 1) if len(jdata['list']) != 1 else vod.get('vod_name', '')
                            play_url = f"{p[-1]}||{n[-1]}"
                            play_list.append(f"{play_name}${play_url}")
            video_detail["vod_play_url"] = "#".join(play_list)
            return {'list': [video_detail]}
        except Exception:
            return {'list': []}

    def searchContent(self, key, quick, pg=1):
        videos = []
        try:
            body = {"keywords": key, "order_val": "1", "page": str(pg)}
            data = self.get_data(body, '/App/Index/findMoreVod', use_cache=False)
            if data and 'list' in data:
                for item in data['list']:
                    vod_continu = item.get('vod_continu', 0)
                    remarks = '电影' if vod_continu == 0 else f'更新至{vod_continu}集'
                    videos.append({
                        "vod_id": f"{item.get('vod_id', '')}/{vod_continu}",
                        "vod_name": item.get('vod_name', ''),
                        "vod_pic": item.get('vod_pic', ''),
                        "vod_remarks": remarks
                    })
        except Exception:
            pass
        return {'list': videos, 'page': int(pg), 'pagecount': 9999, 'limit': 30, 'total': 999999}

    def playerContent(self, flag, id, vipFlags):
        try:
            parts = id.split('||')
            if len(parts) < 2:
                return {"parse": 0, "playUrl": "", "url": ""}
            param_str = parts[0]
            resolutions = parts[1].split('@') if len(parts) > 1 else []
            params = {}
            for pair in param_str.split('&'):
                if '=' in pair:
                    key, value = pair.split('=', 1)
                    params[key] = value
            if resolutions:
                params['resolution'] = resolutions[0]
                data = self.get_data(params, '/App/Resource/VurlDetail/showOne', use_cache=False)
                if data and 'url' in data:
                    return {
                        "parse": 0, 
                        "playUrl": "", 
                        "url": data['url'],
                        "header": json.dumps({
                            "User-Agent": self.media_ua,
                            "Referer": self.media_referer
                        })
                    }
            return {"parse": 0, "playUrl": "", "url": ""}
        except Exception:
            return {"parse": 0, "playUrl": "", "url": ""}

    def isVideoFormat(self, url):
        return False
    def manualVideoCheck(self):
        return False
    def localProxy(self, params):
        return None
    def destroy(self):
        pass
    def get_cached_data(self, cache_key, data, path):
        current_time = time.time()
        if cache_key in self.cache:
            cached_data, timestamp = self.cache[cache_key]
            if current_time - timestamp < self.cache_timeout:
                return cached_data
        result = self.get_data(data, path)
        if result:
            self.cache[cache_key] = (result, current_time)
        return result
