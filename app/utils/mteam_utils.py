from urllib.parse import urlparse

from app.utils import RequestUtils, StringUtils
from config import Config

from pathlib import Path
import datetime
import asyncio
import shutil

class MteamUtils:
    _local_keep_keys = ['apiHost', 'auth', 'did', 'persist:persist', 'persist:torrent', 'persist:user', 'visitorId']
    _local_remove_keys = ['lastCheckTime', 'user.setLastUpdate']

    @staticmethod
    def get_api_url(url):
        from urllib.parse import urlparse
        parsed_url = urlparse(url)
        index = parsed_url.hostname.index('m-team')
        last_domain = parsed_url.hostname[index:]
        return str(parsed_url.scheme) + "://" + 'api.' + last_domain

    @staticmethod
    def get_mteam_torrent_info(torrent_url, ua=None, proxy=False):
        api = "%s/api/torrent/detail"
        api = api % MteamUtils.get_api_url(torrent_url)
        torrent_id = torrent_url.split('/')[-1]
        req = MteamUtils.buildRequestUtils(api_key=MteamUtils.get_api_key(torrent_url), headers=ua, proxies=proxy).post_res(url=api, params={"id": torrent_id})

        if req and req.status_code == 200:
            return req.json().get("data")

        return None

    @staticmethod
    def test_connection(site_info):
        api = "%s/api/member/profile"
        site_url = site_info.get("signurl")
        api = api % MteamUtils.get_api_url(site_url)
        site_api_key = site_info.get("api_key")
        ua = site_info.get("ua")
        res = MteamUtils.buildRequestUtils(
            headers=ua,
            api_key=site_api_key,
            proxies=Config().get_proxies() if site_info.get("proxy") else None,
            timeout=15
        ).post_res(url=api)
        if res:
            if res.status_code == 200:
                user_info = res.json()
                if user_info and user_info.get("data"):
                    return True, "连接成功"
            else:
                return False, "连接失败：" + str(res.status_code)
        return False, "连接失败"

    @staticmethod
    async def check_file_downloaded(directory_path: Path, file_extension: str, timeout: int = 20):
        """
        检查目录中是否有指定扩展名的文件，并返回文件路径。
        
        :param directory_path: 要检查的目录路径
        :param file_extension: 文件扩展名，如 '.torrent'
        :param timeout: 等待文件下载完成的超时时间，单位为秒
        :return: 下载完成的文件路径，如果超时则返回 None
        """
        start_time = datetime.datetime.now()
        while True:
            for file in directory_path.glob(f"*{file_extension}"):
                if file.is_file():
                    return file
            if (datetime.datetime.now() - start_time).total_seconds() > timeout:
                return None
            await asyncio.sleep(1)
            
    @staticmethod
    async def get_mteam_torrent_web(url, ua=None, proxy=False, download_path=None):
        from app.helper import ChromeHelper
        chrome = ChromeHelper()
        if not chrome.get_status():
            return None, None
        
        # 使用浏览器获取HTML文本
        if not await chrome.visit(url=url,
                            local_storage=MteamUtils.get_local_storage(url),
                            ua=ua,
                            proxy=proxy):
            await chrome.quit()
            return None, None

        # Mt_dialog = await chrome._tab.find(text="//div[@role='dialog']", timeout=3)
        # if Mt_dialog:
        #     Mt_dialog_ok = await chrome._tab.find(text="//div[@role='dialog']//div[@class='ant-modal-footer !text-center']//button[@type='button' and not(@disabled)]")
        #     await Mt_dialog_ok.mouse_move()
        #     await Mt_dialog_ok.mouse_click()

        download_button = await chrome._tab.find(text="//button[@type='button' and .//span[@aria-label='download'] and .//span[text()='下載']]")
        if not download_button:
            await chrome.quit()
            return None, None
        if download_path == None:
            download_path = Path.cwd() / "downloads"
            download_path.mkdir(exist_ok=True)
        else:
            download_path = Path(download_path)
        now = datetime.datetime.now()
        directory_path = download_path / f"{now.strftime('%Y-%m-%d_%H-%M-%S')}-{now.microsecond // 1000:03d}"
        directory_path.mkdir(exist_ok=True)
        await chrome._tab.set_download_path(directory_path)
        await download_button.click()

        torrent = await MteamUtils.check_file_downloaded(directory_path, '.torrent')
        new_torrent_path = None
        torrent_content = None
        if torrent:
            new_torrent_path = download_path / torrent.name
            shutil.move(torrent, new_torrent_path)
            with open(new_torrent_path, 'rb') as f:
                torrent_content = f.read()
            
        directory_path.rmdir()
        await chrome.quit()
        return new_torrent_path, torrent_content
    
    @staticmethod
    def get_mteam_torrent_url(url, ua=None, referer=None, proxy=False):
        if url.find('api/rss/dl') != -1:
            return url
        if MteamUtils.get_api_key(url):
            api = "%s/api/torrent/genDlToken"
            api = api % MteamUtils.get_api_url(url)
            from urllib.parse import urlparse
            parsed_url = urlparse(url)
            torrent_id = parsed_url.path.split('/')[-1]

            req = MteamUtils.buildRequestUtils(
                headers=ua,
                api_key=MteamUtils.get_api_key(url),
                referer=referer,
                proxies=Config().get_proxies() if proxy else None
            ).post_res(url=api, params={"id": torrent_id})

            if req and req.status_code == 200:
                return req.json().get("data")

        return None

    @staticmethod
    def get_mteam_torrent_req(url, ua=None, referer=None, proxy=False):
        req = MteamUtils.buildRequestUtils(
            api_key=MteamUtils.get_api_key(url),
            headers=ua,
            referer=referer,
            proxies=Config().get_proxies() if proxy else None
        ).get_res(url=url, allow_redirects=True)

        return req

    @staticmethod
    def get_api_key(url):
        from app.sites import Sites
        sites = Sites()
        site_info = sites.get_sites(siteurl=url)
        if site_info:
            api_key = site_info.get("api_key")

            if api_key:
                return api_key

        return None
    
    @staticmethod
    def get_local_storage(url):
        from app.sites import Sites
        sites = Sites()
        site_info = sites.get_sites(siteurl=url)
        if site_info:
            local_storage = site_info.get("local_storage")

            if local_storage:
                return local_storage

        return None

    @staticmethod
    def buildRequestUtils(cookies=None, api_key=None, headers=None, proxies=False, content_type=None, accept_type=None, session=None, referer=None, timeout=30):
        if api_key:
            # use api key
            return RequestUtils(headers=headers, api_key=api_key, timeout=timeout, referer=referer,
                                content_type=content_type, session=session, accept_type=accept_type,
                                proxies=Config().get_proxies() if proxies else None)
        return RequestUtils(headers=headers, cookies=cookies, timeout=timeout, referer=referer,
                            content_type=content_type, session=session, accept_type=accept_type,
                            proxies=Config().get_proxies() if proxies else None)

