import os
import asyncio
import psutil
import re
import time
import nodriver as nd
from nodriver import Tab, Element, Browser
from nodriver.core.connection import ProtocolException
from nodriver.core.config import find_chrome_executable
from urllib.parse import urlparse

import log
import app.helper.cloudflare_helper as CloudflareHelper
from app.utils import SystemUtils, ExceptionUtils
from config import Config

import typing
import json

driver_executable_path = None

sub_regexes = {
    "tag": "([a-zA-Z][a-zA-Z0-9]{0,10}|\*)",
    "attribute": "[.a-zA-Z_:][-\w:.]*(\(\))?)",
    "value": "\s*[\w/:][-/\w\s,:;.]*"
}

validation_re = (
    "(?P<node>"
      "("
        "^id\([\"\']?(?P<idvalue>%(value)s)[\"\']?\)" # special case! id(idValue)
      "|"
        "(?P<nav>//?)(?P<tag>%(tag)s)" # //div
        "(\[("
          "(?P<matched>(?P<mattr>@?%(attribute)s=[\"\'](?P<mvalue>%(value)s))[\"\']" # [@id="bleh"] and [text()="meh"]
        "|"
          "(?P<contained>contains\((?P<cattr>@?%(attribute)s,\s*[\"\'](?P<cvalue>%(value)s)[\"\']\))" # [contains(text(), "bleh")] or [contains(@id, "bleh")]
        ")\])?"
        "(\[(?P<nth>\d+)\])?"
      ")"
    ")" % sub_regexes
)

prog = re.compile(validation_re)

