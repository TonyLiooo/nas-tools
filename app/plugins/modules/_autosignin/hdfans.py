from app.helper import ChromeHelper, SiteHelper
from app.helper.cloudflare_helper import under_challenge
from app.plugins.modules._autosignin._base import _ISiteSigninHandler
from app.utils import StringUtils, RequestUtils
from config import Config
import asyncio

class HDFans(_ISiteSigninHandler):
    """
    hdfans签到
    """
    
    # 匹配的站点Url，每一个实现类都需要设置为自己的站点Url
    site_url = "hdfans.org"

    # 签到成功
    _success_text = "签到成功"
    _sign_text = "签到已得"
    _repeat_text = "请不要重复签到哦"

    @classmethod
    def match(cls, url):
        """
        根据站点Url判断是否匹配当前站点签到类，大部分情况使用默认实现即可
        :param url: 站点Url
        :return: 是否匹配，如匹配则会调用该类的signin方法
        """
        return True if StringUtils.url_equal(url, cls.site_url) else False

    async def signin(self, site_info: dict):
        """
        执行签到操作
        :param site_info: 站点信息，含有站点Url、站点Cookie、UA等信息
        :return: 签到结果信息
        """
        site = site_info.get("name")
        site_cookie = site_info.get("cookie")
        ua = site_info.get("ua")
        proxy = Config().get_proxies() if site_info.get("proxy") else None

        chrome = ChromeHelper()
        if site_info.get("chrome") and chrome.get_status():
            self.info(f"{site} 开始仿真签到")
            msg, html_text = await self.__chrome_visit(chrome=chrome,
                                                 url="https://hdfans.org",
                                                 ua=ua,
                                                 site_cookie=site_cookie,
                                                 proxy=proxy,
                                                 site=site)
            # 仿真访问失败
            if msg:
                await chrome.quit()
                return False, msg

            # 已签到
            if self._sign_text in html_text:
                await chrome.quit()
                self.info(f"今日已签到")
                return True, f'【{site}】今日已签到'

            # 仿真签到
            msg, html_text = await self.__chrome_visit(chrome=chrome,
                                                 url="https://hdfans.org/attendance.php",
                                                 ua=ua,
                                                 site_cookie=site_cookie,
                                                 proxy=proxy,
                                                 site=site)
            await chrome.quit()
            if msg:
                return False, msg

            # 签到成功
            if self._success_text in html_text:
                self.info(f"签到成功")
                return True, f'【{site}】签到成功'
            
            self.error(f"签到失败，签到接口返回 {html_text}")
            return False, f'【{site}】签到失败'
        else:
            self.info(f"{site} 开始签到")
            # 获取页面html
            html_res = RequestUtils(cookies=site_cookie,
                                    headers=ua,
                                    proxies=proxy
                                    ).get_res(url="https://hdfans.org/attendance.php")
            if not html_res or html_res.status_code != 200:
                self.error(f"签到失败，请检查站点连通性")
                return False, f'【{site}】签到失败，请检查站点连通性'

            if "login.php" in html_res.text:
                self.error(f"签到失败，cookie失效")
                return False, f'【{site}】签到失败，cookie失效'

            # 判断是否已签到
            # '已连续签到278天，此次签到您获得了100魔力值奖励!'
            if self._success_text in html_res.text:
                self.info(f"签到成功")
                return True, f'【{site}】签到成功'
            if self._repeat_text in html_res.text:
                self.info(f"今日已签到")
                return True, f'【{site}】今日已签到'
            self.error(f"签到失败，签到接口返回 {html_res.text}")
            return False, f'【{site}】签到失败'

    async def __chrome_visit(self, chrome:ChromeHelper, url, ua, site_cookie, proxy, site):
        if not await chrome.visit(url=url, ua=ua, cookie=site_cookie,
                            proxy=proxy):
            self.warn("%s 无法打开网站" % site)
            return f"【{site}】仿真签到失败，无法打开网站！", None
        # 检测是否过cf
        await asyncio.sleep(3)
        if under_challenge(await chrome.get_html()):
            # 循环检测是否过cf
            cloudflare = await chrome.pass_cloudflare()
            if not cloudflare:
                self.warn("%s 跳转站点失败" % site)
                return f"【{site}】仿真签到失败，跳转站点失败！", None
        logged_in = await SiteHelper.wait_for_logged_in(chrome._tab)
        if not logged_in:
            self.warn("%s 站点未登录" % site)
            return f"【{site}】仿真签到失败，站点未登录！", None
        # 获取html
        html_text = await chrome.get_html()
        if not html_text:
            self.warn("%s 获取站点源码失败" % site)
            return f"【{site}】仿真签到失败，获取站点源码失败！", None

        # 站点访问正常，返回html
        return None, html_text
