import base64
import datetime
import importlib
import inspect
import json
import os.path
import re
import shutil
import signal
import sqlite3
import time
from math import floor
from pathlib import Path
from urllib.parse import unquote
import ast
import copy

import cn2an
from flask_login import logout_user, current_user
from werkzeug.security import generate_password_hash

import log
from app.brushtask import BrushTask
from app.conf import SystemConfig, ModuleConf
from app.downloader import Downloader
from app.filetransfer import FileTransfer
from app.filter import Filter
from app.helper import DbHelper, ProgressHelper, ThreadHelper, \
    MetaHelper, DisplayHelper, WordsHelper
from app.helper import RssHelper, PluginHelper, ChromeHelper
from app.indexer import Indexer
from app.media import Category, Media, Bangumi, DouBan, Scraper
from app.media.meta import MetaInfo, MetaBase
from app.mediaserver import MediaServer
from app.message import Message, MessageCenter
from app.plugins import PluginManager, EventManager
from app.rss import Rss
from app.rsschecker import RssChecker
from app.scheduler import Scheduler
from app.searcher import Searcher
from app.sites import Sites, SiteUserInfo, SiteCookie, SiteConf
from app.subscribe import Subscribe
from app.sync import Sync
from app.torrentremover import TorrentRemover
from app.utils import StringUtils, EpisodeFormat, RequestUtils, PathUtils, \
    SystemUtils, ExceptionUtils, Torrent
from app.utils.types import RmtMode, OsType, SearchType, SyncType, MediaType, MovieTypes, TvTypes, \
    EventType, SystemConfigKey, RssType
from app.utils.time_utils import TimeUtils
from config import RMT_MEDIAEXT, RMT_SUBEXT, RMT_AUDIO_TRACK_EXT, Config
from web.backend.search_torrents import search_medias_for_web, search_media_by_message
from web.backend.pro_user import ProUser
from web.backend.web_utils import WebUtils

import asyncio

