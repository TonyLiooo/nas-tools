import requests
import urllib3
from urllib3.exceptions import InsecureRequestWarning
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
from config import Config
from urllib.parse import urlparse
import time
import socket
import threading
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED, TimeoutError as FuturesTimeoutError

urllib3.disable_warnings(InsecureRequestWarning)


class RequestUtils:
    _headers = None
    _cookies = None
    _proxies = None
    _timeout = (5, 20)
    _session = None

    # thread-local DNS family selector for dual-stack racing
    _tls = threading.local()
    _orig_getaddrinfo = socket.getaddrinfo
    _ga_installed = False

    def _ga_wrapper(host, port, family=0, type=0, proto=0, flags=0):
        res = RequestUtils._orig_getaddrinfo(host, port, family, type, proto, flags)
        desired = getattr(RequestUtils._tls, 'family', None)
        if desired is None:
            return res
        try:
            filtered = [r for r in res if r and r[0] == desired]
            return filtered if filtered else res
        except Exception:
            return res

    @staticmethod
    def _ensure_ga_installed():
        if not RequestUtils._ga_installed:
            socket.getaddrinfo = RequestUtils._ga_wrapper
            RequestUtils._ga_installed = True

    def __init__(self,
                 headers=None,
                 cookies=None,
                 api_key=None,
                 proxies=False,
                 session=None,
                 timeout=None,
                 referer=None,
                 content_type=None,
                 accept_type=None,
                 retries=3,
                 backoff_factor=0.5,
                 status_forcelist=None,
                 allowed_methods=None,
                 exception_retries=1,
                 dual_stack_race=False,
                 prefer_ipv4=True):
        if not content_type:
            content_type = "application/x-www-form-urlencoded; charset=UTF-8"
        if headers:
            if isinstance(headers, str):
                self._headers = {
                    "Content-Type": content_type,
                    "User-Agent": f"{headers}",
                    "Accept": accept_type
                }
            else:
                self._headers = headers
        else:
            self._headers = {
                "Content-Type": content_type,
                "User-Agent": Config().get_ua(),
                "Accept": accept_type
            }
        if referer:
            self._headers.update({
                "referer": referer
            })
        if cookies:
            if isinstance(cookies, str):
                self._cookies = self.cookie_parse(cookies)
            else:
                self._cookies = cookies
        if api_key:
            self._headers.update({
                'x-api-key': api_key
            })
        if proxies:
            self._proxies = proxies
        # session & retry policy (Plan A)
        # 默认开启重试，若传入retries<=0则不启用
        if session:
            self._session = session
        else:
            self._session = requests.Session()

        # 保存重试配置用于异常级别退避
        self._retry_backoff_factor = backoff_factor
        self._exception_retries = exception_retries if exception_retries is not None else 1

        if status_forcelist is None:
            status_forcelist = (429, 500, 502, 503, 504)
        if allowed_methods is None:
            allowed_methods = frozenset(["HEAD", "GET", "OPTIONS", "POST"])  # POST仅在安全可重试的场景使用

        if retries and retries > 0:
            retry_kwargs = {
                "total": retries,
                "connect": retries,
                "read": retries,
                "status": retries,
                "backoff_factor": backoff_factor,
                "status_forcelist": status_forcelist,
                "raise_on_status": False,
                "respect_retry_after_header": True
            }
            # 兼容不同urllib3版本的参数名 (allowed_methods/method_whitelist)
            try:
                retry = Retry(allowed_methods=allowed_methods, **retry_kwargs)
            except TypeError:
                retry = Retry(method_whitelist=allowed_methods, **retry_kwargs)

            adapter = HTTPAdapter(max_retries=retry)
            self._session.mount("http://", adapter)
            self._session.mount("https://", adapter)

        if timeout:
            self._timeout = timeout
        self._dual_stack_race = dual_stack_race
        self._prefer_ipv4 = prefer_ipv4

    def _send_once(self, method, url, data=None, params=None, allow_redirects=True, files=None, json=None):
        if self._session:
            return self._session.request(method,
                                         url,
                                         data=data,
                                         params=params,
                                         verify=False,
                                         headers=self._headers,
                                         proxies=self.get_proxy(url),
                                         cookies=self._cookies,
                                         timeout=self._timeout,
                                         allow_redirects=allow_redirects,
                                         files=files,
                                         json=json)
        else:
            return requests.request(method,
                                    url,
                                    data=data,
                                    params=params,
                                    verify=False,
                                    headers=self._headers,
                                    proxies=self.get_proxy(url),
                                    cookies=self._cookies,
                                    timeout=self._timeout,
                                    allow_redirects=allow_redirects,
                                    files=files,
                                    json=json)

    def _send_with_race(self, method, url, data=None, params=None, allow_redirects=True, files=None, json=None, raise_exception=False):
        attempts = (self._exception_retries or 0) + 1
        for attempt in range(attempts):
            try:
                # do not race when proxies are in use
                if self.get_proxy(url):
                    return self._send_once(method, url, data=data, params=params, allow_redirects=allow_redirects, files=files, json=json)

                if self._dual_stack_race:
                    RequestUtils._ensure_ga_installed()

                    def runner(family):
                        try:
                            RequestUtils._tls.family = family
                            return self._send_once(method, url, data=data, params=params, allow_redirects=allow_redirects, files=files, json=json)
                        finally:
                            RequestUtils._tls.family = None

                    ex = ThreadPoolExecutor(max_workers=2)
                    try:
                        f6 = ex.submit(runner, socket.AF_INET6)
                        f4 = ex.submit(runner, socket.AF_INET)
                        done, pending = wait({f6, f4}, return_when=FIRST_COMPLETED)
                        first = next(iter(done))
                        try:
                            r_first = first.result()
                        except requests.exceptions.RequestException:
                            r_first = None
                        # Prefer success (2xx/3xx) if available
                        if r_first is not None and getattr(r_first, 'status_code', None) and r_first.status_code < 400:
                            return r_first
                        # small grace to see if the other succeeds quickly
                        other = next(iter(pending)) if pending else None
                        if other:
                            try:
                                r_other = other.result(timeout=1)
                                if r_other is not None and getattr(r_other, 'status_code', None) and r_other.status_code < 400:
                                    return r_other
                            except Exception:
                                pass
                        # fallback to first result (may be error or None)
                        return r_first
                    finally:
                        try:
                            ex.shutdown(wait=False, cancel_futures=True)
                        except Exception:
                            pass
                else:
                    RequestUtils._ensure_ga_installed()
                    order = (socket.AF_INET, socket.AF_INET6) if getattr(self, '_prefer_ipv4', True) else (socket.AF_INET6, socket.AF_INET)
                    last_exc = None
                    for fam in order:
                        try:
                            RequestUtils._tls.family = fam
                            return self._send_once(method, url, data=data, params=params, allow_redirects=allow_redirects, files=files, json=json)
                        except requests.exceptions.RequestException as e:
                            last_exc = e
                        finally:
                            RequestUtils._tls.family = None
                    if last_exc is not None:
                        raise last_exc
                    return None
            except requests.exceptions.RequestException:
                if attempt < attempts - 1:
                    delay = (self._retry_backoff_factor or 0.5) * (2 ** attempt)
                    time.sleep(delay)
                    continue
                if raise_exception:
                    raise requests.exceptions.RequestException
                return None

    def post(self, url, data=None, json=None):
        if json is None:
            json = {}
        return self._send_with_race("POST", url, data=data, json=json)

    def get(self, url, params=None):
        r = self._send_with_race("GET", url, params=params)
        if not r:
            return None
        return str(r.content, 'utf-8')

    def get_res(self, url, params=None, allow_redirects=True, raise_exception=False):
        return self._send_with_race("GET", url, params=params, allow_redirects=allow_redirects, raise_exception=raise_exception)

    def post_res(self, url, data=None, params=None, allow_redirects=True, files=None, json=None):
        return self._send_with_race("POST", url, data=data, params=params, allow_redirects=allow_redirects, files=files, json=json)

    def get_proxy(self, url):
        """
        跳过本地地址
        """
        parse_result = urlparse(url)
        host = parse_result.hostname
        if "127.0.0.1" == host or "localhost" == host:
            return None
        else:
            return self._proxies

    @staticmethod
    def cookie_parse(cookies_str, array=False):
        """
        解析cookie，转化为字典或者数组
        :param cookies_str: cookie字符串
        :param array: 是否转化为数组
        :return: 字典或者数组
        """
        if not cookies_str:
            return {}
        cookie_dict = {}
        cookies = cookies_str.split(';')
        for cookie in cookies:
            cstr = cookie.split('=')
            if len(cstr) > 1:
                cookie_dict[cstr[0].strip()] = cstr[1].strip()
        if array:
            cookiesList = []
            for cookieName, cookieValue in cookie_dict.items():
                cookies = {'name': cookieName, 'value': cookieValue}
                cookiesList.append(cookies)
            return cookiesList
        return cookie_dict

    @staticmethod
    def check_response_is_valid_json(response):
        """
        解析返回的内容是否是一段html
        """
        content_type = response.headers.get('Content-Type', '')
        return 'application/json' in content_type
