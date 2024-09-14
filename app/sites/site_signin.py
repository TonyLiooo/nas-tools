import re
from multiprocessing.dummy import Pool as ThreadPool

from lxml import etree
from app.helper.cloudflare_helper import under_challenge

import log
from app.helper import ChromeHelper, SubmoduleHelper, DbHelper, SiteHelper
from app.message import Message
from app.sites.siteconf import SiteConf
from app.sites.sites import Sites
from app.utils import RequestUtils, ExceptionUtils, StringUtils, MteamUtils
from app.utils.commons import singleton
from config import Config

import asyncio
import inspect


@singleton
class SiteSignin(object):
    sites = None
    dbhelper = None
    message = None
    siteconf = None

    _MAX_CONCURRENCY = 10

    def __init__(self):
        # 加载模块
        self._site_schema = SubmoduleHelper.import_submodules('app.sites.sitesignin',
                                                              filter_func=lambda _, obj: hasattr(obj, 'match'))
        log.debug(f"【Sites】加载站点签到：{self._site_schema}")
        self.init_config()

    def init_config(self):
        self.sites = Sites()
        self.dbhelper = DbHelper()
        self.message = Message()
        self.siteconf = SiteConf()

    def __build_class(self, url):
        for site_schema in self._site_schema:
            try:
                if site_schema.match(url):
                    return site_schema
            except Exception as e:
                ExceptionUtils.exception_traceback(e)
        return None

    def signin(self):
        """
        站点并发签到
        """
        sites = self.sites.get_sites(signin=True)
        if not sites:
            return

        try:
            with ThreadPool(min(len(sites), self._MAX_CONCURRENCY)) as pool:
                results = pool.map(lambda site: asyncio.run(self.__signin_site(site)), sites)

                status = [result for result in results if result]
                
                if status:
                    self.message.send_site_signin_message(status)

        except Exception as e:
            log.error(f"An error occurred: {e}")

    async def __signin_site(self, site_info):
        """
        签到一个站点
        """
        site_module = self.__build_class(site_info.get("signurl"))

        if site_module and hasattr(site_module, "signin"):
            try:
                site_instance = site_module()
                if inspect.iscoroutinefunction(site_instance.signin):
                    return await site_instance.signin(site_info)
                else:
                    return site_instance.signin(site_info)
            except Exception as e:
                return f"【{site_info.get('name')}】签到失败：{str(e)}"
        else:
            return await self.__signin_base(site_info)

    async def __signin_base(self, site_info):
        """
        通用签到处理
        :param site_info: 站点信息
        :return: 签到结果信息
        """
        if not site_info:
            return ""
        site = site_info.get("name")
        try:
            site_url = site_info.get("signurl")
            site_cookie = site_info.get("cookie")
            ua = site_info.get("ua")
            if not site_url or not site_cookie:
                self.warn("未配置 %s 的站点地址或Cookie，无法签到" % str(site))
                return ""
            chrome = ChromeHelper()
            if site_info.get("chrome") and chrome.get_status():
                # 首页
                self.info("开始站点仿真签到：%s" % site)
                home_url = StringUtils.get_base_url(site_url)
                if "1ptba" in home_url:
                    home_url = f"{home_url}/index.php"
                if not await chrome.visit(url=home_url, ua=ua, cookie=site_cookie, proxy=site_info.get("proxy")):
                    await chrome.quit()
                    self.warn("%s 无法打开网站" % site)
                    return f"【{site}】仿真签到失败，无法打开网站！"
                # 循环检测是否过cf
                cloudflare = await chrome.pass_cloudflare()
                if not cloudflare:
                    await chrome.quit()
                    self.warn("%s 跳转站点失败" % site)
                    return f"【{site}】仿真签到失败，跳转站点失败！"
                # 判断是否已签到
                html_text = await chrome.get_html()
                if not html_text:
                    await chrome.quit()
                    self.warn("%s 获取站点源码失败" % site)
                    return f"【{site}】仿真签到失败，获取站点源码失败！"
                # 查找签到按钮
                html = etree.HTML(html_text)
                xpath_str = None
                for xpath in self.siteconf.get_checkin_conf():
                    if html.xpath(xpath):
                        xpath_str = xpath
                        break
                if re.search(r'已签|签到已得', html_text, re.IGNORECASE):
                    await chrome.quit()
                    self.info("%s 今日已签到" % site)
                    return f"【{site}】今日已签到"
                if not xpath_str:
                    await chrome.quit()
                    if SiteHelper.is_logged_in(html_text):
                        self.warn("%s 未找到签到按钮，模拟登录成功" % site)
                        return f"【{site}】模拟登录成功，已签到或无需签到"
                    else:
                        self.info("%s 未找到签到按钮，且模拟登录失败" % site)
                        return f"【{site}】模拟登录失败！"
                # 开始仿真
                try:
                    checkin_obj = await chrome._tab.find(text=xpath_str, timeout=6)
                    if checkin_obj:
                        await checkin_obj.mouse_move()
                        await checkin_obj.mouse_click()
                        # 检测是否过cf
                        await chrome._tab.sleep(3)
                        if under_challenge(await chrome.get_html()):
                            cloudflare = await chrome.pass_cloudflare()
                            if not cloudflare:
                                await chrome.quit()
                                self.info("%s 仿真签到失败，无法通过Cloudflare" % site)
                                return f"【{site}】仿真签到失败，无法通过Cloudflare！"
                        # 判断是否已签到   [签到已得125, 补签卡: 0]
                        if re.search(r'已签|签到已得', await chrome.get_html(), re.IGNORECASE):
                            await chrome.quit()
                            return f"【{site}】签到成功"
                        await chrome.quit()
                        self.info("%s 仿真签到成功" % site)
                        return f"【{site}】仿真签到成功"
                except Exception as e:
                    ExceptionUtils.exception_traceback(e)
                    await chrome.quit()
                    self.warn("%s 仿真签到失败：%s" % (site, str(e)))
                    return f"【{site}】签到失败！"
            # 模拟登录
            else:
                if site_url.find("attendance.php") != -1:
                    checkin_text = "签到"
                else:
                    checkin_text = "模拟登录"
                self.info(f"开始站点{checkin_text}：{site}")
                # 访问链接
                res = RequestUtils(cookies=site_cookie,
                                   headers=ua,
                                   proxies=Config().get_proxies() if site_info.get("proxy") else None
                                   ).get_res(url=site_url)
                if res and res.status_code in [200, 500, 403]:
                    if not SiteHelper.is_logged_in(res.text):
                        if under_challenge(res.text):
                            msg = "站点被Cloudflare防护，请开启浏览器仿真"
                        elif res.status_code == 200:
                            msg = "Cookie已失效"
                        else:
                            msg = f"状态码：{res.status_code}"
                        self.warn(f"{site} {checkin_text}失败，{msg}")
                        return f"【{site}】{checkin_text}失败，{msg}！"
                    else:
                        self.info(f"{site} {checkin_text}成功")
                        return f"【{site}】{checkin_text}成功"
                elif res is not None:
                    self.warn(f"{site} {checkin_text}失败，状态码：{res.status_code}")
                    return f"【{site}】{checkin_text}失败，状态码：{res.status_code}！"
                else:
                    self.warn(f"{site} {checkin_text}失败，无法打开网站")
                    return f"【{site}】{checkin_text}失败，无法打开网站！"
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            if chrome:
                await chrome.quit()
            self.warn("%s 签到失败：%s" % (site, str(e)))
            return f"【{site}】签到失败：{str(e)}！"