class ChromeHelper(object):
    _executable_path = None

    _chrome = None
    _tab = None
    _headless = False

    _proxy = None
    _ua = None

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
    def string_to_cookie_params(cookie_string, url, json_format:bool=False):
        cookie_params = []
        domain = urlparse(str(url)).hostname
        parts = cookie_string.split(';')
        for part in parts:
            key_value = part.strip().split('=', 1)
            if len(key_value) != 2:
                continue
            key = key_value[0].strip()
            value = key_value[1].strip()
            cookie_param = nd.cdp.network.CookieParam(name=key, value=value, path="/", domain=domain)
            if json_format:
                cookie_param.to_json()
            cookie_params.append(cookie_param)
        return cookie_params
    
    @staticmethod
    async def wait_until_element_state(tab: Tab, text, should_appear=True, timeout=30):
        async def wait_element_disappear():
            try:
                while await tab.find(text=text, timeout=3):
                    await asyncio.sleep(1)
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
        while await tab.evaluate('document.readyState') == 'loading':
            await asyncio.sleep(1)
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
    
        css = ""
        position = 0

        while position < len(xpath):
            node = prog.match(xpath[position:])
            if node is None:
                raise "Invalid or unsupported Xpath: %s" % xpath
            # log.debug("node found: %s" % node)
            match = node.groupdict()
            # log.debug("broke node down to: %s" % match)

            nav = " " if match['nav'] == "//" else " > " if position != 0 else ""
            tag = "" if match['tag'] == "*" else match['tag'] or ""

            if match['idvalue']:
                attr = "#%s" % match['idvalue'].replace(" ", "#")
            elif match['matched']:
                if match['mattr'] == "@id":
                    attr = "#%s" % match['mvalue'].replace(" ", "#")
                elif match['mattr'] == "@class":
                    attr = ".%s" % match['mvalue'].replace(" ", ".")
                elif match['mattr'] in ["text()", "."]:
                    attr = ":contains(^%s$)" % match['mvalue']
                elif match['mattr']:
                    if match["mvalue"].find(" ") != -1:
                        match["mvalue"] = "\"%s\"" % match["mvalue"]
                    attr = "[%s=%s]" % (match['mattr'].replace("@", ""), match['mvalue'])
            elif match['contained']:
                if match['cattr'].startswith("@"):
                    attr = "[%s*=%s]" % (match['cattr'].replace("@", ""), match['cvalue'])
                elif match['cattr'] == "text()":
                    attr = ":contains(%s)" % match['cvalue']
            else:
                attr = ""
                
            nth = ":nth-of-type(%s)" % match['nth'] if match['nth'] else ""
            node_css = nav + tag + attr + nth
            # log.debug("final node css: %s" % node_css)
            css += node_css
            position += node.end()
            
        return css.strip() 

    async def is_clickable(self, element:Element):
        """
        checks if the element is clickable
        
        checks if the element is displayed and enabled
        :return: True if the element is clickable, False otherwise.
        :rtype: bool
        """
        if not element or not element.backend_node_id:
            return False
        try:
            box_model = await self._tab.send(nd.cdp.dom.get_box_model(backend_node_id=element.backend_node_id))
            size = {"height": 0, "width": 0} if box_model is None else {"height": box_model.height, "width": box_model.width}
            is_displayed = (size["height"] > 0 and size["width"] > 0)
            is_enabled = not bool(element.attrs.get("disabled"))
            return is_displayed and is_enabled
        except ProtocolException:
            return False
        
    async def element_to_be_clickable(self, selector, timeout=10):
        end_time = time.monotonic() + timeout
        while time.monotonic() < end_time:
            try:
                element = await self._tab.wait_for(text=selector, timeout=timeout)
                is_clickable = await self.is_clickable(element)
                # is_enabled = await self._tab.evaluate(f'document.querySelector(\'{self.xpath_to_css(selector)}\').disabled === false')
                if is_clickable:
                    return element
            except asyncio.TimeoutError:
                return False
            await asyncio.sleep(0.2)
        return False
    
    async def element_not_to_be_clickable(self, selector, timeout=10):
        end_time = time.monotonic() + timeout
        while time.monotonic() < end_time:
            try:
                element = await self._tab.wait_for(text=selector, timeout=timeout)
                is_clickable = await self.is_clickable(element)
                # is_disabled = await self._tab.evaluate(f'document.querySelector(\'{self.xpath_to_css(selector)}\').disabled === true')
                if not is_clickable:
                    return True
            except asyncio.TimeoutError:
                return True
            await asyncio.sleep(0.2)
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

        if self._ua:
            options.add_argument(f'--user-agent={self._ua}')

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
        chrome = await RetryBrowser.create(config=options)
        return chrome

    async def visit(self, url, ua=None, cookie=None, local_storage=None, timeout=30, proxy=None, new_tab=False):
        self._proxy = proxy
        self._ua = ua
        if not await self.browser:
            return False
        try:
            if cookie:
                await self._chrome.cookies.clear()
                cookies = self.string_to_cookie_params(cookie, url)
                await self._chrome.connection.send(nd.cdp.storage.set_cookies(cookies))
            if self._tab:
                await self._tab.get(url)
            else:
                self._tab = await self._chrome.get(url)
            await self._tab
            await self._tab.wait_for(text="html",timeout=timeout)
            await asyncio.wait_for(self.check_document_ready(self._tab), timeout)
            if local_storage:
                await self.set_local_storage(local_storage)
                await self._tab.get(url)
                await self._tab
                await self._tab.wait_for(text="html",timeout=timeout)
                await asyncio.wait_for(self.check_document_ready(self._tab), timeout)
            return True
        except asyncio.TimeoutError:
            log.debug("Timeout: Page did not complete loading within the timeout period.")
            if await self._tab.find(text="html"):
                return True
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

    async def get_cookies(self, str_format:bool=True):
        if not self._chrome:
            return "" if str_format else []
        connection = next((tab for tab in self._chrome.tabs if not tab.closed), self._chrome.connection)
        cookie_str = ""
        try:
            def get_cookies_cdp_generator():
                cmd_json = yield {"method": "Storage.getCookies", "params": {}}
                return [i for i in cmd_json.get("cookies", [])]
            cookies = await connection.send(get_cookies_cdp_generator())
            if str_format and cookies:
                for _cookie in cookies:
                    cookie_str += "%s=%s;" % (_cookie["name"], _cookie["value"])
        except Exception as err:
            cookies = "" if str_format else []
            log.error(str(err))
        return cookie_str if str_format else cookies
    
    @staticmethod
    def filter_local_storage(local_storage, keep_keys=None, remove_keys=None):
        is_json = False
        if isinstance(local_storage, str):
            try:
                local_storage = json.loads(local_storage)
                is_json = True
            except json.JSONDecodeError:
                pass

        if not isinstance(local_storage, dict):
            return local_storage
        elif keep_keys is not None:
            filtered_storage = {k: v for k, v in local_storage.items() if k in keep_keys}
        elif remove_keys is not None:
            filtered_storage = {k: v for k, v in local_storage.items() if k not in remove_keys}

        return json.dumps(filtered_storage) if is_json else filtered_storage

    async def set_local_storage(self, local_storage):
        if not self._tab:
            return
        local_storage = json.loads(local_storage)

        if not (local_storage and type(local_storage) == dict):
            return
        
        stability_count = 0
        previous_storage = None
        for _ in range(10):
            current_storage = await self.get_local_storage()
            if current_storage:
                if current_storage == previous_storage:
                    stability_count += 1
                    if stability_count >= 2:
                        break
                else:
                    stability_count = 0
                previous_storage = current_storage
            await asyncio.sleep(1)

        for i in range(3):
            try:
                for key in local_storage:
                    escaped_value = json.dumps(local_storage[key])
                    await self._tab.evaluate(f'localStorage.setItem("{key}", {escaped_value});')
                # await self._tab.set_local_storage(local_storage)
                break
            except Exception as err:
                if i == 2:
                    log.error("set local storage error: " + str(err))
            await asyncio.sleep(1)

    async def get_local_storage(self):
        if self._tab:
            try:
                # local_storage = json.dumps(dict(await self._tab.evaluate("Object.fromEntries(Object.entries(localStorage));")))
                local_storage = json.dumps(await self._tab.get_local_storage())
                if not local_storage or local_storage == '{}':
                    return ""
                return local_storage
            except Exception as err:
                log.error(str(err))
        return ""

    async def get_ua(self):
        try:
            if self._tab:
                return await self._tab.evaluate('navigator.userAgent')
            elif self._chrome:
                return re.sub('HEADLESS', '', self._chrome.info['User-Agent'], flags=re.IGNORECASE)
            return None
        except Exception as err:
            log.error(str(err))
            return None

    async def quit(self):
        if self._chrome:
            try:
                # Close all tabs
                for tab in self._chrome.tabs:
                    await tab.close()
                self._chrome.stop()
                
                # Wait for the websocket to return True (Closed)
                end_time = time.monotonic() + 10
                while time.monotonic() < end_time:
                    if self._chrome.connection.closed and not self._chrome._process:
                        # log.debug(f"Websocket status: {self._chrome.connection.closed}")
                        break
                    await asyncio.sleep(0.2)
            except Exception as e:
                log.error(f"Error during browser closure: {e}")
            finally:
                # Ensure the browser process is terminated
                self._cleanup_processes()
                self._tab = None
                self._chrome = None

    def _cleanup_processes(self):
        process_pid = self._chrome._process_pid
        if process_pid is None or not psutil.pid_exists(process_pid):
            return
        
        try:
            # Get the list of child processes before closing the Browser instance
            parent_process = psutil.Process(process_pid)
            processes_to_kill = parent_process.children(recursive=True) + [parent_process]
        except psutil.NoSuchProcess:
            # log.debug(f"Parent process {process_pid} no longer exists")
            return

        for proc in processes_to_kill:
            try:
                log.debug(f"正在终止进程 {proc.pid} ({proc.name()})...")
                proc.terminate()
            except psutil.NoSuchProcess:
                pass
        
        _, alive = psutil.wait_procs(processes_to_kill, timeout=5)

        for proc in alive:
            try:
                log.debug(f"进程 {proc.pid} 依然存活，强制杀死...")
                proc.kill()
            except psutil.NoSuchProcess:
                pass

    def __del__(self):
        pass
    
    @staticmethod
    def kill_chrome_processes():
        # Iterate through all running processes
        for proc in psutil.process_iter(attrs=['pid', 'name', 'cmdline']):
            try:
                if 'chrome' in proc.info['name'].lower() or 'chromium' in proc.info['name'].lower():
                    proc.terminate()
                    proc.wait(timeout=3)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass

        # Check if any processes are still running and forcefully kill them if needed
        for proc in psutil.process_iter(attrs=['pid', 'name', 'cmdline']):
            try:
                if 'chrome' in proc.info['name'].lower() or 'chromium' in proc.info['name'].lower():
                    print(f"Force killing process: {proc.info['pid']} - {proc.info['name']}")
                    proc.kill()
                    proc.wait(timeout=3)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass

