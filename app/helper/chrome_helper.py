import os
import asyncio
import psutil
import re
import nodriver as nd
from nodriver import Tab
from nodriver.core.config import find_chrome_executable
from urllib.parse import urlparse

import log
import app.helper.cloudflare_helper as CloudflareHelper
from app.utils import SystemUtils, ExceptionUtils
from config import Config

import typing
import json

driver_executable_path = None


class ChromeHelper(object):
    _executable_path = None

    _chrome = None
    _tab = None
    _headless = False

    _proxy = None

    def __init__(self, headless=False):

        self._executable_path = SystemUtils.get_webdriver_path() or driver_executable_path

        if SystemUtils.is_windows() or SystemUtils.is_macos():
            self._headless = False
        elif not os.environ.get("NASTOOL_DISPLAY"):
            self._headless = True
        else:
            self._headless = headless
    
    def init_driver(self):
        if self._executable_path:
            return
        
        chrome_executable = find_chrome_executable()
        if not chrome_executable:
            return
        
        global driver_executable_path
        driver_executable_path = chrome_executable
        
        try:
            SystemUtils.chmod755(driver_executable_path)
        except Exception as err:
            ExceptionUtils.exception_traceback(err)


    @staticmethod
    def string_to_cookie_params(cookie_string, domain):
        cookie_params = []
        parts = cookie_string.split(';')
        for part in parts:
            key_value = part.strip().split('=', 1)
            if len(key_value) != 2:
                continue
            key = key_value[0].strip()
            value = key_value[1].strip()
            cookie_param = nd.cdp.network.CookieParam(name=key, value=value, path="/", domain=domain)
            cookie_params.append(cookie_param)
        return cookie_params
    
    @staticmethod
    async def wait_until_element_state(tab: Tab, text, should_appear=True, timeout=30):
        async def wait_element_disappear():
            try:
                while await tab.find(text=text, timeout=3):
                    await tab.sleep(1)
            except asyncio.TimeoutError:
                return True
        try:
            if should_appear:
                await tab.wait_for(text=text, timeout=timeout)
            else:
                await asyncio.wait_for(wait_element_disappear(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    @staticmethod
    def cdp_generator(method, params:typing.Dict[str, typing.Any]=dict()):
        cmd_dict : typing.Dict[str, typing.Any] = {"method": method, "params": params}
        cmd_json = yield cmd_dict
        return cmd_json
    
    @staticmethod
    async def describe_node(tab:Tab, node_id):
        return await tab.send(ChromeHelper.cdp_generator("DOM.describeNode", {
            "nodeId": node_id,
            # "depth": -1,
            "pierce": True
        }))
    
    @staticmethod
    async def find_element_in_node(tab:Tab, node_id, selector):
        result = await tab.send(ChromeHelper.cdp_generator("DOM.querySelector", {
            "nodeId": node_id,
            "selector": ChromeHelper.xpath_to_css(selector)
        }))
        return result
    
    @staticmethod
    async def find_all_element_in_node(tab:Tab, node_id, selector):
        results = await tab.send(ChromeHelper.cdp_generator("DOM.querySelectorAll", {
            "nodeId": node_id,
            "selector": ChromeHelper.xpath_to_css(selector)
        }))
        return results
    
    @staticmethod
    async def switch_to_frame(browser:nd.Browser, frame_id):
        iframe_tab: Tab = next(
            filter(
            lambda x: str(x.target.target_id) == str(frame_id), browser.targets
            ),
            None
        )
        return iframe_tab
    
    @staticmethod
    async def check_document_ready(tab:Tab):
        while await tab.evaluate('document.readyState') != 'complete':
            await tab.sleep(1)
        return True
    
    @staticmethod
    def xpath_to_css(xpath: str) -> str:
        """
        Convert an XPath expression to a CSS selector.
        
        Args:
            xpath (str): The XPath expression to convert.
        
        Returns:
            str: The equivalent CSS selector.
        """
    
        # Convert XPath axis and node tests to CSS selectors
        css = xpath
        
        # Convert predicate expressions (e.g., [1], [@attr='value']) to CSS attribute selectors
        css = re.sub(r'\[@([^\]]+)=["\']([^"\']+)["\']\]', r'[\1="\2"]', css)
        
        # Convert XPath predicates (e.g., [1]) to nth-child CSS selectors
        css = re.sub(r'\[(\d+)\]', r':nth-child(\1)', css)
        
        # Remove the XPath axis from the beginning of the XPath expression
        css = re.sub(r'^//', '', css)
        
        # Replace double slashes with a single slash (XPath to CSS path)
        css = re.sub(r'//', ' ', css)
        
        # Remove unnecessary leading and trailing spaces
        css = css.strip()

        # Ensure CSS selector is properly formatted
        css = re.sub(r'(\s+)', ' ', css)  # Replace multiple spaces with a single space

        # Clean up any residual syntax errors or unnecessary parts
        css = css.replace('[1]', '')

        # Replace common XPath functions and expressions
        css = re.sub(r'\[contains\(@class,["\']([^"\']+)["\']\)\]', r'.\1', css)
        css = re.sub(r'\[contains\(@id,["\']([^"\']+)["\']\)\]', r'#\1', css)
        css = re.sub(r'\[contains\(@name,["\']([^"\']+)["\']\)\]', r'[name="\1"]', css)
        css = re.sub(r'\[@id=["\']([^"\']+)["\']\]', r'#\1', css)
        css = re.sub(r'\[@class=["\']([^"\']+)["\']\]', r'.\1', css)

        return css

    async def element_to_be_clickable(self, selector, timeout=10):
        try:
            start_time = asyncio.get_event_loop().time()
            element = await self._tab.wait_for(text=selector, timeout=timeout)
            while True:
                elapsed_time = asyncio.get_event_loop().time() - start_time
                if elapsed_time > timeout:
                    raise asyncio.TimeoutError
                is_enabled = await self._tab.evaluate(f'document.querySelector(\'{self.xpath_to_css(selector)}\').disabled === false')
                if is_enabled:
                    return element
                await asyncio.sleep(0.2)
        except asyncio.TimeoutError:
            return False
    
    async def element_not_to_be_clickable(self, selector, timeout=10):
        try:
            start_time = asyncio.get_event_loop().time()
            await self._tab.wait_for(text=selector, timeout=timeout)
            while True:
                elapsed_time = asyncio.get_event_loop().time() - start_time
                if elapsed_time > timeout:
                    raise asyncio.TimeoutError
                is_disabled = await self._tab.evaluate(f'document.querySelector(\'{self.xpath_to_css(selector)}\').disabled === true')
                if is_disabled:
                    return True
                await asyncio.sleep(0.2)
        except asyncio.TimeoutError:
            return False
    
    @staticmethod
    async def find_and_click_element(tab:Tab, selector):
        async def process_node(_tab:Tab, node):    
            node_id = node['nodeId'] if 'nodeId' in node else None
            if not node_id:
                return _tab, None

            result = await ChromeHelper.find_element_in_node(_tab, node_id, selector)
            if result and result.get('nodeId'):
                return _tab, result

            if 'shadowRoots' in node:
                for shadow_root in node['shadowRoots']:
                    process_tab, result = await process_node(_tab, shadow_root)
                    if result and result.get('nodeId'):
                        return process_tab, result

            iframe_results = await ChromeHelper.find_all_element_in_node(_tab, node_id, 'iframe')
            for iframe_result in iframe_results:
                if iframe_result and iframe_result.get('nodeId'):
                    iframe_node_id = iframe_result['nodeId']
                    process_tab, result = await process_iframe(_tab, iframe_node_id)
                    if result and result.get('nodeId'):
                        return process_tab, result

            if 'children' in node:
                process_tab, result = await process_child(_tab, node)
                if result and result.get('nodeId'):
                    return process_tab, result
            
            return _tab, None

        async def process_iframe(_tab:Tab, node_id):
            iframe_response = await ChromeHelper.describe_node(_tab, node_id)
            frame_id = iframe_response['node']['frameId']
            iframe_tab = await ChromeHelper.switch_to_frame(_tab.browser, frame_id)
            if iframe_tab:
                iframe_document = await iframe_tab.send(ChromeHelper.cdp_generator("DOM.getDocument", {"depth": -1, "pierce": True}))
                process_tab, result = await process_node(iframe_tab, iframe_document['root'])
                if result and result.get('nodeId'):
                    return process_tab, result
            return _tab, None

        async def process_child(_tab:Tab, node):
            if 'children' in node:
                for child in node.get('children'):
                    if 'shadowRoots' in child:
                        for shadow_root in child['shadowRoots']:
                            process_tab, result = await process_node(_tab, shadow_root)
                            if result and result.get('nodeId'):
                                return process_tab, result
                    if 'children' in child:
                        process_tab, result = await process_child(_tab, child)
                        if result and result.get('nodeId'):
                            return process_tab, result
            return _tab, None

        document = await tab.send(ChromeHelper.cdp_generator("DOM.getDocument", {"depth": -1, "pierce": True}))
        process_tab, result = await process_node(tab, document['root'])

        if result is None or 'nodeId' not in result or result['nodeId'] is None:
            raise Exception(f"Element with selector '{selector}' not found.")
        
        node_id = result['nodeId']
        box_model = await process_tab.send(ChromeHelper.cdp_generator('DOM.getBoxModel', {
            'nodeId': node_id
        }))

        if 'model' in box_model and 'content' in box_model['model']:
            content = box_model['model']['content']
            x_min, y_min = content[0], content[1]
            x_max, y_max = content[4], content[5]
            x_center = (x_min + x_max) / 2
            y_center = (y_min + y_max) / 2

            await process_tab.send(ChromeHelper.cdp_generator('DOM.scrollIntoViewIfNeeded', {
                'nodeId': node_id
            }))

            await asyncio.gather(
                process_tab.send(ChromeHelper.cdp_generator('Input.dispatchMouseEvent', {
                    'type': 'mouseMoved',
                    'x': x_center,
                    'y': y_center,
                    'button': 'none'
                })),

                process_tab.send(ChromeHelper.cdp_generator('Input.dispatchMouseEvent', {
                    'type': 'mousePressed',
                    'x': x_center,
                    'y': y_center,
                    'button': 'left',
                    'clickCount': 1
                })),
                process_tab.send(ChromeHelper.cdp_generator('Input.dispatchMouseEvent', {
                    'type': 'mouseReleased',
                    'x': x_center,
                    'y': y_center,
                    'button': 'left',
                    'clickCount': 1
                }))
            )
        else:
            raise Exception(f"Failed to get box model for element with selector '{selector}'.")

    def get_status(self):
        if self._executable_path and not os.path.exists(self._executable_path):
            return False
        if not find_chrome_executable():
            return False
        return True

    @property
    async def browser(self):
        if not self._chrome:
            try:
                self._chrome = await self.__get_browser()
            except Exception as e:
                log.debug(f"Error getting browser: {e}")
        return self._chrome

    async def __get_browser(self):
        options = nd.Config()
        options.sandbox = False
        options.add_argument('--disable-gpu')
        options.add_argument('--ignore-certificate-errors')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument("--start-maximized")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-plugins-discovery")
        options.add_argument('--no-first-run')
        options.add_argument('--no-service-autorun')
        options.add_argument('--no-default-browser-check')
        options.add_argument('--password-store=basic')
        options.add_argument('--disable-setuid-sandbox')
        options.add_argument('--no-zygote')
        options.add_argument('--disable-gpu-sandbox')
        options.add_argument('--disable-software-rasterizer')
        options.add_argument('--ignore-ssl-errors')
        options.add_argument('--use-gl=swiftshader')
        options.add_argument("--disable-popup-blocking")
        options.add_argument('--disable-web-security')

        if SystemUtils.is_windows() or SystemUtils.is_macos():
            options.add_argument("--window-position=-32000,-32000")
        if self._proxy:
            proxy = Config().get_proxies().get("https")
            if proxy:
                proxy = proxy.split('/')[-1]
                options.add_argument('--proxy-server=%s' % proxy)
        if self._headless:
            options.headless = True
        options.lang="zh-CN"
        chrome = await nd.Browser.create(config=options)
        return chrome

    async def visit(self, url, ua=None, cookie=None, local_storage=None, timeout=60, proxy=None, new_tab=False):
        self._proxy = proxy
        if not await self.browser:
            return False
        try:
            if ua:
                await self._chrome.connection.send(nd.cdp.network.set_user_agent_override(user_agent = ua))
            if cookie:
                await self._chrome.cookies.clear()
                cookies = self.string_to_cookie_params(cookie, urlparse(str(url)).hostname)
                await self._chrome.connection.send(nd.cdp.storage.set_cookies(cookies))
            if self._tab:
                await self._tab.get(url)
            else:
                self._tab = await self._chrome.get(url)
            if local_storage:
                await self._tab.wait_for(text="html",timeout=timeout)
                await self.set_local_storage(local_storage)
                await self._tab.get(url)
            await asyncio.wait_for(self.check_document_ready(self._tab), timeout)
            return True
        except asyncio.TimeoutError:
            log.debug("Timeout: Page did not complete loading within the timeout period.")
            return False
        except Exception as err:
            log.error(str(err))
            return False

    async def new_tab(self, url, ua=None, cookie=None, local_storage=None):
        if not self._chrome:
            return False
        return await self.visit(url=url, ua=ua, cookie=cookie, local_storage=local_storage, new_tab=True)

    async def close_tab(self):
        try:
            await self._tab.close()
            if self._chrome.tabs == []:
                await self.quit()
        except Exception as err:
            log.error(str(err))
            return False

    async def pass_cloudflare(self):
        challenge = await CloudflareHelper.resolve_challenge(tab=self._tab)
        return challenge

    async def execute_script(self, script:str):
        if not self._tab:
            return False
        try:
            return await self._tab.evaluate(script.replace('return ',''))
        except Exception as err:
            log.error(str(err))

    async def get_title(self):
        if not self._tab:
            return ""
        return await self._tab.target.title

    async def get_html(self):
        if not self._tab:
            return ""
        return await self._tab.get_content()

    async def get_cookies(self):
        if not self._chrome:
            return ""
        connection = None
        for tab in self._chrome.tabs:
            if tab.closed:
                continue
            connection = tab
            break
        else:
            connection = self._chrome.connection
        cookie_str = ""
        try:
            def get_cookies_cdp_generator():
                cmd_json = yield {"method": "Storage.getCookies", "params": {}}
                return [i for i in cmd_json["cookies"]]
            cookies = await connection.send(get_cookies_cdp_generator())
            if cookies != []:
                for _cookie in cookies:
                    cookie_str += "%s=%s;" % (_cookie["name"], _cookie["value"])
        except Exception as err:
            log.error(str(err))
        return cookie_str
    
    async def set_local_storage(self, local_storage):
        if not self._tab:
            return ""
        local_storage = json.loads(local_storage)

        if type(local_storage) == dict and local_storage:
            try:
                for key in local_storage:
                    escaped_value = json.dumps(local_storage[key])
                    await self._tab.evaluate(f'localStorage.setItem("{key}", {escaped_value});')
            except Exception as err:
                log.error("set local storage error: " + str(err))
    
    async def get_local_storage(self):
        if self._tab:
            try:
                local_storage = json.dumps(await self._tab.evaluate("Object.fromEntries(Object.entries(localStorage));"))
                return local_storage
            except Exception as err:
                log.error(str(err))
        return ""

    def get_ua(self):
        try:
            return re.sub('HEADLESS', '', self._chrome.info['User-Agent'], flags=re.IGNORECASE)
        except Exception as err:
            log.error(str(err))
            return None

    async def quit(self):
        if self._chrome:
            for tab in self._chrome.tabs:
                await tab.close()
            self._chrome.stop()
            # Wait for the websocket to return True (Closed)
            while not self._chrome.connection.closed:
                # log.debug(f"Websocket status: {self._chrome.connection.closed}")
                await asyncio.sleep(0.1)
            self._fixup_uc_pid_leak()
            self._tab = None
            self._chrome = None

    def _fixup_uc_pid_leak(self):
        process_pid = self._chrome._process_pid
        if process_pid is None or not psutil.pid_exists(process_pid):
            return
        
        # Get the list of child processes before closing the Browser instance
        child_processes = psutil.Process(process_pid).children(recursive=True)
        for proc in child_processes:
            try:
                if proc.pid == process_pid:
                    log.debug(f"Terminating Chromium process with PID: {proc.pid}")
                    proc.terminate()
                elif any(name in proc.name().lower() for name in ("chromium", "chrome")):
                    log.debug(f"Terminating Chromium child process with PID: {proc.pid}")
                    proc.terminate()
                elif proc.status() == 'zombie':
                    log.debug(f"Terminating zombie Chromium process with PID: {proc.pid}")
                    proc.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass

        # Wait for all processes to terminate
        for proc in child_processes:
            try:
                if proc.pid == process_pid or any(name in proc.name().lower() for name in ("chromium", "chrome")):
                    proc.wait(timeout=10)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass

    def __del__(self):
        pass

def init_chrome():
    """
    初始化chrome驱动
    """
    ChromeHelper().init_driver()
