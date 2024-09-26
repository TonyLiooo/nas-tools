# -*- coding: utf-8 -*-
from datetime import datetime
import os
import re

from lxml import etree

from app.utils import SystemUtils
from config import RMT_SUBEXT

import asyncio
from nodriver import Tab, Element

class SiteHelper:

    @classmethod
    def is_logged_in(cls, html_text):
        """
        判断站点是否已经登陆
        :param html_text:
        :return:
        """
        html = etree.HTML(html_text)
        if not html:
            return False
        # 存在明显的密码输入框，说明未登录
        if html.xpath("//input[@type='password']"):
            return False

        # 是否存在登出和用户面板等链接
        xpaths = ['//a[contains(@href, "logout")'
                  ' or contains(@data-url, "logout")'
                  ' or contains(@href, "mybonus") '
                  ' or contains(@onclick, "logout")'
                  ' or contains(@href, "usercp")]',
                  '//form[contains(@action, "logout")]']
        for xpath in xpaths:
            if html.xpath(xpath):
                return True
        user_info_div = html.xpath('//div[@class="user-info-side"]')
        if user_info_div:
            return True
        seedersList = html.xpath('//tr[td[img[@class="size"]] and td[img[@class="seeders"]] and td[img[@class="leechers"]]]')
        if seedersList:
            return True
        return False
    
    @staticmethod
    async def wait_for_logged_in(tab:Tab, timeout=30):
        """
        等待页面登录完成
        :param tab: nodriver tab对象
        :param timeout: 最大等待时间（秒）
        :return: bool
        """
        end_time = asyncio.get_event_loop().time() + timeout
        while True:
            html_text = await tab.get_content()
            if SiteHelper.is_logged_in(html_text):
                await asyncio.sleep(1)
                return True
            if asyncio.get_event_loop().time() > end_time:
                return False
            await asyncio.sleep(1)
            

    @staticmethod
    def get_url_subtitle_name(disposition, url):
        """
        从站点下载请求中获取字幕文件名
        """
        fname = re.findall(r"filename=\"?(.+)\"?", disposition or "")
        if fname:
            fname = str(fname[0].encode('ISO-8859-1').decode()).split(";")[0].strip()
            if fname.endswith('"'):
                fname = fname[:-1]
        elif url and os.path.splitext(url)[-1] in (RMT_SUBEXT + ['.zip']):
            fname = url.split("/")[-1]
        else:
            fname = str(datetime.now())
        return fname

    @staticmethod
    def transfer_subtitle(source_sub_file, media_file):
        """
        转移站点字幕
        """
        new_sub_file = "%s%s" % (os.path.splitext(media_file)[0], os.path.splitext(source_sub_file)[-1])
        if os.path.exists(new_sub_file):
            return 1
        else:
            return SystemUtils.copy(source_sub_file, new_sub_file)