class RetryBrowser(Browser):
    @classmethod
    async def create(
        cls,
        config=None,
        *,
        user_data_dir=None,
        headless=False,
        browser_executable_path=None,
        browser_args=None,
        sandbox=True,
        host=None,
        port=None,
        max_retries=3,
        retry_interval=2,
        **kwargs,
    ) -> "RetryBrowser":
        """
        Wrapper for the original `create` method with retry functionality.
        """
        retries = 0

        while retries < max_retries:
            instance = cls(
                config=config or cls.Config(
                    user_data_dir=user_data_dir,
                    headless=headless,
                    browser_executable_path=browser_executable_path,
                    browser_args=browser_args or [],
                    sandbox=sandbox,
                    host=host,
                    port=port,
                    **kwargs,
                )
            )
            try:
                await instance.start()
                return instance
            except Exception as e:
                await asyncio.sleep(retry_interval)
                try:
                    instance.info = nd.ContraDict(await instance._http.get("version"), silent=True)
                    if not instance.info:
                        raise
                    instance.connection = nd.Connection(instance.info.webSocketDebuggerUrl, _owner=instance)
                    if instance.config.autodiscover_targets:
                        instance.connection.handlers[nd.cdp.target.TargetInfoChanged] = [
                            instance._handle_target_update
                        ]
                        instance.connection.handlers[nd.cdp.target.TargetCreated] = [
                            instance._handle_target_update
                        ]
                        instance.connection.handlers[nd.cdp.target.TargetDestroyed] = [
                            instance._handle_target_update
                        ]
                        instance.connection.handlers[nd.cdp.target.TargetCrashed] = [
                            instance._handle_target_update
                        ]
                        await instance.connection.send(nd.cdp.target.set_discover_targets(discover=True))
                    return instance
                except:
                    retries += 1
                    log.debug(f"Failed to start browser, attempt {retries}/{max_retries}: {e}")
                    if hasattr(instance, '_process') and instance._process:
                        await RetryBrowser._cleanup_process(instance)
                    instance._process = None
                    instance._process_pid = None
                    nd.util.get_registered_instances().remove(instance)
        raise Exception(f"Failed to create browser after {max_retries} attempts")
    
    @staticmethod
    async def _cleanup_process(instance: "RetryBrowser"):
        """
        Cleans up the browser process, tries to terminate gracefully, and force kills if necessary.
        """
        try:
            instance._process.terminate()
            await asyncio.wait_for(instance._process.wait(), timeout=10)
        except asyncio.TimeoutError:
            log.debug("Process did not terminate within the timeout, forcefully killing.")
            instance._process.kill()
            await instance._process.wait()
        except Exception as inner_exception:
            log.debug(f"Error during process cleanup: {inner_exception}")

def init_chrome():
    """
    初始化chrome驱动
    """
    ChromeHelper().init_driver()
