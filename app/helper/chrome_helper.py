import os
import asyncio
import psutil
import re
import shutil
import tempfile
import time
import nodriver as nd
from nodriver import Tab, Element, Browser
from nodriver.core.connection import ProtocolException
from nodriver.core.config import find_chrome_executable, is_posix
import threading
from urllib.parse import urlparse

import log
import app.helper.cloudflare_helper as CloudflareHelper
from app.utils import SystemUtils, ExceptionUtils
from config import Config

import typing
import json
import hashlib
from filelock import FileLock, Timeout as FileLockTimeout

_SPAWN_THREAD_LOCK = threading.Lock()

driver_executable_path = None

sub_regexes = {
    "tag": r"([a-zA-Z][a-zA-Z0-9]{0,10}|\*)",
    "attribute": r"[.a-zA-Z_:][-\w:.]*(\(\))?)",
    "value": r"\s*[\w/:][-/\w\s,:;.]*",
}

validation_re = (
    r"(?P<node>"
    r"(" 
    r"^id\([\"\']?(?P<idvalue>%(value)s)[\"\']?\)" 
    r"|" 
    r"(?P<nav>//?)(?P<tag>%(tag)s)" 
    r"(\[(" 
    r"(?P<matched>(?P<mattr>@?%(attribute)s=[\"\'](?P<mvalue>%(value)s))[\"\']" 
    r"|" 
    r"(?P<contained>contains\((?P<cattr>@?%(attribute)s,\s*[\"\'](?P<cvalue>%(value)s)[\"\']\))" 
    r")\])?" 
    r"(\[(?P<nth>\d+)\])?" 
    r")" 
    r")" % sub_regexes
)

prog = re.compile(validation_re)

