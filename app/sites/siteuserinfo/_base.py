# -*- coding: utf-8 -*-
import base64
import json
import re
from abc import ABCMeta, abstractmethod
from urllib.parse import urljoin, urlsplit

import requests
from lxml import etree

import log
from app.helper import SiteHelper, ChromeHelper
from app.helper.cloudflare_helper import under_challenge
from app.utils import RequestUtils
from app.utils.types import SiteSchema
from config import Config
import asyncio

SITE_BASE_ORDER = 1000


class _ISiteUserInfo(metaclass=ABCMeta):
    # 站点模版
    schema = SiteSchema.NexusPhp
    # 站点解析时判断顺序，值越小越先解析
    order = SITE_BASE_ORDER

    def __init__(self, site_name, url, site_cookie, site_local_storage=None, index_html=None, session=None, ua=None, emulate=False, proxy=None, chrome=None):
        super().__init__()
        # 站点信息
        self.site_name = None
        self.site_url = None
        self.site_favicon = None
        # 用户信息
        self.username = None
        self.userid = None
        # 未读消息
        self.message_unread = 0
        self.message_unread_contents = []

        # 流量信息
        self.upload = 0
        self.download = 0
        self.ratio = 0

        # 种子信息
        self.seeding = 0
        self.leeching = 0
        self.uploaded = 0
        self.completed = 0
        self.incomplete = 0
        self.seeding_size = 0
        self.leeching_size = 0
        self.uploaded_size = 0
        self.completed_size = 0
        self.incomplete_size = 0
        # 做种人数, 种子大小
        self.seeding_info = []

        # 用户详细信息
        self.user_level = None
        self.join_at = None
        self.last_seen = None
        self.bonus = 0.0

        # 错误信息
        self.err_msg = None
        # 内部数据
        self._base_url = None
        self._site_cookie = None
        self._site_local_storage = None
        self._index_html = None
        self._addition_headers = None

        # 站点页面
        self._brief_page = "index.php"
        self._user_detail_page = "userdetails.php?id="
        self._user_traffic_page = "index.php"
        self._torrent_seeding_page = "getusertorrentlistajax.php?userid="
        self._user_mail_unread_page = "messages.php?action=viewmailbox&box=1&unread=yes"
        self._sys_mail_unread_page = "messages.php?action=viewmailbox&box=-2&unread=yes"
        self._torrent_seeding_params = None
        self._torrent_seeding_headers = None

        split_url = urlsplit(url)
        self.site_name = site_name
        self.site_url = url
        self._base_url = f"{split_url.scheme}://{split_url.netloc}"
        self._favicon_url = urljoin(self._base_url, "favicon.ico")
        self.site_favicon = ""
        self._site_cookie = site_cookie
        self._site_local_storage = site_local_storage
        self._index_html = index_html
        self._session = session if session else requests.Session()
        self._ua = ua

        self._emulate = emulate
        self._proxy = proxy
        self.chrome = chrome

    def site_schema(self):
        """
        站点解析模型
        :return: 站点解析模型
        """
        return self.schema

    @classmethod
    def match(cls, html_text):
        """
        是否匹配当前解析模型
        :param html_text: 站点首页html
        :return: 是否匹配
        """
        return False

    async def parse(self):
        """
        解析站点信息
        :return:
        """
        self._parse_favicon(self._index_html)
        if not self._parse_logged_in(self._index_html):
            return

        self._parse_site_page(self._index_html)
        self._parse_user_base_info(self._index_html)
        await self._pase_unread_msgs()
        if self._user_traffic_page:
            self._parse_user_traffic_info(await self._get_page_content(urljoin(self._base_url, self._user_traffic_page)))
        if self._user_detail_page:
            self._parse_user_detail_info(await self._get_page_content(urljoin(self._base_url, self._user_detail_page)))

        await self._parse_seeding_pages()
        self.seeding_info = json.dumps(self.seeding_info)

    async def _pase_unread_msgs(self):
        """
        解析所有未读消息标题和内容
        :return:
        """
        unread_msg_links = []
        if self.message_unread > 0:
            links = {self._user_mail_unread_page, self._sys_mail_unread_page}
            for link in links:
                if not link:
                    continue

                msg_links = []
                next_page = self._parse_message_unread_links(
                    await self._get_page_content(urljoin(self._base_url, link)), msg_links)
                while next_page:
                    next_page = self._parse_message_unread_links(
                        await self._get_page_content(urljoin(self._base_url, next_page)), msg_links)

                unread_msg_links.extend(msg_links)

        for msg_link in unread_msg_links:
            log.debug(f"【Sites】{self.site_name} 信息链接 {msg_link}")
            head, date, content = self._parse_message_content(await self._get_page_content(urljoin(self._base_url, msg_link)))
            log.debug(f"【Sites】{self.site_name} 标题 {head} 时间 {date} 内容 {content}")
            self.message_unread_contents.append((head, date, content))

    async def _parse_seeding_pages(self):
        referer_url = urljoin(self._base_url, self._user_detail_page) if self._user_detail_page else self._base_url

        def _build_seeding_headers(target_url):
            if "ajax" in str(target_url).lower():
                return {
                    "Referer": referer_url,
                    "Accept-Language": "zh-CN,zh;q=0.9",
                    "X-Requested-With": "XMLHttpRequest",
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                }
            else:
                return {
                    "Referer": referer_url,
                    "Accept-Language": "zh-CN,zh;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Site": "same-origin",
                    "Sec-Fetch-User": "?1",
                    "Upgrade-Insecure-Requests": "1",
                }

        if self._torrent_seeding_page:
            first_url = urljoin(self._base_url, self._torrent_seeding_page)
            self._torrent_seeding_headers = _build_seeding_headers(first_url)
            next_page = self._parse_user_torrent_seeding_info(
                await self._get_page_content(first_url,
                                       self._torrent_seeding_params,
                                       self._torrent_seeding_headers))

            # 其他页处理
            while next_page:
                next_url = urljoin(urljoin(self._base_url, self._torrent_seeding_page), next_page)
                self._torrent_seeding_headers = _build_seeding_headers(next_url)
                next_page = self._parse_user_torrent_seeding_info(
                    await self._get_page_content(next_url,
                                           self._torrent_seeding_params,
                                           self._torrent_seeding_headers),
                    multi_page=True)

    @staticmethod
    def _prepare_html_text(html_text):
        """
        处理掉HTML中的干扰部分
        """
        return re.sub(r"#\d+", "", re.sub(r"\d+px", "", html_text))

    @abstractmethod
    def _parse_message_unread_links(self, html_text, msg_links):
        """
        获取未阅读消息链接
        :param html_text:
        :return:
        """
        pass

    def _parse_favicon(self, html_text):
        """
        解析站点favicon,返回base64 fav图标
        :param html_text:
        :return:
        """
        html = etree.HTML(html_text)
        if html:
            fav_link = html.xpath('//head/link[contains(@rel, "icon")]/@href')
            if fav_link:
                self._favicon_url = urljoin(self._base_url, fav_link[0])

        # 非关键路径：拉取站点图标，避免阻塞整体解析
        res = RequestUtils(
            cookies=self._site_cookie,
            session=self._session,
            timeout=(5, 5),
            headers=self._ua,
            proxies=Config().get_proxies() if self._proxy else None,
            retries=0,
            exception_retries=0,
            backoff_factor=0.1,
            status_forcelist=(),
            allowed_methods=frozenset(["HEAD", "GET", "OPTIONS"])
        ).get_res(url=self._favicon_url)
        if res:
            self.site_favicon = base64.b64encode(res.content).decode()

    async def _execute_javascript_url(self, js_url):
        """
        在当前浏览器页面执行 JavaScript URL 中的代码
        """
        if not self.chrome or not self.chrome._tab:
            log.warn(f"【Sites】{self.site_name} 无法执行 JavaScript URL：浏览器未打开")
            return ""
        
        js_code = re.sub(r'^javascript:\s*', '', js_url, flags=re.IGNORECASE)
        if not js_code:
            return ""
        
        try:
            await self.chrome.execute_script(js_code)
            await asyncio.sleep(2)
            try:
                await asyncio.wait_for(ChromeHelper.check_document_ready(self.chrome._tab), timeout=10)
            except asyncio.TimeoutError:
                pass
            return await self.chrome.get_html()
        except Exception as e:
            log.error(f"【Sites】{self.site_name} 执行 JavaScript 失败: {str(e)}")
            try:
                return await self.chrome.get_html()
            except Exception:
                return ""

    async def _get_page_content(self, url, params=None, headers=None):
        """
        :param url: 网页地址
        :param params: post参数
        :param headers: 额外的请求头
        :return:
        """
        # 验证URL有效性
        if not url:
            log.warn(f"【Sites】{self.site_name} 无效的URL: 空URL")
            return ""
        
        # 处理 JavaScript URL：在当前浏览器页面执行 JavaScript 代码
        if url.lower().startswith('javascript:'):
            return await self._execute_javascript_url(url)
        
        parsed_url = urlsplit(url)
        if parsed_url.scheme and parsed_url.scheme.lower() not in ('http', 'https', ''):
            log.warn(f"【Sites】{self.site_name} 跳过不支持的URL协议 '{parsed_url.scheme}': {url[:100]}")
            return ""
        
        if not parsed_url.netloc and not url.startswith('/'):
            # 相对路径应该以 / 开头，否则可能是无效URL
            if ':' in url.split('/')[0]:  # 检查是否像 "data:..." 这样的伪协议
                log.warn(f"【Sites】{self.site_name} 跳过无效的URL: {url[:100]}")
                return ""
        
        req_headers = None
        proxies = Config().get_proxies() if self._proxy else None
        if self._ua or headers or self._addition_headers:
            req_headers = {}
            if headers:
                req_headers.update(headers)

            if isinstance(self._ua, str):
                req_headers.update({
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "User-Agent": f"{self._ua}"
                })
            else:
                req_headers.update(self._ua)

            if self._addition_headers:
                req_headers.update(self._addition_headers)

        if params:
            res = RequestUtils(cookies=self._site_cookie,
                               session=self._session,
                               timeout=60,
                               proxies=proxies,
                               headers=req_headers).post_res(url=url, data=params)
        else:
            res = RequestUtils(cookies=self._site_cookie,
                               session=self._session,
                               timeout=60,
                               proxies=proxies,
                               headers=req_headers).get_res(url=url)
        if (res is None and self._emulate) or (res is not None and res.status_code in (200, 500, 403)):
            # 如果cloudflare 有防护，尝试使用浏览器仿真
            if res is None or (under_challenge(res.text) or (not SiteHelper.is_logged_in(res.text) and not SiteHelper.is_api_logged_in(res.text))):
                log.debug(f"【Sites】{self.site_name} 检测到Cloudflare或未获取到登录数据，需要浏览器仿真")
                if self.chrome:
                    chrome = self.chrome
                else:
                    self.chrome = ChromeHelper()
                    chrome = self.chrome
                if self._emulate and chrome.get_status():
                    if not await chrome.visit(url=url, ua=self._ua, cookie=self._site_cookie, local_storage=self._site_local_storage, proxy=self._proxy):
                        log.error(f"【Sites】{self.site_name} 无法打开网站")
                        return ""
                    # 循环检测是否过cf
                    cloudflare = await chrome.pass_cloudflare()
                    if not cloudflare:
                        log.error(f"【Sites】{self.site_name} 跳转站点失败")
                        return ""
                    await SiteHelper.wait_for_logged_in(chrome._tab)
                    await asyncio.sleep(1)
                    return await chrome.get_html()
                else:
                    log.warn(
                        f"【Sites】{self.site_name} 检测到Cloudflare，需要浏览器仿真，但是浏览器不可用或者未开启浏览器仿真")
                    return ""
            res.encoding = res.apparent_encoding or 'utf-8'
            try:
                if re.search(r'charset=["\']?utf-?8["\']?', res.text, re.IGNORECASE):
                    res.encoding = "UTF-8"
            except UnicodeDecodeError:
                pass
            try:
                html_text = res.content.decode(res.encoding)
            except UnicodeDecodeError:
                html_text = res.content.decode('utf-8', errors='ignore')
            return html_text

        return ""

    @abstractmethod
    def _parse_site_page(self, html_text):
        """
        解析站点相关信息页面
        :param html_text:
        :return:
        """
        pass

    @abstractmethod
    def _parse_user_base_info(self, html_text):
        """
        解析用户基础信息
        :param html_text:
        :return:
        """
        pass

    def _parse_logged_in(self, html_text):
        """
        解析用户是否已经登陆
        :param html_text:
        :return: True/False
        """
        logged_in = SiteHelper.is_logged_in(html_text)
        if not logged_in:
            self.err_msg = "未检测到已登陆，请检查cookies是否过期"
            log.warn(f"【Sites】{self.site_name} 未登录，跳过后续操作")

        return logged_in

    @abstractmethod
    def _parse_user_traffic_info(self, html_text):
        """
        解析用户的上传，下载，分享率等信息
        :param html_text:
        :return:
        """
        pass

    @abstractmethod
    def _parse_user_torrent_seeding_info(self, html_text, multi_page=False):
        """
        解析用户的做种相关信息
        :param html_text:
        :param multi_page: 是否多页数据
        :return: 下页地址
        """
        pass

    @abstractmethod
    def _parse_user_detail_info(self, html_text):
        """
        解析用户的详细信息
        加入时间/等级/魔力值等
        :param html_text:
        :return:
        """
        pass

    @abstractmethod
    def _parse_message_content(self, html_text):
        """
        解析短消息内容
        :param html_text:
        :return:  head: message, date: time, content: message content
        """
        pass
