import requests

import log
from urllib.parse import quote, urljoin
from app.helper import ChromeHelper
from app.utils import StringUtils, MteamUtils
from config import Config
import asyncio

from bs4 import BeautifulSoup

class MTeamSpider(object):
    _appid = "nastool"
    _req = None
    _token = None
    _api_url = "%s/api/torrent/search"
    _pageurl = "%sdetail/%s"

    def __init__(self, indexer):
        self._indexer = indexer
        if indexer:
            self._indexerid = indexer.id
            self._domain = indexer.domain
            self._name = indexer.name
            if indexer.proxy:
                self._proxy = Config().get_proxies()
            self._cookie = indexer.cookie
            self._ua = indexer.ua
        self._api_url = self._api_url % MteamUtils.get_api_url(self._domain)
        self.init_config()

    def init_config(self):
        session = requests.session()
        self._req = MteamUtils.buildRequestUtils(proxies=Config().get_proxies(), session=session, content_type="application/json",
            accept_type="application/json", api_key=MteamUtils.get_api_key(self._domain), headers=self._ua, timeout=10)

    def get_discount(self, discount):
        if discount == "PERCENT_50":
            return 1.0, 0.5
        elif discount == "NORMAL":
            return 1.0, 1.0
        elif discount == "PERCENT_70":
            return 1.0, 0.7
        elif discount == "FREE":
            return 1.0, 0.0
        elif discount == "_2X_FREE":
            return 2.0, 0.0
        elif discount == "_2X":
            return 2.0, 1.0
        elif discount == "_2X_PERCENT_50":
            return 2.0, 0.5

    def inner_search(self, keyword, page=None):
        if page:
            page = int(page) + 1
        else:
            page = 1

        param = {
            "categories":[],
            "keyword": keyword,
            "mode":"normal",
            "pageNumber": page,
            "pageSize":100,
            "visible":1
        }
        # if imdb_id:
        #     params['search_imdb'] = imdb_id
        # else:
        #     params['search_string'] = keyword
        res = self._req.post_res(url=self._api_url, json=param)
        torrents = []
        if res and res.status_code == 200:
            results = res.json().get('data') or {}
            # TODO 遍历多个页面获取数据
            totalPages = results.get("totalPages")
            total = results.get("total")
            curData = results.get('data') or []

            for result in curData:
                status = result.get("status")
                up_discount, down_discount = self.get_discount(status.get('discount'))
                torrent = {'indexer': self._indexerid,
                           'title': result.get('name'),
                           'description': result.get('smallDescr'),
                           # enlosure 给 pageurl，后续下载种子的时候，从接口中解析，这里只是为了跳过中间的检验流程
                           'enclosure': self._pageurl % (self._domain, result.get('id')),
                           'size': result.get('size'),
                           'seeders': status.get('seeders'),
                           'peers': status.get('leechers'),
                           # 'freeleech': result.get('discount'),
                           'downloadvolumefactor': down_discount,
                           'uploadvolumefactor': up_discount,
                           'page_url': self._pageurl % (self._domain, result.get('id')),
                           'imdbid': result.get('episode_info').get('imdb') if result.get('episode_info') else ''}
                torrents.append(torrent)
        elif res is not None:
            log.warn(f"【INDEXER】{self._name} 搜索失败，错误码：{res.status_code}")
            return True, []
        else:
            log.warn(f"【INDEXER】{self._name} 搜索失败，无法连接 torrentapi.org")
            return True, []
        return False, torrents

    async def browser_search(self, keyword, page=None, mtype=None):
        """
        开始搜索
        :param: keyword: 搜索关键字
        :param: indexer: 站点配置
        :param: page: 页码
        :param: mtype: 类型
        :return: (是否发生错误，种子列表)
        """
        if not keyword:
            keyword = ""
        if isinstance(keyword, list):
            keyword = " ".join(keyword)
        chrome = ChromeHelper()
        if not chrome.get_status():
            return True, []
        # 请求路径
        torrentspath = r'browse?keyword={keyword}'
        search_url = urljoin(self._indexer.domain, torrentspath.replace("{keyword}", quote(keyword)))
        # 使用浏览器获取HTML文本
        if not await chrome.visit(url=search_url,
                            local_storage=self._indexer.local_storage,
                            ua=self._indexer.ua,
                            proxy=self._indexer.proxy):
            return True, []
        cloudflare = await chrome.pass_cloudflare()
        if not cloudflare:
            return True, []
        # 等待页面加载完成
        try:
            await asyncio.wait_for(chrome.check_document_ready(chrome._tab), 30)
        except:
            pass
        torrents = []
        while True:
            await chrome.wait_until_element_state(tab=chrome._tab,text="//div[@id='float-btns']//button//span[@role='img' and contains(@class, 'anticon-loading') and @aria-label='loading']", should_appear=False, timeout=20)
            # 获取HTML文本
            html_text = await chrome.get_html()
            if not html_text:
                return True, torrents
            soup = BeautifulSoup(html_text, 'lxml')
            tbody = soup.find('tbody', class_='bg-[#bccad6]')
            if tbody:
                # Find all rows in the table body
                rows = tbody.find_all('tr')
            else:
                rows = soup.find_all('tr')
            if rows:
                # Extract data from each row
                for row in rows:
                    cells = row.find_all('td')
                    if len(cells) == 7:
                        imdb_link = row.find('a', href=True, text=lambda x: x and 'imdb' in x.lower())
                        imdb_id = ''
                        if imdb_link and 'imdb.com/title/' in imdb_link['href']:
                            imdb_id = imdb_link['href'].split('/title/')[1].split('/')[0]
                        discount_tag = cells[1].find('span', {'class': 'ant-tag'})
                        down_discount = 1.0
                        if discount_tag:
                            discount_text = discount_tag.get_text(strip=True)
                            if discount_text == 'free':
                                down_discount = 0.0
                            elif '%' in discount_text:
                                down_discount = float(discount_text.replace('%', '')) / 100.0
                        torrent = {
                            'indexer': self._indexerid,
                            'title': cells[1].find('strong').get_text(strip=True),
                            'description': cells[1].find('span', {'class': 'ant-typography'}).get_text(strip=True),
                            'enclosure': urljoin(self._indexer.domain, cells[1].find('a')['href']),
                            'size': StringUtils.num_filesize(cells[4].get_text(strip=True)),
                            'seeders': cells[5].get_text(strip=True),
                            'peers': cells[6].get_text(strip=True),
                            'downloadvolumefactor': down_discount,
                            'uploadvolumefactor': 1.0,
                            'page_url': urljoin(self._indexer.domain, cells[1].find('a')['href']),
                            'imdbid': imdb_id
                        }
                        torrents.append(torrent)

            pagination_next = soup.find('li', class_='ant-pagination-next')
            next_obj = await chrome._tab.find('//li[@title="下一頁" and contains(@class, "ant-pagination-next")]/button')
            # Extract the aria-disabled attribute
            if pagination_next and pagination_next.get('aria-disabled', 'false')=='false' and next_obj:
                await next_obj.click()
                await chrome._tab.sleep(0.5)
            else:
                break

        return False, torrents
    
    def search(self, keyword, page=None):
        error_flag = True
        result_array = []
        if not keyword:
            return True, []
        if self._indexer.api_key:
            error_flag, result_array = self.inner_search(keyword, page)
        if not result_array and self._indexer.local_storage:
            error_flag, result_array = asyncio.run(self.browser_search(keyword, page))
        return error_flag, result_array
        