class ChromeHelper(object):
    _executable_path = None

    _chrome = None
    _tab = None
    _headless = False

    _proxy = None
    _ua = None
    
    # 站点Profile管理
    _SITE_PROFILES_DIR = "chrome_profiles"  # 相对于config目录
    _SITE_PROFILE_MAX_AGE_DAYS = 7  # Profile过期天数
    _site_profile_locks = {}  # 站点Profile锁字典 {site_domain: FileLock}
    _site_profile_locks_lock = threading.Lock()  # 保护锁字典的锁
    
    # 实例变量
    _site_domain = None  # 当前使用的站点域名
    _site_profile_lock = None  # 当前持有的站点Profile锁
    _uses_site_profile = False  # 是否使用站点Profile
    _authenticated_domain = None  # 已成功认证的域名（preserve_data模式下）

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
    def get_site_profiles_base_dir() -> str:
        """
        获取站点Profile基础目录
        :return: 站点Profile基础目录路径
        """
        config_path = Config().get_config_path()
        return os.path.join(config_path, ChromeHelper._SITE_PROFILES_DIR)
    
    @staticmethod
    def _get_site_domain_hash(site_domain: str) -> str:
        """
        获取站点域名的安全哈希值（用于目录命名）
        :param site_domain: 站点域名
        :return: 域名的短哈希值
        """
        # 使用MD5的前12位作为目录名，避免特殊字符问题
        return hashlib.md5(site_domain.encode()).hexdigest()[:12]
    
    @staticmethod
    def get_site_profile_dir(site_domain: str) -> str:
        """
        获取站点专用的浏览器Profile目录
        :param site_domain: 站点域名
        :return: 该站点的浏览器Profile目录路径
        """
        base_dir = ChromeHelper.get_site_profiles_base_dir()
        # 使用域名哈希作为目录名，并附加域名作为前缀方便识别
        safe_domain = re.sub(r'[^\w\-.]', '_', site_domain)[:30]
        dir_name = f"{safe_domain}_{ChromeHelper._get_site_domain_hash(site_domain)}"
        return os.path.join(base_dir, dir_name)
    
    @staticmethod
    def get_site_profile_lock_path(site_domain: str) -> str:
        """
        获取站点Profile锁文件路径
        :param site_domain: 站点域名
        :return: 锁文件路径
        """
        profile_dir = ChromeHelper.get_site_profile_dir(site_domain)
        return f"{profile_dir}.lock"
    
    def acquire_site_profile_lock(self, site_domain: str, timeout: float = 60) -> bool:
        """
        获取站点Profile的独占锁
        :param site_domain: 站点域名
        :param timeout: 超时时间（秒），默认60秒
        :return: 是否成功获取锁
        """
        lock_path = ChromeHelper.get_site_profile_lock_path(site_domain)
        
        # 确保锁文件目录存在
        lock_dir = os.path.dirname(lock_path)
        if not os.path.exists(lock_dir):
            os.makedirs(lock_dir, exist_ok=True)
        
        with ChromeHelper._site_profile_locks_lock:
            if site_domain not in ChromeHelper._site_profile_locks:
                ChromeHelper._site_profile_locks[site_domain] = FileLock(lock_path)
            file_lock = ChromeHelper._site_profile_locks[site_domain]
        
        try:
            file_lock.acquire(timeout=timeout)
            self._site_profile_lock = file_lock
            self._site_domain = site_domain
            self._uses_site_profile = True
            log.debug(f"Acquired site profile lock for {site_domain}")
            return True
        except FileLockTimeout:
            log.warn(f"Failed to acquire site profile lock for {site_domain} within {timeout}s")
            return False
    
    def release_site_profile_lock(self):
        """
        释放当前持有的站点Profile锁
        """
        if self._site_profile_lock and self._site_profile_lock.is_locked:
            try:
                self._site_profile_lock.release()
                log.debug(f"Released site profile lock for {self._site_domain}")
            except Exception as e:
                log.error(f"Error releasing site profile lock: {e}")
        self._site_profile_lock = None
        self._site_domain = None
        self._uses_site_profile = False
    
    @staticmethod
    def cleanup_expired_site_profiles():
        """
        清理过期的站点Profile目录
        删除超过 _SITE_PROFILE_MAX_AGE_DAYS 天未使用的Profile
        """
        base_dir = ChromeHelper.get_site_profiles_base_dir()
        if not os.path.exists(base_dir):
            return
        
        max_age_seconds = ChromeHelper._SITE_PROFILE_MAX_AGE_DAYS * 24 * 60 * 60
        current_time = time.time()
        deleted_count = 0
        
        for name in os.listdir(base_dir):
            profile_path = os.path.join(base_dir, name)
            if not os.path.isdir(profile_path):
                continue
            
            # 检查是否有锁定（正在使用）
            lock_path = f"{profile_path}.lock"
            try:
                # 尝试获取锁，如果获取不到说明正在使用
                test_lock = FileLock(lock_path, timeout=0)
                test_lock.acquire()
                test_lock.release()
            except FileLockTimeout:
                # 正在使用，跳过
                continue
            except Exception:
                pass
            
            # 检查最后修改时间
            try:
                last_access_file = os.path.join(profile_path, ".last_access")
                if os.path.exists(last_access_file):
                    mtime = os.path.getmtime(last_access_file)
                else:
                    mtime = os.path.getmtime(profile_path)
                
                age = current_time - mtime
                if age > max_age_seconds:
                    shutil.rmtree(profile_path, ignore_errors=True)
                    if os.path.exists(lock_path):
                        os.remove(lock_path)
                    deleted_count += 1
                    log.debug(f"Deleted expired site profile: {name}")
            except Exception as e:
                log.error(f"Error checking profile age for {name}: {e}")
        
        if deleted_count > 0:
            log.info(f"Cleaned up {deleted_count} expired site profiles")
    
    @staticmethod
    def update_site_profile_access_time(site_domain: str):
        """
        更新站点Profile的最后访问时间
        :param site_domain: 站点域名
        """
        profile_dir = ChromeHelper.get_site_profile_dir(site_domain)
        if not os.path.exists(profile_dir):
            return
        
        last_access_file = os.path.join(profile_dir, ".last_access")
        try:
            with open(last_access_file, 'w') as f:
                f.write(str(time.time()))
        except Exception as e:
            log.debug(f"Error updating profile access time: {e}")

    @staticmethod
    def get_site_profile_list() -> list:
        """
        获取所有站点Profile缓存列表
        :return: 缓存列表，每项包含 {name, domain, dir_name, size, created_time, last_access_time, is_locked}
        """
        import datetime
        base_dir = ChromeHelper.get_site_profiles_base_dir()
        if not os.path.exists(base_dir):
            return []
        
        profiles = []
        current_time = time.time()
        
        for name in os.listdir(base_dir):
            profile_path = os.path.join(base_dir, name)
            if not os.path.isdir(profile_path):
                continue
            
            # 解析域名（目录名格式：{safe_domain}_{hash}）
            parts = name.rsplit('_', 1)
            domain = parts[0] if len(parts) > 1 else name
            
            # 检查是否正在使用（有锁）
            lock_path = f"{profile_path}.lock"
            is_locked = False
            try:
                test_lock = FileLock(lock_path, timeout=0)
                test_lock.acquire()
                test_lock.release()
            except FileLockTimeout:
                is_locked = True
            except Exception:
                pass
            
            # 获取创建时间和最后访问时间
            try:
                # 创建时间：目录的创建时间
                created_time = os.path.getctime(profile_path)
                
                # 最后访问时间：.last_access 文件的内容或修改时间
                last_access_file = os.path.join(profile_path, ".last_access")
                if os.path.exists(last_access_file):
                    try:
                        with open(last_access_file, 'r') as f:
                            last_access_time = float(f.read().strip())
                    except:
                        last_access_time = os.path.getmtime(last_access_file)
                else:
                    last_access_time = os.path.getmtime(profile_path)
                
                # 计算目录大小
                total_size = 0
                for dirpath, dirnames, filenames in os.walk(profile_path):
                    for f in filenames:
                        fp = os.path.join(dirpath, f)
                        try:
                            total_size += os.path.getsize(fp)
                        except:
                            pass
                
                # 转换为易读格式
                if total_size < 1024:
                    size_str = f"{total_size} B"
                elif total_size < 1024 * 1024:
                    size_str = f"{total_size / 1024:.1f} KB"
                else:
                    size_str = f"{total_size / (1024 * 1024):.1f} MB"
                
                profiles.append({
                    'name': name,
                    'domain': domain,
                    'dir_name': name,
                    'size': size_str,
                    'size_bytes': total_size,
                    'created_time': datetime.datetime.fromtimestamp(created_time).strftime('%Y-%m-%d %H:%M:%S'),
                    'created_timestamp': created_time,
                    'last_access_time': datetime.datetime.fromtimestamp(last_access_time).strftime('%Y-%m-%d %H:%M:%S'),
                    'last_access_timestamp': last_access_time,
                    'is_locked': is_locked
                })
            except Exception as e:
                log.debug(f"Error getting profile info for {name}: {e}")
        
        # 按最后访问时间倒序排列
        profiles.sort(key=lambda x: x['last_access_timestamp'], reverse=True)
        return profiles

    @staticmethod
    def delete_site_profiles(dir_names: list) -> dict:
        """
        删除指定的站点Profile缓存
        :param dir_names: 要删除的目录名列表
        :return: {'success': 成功数, 'failed': 失败数, 'locked': 被锁定数, 'errors': 错误信息列表}
        """
        base_dir = ChromeHelper.get_site_profiles_base_dir()
        if not os.path.exists(base_dir):
            return {'success': 0, 'failed': 0, 'locked': 0, 'errors': ['缓存目录不存在']}
        
        success_count = 0
        failed_count = 0
        locked_count = 0
        errors = []
        
        for dir_name in dir_names:
            profile_path = os.path.join(base_dir, dir_name)
            if not os.path.exists(profile_path):
                failed_count += 1
                errors.append(f"{dir_name}: 不存在")
                continue
            
            lock_path = f"{profile_path}.lock"
            
            # 检查是否正在使用
            try:
                test_lock = FileLock(lock_path, timeout=0)
                test_lock.acquire()
                # 成功获取锁，可以删除
                try:
                    shutil.rmtree(profile_path, ignore_errors=True)
                    if os.path.exists(lock_path):
                        os.remove(lock_path)
                    success_count += 1
                    log.info(f"已删除站点缓存: {dir_name}")
                except Exception as e:
                    failed_count += 1
                    errors.append(f"{dir_name}: {str(e)}")
                finally:
                    test_lock.release()
            except FileLockTimeout:
                locked_count += 1
                errors.append(f"{dir_name}: 正在使用中")
            except Exception as e:
                failed_count += 1
                errors.append(f"{dir_name}: {str(e)}")
        
        return {
            'success': success_count,
            'failed': failed_count,
            'locked': locked_count,
            'errors': errors
        }

    @staticmethod
    def delete_all_site_profiles() -> dict:
        """
        删除所有未锁定的站点Profile缓存
        :return: {'success': 成功数, 'failed': 失败数, 'locked': 被锁定数, 'errors': 错误信息列表}
        """
        profiles = ChromeHelper.get_site_profile_list()
        dir_names = [p['dir_name'] for p in profiles]
        return ChromeHelper.delete_site_profiles(dir_names)

    @staticmethod
    def string_to_cookie_params(cookie_string, url, json_format:bool=False):
        """
        将cookie字符串转换为CookieParam对象列表
        :param cookie_string: cookie字符串
        :param url: 目标URL，用于提取domain
        :param json_format: 是否转换为JSON格式
        :return: CookieParam对象列表，如果URL无效则返回空列表
        """
        cookie_params = []
        parsed_url = urlparse(str(url))
        domain = parsed_url.hostname
        
        # 验证URL有效性：必须是http/https协议且有有效的domain
        if not domain:
            log.warn(f"无效的URL，无法提取domain: {url}")
            return cookie_params
        
        # 检查协议是否为http/https
        if parsed_url.scheme not in ('http', 'https', ''):
            log.warn(f"不支持的URL协议 '{parsed_url.scheme}'，跳过cookie注入: {url}")
            return cookie_params
        
        if not cookie_string:
            return cookie_params
            
        parts = cookie_string.split(';')
        for part in parts:
            key_value = part.strip().split('=', 1)
            if len(key_value) != 2:
                continue
            key = key_value[0].strip()
            value = key_value[1].strip()
            # 跳过空的key或value
            if not key:
                continue
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
        }), _is_update=True)
    
    @staticmethod
    async def find_element_in_node(tab:Tab, node_id, selector):
        result = await tab.send(ChromeHelper.cdp_generator("DOM.querySelector", {
            "nodeId": node_id,
            "selector": ChromeHelper.xpath_to_css(selector)
        }), _is_update=True)
        return result
    
    @staticmethod
    async def find_all_element_in_node(tab:Tab, node_id, selector):
        results = await tab.send(ChromeHelper.cdp_generator("DOM.querySelectorAll", {
            "nodeId": node_id,
            "selector": ChromeHelper.xpath_to_css(selector)
        }), _is_update=True)
        return results
    
    @staticmethod
    async def switch_to_frame(browser:nd.Browser, frame_id):
        iframe_tab: Tab = next(
            filter(
            lambda x: str(x.target.target_id) == str(frame_id), browser.targets
            ),
            None
        )
        if iframe_tab:
            iframe_tab.websocket_url = iframe_tab.websocket_url.replace("iframe", "page")
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
                return xpath
                # raise "Invalid or unsupported Xpath: %s" % xpath
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
            box_model = await self._tab.send(nd.cdp.dom.get_box_model(backend_node_id=element.backend_node_id), _is_update=True)
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
                element = await self._tab.find(text=selector, timeout=timeout)
                is_clickable = await self.is_clickable(element)
                # is_enabled = await self._tab.evaluate(f'document.querySelector(\'{self.xpath_to_css(selector)}\').disabled === false')
                if is_clickable:
                    return element
            except ProtocolException:
                pass
            except asyncio.TimeoutError:
                return False
            await asyncio.sleep(0.2)
        return False
    
    async def element_not_to_be_clickable(self, selector, timeout=10):
        end_time = time.monotonic() + timeout
        while time.monotonic() < end_time:
            try:
                element = await self._tab.find(text=selector, timeout=timeout)
                is_clickable = await self.is_clickable(element)
                # is_disabled = await self._tab.evaluate(f'document.querySelector(\'{self.xpath_to_css(selector)}\').disabled === true')
                if not is_clickable:
                    return True
            except asyncio.TimeoutError:
                return True
            await asyncio.sleep(0.2)
        return False
    
    @staticmethod
    async def find_and_click_element(tab:Tab, selector, click_enabled=True, max_depth=-1, timeout=10):
        """
        查找元素并可选择点击
        :param tab: Tab对象
        :param selector: CSS选择器
        :param click_enabled: 是否点击元素
        :param max_depth: 最大递归深度，-1表示不限制递归深度，默认-1
        :param timeout: 超时时间(秒)，防止长时间卡死，默认10秒
        :return: (found: bool, coordinates: tuple/None)
                 - found: True表示找到元素，False表示未找到
                 - coordinates: 元素坐标(x, y)，未找到时为None
        """
        async def process_node(_tab:Tab, node, depth=0):    
            if max_depth >= 0 and depth > max_depth:
                return _tab, None
                
            node_id = node['nodeId'] if 'nodeId' in node else None
            if not node_id:
                return _tab, None

            result = await ChromeHelper.find_element_in_node(_tab, node_id, selector)
            if result and result.get('nodeId'):
                return _tab, result

            if 'shadowRoots' in node:
                for shadow_root in node['shadowRoots']:
                    process_tab, result = await process_node(_tab, shadow_root, depth + 1)
                    if result and result.get('nodeId'):
                        return process_tab, result

            iframe_results = await ChromeHelper.find_all_element_in_node(_tab, node_id, 'iframe')
            if iframe_results and iframe_results.get('nodeIds'):
                for iframe_node_id in iframe_results["nodeIds"]:
                    process_tab, result = await process_iframe(_tab, iframe_node_id, depth + 1)
                    if result and result.get('nodeId'):
                        return process_tab, result

            if 'children' in node:
                process_tab, result = await process_child(_tab, node, depth + 1)
                if result and result.get('nodeId'):
                    return process_tab, result
            
            return _tab, None

        async def process_iframe(_tab:Tab, node_id, depth=0):
            if max_depth >= 0 and depth > max_depth:
                return _tab, None
            try:
                iframe_response = await ChromeHelper.describe_node(_tab, node_id)
                frame_id = iframe_response['node']['frameId']
                iframe_tab = await ChromeHelper.switch_to_frame(_tab.browser, frame_id)
                if iframe_tab:
                    iframe_document = await iframe_tab.send(ChromeHelper.cdp_generator("DOM.getDocument", {"depth": -1, "pierce": True}), _is_update=True)
                    process_tab, result = await process_node(iframe_tab, iframe_document['root'], depth + 1)
                    if result and result.get('nodeId'):
                        return process_tab, result
            except Exception:
                pass
            return _tab, None

        async def process_child(_tab:Tab, node, depth=0):
            if max_depth >= 0 and depth > max_depth:
                return _tab, None
            if 'children' in node:
                for child in node.get('children'):
                    if 'shadowRoots' in child:
                        for shadow_root in child['shadowRoots']:
                            process_tab, result = await process_node(_tab, shadow_root, depth + 1)
                            if result and result.get('nodeId'):
                                return process_tab, result
                    if 'children' in child:
                        process_tab, result = await process_child(_tab, child, depth + 1)
                        if result and result.get('nodeId'):
                            return process_tab, result
            return _tab, None

        try:
            async def execute_element_search():
                document = await tab.send(ChromeHelper.cdp_generator("DOM.getDocument", {"depth": -1, "pierce": True}), _is_update=True)
                process_tab, result = await process_node(tab, document['root'])

                if result is None or 'nodeId' not in result or result['nodeId'] is None:
                    return False, None
                
                node_id = result['nodeId']
                box_model = await process_tab.send(ChromeHelper.cdp_generator('DOM.getBoxModel', {
                    'nodeId': node_id
                }), _is_update=True)
                return process_tab, result, box_model, node_id
            
            search_result = await asyncio.wait_for(execute_element_search(), timeout=timeout)
            if len(search_result) == 2:  # 返回了 False, None
                return search_result
            process_tab, result, box_model, node_id = search_result
            
        except asyncio.TimeoutError:
            log.debug(f"find_and_click_element timed out after {timeout} seconds")
            return False, None
        except Exception:
            return False, None

        if 'model' in box_model and 'content' in box_model['model']:
            content = box_model['model']['content']
            x_min, y_min = content[0], content[1]
            x_max, y_max = content[4], content[5]
            x_center = (x_min + x_max) / 2
            y_center = (y_min + y_max) / 2
            coordinates = (x_center, y_center)

            if click_enabled:
                await process_tab.send(ChromeHelper.cdp_generator('DOM.scrollIntoViewIfNeeded', {
                    'nodeId': node_id
                }), _is_update=True)

                await process_tab.send(ChromeHelper.cdp_generator('Input.dispatchMouseEvent', {
                    'type': 'mouseMoved',
                    'x': x_center,
                    'y': y_center,
                    'button': 'none'
                }), _is_update=True)

                await process_tab.send(ChromeHelper.cdp_generator('Input.dispatchMouseEvent', {
                    'type': 'mousePressed',
                    'x': x_center,
                    'y': y_center,
                    'button': 'left',
                    'clickCount': 1
                }), _is_update=True)

                await process_tab.send(ChromeHelper.cdp_generator('Input.dispatchMouseEvent', {
                    'type': 'mouseReleased',
                    'x': x_center,
                    'y': y_center,
                    'button': 'left',
                    'clickCount': 1
                }), _is_update=True)
            
            return True, coordinates
        else:
            return False, None

    @staticmethod
    async def find_element(tab:Tab, selector):
        """
        查找元素
        :param tab: Tab对象
        :param selector: CSS选择器
        :return: (found: bool, coordinates: tuple/None)
        """
        return await ChromeHelper.find_and_click_element(tab, selector, click_enabled=False)

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

    async def __get_browser(self, user_data_dir=None):
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
            proxies = Config().get_proxies()
            if proxies:
                proxy = proxies.get("https")
                if proxy:
                    proxy = proxy.split('/')[-1]
                    options.add_argument('--proxy-server=%s' % proxy)
        if self._headless:
            options.headless = True
        options.lang="zh-CN"
        chrome = await RetryBrowser.create(config=options, user_data_dir=user_data_dir, max_retries=5, retry_interval=2)
        return chrome

    async def _open_page(self, url, timeout, new_tab=False):
        """打开页面并等待加载完成"""
        self._tab = await self._chrome.get(url, new_tab=new_tab)
        await self._tab
        await self._tab.wait_for(text="html", timeout=timeout)
        await asyncio.wait_for(self.check_document_ready(self._tab), timeout)
    
    async def _navigate(self, url, timeout):
        """在当前标签页导航到新URL"""
        await self._tab.get(url)
        await self._tab
        await self._tab.wait_for(text="html", timeout=timeout)
        await asyncio.wait_for(self.check_document_ready(self._tab), timeout)
    
    async def _reload_page(self, timeout):
        """刷新当前页面"""
        await self._tab.reload()
        await self._tab.wait_for(text="html", timeout=timeout)
        await asyncio.wait_for(self.check_document_ready(self._tab), timeout)

    async def visit(self, url, ua=None, cookie=None, local_storage=None, timeout=30, proxy=None, new_tab=False, 
                    site_domain=None, preserve_data=False):
        """
        访问URL
        :param url: 目标URL
        :param ua: User-Agent
        :param cookie: Cookie字符串
        :param local_storage: LocalStorage JSON字符串
        :param timeout: 超时时间
        :param proxy: 是否使用代理
        :param new_tab: 是否在新标签页打开
        :param site_domain: 站点域名，用于获取站点专用Profile和锁定
        :param preserve_data: 如果为True，优先使用浏览器已有的cookie/localStorage，只在需要时才注入新数据
        """
        # 验证URL有效性
        parsed_url = urlparse(str(url))
        if parsed_url.scheme not in ('http', 'https'):
            log.error(f"无效的URL协议 '{parsed_url.scheme}'，只支持http/https: {url}")
            return False
        if not parsed_url.hostname:
            log.error(f"无效的URL，缺少有效的主机名: {url}")
            return False
        
        current_domain = parsed_url.hostname
        self._proxy = proxy
        self._ua = ua
        
        # 如果指定了站点域名，尝试获取站点Profile锁并使用站点专用Profile
        user_data_dir = None
        if site_domain:
            if not self.acquire_site_profile_lock(site_domain, timeout=60):
                log.warn(f"无法获取站点 {site_domain} 的Profile锁，将使用临时Profile")
            else:
                user_data_dir = ChromeHelper.get_site_profile_dir(site_domain)
                if not os.path.exists(user_data_dir):
                    os.makedirs(user_data_dir, exist_ok=True)
                log.debug(f"使用站点Profile目录: {user_data_dir}")
        
        # 获取浏览器
        if not self._chrome:
            try:
                self._chrome = await self.__get_browser(user_data_dir=user_data_dir)
            except Exception as e:
                log.debug(f"Error getting browser: {e}")
                return False
        
        if not self._chrome:
            return False
            
        max_retries = 3
        backoff = 1
        last_err = None
        for attempt in range(1, max_retries + 1):
            try:
                # 已认证同域名时直接导航
                if self._authenticated_domain == current_domain and self._tab:
                    await self._navigate(url, timeout)
                    return True
                
                should_inject_cookie = True
                
                # preserve_data模式：先尝试使用已保存的浏览器数据
                if preserve_data and self._uses_site_profile:
                    await self._open_page(url, timeout, new_tab)
                    from app.helper import SiteHelper
                    if await SiteHelper.wait_for_logged_in(self._tab, timeout=5):
                        log.debug(f"使用已保存的浏览器数据成功登录站点")
                        should_inject_cookie = False
                        self._authenticated_domain = current_domain
                        if site_domain:
                            ChromeHelper.update_site_profile_access_time(site_domain)
                
                # 注入cookie
                if should_inject_cookie and cookie:
                    cookies = self.string_to_cookie_params(cookie, url)
                    if cookies:
                        await self._chrome.cookies.clear()
                        await self._chrome.connection.send(nd.cdp.storage.set_cookies(cookies))
                    
                    if self._tab:
                        await self._reload_page(timeout)
                    else:
                        await self._open_page(url, timeout, new_tab)
                    self._authenticated_domain = current_domain
                
                # 处理localStorage
                if local_storage:
                    if not self._tab:
                        await self._open_page(url, timeout, new_tab)
                    await self.set_local_storage(local_storage)
                    await self._navigate(url, timeout)
                    self._authenticated_domain = current_domain
                
                # 兜底：确保页面已打开
                if not self._tab:
                    await self._open_page(url, timeout, new_tab)
                    self._authenticated_domain = current_domain
                
                if site_domain:
                    ChromeHelper.update_site_profile_access_time(site_domain)
                    
                return True
            except asyncio.TimeoutError as e:
                last_err = e
                log.debug("Timeout: Page did not complete loading within the timeout period.")
                try:
                    if self._tab and await self._tab.find(text="html"):
                        return True
                except Exception:
                    pass
            except Exception as err:
                last_err = err
                log.error(str(err))

            if attempt < max_retries:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 5)
                continue
            else:
                break
        return False
    
    async def inject_credentials(self, url, cookie=None, local_storage=None, reload=True):
        """
        注入cookie和localStorage，并可选刷新页面使其生效
        :param url: 站点URL（用于设置cookie的domain）
        :param cookie: Cookie字符串
        :param local_storage: LocalStorage JSON字符串
        :param reload: 注入后是否刷新页面，默认True
        """
        if not self._chrome:
            return False

        try:
            if cookie:
                cookies = self.string_to_cookie_params(cookie, url)
                if cookies:
                    await self._chrome.cookies.clear()
                    await self._chrome.connection.send(nd.cdp.storage.set_cookies(cookies))

            if local_storage:
                await self.set_local_storage(local_storage)

            if reload and self._tab:
                await self._tab.reload()
                await self._tab.wait_for(text="html", timeout=30)
                await asyncio.wait_for(self.check_document_ready(self._tab), timeout=30)

            return True
        except Exception as e:
            log.error(f"注入凭据失败: {e}")
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
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                return await self._tab.get_content()
            except Exception as err:
                log.debug(f"get_html attempt {attempt}/{max_retries} failed: {err}")
                if attempt < max_retries:
                    await asyncio.sleep(1)
        return ""

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
        
        if keep_keys is not None:
            filtered_storage = {k: v for k, v in local_storage.items() if k in keep_keys}
        elif remove_keys is not None:
            filtered_storage = {k: v for k, v in local_storage.items() if k not in remove_keys}
        else:
            filtered_storage = local_storage

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

    async def quit(self, preserve_profile=None):
        """
        退出浏览器
        :param preserve_profile: 是否保留Profile目录。如果为None，则自动判断：
                                 使用站点Profile时保留，使用临时Profile时删除
        """
        # 如果没有明确指定，根据是否使用站点Profile来决定
        if preserve_profile is None:
            preserve_profile = self._uses_site_profile
            
        if self._chrome:
            try:
                self._chrome.stop()
                # Wait for the browser process to be terminated
                end_time = time.monotonic() + 10
                while time.monotonic() < end_time:
                    if not self._chrome._process:
                        break
                    await asyncio.sleep(0.2)
            except Exception as e:
                log.error(f"Error during browser closure: {e}")
            finally:
                # Ensure the browser process is terminated
                self._cleanup_processes(preserve_profile=preserve_profile)
                self._tab = None
                self._chrome = None
                self._authenticated_domain = None

        # 释放站点Profile锁
        self.release_site_profile_lock()

    def _cleanup_processes(self, preserve_profile=False):
        """
        Ensure process teardown AND temp profile/registry cleanup always run.
        Even if the tracked PID is missing, we still remove this instance's
        temp user-data-dir (when not custom and not preserve_profile) and deregister it.
        :param preserve_profile: 是否保留Profile目录
        """
        processes_to_kill = []
        process_pid = getattr(self._chrome, "_process_pid", None) if self._chrome else None
        log.debug(f"ChromeHelper _cleanup_processes Process PID: {process_pid}")
        # Try to terminate the process tree if we have a valid PID
        if process_pid and psutil.pid_exists(process_pid):
            try:
                # Get the list of child processes before closing the Browser instance
                parent_process = psutil.Process(process_pid)
                processes_to_kill = parent_process.children(recursive=True) + [parent_process]
            except psutil.NoSuchProcess:
                processes_to_kill = []

            for proc in processes_to_kill:
                try:
                    log.debug(f"Terminating process {proc.pid} ({proc.name()})...")
                    proc.terminate()
                except psutil.NoSuchProcess:
                    pass

            if processes_to_kill:
                _, alive = psutil.wait_procs(processes_to_kill, timeout=5)

                for proc in alive:
                    try:
                        log.debug(f"Process {proc.pid} still alive, force killing...")
                        proc.kill()
                    except psutil.NoSuchProcess:
                        pass

        # 只有在不保留Profile时才删除数据目录
        if not preserve_profile:
            try:
                cfg = getattr(self._chrome, 'config', None)
                uses_custom = getattr(cfg, 'uses_custom_data_dir', True)
                data_dir = getattr(cfg, 'user_data_dir', None)
                log.debug(f"Removing temp directory {data_dir}")
                if data_dir and not uses_custom:
                    shutil.rmtree(data_dir, ignore_errors=True)
            except Exception:
                pass
        else:
            log.debug("Preserving browser profile directory")
            
        try:
            nd.util.get_registered_instances().discard(self._chrome)
        except Exception:
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
        # After killing processes, remove temp profiles and clear Nodriver's registry to avoid residual growth
        try:
            nd.util.deconstruct_browser()
        except Exception:
            pass
        try:
            reg = nd.util.get_registered_instances()
            reg.clear()
        except Exception:
            pass
        # Finally, prune any old temp user-data dirs not in use
        try:
            ChromeHelper.prune_chrome_leftovers()
        except Exception:
            pass

    @staticmethod
    def prune_chrome_leftovers(max_age_minutes: int = 120) -> dict:
        """
        Safely prune only stopped or orphaned Nodriver instances and uc_* temp profiles,
        without touching any currently running Chrome/Chromium processes.

        - Never kills processes.
        - Never removes user_data_dir that is currently in use by any running process.
        - Only removes temp profiles (uses_custom_data_dir == False) older than max_age_minutes.

        Returns summary dict with deleted_dirs, pruned_instances, in_use.
        """
        # Collect in-use user-data-dirs from all running chrome/chromium processes
        in_use_dirs = set()
        for proc in psutil.process_iter(attrs=['pid', 'name', 'cmdline']):
            try:
                name = (proc.info.get('name') or '').lower()
                if 'chrome' in name or 'chromium' in name:
                    for arg in (proc.info.get('cmdline') or []):
                        if isinstance(arg, str) and arg.startswith('--user-data-dir='):
                            in_use_dirs.add(os.path.normpath(arg.split('=', 1)[1]))
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        deleted_dirs = []
        pruned_instances = 0

        # Prune only stopped instances from Nodriver registry
        try:
            reg = nd.util.get_registered_instances()
            for inst in list(reg):
                alive = False
                try:
                    pid = getattr(inst, '_process_pid', None)
                    alive = bool(pid) and psutil.pid_exists(pid)
                except Exception:
                    pass
                
                if not alive:
                    # Remove temp profile if not custom and not in use
                    try:
                        cfg = getattr(inst, 'config', None)
                        data_dir = getattr(cfg, 'user_data_dir', None)
                        uses_custom = getattr(cfg, 'uses_custom_data_dir', True)
                        if data_dir and not uses_custom:
                            norm = os.path.normpath(data_dir)
                            if norm not in in_use_dirs and ChromeHelper._dir_older_than(norm, max_age_minutes):
                                shutil.rmtree(norm, ignore_errors=True)
                                deleted_dirs.append(norm)
                    except Exception:
                        pass
                    try:
                        reg.discard(inst)
                        pruned_instances += 1
                    except Exception:
                        pass
        except Exception as e:
            log.error(f"Failed to clean nodriver registry: {e}")

        # Prune orphan uc_* temp dirs in system temp that are not in use
        try:
            for name in os.listdir(tempfile.gettempdir()):
                if name.startswith('uc_'):
                    path = os.path.join(tempfile.gettempdir(), name)
                    if os.path.isdir(path):
                        norm = os.path.normpath(path)
                        if norm not in in_use_dirs and ChromeHelper._dir_older_than(norm, max_age_minutes):
                            try:
                                shutil.rmtree(norm, ignore_errors=True)
                                deleted_dirs.append(norm)
                            except Exception:
                                pass
        except Exception as e:
            log.error(f"Failed to scan system temp directory: {e}")

        if deleted_dirs or pruned_instances:
            log.debug(f"Chrome cleanup completed: deleted {len(deleted_dirs)} dirs, pruned {pruned_instances} instances")
        
        return {'deleted_dirs': deleted_dirs, 'pruned_instances': pruned_instances, 'in_use': list(in_use_dirs)}

    @staticmethod
    def _dir_older_than(path: str, max_age_minutes: int) -> bool:
        """
        检查目录是否超过指定年龄
        
        :param path: 目录路径
        :param max_age_minutes: 最大年龄（分钟）
        :return: True 如果目录存在且超过指定年龄
        """
        if not os.path.exists(path):
            return False
            
        try:
            mtime = os.path.getmtime(path)
        except Exception:
            return False
            
        age_sec = max(0, time.time() - mtime)
        age_threshold = max_age_minutes * 60
        
        return age_sec >= age_threshold

