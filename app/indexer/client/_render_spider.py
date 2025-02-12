# coding: utf-8
import copy
import time
from urllib.parse import quote

from pyquery import PyQuery

from app.helper import ChromeHelper
from app.indexer.client._spider import TorrentSpider
from app.utils import ExceptionUtils
from config import Config

import asyncio

class RenderSpider(object):
    torrentspider = None
    torrents_info_array = []
    result_num = 100

    def __init__(self, indexer):
        self.torrentspider = TorrentSpider()
        self._indexer = indexer
        self.init_config()

    def init_config(self):
        self.torrents_info_array = []
        self.result_num = Config().get_config('pt').get('site_search_result_num') or 100

    async def search(self, keyword, page=None, mtype=None):
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
        torrentspath = self._indexer.search_config.get('paths', [{}])[0].get('path', '') or ''
        search_url = self._indexer.domain + torrentspath.replace("{keyword}", quote(keyword))
        # 请求方式，支持GET和浏览仿真
        method = self._indexer.search_config.get('paths', [{}])[0].get('method', '')
        if method == "chrome":
            # 请求参数
            params = self._indexer.search_config.get('paths', [{}])[0].get('params', {})
            # 搜索框
            search_input = params.get('keyword')
            # 搜索按钮
            search_button = params.get('submit')
            # 预执行脚本
            pre_script = params.get('script')
            # referer
            if params.get('referer'):
                referer = self._indexer.domain + params.get('referer').replace('{keyword}', quote(keyword))
            else:
                referer = self._indexer.domain
            if not search_input or not search_button:
                return True, []
            # 使用浏览器打开页面
            if not await chrome.visit(url=search_url,
                                cookie=self._indexer.cookie,
                                local_storage=self._indexer.local_storage,
                                ua=self._indexer.ua,
                                proxy=self._indexer.proxy):
                await chrome.quit()
                return True, []
            cloudflare = await chrome.pass_cloudflare()
            if not cloudflare:
                await chrome.quit()
                return True, []
            # 模拟搜索操作
            try:
                # 执行脚本
                if pre_script:
                    await chrome.execute_script(pre_script)
                # 等待可点击
                submit_obj = await chrome.element_to_be_clickable(selector=search_button, timeout=10)
                if submit_obj:
                    # 输入用户名
                    search_input_element = await chrome._tab.find(search_input)
                    await search_input_element.send_keys(keyword)
                    # 提交搜索
                    await submit_obj.mouse_move()
                    await submit_obj.mouse_click()
                else:
                    await chrome.quit()
                    return True, []
            except Exception as e:
                ExceptionUtils.exception_traceback(e)
                await chrome.quit()
                return True, []
        else:
            # referer
            referer = self._indexer.domain
            # 使用浏览器获取HTML文本
            if not await chrome.visit(url=search_url,
                                cookie=self._indexer.cookie,
                                local_storage=self._indexer.local_storage,
                                ua=self._indexer.ua,
                                proxy=self._indexer.proxy):
                await chrome.quit()
                return True, []
            cloudflare = await chrome.pass_cloudflare()
            if not cloudflare:
                await chrome.quit()
                return True, []
        # 等待页面加载完成
        try:
            await asyncio.wait_for(chrome.check_document_ready(chrome._tab), 30)
        except:
            pass
        # 获取HTML文本
        html_text = await chrome.get_html()
        if not html_text:
            await chrome.quit()
            return True, []
        # 重新获取Cookie和UA
        self._indexer.cookie = await chrome.get_cookies()
        self._indexer.ua = await chrome.get_ua()
        # 设置抓虫参数
        self.torrentspider.setparam(keyword=keyword,
                                    indexer=self._indexer,
                                    referer=referer,
                                    page=page,
                                    mtype=mtype)
        # 种子筛选器
        torrents_selector = self._indexer.torrents.get('list', {}).get('selector', '')
        if not torrents_selector:
            await chrome.quit()
            return False, []
        # 解析HTML文本
        html_doc = PyQuery(html_text)
        for torn in html_doc(torrents_selector):
            self.torrents_info_array.append(copy.deepcopy(self.torrentspider.Getinfo(PyQuery(torn))))
            if len(self.torrents_info_array) >= int(self.result_num):
                break
        await chrome.quit()
        return False, self.torrents_info_array
