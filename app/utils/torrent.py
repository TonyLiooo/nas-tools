import datetime
import os.path
import time
import re
import tempfile
import hashlib
from urllib.parse import quote, unquote, urlencode, urlparse

import libtorrent
from bencode import bencode, bdecode

import log
from app.utils import StringUtils
from app.utils.mteam_utils import MteamUtils
from app.utils.http_utils import RequestUtils
from app.utils.types import MediaType
from config import Config

import asyncio
from typing import List, Callable


class Torrent:
    _torrent_temp_path = None

    def __init__(self):
        self._torrent_temp_path = Config().get_temp_path()
        if not os.path.exists(self._torrent_temp_path):
            os.makedirs(self._torrent_temp_path, exist_ok=True)

    def get_torrent_info(self, url, cookie=None, ua=None, referer=None, proxy=False):
        """
        把种子下载到本地，返回种子内容
        :param url: 种子链接
        :param cookie: 站点Cookie
        :param ua: 站点UserAgent
        :param referer: 关联地址，有的网站需要这个否则无法下载
        :param proxy: 是否使用内置代理
        :return: 种子保存路径、种子内容、种子文件列表主目录、种子文件列表、错误信息
        """
        if not url:
            return None, None, "", [], "URL为空"
        if url.startswith("magnet:"):
            return None, url, "", [], f"{url} 为磁力链接"
        try:
            # 下载保存种子文件
            file_path, content, errmsg = self.save_torrent_file(url=url,
                                                                cookie=cookie,
                                                                ua=ua,
                                                                referer=referer,
                                                                proxy=proxy)
            if not file_path:
                return None, content, "", [], errmsg
            # 解析种子文件
            files_folder, files, retmsg = self.get_torrent_files(file_path)
            # 种子文件路径、种子内容、种子文件列表主目录、种子文件列表、错误信息
            return file_path, content, files_folder, files, retmsg

        except Exception as err:
            return None, None, "", [], "下载种子文件出现异常：%s" % str(err)

    def save_torrent_file(self, url, cookie=None, ua=None, referer=None, proxy=False):
        """
        把种子下载到本地
        :return: 种子保存路径，错误信息
        """
        if url.find("m-team") != -1:
            web_url = url
            url = MteamUtils.get_mteam_torrent_url(url, ua, referer, proxy)
            if not url:
                if MteamUtils.get_local_storage(web_url):
                    file_path, file_conten = asyncio.run(MteamUtils.get_mteam_torrent_web(web_url, ua=ua, proxy=proxy, download_path=self._torrent_temp_path))
                if file_path:
                    return file_path, file_conten, ""
                return None, url, f"mteam 种子链接获取出错，详情地址为 {url}"
            req = MteamUtils.get_mteam_torrent_req(url, ua, referer, proxy)
        else:
            req = RequestUtils(
                headers=ua,
                cookies=cookie,
                referer=referer,
                proxies=Config().get_proxies() if proxy else None
            ).get_res(url=url, allow_redirects=False)
        while req and req.status_code in [301, 302]:
            url = req.headers['Location']
            if url and url.startswith("magnet:"):
                return None, url, f"获取到磁力链接：{url}"
            req = RequestUtils(
                headers=ua,
                cookies=cookie,
                referer=referer,
                proxies=Config().get_proxies() if proxy else None
            ).get_res(url=url, allow_redirects=False)
        if req and req.status_code == 200:
            if not req.content:
                return None, None, "未下载到种子数据"
            # 解析内容格式
            if req.text and str(req.text).startswith("magnet:"):
                # 磁力链接
                return None, req.text, "磁力链接"
            elif req.text and "下载种子文件" in req.text:
                # 首次下载提示页面
                skip_flag = False
                try:
                    form = re.findall(r'<form.*?action="(.*?)".*?>(.*?)</form>', req.text, re.S)
                    if form:
                        action = form[0][0]
                        if not action or action == "?":
                            action = url
                        elif not action.startswith('http'):
                            action = StringUtils.get_base_url(url) + action
                        inputs = re.findall(r'<input.*?name="(.*?)".*?value="(.*?)".*?>', form[0][1], re.S)
                        if action and inputs:
                            data = {}
                            for item in inputs:
                                data[item[0]] = item[1]
                            # 改写req
                            req = RequestUtils(
                                headers=ua,
                                cookies=cookie,
                                referer=referer,
                                proxies=Config().get_proxies() if proxy else None
                            ).post_res(url=action, data=data)
                            if req and req.status_code == 200:
                                # 检查是不是种子文件，如果不是抛出异常
                                bdecode(req.content)
                                # 跳过成功
                                log.info(f"【Downloader】触发了站点首次种子下载，已自动跳过：{url}")
                                skip_flag = True
                            elif req is not None:
                                log.warn(f"【Downloader】触发了站点首次种子下载，且无法自动跳过，"
                                         f"返回码：{req.status_code}，错误原因：{req.reason}")
                            else:
                                log.warn(f"【Downloader】触发了站点首次种子下载，且无法自动跳过：{url}")
                except Exception as err:
                    log.warn(f"【Downloader】触发了站点首次种子下载，尝试自动跳过时出现错误：{str(err)}，链接：{url}")

                if not skip_flag:
                    return None, None, "种子数据有误，请确认链接是否正确，如为PT站点则需手工在站点下载一次种子"
            else:
                # 检查是不是种子文件，如果不是仍然抛出异常
                try:
                    bdecode(req.content)
                except Exception as err:
                    print(str(err))
                    return None, None, "种子数据有误，请确认链接是否正确"
            # 读取种子文件名
            file_name = self.__get_url_torrent_filename(req, url)
            # 种子文件路径
            file_path = os.path.join(self._torrent_temp_path, file_name)
            # 种子内容
            file_content = req.content
            # 写入磁盘
            with open(file_path, 'wb') as f:
                f.write(file_content)
        elif req is None:
            return None, None, "无法打开链接：%s" % url
        elif req.status_code == 429:
            return None, None, "触发站点流控，请稍后重试"
        else:
            return None, None, "下载种子出错，状态码：%s" % req.status_code

        return file_path, file_content, ""

    @staticmethod
    def get_torrent_files(path):
        """
        解析Torrent文件，获取文件清单
        :return: 种子文件列表主目录、种子文件列表、错误信息
        """
        if not path or not os.path.exists(path):
            return "", [], f"种子文件不存在：{path}"
        file_names = []
        file_folder = ""
        try:
            torrent = bdecode(open(path, 'rb').read())
            if torrent.get("info"):
                files = torrent.get("info", {}).get("files") or []
                if files:
                    for item in files:
                        if item.get("path"):
                            file_names.append(item["path"][0])
                    file_folder = torrent.get("info", {}).get("name")
                else:
                    file_names.append(torrent.get("info", {}).get("name"))
        except Exception as err:
            return file_folder, file_names, "解析种子文件异常：%s" % str(err)
        return file_folder, file_names, ""

    def read_torrent_content(self, path):
        """
        读取本地种子文件的内容
        :return: 种子内容、种子文件列表主目录、种子文件列表、错误信息
        """
        if not path or not os.path.exists(path):
            return None, "", [], "种子文件不存在：%s" % path
        content, retmsg, file_folder, files = None, "", "", []
        try:
            # 读取种子文件内容
            with open(path, 'rb') as f:
                content = f.read()
            # 解析种子文件
            file_folder, files, retmsg = self.get_torrent_files(path)
        except Exception as e:
            retmsg = "读取种子文件出错：%s" % str(e)
        return content, file_folder, files, retmsg

    @staticmethod
    def __get_url_torrent_filename(req, url):
        """
        从下载请求中获取种子文件名
        """
        if not req:
            return ""
        disposition = req.headers.get('content-disposition') or ""
        file_name = re.findall(r"filename=\"?(.+)\"?", disposition)
        if file_name:
            file_name = unquote(str(file_name[0].encode('ISO-8859-1').decode()).split(";")[0].strip())
            if file_name.endswith('"'):
                file_name = file_name[:-1]
        elif url and url.endswith(".torrent"):
            file_name = unquote(url.split("/")[-1])
        else:
            file_name = str(datetime.datetime.now())
        return file_name.replace('/', '')

    @staticmethod
    def get_intersection_episodes(target, source, title):
        """
        对两个季集字典进行判重，有相同项目的取集的交集
        """
        if not source or not title:
            return target
        if not source.get(title):
            return target
        if not target.get(title):
            target[title] = source.get(title)
            return target
        index = -1
        for target_info in target.get(title):
            index += 1
            source_info = None
            for info in source.get(title):
                if info.get("season") == target_info.get("season"):
                    source_info = info
                    break
            if not source_info:
                continue
            if not source_info.get("episodes"):
                continue
            if not target_info.get("episodes"):
                target_episodes = source_info.get("episodes")
                target[title][index]["episodes"] = target_episodes
                continue
            target_episodes = list(set(target_info.get("episodes")).intersection(set(source_info.get("episodes"))))
            target[title][index]["episodes"] = target_episodes
        return target

    @staticmethod
    def filter_media_list(media_list: List, filters: List[Callable]) -> List:
        """
        筛选媒体列表
        :param media_list: 原始媒体列表
        :param filters: 筛选条件列表，每个条件是一个函数，接受媒体对象，返回布尔值
        :return: 筛选后的媒体列表
        """
        for filter_func in filters:
            media_list = filter(filter_func, media_list)
        return list(media_list)

    @staticmethod
    def has_promotion_priority(priority_filter: str) -> Callable:
        """
        根据输入的优先级筛选条件筛选媒体列表。
        :param priority_filter: 支持 "<3"、">3"、"0-3" 等形式。
        :return: 返回筛选条件的函数。
        """
        def filter_by_priority(media):
            priority = media.get_promotion_priority()
            try:
                if "-" in priority_filter:
                    # 区间筛选，格式如 "0-3"
                    min_priority, max_priority = map(int, priority_filter.split("-"))
                    return min_priority <= priority <= max_priority
                elif priority_filter.startswith("<"):
                    # 小于某个值
                    max_priority = int(priority_filter[1:])
                    return priority < max_priority
                elif priority_filter.startswith(">"):
                    # 大于某个值
                    min_priority = int(priority_filter[1:])
                    return priority > min_priority
                else:
                    # 等于某个值（默认）
                    return priority == int(priority_filter)
            except ValueError:
                # 如果解析失败，不筛选任何媒体
                return False

        return filter_by_priority

    @staticmethod
    def is_specific_site(site_list: list) -> Callable:
        """筛选指定站点的媒体"""
        return lambda media: media.site in site_list

    @staticmethod
    def filter_by_season_and_episode(season_list: List[int], episode_list: List[int]) -> Callable:
        """
        返回基于季和集的筛选函数
        :param season_list: 要匹配的季列表。如果为空，则表示不限制季。
        :param episode_list: 要匹配的集列表。如果为空，则表示不限制集。
        :return: 一个筛选函数，接受媒体对象，返回布尔值
        """
        def filter_func(media):
            media_seasons = set(media.get_season_list())
            media_episodes = set(media.get_episode_list())

            # 如果季列表非空，检查交集；否则不限制
            if media_seasons and season_list and not media_seasons.intersection(season_list):
                return False

            # 如果集列表非空，检查交集；否则不限制
            if media_episodes and episode_list and not media_episodes.intersection(episode_list):
                return False

            return True

        return filter_func
    
    @staticmethod
    def sort_media_list(media_list, download_order=None):
        """
        排序媒体列表
        """
        # 排序函数，标题、站点、资源类型、做种数量
        def get_sort_tuple(media):
            season = media.get_season_string() or "ZZZ"
            episode = media.get_episode_string() or "ZZZ"
            # 排序元组：标题、资源类型、站点、做种、季集
            if download_order == "seeder":
                return (
                    media.title,                            # 按标题排序
                    (season, episode),                      # 按季、集排序
                    int(media.res_order),                   # 按资源优先级排序
                    int(media.get_promotion_priority()),    # 按促销优先级排序
                    -int(media.seeders),                    # 按做种人数降序
                    -int(media.peers),                      # 按下载人数降序
                    int(media.site_order),                  # 按站点优先级排序
                )
            else:
                return (
                    media.title,                            # 按标题排序
                    (season, episode),                      # 按季、集排序
                    int(media.res_order),                   # 按资源优先级排序
                    int(media.get_promotion_priority()),    # 按促销优先级排序
                    int(media.site_order),                  # 按站点优先级排序
                    -int(media.seeders),                    # 按做种人数降序
                    -int(media.peers),                      # 按下载人数降序
                )
        return sorted(media_list, key=get_sort_tuple, reverse=True)
    
    @staticmethod
    def get_download_list(media_list, download_order):
        """
        对媒体信息进行排序、去重
        """
        if not media_list:
            return []
        
        # 按排序规则对媒体列表排序
        media_list = Torrent.sort_media_list(media_list, download_order)

        # 去重处理
        unique_media_list = []
        seen_media_names = set()

        for media in media_list:
            # 控重的主键是标题 + 季集（如果有）
            if media.type == MediaType.MOVIE:
                media_name = media.get_title_string()
            else:
                media_name = f"{media.get_title_string()}{media.get_season_episode_string()}"

            # 避免重复添加
            if media_name not in seen_media_names:
                seen_media_names.add(media_name)
                unique_media_list.append(media)

        return unique_media_list

    @staticmethod
    def magent2torrent(url, path, timeout=20):
        """
        磁力链接转种子文件
        :param url: 磁力链接
        :param path: 保存目录
        :param timeout: 获取元数据超时时间
        :return: 转换后种子路径
        """

        log.info(f"【Downloader】转换磁力链接：{url}")
        session = libtorrent.session()
        magnet_info = libtorrent.parse_magnet_uri(url)
        magnet_info.save_path = path
        handle = session.add_torrent(magnet_info)

        log.debug("【Downloader】获取元数据中")
        tout = 0
        while not handle.status().name:
            time.sleep(1)
            tout += 1
            if tout > timeout:
                log.debug("【Downloader】元数据获取超时")
                return None, "种子元数据获取超时"
        session.pause()

        log.debug("【Downloader】获取元数据完成")
        tf = handle.torrent_file()
        ti = libtorrent.torrent_info(tf)
        torrent_file = libtorrent.create_torrent(ti)
        torrent_file.set_comment(ti.comment())
        torrent_file.set_creator(ti.creator())

        file_path = os.path.join(path, "%s.torrent" % handle.status().name)

        with open(file_path, 'wb') as f_handle:
            f_handle.write(libtorrent.bencode(torrent_file.generate()))
            f_handle.close()

        session.remove_torrent(handle, 1)
        log.info(f"【Downloader】转换后的种子路径：{file_path}")
        return file_path, ""

    @staticmethod
    def _write_binary_to_temp_file(binary_data):
        """
        种子内容转种子文件
        :param binary_data: 种子内容
        :return: 转换后种子路径
        """
        try:
            temp_file = tempfile.NamedTemporaryFile(delete=False)
            temp_file.write(binary_data)
            temp_file.close()
            return temp_file.name
        except Exception as e:
            log.error(f"【Downloader】种子内容无法写入临时文件")
            return None

    @staticmethod
    def _parse_torrent_dict(torrent_data):
        """
        获取种子文件的信息
        :param torrent_data: 种子内容的二进制数据
        :return: 种子文件的信息
        """
        try:
            torrent_dict = bdecode(torrent_data)
            return torrent_dict
        except Exception as e:
            log.error(f"【Downloader】无法解析种子文件内容")
            return None

    @staticmethod
    def _create_magnet_link(torrent_dict):
        """
        根据种子信息生成磁力链接
        :param torrent_dict: 种子信息
        :return: 磁力链接
        """
        if torrent_dict is None:
            return None
        
        magnet_info = {}
        
        if 'info' in torrent_dict:
            info_hash = hashlib.sha1(bencode(torrent_dict['info'])).hexdigest()
            magnet_info['xt'] = 'urn:btih:' + info_hash
        
        if 'name' in torrent_dict['info']:
            magnet_info['dn'] = torrent_dict['info']['name']
        
        if 'announce' in torrent_dict:
            magnet_info['tr'] = torrent_dict['announce']
        
        if 'announce-list' in torrent_dict:
            magnet_info['tr'] = [announce[0] for announce in torrent_dict['announce-list']]

        magnet_link = 'magnet:?{}'.format(urlencode(magnet_info))
        return magnet_link

    @staticmethod
    def binary_data_to_magnet_link(binary_data):
        """
        根据种子内容生成磁力链接
        :param binary_data: 种子内容
        :return: 磁力链接
        """
        temp_file_path = Torrent._write_binary_to_temp_file(binary_data)
        if not temp_file_path:
            return None
        
        with open(temp_file_path, 'rb') as torrent_file:
            torrent_data = torrent_file.read()
            torrent_dict = Torrent._parse_torrent_dict(torrent_data)
            magnet_link = Torrent._create_magnet_link(torrent_dict)
            Torrent._close_and_delete_file(temp_file_path)
            return magnet_link

    @staticmethod
    def _close_and_delete_file(file_path):
        """
        清理临时生成的种子文件
        :param file_path: 种子文件路径
        :return: 是否删除成功
        """
        try:
            with open(file_path, 'r+') as file:
                file.close()
        except:
            pass

        try:
            os.remove(file_path)
            return True
        except Exception as e:
            return False

    @staticmethod
    def is_magnet(link):
        """
        判断是否是磁力
        """
        return link.lower().startswith("magnet:?xt=urn:btih:")

    @staticmethod        
    def maybe_torrent_url(link):
        """
        判断是否可能是种子url
        """
        try:
            parsed = urlparse(link)
            return bool(parsed.netloc) and parsed.scheme in ['http', 'https', 'ftp']
        except Exception as err:
            return False

    @staticmethod
    def format_enclosure(link):
        """
        格式化一个链接
        如果是磁力链接或者为私有PT站点则直接返回
        如果不是磁力链接看是否是种子链接，如果是则下载种子后转换为磁力链接
        """
        if not StringUtils.is_string_and_not_empty(link):
            return None
        if Torrent.is_magnet(link):
            return link
        if not Torrent.maybe_torrent_url(link):
            return None

        _, torrent_content, _, _, retmsg = Torrent().get_torrent_info(link)
        if not torrent_content:
            print(f"下载种子文件出错: {retmsg}")
            return None
        return torrent_content