class RetryBrowser(Browser):
    @staticmethod
    async def _start_with_long_wait(instance: "RetryBrowser"):
        # Ensure host/port configured (connect_existing=False path)
        if instance.config.host is None or instance.config.port is None:
            instance.config.host = "127.0.0.1"
            instance.config.port = nd.util.free_port()

        # Build executable and params
        exe = instance.config.browser_executable_path
        params = instance.config()

        # Spawn process
        instance._process = await asyncio.create_subprocess_exec(
            exe,
            *params,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            close_fds=is_posix,
        )
        instance._process_pid = instance._process.pid

        # Prepare HTTP API and registry
        from nodriver.core.browser import HTTPApi
        instance._http = HTTPApi((instance.config.host, instance.config.port))
        nd.util.get_registered_instances().add(instance)

        # Poll /json/version up to 30s; then parse stderr for DevTools URL
        info_json = None
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            try:
                info_json = await instance._http.get("version")
                if info_json and info_json.get("webSocketDebuggerUrl"):
                    break
            except Exception:
                pass
            await asyncio.sleep(0.5)

        if not info_json or not info_json.get("webSocketDebuggerUrl"):
            ws_url = ""
            pattern = re.compile(r"DevTools listening on (ws://[^\s]+)")
            stderr_deadline = time.monotonic() + 10.0
            while time.monotonic() < stderr_deadline and not ws_url:
                try:
                    line = await asyncio.wait_for(instance._process.stderr.readline(), timeout=0.5)
                    if not line:
                        continue
                    try:
                        s = line.decode(errors="ignore")
                    except Exception:
                        s = str(line)
                    m = pattern.search(s)
                    if m:
                        ws_url = m.group(1)
                        break
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    break
            if not ws_url:
                raise Exception("DevTools endpoint not available")
            info_json = {"webSocketDebuggerUrl": ws_url}

        # Establish websocket connection and enable target discovery
        ws_url = info_json.get("webSocketDebuggerUrl") if isinstance(info_json, dict) else ""
        try:
            instance.info = nd.ContraDict(info_json, silent=True)
        except Exception:
            instance.info = info_json if isinstance(info_json, dict) else {"webSocketDebuggerUrl": ws_url}
        instance.connection = nd.Connection(ws_url or getattr(instance.info, 'webSocketDebuggerUrl', ''), browser=instance)
        if instance.config.autodiscover_targets:
            instance.connection.handlers[nd.cdp.target.TargetInfoChanged] = [instance._handle_target_update]
            instance.connection.handlers[nd.cdp.target.TargetCreated] = [instance._handle_target_update]
            instance.connection.handlers[nd.cdp.target.TargetDestroyed] = [instance._handle_target_update]
            instance.connection.handlers[nd.cdp.target.TargetCrashed] = [instance._handle_target_update]
            await instance.connection.send(nd.cdp.target.set_discover_targets(discover=True))

        # Ensure we have at least one page target
        await instance.update_targets()
        end_time = time.monotonic() + 5
        while not any(getattr(t, 'type_', None) == 'page' for t in instance.targets):
            if time.monotonic() >= end_time:
                break
            await asyncio.sleep(0.1)
            await instance.update_targets()

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
                # serialize critical section of spawn and port selection across threads/loops
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, _SPAWN_THREAD_LOCK.acquire)
                try:
                    await cls._start_with_long_wait(instance)
                finally:
                    _SPAWN_THREAD_LOCK.release()
                log.debug(f"RetryBrowser create instance._process_pid: {instance._process_pid}")
                return instance
            except Exception as e:
                retries += 1
                log.debug(f"Failed to start browser, attempt {retries}/{max_retries}: {e}")
                if hasattr(instance, '_process') and instance._process:
                    await RetryBrowser._cleanup_process(instance)
                instance._process = None
                instance._process_pid = None
                try:
                    nd.util.get_registered_instances().discard(instance)
                except Exception:
                    pass
                await asyncio.sleep(retry_interval)
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
        # Remove only this instance's temp profile (if not custom) and deregister it safely
        try:
            cfg = getattr(instance, 'config', None)
            uses_custom = getattr(cfg, 'uses_custom_data_dir', True)
            data_dir = getattr(cfg, 'user_data_dir', None)
            log.debug(f"Removing temp directory {data_dir}")
            if data_dir and not uses_custom:
                shutil.rmtree(data_dir, ignore_errors=True)
        except Exception:
            pass
        try:
            nd.util.get_registered_instances().discard(instance)
        except Exception:
            pass

def init_chrome():
    """
    初始化chrome驱动
    """
    ChromeHelper().init_driver()
    # 清理过期的站点Profile
    try:
        ChromeHelper.cleanup_expired_site_profiles()
    except Exception as e:
        log.debug(f"清理过期站点Profile时出错: {e}")
