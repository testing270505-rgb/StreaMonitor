import itertools
import json
import random
import re
import time
import requests
import base64
import hashlib
import os
from functools import lru_cache
from typing import Optional, Tuple, List, Dict

from urllib.parse import urljoin
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from streamonitor.bot import Bot
from streamonitor.downloaders.hls import getVideoNativeHLS
from streamonitor.enums import Status


class StripChat(Bot):
    site = "StripChat"
    siteslug = "SC"

    _static_data = None
    _main_js_data = None
    _doppio_js_data = None
    _mouflon_cache_filename = 'stripchat_mouflon_keys.json'
    _mouflon_keys: dict = None
    _session = None

    _DOPPIO_INDEX_PATTERN = re.compile(r'(\d+):\s*"([a-f0-9]+)"')
    _DOPPIO_REQUIRE_PATTERN = re.compile(r'require\(["\']\./(Doppio[^"\']+\.js)["\']\)')
    _HASH_PATTERNS = [
        re.compile(r'{}:\\"([a-zA-Z0-9]{{20}})\\"'),
        re.compile(r'{}:"([a-zA-Z0-9]{{20}})"'),
        re.compile(r'"{}":"([a-zA-Z0-9]{{20}})"'),
    ]

    _MOUFLON_NEEDLE = "#EXT-X-MOUFLON:"
    _MOUFLON_FILE_ATTR = "#EXT-X-MOUFLON:FILE:"
    _MOUFLON_URI_ATTR = "#EXT-X-MOUFLON:URI:"
    _MOUFLON_FILENAME = "media.mp4"
    _CDN_DOMAINS = ("org", "com", "net")

    _PRIVATE_STATUSES = frozenset(["private", "groupShow", "p2p", "virtualPrivate", "p2pVoice"])
    _OFFLINE_STATUSES = frozenset(["off", "idle"])

    _MMP_FALLBACK_VERSION = "v2.6.0"

    __slots__ = ('vr',)

    if os.path.exists(_mouflon_cache_filename):
        with open(_mouflon_cache_filename) as f:
            try:
                if not isinstance(_mouflon_keys, dict):
                    _mouflon_keys = {}
                _mouflon_keys.update(json.load(f))
                print('Loaded StripChat mouflon key cache')
            except Exception as e:
                print('Error loading mouflon key cache:', e)

    def __init__(self, username):
        if StripChat._static_data is None:
            StripChat._static_data = {}
            try:
                self.getInitialData()
            except Exception as e:
                StripChat._static_data = None
                raise e

        end_time = time.time() + 15
        while StripChat._static_data == {} and time.time() < end_time:
            time.sleep(0.01)

        if StripChat._static_data == {}:
            raise TimeoutError("Static data initialization timeout")

        super().__init__(username)
        self.vr = False
        self.getVideo = lambda _, url, filename: getVideoNativeHLS(
            self, url, filename, StripChat.m3u_decoder
        )

    @classmethod
    def _get_session(cls):
        if cls._session is None:
            cls._session = requests.Session()
            retry = Retry(
                total=2,
                backoff_factor=0.1,
                status_forcelist=[429, 500, 502, 503, 504],
            )
            adapter = HTTPAdapter(
                max_retries=retry,
                pool_connections=15,
                pool_maxsize=30,
                pool_block=False
            )
            cls._session.mount("http://", adapter)
            cls._session.mount("https://", adapter)
            cls._session.headers.update({
                'Connection': 'keep-alive',
                'Accept-Encoding': 'gzip, deflate'
            })
        return cls._session

    @classmethod
    def getInitialData(cls):
        s = cls._get_session()

        try:
            r = s.get(
                "https://hu.stripchat.com/api/front/v3/config/static",
                headers=cls.headers,
                timeout=5
            )
            r.raise_for_status()
            response_json = r.json()

            if "static" in response_json:
                static_data = response_json["static"]
            else:
                static_data = response_json

            mmp_origin = static_data.get("featureSettings", {}).get(
                "MMPExternalUnitedSourceOrigin",
                "https://mmp.doppiocdn.com/player/mmp"
            )

            mmp_version = cls._MMP_FALLBACK_VERSION
            try:
                r_home = s.get("https://stripchat.com", headers=cls.headers, timeout=5)
                r_home.raise_for_status()
                version_match = re.search(
                    r'mmp\.doppiocdn\.com/player/mmp/(v[\d.]+)/',
                    r_home.text
                )
                if version_match:
                    mmp_version = version_match.group(1)
            except Exception:
                pass

            mmp_base = f"{mmp_origin}/{mmp_version}"

            r = s.get(f"{mmp_base}/main.js", headers=cls.headers, timeout=5)
            r.raise_for_status()
            main_js_data = r.text

            doppio_url = None

            if match := cls._DOPPIO_REQUIRE_PATTERN.search(main_js_data):
                doppio_url = f"{mmp_base}/{match[1]}"
            elif match := cls._DOPPIO_INDEX_PATTERN.search(main_js_data):
                idx = match[1]
                for pattern_template in cls._HASH_PATTERNS:
                    pattern = re.compile(pattern_template.pattern.format(idx))
                    if hash_match := pattern.search(main_js_data):
                        doppio_url = f"{mmp_base}/chunk-{hash_match[1]}.js"
                        break

            if not doppio_url:
                raise Exception("Doppio.js not found")

            r = s.get(doppio_url, headers=cls.headers, timeout=5)
            r.raise_for_status()
            doppio_js_data = r.text

            StripChat._static_data = static_data
            StripChat._main_js_data = main_js_data
            StripChat._doppio_js_data = doppio_js_data

        except Exception as e:
            print(f"ERROR in getInitialData: {e}")
            raise

    @staticmethod
    def uniq(length: int = 16) -> str:
        return ''.join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=length))

    @classmethod
    @lru_cache(maxsize=512)
    def _get_hash_bytes(cls, key: str) -> bytes:
        return hashlib.sha256(key.encode()).digest()

    @classmethod
    def m3u_decoder(cls, content: str) -> str:
        @lru_cache(maxsize=64)
        def _decode(encrypted_b64: str, key: str) -> str:
            hash_bytes = cls._get_hash_bytes(key)
            encrypted_data = base64.b64decode(encrypted_b64 + "==")
            return bytes(a ^ b for (a, b) in zip(encrypted_data, itertools.cycle(hash_bytes))).decode("utf-8")

        psch, _, pdkey = cls._getMouflonFromM3U(content)
        if not pdkey:
            return content

        decoded = []
        lines = content.splitlines()
        last_decoded_file = None

        if psch == "v1":
            for line in lines:
                if line.startswith(cls._MOUFLON_FILE_ATTR):
                    last_decoded_file = _decode(line[len(cls._MOUFLON_FILE_ATTR):], pdkey)
                elif last_decoded_file and line.endswith(cls._MOUFLON_FILENAME):
                    decoded.append(line.replace(cls._MOUFLON_FILENAME, last_decoded_file))
                    last_decoded_file = None
                elif line.startswith(cls._MOUFLON_NEEDLE):
                    continue
                else:
                    decoded.append(line)

        elif psch == "v2":
            i = 0
            while i < len(lines):
                line = lines[i]

                if line.startswith(cls._MOUFLON_URI_ATTR):
                    enc = line[len(cls._MOUFLON_URI_ATTR):].strip()
                    try:
                        left, ts = enc.rsplit("_", 1)
                        left2, enc_part = left.rsplit("_", 1)
                        dec = _decode(enc_part[::-1], pdkey)
                        real_uri = f"{left2}_{dec}_{ts}"

                        i += 1
                        while i < len(lines):
                            nxt = lines[i]
                            if nxt.startswith("#"):
                                decoded.append(nxt)
                                i += 1
                                continue
                            decoded.append(real_uri)
                            i += 1
                            break
                        continue
                    except Exception:
                        i += 1
                        continue

                if line.startswith(cls._MOUFLON_NEEDLE):
                    i += 1
                    continue

                decoded.append(line)
                i += 1
        else:
            return content

        return "\n".join(decoded)

    @classmethod
    @lru_cache(maxsize=128)
    def getMouflonDecKey(cls, pkey: str) -> Optional[str]:
        if cls._mouflon_keys is None:
            cls._mouflon_keys = {}

        if pkey in cls._mouflon_keys:
            return cls._mouflon_keys[pkey]

        if not cls._doppio_js_data:
            return None

        pattern = f'"{pkey}:'
        idx = cls._doppio_js_data.find(pattern)
        if idx != -1:
            start = idx + len(pattern)
            end = cls._doppio_js_data.find('"', start)
            if end != -1:
                key = cls._doppio_js_data[start:end]
                cls._mouflon_keys[pkey] = key
                return key

        return None

    @staticmethod
    def _getMouflonFromM3U(m3u8_doc: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        needle = StripChat._MOUFLON_NEEDLE
        idx = 0

        while (idx := m3u8_doc.find(needle, idx)) != -1:
            line_end = m3u8_doc.find('\n', idx)
            if line_end == -1:
                line_end = len(m3u8_doc)

            line = m3u8_doc[idx:line_end]
            parts = line.split(':', 3)

            if len(parts) >= 4:
                psch, pkey = parts[2], parts[3]
                if pdkey := StripChat.getMouflonDecKey(pkey):
                    return psch, pkey, pdkey

            idx += len(needle)

        return None, None, None

    def getWebsiteURL(self) -> str:
        return f"https://stripchat.com/{self.username}"

    def getVideoUrl(self):
        selected = self.getWantedResolutionPlaylist(None)
        if not selected:
            return selected
        if selected.startswith(("http://", "https://")):
            return selected

        stream_id = self.lastInfo["streamName"]
        vr = "_vr" if self.vr else ""
        auto = "_auto" if not self.vr else ""
        host = f"doppiocdn.{random.choice(self._CDN_DOMAINS)}"
        master_url = f"https://edge-hls.{host}/hls/{stream_id}{vr}/master/{stream_id}{vr}{auto}.m3u8"
        return urljoin(master_url, selected)

    def getPlaylistVariants(self, url) -> List[Dict]:
        stream_id = self.lastInfo["streamName"]
        vr = "_vr" if self.vr else ""
        auto = "_auto" if not self.vr else ""

        host = f"doppiocdn.{random.choice(self._CDN_DOMAINS)}"
        master_url = f"https://edge-hls.{host}/hls/{stream_id}{vr}/master/{stream_id}{vr}{auto}.m3u8"

        try:
            result = self.session.get(master_url, headers=self.headers, cookies=self.cookies, timeout=4)
            result.raise_for_status()
        except Exception:
            return []

        m3u8_doc = result.text
        psch, pkey, _ = self._getMouflonFromM3U(m3u8_doc)

        variants = super().getPlaylistVariants(m3u_data=m3u8_doc)
        if not variants:
            return []

        fixed = []
        for v in variants:
            vurl = v.get("url", "")
            abs_url = vurl if vurl.startswith(("http://", "https://")) else urljoin(master_url, vurl)

            if psch and pkey:
                sep = "&" if "?" in abs_url else "?"
                abs_url = f"{abs_url}{sep}psch={psch}&pkey={pkey}"

            nv = dict(v)
            nv["url"] = abs_url
            fixed.append(nv)

        return fixed

    def getStatus(self) -> Status:
        url = f"https://stripchat.com/api/front/v2/models/username/{self.username}/cam?uniq={self.uniq()}"

        try:
            r = self.session.get(url, headers=self.headers, timeout=4)
            r.raise_for_status()
            data = r.json()
        except Exception:
            return Status.UNKNOWN

        if "cam" not in data:
            if data.get("error") == "Not Found":
                return Status.NOTEXIST
            return Status.UNKNOWN

        self.lastInfo = {"model": data["user"]["user"]}
        if isinstance(data["cam"], dict):
            self.lastInfo.update(data["cam"])

        status = self.lastInfo["model"].get("status")

        if status == "public" and self.lastInfo.get("isCamAvailable") and self.lastInfo.get("isCamActive"):
            return Status.PUBLIC

        if status in self._PRIVATE_STATUSES:
            return Status.PRIVATE

        if status in self._OFFLINE_STATUSES:
            return Status.OFFLINE

        if self.lastInfo["model"].get("isDeleted"):
            return Status.NOTEXIST

        if data["user"].get("isGeoBanned"):
            return Status.RESTRICTED

        return Status.UNKNOWN