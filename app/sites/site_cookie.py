import base64
import time

from lxml import etree

import log
from app.helper import ProgressHelper, OcrHelper, SiteHelper
from app.helper import ChromeHelper
from app.sites.siteconf import SiteConf
from app.sites.sites import Sites
from app.utils import StringUtils, RequestUtils, ExceptionUtils
from app.utils.commons import singleton
from app.utils.types import ProgressKey

import asyncio

@singleton
class SiteCookie(object):
    progress = None
    sites = None
    siteconf = None
    ocrhelper = None
    captcha_code = {}

    def __init__(self):
        self.init_config()

    def init_config(self):
        self.progress = ProgressHelper()
        self.sites = Sites()
        self.siteconf = SiteConf()
        self.ocrhelper = OcrHelper()
        self.captcha_code = {}

    def set_code(self, code, value):
        """
        设置验证码的值
        """
        self.captcha_code[code] = value

    def get_code(self, code):
        """
        获取验证码的值
        """
        return self.captcha_code.get(code)
    
    def xpath_search(self, html_element, xpath_list):
        for xpath in xpath_list:
            if html_element.xpath(xpath):
                return xpath
        return None

    async def __get_site_cookie_ua(self,
                             url,
                             username,
                             password,
                             twostepcode=None,
                             ocrflag=False,
                             proxy=False,
                             ua=None):
        """
        获取站点cookie、local storage和ua
        :param url: 站点地址
        :param username: 用户名
        :param password: 密码
        :param twostepcode: 两步验证
        :param ocrflag: 是否开启OCR识别
        :param proxy: 是否使用内置代理
        :param ua: 自定义User-Agent
        :return: cookie、local storage、 ua、message
        """
        if not url or not username or not password:
            return None, None, None, "参数错误"
        # 全局锁
        chrome = ChromeHelper()
        if not chrome.get_status():
            return None, None, None, "需要浏览器内核环境才能更新站点信息"
        if not await chrome.visit(url=url, proxy=proxy, ua=ua):
            await chrome.quit()
            return None, None, None, "Chrome模拟访问失败"
        # 循环检测是否过cf
        cloudflare = await chrome.pass_cloudflare()
        if not cloudflare:
            await chrome.quit()
            return None, None, None, "跳转站点失败，无法通过Cloudflare验证"
        await chrome._tab
        # 登录页面代码
        try:
            await asyncio.wait_for(chrome.check_document_ready(chrome._tab), 30)
        except:
            pass
        await asyncio.sleep(3)
        html_text = await chrome.get_html()
        if not html_text:
            await chrome.quit()
            return None, None, None, "获取源码失败"
        if SiteHelper.is_logged_in(html_text):
            cookies, ua = await chrome.get_cookies(), await chrome.get_ua()
            local_storage = await chrome.get_local_storage()
            await chrome.quit()
            return cookies, local_storage, ua, "已经登录过且Cookie未失效"
        # 站点配置
        login_conf = self.siteconf.get_login_conf()
        end_time = time.monotonic() + 20

        while time.monotonic() < end_time:
            html_text = await chrome.get_html()
            html = etree.HTML(html_text)
            username_xpath = self.xpath_search(html, login_conf.get("username"))
            password_xpath = self.xpath_search(html, login_conf.get("password"))
            submit_xpath = self.xpath_search(html, login_conf.get("submit"))
            if username_xpath and password_xpath and submit_xpath:
                break
            await asyncio.sleep(1)

        # 查找用户名输入框
        if not username_xpath:
            await chrome.quit()
            return None, None, None, "未找到用户名输入框"
        # 查找密码输入框
        if not password_xpath:
            await chrome.quit()
            return None, None, None, "未找到密码输入框"
        # 查找两步验证码
        twostepcode_xpath = self.xpath_search(html, login_conf.get("twostep"))
        # 查找验证码输入框
        captcha_xpath = self.xpath_search(html, login_conf.get("captcha"))
        # 查找验证码图片
        captcha_img_url = None
        if captcha_xpath:
            for xpath in login_conf.get("captcha_img"):
                if html.xpath(xpath):
                    captcha_img_url = html.xpath(xpath)[0]
                    break
            if not captcha_img_url:
                await chrome.quit()
                return None, None, None, "未找到验证码图片"
        # 查找登录按钮
        if not submit_xpath:
            await chrome.quit()
            return None, None, None, "未找到登录按钮"
        # 点击登录按钮
        try:
            submit_obj = await chrome.element_to_be_clickable(submit_xpath, timeout=6)
            if submit_obj:
                # 输入用户名
                username_element = await chrome._tab.find(username_xpath)
                await username_element.send_keys(username)
                # 输入密码
                password_element = await chrome._tab.find(password_xpath)
                await password_element.send_keys(password)
                # 输入两步验证码
                if twostepcode and twostepcode_xpath:
                    twostepcode_element = await chrome.element_to_be_clickable(twostepcode_xpath, timeout=6)
                    if twostepcode_element:
                        await twostepcode_element.send_keys(twostepcode)
                # 识别验证码
                if captcha_xpath:
                    captcha_element = await chrome.element_to_be_clickable(captcha_xpath, timeout=6)
                    if captcha_element:
                        code_url = self.__get_captcha_url(url, captcha_img_url)
                        if ocrflag:
                            # 自动OCR识别验证码
                            captcha = await self.get_captcha_text(chrome, code_url)
                            if captcha:
                                log.info("【Sites】验证码地址为：%s，识别结果：%s" % (code_url, captcha))
                            else:
                                await chrome.quit()
                                return None, None, None, "验证码识别失败"
                        else:
                            # 等待用户输入
                            captcha = None
                            code_bin = None
                            code_key = StringUtils.generate_random_str(5)
                            for sec in range(60, 0, -1):
                                if self.get_code(code_key):
                                    # 用户输入了
                                    captcha = self.get_code(code_key)
                                    log.info("【Sites】接收到验证码：%s" % captcha)
                                    self.progress.update(ptype=ProgressKey.SiteCookie,
                                                         text="接收到验证码：%s" % captcha)
                                    break
                                else:
                                    # 获取验证码图片base64
                                    if not code_bin:
                                        code_bin = await self.get_captcha_base64(chrome, code_url)
                                        if not code_bin:
                                            await chrome.quit()
                                            return None, None, None, "获取验证码图片数据失败"
                                    else:
                                        code_bin = f"data:image/png;base64,{code_bin}"
                                    # 推送到前端
                                    self.progress.update(ptype=ProgressKey.SiteCookie,
                                                         text=f"{code_bin}|{code_key}")
                                    time.sleep(1)
                            if not captcha:
                                await chrome.quit()
                                return None, None, None, "验证码输入超时"
                        # 输入验证码
                        await captcha_element.send_keys(captcha)
                    else:
                        # 不可见元素不处理
                        pass
                # 提交登录
                await submit_obj.mouse_move()
                await submit_obj.mouse_click()
                # 等待页面刷新完毕
                await chrome.element_not_to_be_clickable(submit_xpath, timeout=6)
                await chrome._tab
                try:
                    await asyncio.wait_for(chrome.check_document_ready(chrome._tab), 20)
                except:
                    pass
            else:
                await chrome.quit()
                return None, None, None, "未找到登录按钮"
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            return None, None, None, "仿真登录失败：%s" % str(e)
        logged_in = await SiteHelper.wait_for_logged_in(chrome._tab)
        if logged_in:
            cookies, ua = await chrome.get_cookies(), await chrome.get_ua()
            local_storage = await chrome.get_local_storage()
            await chrome.quit()
            return cookies, local_storage, ua, ""
        else:
            if url.find("m-team") != -1:
                html_text = await chrome.get_html()
                if "郵箱驗證碼" in html_text:
                    await asyncio.sleep(5)
                    # email handler
                    email_xpath = '//input[@id="email"]'
                    email_send_xpath = '//div[@id="code"]/button'
                    code_xpath = '//div[@id="code"]/input'
                    login_submit_xpath = '//button[@type="submit"]'

                    # get user input email
                    email = None
                    code_key = StringUtils.generate_random_str(5)
                    for sec in range(60, 0, -1):
                        if self.get_code(code_key):
                            # 用户输入了
                            email = self.get_code(code_key)
                            log.info("【Sites】接收到 email：%s" % email)
                            self.progress.update(ptype=ProgressKey.SiteCookie,
                                                 text="接收到 email：%s" % email)
                            break
                        else:
                            # get email
                            code_bin = f"data:email"
                            # 推送到前端
                            self.progress.update(ptype=ProgressKey.SiteCookie,
                                                 text=f"{code_bin}|{code_key}")
                            await asyncio.sleep(1)
                    if not email:
                        await chrome.quit()
                        return None, None, None, "email 输入超时"
                    email_element = await chrome._tab.find(email_xpath)
                    await email_element.send_keys(email)
                    await asyncio.sleep(1)
                    # click send email
                    email_send_obj = await chrome.element_to_be_clickable(email_send_xpath, timeout=10)
                    if email_send_obj:
                        await email_send_obj.mouse_move()
                        await email_send_obj.mouse_click()
                    await asyncio.sleep(1)
                    # get user input code
                    email_verify_code = None
                    code_key = StringUtils.generate_random_str(5)
                    for sec in range(60, 0, -1):
                        if self.get_code(code_key):
                            # 用户输入了
                            email_verify_code = self.get_code(code_key)
                            log.info("【Sites】接收到邮箱验证码：%s" % email_verify_code)
                            self.progress.update(ptype=ProgressKey.SiteCookie,
                                                 text="接收到邮箱验证码：%s" % email_verify_code)
                            break
                        else:
                            code_bin = f"data:email_verify_code"
                            # 推送到前端
                            self.progress.update(ptype=ProgressKey.SiteCookie,
                                                 text=f"{code_bin}|{code_key}")
                            await asyncio.sleep(1)
                    if not email_verify_code:
                        await chrome.quit()
                        return None, None, None, "email 验证码输入超时"
                    email_verify_element = await chrome._tab.find(code_xpath)
                    await email_verify_element.send_keys(email_verify_code)

                    # submit again try refresh, check again
                    login_submit_obj = await chrome.element_to_be_clickable(login_submit_xpath, timeout=10)
                    if login_submit_obj:
                        await login_submit_obj.mouse_move()
                        await login_submit_obj.mouse_click()
                        # 等待页面刷新完毕
                        await chrome.element_not_to_be_clickable(login_submit_xpath, timeout=20)

                    # check again
                    logged_in = await SiteHelper.wait_for_logged_in(chrome._tab)
                    if logged_in:
                        cookies, ua = await chrome.get_cookies(), await chrome.get_ua()
                        local_storage = await chrome.get_local_storage()
                        await chrome.quit()
                        return cookies, local_storage, ua, ""
            await chrome.quit()
            # 读取错误信息
            error_xpath = None
            for xpath in login_conf.get("error"):
                if html.xpath(xpath):
                    error_xpath = xpath
                    break
            if not error_xpath:
                return None, None, None, "登录失败"
            else:
                error_msg = html.xpath(error_xpath)[0]
                return None, None, None, error_msg

    async def get_captcha_text(self, chrome, code_url):
        """
        识别验证码图片的内容
        """
        code_b64 = await self.get_captcha_base64(chrome=chrome,
                                           image_url=code_url)
        if not code_b64:
            return ""
        return self.ocrhelper.get_captcha_text(image_b64=code_b64)

    @staticmethod
    def __get_captcha_url(siteurl, imageurl):
        """
        获取验证码图片的URL
        """
        if not siteurl or not imageurl:
            return ""
        if imageurl.startswith("/"):
            imageurl = imageurl[1:]
        return "%s/%s" % (StringUtils.get_base_url(siteurl), imageurl)

    async def update_sites_cookie_ua(self,
                               username,
                               password,
                               twostepcode=None,
                               siteid=None,
                               ocrflag=False):
        """
        更新所有站点Cookie和ua
        """
        # 获取站点列表
        sites = self.sites.get_sites(siteid=siteid)
        if siteid:
            sites = [sites]
        # 总数量
        site_num = len(sites)
        # 当前数量
        curr_num = 0
        # 返回码、返回消息
        retcode = 0
        messages = []
        # 开始进度
        self.progress.start(ProgressKey.SiteCookie)
        for site in sites:
            if not site.get("signurl") and not site.get("rssurl"):
                log.info("【Sites】%s 未设置地址，跳过" % site.get("name"))
                continue
            log.info("【Sites】开始更新 %s Cookie、Local Storage和User-Agent ..." % site.get("name"))
            self.progress.update(ptype=ProgressKey.SiteCookie,
                                 text="开始更新 %s Cookie、Local Storage和User-Agent ..." % site.get("name"))
            # 登录页面地址
            baisc_url = StringUtils.get_base_url(site.get("signurl") or site.get("rssurl"))
            site_conf = self.siteconf.get_grap_conf(url=baisc_url)
            if site_conf.get("LOGIN"):
                login_url = "%s/%s" % (baisc_url, site_conf.get("LOGIN"))
            else:
                login_url = "%s/login.php" % baisc_url
            ua = site.get("ua", None)
            # 获取Cookie和User-Agent
            cookie, local_storage, ua, msg = await self.__get_site_cookie_ua(url=login_url,
                                                        username=username,
                                                        password=password,
                                                        twostepcode=twostepcode,
                                                        ocrflag=ocrflag,
                                                        proxy=site.get("proxy"),
                                                        ua=ua)
            # 更新进度
            curr_num += 1
            if not cookie and not local_storage:
                log.error("【Sites】获取 %s 信息失败：%s" % (site.get("name"), msg))
                messages.append("%s %s" % (site.get("name"), msg))
                self.progress.update(ptype=ProgressKey.SiteCookie,
                                     value=round(100 * (curr_num / site_num)),
                                     text="%s %s" % (site.get("name"), msg))
                retcode = 1
            else:
                self.sites.update_site_cookie(siteid=site.get("id"), cookie=cookie, ua=ua)
                log.info("【Sites】更新 %s 的Cookie和User-Agent成功" % site.get("name"))
                messages.append("%s %s" % (site.get("name"), msg or "更新Cookie和User-Agent成功"))
                self.progress.update(ptype=ProgressKey.SiteCookie,
                                     value=round(100 * (curr_num / site_num)),
                                     text="%s %s" % (site.get("name"), msg or "更新Cookie和User-Agent成功"))
                if local_storage:
                    self.sites.update_site_local_storage(siteid=site.get("id"), local_storage=local_storage)
                    log.info("【Sites】更新 %s 的Local Storage成功" % site.get("name"))
                    messages.append("%s %s" % (site.get("name"), msg or "更新Local Storage成功"))
                    self.progress.update(ptype=ProgressKey.SiteCookie,
                                        value=round(100 * (curr_num / site_num)),
                                        text="%s %s" % (site.get("name"), msg or "更新Local Storage成功"))
        self.progress.end(ProgressKey.SiteCookie)
        return retcode, messages

    @staticmethod
    async def get_captcha_base64(chrome, image_url):
        """
        根据图片地址，使用浏览器获取验证码图片base64编码
        """
        if not image_url:
            return ""
        cookies = await chrome.get_cookies()
        if not cookies:
            cookies = None
        ret = RequestUtils(headers=await chrome.get_ua(),
                           cookies=cookies).get_res(image_url)
        if ret:
            return base64.b64encode(ret.content).decode()
        return ""
