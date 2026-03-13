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

    _CHROME_SIGNIN_TIMEOUT = 300

    async def __signin_base(self, site_info):
        """
        通用签到处理
        :param site_info: 站点信息
        :return: 签到结果信息
        """
        if not site_info:
            return ""
        site = site_info.get("name")
        chrome = None
        try:
            site_url = site_info.get("signurl")
            site_cookie = site_info.get("cookie")
            site_local_storage = site_info.get("local_storage")
            ua = site_info.get("ua")
            if not site_url or not site_cookie:
                log.warn("【Sites】未配置 %s 的站点地址或Cookie，无法签到" % str(site))
                return ""
            chrome = ChromeHelper()
            if site_info.get("chrome") and chrome.get_status():
                log.info("【Sites】开始站点仿真签到：%s" % site)
                try:
                    result = await asyncio.wait_for(
                        self._chrome_signin(chrome, site_info, site, site_url, site_cookie, site_local_storage, ua),
                        timeout=self._CHROME_SIGNIN_TIMEOUT
                    )
                    if result is not None:
                        return result
                except asyncio.TimeoutError:
                    log.error(f"【Sites】{site} 仿真签到总超时({self._CHROME_SIGNIN_TIMEOUT}s)")
                    return f"【{site}】仿真签到超时！"
            # 模拟登录
            else:
                if site_url.find("attendance.php") != -1:
                    checkin_text = "签到"
                else:
                    checkin_text = "模拟登录"
                log.info(f"【Sites】开始站点{checkin_text}：{site}")
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
                        log.warn(f"【Sites】{site} {checkin_text}失败，{msg}")
                        return f"【{site}】{checkin_text}失败，{msg}！"
                    else:
                        log.info(f"【Sites】{site} {checkin_text}成功")
                        return f"【{site}】{checkin_text}成功"
                elif res is not None:
                    log.warn(f"【Sites】{site} {checkin_text}失败，状态码：{res.status_code}")
                    return f"【{site}】{checkin_text}失败，状态码：{res.status_code}！"
                else:
                    log.warn(f"【Sites】{site} {checkin_text}失败，无法打开网站")
                    return f"【{site}】{checkin_text}失败，无法打开网站！"
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            log.warn("【Sites】%s 签到失败：%s" % (site, str(e)))
            return f"【{site}】签到失败：{str(e)}！"
        finally:
            try:
                if chrome:
                    await chrome.quit()
            except Exception:
                pass

    async def _chrome_signin(self, chrome, site_info, site, site_url, site_cookie, site_local_storage, ua):
        home_url = StringUtils.get_base_url(site_url)
        if "1ptba" in home_url:
            home_url = f"{home_url}/index.php"
        from urllib.parse import urlparse
        site_domain = urlparse(home_url).netloc
        if not await chrome.visit(url=home_url, ua=ua, cookie=site_cookie, local_storage=site_local_storage,
                                   proxy=site_info.get("proxy"), site_domain=site_domain, preserve_data=True):
            log.warn("【Sites】%s 无法打开网站" % site)
            return f"【{site}】仿真签到失败，无法打开网站！"
        cloudflare = await chrome.pass_cloudflare()
        if not cloudflare:
            log.warn("【Sites】%s 跳转站点失败" % site)
            return f"【{site}】仿真签到失败，跳转站点失败！"
        logged_in = await SiteHelper.wait_for_logged_in(chrome._tab, timeout=15)
        html_text = await chrome.get_html()
        if not html_text:
            log.warn("【Sites】%s 获取站点源码失败" % site)
            return f"【{site}】仿真签到失败，获取站点源码失败！"
        if not logged_in and not SiteHelper.is_logged_in(html_text):
            log.warn("【Sites】%s 站点未登录" % site)
            return f"【{site}】仿真签到失败，站点未登录！"
        html = etree.HTML(html_text)
        xpath_str = None
        for xpath in self.siteconf.get_checkin_conf():
            if html.xpath(xpath):
                xpath_str = xpath
                break
        if re.search(r'已签|签到已得', html_text, re.IGNORECASE):
            log.info("【Sites】%s 今日已签到" % site)
            return f"【{site}】今日已签到"
        if not xpath_str:
            if SiteHelper.is_logged_in(html_text):
                log.warn("【Sites】%s 未找到签到按钮，模拟登录成功" % site)
                return f"【{site}】模拟登录成功，已签到或无需签到"
            else:
                log.info("【Sites】%s 未找到签到按钮，且模拟登录失败" % site)
                return f"【{site}】模拟登录失败！"
        checkin_obj = await chrome._tab.find(text=xpath_str, timeout=6)
        if checkin_obj:
            await checkin_obj.mouse_move()
            await checkin_obj.mouse_click()
            await asyncio.sleep(3)
            if under_challenge(await chrome.get_html()):
                cloudflare = await chrome.pass_cloudflare()
                if not cloudflare:
                    log.info("【Sites】%s 仿真签到失败，无法通过Cloudflare" % site)
                    return f"【{site}】仿真签到失败，无法通过Cloudflare！"
            if re.search(r'已签|签到已得', await chrome.get_html(), re.IGNORECASE):
                return f"【{site}】签到成功"
            log.info("【Sites】%s 仿真签到成功" % site)
            return f"【{site}】仿真签到成功"
        return None