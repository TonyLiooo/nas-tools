# -*- coding: utf-8 -*-
import json
import re
import asyncio
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, wait, FIRST_COMPLETED, as_completed
from abc import ABC
from urllib.parse import urljoin, urlsplit

from lxml import etree

import log
from app.sites.siteuserinfo._base import _ISiteUserInfo, SITE_BASE_ORDER
from app.utils import StringUtils, MteamUtils
from config import Config
from app.utils.exception_utils import ExceptionUtils
from app.utils.types import SiteSchema

from app.helper import SiteHelper, ChromeHelper
from bs4 import BeautifulSoup

class MteamSiteUserInfo(_ISiteUserInfo):

    _roleToLevelMap = {
        '1': 'User',
        '2': 'Power User',
        '3': 'Elite User',
        '4': 'Crazy User',
        '5': 'Insane User',
        '6': 'Veteran User',
        '7': 'Extreme User',
        '8': 'Ultimate User',
        '9': 'Nexus Master',
        '10': 'VIP',
        '17': 'Offer memberStaff',
        '18': 'bet memberStaff',
        '12': '巡查',
        '11': '職人',
        '13':'總版',
        '14': '總管',
        '15': '維護開發員',
        '16': '站長',

    }

    schema = SiteSchema.Mteam
    order = SITE_BASE_ORDER

    def _parse_site_page(self, html_text):
        html_text = self._prepare_html_text(html_text)
        self._user_detail_page = None

        user_detail = re.search(r"/profile/detail/(\d+)", html_text)

        if user_detail and user_detail.group().strip():
            self._user_detail_page = user_detail.group().strip().lstrip('/')
            self.userid = user_detail.group(1)

    def _parse_user_base_info(self, html_text):
        # 合并解析，减少额外请求调用
        self._parse_user_traffic_info(html_text)

        self._parse_message_unread(html_text)

        html = etree.HTML(html_text)
        if not html:
            return

        ret = html.xpath(f'//a[contains(@href, "detail") and contains(@href, "{self.userid}")]//text()')
        if ret:
            self.username = str(ret[0])
            return

    def _parse_user_traffic_info(self, html_text):
        html_text = self._prepare_html_text(html_text)
        
        upload_match = re.search(r"上[传傳]量[:：_<>/a-zA-Z-=\"'\s#;]+[^>]+>[:：=\"'\s]?([\d,.\s]+[KMGTPI]*B)", html_text, re.IGNORECASE)
        self.upload = StringUtils.num_filesize(upload_match.group(1).strip()) if upload_match else 0

        download_match = re.search(r"下[载載]量[:：_<>/a-zA-Z-=\"'\s#;]+[^>]+>[:：=\"'\s]?([\d,.\s]+[KMGTPI]*B)", html_text, re.IGNORECASE)
        self.download = StringUtils.num_filesize(download_match.group(1).strip()) if download_match else 0
        # 计算分享率
        ratio_match = re.search(r"分享率[:：_<>/a-zA-Z-=\"'\s#;]+[^>]+>[:：=\"'\s]?([\d,.\s]+)", html_text)
        calc_ratio = 0.0 if self.download <= 0.0 else round(self.upload / self.download, 3)
        # 优先使用页面上的分享率
        self.ratio = StringUtils.str_float(ratio_match.group(1)) if (ratio_match and ratio_match.group(1).strip()) else calc_ratio

        leeching_match = re.search(r"(Torrents leeching|下载中)[^>]+>(\d+)[\s\S]+<", html_text)
        self.leeching = StringUtils.str_int(leeching_match.group(2)) if leeching_match and leeching_match.group(
            2).strip() else 0

        bonus_match = re.search(r"魔力值.*?<span[^>]*>([\d,.]+)</span>", html_text)
        if bonus_match and bonus_match.group(1).strip():
            self.bonus = StringUtils.str_float(bonus_match.group(1).strip())

    def _parse_user_torrent_seeding_info(self, html_text, multi_page=False):
        pass

    async def _parse_user_detail_info(self, html_text):
        """
        解析用户额外信息，加入时间，等级
        :param html_text:
        :return:
        """
        if not html_text:
            return
        html = etree.HTML(html_text)

        seeding_sizes = []
        seeding_seeders = []
        seeding_leechers = []

        if self.chrome and self.chrome._tab:
            try:
                await self.chrome.wait_until_element_state(tab=self.chrome._tab,text="目前做種", should_appear=True, timeout=20)
                seeding_obj = await self.chrome._tab.find('//tr/td[text()="目前做種"]/following-sibling::td/button')
                await seeding_obj.click()
                await self.chrome._tab.wait_for(text='//tbody[@class="ant-table-tbody"]/tr[not(./td//div[contains(text(), "無此資料")])]', timeout=6)

                while True:
                    await self.chrome.wait_until_element_state(tab=self.chrome._tab,text="//div[@id='float-btns']//button//span[@role='img' and contains(@class, 'anticon-loading') and @aria-label='loading']", should_appear=False, timeout=20)
                    html_text = await self.chrome.get_html()
                    html = etree.HTML(html_text)
                    soup = BeautifulSoup(html_text, 'lxml')
                    
                    tbody = None
                    modals = soup.find_all('div', class_='ant-modal-content')
                    target_modal = next((m for m in modals
                                         if (m.find('div', class_='ant-modal-title') and
                                             '目前做種' in m.find('div', class_='ant-modal-title').get_text(strip=True))), None)

                    if target_modal:
                        tbody = target_modal.select_one('div.ant-modal-body tbody.ant-table-tbody') 
                        if not tbody:
                            tbody = target_modal.select_one('table[data-extentions-extra-tablecapture-id] tbody.ant-table-tbody')

                    if tbody:
                        rows = tbody.find_all('tr')
                        for row in rows:
                            cells = row.find_all('td')

                            category = title = description = size = seeders = leechers = upload = download = completed = 'N/A'

                            if len(cells) > 0:
                                category_tag = cells[0].find('span', class_=lambda x: x and 'cat-' in x)
                                if category_tag:
                                    category = category_tag.get_text(strip=True)
                                
                                title_strong = cells[0].find('strong')
                                if title_strong:
                                    title = title_strong.get_text(strip=True)
                                
                                description_spans = cells[0].find_all('span', class_='ant-typography-ellipsis')
                                if len(description_spans) > 1:
                                    description = description_spans[-1].get_text(strip=True)

                            if len(cells) > 1:
                                size = cells[1].get_text(strip=True)

                            if len(cells) > 2:
                                activity_div = cells[2].find('div', class_='ant-space')
                                if activity_div:
                                    activity_spans = activity_div.find_all('span')
                                    number_spans = [span for span in activity_spans if span.get_text(strip=True).isdigit()]
                                    if len(number_spans) >= 2:
                                        seeders = number_spans[0].get_text(strip=True)
                                        leechers = number_spans[1].get_text(strip=True)

                            if len(cells) > 3:
                                upload = cells[3].get_text(strip=True)

                            if len(cells) > 4:
                                download = cells[4].get_text(strip=True)

                            if len(cells) > 5:
                                completed = cells[5].get_text(strip=True)

                            # Print the extracted data
                            # print(f'Category: {category}')
                            # print(f'Title: {title}')
                            # print(f'Description: {description}')
                            # print(f'Size: {size}')
                            # print(f'Seeders: {seeders}')
                            # print(f'Leechers: {leechers}')
                            # print(f'Upload: {upload}')
                            # print(f'Download: {download}')
                            # print(f'Completed: {completed}')
                            # print('---')
                            if size != 'N/A' and seeders !='N/A' and leechers!='N/A':
                                seeding_sizes.append(size)
                                seeding_seeders.append(seeders)
                                seeding_leechers.append(leechers)
                    else:
                        log.debug('No tbody element found with the class "ant-table-tbody".')

                    pagination_next = target_modal.find('li', class_='ant-pagination-next') if target_modal else None
                    next_obj = await self.chrome._tab.find('//li[@title="下一頁" and contains(@class, "ant-pagination-next")]/button')
                    if pagination_next and pagination_next.get('aria-disabled', 'false')=='false' and next_obj:
                        await next_obj.click()
                    else:
                        break
            except Exception as err:
                log.error(str(err))

        # 做种体积 & 做种数
        tmp_seeding = len(seeding_sizes)
        tmp_seeding_size = 0
        tmp_seeding_info = []
        for i in range(0, len(seeding_sizes)):
            size = StringUtils.num_filesize(seeding_sizes[i].strip())
            seeders = StringUtils.str_int(seeding_seeders[i])

            tmp_seeding_size += size
            tmp_seeding_info.append([seeders, size])

        if not self.seeding_size:
            self.seeding_size = tmp_seeding_size
        if not self.seeding:
            self.seeding = tmp_seeding
        if not self.seeding_info:
            self.seeding_info = tmp_seeding_info
        self.seeding_info = json.dumps(self.seeding_info)

        user_levels_text = html.xpath('//tr/td[text()="等級" or text()="等级"]/following-sibling::td[1]/img[1]/@title')
        if user_levels_text:
            self.user_level = user_levels_text[0].strip()

        if not self.bonus:
            bonus_text = html.xpath('//tr/td[text()="魔力值" or text()="猫粮"]/following-sibling::td[1]/text()')
            if bonus_text:
                full_text = bonus_text[0].strip()
                first_number = re.search(r'^([\d,]+\.?\d*)', full_text)
                if first_number:
                    self.bonus = StringUtils.str_float(first_number.group(1))
                else:
                    self.bonus = 0

        # 加入日期
        join_at_text = html.xpath(
            '//tr/td[text()="加入日期" or text()="注册日期" or *[text()="加入日期"]]/following-sibling::td[1]//text()'
            '|//div/b[text()="加入日期"]/../text()|//span[text()="加入日期："]/following-sibling::span[1]/text()')
        if join_at_text:
            self.join_at = StringUtils.unify_datetime_str(join_at_text[0].split(' (')[0].strip())

        # 最近动向
        last_seen_text = html.xpath(
            '//tr/td[text()="最近动向" or text()="最近動向" or text()="上次访问"]/following-sibling::td[1]//text()'
            '|//div/b[text()="最近动向"]/../text()|//span[text()="最近動向："]/following-sibling::span[1]/text()'
        )
        if last_seen_text:
            self.last_seen = StringUtils.unify_datetime_str(last_seen_text[0].split(' (')[0].strip())

    async def _parse_message_unread_links(self, html_text, msg_links):
        html = etree.HTML(html_text)
        if not html:
            return
        
        message_links = html.xpath('//a[contains(@href, "/message/read?id=") and ./following-sibling::sup]/@href')
        if message_links:
            msg_links.extend(message_links)
        
        if self.chrome and self.chrome._tab:
            pagination_next = html.xpath('//li[@title="下一頁" and contains(@class, "ant-pagination-next")]')[0]
            next_obj = await self.chrome._tab.find('//li[@title="下一頁" and contains(@class, "ant-pagination-next")]/button')
            # Extract the aria-disabled attribute
            if pagination_next and pagination_next.get('aria-disabled', 'false')=='false' and next_obj:
                await next_obj.click()
                await asyncio.sleep(0.5)
                await self._parse_message_unread_links(await self.chrome.get_html(), msg_links)

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
                await self._parse_message_unread_links(await self._get_page_content(urljoin(self._base_url, link)), unread_msg_links)

        for msg_link in unread_msg_links:
            log.debug(f"【Sites】{self.site_name} 信息链接 {msg_link}")
            head, date, content = self._parse_message_content(await self._get_page_content(urljoin(self._base_url, msg_link)))
            log.debug(f"【Sites】{self.site_name} 标题 {head} 时间 {date} 内容 {content}")
            self.message_unread_contents.append((head, date, content))

    def _parse_message_unread(self, html_text):
        """
        解析未读短消息数量
        :param html_text:
        :return:
        """
        html = etree.HTML(html_text)
        if not html:
            return
        
        self.message_unread = 0

        user_mail_label = html.xpath('//a[contains(@href, "/message/") and .//img[contains(@title, "收件箱")]]')
        if user_mail_label:
            self._user_mail_unread_page = user_mail_label[0].get('href')
        else:
            self._user_mail_unread_page = None

        sys_mail_label = html.xpath('//a[contains(@href, "/message/") and .//img[contains(@title, "系統通知")]]')
        if sys_mail_label:
            self._sys_mail_unread_page = sys_mail_label[0].get('href')
        else:
            self._sys_mail_unread_page = None

        message_labels = html.xpath('//a[contains(@href, "/message/")]//sup')
        
        for message_label in message_labels:
            message_unread = message_label.attrib.get('title')
            if message_unread:
                self.message_unread += StringUtils.str_int(message_unread)
                
    def _parse_message_content(self, html_text):
        html = etree.HTML(html_text)
        if not html:
            return None, None, None
        # 标题
        message_head_text = None
        message_head = html.xpath('//div[@class="ant-card-head-title"]//span[contains(@class, "ant-breadcrumb-link")][last()]/text()')
        if message_head:
            message_head_text = message_head[-1].strip()

        # 消息时间
        message_date_text = None
        message_date = html.xpath('//div[@class="trrdd"]//div[contains(@class, "ant-col")]//span[@title]/@title')

        if message_date:
            message_date_text = message_date[0].strip()

        # 消息内容
        message_content_text = None
        message_content = html.xpath('//div[@class="whitespace-pre-wrap mb-1"]')
        if message_content:
            message_content_text = message_content[0].xpath("string(.)").replace('<br>', '\n').strip()

        return message_head_text, message_date_text, message_content_text

    @classmethod
    def match(cls, html_text):
        """
        默认使用NexusPhp解析
        :param html_text:
        :return:
        """
        return "M-Team" in html_text

    def _post_api(self, url, json=None):
        use_proxy = bool(self._proxy)
        timeout_direct = (10, 20)
        timeout_proxy = (20, 20)
        retries_direct = 1
        retries_proxy = 1
        backoff = 0.2
        threshold = 15

        def _do_post(proxies_flag, timeout, retries, exception_retries):
            kwargs = {
                "headers": self._ua,
                "api_key": MteamUtils.get_api_key(self.site_url),
                "session": self._session,
                "proxies": proxies_flag,
                "timeout": timeout,
                "retries": retries,
                "backoff_factor": backoff,
                "status_forcelist": (408, 429, 500, 502, 503, 504),
                "exception_retries": exception_retries,
                # 禁止适配器对 POST 进行方法级重试，避免单轮多次长超时叠加
                "allowed_methods": frozenset(["HEAD", "GET", "OPTIONS"]) 
            }
            if json is not None:
                kwargs.update({
                    "content_type": "application/json",
                    "accept_type": "application/json",
                })
            res = MteamUtils.buildRequestUtils(**kwargs).post_res(url=url, json=json)
            return res

        if use_proxy:
            return _do_post(True, timeout_proxy, retries_proxy, 1)

        ex = ThreadPoolExecutor(max_workers=2)
        try:
            f_direct = ex.submit(_do_post, False, timeout_direct, retries_direct, 0)
            try:
                res = f_direct.result(timeout=threshold)
                if res is not None and getattr(res, "status_code", None) == 200:
                    return res
            except FuturesTimeoutError:
                pass

            # small optimization: skip spawning proxy branch if no system proxies configured
            if not Config().get_proxies():
                try:
                    return f_direct.result()
                except Exception:
                    return None

            f_proxy = ex.submit(_do_post, True, timeout_proxy, retries_proxy, 1)
            done, pending = wait({f_direct, f_proxy}, return_when=FIRST_COMPLETED)
            for f in done:
                try:
                    res = f.result()
                    if res is not None and getattr(res, "status_code", None) == 200:
                        return res
                except Exception:
                    pass
            for f in pending:
                try:
                    return f.result()
                except Exception:
                    return None
        finally:
            # do not wait for lingering futures; avoid blocking on slow direct after proxy wins
            try:
                ex.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass

    def _parse_logged_in(self, html_text):
        api = "%s/api/member/profile"
        api = api % MteamUtils.get_api_url(self.site_url)
        res = self._post_api(api)
        if res and res.status_code == 200:
            user_info = res.json()
            if user_info and user_info.get("data"):
                return True, "获取用户信息成功"
        elif res is not None and res.status_code:
            return False, f"获取用户信息失败：{res.status_code}"
        return False, "连接馒头失败"

    def get_user_profile(self):
        api = "%s/api/member/profile"
        api = api % MteamUtils.get_api_url(self.site_url)
        res = self._post_api(api)
        if res and res.status_code == 200:
            user_info = res.json()
            if user_info and user_info.get("data"):
                return user_info.get("data")
        return None

    def parseSeedingList(self, dataList):
        seeding_info = []
        total_size = 0
        for item in dataList:
            torrent = item.get("torrent")
            size = StringUtils.str_int(torrent.get("size"))
            total_size += size
            seeders = StringUtils.str_int(torrent.get("status").get("seeders"))
            seeding_info.append([seeders, size])

        return total_size, seeding_info

    def parse_seeding(self):
        # get first page
        all_seeding_info = []
        data = self.getSeedingPage(self.userid, 1, 200)
        if not data or not data.get("data"):
            self.seeding = 0
            self.seeding_size = 0
            self.seeding_info = json.dumps([])
            return
        cur_list_size, seeding_info = self.parseSeedingList(data.get("data"))
        totalPages = StringUtils.str_int(data.get("totalPages"))
        total = data.get("total")

        self.seeding = total
        self.seeding_size = 0
        self.seeding_size += cur_list_size
        all_seeding_info.extend(seeding_info)

        if totalPages > 1:
            page_indices = list(range(2, totalPages + 1))
            with ThreadPoolExecutor(max_workers=3) as ex:
                futures = {ex.submit(self.getSeedingPage, self.userid, idx, 200): idx for idx in page_indices}
                for f in as_completed(futures):
                    page_data = f.result()
                    if page_data and page_data.get("data"):
                        cur_list_size, seeding_info = self.parseSeedingList(page_data.get("data"))
                        self.seeding_size += cur_list_size
                        all_seeding_info.extend(seeding_info)

        self.seeding_info = json.dumps(all_seeding_info)

    def getSeedingPage(self, user_id, page_num, page_size):
        api = "%s/api/member/getUserTorrentList"
        api = api % MteamUtils.get_api_url(self.site_url)
        params = {
            "pageNumber": page_num,
            "pageSize": page_size,
            "userid": user_id,
            "type": "SEEDING"
        }
        res = self._post_api(api, json=params)

        if res and res.status_code == 200:
            result = res.json()
            if result and result.get("data"):
                return result.get("data")

        return None

    async def parse(self):
        self._parse_favicon(self._index_html)
        api_key=MteamUtils.get_api_key(self.site_url)
        if api_key:
            user_info = self.get_user_profile()
            if user_info:
                self.username = user_info.get("username")

                memerberCount = user_info.get("memberCount")
                self.upload = StringUtils.num_filesize(memerberCount.get("uploaded"))
                self.download = StringUtils.num_filesize(memerberCount.get("downloaded"))
                self.ratio = memerberCount.get("shareRate")
                self.bonus = memerberCount.get("bonus")
                self.userid = user_info.get("id")
                self.user_level = self._roleToLevelMap.get(user_info.get("role"))
                self.join_at = user_info.get("createdDate")

                memberStatus = user_info.get("memberStatus")
                self.last_seen = memberStatus.get('lastBrowse')

                self.parse_seeding()
                return
                
        if SiteHelper.is_logged_in(self._index_html):

            self._parse_site_page(self._index_html)
            self._parse_user_base_info(self._index_html)
            await self._pase_unread_msgs()
            if self._user_detail_page:
                await self._parse_user_detail_info(await self._get_page_content(urljoin(self._base_url, self._user_detail_page)))
            return
        self.seeding_info = ''    