class WebAction:
    _actions = {}
    _commands = {}

    def __init__(self):
        # WEB请求响应
        self._actions = {
            "sch": self.__sch,
            "search": self.__search,
            "download": self.__download,
            "download_link": self.__download_link,
            "download_torrent": self.__download_torrent,
            "pt_start": self.__pt_start,
            "pt_stop": self.__pt_stop,
            "pt_remove": self.__pt_remove,
            "pt_info": self.__pt_info,
            "del_unknown_path": self.__del_unknown_path,
            "rename": self.__rename,
            "rename_udf": self.__rename_udf,
            "delete_history": self.delete_history,
            "version": self.__version,
            "update_site": self.__update_site,
            "get_site": self.__get_site,
            "del_site": self.__del_site,
            "get_site_favicon": self.__get_site_favicon,
            "restart": self.__restart,
            "update_system": self.update_system,
            "reset_db_version": self.__reset_db_version,
            "logout": self.__logout,
            "update_config": self.__update_config,
            "update_directory": self.__update_directory,
            "add_or_edit_sync_path": self.__add_or_edit_sync_path,
            "get_sync_path": self.get_sync_path,
            "delete_sync_path": self.__delete_sync_path,
            "check_sync_path": self.__check_sync_path,
            "remove_rss_media": self.__remove_rss_media,
            "add_rss_media": self.__add_rss_media,
            "re_identification": self.re_identification,
            "media_info": self.__media_info,
            "test_connection": self.__test_connection,
            "user_manager": self.__user_manager,
            "refresh_rss": self.__refresh_rss,
            "delete_tmdb_cache": self.__delete_tmdb_cache,
            "movie_calendar_data": self.__movie_calendar_data,
            "tv_calendar_data": self.__tv_calendar_data,
            "modify_tmdb_cache": self.__modify_tmdb_cache,
            "rss_detail": self.__rss_detail,
            "truncate_blacklist": self.truncate_blacklist,
            "truncate_rsshistory": self.truncate_rsshistory,
            "add_brushtask": self.__add_brushtask,
            "del_brushtask": self.__del_brushtask,
            "brushtask_enable": self.__brushtask_enable,
            "brushtask_detail": self.__brushtask_detail,
            "update_brushtask_state": self.__update_brushtask_state,
            "name_test": self.__name_test,
            "rule_test": self.__rule_test,
            "net_test": self.__net_test,
            "add_filtergroup": self.__add_filtergroup,
            "restore_filtergroup": self.__restore_filtergroup,
            "set_default_filtergroup": self.__set_default_filtergroup,
            "del_filtergroup": self.__del_filtergroup,
            "add_filterrule": self.__add_filterrule,
            "del_filterrule": self.__del_filterrule,
            "filterrule_detail": self.__filterrule_detail,
            "get_site_activity": self.__get_site_activity,
            "get_site_history": self.__get_site_history,
            "get_recommend": self.get_recommend,
            "get_downloaded": self.get_downloaded,
            "get_site_seeding_info": self.__get_site_seeding_info,
            "clear_tmdb_cache": self.__clear_tmdb_cache,
            "check_site_attr": self.__check_site_attr,
            "refresh_process": self.refresh_process,
            "restory_backup": self.__restory_backup,
            "start_mediasync": self.__start_mediasync,
            "start_mediaDisplayModuleSync": self.__start_mediaDisplayModuleSync,
            "mediasync_state": self.__mediasync_state,
            "get_tvseason_list": self.__get_tvseason_list,
            "get_userrss_task": self.__get_userrss_task,
            "delete_userrss_task": self.__delete_userrss_task,
            "update_userrss_task": self.__update_userrss_task,
            "check_userrss_task": self.__check_userrss_task,
            "get_rssparser": self.__get_rssparser,
            "delete_rssparser": self.__delete_rssparser,
            "update_rssparser": self.__update_rssparser,
            "run_userrss": self.__run_userrss,
            "run_brushtask": self.__run_brushtask,
            "list_site_resources": self.list_site_resources,
            "list_rss_articles": self.__list_rss_articles,
            "rss_article_test": self.__rss_article_test,
            "list_rss_history": self.__list_rss_history,
            "rss_articles_check": self.__rss_articles_check,
            "rss_articles_download": self.__rss_articles_download,
            "add_custom_word_group": self.__add_custom_word_group,
            "delete_custom_word_group": self.__delete_custom_word_group,
            "add_or_edit_custom_word": self.__add_or_edit_custom_word,
            "get_custom_word": self.__get_custom_word,
            "delete_custom_words": self.__delete_custom_words,
            "check_custom_words": self.__check_custom_words,
            "export_custom_words": self.__export_custom_words,
            "analyse_import_custom_words_code": self.__analyse_import_custom_words_code,
            "import_custom_words": self.__import_custom_words,
            "get_categories": self.get_categories,
            "re_rss_history": self.__re_rss_history,
            "delete_rss_history": self.__delete_rss_history,
            "share_filtergroup": self.__share_filtergroup,
            "import_filtergroup": self.__import_filtergroup,
            "get_transfer_statistics": self.get_transfer_statistics,
            "get_library_spacesize": self.get_library_spacesize,
            "get_library_mediacount": self.get_library_mediacount,
            "get_library_playhistory": self.get_library_playhistory,
            "get_search_result": self.get_search_result,
            "search_media_infos": self.search_media_infos,
            "get_movie_rss_list": self.get_movie_rss_list,
            "get_tv_rss_list": self.get_tv_rss_list,
            "get_rss_history": self.get_rss_history,
            "get_transfer_history": self.get_transfer_history,
            "truncate_transfer_history": self.truncate_transfer_history,
            "get_unknown_list": self.get_unknown_list,
            "get_unknown_list_by_page": self.get_unknown_list_by_page,
            "truncate_transfer_unknown": self.truncate_transfer_unknown,
            "get_customwords": self.get_customwords,
            "get_users": self.get_users,
            "get_filterrules": self.get_filterrules,
            "get_downloading": self.get_downloading,
            "test_site": self.__test_site,
            "get_sub_path": self.__get_sub_path,
            "get_filehardlinks": self.__get_filehardlinks,
            "get_dirhardlink": self.__get_dirhardlink,
            "rename_file": self.__rename_file,
            "delete_files": self.__delete_files,
            "download_subtitle": self.__download_subtitle,
            "get_download_setting": self.__get_download_setting,
            "update_download_setting": self.__update_download_setting,
            "delete_download_setting": self.__delete_download_setting,
            "update_message_client": self.__update_message_client,
            "delete_message_client": self.__delete_message_client,
            "check_message_client": self.__check_message_client,
            "get_message_client": self.__get_message_client,
            "test_message_client": self.__test_message_client,
            "get_sites": self.__get_sites,
            "get_indexers": self.__get_indexers,
            "get_download_dirs": self.__get_download_dirs,
            "find_hardlinks": self.__find_hardlinks,
            "update_sites_cookie_ua": self.__update_sites_cookie_ua,
            "update_site_cookie_ua": self.__update_site_cookie_ua,
            "set_site_captcha_code": self.__set_site_captcha_code,
            "update_torrent_remove_task": self.__update_torrent_remove_task,
            "get_torrent_remove_task": self.__get_torrent_remove_task,
            "delete_torrent_remove_task": self.__delete_torrent_remove_task,
            "get_remove_torrents": self.__get_remove_torrents,
            "auto_remove_torrents": self.__auto_remove_torrents,
            "list_brushtask_torrents": self.__list_brushtask_torrents,
            "set_system_config": self.__set_system_config,
            "get_site_user_statistics": self.get_site_user_statistics,
            "send_plugin_message": self.send_plugin_message,
            "send_custom_message": self.send_custom_message,
            "media_detail": self.media_detail,
            "media_similar": self.__media_similar,
            "media_recommendations": self.__media_recommendations,
            "media_person": self.__media_person,
            "person_medias": self.__person_medias,
            "save_user_script": self.__save_user_script,
            "run_directory_sync": self.__run_directory_sync,
            "update_plugin_config": self.__update_plugin_config,
            "get_season_episodes": self.__get_season_episodes,
            "get_user_menus": self.get_user_menus,
            "get_top_menus": self.get_top_menus,
            "auth_user_level": self.auth_user_level,
            "update_downloader": self.__update_downloader,
            "del_downloader": self.__del_downloader,
            "check_downloader": self.__check_downloader,
            "get_downloaders": self.__get_downloaders,
            "test_downloader": self.__test_downloader,
            "get_indexer_statistics": self.__get_indexer_statistics,
            "media_path_scrap": self.__media_path_scrap,
            "get_default_rss_setting": self.get_default_rss_setting,
            "get_movie_rss_items": self.get_movie_rss_items,
            "get_tv_rss_items": self.get_tv_rss_items,
            "get_ical_events": self.get_ical_events,
            "install_plugin": self.install_plugin,
            "uninstall_plugin": self.uninstall_plugin,
            "get_plugin_apps": self.get_plugin_apps,
            "get_plugin_page": self.get_plugin_page,
            "get_plugin_state": self.get_plugin_state,
            "get_plugins_conf": self.get_plugins_conf,
            "update_category_config": self.update_category_config,
            "get_category_config": self.get_category_config,
            "get_system_processes": self.get_system_processes,
            "run_plugin_method": self.run_plugin_method,
            "get_library_resume": self.__get_resume,
        }
        # 远程命令响应
        self._commands = {
            "/ptr": {"func": TorrentRemover().auto_remove_torrents, "desc": "自动删种"},
            "/ptt": {"func": Downloader().transfer, "desc": "下载文件转移"},
            "/rst": {"func": Sync().transfer_sync, "desc": "目录同步"},
            "/rss": {"func": Rss().rssdownload, "desc": "电影/电视剧订阅"},
            "/ssa": {"func": Subscribe().subscribe_search_all, "desc": "订阅搜索"},
            "/tbl": {"func": self.truncate_blacklist, "desc": "清理转移缓存"},
            "/trh": {"func": self.truncate_rsshistory, "desc": "清理RSS缓存"},
            "/utf": {"func": self.unidentification, "desc": "重新识别"},
            "/udt": {"func": self.update_system, "desc": "系统更新"},
            "/sta": {"func": self.user_statistics, "desc": "站点数据统计"}
        }

    def action(self, cmd, data):
        """
        执行WEB请求
        """
        func = self._actions.get(cmd)
        if not func:
            return {"code": -1, "msg": "非授权访问！"}
        elif inspect.signature(func).parameters:
            return func(data)
        else:
            return func(**{})

    def api_action(self, cmd, data=None):
        """
        执行API请求
        """
        result = self.action(cmd, data)
        if not result:
            return {
                "code": -1,
                "success": False,
                "message": "服务异常，未获取到返回结果"
            }
        code = result.get("code", result.get("retcode", 0))
        if not code or str(code) == "0":
            success = True
        else:
            success = False
        message = result.get("msg", result.get("retmsg", ""))
        for key in ['code', 'retcode', 'msg', 'retmsg']:
            if key in result:
                result.pop(key)
        return {
            "code": code,
            "success": success,
            "message": message,
            "data": result
        }

    @staticmethod
    def stop_service():
        """
        关闭服务
        """
        # 停止定时服务
        Scheduler().stop_service()
        # 停止监控
        Sync().stop_service()
        # 关闭虚拟显示
        DisplayHelper().stop_service()
        # 关闭刷流
        BrushTask().stop_service()
        # 关闭自定义订阅
        RssChecker().stop_service()
        # 关闭自动删种
        TorrentRemover().stop_service()
        # 关闭下载器监控
        Downloader().stop_service()
        # 关闭插件
        PluginManager().stop_service()
        # 关闭浏览器
        ChromeHelper.kill_chrome_processes()

    @staticmethod
    def start_service():
        # 加载站点配置
        SiteConf()
        # 启动虚拟显示
        DisplayHelper()
        # 启动定时服务
        Scheduler()
        # 启动监控服务
        Sync()
        # 启动刷流服务
        BrushTask()
        # 启动自定义订阅服务
        RssChecker()
        # 启动自动删种服务
        TorrentRemover()
        # 加载插件
        PluginManager()

    def restart_service(self):
        """
        重启服务
        """
        self.stop_service()
        self.start_service()

    def restart_server(self):
        """
        停止进程
        """
        # 关闭服务
        self.stop_service()
        # 重启进程
        if os.name == "nt":
            os.kill(os.getpid(), getattr(signal, "SIGKILL", signal.SIGTERM))
        elif SystemUtils.is_synology():
            os.system(
                "ps -ef | grep -v grep | grep 'python run.py'|awk '{print $2}'|xargs kill -9")
        elif SystemUtils.is_docker():
            os.system("pkill -f 'python3 run.py'")
        else:
            if SystemUtils.check_process('node'):
                os.system("pm2 restart NAStool")
            else:
                os.system("pkill -f 'python3 run.py'")

    def handle_message_job(self, msg, in_from=SearchType.OT, user_id=None, user_name=None):
        """
        处理消息事件
        """
        if not msg:
            return

        # 触发MessageIncoming事件
        EventManager().send_event(EventType.MessageIncoming, {
            "channel": in_from.value,
            "user_id": user_id,
            "user_name": user_name,
            "message": msg

        })

        # 系统内置命令
        command = self._commands.get(msg)
        if command:
            # 启动服务
            ThreadHelper().start_thread(command.get("func"), ())
            # 消息回应
            Message().send_channel_msg(
                channel=in_from, title="正在运行 %s ..." % command.get("desc"), user_id=user_id)
            return

        # 插件命令
        plugin_commands = PluginManager().get_plugin_commands()
        for command in plugin_commands:
            if command.get("cmd") == msg:
                # 发送事件
                EventManager().send_event(command.get("event"), command.get("data") or {})
                # 消息回应
                Message().send_channel_msg(
                    channel=in_from, title="正在运行 %s ..." % command.get("desc"), user_id=user_id)
                return

        # 站点搜索或者添加订阅
        ThreadHelper().start_thread(search_media_by_message,
                                    (msg, in_from, user_id, user_name))

    @staticmethod
    def set_config_value(cfg, cfg_key, cfg_value):
        """
        根据Key设置配置值
        """
        # 密码
        if cfg_key == "app.login_password":
            if cfg_value and not cfg_value.startswith("[hash]"):
                cfg['app']['login_password'] = "[hash]%s" % generate_password_hash(
                    cfg_value)
            else:
                cfg['app']['login_password'] = cfg_value or "password"
            return cfg
        # 代理
        if cfg_key == "app.proxies":
            if cfg_value:
                if not cfg_value.startswith("http") and not cfg_value.startswith("sock"):
                    cfg['app']['proxies'] = {
                        "https": "http://%s" % cfg_value, "http": "http://%s" % cfg_value}
                else:
                    cfg['app']['proxies'] = {"https": "%s" %
                                                      cfg_value, "http": "%s" % cfg_value}
            else:
                cfg['app']['proxies'] = {"https": None, "http": None}
            return cfg
        # 最大支持三层赋值
        keys = cfg_key.split(".")
        if keys:
            if len(keys) == 1:
                cfg[keys[0]] = cfg_value
            elif len(keys) == 2:
                if not cfg.get(keys[0]):
                    cfg[keys[0]] = {}
                cfg[keys[0]][keys[1]] = cfg_value
            elif len(keys) == 3:
                if cfg.get(keys[0]):
                    if not cfg[keys[0]].get(keys[1]) or isinstance(cfg[keys[0]][keys[1]], str):
                        cfg[keys[0]][keys[1]] = {}
                    cfg[keys[0]][keys[1]][keys[2]] = cfg_value
                else:
                    cfg[keys[0]] = {}
                    cfg[keys[0]][keys[1]] = {}
                    cfg[keys[0]][keys[1]][keys[2]] = cfg_value

        return cfg

    @staticmethod
    def set_config_directory(cfg, oper, cfg_key, cfg_value, update_value=None):
        """
        更新目录数据
        """

        def remove_sync_path(obj, key):
            if not isinstance(obj, list):
                return []
            ret_obj = []
            for item in obj:
                if item.split("@")[0].replace("\\", "/") != key.split("@")[0].replace("\\", "/"):
                    ret_obj.append(item)
            return ret_obj

        # 最大支持二层赋值
        keys = cfg_key.split(".")
        if keys:
            if len(keys) == 1:
                if cfg.get(keys[0]):
                    if not isinstance(cfg[keys[0]], list):
                        cfg[keys[0]] = [cfg[keys[0]]]
                    if oper == "add":
                        cfg[keys[0]].append(cfg_value)
                    elif oper == "sub":
                        cfg[keys[0]].remove(cfg_value)
                        if not cfg[keys[0]]:
                            cfg[keys[0]] = None
                    elif oper == "set":
                        cfg[keys[0]].remove(cfg_value)
                        if update_value:
                            cfg[keys[0]].append(update_value)
                else:
                    cfg[keys[0]] = cfg_value
            elif len(keys) == 2:
                if cfg.get(keys[0]):
                    if not cfg[keys[0]].get(keys[1]):
                        cfg[keys[0]][keys[1]] = []
                    if not isinstance(cfg[keys[0]][keys[1]], list):
                        cfg[keys[0]][keys[1]] = [cfg[keys[0]][keys[1]]]
                    if oper == "add":
                        cfg[keys[0]][keys[1]].append(
                            cfg_value.replace("\\", "/"))
                    elif oper == "sub":
                        cfg[keys[0]][keys[1]] = remove_sync_path(
                            cfg[keys[0]][keys[1]], cfg_value)
                        if not cfg[keys[0]][keys[1]]:
                            cfg[keys[0]][keys[1]] = None
                    elif oper == "set":
                        cfg[keys[0]][keys[1]] = remove_sync_path(
                            cfg[keys[0]][keys[1]], cfg_value)
                        if update_value:
                            cfg[keys[0]][keys[1]].append(
                                update_value.replace("\\", "/"))
                else:
                    cfg[keys[0]] = {}
                    cfg[keys[0]][keys[1]] = cfg_value.replace("\\", "/")
        return cfg

    @staticmethod
    def __sch(data):
        """
        启动服务
        """
        commands = {
            "pttransfer": Downloader().transfer,
            "sync": Sync().transfer_sync,
            "rssdownload": Rss().rssdownload,
            "subscribe_search_all": Subscribe().subscribe_search_all,
        }
        sch_item = data.get("item")
        if sch_item and commands.get(sch_item):
            ThreadHelper().start_thread(commands.get(sch_item), ())
        return {"retmsg": "服务已启动", "item": sch_item}

    @staticmethod
    def __search(data):
        """
        WEB搜索资源
        """
        search_word = data.get("search_word")
        ident_flag = False if data.get("unident") else True
        filters = data.get("filters")
        tmdbid = data.get("tmdbid")
        media_type = data.get("media_type")
        if media_type:
            if media_type in MovieTypes:
                media_type = MediaType.MOVIE
            else:
                media_type = MediaType.TV
        if search_word:
            ret, ret_msg = search_medias_for_web(content=search_word,
                                                 ident_flag=ident_flag,
                                                 filters=filters,
                                                 tmdbid=tmdbid,
                                                 media_type=media_type)
            if ret != 0:
                return {"code": ret, "msg": ret_msg}
        return {"code": 0}

    @staticmethod
    def __download(data):
        """
        从WEB添加下载
        """
        dl_id = data.get("id")
        dl_dir = data.get("dir")
        dl_setting = data.get("setting")
        results = Searcher().get_search_result_by_id(dl_id)
        for res in results:
            dl_enclosure = res.ENCLOSURE if Sites().get_sites_by_url_domain(res.ENCLOSURE) else Torrent.format_enclosure(res.ENCLOSURE)
            if not dl_enclosure:
                return {"retcode": -1, "retmsg": "未发现当前种子下载链接，请前往站点下载"}
            media = Media().get_media_info(title=res.TORRENT_NAME, subtitle=res.DESCRIPTION)
            if not media:
                continue
            media.set_torrent_info(enclosure=res.ENCLOSURE,
                                   size=res.SIZE,
                                   site=res.SITE,
                                   page_url=res.PAGEURL,
                                   upload_volume_factor=float(
                                       res.UPLOAD_VOLUME_FACTOR),
                                   download_volume_factor=float(res.DOWNLOAD_VOLUME_FACTOR))
            # 添加下载
            _, ret, dir, ret_msg = Downloader().download(media_info=media,
                                                    download_dir=dl_dir,
                                                    download_setting=dl_setting,
                                                    in_from=SearchType.WEB,
                                                    user_name=current_user.username)
            if not ret:
                return {"retcode": -1, "retmsg": ret_msg}
        return {"retcode": 0, "retmsg": ""}

    @staticmethod
    def __download_link(data):
        """
        从WEB添加下载链接
        """
        site = data.get("site")
        enclosure = data.get("enclosure")
        title = data.get("title")
        description = data.get("description")
        page_url = data.get("page_url")
        size = data.get("size")
        seeders = data.get("seeders")
        uploadvolumefactor = data.get("uploadvolumefactor")
        downloadvolumefactor = data.get("downloadvolumefactor")
        dl_dir = data.get("dl_dir")
        dl_setting = data.get("dl_setting")
        if not title or not enclosure:
            return {"code": -1, "msg": "种子信息有误"}
        media = Media().get_media_info(title=title, subtitle=description)
        media.site = site
        media.enclosure = enclosure if Sites().get_sites_by_url_domain(enclosure) else Torrent.format_enclosure(enclosure)
        media.page_url = page_url
        media.size = size
        media.upload_volume_factor = float(uploadvolumefactor)
        media.download_volume_factor = float(downloadvolumefactor)
        media.seeders = seeders
        # 添加下载
        _, ret, dir, ret_msg = Downloader().download(media_info=media,
                                                download_dir=dl_dir,
                                                download_setting=dl_setting,
                                                in_from=SearchType.WEB,
                                                user_name=current_user.username)
        if not ret:
            return {"code": 1, "msg": ret_msg or "如连接正常，请检查下载任务是否存在"}
        return {"code": 0, "msg": "下载成功"}

    @staticmethod
    def __download_torrent(data):
        """
        从种子文件或者URL链接添加下载
        files：文件地址的列表，urls：种子链接地址列表或者单个链接地址
        """
        dl_dir = data.get("dl_dir")
        dl_setting = data.get("dl_setting")
        files = data.get("files") or []
        urls = data.get("urls") or []
        if not files and not urls:
            return {"code": -1, "msg": "没有种子文件或者种子链接"}
        # 下载种子
        for file_item in files:
            if not file_item:
                continue
            file_name = file_item.get("upload", {}).get("filename")
            file_path = os.path.join(Config().get_temp_path(), file_name)
            media_info = Media().get_media_info(title=file_name)
            if media_info:
                media_info.site = "WEB"
            # 添加下载
            Downloader().download(media_info=media_info,
                                  download_dir=dl_dir,
                                  download_setting=dl_setting,
                                  torrent_file=file_path,
                                  in_from=SearchType.WEB,
                                  user_name=current_user.username)
        # 下载链接
        if urls and not isinstance(urls, list):
            urls = [urls]
        for url in urls:
            if not url:
                continue
            # 查询站点
            site_info = Sites().get_sites(siteurl=url)
            if not site_info:
                return {"code": -1, "msg": "根据链接地址未匹配到站点"}
            # 下载种子文件，并读取信息
            file_path, _, _, _, retmsg = Torrent().get_torrent_info(
                url=url,
                cookie=site_info.get("cookie"),
                ua=site_info.get("ua"),
                proxy=site_info.get("proxy")
            )
            if not file_path:
                return {"code": -1, "msg": f"下载种子文件失败： {retmsg}"}
            media_info = Media().get_media_info(title=os.path.basename(file_path))
            if media_info:
                media_info.site = "WEB"
            # 添加下载
            Downloader().download(media_info=media_info,
                                  download_dir=dl_dir,
                                  download_setting=dl_setting,
                                  torrent_file=file_path,
                                  in_from=SearchType.WEB,
                                  user_name=current_user.username)

        return {"code": 0, "msg": "添加下载完成！"}

    @staticmethod
    def __pt_start(data):
        """
        开始下载
        """
        tid = data.get("id")
        if id:
            Downloader().start_torrents(ids=tid)
        return {"retcode": 0, "id": tid}

    @staticmethod
    def __pt_stop(data):
        """
        停止下载
        """
        tid = data.get("id")
        if id:
            Downloader().stop_torrents(ids=tid)
        return {"retcode": 0, "id": tid}

    @staticmethod
    def __pt_remove(data):
        """
        删除下载
        """
        tid = data.get("id")
        if id:
            Downloader().delete_torrents(ids=tid, delete_file=True)
        return {"retcode": 0, "id": tid}

    @staticmethod
    def __pt_info(data):
        """
        查询具体种子的信息
        """
        ids = data.get("ids")
        torrents = Downloader().get_downloading_progress(ids=ids)
        return {"retcode": 0, "torrents": torrents}

    @staticmethod
    def __del_unknown_path(data):
        """
        删除路径
        """
        tids = data.get("id")
        if isinstance(tids, list):
            for tid in tids:
                if not tid:
                    continue
                FileTransfer().delete_transfer_unknown(tid)
            return {"retcode": 0}
        else:
            retcode = FileTransfer().delete_transfer_unknown(tids)
            return {"retcode": retcode}

    def __rename(self, data):
        """
        手工转移
        """
        path = dest_dir = None
        syncmod = ModuleConf.RMT_MODES.get(data.get("syncmod"))
        logid = data.get("logid")
        if logid:
            transinfo = FileTransfer().get_transfer_info_by_id(logid)
            if transinfo:
                path = os.path.join(
                    transinfo.SOURCE_PATH, transinfo.SOURCE_FILENAME)
                dest_dir = transinfo.DEST
            else:
                return {"retcode": -1, "retmsg": "未查询到转移日志记录"}
        else:
            unknown_id = data.get("unknown_id")
            if unknown_id:
                inknowninfo = FileTransfer().get_unknown_info_by_id(unknown_id)
                if inknowninfo:
                    path = inknowninfo.PATH
                    dest_dir = inknowninfo.DEST
                else:
                    return {"retcode": -1, "retmsg": "未查询到未识别记录"}
        if not dest_dir:
            dest_dir = ""
        if not path:
            return {"retcode": -1, "retmsg": "输入路径有误"}
        tmdbid = data.get("tmdb")
        mtype = data.get("type")
        season = data.get("season")
        episode_format = data.get("episode_format")
        episode_details = data.get("episode_details")
        episode_part = data.get("episode_part")
        episode_offset = data.get("episode_offset")
        min_filesize = data.get("min_filesize")
        ignore_download_history = data.get("ignore_download_history")
        if mtype in MovieTypes:
            media_type = MediaType.MOVIE
        elif mtype in TvTypes:
            media_type = MediaType.TV
        else:
            media_type = MediaType.ANIME
        # 如果改次手动修复时一个单文件，自动修复改目录下同名文件，需要配合episode_format生效
        need_fix_all = False
        if os.path.splitext(path)[-1].lower() in RMT_MEDIAEXT and episode_format:
            path = os.path.dirname(path)
            need_fix_all = True
        # 开始转移
        succ_flag, ret_msg = self.__manual_transfer(inpath=path,
                                                    syncmod=syncmod,
                                                    outpath=dest_dir,
                                                    media_type=media_type,
                                                    episode_format=episode_format,
                                                    episode_details=episode_details,
                                                    episode_part=episode_part,
                                                    episode_offset=episode_offset,
                                                    need_fix_all=need_fix_all,
                                                    min_filesize=min_filesize,
                                                    tmdbid=tmdbid,
                                                    season=season,
                                                    ignore_download_history=ignore_download_history)
        if succ_flag:
            if not need_fix_all and not logid:
                # 更新记录状态
                FileTransfer().update_transfer_unknown_state(path)
            return {"retcode": 0, "retmsg": "转移成功"}
        else:
            return {"retcode": 2, "retmsg": ret_msg}

    def __rename_udf(self, data):
        """
        自定义识别
        """
        inpath = data.get("inpath")
        if not os.path.exists(inpath):
            return {"retcode": -1, "retmsg": "输入路径不存在"}
        outpath = data.get("outpath")
        syncmod = ModuleConf.RMT_MODES.get(data.get("syncmod"))
        tmdbid = data.get("tmdb")
        mtype = data.get("type")
        season = data.get("season")
        episode_format = data.get("episode_format")
        episode_details = data.get("episode_details")
        episode_part = data.get("episode_part")
        episode_offset = data.get("episode_offset")
        min_filesize = data.get("min_filesize")
        ignore_download_history = data.get("ignore_download_history")
        if mtype in MovieTypes:
            media_type = MediaType.MOVIE
        elif mtype in TvTypes:
            media_type = MediaType.TV
        else:
            media_type = MediaType.ANIME
        # 开始转移
        succ_flag, ret_msg = self.__manual_transfer(inpath=inpath,
                                                    syncmod=syncmod,
                                                    outpath=outpath,
                                                    media_type=media_type,
                                                    episode_format=episode_format,
                                                    episode_details=episode_details,
                                                    episode_part=episode_part,
                                                    episode_offset=episode_offset,
                                                    min_filesize=min_filesize,
                                                    tmdbid=tmdbid,
                                                    season=season,
                                                    ignore_download_history=ignore_download_history)
        if succ_flag:
            return {"retcode": 0, "retmsg": "转移成功"}
        else:
            return {"retcode": 2, "retmsg": ret_msg}

    @staticmethod
    def __manual_transfer(inpath,
                          syncmod,
                          outpath=None,
                          media_type=None,
                          episode_format=None,
                          episode_details=None,
                          episode_part=None,
                          episode_offset=None,
                          min_filesize=None,
                          tmdbid=None,
                          season=None,
                          need_fix_all=False,
                          ignore_download_history=False
                          ):
        """
        开始手工转移文件
        """
        inpath = os.path.normpath(inpath)
        if outpath:
            outpath = os.path.normpath(outpath)
        if not os.path.exists(inpath):
            return False, "输入路径不存在"
        if tmdbid:
            # 有输入TMDBID
            tmdb_info = Media().get_tmdb_info(mtype=media_type, tmdbid=tmdbid)
            if not tmdb_info:
                return False, "识别失败，无法查询到TMDB信息"
            # 按识别的信息转移
            succ_flag, ret_msg = FileTransfer().transfer_media(in_from=SyncType.MAN,
                                                               in_path=inpath,
                                                               rmt_mode=syncmod,
                                                               target_dir=outpath,
                                                               tmdb_info=tmdb_info,
                                                               media_type=media_type,
                                                               season=season,
                                                               episode=(
                                                                   EpisodeFormat(episode_format,
                                                                                 episode_details,
                                                                                 episode_part,
                                                                                 episode_offset),
                                                                   need_fix_all),
                                                               min_filesize=min_filesize,
                                                               udf_flag=True,
                                                               ignore_download_history=ignore_download_history)
        else:
            # 按识别的信息转移
            succ_flag, ret_msg = FileTransfer().transfer_media(in_from=SyncType.MAN,
                                                               in_path=inpath,
                                                               rmt_mode=syncmod,
                                                               target_dir=outpath,
                                                               media_type=media_type,
                                                               episode=(
                                                                   EpisodeFormat(episode_format,
                                                                                 episode_details,
                                                                                 episode_part,
                                                                                 episode_offset),
                                                                   need_fix_all),
                                                               min_filesize=min_filesize,
                                                               udf_flag=True,
                                                               ignore_download_history=ignore_download_history)
        return succ_flag, ret_msg

    def delete_history(self, data):
        """
        删除识别记录及文件
        """
        logids = data.get('logids') or []
        flag = data.get('flag')
        _filetransfer = FileTransfer()
        for logid in logids:
            # 读取历史记录
            transinfo = _filetransfer.get_transfer_info_by_id(logid)
            if transinfo:
                # 删除记录
                _filetransfer.delete_transfer_log_by_id(logid)
                # 根据flag删除文件
                source_path = transinfo.SOURCE_PATH
                source_filename = transinfo.SOURCE_FILENAME
                media_info = {
                    "type": transinfo.TYPE,
                    "category": transinfo.CATEGORY,
                    "title": transinfo.TITLE,
                    "year": transinfo.YEAR,
                    "tmdbid": transinfo.TMDBID,
                    "season_episode": transinfo.SEASON_EPISODE
                }
                # 删除该识别记录对应的转移记录
                _filetransfer.delete_transfer_blacklist("%s/%s" % (source_path, source_filename))
                dest = transinfo.DEST
                dest_path = transinfo.DEST_PATH
                dest_filename = transinfo.DEST_FILENAME
                if flag in ["del_source", "del_all"]:
                    # 删除源文件
                    del_flag, del_msg = self.delete_media_file(source_path, source_filename)
                    if not del_flag:
                        log.error(del_msg)
                    else:
                        log.info(del_msg)
                        # 触发源文件删除事件
                        EventManager().send_event(EventType.SourceFileDeleted, {
                            "media_info": media_info,
                            "path": source_path,
                            "filename": source_filename
                        })
                if flag in ["del_dest", "del_all"]:
                    # 删除媒体库文件
                    if dest_path and dest_filename:
                        del_flag, del_msg = self.delete_media_file(dest_path, dest_filename)
                        if not del_flag:
                            log.error(del_msg)
                        else:
                            log.info(del_msg)
                            # 触发媒体库文件删除事件
                            EventManager().send_event(EventType.LibraryFileDeleted, {
                                "media_info": media_info,
                                "path": dest_path,
                                "filename": dest_filename
                            })
                    else:
                        meta_info = MetaInfo(title=source_filename)
                        meta_info.title = transinfo.TITLE
                        meta_info.category = transinfo.CATEGORY
                        meta_info.year = transinfo.YEAR
                        if transinfo.SEASON_EPISODE:
                            meta_info.begin_season = int(
                                str(transinfo.SEASON_EPISODE).replace("S", ""))
                        if transinfo.TYPE == MediaType.MOVIE.value:
                            meta_info.type = MediaType.MOVIE
                        else:
                            meta_info.type = MediaType.TV
                        # 删除文件
                        dest_path = _filetransfer.get_dest_path_by_info(dest=dest, meta_info=meta_info)
                        if dest_path and dest_path.find(meta_info.title) != -1:
                            rm_parent_dir = False
                            if not meta_info.get_season_list():
                                # 电影，删除整个目录
                                try:
                                    shutil.rmtree(dest_path)
                                    # 触发媒体库文件删除事件
                                    EventManager().send_event(EventType.LibraryFileDeleted, {
                                        "media_info": media_info,
                                        "path": dest_path
                                    })
                                except Exception as e:
                                    ExceptionUtils.exception_traceback(e)
                            elif not meta_info.get_episode_string():
                                # 电视剧但没有集数，删除季目录
                                try:
                                    shutil.rmtree(dest_path)
                                    # 触发媒体库文件删除事件
                                    EventManager().send_event(EventType.LibraryFileDeleted, {
                                        "media_info": media_info,
                                        "path": dest_path
                                    })
                                except Exception as e:
                                    ExceptionUtils.exception_traceback(e)
                                rm_parent_dir = True
                            else:
                                # 有集数的电视剧，删除对应的集数文件
                                for dest_file in PathUtils.get_dir_files(dest_path):
                                    file_meta_info = MetaInfo(
                                        os.path.basename(dest_file))
                                    if file_meta_info.get_episode_list() and set(
                                            file_meta_info.get_episode_list()
                                    ).issubset(set(meta_info.get_episode_list())):
                                        try:
                                            os.remove(dest_file)
                                            # 触发媒体库文件删除事件
                                            EventManager().send_event(EventType.LibraryFileDeleted, {
                                                "media_info": media_info,
                                                "path": os.path.dirname(dest_file),
                                                "filename": os.path.basename(dest_file)
                                            })
                                        except Exception as e:
                                            ExceptionUtils.exception_traceback(
                                                e)
                                rm_parent_dir = True
                            if rm_parent_dir \
                                    and not PathUtils.get_dir_files(os.path.dirname(dest_path), exts=RMT_MEDIAEXT):
                                # 没有媒体文件时，删除整个目录
                                try:
                                    shutil.rmtree(os.path.dirname(dest_path))
                                except Exception as e:
                                    ExceptionUtils.exception_traceback(e)
        return {"retcode": 0}

    @staticmethod
    def delete_media_file(filedir, filename):
        """
        删除媒体文件，空目录也会被删除
        """
        filedir = os.path.normpath(filedir).replace("\\", "/")
        file = os.path.join(filedir, filename)
        try:
            if not os.path.exists(file):
                return False, f"{file} 不存在"
            os.remove(file)
            nfoname = f"{os.path.splitext(filename)[0]}.nfo"
            nfofile = os.path.join(filedir, nfoname)
            if os.path.exists(nfofile):
                os.remove(nfofile)
            # 检查空目录并删除
            if re.findall(r"^S\d{2}|^Season", os.path.basename(filedir), re.I):
                # 当前是季文件夹，判断并删除
                seaon_dir = filedir
                if seaon_dir.count('/') > 1 and not PathUtils.get_dir_files(seaon_dir, exts=RMT_MEDIAEXT):
                    shutil.rmtree(seaon_dir)
                # 媒体文件夹
                media_dir = os.path.dirname(seaon_dir)
            else:
                media_dir = filedir
            # 检查并删除媒体文件夹，非根目录且目录大于二级，且没有媒体文件时才会删除
            if media_dir != '/' \
                    and media_dir.count('/') > 1 \
                    and not re.search(r'[a-zA-Z]:/$', media_dir) \
                    and not PathUtils.get_dir_files(media_dir, exts=RMT_MEDIAEXT):
                shutil.rmtree(media_dir)
            return True, f"{file} 删除成功"
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            return True, f"{file} 删除失败"

    @staticmethod
    def __version():
        """
        检查新版本
        """
        version, url = WebUtils.get_latest_version()
        if version:
            return {"code": 0, "version": version, "url": url}
        return {"code": -1, "version": "", "url": ""}

    @staticmethod
    def __update_site(data):
        """
        维护站点信息
        """

        _sites = Sites()

        def __is_site_duplicate(query_name, query_tid):
            # 检查是否重名
            for site in _sites.get_sites_by_name(name=query_name):
                if str(site.get("id")) != str(query_tid):
                    return True
            return False

        tid = data.get('site_id')
        name = data.get('site_name')
        site_pri = data.get('site_pri')
        rssurl = data.get('site_rssurl')
        signurl = data.get('site_signurl')
        cookie = data.get('site_cookie')
        local_storage = data.get('site_local_storage')
        api_key = data.get('site_api_key')
        note = data.get('site_note')
        if isinstance(note, dict):
            note = json.dumps(note)
        rss_uses = data.get('site_include')

        if __is_site_duplicate(name, tid):
            return {"code": 400, "msg": "站点名称重复"}

        if tid:
            sites = _sites.get_sites(siteid=tid)
            # 站点不存在
            if not sites:
                return {"code": 400, "msg": "站点不存在"}
            old_name = sites.get('name')
            ret = _sites.update_site(tid=tid,
                                     name=name,
                                     site_pri=site_pri,
                                     rssurl=rssurl,
                                     signurl=signurl,
                                     cookie=cookie,
                                     local_storage=local_storage,
                                     api_key=api_key,
                                     note=note,
                                     rss_uses=rss_uses)
            if ret and (name != old_name):
                # 更新历史站点数据信息
                SiteUserInfo().update_site_name(name, old_name)

        else:
            ret = _sites.add_site(name=name,
                                  site_pri=site_pri,
                                  rssurl=rssurl,
                                  signurl=signurl,
                                  cookie=cookie,
                                  local_storage=local_storage,
                                  api_key=api_key,
                                  note=note,
                                  rss_uses=rss_uses)
        if ret:
            return {"code": "200"}
        else:
            return {"code": "400", "msg": "更新数据库失败，请重试"}

    @staticmethod
    def __get_site(data):
        """
        查询单个站点信息
        """
        tid = data.get("id")
        site_free = False
        site_2xfree = False
        site_hr = False
        if tid:
            ret = Sites().get_sites(siteid=tid)
            if ret.get("signurl"):
                site_attr = SiteConf().get_grap_conf(ret.get("signurl"))
                if site_attr.get("FREE"):
                    site_free = True
                if site_attr.get("2XFREE"):
                    site_2xfree = True
                if site_attr.get("HR"):
                    site_hr = True
        else:
            ret = []
        return {"code": 0, "site": ret, "site_free": site_free, "site_2xfree": site_2xfree, "site_hr": site_hr}

    @staticmethod
    def __get_sites(data):
        """
        查询多个站点信息
        """
        rss = True if data.get("rss") else False
        brush = True if data.get("brush") else False
        statistic = True if data.get("statistic") else False
        basic = True if data.get("basic") else False
        if basic:
            sites = Sites().get_site_dict(rss=rss,
                                          brush=brush,
                                          statistic=statistic)
        else:
            sites = Sites().get_sites(rss=rss,
                                      brush=brush,
                                      statistic=statistic)
        return {"code": 0, "sites": sites}

    @staticmethod
    def __del_site(data):
        """
        删除单个站点信息
        """
        tid = data.get("id")
        if tid:
            ret = Sites().delete_site(tid)
            return {"code": ret}
        else:
            return {"code": 0}

    def __restart(self):
        """
        重启
        """
        # 退出主进程
        self.restart_server()
        return {"code": 0}

    def update_system(self):
        """
        更新
        """
        # 升级
        if SystemUtils.is_synology():
            if SystemUtils.execute('/bin/ps -w -x | grep -v grep | grep -w "nastool update" | wc -l') == '0':
                # 调用群晖套件内置命令升级
                os.system('nastool update')
                # 重启
                self.restart_server()
        else:
            # 清除git代理
            os.system("sudo git config --global --unset http.proxy")
            os.system("sudo git config --global --unset https.proxy")
            # 设置git代理
            proxy = Config().get_proxies() or {}
            http_proxy = proxy.get("http")
            https_proxy = proxy.get("https")
            if http_proxy or https_proxy:
                os.system(
                    f"sudo git config --global http.proxy {http_proxy or https_proxy}")
                os.system(
                    f"sudo git config --global https.proxy {https_proxy or http_proxy}")
            # 清理
            os.system("sudo git clean -dffx")
            # 升级
            branch = os.getenv("NASTOOL_VERSION", "master")
            if os.system(f"sudo git fetch --depth 1 origin {branch}") != 0:
                return {"code": -1}
            os.system(f"sudo git reset --hard origin/{branch}")
            if os.system("sudo git submodule update --init --recursive") != 0:
                return {"code": -2}
            # 安装依赖
            if os.system('sudo pip install -r /nas-tools/requirements.txt') != 0:
                return {"code": -3}
            # 修复权限
            os.system('sudo chown -R nt:nt /nas-tools')
            # 重启
            self.restart_server()
        return {"code": 0}

    @staticmethod
    def __reset_db_version():
        """
        重置数据库版本
        """
        try:
            DbHelper().drop_table("alembic_version")
            return {"code": 0}
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            return {"code": 1, "msg": str(e)}

    @staticmethod
    def __logout():
        """
        注销
        """
        logout_user()
        return {"code": 0}

    def __update_config(self, data):
        """
        更新配置信息
        """
        cfg = Config().get_config()
        cfgs = dict(data).items()
        # 仅测试不保存
        config_test = False
        # 修改配置
        for key, value in cfgs:
            if key == "test" and value:
                config_test = True
                continue
            # 生效配置
            cfg = self.set_config_value(cfg, key, value)

        # 保存配置
        if not config_test:
            Config().save_config(cfg)

        return {"code": 0}

    @staticmethod
    def __add_or_edit_sync_path(data):
        """
        维护同步目录
        """
        sid = data.get("sid")
        source = data.get("from")
        dest = data.get("to")
        unknown = data.get("unknown")
        mode = data.get("syncmod")
        compatibility = data.get("compatibility")
        rename = data.get("rename")
        enabled = data.get("enabled")
        locating = data.get("locating")

        _sync = Sync()

        # 源目录检查
        if not source:
            return {"code": 1, "msg": f'源目录不能为空'}
        if not os.path.exists(source):
            return {"code": 1, "msg": f'{source}目录不存在'}
        # windows目录用\，linux目录用/
        source = os.path.normpath(source)
        # 目的目录检查，目的目录可为空
        if dest:
            dest = os.path.normpath(dest)
            if PathUtils.is_path_in_path(source, dest):
                return {"code": 1, "msg": "目的目录不可包含在源目录中"}
        if unknown:
            unknown = os.path.normpath(unknown)

        # 硬链接不能跨盘
        if mode == "link" and dest:
            common_path = os.path.commonprefix([source, dest])
            if not common_path or common_path == "/":
                return {"code": 1, "msg": "硬链接不能跨盘"}

        # 编辑先删再增
        if sid:
            _sync.delete_sync_path(sid)
        # 若启用，则关闭其他相同源目录的同步目录
        if enabled == 1:
            _sync.check_source(source=source)
        # 插入数据库
        _sync.insert_sync_path(source=source,
                               dest=dest,
                               unknown=unknown,
                               mode=mode,
                               compatibility=compatibility,
                               rename=rename,
                               enabled=enabled,
                               locating=locating)
        return {"code": 0, "msg": ""}

    @staticmethod
    def get_sync_path(data=None):
        """
        查询同步目录
        """
        if data:
            sync_path = Sync().get_sync_path_conf(sid=data.get("sid"))
        else:
            sync_path = Sync().get_sync_path_conf()
        return {"code": 0, "result": sync_path}

    @staticmethod
    def __delete_sync_path(data):
        """
        移出同步目录
        """
        sid = data.get("sid")
        Sync().delete_sync_path(sid)
        return {"code": 0}

    @staticmethod
    def __check_sync_path(data):
        """
        维护同步目录
        """
        flag = data.get("flag")
        sid = data.get("sid")
        checked = data.get("checked")

        _sync = Sync()

        if flag == "compatibility":
            _sync.check_sync_paths(sid=sid, compatibility=1 if checked else 0)
            return {"code": 0}
        elif flag == "rename":
            _sync.check_sync_paths(sid=sid, rename=1 if checked else 0)
            return {"code": 0}
        elif flag == "enable":
            # 若启用，则关闭其他相同源目录的同步目录
            if checked:
                _sync.check_source(sid=sid)
            _sync.check_sync_paths(sid=sid, enabled=1 if checked else 0)
            return {"code": 0}
        elif flag == "locating":
            _sync.check_sync_paths(sid=sid, locating=1 if checked else 0)
            return {"code": 0}        
        else:
            return {"code": 1}

    @staticmethod
    def __remove_rss_media(data):
        """
        移除RSS订阅
        """
        name = data.get("name")
        mtype = data.get("type")
        year = data.get("year")
        season = data.get("season")
        rssid = data.get("rssid")
        page = data.get("page")
        tmdbid = data.get("tmdbid")
        if not str(tmdbid).isdigit():
            tmdbid = None
        if name:
            name = MetaInfo(title=name).get_name()
        if mtype:
            if mtype in MovieTypes:
                Subscribe().delete_subscribe(mtype=MediaType.MOVIE,
                                             title=name,
                                             year=year,
                                             rssid=rssid,
                                             tmdbid=tmdbid)
            else:
                Subscribe().delete_subscribe(mtype=MediaType.TV,
                                             title=name,
                                             season=season,
                                             rssid=rssid,
                                             tmdbid=tmdbid)
        return {"code": 0, "page": page, "name": name}

    @staticmethod
    def __add_rss_media(data):
        """
        添加RSS订阅
        """
        _subscribe = Subscribe()
        channel = RssType.Manual if data.get("in_form") == "manual" else RssType.Auto
        name = data.get("name")
        year = data.get("year")
        keyword = data.get("keyword")
        season = data.get("season")
        fuzzy_match = data.get("fuzzy_match")
        mediaid = data.get("mediaid")
        rss_sites = data.get("rss_sites")
        search_sites = data.get("search_sites")
        over_edition = data.get("over_edition")
        filter_restype = data.get("filter_restype")
        filter_pix = data.get("filter_pix")
        filter_team = data.get("filter_team")
        filter_rule = data.get("filter_rule")
        filter_include = data.get("filter_include")
        filter_exclude = data.get("filter_exclude")
        save_path = data.get("save_path")
        download_setting = data.get("download_setting")
        total_ep = data.get("total_ep")
        current_ep = data.get("current_ep")
        rssid = data.get("rssid")
        page = data.get("page")
        mtype = MediaType.MOVIE if data.get(
            "type") in MovieTypes else MediaType.TV

        media_info = None
        if isinstance(season, list):
            code = 0
            msg = ""
            for sea in season:
                code, msg, media_info = _subscribe.add_rss_subscribe(mtype=mtype,
                                                                     name=name,
                                                                     year=year,
                                                                     channel=channel,
                                                                     keyword=keyword,
                                                                     season=sea,
                                                                     fuzzy_match=fuzzy_match,
                                                                     mediaid=mediaid,
                                                                     rss_sites=rss_sites,
                                                                     search_sites=search_sites,
                                                                     over_edition=over_edition,
                                                                     filter_restype=filter_restype,
                                                                     filter_pix=filter_pix,
                                                                     filter_team=filter_team,
                                                                     filter_rule=filter_rule,
                                                                     filter_include=filter_include,
                                                                     filter_exclude=filter_exclude,
                                                                     save_path=save_path,
                                                                     download_setting=download_setting,
                                                                     rssid=rssid)
                if code != 0:
                    break
        else:
            code, msg, media_info = _subscribe.add_rss_subscribe(mtype=mtype,
                                                                 name=name,
                                                                 year=year,
                                                                 channel=channel,
                                                                 keyword=keyword,
                                                                 season=season,
                                                                 fuzzy_match=fuzzy_match,
                                                                 mediaid=mediaid,
                                                                 rss_sites=rss_sites,
                                                                 search_sites=search_sites,
                                                                 over_edition=over_edition,
                                                                 filter_restype=filter_restype,
                                                                 filter_pix=filter_pix,
                                                                 filter_team=filter_team,
                                                                 filter_rule=filter_rule,
                                                                 filter_include=filter_include,
                                                                 filter_exclude=filter_exclude,
                                                                 save_path=save_path,
                                                                 download_setting=download_setting,
                                                                 total_ep=total_ep,
                                                                 current_ep=current_ep,
                                                                 rssid=rssid)
        if not rssid and media_info:
            rssid = _subscribe.get_subscribe_id(mtype=mtype,
                                                title=name,
                                                tmdbid=media_info.tmdb_id)
        return {"code": code, "msg": msg, "page": page, "name": name, "rssid": rssid}

    @staticmethod
    def re_identification(data):
        """
        未识别的重新识别
        """
        flag = data.get("flag")
        ids = data.get("ids")
        ret_flag = True
        ret_msg = []
        _filetransfer = FileTransfer()
        if flag == "unidentification":
            for wid in ids:
                unknowninfo = _filetransfer.get_unknown_info_by_id(wid)
                if unknowninfo:
                    path = unknowninfo.PATH
                    dest_dir = unknowninfo.DEST
                    rmt_mode = ModuleConf.get_enum_item(
                        RmtMode, unknowninfo.MODE) if unknowninfo.MODE else None
                else:
                    return {"retcode": -1, "retmsg": "未查询到未识别记录"}
                if not dest_dir:
                    dest_dir = ""
                if not path:
                    return {"retcode": -1, "retmsg": "未识别路径有误"}
                succ_flag, msg = _filetransfer.transfer_media(in_from=SyncType.MAN,
                                                              rmt_mode=rmt_mode,
                                                              in_path=path,
                                                              target_dir=dest_dir)
                if succ_flag:
                    _filetransfer.update_transfer_unknown_state(path)
                else:
                    ret_flag = False
                    if msg not in ret_msg:
                        ret_msg.append(msg)
        elif flag == "history":
            for wid in ids:
                transinfo = _filetransfer.get_transfer_info_by_id(wid)
                if transinfo:
                    path = os.path.join(
                        transinfo.SOURCE_PATH, transinfo.SOURCE_FILENAME)
                    dest_dir = transinfo.DEST
                    rmt_mode = ModuleConf.get_enum_item(
                        RmtMode, transinfo.MODE) if transinfo.MODE else None
                else:
                    return {"retcode": -1, "retmsg": "未查询到转移日志记录"}
                if not dest_dir:
                    dest_dir = ""
                if not path:
                    return {"retcode": -1, "retmsg": "未识别路径有误"}
                succ_flag, msg = _filetransfer.transfer_media(in_from=SyncType.MAN,
                                                              rmt_mode=rmt_mode,
                                                              in_path=path,
                                                              target_dir=dest_dir)
                if not succ_flag:
                    ret_flag = False
                    if msg not in ret_msg:
                        ret_msg.append(msg)
        if ret_flag:
            return {"retcode": 0, "retmsg": "转移成功"}
        else:
            return {"retcode": 2, "retmsg": "、".join(ret_msg)}

    @staticmethod
    def __media_info(data):
        """
        查询媒体信息
        """
        mediaid = data.get("id")
        mtype = data.get("type")
        title = data.get("title")
        year = data.get("year")
        page = data.get("page")
        rssid = data.get("rssid")
        seasons = []
        link_url = ""
        vote_average = 0
        poster_path = ""
        release_date = ""
        overview = ""
        # 类型
        if mtype in MovieTypes:
            media_type = MediaType.MOVIE
        else:
            media_type = MediaType.TV

        # 先取订阅信息
        _subcribe = Subscribe()
        _media = Media()
        rssid_ok = False
        if rssid:
            rssid = str(rssid)
            if media_type == MediaType.MOVIE:
                rssinfo = _subcribe.get_subscribe_movies(rid=rssid)
            else:
                rssinfo = _subcribe.get_subscribe_tvs(rid=rssid)
            if not rssinfo:
                return {
                    "code": 1,
                    "retmsg": "无法查询到订阅信息",
                    "rssid": rssid,
                    "type_str": media_type.value
                }
            overview = rssinfo[rssid].get("overview")
            poster_path = rssinfo[rssid].get("poster")
            title = rssinfo[rssid].get("name")
            vote_average = rssinfo[rssid].get("vote")
            year = rssinfo[rssid].get("year")
            release_date = rssinfo[rssid].get("release_date")
            link_url = _media.get_detail_url(mtype=media_type,
                                             tmdbid=rssinfo[rssid].get("tmdbid"))
            if overview and poster_path:
                rssid_ok = True

        # 订阅信息不足
        if not rssid_ok:
            if mediaid:
                media = WebUtils.get_mediainfo_from_id(
                    mtype=media_type, mediaid=mediaid)
            else:
                media = _media.get_media_info(
                    title=f"{title} {year}", mtype=media_type)
            if not media or not media.tmdb_info:
                return {
                    "code": 1,
                    "retmsg": "无法查询到TMDB信息",
                    "rssid": rssid,
                    "type_str": media_type.value
                }
            if not mediaid:
                mediaid = media.tmdb_id
            link_url = media.get_detail_url()
            overview = media.overview
            poster_path = media.get_poster_image()
            title = media.title
            vote_average = round(float(media.vote_average or 0), 1)
            year = media.year
            if media_type != MediaType.MOVIE:
                release_date = media.tmdb_info.get('first_air_date')
                seasons = [{
                    "text": "第%s季" % cn2an.an2cn(season.get("season_number"), mode='low'),
                    "num": season.get("season_number")} for season in
                    _media.get_tmdb_tv_seasons(tv_info=media.tmdb_info)]
            else:
                release_date = media.tmdb_info.get('release_date')

            # 查订阅信息
            if not rssid:
                rssid = _subcribe.get_subscribe_id(mtype=media_type,
                                                   title=title,
                                                   tmdbid=mediaid)

        return {
            "code": 0,
            "type": mtype,
            "type_str": media_type.value,
            "page": page,
            "title": title,
            "vote_average": vote_average,
            "poster_path": poster_path,
            "release_date": release_date,
            "year": year,
            "overview": overview,
            "link_url": link_url,
            "tmdbid": mediaid,
            "rssid": rssid,
            "seasons": seasons
        }

    @staticmethod
    def __test_connection(data):
        """
        测试连通性
        """
        # 支持两种传入方式：命令数组或单个命令，单个命令时xx|xx模式解析为模块和类，进行动态引入
        command = data.get("command")
        ret = None
        if command:
            try:
                module_obj = None
                if isinstance(command, list):
                    for cmd_str in command:
                        ret = eval(cmd_str)
                        if not ret:
                            break
                else:
                    if command.find("|") != -1:
                        module = command.split("|")[0]
                        class_name = command.split("|")[1]
                        module_obj = getattr(
                            importlib.import_module(module), class_name)()
                        if hasattr(module_obj, "init_config"):
                            module_obj.init_config()
                        ret = module_obj.get_status()
                    else:
                        ret = eval(command)
                # 重载配置
                Config().init_config()
                if module_obj:
                    if hasattr(module_obj, "init_config"):
                        module_obj.init_config()
            except Exception as e:
                ret = None
                ExceptionUtils.exception_traceback(e)
            return {"code": 0 if ret else 1}
        return {"code": 0}

    @staticmethod
    def __user_manager(data):
        """
        用户管理
        """
        oper = data.get("oper")
        name = data.get("name")
        if oper == "add":
            password = generate_password_hash(str(data.get("password")))
            pris = data.get("pris")
            if isinstance(pris, list):
                pris = ",".join(pris)
            ret = ProUser().add_user(name, password, pris)
        else:
            ret = ProUser().delete_user(name)

        if ret == 1 or ret:
            return {"code": 0, "success": False}
        return {"code": -1, "success": False, 'message': '操作失败'}

    @staticmethod
    def __refresh_rss(data):
        """
        重新搜索RSS
        """
        mtype = data.get("type")
        rssid = data.get("rssid")
        page = data.get("page")
        if mtype == "MOV":
            ThreadHelper().start_thread(Subscribe().subscribe_search_movie, (rssid,))
        else:
            ThreadHelper().start_thread(Subscribe().subscribe_search_tv, (rssid,))
        return {"code": 0, "page": page}

    @staticmethod
    def get_system_message(lst_time):
        messages = MessageCenter().get_system_messages(lst_time=lst_time)
        if messages:
            lst_time = messages[0].get("time")
        return {
            "code": 0,
            "message": messages,
            "lst_time": lst_time
        }

    @staticmethod
    def __delete_tmdb_cache(data):
        """
        删除tmdb缓存
        """
        if MetaHelper().delete_meta_data(data.get("cache_key")):
            MetaHelper().save_meta_data()
        return {"code": 0}

    @staticmethod
    def __movie_calendar_data(data):
        """
        查询电影上映日期
        """
        tid = data.get("id")
        rssid = data.get("rssid")
        if tid and tid.startswith("DB:"):
            doubanid = tid.replace("DB:", "")
            douban_info = DouBan().get_douban_detail(
                doubanid=doubanid, mtype=MediaType.MOVIE)
            if not douban_info:
                return {"code": 1, "retmsg": "无法查询到豆瓣信息"}
            poster_path = douban_info.get("cover_url") or ""
            title = douban_info.get("title")
            rating = douban_info.get("rating", {}) or {}
            vote_average = rating.get("value") or "无"
            release_date = douban_info.get("pubdate")
            if release_date:
                release_date = re.sub(
                    r"\(.*\)", "", douban_info.get("pubdate")[0])
            if not release_date:
                return {"code": 1, "retmsg": "上映日期不正确"}
            else:
                return {"code": 0,
                        "type": "电影",
                        "title": title,
                        "start": release_date,
                        "id": tid,
                        "year": release_date[0:4] if release_date else "",
                        "poster": poster_path,
                        "vote_average": vote_average,
                        "rssid": rssid
                        }
        else:
            if tid:
                tmdb_info = Media().get_tmdb_info(mtype=MediaType.MOVIE, tmdbid=tid)
            else:
                return {"code": 1, "retmsg": "没有TMDBID信息"}
            if not tmdb_info:
                return {"code": 1, "retmsg": "无法查询到TMDB信息"}
            poster_path = Config().get_tmdbimage_url(tmdb_info.get('poster_path')) \
                if tmdb_info.get('poster_path') else ""
            title = tmdb_info.get('title')
            vote_average = tmdb_info.get("vote_average")
            release_date = tmdb_info.get('release_date')
            if not release_date:
                return {"code": 1, "retmsg": "上映日期不正确"}
            else:
                return {"code": 0,
                        "type": "电影",
                        "title": title,
                        "start": release_date,
                        "id": tid,
                        "year": release_date[0:4] if release_date else "",
                        "poster": poster_path,
                        "vote_average": vote_average,
                        "rssid": rssid
                        }

    @staticmethod
    def __tv_calendar_data(data):
        """
        查询电视剧上映日期
        """
        tid = data.get("id")
        season = data.get("season")
        name = data.get("name")
        rssid = data.get("rssid")
        if tid and tid.startswith("DB:"):
            doubanid = tid.replace("DB:", "")
            douban_info = DouBan().get_douban_detail(doubanid=doubanid, mtype=MediaType.TV)
            if not douban_info:
                return {"code": 1, "retmsg": "无法查询到豆瓣信息"}
            poster_path = douban_info.get("cover_url") or ""
            title = douban_info.get("title")
            rating = douban_info.get("rating", {}) or {}
            vote_average = rating.get("value") or "无"
            release_date = re.sub(r"\(.*\)", "", douban_info.get("pubdate")[0])
            if not release_date:
                return {"code": 1, "retmsg": "上映日期不正确"}
            else:
                return {
                    "code": 0,
                    "events": [{
                        "type": "电视剧",
                        "title": title,
                        "start": release_date,
                        "id": tid,
                        "year": release_date[0:4] if release_date else "",
                        "poster": poster_path,
                        "vote_average": vote_average,
                        "rssid": rssid
                    }]
                }
        else:
            if tid:
                tmdb_info = Media().get_tmdb_tv_season_detail(tmdbid=tid, season=season)
            else:
                return {"code": 1, "retmsg": "没有TMDBID信息"}
            if not tmdb_info:
                return {"code": 1, "retmsg": "无法查询到TMDB信息"}
            episode_events = []
            air_date = tmdb_info.get("air_date")
            if not tmdb_info.get("poster_path"):
                tv_tmdb_info = Media().get_tmdb_info(mtype=MediaType.TV, tmdbid=tid)
                if tv_tmdb_info:
                    poster_path = Config().get_tmdbimage_url(tv_tmdb_info.get('poster_path'))
                else:
                    poster_path = ""
            else:
                poster_path = Config().get_tmdbimage_url(tmdb_info.get('poster_path'))
            year = air_date[0:4] if air_date else ""
            for episode in tmdb_info.get("episodes"):
                episode_events.append({
                    "type": "剧集",
                    "title": "%s 第%s季第%s集" % (
                        name,
                        season,
                        episode.get("episode_number")
                    ) if season != 1 else "%s 第%s集" % (
                        name,
                        episode.get("episode_number")
                    ),
                    "start": episode.get("air_date"),
                    "id": tid,
                    "year": year,
                    "poster": poster_path,
                    "vote_average": episode.get("vote_average") or "无",
                    "rssid": rssid
                })
            return {"code": 0, "events": episode_events}

    @staticmethod
    def __rss_detail(data):
        rid = data.get("rssid")
        mtype = data.get("rsstype")
        if mtype in MovieTypes:
            rssdetail = Subscribe().get_subscribe_movies(rid=rid)
            if not rssdetail:
                return {"code": 1}
            rssdetail = list(rssdetail.values())[0]
            rssdetail["type"] = "MOV"
        else:
            rssdetail = Subscribe().get_subscribe_tvs(rid=rid)
            if not rssdetail:
                return {"code": 1}
            rssdetail = list(rssdetail.values())[0]
            rssdetail["type"] = "TV"
        return {"code": 0, "detail": rssdetail}

    @staticmethod
    def __modify_tmdb_cache(data):
        """
        修改TMDB缓存的标题
        """
        if MetaHelper().modify_meta_data(data.get("key"), data.get("title")):
            MetaHelper().save_meta_data(force=True)
        return {"code": 0}

    @staticmethod
    def truncate_blacklist():
        """
        清空文件转移黑名单记录
        """
        FileTransfer().truncate_transfer_blacklist()
        return {"code": 0}

    @staticmethod
    def truncate_rsshistory():
        """
        清空RSS历史记录
        """
        RssHelper().truncate_rss_history()
        Subscribe().truncate_rss_episodes()
        return {"code": 0}

    @staticmethod
    def __add_brushtask(data):
        """
        新增刷流任务
        """
        # 输入值
        brushtask_id = data.get("brushtask_id")
        brushtask_name = data.get("brushtask_name")
        brushtask_site = data.get("brushtask_site")
        brushtask_interval = data.get("brushtask_interval")
        brushtask_downloader = data.get("brushtask_downloader")
        brushtask_totalsize = data.get("brushtask_totalsize")
        brushtask_state = data.get("brushtask_state")
        brushtask_rssurl = data.get("brushtask_rssurl")
        brushtask_label = data.get("brushtask_label")
        brushtask_up_limit = data.get("brushtask_up_limit")
        brushtask_dl_limit = data.get("brushtask_dl_limit")
        brushtask_savepath = data.get("brushtask_savepath")
        brushtask_transfer = 'Y' if data.get("brushtask_transfer") else 'N'
        brushtask_free_limit_speed = 'Y' if data.get("brushtask_free_limit_speed") else 'N'
        brushtask_free_ddl_delete = 'Y' if data.get("brushtask_free_ddl_delete") else 'N'
        brushtask_sendmessage = 'Y' if data.get(
            "brushtask_sendmessage") else 'N'
        brushtask_free = data.get("brushtask_free")
        brushtask_hr = data.get("brushtask_hr")
        brushtask_torrent_size = data.get("brushtask_torrent_size")
        brushtask_include = data.get("brushtask_include")
        brushtask_exclude = data.get("brushtask_exclude")
        brushtask_dlcount = data.get("brushtask_dlcount")
        brushtask_current_site_count = data.get("brushtask_current_site_count")
        brushtask_current_site_dlcount = data.get("brushtask_current_site_dlcount")
        brushtask_peercount = data.get("brushtask_peercount")
        brushtask_seedtime = data.get("brushtask_seedtime")
        brushtask_seedratio = data.get("brushtask_seedratio")
        brushtask_seedsize = data.get("brushtask_seedsize")
        brushtask_dltime = data.get("brushtask_dltime")
        brushtask_avg_upspeed = data.get("brushtask_avg_upspeed")
        brushtask_iatime = data.get("brushtask_iatime")
        brushtask_pubdate = data.get("brushtask_pubdate")
        brushtask_upspeed = data.get("brushtask_upspeed")
        brushtask_downspeed = data.get("brushtask_downspeed")
        frac_before_range = data.get("frac_before_range")
        frac_before_percent = data.get("frac_before_percent")
        frac_after_range = data.get("frac_after_range")
        # 选种规则
        rss_rule = {
            "free": brushtask_free,
            "hr": brushtask_hr,
            "size": brushtask_torrent_size,
            "include": brushtask_include,
            "exclude": brushtask_exclude,
            "dlcount": brushtask_dlcount,
            "current_site_count": brushtask_current_site_count,
            "current_site_dlcount": brushtask_current_site_dlcount,
            "peercount": brushtask_peercount,
            "pubdate": brushtask_pubdate,
            "upspeed": brushtask_upspeed,
            "downspeed": brushtask_downspeed
        }
        # 删除规则
        remove_rule = {
            "time": brushtask_seedtime,
            "ratio": brushtask_seedratio,
            "uploadsize": brushtask_seedsize,
            "dltime": brushtask_dltime,
            "avg_upspeed": brushtask_avg_upspeed,
            "iatime": brushtask_iatime
        }
        # 部分下载规则
        fraction_rule = {
            "frac_before_range": frac_before_range,
            "frac_before_percent": frac_before_percent,
            "frac_after_range": frac_after_range
        }
        # 添加记录
        item = {
            "name": brushtask_name,
            "site": brushtask_site,
            "free": brushtask_free,
            "rssurl": brushtask_rssurl,
            "interval": brushtask_interval,
            "downloader": brushtask_downloader,
            "seed_size": brushtask_totalsize,
            "label": brushtask_label,
            "up_limit": brushtask_up_limit,
            "dl_limit": brushtask_dl_limit,
            "savepath": brushtask_savepath,
            "transfer": brushtask_transfer,
            "brushtask_free_limit_speed": brushtask_free_limit_speed,
            "brushtask_free_ddl_delete": brushtask_free_ddl_delete,
            "state": brushtask_state,
            "rss_rule": rss_rule,
            "remove_rule": remove_rule,
            "fraction_rule": fraction_rule,
            "sendmessage": brushtask_sendmessage
        }
        BrushTask().update_brushtask(brushtask_id, item)
        return {"code": 0}

    @staticmethod
    def __del_brushtask(data):
        """
        删除刷流任务
        """
        brush_id = data.get("id")
        if brush_id:
            BrushTask().delete_brushtask(brush_id)
            return {"code": 0}
        return {"code": 1}

    @staticmethod
    def __brushtask_detail(data):
        """
        查询刷流任务详情
        """
        brush_id = data.get("id")
        brushtask = BrushTask().get_brushtask_info(brush_id)
        if not brushtask:
            return {"code": 1, "task": {}}

        return {"code": 0, "task": brushtask}

    @staticmethod
    def __update_brushtask_state(data):
        """
        批量暂停/开始刷流任务
        """
        try:
            state = data.get("state")
            task_ids = data.get("ids")
            _brushtask = BrushTask()
            if state is not None:
                if task_ids:
                    for tid in task_ids:
                        _brushtask.update_brushtask_state(state=state, brushtask_id=tid)
                else:
                    _brushtask.update_brushtask_state(state=state)
            return {"code": 0, "msg": ""}
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            return {"code": 1, "msg": "刷流任务设置失败"}

    @staticmethod
    def __brushtask_enable():
        """
        刷流任务可用状态
        """
        isBeyondOneMonth = SiteUserInfo().is_min_join_date_beyond_one_month()
        return {"code": 0, "isBeyondOneMonth": isBeyondOneMonth}

    def __name_test(self, data):
        """
        名称识别测试
        """
        name = data.get("name")
        subtitle = data.get("subtitle")
        if not name:
            return {"code": -1}
        media_info = Media().get_media_info(title=name, subtitle=subtitle)
        if not media_info:
            return {"code": 0, "data": {"name": "无法识别"}}
        return {"code": 0, "data": self.mediainfo_dict(media_info)}

    @staticmethod
    def mediainfo_dict(media_info):
        if not media_info:
            return {}
        tmdb_id = media_info.tmdb_id
        tmdb_link = media_info.get_detail_url()
        tmdb_S_E_link = ""
        if tmdb_id:
            if media_info.get_season_string():
                tmdb_S_E_link = "%s/season/%s" % (tmdb_link,
                                                  media_info.get_season_seq())
                if media_info.get_episode_string():
                    tmdb_S_E_link = "%s/episode/%s" % (
                        tmdb_S_E_link, media_info.get_episode_seq())
        return {
            "type": media_info.type.value if media_info.type else "",
            "name": media_info.get_name(),
            "title": media_info.title,
            "year": media_info.year,
            "season_episode": media_info.get_season_episode_string(),
            "part": media_info.part,
            "tmdbid": tmdb_id,
            "tmdblink": tmdb_link,
            "tmdb_S_E_link": tmdb_S_E_link,
            "category": media_info.category,
            "restype": media_info.resource_type,
            "effect": media_info.resource_effect,
            "pix": media_info.resource_pix,
            "team": media_info.resource_team,
            "customization": media_info.customization,
            "video_codec": media_info.video_encode,
            "audio_codec": media_info.audio_encode,
            "org_string": media_info.org_string,
            "rev_string": media_info.rev_string,
            "ignored_words": media_info.ignored_words,
            "replaced_words": media_info.replaced_words,
            "offset_words": media_info.offset_words
        }

    @staticmethod
    def __rule_test(data):
        title = data.get("title")
        subtitle = data.get("subtitle")
        size = data.get("size")
        rulegroup = data.get("rulegroup")
        if not title:
            return {"code": -1}
        meta_info = MetaInfo(title=title, subtitle=subtitle)
        meta_info.size = float(size) * 1024 ** 3 if size else 0
        match_flag, res_order, match_msg = \
            Filter().check_torrent_filter(meta_info=meta_info,
                                          filter_args={"rule": rulegroup})
        return {
            "code": 0,
            "flag": match_flag,
            "text": "匹配" if match_flag else "未匹配",
            "order": 100 - res_order if res_order else 0
        }

    @staticmethod
    def __net_test(data):
        target = data
        if target == "image.tmdb.org":
            target = target + "/t/p/w500/wwemzKWzjKYJFfCeiB57q3r4Bcm.png"
        if target == "qyapi.weixin.qq.com":
            target = target + "/cgi-bin/message/send"
        target = "https://" + target
        start_time = datetime.datetime.now()
        if target.find("themoviedb") != -1 \
                or target.find("telegram") != -1 \
                or target.find("fanart") != -1 \
                or target.find("tmdb") != -1:
            res = RequestUtils(proxies=Config().get_proxies(),
                               timeout=5).get_res(target)
        else:
            res = RequestUtils(timeout=5).get_res(target)
        seconds = int((datetime.datetime.now() -
                       start_time).microseconds / 1000)
        if not res:
            return {"res": False, "time": "%s 毫秒" % seconds}
        elif res.ok:
            return {"res": True, "time": "%s 毫秒" % seconds}
        else:
            return {"res": False, "time": "%s 毫秒" % seconds}

    @staticmethod
    def __get_site_activity(data):
        """
        查询site活动[上传，下载，魔力值]
        :param data: {"name":site_name}
        :return:
        """
        if not data or "name" not in data:
            return {"code": 1, "msg": "查询参数错误"}

        resp = {"code": 0}

        resp.update(
            {"dataset": SiteUserInfo().get_pt_site_activity_history(data["name"])})
        return resp

    @staticmethod
    def __get_site_history(data):
        """
        查询site 历史[上传，下载]
        :param data: {"days":累计时间}
        :return:
        """
        if not data or "days" not in data or not isinstance(data["days"], int):
            return {"code": 1, "msg": "查询参数错误"}

        resp = {"code": 0}
        _, _, site, upload, download = SiteUserInfo().get_pt_site_statistics_history(
            data["days"] + 1, data.get("end_day", None)
        )

        # 调整为dataset组织数据
        dataset = [["site", "upload", "download"]]
        dataset.extend([[site, upload, download]
                        for site, upload, download in zip(site, upload, download)])
        resp.update({"dataset": dataset})
        return resp

    @staticmethod
    def __get_site_seeding_info(data):
        """
        查询site 做种分布信息 大小，做种数
        :param data: {"name":site_name}
        :return:
        """
        if not data or "name" not in data:
            return {"code": 1, "msg": "查询参数错误"}

        resp = {"code": 0}

        seeding_info = SiteUserInfo().get_pt_site_seeding_info(
            data["name"]).get("seeding_info", [])
        # 调整为dataset组织数据
        dataset = [["seeders", "size"]]
        dataset.extend(seeding_info)

        resp.update({"dataset": dataset})
        return resp

    @staticmethod
    def __add_filtergroup(data):
        """
        新增规则组
        """
        name = data.get("name")
        default = data.get("default")
        if not name:
            return {"code": -1}
        Filter().add_group(name, default)
        return {"code": 0}

    @staticmethod
    def __restore_filtergroup(data):
        """
        恢复初始规则组
        """
        groupids = data.get("groupids")
        init_rulegroups = data.get("init_rulegroups")
        _filter = Filter()
        for groupid in groupids:
            try:
                _filter.delete_filtergroup(groupid)
            except Exception as err:
                ExceptionUtils.exception_traceback(err)
            for init_rulegroup in init_rulegroups:
                if str(init_rulegroup.get("id")) == groupid:
                    for sql in init_rulegroup.get("sql"):
                        DbHelper().excute(sql)
        return {"code": 0}

    @staticmethod
    def __set_default_filtergroup(data):
        groupid = data.get("id")
        if not groupid:
            return {"code": -1}
        Filter().set_default_filtergroup(groupid)
        return {"code": 0}

    @staticmethod
    def __del_filtergroup(data):
        groupid = data.get("id")
        Filter().delete_filtergroup(groupid)
        return {"code": 0}

    @staticmethod
    def __add_filterrule(data):
        rule_id = data.get("rule_id")
        item = {
            "group": data.get("group_id"),
            "name": data.get("rule_name"),
            "pri": data.get("rule_pri"),
            "include": data.get("rule_include"),
            "exclude": data.get("rule_exclude"),
            "size": data.get("rule_sizelimit"),
            "free": data.get("rule_free")
        }
        Filter().add_filter_rule(ruleid=rule_id, item=item)
        return {"code": 0}

    @staticmethod
    def __del_filterrule(data):
        ruleid = data.get("id")
        Filter().delete_filterrule(ruleid)
        return {"code": 0}

    @staticmethod
    def __filterrule_detail(data):
        rid = data.get("ruleid")
        groupid = data.get("groupid")
        ruleinfo = Filter().get_rules(groupid=groupid, ruleid=rid)
        if ruleinfo:
            ruleinfo['include'] = "\n".join(ruleinfo.get("include"))
            ruleinfo['exclude'] = "\n".join(ruleinfo.get("exclude"))
        return {"code": 0, "info": ruleinfo}

    def get_recommend(self, data):
        Type = data.get("type")
        SubType = data.get("subtype")
        CurrentPage = data.get("page")
        if not CurrentPage:
            CurrentPage = 1
        else:
            CurrentPage = int(CurrentPage)

        res_list = []
        if Type in ['MOV', 'TV', 'ALL']:
            if SubType == "hm":
                # TMDB热门电影
                res_list = Media().get_tmdb_hot_movies(CurrentPage)
            elif SubType == "ht":
                # TMDB热门电视剧
                res_list = Media().get_tmdb_hot_tvs(CurrentPage)
            elif SubType == "nm":
                # TMDB最新电影
                res_list = Media().get_tmdb_new_movies(CurrentPage)
            elif SubType == "nt":
                # TMDB最新电视剧
                res_list = Media().get_tmdb_new_tvs(CurrentPage)
            elif SubType == "dbom":
                # 豆瓣正在上映
                res_list = DouBan().get_douban_online_movie(CurrentPage)
            elif SubType == "dbhm":
                # 豆瓣热门电影
                res_list = DouBan().get_douban_hot_movie(CurrentPage)
            elif SubType == "dbht":
                # 豆瓣热门电视剧
                res_list = DouBan().get_douban_hot_tv(CurrentPage)
            elif SubType == "dbdh":
                # 豆瓣热门动画
                res_list = DouBan().get_douban_hot_anime(CurrentPage)
            elif SubType == "dbnm":
                # 豆瓣最新电影
                res_list = DouBan().get_douban_new_movie(CurrentPage)
            elif SubType == "dbtop":
                # 豆瓣TOP250电影
                res_list = DouBan().get_douban_top250_movie(CurrentPage)
            elif SubType == "dbzy":
                # 豆瓣热门综艺
                res_list = DouBan().get_douban_hot_show(CurrentPage)
            elif SubType == "dbct":
                # 华语口碑剧集榜
                res_list = DouBan().get_douban_chinese_weekly_tv(CurrentPage)
            elif SubType == "dbgt":
                # 全球口碑剧集榜
                res_list = DouBan().get_douban_weekly_tv_global(CurrentPage)
            elif SubType == "sim":
                # 相似推荐
                TmdbId = data.get("tmdbid")
                res_list = self.__media_similar({
                    "tmdbid": TmdbId,
                    "page": CurrentPage,
                    "type": Type
                }).get("data")
            elif SubType == "more":
                # 更多推荐
                TmdbId = data.get("tmdbid")
                res_list = self.__media_recommendations({
                    "tmdbid": TmdbId,
                    "page": CurrentPage,
                    "type": Type
                }).get("data")
            elif SubType == "person":
                # 人物作品
                PersonId = data.get("personid")
                res_list = self.__person_medias({
                    "personid": PersonId,
                    "type": None if Type == 'ALL' else Type,
                    "page": CurrentPage
                }).get("data")
            elif SubType == "bangumi":
                # Bangumi每日放送
                Week = data.get("week")
                res_list = Bangumi().get_bangumi_calendar(page=CurrentPage, week=Week)
        elif Type == "SEARCH":
            # 搜索词条
            Keyword = data.get("keyword")
            Source = data.get("source")
            medias = WebUtils.search_media_infos(
                keyword=Keyword, source=Source, page=CurrentPage)
            res_list = [media.to_dict() for media in medias]
        elif Type == "DOWNLOADED":
            # 近期下载
            res_list = self.get_downloaded({
                "page": CurrentPage
            }).get("Items")
        elif Type == "TRENDING":
            # TMDB流行趋势
            res_list = Media().get_tmdb_trending_all_week(page=CurrentPage)
        elif Type == "DISCOVER":
            # TMDB发现
            mtype = MediaType.MOVIE if SubType in MovieTypes else MediaType.TV
            # 过滤参数 with_genres with_original_language
            params = data.get("params") or {}

            res_list = Media().get_tmdb_discover(mtype=mtype, page=CurrentPage, params=params)
        elif Type == "DOUBANTAG":
            # 豆瓣发现
            mtype = MediaType.MOVIE if SubType in MovieTypes else MediaType.TV
            # 参数
            params = data.get("params") or {}
            # 排序
            sort = params.get("sort") or "R"
            # 选中的分类
            tags = params.get("tags") or ""
            # 过滤参数
            res_list = DouBan().get_douban_disover(mtype=mtype,
                                                   sort=sort,
                                                   tags=tags,
                                                   page=CurrentPage)

        # 补充存在与订阅状态
        for res in res_list:
            fav, rssid, item_url = self.get_media_exists_info(mtype=res.get("type"),
                                                              title=res.get("title"),
                                                              year=res.get("year"),
                                                              mediaid=res.get("id"))
            res.update({
                'fav': fav,
                'rssid': rssid
            })
        return {"code": 0, "Items": res_list}

    @staticmethod
    def get_downloaded(data):
        page = data.get("page")
        Items = Downloader().get_download_history(page=page)
        if Items:
            return {"code": 0, "Items": [{
                'id': item.TMDBID,
                'orgid': item.TMDBID,
                'tmdbid': item.TMDBID,
                'title': item.TITLE,
                'type': 'MOV' if item.TYPE == "电影" else "TV",
                'media_type': item.TYPE,
                'year': item.YEAR,
                'vote': item.VOTE,
                'image': item.POSTER,
                'overview': item.TORRENT,
                "date": item.DATE,
                "site": item.SITE
            } for item in Items]}
        else:
            return {"code": 0, "Items": []}

    @staticmethod
    def parse_brush_rule_string(rules: dict):
        if not rules:
            return ""
        rule_filter_string = {"gt": ">", "lt": "<", "bw": ""}
        rule_htmls = []
        if rules.get("size"):
            sizes = rules.get("size").split("#")
            if sizes[0]:
                if sizes[1]:
                    sizes[1] = sizes[1].replace(",", "-")
                rule_htmls.append(
                    '<span class="badge badge-outline text-blue me-1 mb-1" title="种子大小">种子大小: %s %sGB</span>'
                    % (rule_filter_string.get(sizes[0]), sizes[1]))
        if rules.get("pubdate"):
            pubdates = rules.get("pubdate").split("#")
            if pubdates[0]:
                if pubdates[1]:
                    pubdates[1] = pubdates[1].replace(",", "-")
                rule_htmls.append(
                    '<span class="badge badge-outline text-blue me-1 mb-1" title="发布时间">发布时间: %s %s小时</span>'
                    % (rule_filter_string.get(pubdates[0]), pubdates[1]))
        if rules.get("upspeed"):
            rule_htmls.append('<span class="badge badge-outline text-blue me-1 mb-1" title="上传限速">上传限速: %sB/s</span>'
                              % StringUtils.str_filesize(int(rules.get("upspeed")) * 1024))
        if rules.get("downspeed"):
            rule_htmls.append('<span class="badge badge-outline text-blue me-1 mb-1" title="下载限速">下载限速: %sB/s</span>'
                              % StringUtils.str_filesize(int(rules.get("downspeed")) * 1024))
        if rules.get("include"):
            rule_htmls.append(
                '<span class="badge badge-outline text-green me-1 mb-1 text-wrap text-start" title="包含规则">包含: %s</span>'
                % rules.get("include"))
        if rules.get("hr"):
            rule_htmls.append(
                '<span class="badge badge-outline text-red me-1 mb-1" title="排除HR">排除: HR</span>')
        if rules.get("exclude"):
            rule_htmls.append(
                '<span class="badge badge-outline text-red me-1 mb-1 text-wrap text-start" title="排除规则">排除: %s</span>'
                % rules.get("exclude"))
        if rules.get("dlcount"):
            rule_htmls.append('<span class="badge badge-outline text-blue me-1 mb-1" title="同时下载数量限制">同时下载: %s</span>'
                              % rules.get("dlcount"))
        if rules.get("peercount"):
            peer_counts = None
            if rules.get("peercount") == "#":
                peer_counts = None
            elif "#" in rules.get("peercount"):
                peer_counts = rules.get("peercount").split("#")
                peer_counts[1] = peer_counts[1].replace(",", "-") if (len(peer_counts) >= 2 and peer_counts[1]) else \
                    peer_counts[1]
            else:
                try:
                    # 兼容性代码
                    peer_counts = ["lt", int(rules.get("peercount"))]
                except Exception as err:
                    ExceptionUtils.exception_traceback(err)
                    pass
            if peer_counts:
                rule_htmls.append(
                    '<span class="badge badge-outline text-blue me-1 mb-1" title="当前做种人数限制">做种人数: %s %s</span>'
                    % (rule_filter_string.get(peer_counts[0]), peer_counts[1]))
        if rules.get("time"):
            times = rules.get("time").split("#")
            if times[0]:
                rule_htmls.append(
                    '<span class="badge badge-outline text-orange me-1 mb-1" title="做种时间">做种时间: %s %s小时</span>'
                    % (rule_filter_string.get(times[0]), times[1]))
        if rules.get("ratio"):
            ratios = rules.get("ratio").split("#")
            if ratios[0]:
                rule_htmls.append(
                    '<span class="badge badge-outline text-orange me-1 mb-1" title="分享率">分享率: %s %s</span>'
                    % (rule_filter_string.get(ratios[0]), ratios[1]))
        if rules.get("uploadsize"):
            uploadsizes = rules.get("uploadsize").split("#")
            if uploadsizes[0]:
                rule_htmls.append(
                    '<span class="badge badge-outline text-orange me-1 mb-1" title="上传量">上传量: %s %sGB</span>'
                    % (rule_filter_string.get(uploadsizes[0]), uploadsizes[1]))
        if rules.get("dltime"):
            dltimes = rules.get("dltime").split("#")
            if dltimes[0]:
                rule_htmls.append(
                    '<span class="badge badge-outline text-orange me-1 mb-1" title="下载耗时">下载耗时: %s %s小时</span>'
                    % (rule_filter_string.get(dltimes[0]), dltimes[1]))
        if rules.get("avg_upspeed"):
            avg_upspeeds = rules.get("avg_upspeed").split("#")
            if avg_upspeeds[0]:
                rule_htmls.append(
                    '<span class="badge badge-outline text-orange me-1 mb-1" title="平均上传速度">平均上传速度: %s %sKB/S</span>'
                    % (rule_filter_string.get(avg_upspeeds[0]), avg_upspeeds[1]))
        if rules.get("iatime"):
            iatimes = rules.get("iatime").split("#")
            if iatimes[0]:
                rule_htmls.append(
                    '<span class="badge badge-outline text-orange me-1 mb-1" title="未活动时间">未活动时间: %s %s小时</span>'
                    % (rule_filter_string.get(iatimes[0]), iatimes[1]))

        return "<br>".join(rule_htmls)

    @staticmethod
    def __clear_tmdb_cache():
        """
        清空TMDB缓存
        """
        try:
            MetaHelper().clear_meta_data()
            os.remove(MetaHelper().get_meta_data_path())
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            return {"code": 0, "msg": str(e)}
        return {"code": 0}

    @staticmethod
    def __check_site_attr(data):
        """
        检查站点标识
        """
        site_attr = SiteConf().get_grap_conf(data.get("url"))
        site_free = site_2xfree = site_hr = False
        if site_attr.get("FREE"):
            site_free = True
        if site_attr.get("2XFREE"):
            site_2xfree = True
        if site_attr.get("HR"):
            site_hr = True
        return {"code": 0, "site_free": site_free, "site_2xfree": site_2xfree, "site_hr": site_hr}

    @staticmethod
    def refresh_process(data):
        """
        刷新进度条
        """
        detail = ProgressHelper().get_process(data.get("type"))
        if detail:
            return {"code": 0, "value": detail.get("value"), "text": detail.get("text")}
        else:
            return {"code": 1, "value": 0, "text": "正在处理..."}

    @staticmethod
    def __restory_backup(data):
        """
        解压恢复备份文件
        """
        filename = data.get("file_name")
        if filename:
            config_path = Config().get_config_path()
            temp_path = Config().get_temp_path()
            file_path = os.path.join(temp_path, filename)
            try:
                shutil.unpack_archive(file_path, config_path, format='zip')
                return {"code": 0, "msg": ""}
            except Exception as e:
                ExceptionUtils.exception_traceback(e)
                return {"code": 1, "msg": str(e)}
            finally:
                if os.path.exists(file_path):
                    os.remove(file_path)

        return {"code": 1, "msg": "文件不存在"}

    @staticmethod
    def __get_resume(data):
        """
        获得继续观看
        """
        num = data.get("num") or 12
        # 实测，plex 似乎无法按照数目返回，此处手动切片
        return { "code": 0, "list": MediaServer().get_resume(num)[0:num] }

    @staticmethod
    def __start_mediasync(data):
        """
        开始媒体库同步
        """
        librarys = data.get("librarys") or []
        SystemConfig().set(key=SystemConfigKey.SyncLibrary, value=librarys)
        ThreadHelper().start_thread(MediaServer().sync_mediaserver, ())
        return {"code": 0}

    @staticmethod
    def __start_mediaDisplayModuleSync(data):
        """
        开始媒体库同步
        """
        selectedData = data.get("selected") or []
        unselectedData = data.get("unselected") or []
        try:
            selectedModules = [ast.literal_eval(item) for item in selectedData]
            if selectedModules:
                for module in selectedModules:
                    module["selected"] = True

            unselectedModules = [ast.literal_eval(item) for item in unselectedData]
            if unselectedModules:
                for module in unselectedModules:
                    module["selected"] = False

            modules = selectedModules + unselectedModules
            sorted_modules = sorted(modules, key=lambda x: x["id"])
            sorted_modules_str = json.dumps(sorted_modules, ensure_ascii=False, indent=4)
            log.debug(f"【我的媒体库】元数据: {sorted_modules_str}")
            SystemConfig().set(key=SystemConfigKey.LibraryDisplayModule, value=sorted_modules)
            return {"code": 0}
        except Exception as e:
            return {"code": 1}

    @staticmethod
    def __mediasync_state():
        """
        获取媒体库同步数据情况
        """
        status = MediaServer().get_mediasync_status()
        if not status:
            return {"code": 0, "text": "未同步"}
        else:
            return {"code": 0, "text": "电影：%s，电视剧：%s，同步时间：%s" %
                                       (status.get("movie_count"),
                                        status.get("tv_count"),
                                        status.get("time"))}

    @staticmethod
    def __get_tvseason_list(data):
        """
        获取剧集季列表
        """
        tmdbid = data.get("tmdbid")
        title = data.get("title")
        if title:
            title_season = MetaInfo(title=title).begin_season
        else:
            title_season = None
        if not str(tmdbid).isdigit():
            media_info = WebUtils.get_mediainfo_from_id(mtype=MediaType.TV,
                                                        mediaid=tmdbid)
            season_infos = Media().get_tmdb_tv_seasons(media_info.tmdb_info)
        else:
            season_infos = Media().get_tmdb_tv_seasons_byid(tmdbid=tmdbid)
        if title_season:
            seasons = [
                {
                    "text": "第%s季" % title_season,
                    "num": title_season
                }
            ]
        else:
            seasons = [
                {
                    "text": "第%s季" % cn2an.an2cn(season.get("season_number"), mode='low'),
                    "num": season.get("season_number")
                }
                for season in season_infos
            ]
        return {"code": 0, "seasons": seasons}

    @staticmethod
    def __get_userrss_task(data):
        """
        获取自定义订阅详情
        """
        taskid = data.get("id")
        return {"code": 0, "detail": RssChecker().get_rsstask_info(taskid=taskid)}

    @staticmethod
    def __delete_userrss_task(data):
        """
        删除自定义订阅
        """
        if RssChecker().delete_userrss_task(data.get("id")):
            return {"code": 0}
        else:
            return {"code": 1}

    @staticmethod
    def __update_userrss_task(data):
        """
        新增或修改自定义订阅
        """
        uses = data.get("uses")
        address_parser = data.get("address_parser")
        if not address_parser:
            return {"code": 1}
        address = list(dict(sorted(
            {k.replace("address_", ""): y for k, y in address_parser.items() if k.startswith("address_")}.items(),
            key=lambda x: int(x[0])
        )).values())
        parser = list(dict(sorted(
            {k.replace("parser_", ""): y for k, y in address_parser.items() if k.startswith("parser_")}.items(),
            key=lambda x: int(x[0])
        )).values())
        params = {
            "id": data.get("id"),
            "name": data.get("name"),
            "address": address,
            "parser": parser,
            "interval": data.get("interval"),
            "uses": uses,
            "include": data.get("include"),
            "exclude": data.get("exclude"),
            "filter_rule": data.get("rule"),
            "state": data.get("state"),
            "save_path": data.get("save_path"),
            "download_setting": data.get("download_setting"),
            "note": {"proxy": data.get("proxy")},
        }
        if uses == "D":
            params.update({
                "recognization": data.get("recognization")
            })
        elif uses == "R":
            params.update({
                "over_edition": data.get("over_edition"),
                "sites": data.get("sites"),
                "filter_args": {
                    "restype": data.get("restype"),
                    "pix": data.get("pix"),
                    "team": data.get("team")
                }
            })
        else:
            return {"code": 1}
        if RssChecker().update_userrss_task(params):
            return {"code": 0}
        else:
            return {"code": 1}

    @staticmethod
    def __check_userrss_task(data):
        """
        检测自定义订阅
        """
        try:
            flag_dict = {"enable": True, "disable": False}
            taskids = data.get("ids")
            state = flag_dict.get(data.get("flag"))
            _rsschecker = RssChecker()
            if state is not None:
                if taskids:
                    for taskid in taskids:
                        _rsschecker.check_userrss_task(tid=taskid, state=state)
                else:
                    _rsschecker.check_userrss_task(state=state)
            return {"code": 0, "msg": ""}
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            return {"code": 1, "msg": "自定义订阅状态设置失败"}

    @staticmethod
    def __get_rssparser(data):
        """
        获取订阅解析器详情
        """
        pid = data.get("id")
        return {"code": 0, "detail": RssChecker().get_userrss_parser(pid=pid)}

    @staticmethod
    def __delete_rssparser(data):
        """
        删除订阅解析器
        """
        if RssChecker().delete_userrss_parser(data.get("id")):
            return {"code": 0}
        else:
            return {"code": 1}

    @staticmethod
    def __update_rssparser(data):
        """
        新增或更新订阅解析器
        """
        params = {
            "id": data.get("id"),
            "name": data.get("name"),
            "type": data.get("type"),
            "format": data.get("format"),
            "params": data.get("params")
        }
        if RssChecker().update_userrss_parser(params):
            return {"code": 0}
        else:
            return {"code": 1}

    @staticmethod
    def __run_userrss(data):
        RssChecker().check_task_rss(data.get("id"))
        return {"code": 0}

    @staticmethod
    def __run_brushtask(data):
        BrushTask().check_task_rss(data.get("id"))
        return {"code": 0}

    @staticmethod
    def list_site_resources(data):
        resources = Indexer().list_resources(url=data.get("site"),
                                             page=data.get("page"),
                                             keyword=data.get("keyword"))
        if not resources:
            return {"code": 1, "msg": "获取站点资源出现错误，无法连接到站点！"}
        else:
            return {"code": 0, "data": resources}

    @staticmethod
    def __list_rss_articles(data):
        task_info = RssChecker().get_rsstask_info(taskid=data.get("id"))
        uses = task_info.get("uses")
        address_count = len(task_info.get("address"))
        articles = RssChecker().get_rss_articles(data.get("id"))
        count = len(articles)
        if articles:
            return {"code": 0, "data": articles, "count": count, "uses": uses, "address_count": address_count}
        else:
            return {"code": 1, "msg": "未获取到报文"}

    def __rss_article_test(self, data):
        taskid = data.get("taskid")
        title = data.get("title")
        if not taskid:
            return {"code": -1}
        if not title:
            return {"code": -1}
        media_info, match_flag, exist_flag = RssChecker(
        ).test_rss_articles(taskid=taskid, title=title)
        if not media_info:
            return {"code": 0, "data": {"name": "无法识别"}}
        media_dict = self.mediainfo_dict(media_info)
        media_dict.update({"match_flag": match_flag, "exist_flag": exist_flag})
        return {"code": 0, "data": media_dict}

    @staticmethod
    def __list_rss_history(data):
        downloads = []
        historys = RssChecker().get_userrss_task_history(data.get("id"))
        count = len(historys)
        for history in historys:
            params = {
                "title": history.TITLE,
                "downloader": history.DOWNLOADER,
                "date": history.DATE
            }
            downloads.append(params)
        if downloads:
            return {"code": 0, "data": downloads, "count": count}
        else:
            return {"code": 1, "msg": "无下载记录"}

    @staticmethod
    def __rss_articles_check(data):
        if not data.get("articles"):
            return {"code": 2}
        res = RssChecker().check_rss_articles(
            taskid=data.get("taskid"),
            flag=data.get("flag"),
            articles=data.get("articles")
        )
        if res:
            return {"code": 0}
        else:
            return {"code": 1}

    @staticmethod
    def __rss_articles_download(data):
        if not data.get("articles"):
            return {"code": 2}
        res = RssChecker().download_rss_articles(
            taskid=data.get("taskid"), articles=data.get("articles"))
        if res:
            return {"code": 0}
        else:
            return {"code": 1}

    @staticmethod
    def __add_custom_word_group(data):
        try:
            tmdb_id = data.get("tmdb_id")
            tmdb_type = data.get("tmdb_type")
            _wordshelper = WordsHelper()
            _media = Media()
            if tmdb_type == "tv":
                if not _wordshelper.is_custom_word_group_existed(tmdbid=tmdb_id, gtype=2):
                    tmdb_info = _media.get_tmdb_info(mtype=MediaType.TV, tmdbid=tmdb_id)
                    if not tmdb_info:
                        return {"code": 1, "msg": "添加失败，无法查询到TMDB信息"}
                    _wordshelper.insert_custom_word_groups(title=tmdb_info.get("name"),
                                                           year=tmdb_info.get(
                                                               "first_air_date")[0:4],
                                                           gtype=2,
                                                           tmdbid=tmdb_id,
                                                           season_count=tmdb_info.get("number_of_seasons"))
                    return {"code": 0, "msg": ""}
                else:
                    return {"code": 1, "msg": "识别词组（TMDB ID）已存在"}
            elif tmdb_type == "movie":
                if not _wordshelper.is_custom_word_group_existed(tmdbid=tmdb_id, gtype=1):
                    tmdb_info = _media.get_tmdb_info(mtype=MediaType.MOVIE, tmdbid=tmdb_id)
                    if not tmdb_info:
                        return {"code": 1, "msg": "添加失败，无法查询到TMDB信息"}
                    _wordshelper.insert_custom_word_groups(title=tmdb_info.get("title"),
                                                           year=tmdb_info.get(
                                                               "release_date")[0:4],
                                                           gtype=1,
                                                           tmdbid=tmdb_id,
                                                           season_count=0)
                    return {"code": 0, "msg": ""}
                else:
                    return {"code": 1, "msg": "识别词组（TMDB ID）已存在"}
            else:
                return {"code": 1, "msg": "无法识别媒体类型"}
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            return {"code": 1, "msg": str(e)}

    @staticmethod
    def __delete_custom_word_group(data):
        try:
            gid = data.get("gid")
            WordsHelper().delete_custom_word_group(gid=gid)
            return {"code": 0, "msg": ""}
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            return {"code": 1, "msg": str(e)}

    @staticmethod
    def __add_or_edit_custom_word(data):
        try:
            wid = data.get("id")
            gid = data.get("gid")
            group_type = data.get("group_type")
            replaced = data.get("new_replaced")
            replace = data.get("new_replace")
            front = data.get("new_front")
            back = data.get("new_back")
            offset = data.get("new_offset")
            whelp = data.get("new_help")
            wtype = data.get("type")
            season = data.get("season")
            enabled = data.get("enabled")
            regex = data.get("regex")

            _wordshelper = WordsHelper()

            # 集数偏移格式检查
            if wtype in ["3", "4"]:
                if not re.findall(r'EP', offset):
                    return {"code": 1, "msg": "偏移集数格式有误"}
                if re.findall(r'(?!-|\+|\*|/|[0-9]).', re.sub(r'EP', "", offset)):
                    return {"code": 1, "msg": "偏移集数格式有误"}
            if wid:
                _wordshelper.delete_custom_word(wid=wid)
            # 电影
            if group_type == "1":
                season = -2
            # 屏蔽
            if wtype == "1":
                if not _wordshelper.is_custom_words_existed(replaced=replaced):
                    _wordshelper.insert_custom_word(replaced=replaced,
                                                    replace="",
                                                    front="",
                                                    back="",
                                                    offset="",
                                                    wtype=wtype,
                                                    gid=gid,
                                                    season=season,
                                                    enabled=enabled,
                                                    regex=regex,
                                                    whelp=whelp if whelp else "")
                    return {"code": 0, "msg": ""}
                else:
                    return {"code": 1, "msg": "识别词已存在\n（被替换词：%s）" % replaced}
            # 替换
            elif wtype == "2":
                if not _wordshelper.is_custom_words_existed(replaced=replaced):
                    _wordshelper.insert_custom_word(replaced=replaced,
                                                    replace=replace,
                                                    front="",
                                                    back="",
                                                    offset="",
                                                    wtype=wtype,
                                                    gid=gid,
                                                    season=season,
                                                    enabled=enabled,
                                                    regex=regex,
                                                    whelp=whelp if whelp else "")
                    return {"code": 0, "msg": ""}
                else:
                    return {"code": 1, "msg": "识别词已存在\n（被替换词：%s）" % replaced}
            # 集偏移
            elif wtype == "4":
                if not _wordshelper.is_custom_words_existed(front=front, back=back):
                    _wordshelper.insert_custom_word(replaced="",
                                                    replace="",
                                                    front=front,
                                                    back=back,
                                                    offset=offset,
                                                    wtype=wtype,
                                                    gid=gid,
                                                    season=season,
                                                    enabled=enabled,
                                                    regex=regex,
                                                    whelp=whelp if whelp else "")
                    return {"code": 0, "msg": ""}
                else:
                    return {"code": 1, "msg": "识别词已存在\n（前后定位词：%s@%s）" % (front, back)}
            # 替换+集偏移
            elif wtype == "3":
                if not _wordshelper.is_custom_words_existed(replaced=replaced):
                    _wordshelper.insert_custom_word(replaced=replaced,
                                                    replace=replace,
                                                    front=front,
                                                    back=back,
                                                    offset=offset,
                                                    wtype=wtype,
                                                    gid=gid,
                                                    season=season,
                                                    enabled=enabled,
                                                    regex=regex,
                                                    whelp=whelp if whelp else "")
                    return {"code": 0, "msg": ""}
                else:
                    return {"code": 1, "msg": "识别词已存在\n（被替换词：%s）" % replaced}
            else:
                return {"code": 1, "msg": ""}
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            return {"code": 1, "msg": str(e)}

    @staticmethod
    def __get_custom_word(data):
        try:
            wid = data.get("wid")
            word_info = WordsHelper().get_custom_words(wid=wid)
            if word_info:
                word_info = word_info[0]
                word = {"id": word_info.ID,
                        "replaced": word_info.REPLACED,
                        "replace": word_info.REPLACE,
                        "front": word_info.FRONT,
                        "back": word_info.BACK,
                        "offset": word_info.OFFSET,
                        "type": word_info.TYPE,
                        "group_id": word_info.GROUP_ID,
                        "season": word_info.SEASON,
                        "enabled": word_info.ENABLED,
                        "regex": word_info.REGEX,
                        "help": word_info.HELP, }
            else:
                word = {}
            return {"code": 0, "data": word}
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            return {"code": 1, "msg": "查询识别词失败"}

    @staticmethod
    def __delete_custom_words(data):
        try:
            _wordshelper = WordsHelper()
            ids_info = data.get("ids_info")
            if not ids_info:
                _wordshelper.delete_custom_word()
            else:
                ids = [id_info.split("_")[1] for id_info in ids_info]
                for wid in ids:
                    _wordshelper.delete_custom_word(wid=wid)
            return {"code": 0, "msg": ""}
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            return {"code": 1, "msg": str(e)}

    @staticmethod
    def __check_custom_words(data):
        try:
            flag_dict = {"enable": 1, "disable": 0}
            ids_info = data.get("ids_info")
            enabled = flag_dict.get(data.get("flag"))
            _wordshelper = WordsHelper()
            if not ids_info:
                _wordshelper.check_custom_word(enabled=enabled)
            else:
                ids = [id_info.split("_")[1] for id_info in ids_info]
                for wid in ids:
                    _wordshelper.check_custom_word(wid=wid, enabled=enabled)
            return {"code": 0, "msg": ""}
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            return {"code": 1, "msg": "识别词状态设置失败"}

    @staticmethod
    def __export_custom_words(data):
        try:
            note = data.get("note")
            ids_info = data.get("ids_info")
            group_ids = []
            word_ids = []
            group_infos = []
            word_infos = []

            _wordshelper = WordsHelper()

            if ids_info:
                ids_info = ids_info.split("@")
                for id_info in ids_info:
                    wid = id_info.split("_")
                    group_ids.append(wid[0])
                    word_ids.append(wid[1])
                for group_id in group_ids:
                    if group_id != "-1":
                        group_info = _wordshelper.get_custom_word_groups(gid=group_id)
                        if group_info:
                            group_infos.append(group_info[0])
                for word_id in word_ids:
                    word_info = _wordshelper.get_custom_words(wid=word_id)
                    if word_info:
                        word_infos.append(word_info[0])
            else:
                group_infos = _wordshelper.get_custom_word_groups()
                word_infos = _wordshelper.get_custom_words()
            export_dict = {}
            if not group_ids or "-1" in group_ids:
                export_dict["-1"] = {"id": -1,
                                     "title": "通用",
                                     "type": 1,
                                     "words": {}, }
            for group_info in group_infos:
                export_dict[str(group_info.ID)] = {"id": group_info.ID,
                                                   "title": group_info.TITLE,
                                                   "year": group_info.YEAR,
                                                   "type": group_info.TYPE,
                                                   "tmdbid": group_info.TMDBID,
                                                   "season_count": group_info.SEASON_COUNT,
                                                   "words": {}, }
            for word_info in word_infos:
                export_dict[str(word_info.GROUP_ID)]["words"][str(word_info.ID)] = {"id": word_info.ID,
                                                                                    "replaced": word_info.REPLACED,
                                                                                    "replace": word_info.REPLACE,
                                                                                    "front": word_info.FRONT,
                                                                                    "back": word_info.BACK,
                                                                                    "offset": word_info.OFFSET,
                                                                                    "type": word_info.TYPE,
                                                                                    "season": word_info.SEASON,
                                                                                    "regex": word_info.REGEX,
                                                                                    "help": word_info.HELP, }
            export_string = json.dumps(export_dict) + "@@@@@@" + str(note)
            string = base64.b64encode(
                export_string.encode("utf-8")).decode('utf-8')
            return {"code": 0, "string": string}
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            return {"code": 1, "msg": str(e)}

    @staticmethod
    def __analyse_import_custom_words_code(data):
        try:
            import_code = data.get('import_code')
            string = base64.b64decode(import_code.encode(
                "utf-8")).decode('utf-8').split("@@@@@@")
            note_string = string[1]
            import_dict = json.loads(string[0])
            groups = []
            for group in import_dict.values():
                wid = group.get('id')
                title = group.get("title")
                year = group.get("year")
                wtype = group.get("type")
                tmdbid = group.get("tmdbid")
                season_count = group.get("season_count") or ""
                words = group.get("words")
                if tmdbid:
                    link = "https://www.themoviedb.org/%s/%s" % (
                        "movie" if int(wtype) == 1 else "tv", tmdbid)
                else:
                    link = ""
                groups.append({"id": wid,
                               "name": "%s（%s）" % (title, year) if year else title,
                               "link": link,
                               "type": wtype,
                               "seasons": season_count,
                               "words": words})
            return {"code": 0, "groups": groups, "note_string": note_string}
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            return {"code": 1, "msg": str(e)}

    @staticmethod
    def __import_custom_words(data):
        try:
            _wordshelper = WordsHelper()
            import_code = data.get('import_code')
            ids_info = data.get('ids_info')
            string = base64.b64decode(import_code.encode(
                "utf-8")).decode('utf-8').split("@@@@@@")
            import_dict = json.loads(string[0])
            import_group_ids = [id_info.split("_")[0] for id_info in ids_info]
            group_id_dict = {}
            for import_group_id in import_group_ids:
                import_group_info = import_dict.get(import_group_id)
                if int(import_group_info.get("id")) == -1:
                    group_id_dict["-1"] = -1
                    continue
                title = import_group_info.get("title")
                year = import_group_info.get("year")
                gtype = import_group_info.get("type")
                tmdbid = import_group_info.get("tmdbid")
                season_count = import_group_info.get("season_count")
                if not _wordshelper.is_custom_word_group_existed(tmdbid=tmdbid, gtype=gtype):
                    _wordshelper.insert_custom_word_groups(title=title,
                                                           year=year,
                                                           gtype=gtype,
                                                           tmdbid=tmdbid,
                                                           season_count=season_count)
                group_info = _wordshelper.get_custom_word_groups(
                    tmdbid=tmdbid, gtype=gtype)
                if group_info:
                    group_id_dict[import_group_id] = group_info[0].ID
            for id_info in ids_info:
                id_info = id_info.split('_')
                import_group_id = id_info[0]
                import_word_id = id_info[1]
                import_word_info = import_dict.get(
                    import_group_id).get("words").get(import_word_id)
                gid = group_id_dict.get(import_group_id)
                replaced = import_word_info.get("replaced")
                replace = import_word_info.get("replace")
                front = import_word_info.get("front")
                back = import_word_info.get("back")
                offset = import_word_info.get("offset")
                whelp = import_word_info.get("help")
                wtype = int(import_word_info.get("type"))
                season = import_word_info.get("season")
                regex = import_word_info.get("regex")
                # 屏蔽, 替换, 替换+集偏移
                if wtype in [1, 2, 3]:
                    if _wordshelper.is_custom_words_existed(replaced=replaced):
                        return {"code": 1, "msg": "识别词已存在\n（被替换词：%s）" % replaced}
                # 集偏移
                elif wtype == 4:
                    if _wordshelper.is_custom_words_existed(front=front, back=back):
                        return {"code": 1, "msg": "识别词已存在\n（前后定位词：%s@%s）" % (front, back)}
                _wordshelper.insert_custom_word(replaced=replaced,
                                                replace=replace,
                                                front=front,
                                                back=back,
                                                offset=offset,
                                                wtype=wtype,
                                                gid=gid,
                                                season=season,
                                                enabled=1,
                                                regex=regex,
                                                whelp=whelp if whelp else "")
            return {"code": 0, "msg": ""}
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            return {"code": 1, "msg": str(e)}

    @staticmethod
    def get_categories(data):
        if data.get("type") == "电影":
            categories = Category().movie_categorys
        elif data.get("type") == "电视剧":
            categories = Category().tv_categorys
        else:
            categories = Category().anime_categorys
        return {"code": 0, "category": list(categories), "id": data.get("id"), "value": data.get("value")}

    @staticmethod
    def __delete_rss_history(data):
        rssid = data.get("rssid")
        Rss().delete_rss_history(rssid=rssid)
        return {"code": 0}

    @staticmethod
    def __re_rss_history(data):
        rssid = data.get("rssid")
        rtype = data.get("type")
        rssinfo = Rss().get_rss_history(rtype=rtype, rid=rssid)
        if rssinfo:
            if rtype == "MOV":
                mtype = MediaType.MOVIE
            else:
                mtype = MediaType.TV
            if rssinfo[0].SEASON:
                season = int(str(rssinfo[0].SEASON).replace("S", ""))
            else:
                season = None
            code, msg, _ = Subscribe().add_rss_subscribe(mtype=mtype,
                                                         name=rssinfo[0].NAME,
                                                         year=rssinfo[0].YEAR,
                                                         channel=RssType.Auto,
                                                         season=season,
                                                         mediaid=rssinfo[0].TMDBID,
                                                         total_ep=rssinfo[0].TOTAL,
                                                         current_ep=rssinfo[0].START)
            return {"code": code, "msg": msg}
        else:
            return {"code": 1, "msg": "订阅历史记录不存在"}

    @staticmethod
    def __share_filtergroup(data):
        gid = data.get("id")
        _filter = Filter()
        group_info = _filter.get_filter_group(gid=gid)
        if not group_info:
            return {"code": 1, "msg": "规则组不存在"}
        group_rules = _filter.get_filter_rule(groupid=gid)
        if not group_rules:
            return {"code": 1, "msg": "规则组没有对应规则"}
        rules = []
        for rule in group_rules:
            rules.append({
                "name": rule.ROLE_NAME,
                "pri": rule.PRIORITY,
                "include": rule.INCLUDE,
                "exclude": rule.EXCLUDE,
                "size": rule.SIZE_LIMIT,
                "free": rule.NOTE
            })
        rule_json = {
            "name": group_info[0].GROUP_NAME,
            "rules": rules
        }
        json_string = base64.b64encode(json.dumps(
            rule_json).encode("utf-8")).decode('utf-8')
        return {"code": 0, "string": json_string}

    @staticmethod
    def __import_filtergroup(data):
        content = data.get("content")
        try:
            _filter = Filter()

            json_str = base64.b64decode(
                str(content).encode("utf-8")).decode('utf-8')
            json_obj = json.loads(json_str)
            if json_obj:
                if not json_obj.get("name"):
                    return {"code": 1, "msg": "数据格式不正确"}
                _filter.add_group(name=json_obj.get("name"))
                group_id = _filter.get_filter_groupid_by_name(
                    json_obj.get("name"))
                if not group_id:
                    return {"code": 1, "msg": "数据内容不正确"}
                if json_obj.get("rules"):
                    for rule in json_obj.get("rules"):
                        _filter.add_filter_rule(item={
                            "group": group_id,
                            "name": rule.get("name"),
                            "pri": rule.get("pri"),
                            "include": rule.get("include"),
                            "exclude": rule.get("exclude"),
                            "size": rule.get("size"),
                            "free": rule.get("free")
                        })
            return {"code": 0, "msg": ""}
        except Exception as err:
            ExceptionUtils.exception_traceback(err)
            return {"code": 1, "msg": "数据格式不正确，%s" % str(err)}

    @staticmethod
    def get_library_spacesize():
        """
        查询媒体库存储空间
        """
        # 磁盘空间
        UsedSapce = 0
        UsedPercent = 0
        media = Config().get_config('media')
        # 电影目录
        movie_paths = media.get('movie_path')
        if not isinstance(movie_paths, list):
            movie_paths = [movie_paths]
        # 电视目录
        tv_paths = media.get('tv_path')
        if not isinstance(tv_paths, list):
            tv_paths = [tv_paths]
        # 动漫目录
        anime_paths = media.get('anime_path')
        if not isinstance(anime_paths, list):
            anime_paths = [anime_paths]
        # 总空间、剩余空间
        TotalSpace, FreeSpace = SystemUtils.calculate_space_usage(movie_paths + tv_paths + anime_paths)
        if TotalSpace:
            # 已使用空间
            UsedSapce = TotalSpace - FreeSpace
            # 百分比格式化
            UsedPercent = "%0.1f" % ((UsedSapce / TotalSpace) * 100)
            # 总剩余空间 格式化
            if FreeSpace > 1024:
                FreeSpace = "{:,} TB".format(round(FreeSpace / 1024, 2))
            else:
                FreeSpace = "{:,} GB".format(round(FreeSpace, 2))
            # 总使用空间 格式化
            if UsedSapce > 1024:
                UsedSapce = "{:,} TB".format(round(UsedSapce / 1024, 2))
            else:
                UsedSapce = "{:,} GB".format(round(UsedSapce, 2))
            # 总空间 格式化
            if TotalSpace > 1024:
                TotalSpace = "{:,} TB".format(round(TotalSpace / 1024, 2))
            else:
                TotalSpace = "{:,} GB".format(round(TotalSpace, 2))

        return {"code": 0,
                "UsedPercent": UsedPercent,
                "FreeSpace": FreeSpace,
                "UsedSapce": UsedSapce,
                "TotalSpace": TotalSpace}

    @staticmethod
    def get_transfer_statistics():
        """
        查询转移历史统计数据
        """
        Labels = []
        MovieNums = []
        TvNums = []
        AnimeNums = []
        for statistic in FileTransfer().get_transfer_statistics(90):
            if not statistic[2]:
                continue
            if statistic[1] not in Labels:
                Labels.append(statistic[1])
            if statistic[0] == "电影":
                MovieNums.append(statistic[2])
                TvNums.append(0)
                AnimeNums.append(0)
            elif statistic[0] == "电视剧":
                TvNums.append(statistic[2])
                MovieNums.append(0)
                AnimeNums.append(0)
            else:
                AnimeNums.append(statistic[2])
                MovieNums.append(0)
                TvNums.append(0)
        return {
            "code": 0,
            "Labels": Labels,
            "MovieNums": MovieNums,
            "TvNums": TvNums,
            "AnimeNums": AnimeNums
        }

    @staticmethod
    def get_library_mediacount():
        """
        查询媒体库统计数据
        """
        MediaServerClient = MediaServer()
        media_counts = MediaServerClient.get_medias_count()
        UserCount = MediaServerClient.get_user_count()
        if media_counts:
            return {
                "code": 0,
                "Movie": "{:,}".format(media_counts.get('MovieCount')),
                "Series": "{:,}".format(media_counts.get('SeriesCount')),
                "Episodes": "{:,}".format(media_counts.get('EpisodeCount')) if media_counts.get(
                    'EpisodeCount') else "",
                "Music": "{:,}".format(media_counts.get('SongCount')),
                "User": UserCount
            }
        else:
            return {"code": -1, "msg": "媒体库服务器连接失败"}

    @staticmethod
    def get_library_playhistory():
        """
        查询媒体库播放记录
        """
        return {"code": 0, "result": MediaServer().get_activity_log(30)}

    def get_search_result(self):
        """
        查询所有搜索结果
        """
        SearchResults = {}
        res = Searcher().get_search_results()
        total = len(res)
        for item in res:
            # 质量(来源、效果)、分辨率
            if item.RES_TYPE:
                try:
                    res_mix = json.loads(item.RES_TYPE)
                except Exception as err:
                    ExceptionUtils.exception_traceback(err)
                    continue
                respix = res_mix.get("respix") or ""
                video_encode = res_mix.get("video_encode") or ""
                restype = res_mix.get("restype") or ""
                reseffect = res_mix.get("reseffect") or ""
            else:
                restype = ""
                respix = ""
                reseffect = ""
                video_encode = ""
            # 分组标识 (来源，分辨率)
            group_key = re.sub(r"[-.\s@|]", "", f"{respix}_{restype}").lower()
            # 分组信息
            group_info = {
                "respix": respix,
                "restype": restype,
            }
            # 种子唯一标识 （大小，质量(来源、效果)，制作组组成）
            unique_key = re.sub(r"[-.\s@|]", "",
                                f"{respix}_{restype}_{video_encode}_{reseffect}_{item.SIZE}_{item.OTHERINFO}").lower()
            # 标识信息
            unique_info = {
                "video_encode": video_encode,
                "size": item.SIZE,
                "reseffect": reseffect,
                "releasegroup": item.OTHERINFO
            }
            # 结果
            title_string = f"{item.TITLE}"
            if item.YEAR:
                title_string = f"{title_string} ({item.YEAR})"
            # 电视剧季集标识
            mtype = item.TYPE or ""
            SE_key = item.ES_STRING if item.ES_STRING and mtype != "MOV" else "MOV"
            media_type = {"MOV": "电影", "TV": "电视剧", "ANI": "动漫"}.get(mtype)
            # 只需要部分种子标签
            labels = [label for label in str(item.NOTE).split("|")
                      if label in ["官方", "官组", "中字", "国语", "特效", "特效字幕"]]
            # 种子信息
            torrent_item = {
                "id": item.ID,
                "seeders": item.SEEDERS,
                "enclosure": item.ENCLOSURE,
                "site": item.SITE,
                "torrent_name": item.TORRENT_NAME,
                "description": item.DESCRIPTION,
                "pageurl": item.PAGEURL,
                "uploadvalue": item.UPLOAD_VOLUME_FACTOR,
                "downloadvalue": item.DOWNLOAD_VOLUME_FACTOR,
                "size": item.SIZE,
                "respix": respix,
                "restype": restype,
                "reseffect": reseffect,
                "releasegroup": item.OTHERINFO,
                "video_encode": video_encode,
                "labels": labels
            }
            # 促销
            free_item = {
                "value": f"{item.UPLOAD_VOLUME_FACTOR} {item.DOWNLOAD_VOLUME_FACTOR}",
                "name": MetaBase.get_free_string(item.UPLOAD_VOLUME_FACTOR, item.DOWNLOAD_VOLUME_FACTOR)
            }
            #分辨率
            if respix == "":
                respix = "未知分辨率"
            # 制作组、字幕组
            if item.OTHERINFO is None:
                releasegroup = "未知"
            else:
                releasegroup = item.OTHERINFO
            # 季
            filter_season = SE_key.split()[0] if SE_key and SE_key not in [
                "MOV", "TV"] else None
            # 合并搜索结果
            if SearchResults.get(title_string):
                # 种子列表
                result_item = SearchResults[title_string]
                torrent_dict = SearchResults[title_string].get("torrent_dict")
                SE_dict = torrent_dict.get(SE_key)
                if SE_dict:
                    group = SE_dict.get(group_key)
                    if group:
                        unique = group.get("group_torrents").get(unique_key)
                        if unique:
                            unique["torrent_list"].append(torrent_item)
                            group["group_total"] += 1
                        else:
                            group["group_total"] += 1
                            group.get("group_torrents")[unique_key] = {
                                "unique_info": unique_info,
                                "torrent_list": [torrent_item]
                            }
                    else:
                        SE_dict[group_key] = {
                            "group_info": group_info,
                            "group_total": 1,
                            "group_torrents": {
                                unique_key: {
                                    "unique_info": unique_info,
                                    "torrent_list": [torrent_item]
                                }
                            }
                        }
                else:
                    torrent_dict[SE_key] = {
                        group_key: {
                            "group_info": group_info,
                            "group_total": 1,
                            "group_torrents": {
                                unique_key: {
                                    "unique_info": unique_info,
                                    "torrent_list": [torrent_item]
                                }
                            }
                        }
                    }
                # 过滤条件
                torrent_filter = dict(result_item.get("filter"))
                if free_item not in torrent_filter.get("free"):
                    torrent_filter["free"].append(free_item)
                if releasegroup not in torrent_filter.get("releasegroup"):
                    torrent_filter["releasegroup"].append(releasegroup)
                if respix not in torrent_filter.get("respix"):
                    torrent_filter["respix"].append(respix)
                if item.SITE not in torrent_filter.get("site"):
                    torrent_filter["site"].append(item.SITE)
                if video_encode \
                        and video_encode not in torrent_filter.get("video"):
                    torrent_filter["video"].append(video_encode)
                if filter_season \
                        and filter_season not in torrent_filter.get("season"):
                    torrent_filter["season"].append(filter_season)
            else:
                fav, rssid = 0, None
                # 存在标志
                if item.TMDBID:
                    fav, rssid, item_url = self.get_media_exists_info(
                        mtype=mtype,
                        title=item.TITLE,
                        year=item.YEAR,
                        mediaid=item.TMDBID)

                SearchResults[title_string] = {
                    "key": item.ID,
                    "title": item.TITLE,
                    "year": item.YEAR,
                    "type_key": mtype,
                    "image": item.IMAGE,
                    "type": media_type,
                    "vote": item.VOTE,
                    "tmdbid": item.TMDBID,
                    "backdrop": item.IMAGE,
                    "poster": item.POSTER,
                    "overview": item.OVERVIEW,
                    "fav": fav,
                    "rssid": rssid,
                    "torrent_dict": {
                        SE_key: {
                            group_key: {
                                "group_info": group_info,
                                "group_total": 1,
                                "group_torrents": {
                                    unique_key: {
                                        "unique_info": unique_info,
                                        "torrent_list": [torrent_item]
                                    }
                                }
                            }
                        }
                    },
                    "filter": {
                        "site": [item.SITE],
                        "free": [free_item],
                        "releasegroup": [releasegroup],
                        "respix": [respix],
                        "video": [video_encode] if video_encode else [],
                        "season": [filter_season] if filter_season else []
                    }
                }

        # 提升整季的顺序到顶层
        def se_sort(k):
            k = re.sub(r" +|(?<=s\d)\D*?(?=e)|(?<=s\d\d)\D*?(?=e)",
                       " ", k[0], flags=re.I).split()
            return (k[0], k[1]) if len(k) > 1 else ("Z" + k[0], "ZZZ")

        # 开始排序季集顺序
        for title, item in SearchResults.items():
            # 排序筛选器 季
            item["filter"]["season"].sort(reverse=True)
            # 排序筛选器 制作组、字幕组.  将未知放到最后
            item["filter"]["releasegroup"] = sorted(item["filter"]["releasegroup"], key=lambda x: (x == "未知", x))
            # 排序种子列 集
            item["torrent_dict"] = sorted(item["torrent_dict"].items(),
                                          key=se_sort,
                                          reverse=True)
        return {"code": 0, "total": total, "result": SearchResults}

    @staticmethod
    def search_media_infos(data):
        """
        根据关键字搜索相似词条
        """
        SearchWord = data.get("keyword")
        if not SearchWord:
            return []
        SearchSourceType = data.get("searchtype")
        medias = WebUtils.search_media_infos(keyword=SearchWord,
                                             source=SearchSourceType)

        return {"code": 0, "result": [media.to_dict() for media in medias]}

    @staticmethod
    def get_movie_rss_list():
        """
        查询所有电影订阅
        """
        return {"code": 0, "result": Subscribe().get_subscribe_movies()}

    @staticmethod
    def get_tv_rss_list():
        """
        查询所有电视剧订阅
        """
        return {"code": 0, "result": Subscribe().get_subscribe_tvs()}

    @staticmethod
    def get_rss_history(data):
        """
        查询所有订阅历史
        """
        mtype = data.get("type")
        return {"code": 0, "result": [rec.as_dict() for rec in Rss().get_rss_history(rtype=mtype)]}

    @staticmethod
    def get_downloading(data = {}):
        """
        查询正在下载的任务
        """
        dl_id = data.get("id")
        force_list = data.get("force_list")
        MediaHander = Media()
        DownloaderHandler = Downloader()
        torrents = DownloaderHandler.get_downloading_progress(downloader_id=dl_id, force_list=bool(force_list))
        
        for torrent in torrents:
            # 先查询下载记录，没有再识别
            name = torrent.get("name")
            site_url = torrent.get("site_url")
            download_info = DownloaderHandler.get_download_history_by_downloader(
                downloader=DownloaderHandler.default_downloader_id,
                download_id=torrent.get("id")
            )
            if download_info:
                name = download_info.TITLE
                year = download_info.YEAR
                poster_path = download_info.POSTER
                se = download_info.SE
            else:
                media_info = MediaHander.get_media_info(title=name)
                if not media_info:
                    torrent.update({
                        "site_url": site_url,
                        "title": name,
                        "image": ""
                    })
                    continue
                year = media_info.year
                name = media_info.title or media_info.get_name()
                se = media_info.get_season_episode_string()
                poster_path = media_info.get_poster_image()
            # 拼装标题
            if year:
                title = "%s (%s) %s" % (name,
                                        year,
                                        se)
            else:
                title = "%s %s" % (name, se)

            torrent.update({
                "site_url": site_url,
                "title": title,
                "image": poster_path or ""
            })

        return {"code": 0, "result": torrents}

    @staticmethod
    def get_transfer_history(data):
        """
        查询媒体整理历史记录
        """
        PageNum = data.get("pagenum")
        if not PageNum:
            PageNum = 30
        SearchStr = data.get("keyword")
        CurrentPage = data.get("page")
        if not CurrentPage:
            CurrentPage = 1
        else:
            CurrentPage = int(CurrentPage)
        totalCount, historys = FileTransfer().get_transfer_history(SearchStr, CurrentPage, PageNum)
        historys_list = []
        for history in historys:
            history = history.as_dict()
            sync_mode = history.get("MODE")
            rmt_mode = ModuleConf.get_dictenum_key(
                ModuleConf.RMT_MODES, sync_mode) if sync_mode else ""
            history.update({
                "SYNC_MODE": sync_mode,
                "RMT_MODE": rmt_mode
            })
            historys_list.append(history)
        TotalPage = floor(totalCount / PageNum) + 1

        return {
            "code": 0,
            "total": totalCount,
            "result": historys_list,
            "totalPage": TotalPage,
            "pageNum": PageNum,
            "currentPage": CurrentPage
        }

    @staticmethod
    def truncate_transfer_history():
        """
        清空媒体整理历史记录
        """
        if FileTransfer().get_transfer_history_count() < 1:
            return { "code": 0, "result": True }
        FileTransfer().truncate_transfer_history_list()
        return { "code": 0, "result": True }

    @staticmethod
    def get_unknown_list():
        """
        查询所有未识别记录
        """
        Items = []
        Records = FileTransfer().get_transfer_unknown_paths()
        for rec in Records:
            if not rec.PATH:
                continue
            path = rec.PATH.replace("\\", "/") if rec.PATH else ""
            path_to = rec.DEST.replace("\\", "/") if rec.DEST else ""
            sync_mode = rec.MODE or ""
            rmt_mode = ModuleConf.get_dictenum_key(ModuleConf.RMT_MODES,
                                                   sync_mode) if sync_mode else ""
            Items.append({
                "id": rec.ID,
                "path": path,
                "to": path_to,
                "name": path,
                "sync_mode": sync_mode,
                "rmt_mode": rmt_mode,
            })

        return {"code": 0, "items": Items}

    @staticmethod
    def get_unknown_list_by_page(data):
        """
        查询所有未识别记录
        """
        PageNum = data.get("pagenum")
        if not PageNum:
            PageNum = 30
        SearchStr = data.get("keyword")
        CurrentPage = data.get("page")
        if not CurrentPage:
            CurrentPage = 1
        else:
            CurrentPage = int(CurrentPage)
        totalCount, Records = FileTransfer().get_transfer_unknown_paths_by_page(
            SearchStr, CurrentPage, PageNum)
        Items = []
        for rec in Records:
            if not rec.PATH:
                continue
            path = rec.PATH.replace("\\", "/") if rec.PATH else ""
            path_to = rec.DEST.replace("\\", "/") if rec.DEST else ""
            sync_mode = rec.MODE or ""
            rmt_mode = ModuleConf.get_dictenum_key(ModuleConf.RMT_MODES,
                                                   sync_mode) if sync_mode else ""
            Items.append({
                "id": rec.ID,
                "path": path,
                "to": path_to,
                "name": path,
                "sync_mode": sync_mode,
                "rmt_mode": rmt_mode,
            })
        TotalPage = floor(totalCount / PageNum) + 1

        return {
            "code": 0,
            "total": totalCount,
            "items": Items,
            "totalPage": TotalPage,
            "pageNum": PageNum,
            "currentPage": CurrentPage
        }

    @staticmethod
    def truncate_transfer_unknown(): 
        """
        清空媒体手动整理历史记录
        """
        if FileTransfer().get_transfer_unknown_count() < 1:
            return { "code": 0, "result": True }
        FileTransfer().truncate_transfer_unknown_list()
        return { "code": 0, "result": True }

    @staticmethod
    def unidentification():
        """
        重新识别所有未识别记录
        """
        ItemIds = []
        Records = FileTransfer().get_transfer_unknown_paths()
        for rec in Records:
            if not rec.PATH:
                continue
            ItemIds.append(rec.ID)

        if len(ItemIds) > 0:
            WebAction.re_identification({"flag": "unidentification", "ids": ItemIds})

    @staticmethod
    def get_customwords():
        _wordshelper = WordsHelper()
        words = []
        words_info = _wordshelper.get_custom_words(gid=-1)
        for word_info in words_info:
            words.append({"id": word_info.ID,
                          "replaced": word_info.REPLACED,
                          "replace": word_info.REPLACE,
                          "front": word_info.FRONT,
                          "back": word_info.BACK,
                          "offset": word_info.OFFSET,
                          "type": word_info.TYPE,
                          "group_id": word_info.GROUP_ID,
                          "season": word_info.SEASON,
                          "enabled": word_info.ENABLED,
                          "regex": word_info.REGEX,
                          "help": word_info.HELP, })
        groups = [{"id": "-1",
                   "name": "通用",
                   "link": "",
                   "type": "1",
                   "seasons": "0",
                   "words": words}]
        groups_info = _wordshelper.get_custom_word_groups()
        for group_info in groups_info:
            gid = group_info.ID
            name = "%s (%s)" % (group_info.TITLE, group_info.YEAR)
            gtype = group_info.TYPE
            if gtype == 1:
                link = "https://www.themoviedb.org/movie/%s" % group_info.TMDBID
            else:
                link = "https://www.themoviedb.org/tv/%s" % group_info.TMDBID
            words = []
            words_info = _wordshelper.get_custom_words(gid=gid)
            for word_info in words_info:
                words.append({"id": word_info.ID,
                              "replaced": word_info.REPLACED,
                              "replace": word_info.REPLACE,
                              "front": word_info.FRONT,
                              "back": word_info.BACK,
                              "offset": word_info.OFFSET,
                              "type": word_info.TYPE,
                              "group_id": word_info.GROUP_ID,
                              "season": word_info.SEASON,
                              "enabled": word_info.ENABLED,
                              "regex": word_info.REGEX,
                              "help": word_info.HELP, })
            groups.append({"id": gid,
                           "name": name,
                           "link": link,
                           "type": group_info.TYPE,
                           "seasons": group_info.SEASON_COUNT,
                           "words": words})
        return {
            "code": 0,
            "result": groups
        }

    @staticmethod
    def get_users():
        """
        查询所有用户
        """
        user_list = ProUser().get_users()
        Users = []
        for user in user_list:
            pris = str(user.PRIS).split(",")
            Users.append({"id": user.ID, "name": user.NAME, "pris": pris})
        return {"code": 0, "result": Users}

    @staticmethod
    def get_filterrules():
        """
        查询所有过滤规则
        """
        RuleGroups = Filter().get_rule_infos()
        sql_file = os.path.join(Config().get_script_path(), "init_filter.sql")
        with open(sql_file, "r", encoding="utf-8") as f:
            sql_list = f.read().split(';\n')
            Init_RuleGroups = []
            i = 0
            while i < len(sql_list):
                rulegroup = {}
                rulegroup_info = re.findall(
                    r"[0-9]+,'[^\"]+NULL", sql_list[i], re.I)[0].split(",")
                rulegroup['id'] = int(rulegroup_info[0])
                rulegroup['name'] = rulegroup_info[1][1:-1]
                rulegroup['rules'] = []
                rulegroup['sql'] = [sql_list[i]]
                if i + 1 < len(sql_list):
                    rules = re.findall(
                        r"[0-9]+,'[^\"]+NULL", sql_list[i + 1], re.I)[0].split("),\n (")
                    for rule in rules:
                        rule_info = {}
                        rule = rule.split(",")
                        rule_info['name'] = rule[2][1:-1]
                        rule_info['include'] = rule[4][1:-1]
                        rule_info['exclude'] = rule[5][1:-1]
                        rulegroup['rules'].append(rule_info)
                    rulegroup["sql"].append(sql_list[i + 1])
                Init_RuleGroups.append(rulegroup)
                i = i + 2
        return {
            "code": 0,
            "ruleGroups": RuleGroups,
            "initRules": Init_RuleGroups
        }

    def __update_directory(self, data):
        """
        维护媒体库目录
        """
        cfg = self.set_config_directory(Config().get_config(),
                                        data.get("oper"),
                                        data.get("key"),
                                        data.get("value"),
                                        data.get("replace_value"))
        # 保存配置
        Config().save_config(cfg)
        return {"code": 0}

    @staticmethod
    def __test_site(data):
        """
        测试站点连通性
        """
        flag, msg, times, web_data = asyncio.run(Sites().test_connection(data.get("id")))
        code = 0 if flag else -1
        return {"code": code, "msg": msg, "time": times}

    @staticmethod
    def __get_sub_path(data):
        """
        查询下级子目录
        """
        r = []
        try:
            ft = data.get("filter") or "ALL"
            d = data.get("dir")
            if not d or d == "/":
                if SystemUtils.get_system() == OsType.WINDOWS:
                    partitions = SystemUtils.get_windows_drives()
                    if partitions:
                        dirs = [os.path.join(partition, "/")
                                for partition in partitions]
                    else:
                        dirs = [os.path.join("C:/", f)
                                for f in os.listdir("C:/")]
                else:
                    dirs = [os.path.join("/", f) for f in os.listdir("/")]
            elif d == "*SYNC-FOLDERS*":
                sync_dirs = []
                for id, conf in Sync().get_sync_path_conf().items():
                    sync_dirs.append(conf["from"])
                    sync_dirs.append(conf["to"])
                dirs = list(set(sync_dirs))
            elif d == "*DOWNLOAD-FOLDERS*":
                dirs = [path.rstrip('/') for path in Downloader().get_download_visit_dirs()]
            elif d == "*MEDIA-FOLDERS*":
                media_dirs = []
                movie_path = Config().get_config('media').get('movie_path')
                tv_path = Config().get_config('media').get('tv_path')
                anime_path = Config().get_config('media').get('anime_path')
                unknown_path = Config().get_config('media').get('unknown_path')
                if movie_path is not None: media_dirs.extend([path.rstrip('/') for path in movie_path])
                if tv_path is not None: media_dirs.extend([path.rstrip('/') for path in tv_path])
                if anime_path is not None: media_dirs.extend([path.rstrip('/') for path in anime_path])
                if unknown_path is not None: media_dirs.extend([path.rstrip('/') for path in unknown_path])   
                dirs = list(set(media_dirs))             
            else:
                d = os.path.normpath(unquote(d))
                if not os.path.isdir(d):
                    d = os.path.dirname(d)
                dirs = [os.path.join(d, f) for f in os.listdir(d)]
            dirs.sort()
            for ff in dirs:
                if os.path.isdir(ff):
                    if 'ONLYDIR' in ft or 'ALL' in ft:
                        r.append({
                            "path": ff.replace("\\", "/"),
                            "name": os.path.basename(ff),
                            "type": "dir",
                            "rel": os.path.dirname(ff).replace("\\", "/")
                        })
                else:
                    ext = os.path.splitext(ff)[-1][1:]
                    flag = False
                    if 'ONLYFILE' in ft or 'ALL' in ft:
                        flag = True
                    elif "MEDIAFILE" in ft and f".{str(ext).lower()}" in RMT_MEDIAEXT:
                        flag = True
                    elif "SUBFILE" in ft and f".{str(ext).lower()}" in RMT_SUBEXT:
                        flag = True
                    elif "AUDIOTRACKFILE" in ft and f".{str(ext).lower()}" in RMT_AUDIO_TRACK_EXT:
                        flag = True
                    if flag:
                        r.append({
                            "path": ff.replace("\\", "/"),
                            "name": os.path.basename(ff),
                            "type": "file",
                            "rel": os.path.dirname(ff).replace("\\", "/"),
                            "ext": ext,
                            "size": StringUtils.str_filesize(os.path.getsize(ff))
                        })

        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            return {
                "code": -1,
                "message": '加载路径失败: %s' % str(e)
            }
        return {
            "code": 0,
            "count": len(r),
            "data": r
        }

    @staticmethod
    def __get_filehardlinks(data):
        """
        获取文件硬链接
        """            
        def parse_hardlinks(hardlinks):
            paths = []
            for link in hardlinks:
                paths.append([SystemUtils.shorten_path(link["file"], 'left', 2), link["file"], link["filepath"]])      
            return paths
        r = {}
        try:
            file = data.get("filepath")
            direction = ""
            hardlinks = []
            # 获取所有硬链接的同步目录设置
            sync_dirs = Sync().get_filehardlinks_sync_dirs()  
            # 按设置遍历检查文件是否在同步目录内，只查找第一个匹配项，多余的忽略
            for dir in sync_dirs:
                if dir[0] and file.startswith(f"{dir[0]}/"):
                    direction = '→'
                    hardlinks = parse_hardlinks(SystemUtils().find_hardlinks(file=file, fdir=dir[1]))
                    break
                elif dir[1] and file.startswith(f"{dir[1]}/"):
                    direction = '←'
                    hardlinks = parse_hardlinks(SystemUtils().find_hardlinks(file=file, fdir=dir[0]))
                    break     
            r={
                "filepath": file,  # 文件路径
                "direction": direction,  # 同步方向
                "hardlinks": hardlinks  # 同步链接，内容分别为缩略路径、文件路径、目录路径
            }
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            return {
                "code": -1,
                "message": '加载路径失败: %s' % str(e)
            }
        return {
            "code": 0,
            "count": len(r),
            "data": r
        }
        
    @staticmethod
    def __get_dirhardlink(data):
        """
        获取同步目录硬链接
        """            
        r = {}
        try:
            path = data.get("dirpath")
            direction = ""
            hardlink = []
            locating = False
            # 获取所有硬链接的同步目录设置
            sync_dirs = Sync().get_filehardlinks_sync_dirs()    
            # 按设置遍历检查目录是否是同步目录或在同步目录内             
            for dir in sync_dirs:
                if dir[0] and (dir[0] == path or path.startswith(f"{dir[0]}/")):
                    direction = '→'
                    hardlink = dir[0].replace(dir[0], dir[1])
                    locating = dir[2]
                    break
                elif dir[1] and (dir[1] == path or path.startswith(f"{dir[1]}/")):
                    direction = '←'
                    hardlink = dir[1].replace(dir[1], dir[0])
                    locating = dir[2]
                    break
            r={
                "dirpath": path,  # 同步目录路径
                "direction": direction,  # 同步方向
                "hardlink": hardlink,  # 同步链接，内容为配置中对应的目录或子目录
                "locating": locating  # 自动定位
            }
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            return {
                "code": -1,
                "message": '加载路径失败: %s' % str(e)
            }
        return {
            "code": 0,
            "count": len(r),
            "data": r
        }
        
    @staticmethod
    def __rename_file(data):
        """
        文件重命名
        """
        path = data.get("path")
        name = data.get("name")
        if path and name:
            try:
                shutil.move(path, os.path.join(os.path.dirname(path), name))
            except Exception as e:
                ExceptionUtils.exception_traceback(e)
                return {"code": -1, "msg": str(e)}
        return {"code": 0}

    def __delete_files(self, data):
        """
        删除文件
        """
        files = data.get("files")
        if files:
            # 删除文件
            for file in files:
                del_flag, del_msg = self.delete_media_file(filedir=os.path.dirname(file),
                                                           filename=os.path.basename(file))
                if not del_flag:
                    log.error(del_msg)
                else:
                    log.info(del_msg)
        return {"code": 0}

    @staticmethod
    def __download_subtitle(data):
        """
        从配置的字幕服务下载单个文件的字幕
        """
        path = data.get("path")
        name = data.get("name")
        media = Media().get_media_info(title=name)
        if not media or not media.tmdb_info:
            return {"code": -1, "msg": f"{name} 无法从TMDB查询到媒体信息"}
        if not media.imdb_id:
            media.set_tmdb_info(Media().get_tmdb_info(mtype=media.type,
                                                      tmdbid=media.tmdb_id))
        # 触发字幕下载事件
        EventManager().send_event(EventType.SubtitleDownload, {
            "media_info": media.to_dict(),
            "file": os.path.splitext(path)[0],
            "file_ext": os.path.splitext(name)[-1],
            "bluray": False
        })
        return {"code": 0, "msg": "字幕下载任务已提交，正在后台运行。"}

    @staticmethod
    def __media_path_scrap(data):
        """
        刮削媒体文件夹或文件
        """
        path = data.get("path")
        if not path:
            return {"code": -1, "msg": "请指定刮削路径"}
        ThreadHelper().start_thread(Scraper().folder_scraper, (path, None, 'force_all'))
        return {"code": 0, "msg": "刮削任务已提交，正在后台运行。"}

    @staticmethod
    def __get_download_setting(data):
        sid = data.get("sid")
        if sid:
            download_setting = Downloader().get_download_setting(sid=sid)
        else:
            download_setting = list(
                Downloader().get_download_setting().values())
        return {"code": 0, "data": download_setting}

    @staticmethod
    def __update_download_setting(data):
        sid = data.get("sid")
        name = data.get("name")
        category = data.get("category")
        tags = data.get("tags")
        is_paused = data.get("is_paused")
        upload_limit = data.get("upload_limit")
        download_limit = data.get("download_limit")
        ratio_limit = data.get("ratio_limit")
        seeding_time_limit = data.get("seeding_time_limit")
        downloader = data.get("downloader")
        Downloader().update_download_setting(sid=sid,
                                             name=name,
                                             category=category,
                                             tags=tags,
                                             is_paused=is_paused,
                                             upload_limit=upload_limit or 0,
                                             download_limit=download_limit or 0,
                                             ratio_limit=ratio_limit or 0,
                                             seeding_time_limit=seeding_time_limit or 0,
                                             downloader=downloader)
        return {"code": 0}

    @staticmethod
    def __delete_download_setting(data):
        sid = data.get("sid")
        Downloader().delete_download_setting(sid=sid)
        return {"code": 0}

    @staticmethod
    def __update_message_client(data):
        """
        更新消息设置
        """
        _message = Message()
        name = data.get("name")
        cid = data.get("cid")
        ctype = data.get("type")
        config = data.get("config")
        switchs = data.get("switchs")
        interactive = data.get("interactive")
        enabled = data.get("enabled")
        if cid:
            _message.delete_message_client(cid=cid)
        if int(interactive) == 1:
            _message.check_message_client(interactive=0, ctype=ctype)
        _message.insert_message_client(name=name,
                                       ctype=ctype,
                                       config=config,
                                       switchs=switchs,
                                       interactive=interactive,
                                       enabled=enabled)
        return {"code": 0}

    @staticmethod
    def __delete_message_client(data):
        """
        删除消息设置
        """
        if Message().delete_message_client(cid=data.get("cid")):
            return {"code": 0}
        else:
            return {"code": 1}

    @staticmethod
    def __check_message_client(data):
        """
        维护消息设置
        """
        flag = data.get("flag")
        cid = data.get("cid")
        ctype = data.get("type")
        checked = data.get("checked")
        _message = Message()
        if flag == "interactive":
            # TG/WX只能开启一个交互
            if checked:
                _message.check_message_client(interactive=0, ctype=ctype)
            _message.check_message_client(cid=cid,
                                          interactive=1 if checked else 0)
            return {"code": 0}
        elif flag == "enable":
            _message.check_message_client(cid=cid,
                                          enabled=1 if checked else 0)
            return {"code": 0}
        else:
            return {"code": 1}

    @staticmethod
    def __get_message_client(data):
        """
        获取消息设置
        """
        cid = data.get("cid")
        return {"code": 0, "detail": Message().get_message_client_info(cid=cid)}

    @staticmethod
    def __test_message_client(data):
        """
        测试消息设置
        """
        ctype = data.get("type")
        config = json.loads(data.get("config"))
        res = Message().get_status(ctype=ctype, config=config)
        if res:
            return {"code": 0}
        else:
            return {"code": 1}

    @staticmethod
    def __get_indexers():
        """
        获取索引器
        """
        return {"code": 0, "indexers": Indexer().get_indexer_dict()}

    @staticmethod
    def __get_download_dirs(data):
        """
        获取下载目录
        """
        sid = data.get("sid")
        site = data.get("site")
        if not sid and site:
            sid = Sites().get_site_download_setting(site_name=site)
        dirs = Downloader().get_download_dirs(setting=sid)
        return {"code": 0, "paths": dirs}

    @staticmethod
    def __find_hardlinks(data):
        files = data.get("files")
        file_dir = data.get("dir")
        if not files:
            return []
        if not file_dir and os.name != "nt":
            # 取根目录下一级为查找目录
            file_dir = os.path.commonpath(files).replace("\\", "/")
            if file_dir != "/":
                file_dir = "/" + str(file_dir).split("/")[1]
            else:
                return []
        hardlinks = {}
        if files:
            try:
                for file in files:
                    hardlinks[os.path.basename(file)] = SystemUtils(
                    ).find_hardlinks(file=file, fdir=file_dir)
            except Exception as e:
                ExceptionUtils.exception_traceback(e)
                return {"code": 1}
        return {"code": 0, "data": hardlinks}

    @staticmethod
    def __update_sites_cookie_ua(data):
        """
        更新所有站点的Cookie和UA
        """
        siteid = data.get("siteid")
        username = data.get("username")
        password = data.get("password")
        twostepcode = data.get("two_step_code")
        ocrflag = data.get("ocrflag")
        # 保存设置
        SystemConfig().set(key=f"{SystemConfigKey.CookieUserInfo}_{siteid}",
                           value={
                               "username": username,
                               "password": password,
                               "two_step_code": twostepcode
                           })
        retcode, messages = asyncio.run(SiteCookie().update_sites_cookie_ua(siteid=siteid,
                                                                username=username,
                                                                password=password,
                                                                twostepcode=twostepcode,
                                                                ocrflag=ocrflag))
        return {"code": retcode, "messages": messages}

    @staticmethod
    def __update_site_cookie_ua(data):
        """
        更新单个站点的Cookie和UA
        """
        siteid = data.get("site_id")
        cookie = data.get("site_cookie")
        ua = data.get("site_ua")
        Sites().update_site_cookie(siteid=siteid, cookie=cookie, ua=ua)
        return {"code": 0, "messages": "请求发送成功"}

    @staticmethod
    def __set_site_captcha_code(data):
        """
        设置站点验证码
        """
        code = data.get("code")
        value = data.get("value")
        SiteCookie().set_code(code=code, value=value)
        return {"code": 0}

    @staticmethod
    def __update_torrent_remove_task(data):
        """
        更新自动删种任务
        """
        flag, msg = TorrentRemover().update_torrent_remove_task(data=data)
        if not flag:
            return {"code": 1, "msg": msg}
        else:
            return {"code": 0}

    @staticmethod
    def __get_torrent_remove_task(data=None):
        """
        获取自动删种任务
        """
        if data:
            tid = data.get("tid")
        else:
            tid = None
        return {"code": 0, "detail": TorrentRemover().get_torrent_remove_tasks(taskid=tid)}

    @staticmethod
    def __delete_torrent_remove_task(data):
        """
        删除自动删种任务
        """
        tid = data.get("tid")
        flag = TorrentRemover().delete_torrent_remove_task(taskid=tid)
        if flag:
            return {"code": 0}
        else:
            return {"code": 1}

    @staticmethod
    def __get_remove_torrents(data):
        """
        获取满足自动删种任务的种子
        """
        tid = data.get("tid")
        flag, torrents = TorrentRemover().get_remove_torrents(taskid=tid)
        if not flag or not torrents:
            return {"code": 1, "msg": "未获取到符合处理条件种子"}
        return {"code": 0, "data": torrents}

    @staticmethod
    def __auto_remove_torrents(data):
        """
        执行自动删种任务
        """
        tid = data.get("tid")
        TorrentRemover().auto_remove_torrents(taskids=tid)
        return {"code": 0}

    @staticmethod
    def __get_site_favicon(data):
        """
        获取站点图标
        """
        sitename = data.get("name")
        return {"code": 0, "icon": Sites().get_site_favicon(site_name=sitename)}

    @staticmethod
    def __list_brushtask_torrents(data):
        """
        获取刷流任务的种子明细
        """
        results = BrushTask().get_brushtask_torrents(brush_id=data.get("id"),
                                                     active=False)
        if not results:
            return {"code": 1, "msg": "未下载种子或未获取到种子明细"}
        # 返回最多300个，优化页面性能
        if len(results) > 0:
            results = results[0: min(300, len(results))]
        return {"code": 0, "data": [item.as_dict() for item in results]}

    @staticmethod
    def __set_system_config(data):
        """
        设置系统设置（数据库）
        """
        key = data.get("key")
        value = data.get("value")
        if not key:
            return {"code": 1}
        try:
            SystemConfig().set(key=key, value=value)
            return {"code": 0}
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            return {"code": 1}

    @staticmethod
    def get_site_user_statistics(data):
        """
        获取站点用户统计信息
        """
        sites = data.get("sites")
        encoding = data.get("encoding") or "RAW"
        sort_by = data.get("sort_by")
        sort_on = data.get("sort_on")
        site_hash = data.get("site_hash")
        statistics = SiteUserInfo().get_site_user_statistics(sites=sites, encoding=encoding)
        if sort_by and sort_on in ["asc", "desc"]:
            if sort_on == "asc":
                statistics.sort(key=lambda x: x[sort_by])
            else:
                statistics.sort(key=lambda x: x[sort_by], reverse=True)
        if site_hash == "Y":
            for item in statistics:
                item["site_hash"] = StringUtils.md5_hash(item.get("site"))
        for item in statistics:
            item['last_seen'] = TimeUtils.time_difference(item['last_seen'])
            item['update_at'] = TimeUtils.time_difference(item['update_at'])
            if TimeUtils.less_than_days(item['join_at'], 31):
                item['level_description'] = "新手"
            else:
                item['level_description'] = ""
        return {"code": 0, "data": statistics}

    @staticmethod
    def send_plugin_message(data):
        """
        发送插件消息
        """
        title = data.get("title")
        text = data.get("text") or ""
        image = data.get("image") or ""
        Message().send_plugin_message(title=title, text=text, image=image)
        return {"code": 0}

    @staticmethod
    def send_custom_message(data):
        """
        发送自定义消息
        """
        title = data.get("title")
        text = data.get("text") or ""
        image = data.get("image") or ""
        message_clients = data.get("message_clients")
        if not message_clients:
            return {"code": 1, "msg": "未选择消息服务"}
        Message().send_custom_message(clients=message_clients, title=title, text=text, image=image)
        return {"code": 0}

    @staticmethod
    def get_rmt_modes():
        RmtModes = ModuleConf.RMT_MODES_LITE if SystemUtils.is_lite_version(
        ) else ModuleConf.RMT_MODES
        return [{
            "value": value,
            "name": name.value
        } for value, name in RmtModes.items()]

    def media_detail(self, data):
        """
        获取媒体详情
        """
        # TMDBID 或 DB:豆瓣ID
        tmdbid = data.get("tmdbid")
        mtype = MediaType.MOVIE if data.get(
            "type") in MovieTypes else MediaType.TV
        if not tmdbid:
            return {"code": 1, "msg": "未指定媒体ID"}
        media_info = WebUtils.get_mediainfo_from_id(
            mtype=mtype, mediaid=tmdbid)
        # 检查TMDB信息
        if not media_info or not media_info.tmdb_info:
            return {
                "code": 1,
                "msg": "无法查询到TMDB信息"
            }
        # 查询存在及订阅状态
        fav, rssid, item_url = self.get_media_exists_info(mtype=mtype,
                                                          title=media_info.title,
                                                          year=media_info.year,
                                                          mediaid=media_info.tmdb_id)
        MediaHandler = Media()
        MediaServerHandler = MediaServer()
        # 查询季
        seasons = MediaHandler.get_tmdb_tv_seasons(media_info.tmdb_info)
        # 查询季是否存在
        if seasons:
            for season in seasons:
                season.update({
                    "state": True if MediaServerHandler.check_item_exists(
                        mtype=mtype,
                        title=media_info.title,
                        year=media_info.year,
                        tmdbid=media_info.tmdb_id,
                        season=season.get("season_number")) else False
                })
        return {
            "code": 0,
            "data": {
                "tmdbid": media_info.tmdb_id,
                "douban_id": media_info.douban_id,
                "background": MediaHandler.get_tmdb_backdrops(tmdbinfo=media_info.tmdb_info),
                "image": media_info.get_poster_image(),
                "vote": media_info.vote_average,
                "year": media_info.year,
                "title": media_info.title,
                "genres": MediaHandler.get_tmdb_genres_names(tmdbinfo=media_info.tmdb_info),
                "overview": media_info.overview,
                "runtime": StringUtils.str_timehours(media_info.runtime),
                "fact": MediaHandler.get_tmdb_factinfo(media_info),
                "crews": MediaHandler.get_tmdb_crews(tmdbinfo=media_info.tmdb_info, nums=6),
                "actors": MediaHandler.get_tmdb_cats(mtype=mtype, tmdbid=media_info.tmdb_id),
                "link": media_info.get_detail_url(),
                "douban_link": media_info.get_douban_detail_url(),
                "fav": fav,
                "item_url": item_url,
                "rssid": rssid,
                "seasons": seasons
            }
        }

    @staticmethod
    def __media_similar(data):
        """
        查询TMDB相似媒体
        """
        tmdbid = data.get("tmdbid")
        page = data.get("page") or 1
        mtype = MediaType.MOVIE if data.get(
            "type") in MovieTypes else MediaType.TV
        if not tmdbid:
            return {"code": 1, "msg": "未指定TMDBID"}
        if mtype == MediaType.MOVIE:
            result = Media().get_movie_similar(tmdbid=tmdbid, page=page)
        else:
            result = Media().get_tv_similar(tmdbid=tmdbid, page=page)
        return {"code": 0, "data": result}

    @staticmethod
    def __media_recommendations(data):
        """
        查询TMDB同类推荐媒体
        """
        tmdbid = data.get("tmdbid")
        page = data.get("page") or 1
        mtype = MediaType.MOVIE if data.get(
            "type") in MovieTypes else MediaType.TV
        if not tmdbid:
            return {"code": 1, "msg": "未指定TMDBID"}
        if mtype == MediaType.MOVIE:
            result = Media().get_movie_recommendations(tmdbid=tmdbid, page=page)
        else:
            result = Media().get_tv_recommendations(tmdbid=tmdbid, page=page)
        return {"code": 0, "data": result}

    @staticmethod
    def __media_person(data):
        """
        根据TMDBID或关键字查询TMDB演员
        """
        tmdbid = data.get("tmdbid")
        mtype = MediaType.MOVIE if data.get("type") in MovieTypes else MediaType.TV
        keyword = data.get("keyword")
        if not tmdbid and not keyword:
            return {"code": 1, "msg": "未指定TMDBID或关键字"}
        if tmdbid:
            result = Media().get_tmdb_cats(tmdbid=tmdbid, mtype=mtype)
        else:
            result = Media().search_tmdb_person(name=keyword)
        return {"code": 0, "data": result}

    @staticmethod
    def __person_medias(data):
        """
        查询演员参演作品
        """
        personid = data.get("personid")
        page = data.get("page") or 1
        if data.get("type"):
            mtype = MediaType.MOVIE if data.get("type") in MovieTypes else MediaType.TV
        else:
            mtype = None
        if not personid:
            return {"code": 1, "msg": "未指定演员ID"}
        return {"code": 0, "data": Media().get_person_medias(personid=personid,
                                                             mtype=mtype,
                                                             page=page)}

    @staticmethod
    def __save_user_script(data):
        """
        保存用户自定义脚本
        """
        script = data.get("javascript") or ""
        css = data.get("css") or ""
        SystemConfig().set(key=SystemConfigKey.CustomScript,
                           value={
                               "css": css,
                               "javascript": script
                           })
        return {"code": 0, "msg": "保存成功"}

    @staticmethod
    def __run_directory_sync(data):
        """
        执行单个目录的目录同步
        """
        ThreadHelper().start_thread(Sync().transfer_sync, (data.get("sid"),))
        return {"code": 0, "msg": "执行成功"}

    @staticmethod
    def __update_plugin_config(data):
        """
        保存插件配置
        """
        plugin_id = data.get("plugin")
        config = data.get("config")
        if not plugin_id:
            return {"code": 1, "msg": "数据错误"}
        PluginManager().save_plugin_config(pid=plugin_id, conf=config)
        PluginManager().reload_plugin(plugin_id)
        return {"code": 0, "msg": "保存成功"}

    @staticmethod
    def get_media_exists_info(mtype, title, year, mediaid):
        """
        获取媒体存在标记：是否存在、是否订阅
        :param: mtype 媒体类型
        :param: title 媒体标题
        :param: year 媒体年份
        :param: mediaid TMDBID/DB:豆瓣ID/BG:Bangumi的ID
        :return: 1-已订阅/2-已下载/0-不存在未订阅, RSSID, 如果已下载,还会有对应的媒体库的播放地址链接
        """
        if str(mediaid).isdigit():
            tmdbid = mediaid
        else:
            tmdbid = None
        if mtype in MovieTypes:
            rssid = Subscribe().get_subscribe_id(mtype=MediaType.MOVIE,
                                                 title=title,
                                                 year=year,
                                                 tmdbid=tmdbid)
        else:
            if not tmdbid:
                meta_info = MetaInfo(title=title)
                title = meta_info.get_name()
                season = meta_info.get_season_string()
                if season:
                    year = None
            else:
                season = None
            rssid = Subscribe().get_subscribe_id(mtype=MediaType.TV,
                                                 title=title,
                                                 year=year,
                                                 season=season,
                                                 tmdbid=tmdbid)
        item_url = None
        if rssid:
            # 已订阅
            fav = "1"
        else:
            # 检查媒体服务器是否存在
            item_id = MediaServer().check_item_exists(mtype=mtype, title=title, year=year, tmdbid=tmdbid)
            if item_id:
                # 已下载
                fav = "2"
                item_url = MediaServer().get_play_url(item_id=item_id)
            else:
                # 未订阅、未下载
                fav = "0"
        return fav, rssid, item_url

    @staticmethod
    def __get_season_episodes(data=None):
        """
        查询TMDB剧集情况
        """
        tmdbid = data.get("tmdbid")
        title = data.get("title")
        year = data.get("year")
        season = 1 if data.get("season") is None else data.get("season")
        if not tmdbid:
            return {"code": 1, "msg": "TMDBID为空"}
        episodes = Media().get_tmdb_season_episodes(tmdbid=tmdbid,
                                                    season=season)
        MediaServerHandler = MediaServer()
        for episode in episodes:
            episode.update({
                "state": True if MediaServerHandler.check_item_exists(
                    mtype=MediaType.TV,
                    title=title,
                    year=year,
                    tmdbid=tmdbid,
                    season=season,
                    episode=episode.get("episode_number")) else False
            })
        return {
            "code": 0,
            "episodes": episodes
        }

    @staticmethod
    def get_user_menus():
        """
        查询用户菜单
        """
        # 需要过滤的菜单
        ignore = []
        # 获取可用菜单
        menus = current_user.get_usermenus(ignore=ignore)
        return {
            "code": 0,
            "menus": menus,
            "level": current_user.level
        }

    @staticmethod
    def get_top_menus():
        """
        查询顶底菜单列表
        """
        return {
            "code": 0,
            "menus": current_user.get_topmenus()
        }

    @staticmethod
    def auth_user_level(data=None):
        """
        用户认证
        """
        if data:
            site = data.get("site")
            params = data.get("params")
        else:
            site, params = None, {}
        state, msg = ProUser().check_user(site, params)
        if state:
            return {"code": 0, "msg": "认证成功"}
        return {"code": 1, "msg": f"{msg or '认证失败，请检查合作站点账号是否正常！'}"}

    @staticmethod
    def __update_downloader(data):
        """
        更新下载器
        """
        did = data.get("did")
        name = data.get("name")
        dtype = data.get("type")
        enabled = data.get("enabled")
        transfer = data.get("transfer")
        only_nastool = data.get("only_nastool")
        match_path = data.get("match_path")
        rmt_mode = data.get("rmt_mode")
        config = data.get("config")
        if not isinstance(config, str):
            config = json.dumps(config)
        download_dir = data.get("download_dir")
        if not isinstance(download_dir, str):
            download_dir = json.dumps(download_dir)
        Downloader().update_downloader(did=did,
                                       name=name,
                                       dtype=dtype,
                                       enabled=enabled,
                                       transfer=transfer,
                                       only_nastool=only_nastool,
                                       match_path=match_path,
                                       rmt_mode=rmt_mode,
                                       config=config,
                                       download_dir=download_dir)
        return {"code": 0}

    @staticmethod
    def __del_downloader(data):
        """
        删除下载器
        """
        did = data.get("did")
        Downloader().delete_downloader(did=did)
        return {"code": 0}

    @staticmethod
    def __check_downloader(data):
        """
        检查下载器
        """
        did = data.get("did")
        if not did:
            return {"code": 1}
        checked = data.get("checked")
        flag = data.get("flag")
        enabled, transfer, only_nastool, match_path = None, None, None, None
        if flag == "enabled":
            enabled = 1 if checked else 0
        elif flag == "transfer":
            transfer = 1 if checked else 0
        elif flag == "only_nastool":
            only_nastool = 1 if checked else 0
        elif flag == "match_path":
            match_path = 1 if checked else 0
        Downloader().check_downloader(did=did,
                                      enabled=enabled,
                                      transfer=transfer,
                                      only_nastool=only_nastool,
                                      match_path=match_path)
        return {"code": 0}

    @staticmethod
    def __get_downloaders(data):
        """
        获取下载器
        """
        def add_is_default(dl_conf, defualt_id):
            dl_conf["is_default"] = str(dl_conf["id"]) == defualt_id
            return dl_conf
        
        did = data.get("did")
        downloader = Downloader()
        resp = downloader.get_downloader_conf(did=did)
        default_dl_id = downloader.default_downloader_id

        if did:
            """
              单个下载器 conf
            """
            return {"code": 0, "detail": add_is_default(copy.deepcopy(resp), default_dl_id) if resp else None}
        else:
            """
              所有下载器 conf
            """
            confs = copy.deepcopy(resp)
            for key in confs:
                add_is_default(confs[key], default_dl_id)

            return {"code": 0, "detail": confs}

    @staticmethod
    def __test_downloader(data):
        """
        测试下载器
        """
        dtype = data.get("type")
        config = json.loads(data.get("config"))
        res = Downloader().get_status(dtype=dtype, config=config)
        if res:
            return {"code": 0}
        else:
            return {"code": 1}

    @staticmethod
    def __get_indexer_statistics():
        """
        获取索引器统计数据
        """
        dataset = [["indexer", "avg"]]
        result = Indexer().get_indexer_statistics() or []
        dataset.extend([[ret[0], round(ret[4], 1)] for ret in result])
        return {
            "code": 0,
            "data": [{
                "name": ret[0],
                "total": ret[1],
                "fail": ret[2],
                "success": ret[3],
                "avg": round(ret[4], 1),
            } for ret in result],
            "dataset": dataset
        }

    @staticmethod
    def user_statistics():
        """
        强制刷新站点数据,并发送站点统计的消息
        """
        # 强制刷新站点数据,并发送站点统计的消息
        SiteUserInfo().refresh_site_data_now()

    @staticmethod
    def get_default_rss_setting(data):
        """
        获取默认订阅设置
        """
        match data.get("mtype"):
            case "TV":
                default_rss_setting = Subscribe().default_rss_setting_tv
            case "MOV":
                default_rss_setting = Subscribe().default_rss_setting_mov
            case _:
                default_rss_setting = {}
        if default_rss_setting:
            return {"code": 0, "data": default_rss_setting}
        return {"code": 1}

    @staticmethod
    def get_movie_rss_items():
        """
        获取所有电影订阅项目
        """
        RssMovieItems = [
            {
                "id": movie.get("tmdbid"),
                "rssid": movie.get("id")
            } for movie in Subscribe().get_subscribe_movies().values() if movie.get("tmdbid")
        ]
        return {"code": 0, "result": RssMovieItems}

    @staticmethod
    def get_tv_rss_items():
        """
        获取所有电视剧订阅项目
        """
        # 电视剧订阅
        RssTvItems = [
            {
                "id": tv.get("tmdbid"),
                "rssid": tv.get("id"),
                "season": int(str(tv.get('season')).replace("S", "")),
                "name": tv.get("name"),
            } for tv in Subscribe().get_subscribe_tvs().values() if tv.get('season') and tv.get("tmdbid")
        ]
        # 自定义订阅
        RssTvItems += RssChecker().get_userrss_mediainfos()
        # 电视剧订阅去重
        Uniques = set()
        UniqueTvItems = []
        for item in RssTvItems:
            unique = f"{item.get('id')}_{item.get('season')}"
            if unique not in Uniques:
                Uniques.add(unique)
                UniqueTvItems.append(item)
        return {"code": 0, "result": UniqueTvItems}

    def get_ical_events(self):
        """
        获取ical日历事件
        """
        Events = []
        # 电影订阅
        RssMovieItems = self.get_movie_rss_items().get("result")
        for movie in RssMovieItems:
            info = self.__movie_calendar_data(movie)
            if info.get("id"):
                Events.append(info)

        # 电视剧订阅
        RssTvItems = self.get_tv_rss_items().get("result")
        for tv in RssTvItems:
            infos = self.__tv_calendar_data(tv).get("events")
            if infos and isinstance(infos, list):
                for info in infos:
                    if info.get("id"):
                        Events.append(info)

        return {"code": 0, "result": Events}

    @staticmethod
    def install_plugin(data, reload=True):
        """
        安装插件
        """
        module_id = data.get("id")
        if not module_id:
            return {"code": -1, "msg": "参数错误"}
        # 用户已安装插件列表
        user_plugins = SystemConfig().get(SystemConfigKey.UserInstalledPlugins) or []
        if module_id not in user_plugins:
            user_plugins.append(module_id)
            PluginHelper.install(module_id)
        # 保存配置
        SystemConfig().set(SystemConfigKey.UserInstalledPlugins, user_plugins)
        # 重新加载插件
        if reload:
            PluginManager().init_config()
        return {"code": 0, "msg": "插件安装成功"}

    @staticmethod
    def uninstall_plugin(data):
        """
        卸载插件
        """
        module_id = data.get("id")
        if not module_id:
            return {"code": -1, "msg": "参数错误"}
        # 用户已安装插件列表
        user_plugins = SystemConfig().get(SystemConfigKey.UserInstalledPlugins) or []
        if module_id in user_plugins:
            user_plugins.remove(module_id)
        # 保存配置
        SystemConfig().set(SystemConfigKey.UserInstalledPlugins, user_plugins)
        # 重新加载插件
        PluginManager().init_config()
        return {"code": 0, "msg": "插件卸载功"}

    @staticmethod
    def get_plugin_apps():
        """
        获取插件列表
        """
        plugins = PluginManager().get_plugin_apps(current_user.level)
        statistic = PluginHelper.statistic()
        return {"code": 0, "result": plugins, "statistic": statistic}

    @staticmethod
    def get_plugin_page(data):
        """
        查询插件的额外数据
        """
        plugin_id = data.get("id")
        if not plugin_id:
            return {"code": 1, "msg": "参数错误"}
        title, content, func = PluginManager().get_plugin_page(pid=plugin_id)
        return {"code": 0, "title": title, "content": content, "func": func}

    @staticmethod
    def get_plugin_state(data):
        """
        获取插件状态
        """
        plugin_id = data.get("id")
        if not plugin_id:
            return {"code": 1, "msg": "参数错误"}
        state = PluginManager().get_plugin_state(plugin_id)
        return {"code": 0, "state": state}

    @staticmethod
    def get_plugins_conf():
        Plugins = PluginManager().get_plugins_conf(current_user.level)
        return {"code": 0, "result": Plugins}

    @staticmethod
    def update_category_config(data):
        """
        保存二级分类配置
        """
        text = data.get("config") or ''
        # 保存配置
        category_path = Config().category_path
        if category_path:
            with open(category_path, "w", encoding="utf-8") as f:
                f.write(text)
        return {"code": 0, "msg": "保存成功"}

    @staticmethod
    def get_category_config(data):
        """
        获取二级分类配置
        """
        category_name = data.get("category_name")
        if not category_name:
            return {"code": 1, "msg": "请输入二级分类策略名称"}
        if category_name == "config":
            return {"code": 1, "msg": "非法二级分类策略名称"}
        category_path = os.path.join(Config().get_config_path(), f"{category_name}.yaml")
        if not os.path.exists(category_path):
            return {"code": 1, "msg": "请保存生成配置文件"}
        # 读取category配置文件数据
        with open(category_path, "r", encoding="utf-8") as f:
            category_text = f.read()
        return {"code": 0, "text": category_text}

    @staticmethod
    def backup(full_backup=False, bk_path=None):
        """
        @param full_backup  是否完整备份
        @param bk_path     自定义备份路径
        """
        try:
            # 创建备份文件夹
            config_path = Path(Config().get_config_path())
            backup_file = f"bk_{time.strftime('%Y%m%d%H%M%S')}"
            if bk_path:
                backup_path = Path(bk_path) / backup_file
            else:
                backup_path = config_path / "backup_file" / backup_file
            backup_path.mkdir(parents=True)
            # 把现有的相关文件进行copy备份
            shutil.copy(f'{config_path}/config.yaml', backup_path)
            shutil.copy(f'{config_path}/default-category.yaml', backup_path)
            shutil.copy(f'{config_path}/user.db', backup_path)

            # 完整备份不删除表
            if not full_backup:
                conn = sqlite3.connect(f'{backup_path}/user.db')
                cursor = conn.cursor()
                # 执行操作删除不需要备份的表
                table_list = [
                    'SEARCH_RESULT_INFO',
                    'RSS_TORRENTS',
                    'DOUBAN_MEDIAS',
                    'TRANSFER_HISTORY',
                    'TRANSFER_UNKNOWN',
                    'TRANSFER_BLACKLIST',
                    'SYNC_HISTORY',
                    'DOWNLOAD_HISTORY',
                    'alembic_version'
                ]
                for table in table_list:
                    cursor.execute(f"""DROP TABLE IF EXISTS {table};""")
                conn.commit()
                cursor.close()
                conn.close()
            zip_file = str(backup_path) + '.zip'
            if os.path.exists(zip_file):
                zip_file = str(backup_path) + '.zip'
            shutil.make_archive(str(backup_path), 'zip', str(backup_path))
            shutil.rmtree(str(backup_path))
            return zip_file
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            return None

    @staticmethod
    def get_system_processes():
        """
        获取系统进程
        """
        return {"code": 0, "data": SystemUtils.get_all_processes()}

    @staticmethod
    def run_plugin_method(data):
        """
        运行插件方法
        """
        plugin_id = data.get("plugin_id")
        method = data.get("method")
        if not plugin_id or not method:
            return {"code": 1, "msg": "参数错误"}
        data.pop("plugin_id")
        data.pop("method")
        result = PluginManager().run_plugin_method(pid=plugin_id, method=method, **data)
        return {"code": 0, "result": result}

    def get_commands(self):
        """
        获取命令列表
        """
        return [{
            "id": cid,
            "name": cmd.get("desc")
        } for cid, cmd in self._commands.items()] + [{
            "id": item.get("cmd"),
            "name": item.get("desc")
        } for item in PluginManager().get_plugin_commands()]
