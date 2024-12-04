import os.path
import re

import log
from app.downloader import Downloader
from app.helper import ProgressHelper
from app.helper.openai_helper import OpenAiHelper
from app.indexer import Indexer
from app.media import Media, DouBan
from app.message import Message
from app.searcher import Searcher
from app.sites import Sites
from app.subscribe import Subscribe
from app.utils import StringUtils, Torrent
from app.utils.types import SearchType, IndexerType, ProgressKey, RssType
from config import Config
from web.backend.web_utils import WebUtils

SEARCH_MEDIA_CACHE = {}
SEARCH_MEDIA_TYPE = {}
SELECT_TYPE = {}
PAGE_SIZE = 8

def search_medias_for_web(content, ident_flag=True, filters=None, tmdbid=None, media_type=None):
    """
    WEB资源搜索
    :param content: 关键字文本，可以包括 类型、标题、季、集、年份等信息，使用 空格分隔，也支持种子的命名格式
    :param ident_flag: 是否进行媒体信息识别
    :param filters: 其它过滤条件
    :param tmdbid: TMDBID或DB:豆瓣ID
    :param media_type: 媒体类型，配合tmdbid传入
    :return: 错误码，错误原因，成功时直接插入数据库
    """
    mtype, key_word, season_num, episode_num, year, content = StringUtils.get_keyword_from_string(content)
    if not key_word:
        log.info("【Web】%s 搜索关键字有误！" % content)
        return -1, "%s 未识别到搜索关键字！" % content
    # 类型
    if media_type:
        mtype = media_type
    # 开始进度
    _searcher = Searcher()
    _process = ProgressHelper()
    _media = Media()
    _process.start(ProgressKey.Search)
    # 识别媒体
    media_info = None
    if ident_flag:

        # 有TMDBID或豆瓣ID
        if tmdbid:
            media_info = WebUtils.get_mediainfo_from_id(mtype=mtype, mediaid=tmdbid)
        else:
            # 按输入名称查
            media_info = _media.get_media_info(mtype=media_type or mtype,
                                               title=content)

        # 整合集
        if media_info:
            if season_num:
                media_info.begin_season = int(season_num)
            if episode_num:
                media_info.begin_episode = int(episode_num)

        if media_info and media_info.tmdb_info:
            # 查询到TMDB信息
            log.info(f"【Web】从TMDB中匹配到{media_info.type.value}：{media_info.get_title_string()}")
            # 查找的季
            if media_info.begin_season is None:
                search_season = None
            else:
                search_season = media_info.get_season_list()
            # 查找的集
            search_episode = media_info.get_episode_list()
            if search_episode and not search_season:
                search_season = [1]
            # 中文名
            if media_info.cn_name:
                search_cn_name = media_info.cn_name
            else:
                search_cn_name = media_info.title
            # 英文名
            search_en_name = None
            if media_info.en_name:
                search_en_name = media_info.en_name
            else:
                if media_info.original_language == "en":
                    search_en_name = media_info.original_title
                else:
                    en_title = _media.get_tmdb_en_title(media_info)
                    if en_title:
                        search_en_name = en_title
            # 两次搜索名称
            second_search_name = None
            if Config().get_config("laboratory").get("search_en_title"):
                if search_en_name:
                    first_search_name = search_en_name
                    second_search_name = search_cn_name
                else:
                    first_search_name = search_cn_name
            else:
                first_search_name = search_cn_name
                if search_en_name:
                    second_search_name = search_en_name

            filter_args = {"season": search_season,
                           "episode": search_episode,
                           "year": media_info.year,
                           "type": media_info.type}
        else:
            # 查询不到数据，使用快速搜索
            log.info(f"【Web】{content} 未从TMDB匹配到媒体信息，将使用快速搜索...")
            ident_flag = False
            media_info = None
            first_search_name = key_word
            second_search_name = None
            filter_args = {
                "season": season_num,
                "episode": episode_num,
                "year": year
            }
    # 快速搜索
    else:
        first_search_name = key_word
        second_search_name = None
        filter_args = {
            "season": season_num,
            "episode": episode_num,
            "year": year
        }
    # 整合高级查询条件
    if filters:
        filter_args.update(filters)
    # 开始搜索
    log.info("【Web】开始搜索 %s ..." % content)
    media_list = _searcher.search_medias(key_word=first_search_name,
                                         filter_args=filter_args,
                                         match_media=media_info,
                                         in_from=SearchType.WEB)
    # 使用第二名称重新搜索
    if ident_flag \
            and len(media_list) == 0 \
            and second_search_name \
            and second_search_name != first_search_name:
        _process.start(ProgressKey.Search)
        _process.update(ptype=ProgressKey.Search,
                        text="%s 未搜索到资源,尝试通过 %s 重新搜索 ..." % (
                            first_search_name, second_search_name))
        log.info("【Searcher】%s 未搜索到资源,尝试通过 %s 重新搜索 ..." % (first_search_name, second_search_name))
        media_list = _searcher.search_medias(key_word=second_search_name,
                                             filter_args=filter_args,
                                             match_media=media_info,
                                             in_from=SearchType.WEB)
    # 清空缓存结果
    _searcher.delete_all_search_torrents()
    # 结束进度
    _process.end(ProgressKey.Search)
    if len(media_list) == 0:
        log.info("【Web】%s 未搜索到任何资源" % content)
        return 1, "%s 未搜索到任何资源" % content
    else:
        log.info("【Web】共搜索到 %s 个有效资源" % len(media_list))
        # 插入数据库
        media_list = sorted(media_list, key=lambda x: "%s%s%s" % (str(x.res_order).rjust(3, '0'),
                                                                  str(x.site_order).rjust(3, '0'),
                                                                  str(x.seeders).rjust(10, '0')), reverse=True)
        _searcher.insert_search_results(media_items=media_list,
                                        ident_flag=ident_flag,
                                        title=content)
        return 0, ""

def handle_invalid_input(input_str, in_from, user_id):
    Message().send_channel_msg(channel=in_from,
                               title="输入有误！",
                               user_id=user_id)
    log.warn("【Web】错误的输入值：%s" % input_str)

def handle_page_navigation(input_str, in_from, user_id):
    if input_str.lower() == "p" or input_str == "上一页":
        medias = SELECT_TYPE[user_id].get("filtered_list", []) or SEARCH_MEDIA_CACHE.get(user_id, [])
        if (SELECT_TYPE[user_id]["page"] - 1) * PAGE_SIZE >= 0:
            SELECT_TYPE[user_id]["page"] -= 1
            title = SELECT_TYPE[user_id]["title"].format(current_page=SELECT_TYPE[user_id]["page"] + 1)
            Message().send_channel_list_msg(channel=in_from,
                                            title=title,
                                            medias=medias,
                                            user_id=user_id,
                                            page=SELECT_TYPE[user_id]["page"],
                                            page_size=PAGE_SIZE)
        else:
            Message().send_channel_msg(channel=in_from,
                                        title="已经在首页了！",
                                        user_id=user_id)

    elif input_str == "n" or input_str == "下一页":
        medias = SELECT_TYPE[user_id].get("filtered_list", []) or SEARCH_MEDIA_CACHE.get(user_id, [])
        if (SELECT_TYPE[user_id]["page"] + 1) * PAGE_SIZE < len(medias):
            SELECT_TYPE[user_id]["page"] += 1
            title = SELECT_TYPE[user_id]["title"].format(current_page=SELECT_TYPE[user_id]["page"] + 1)
            Message().send_channel_list_msg(channel=in_from,
                                            title=title,
                                            medias=medias,
                                            user_id=user_id,
                                            page=SELECT_TYPE[user_id]["page"],
                                            page_size=PAGE_SIZE)
        else:
            Message().send_channel_msg(channel=in_from,
                                        title="已经在最后一页了！",
                                        user_id=user_id)

def handle_download(input_str, in_from, user_id, user_name):
    """
    处理用户的下载请求。
    """
    medias = SELECT_TYPE[user_id].get("filtered_list", []) or SEARCH_MEDIA_CACHE.get(user_id, [])
    if not medias:
        Message().send_channel_msg(
            channel=in_from,
            title="没有可下载的媒体",
            user_id=user_id
        )
        return
    if input_str == 0:
        # 批量下载
        download_items, left_medias = Downloader().batch_download(
            in_from=in_from,
            media_list=medias,
            need_tvs=SELECT_TYPE[user_id].get("no_exists", None),
            user_name=user_name
        )
        if not download_items:
            log.info("【Searcher】未下载到任何资源")
            Message().send_channel_msg(
                channel=in_from,
                title="【Searcher】未下载到任何资源",
                user_id=user_id
            )
        SELECT_TYPE[user_id] = {}
        return

    if in_from != SearchType.WEB:
        choose = PAGE_SIZE * SELECT_TYPE[user_id].get("page", 0) + input_str - 1
    else:
        choose = input_str - 1

    if 0 <= choose < len(medias):
        meta_info = medias[choose]
        Downloader().download(
            media_info=meta_info,
            in_from=in_from,
            user_name=user_name
        )
        SELECT_TYPE[user_id] = {}
    else:
        handle_invalid_input(input_str, in_from, user_id)

def process_filters(user_id, in_from):
    """
    处理过滤条件，根据用户输入的筛选条件进行过滤。
    """
    if SELECT_TYPE[user_id].get("filters"):
        SELECT_TYPE[user_id]["filter_flag"] = None
        # 提取筛选条件函数与描述
        descriptions, filters = zip(*SELECT_TYPE[user_id]["filters"])
        
        # 应用筛选器
        filtered_list = Torrent.filter_media_list(SEARCH_MEDIA_CACHE[user_id], list(filters))
        if not filtered_list:
            SELECT_TYPE[user_id]["filters"] = []
            Message().send_channel_msg(
                channel=in_from,
                title="没有筛选到种子信息，如需重新筛选，请重新发“f”或“筛选”。",
                user_id=user_id
            )
            return

        # 更新筛选结果并发送
        SELECT_TYPE[user_id]["filtered_list"] = filtered_list
        applied_filters = "\n".join(f"{i+1}. {desc}" for i, desc in enumerate(descriptions))
        title = f"应用了以下筛选条件：\n{applied_filters}\n\n"
        title += f"{SELECT_TYPE[user_id]['filtered_list'][0].title} 共筛选出 {len(filtered_list)} 个资源，请回复序号选择下载"

        if in_from != SearchType.WEB and len(filtered_list) > PAGE_SIZE:
            total_pages = (len(filtered_list) + PAGE_SIZE - 1) // PAGE_SIZE
            title += f"\n（当前第 {{current_page}} 页, 共 {total_pages} 页）\n"
            title += " 0: 自动选择\n p: 上一页\n n: 下一页\n f: 继续筛选\n q: 退出"
        else:
            title += "\n 0: 自动选择\n f: 继续筛选\n q: 退出"

        SELECT_TYPE[user_id]["page"] = 0
        SELECT_TYPE[user_id]["title"] = title
        Message().send_channel_list_msg(
            channel=in_from,
            title=title.format(current_page=1),
            medias=filtered_list,
            user_id=user_id,
            page=0,
            page_size=PAGE_SIZE
        )
    else:
        Message().send_channel_msg(channel=in_from, title="请添加有效的筛选条件", user_id=user_id)
        prompt_filter_options(in_from, user_id)

def handle_site_filter(input_str, user_id, in_from):
    """
    处理站点筛选。
    """
    if SELECT_TYPE[user_id].get("filter_flag") == 1:
        if str(input_str).lower() == "q":
            SELECT_TYPE[user_id]["filter_flag"] = "Select"
            prompt_filter_options(in_from, user_id)
            return

        filter_sites = []
        indexes = re.split(r"[,， ]", str(input_str).strip())
        for index in indexes:
            if index.isdigit() and int(index) in range(len(SELECT_TYPE[user_id]["sites"])):
                filter_sites.append(SELECT_TYPE[user_id]["sites"][int(index)])

        if filter_sites:
            description = "站点: " + ", ".join(filter_sites)
            SELECT_TYPE[user_id]["filters"].append((description, Torrent.is_specific_site(filter_sites)))
            SELECT_TYPE[user_id]["filter_flag"] = "Select"
            Message().send_channel_msg(channel=in_from, title=f"站点筛选已应用：{description}", user_id=user_id)
            prompt_filter_options(in_from, user_id)
        else:
            Message().send_channel_msg(channel=in_from, title="请选择有效的站点序号", user_id=user_id)
    else:
        SELECT_TYPE[user_id]["filter_flag"] = 1
        SELECT_TYPE[user_id]["sites"] = list(set(media.site for media in SEARCH_MEDIA_CACHE[user_id]))
        title = "请输入对应序号选择站点（多个站点请用“,”逗号或“ ”空格隔开）：\n"
        title += "\n".join(f" {index}. {site}" for index, site in enumerate(SELECT_TYPE[user_id]["sites"])) + "\n q. 返回"
        Message().send_channel_msg(channel=in_from, title=title, user_id=user_id)

def handle_promotion_filter(input_str, user_id, in_from):
    """
    处理促销优先级筛选。
    """
    if SELECT_TYPE[user_id].get("filter_flag") == 2:
        if str(input_str).lower() == "q":
            SELECT_TYPE[user_id]["filter_flag"] = "Select"
            prompt_filter_options(in_from, user_id)
            return

        if re.match(r"^\d+|<\d+|>\d+|\d+-\d+$", str(input_str).strip()):
            description = f"促销优先级: {input_str}"
            SELECT_TYPE[user_id]["filters"].append((description, Torrent.has_promotion_priority(str(input_str))))
            SELECT_TYPE[user_id]["filter_flag"] = "Select"
            Message().send_channel_msg(channel=in_from, title=f"促销优先级筛选已应用：{description}", user_id=user_id)
            prompt_filter_options(in_from, user_id)
        else:
            Message().send_channel_msg(channel=in_from, title="请输入有效的促销优先级序号", user_id=user_id)
    else:
        SELECT_TYPE[user_id]["filter_flag"] = 2
        promotion_priorities = sorted(set((int(media.get_promotion_priority()), media.get_promotion_string())
                                          for media in SEARCH_MEDIA_CACHE[user_id]))
        title = "请输入对应序号添加促销类型，多个类型可用“,”逗号或“ ”空格隔开，亦可“<3”、“>3”、“0-3”（数字越小优先级越高）：\n"
        title += "\n".join(f" {i[0]}. {i[1]}" for i in promotion_priorities) + "\n q. 返回"
        Message().send_channel_msg(channel=in_from, title=title, user_id=user_id)

def handle_season_episode_filter(input_str, user_id, in_from):
    """
    处理季和集筛选。
    """
    if SELECT_TYPE[user_id].get("filter_flag") == 3:
        if str(input_str).lower() == "q":
            SELECT_TYPE[user_id]["filter_flag"] = "Select"
            prompt_filter_options(in_from, user_id)
            return

        # 更新正则表达式以支持新的格式 S1-3, E1-30
        pattern = r"(S(\d+)-S?(\d+)|S(\d+))|(E(\d+)-E?(\d+)|E(\d+))"
        matches = re.findall(pattern, input_str, re.I)

        seasons = set()
        episodes = set()
        for match in matches:
            if match[1] and match[2]:  # S01-S03 或 S1-3
                seasons.update(list(range(int(match[1]), int(match[2]) + 1)))
            elif match[3]:  # S01 或 S1
                seasons.add(int(match[3]))
            if match[5] and match[6]:  # E1-E30 或 E1-30
                episodes.update(list(range(int(match[5]), int(match[6]) + 1)))
            elif match[7]:  # E1
                episodes.add(int(match[7]))

        if seasons or episodes:
            seasons = sorted(seasons)
            episodes = sorted(episodes)

            season_desc = ""
            episode_desc = ""

            if seasons:
                season_desc = f"S{seasons[0]:02d}-S{seasons[-1]:02d}" if len(seasons) > 1 else f"S{seasons[0]:02d}"
            if episodes:
                episode_desc = f"E{episodes[0]:02d}-E{episodes[-1]:02d}" if len(episodes) > 1 else f"E{episodes[0]:02d}"
                
            if season_desc and episode_desc:
                filter_desc = f"季: {season_desc}，集: {episode_desc}"
            elif season_desc:
                filter_desc = f"季: {season_desc}"
            elif episode_desc:
                filter_desc = f"集: {episode_desc}"

            SELECT_TYPE[user_id]["filters"].append((filter_desc, Torrent.filter_by_season_and_episode(seasons, episodes)))
            SELECT_TYPE[user_id]["filter_flag"] = "Select"
            Message().send_channel_msg(channel=in_from, title=f"筛选已应用：{filter_desc}", user_id=user_id)
            prompt_filter_options(in_from, user_id)
        else:
            Message().send_channel_msg(channel=in_from, title="请输入有效的季和集格式", user_id=user_id)
    else:
        SELECT_TYPE[user_id]["filter_flag"] = 3
        title = "请输入季和集（如：S01-S03 E1-E30, S1-3 E1-30, S01 E1,E2,E3）：\n q. 返回"
        Message().send_channel_msg(channel=in_from, title=title, user_id=user_id)

def remove_filter(input_str, user_id, in_from):
    """
    移除已添加的筛选条件。
    """
    # 检查是否存在筛选条件
    if not SELECT_TYPE[user_id].get("filters"):
        Message().send_channel_msg(channel=in_from, title="当前没有筛选条件", user_id=user_id)
        prompt_filter_options(in_from, user_id)
        return

    if SELECT_TYPE[user_id].get("filter_flag") == 'v':
        to_remove = []
        if str(input_str).lower() == "a":
            removed_conditions = [desc for desc, _ in SELECT_TYPE[user_id]["filters"]]
            SELECT_TYPE[user_id]["filters"] = []
            SELECT_TYPE[user_id]["filter_flag"] = "Select"
            removed_message = "、".join(removed_conditions)
            Message().send_channel_msg(
                channel=in_from, 
                title=f"已移除全部筛选条件：{removed_message}",
                user_id=user_id
            )
            prompt_filter_options(in_from, user_id)
        elif str(input_str).lower() == "q":
            SELECT_TYPE[user_id]["filter_flag"] = "Select"
            prompt_filter_options(in_from, user_id)
        else:
            indexes = re.split(r"[,， ]", str(input_str).strip())
            for index in indexes:
                if index.isdigit() and int(index) in range(len(SELECT_TYPE[user_id]["filters"])):
                    to_remove.append(int(index))
            if to_remove:
                to_remove = sorted(to_remove, reverse=True)  # 从后往前移除，避免索引混乱
                removed_conditions = [SELECT_TYPE[user_id]["filters"][idx][0] for idx in to_remove]
                for idx in to_remove:
                    SELECT_TYPE[user_id]["filters"].pop(idx)
                removed_message = "、".join(removed_conditions)
                Message().send_channel_msg(
                    channel=in_from,
                    title=f"已移除以下筛选条件：{removed_message}",
                    user_id=user_id
                )
                SELECT_TYPE[user_id]["filter_flag"] = "Select"
                prompt_filter_options(in_from, user_id)
            else:
                Message().send_channel_msg(channel=in_from, title="请输入有效的序号进行移除", user_id=user_id)
    else:
        SELECT_TYPE[user_id]["filter_flag"] = 'v'
        title = "已添加如下筛选条件，输入对应序号可移除条件（多个条件请用“,”逗号或“ ”空格隔开）：\n"
        title += "\n".join(f" {index}. {filter_desc}" for index, (filter_desc, _) in enumerate(SELECT_TYPE[user_id]["filters"]))
        title += "\n a. 清空所有条件\n" + " q. 返回"
        Message().send_channel_msg(channel=in_from, title=title, user_id=user_id)

def exit_filter(user_id, in_from):
    """
    退出筛选。
    """
    SELECT_TYPE[user_id]["filter_flag"] = None
    SELECT_TYPE[user_id]["filters"] = []
    SELECT_TYPE[user_id]["filtered_list"] = []
    SELECT_TYPE[user_id]["page"] = 0
    SELECT_TYPE[user_id]["title"] = SELECT_TYPE[user_id].get("title2",SELECT_TYPE[user_id].get("title"))
    Message().send_channel_msg(channel=in_from,
                                title="已退出筛选，可以继需选择需下载的资源。",
                                user_id=user_id)
    title = SELECT_TYPE[user_id]["title"].format(current_page=SELECT_TYPE[user_id]["page"]+1)
    Message().send_channel_list_msg(channel=in_from,
                                    title=title,
                                    medias=SEARCH_MEDIA_CACHE[user_id],
                                    user_id=user_id,
                                    page=SELECT_TYPE[user_id]["page"],
                                    page_size=PAGE_SIZE)

def prompt_filter_options(in_from, user_id):
    """
    提示用户选择筛选操作。
    """
    SELECT_TYPE[user_id]["filter_flag"] = "Select"
    if not SELECT_TYPE[user_id].get("filters"):
        SELECT_TYPE[user_id]["filters"] = []
    Message().send_channel_msg(channel=in_from,
                            title="请输入对应序号添加筛选：\n"
                                    " 0. 开始筛选\n"
                                    " 1. 筛选站点\n"
                                    " 2. 筛选促销\n"
                                    " 3. 筛选季和集\n"
                                    " v. 查看或移除筛选\n"
                                    " q. 退出并清空筛选",
                            user_id=user_id)

def handle_filter(input_str, in_from, user_id):

    filter_flag = SELECT_TYPE[user_id].get("filter_flag")

    if input_str.isdigit():
        input_str = int(input_str)
    else:
        input_str = input_str.lower()

    if filter_flag == "Select":
        filter_flag = input_str

    if filter_flag == 0:  # 开始筛选
        process_filters(user_id, in_from)
    elif filter_flag == 1:  # 站点筛选
        handle_site_filter(input_str, user_id, in_from)
    elif filter_flag == 2:  # 促销优先级筛选
        handle_promotion_filter(input_str, user_id, in_from)
    elif filter_flag == 3:  # 季和集筛选
        handle_season_episode_filter(input_str, user_id, in_from)
    elif filter_flag == 'v':  # 查看或移除筛选
        remove_filter(input_str, user_id, in_from)
    elif filter_flag == 'q':  # 退出筛选
        exit_filter(user_id, in_from)
    else:
        prompt_filter_options(in_from, user_id) # 默认情况，提示用户选择筛选选项

def search_media_by_message(input_str, in_from: SearchType, user_id, user_name=None):
    """
    输入字符串，解析要求并进行资源搜索
    :param input_str: 输入字符串，可以包括标题、年份、季、集的信息，使用空格隔开
    :param in_from: 搜索下载的请求来源
    :param user_id: 需要发送消息的，传入该参数，则只给对应用户发送交互消息
    :param user_name: 用户名称
    :return: 请求的资源是否全部下载完整、请求的文本对应识别出来的媒体信息、请求的资源如果是剧集，则返回下载后仍然缺失的季集信息
    """
    if not input_str:
        log.info("【Searcher】搜索关键字有误！")
        return
    else:
        input_str = str(input_str).strip()
    if SELECT_TYPE.get(user_id):
        # 如果是数字，表示选择项
        if input_str.isdigit() and SELECT_TYPE[user_id]["type"] == "search":
            # Handle search type input
            choose = PAGE_SIZE * SELECT_TYPE[user_id]["page"] + int(input_str) - 1
            if not SEARCH_MEDIA_CACHE.get(user_id) or \
                    choose < 0 or choose >= len(SEARCH_MEDIA_CACHE.get(user_id)):
                handle_invalid_input(input_str, in_from, user_id)
                return
            media_info = SEARCH_MEDIA_CACHE[user_id][choose]
            if not SEARCH_MEDIA_TYPE.get(user_id) or SEARCH_MEDIA_TYPE.get(user_id) == "SEARCH":
                # Search for additional media info
                __search_media(in_from=in_from, media_info=media_info, user_id=user_id, user_name=user_name)
            else:
                # Subscription
                __rss_media(in_from=in_from, media_info=media_info, user_id=user_id, user_name=user_name)

        elif SELECT_TYPE[user_id]["type"]=="download" and (input_str.lower() in ["f", "筛选", "过滤"] or SELECT_TYPE[user_id].get("filter_flag")):
            # Handle filter input
            handle_filter(input_str, in_from, user_id)
            
        elif input_str.isdigit() and SELECT_TYPE[user_id]["type"] == "download":
            # Handle download type input
            handle_download(int(input_str), in_from, user_id, user_name)
        
        elif in_from != SearchType.WEB and input_str.lower() in ["p", "上一页", "n", "下一页"]:
            # Handle page navigation input
            handle_page_navigation(input_str, in_from, user_id)
        
        elif input_str=="q" or input_str=="退出":
            SELECT_TYPE[user_id] = {}
            Message().send_channel_msg(channel=in_from,
                                        title="已退出选择",
                                        user_id=user_id)
        else:
            handle_invalid_input(input_str, in_from, user_id)
    # 接收到文本
    else:
        SELECT_TYPE[user_id] = {}
        if input_str.startswith("订阅"):
            # 订阅
            SEARCH_MEDIA_TYPE[user_id] = "SUBSCRIBE"
            input_str = re.sub(r"订阅[:：\s]*", "", input_str)
        elif input_str.startswith("http"):
            # 下载链接
            SEARCH_MEDIA_TYPE[user_id] = "DOWNLOAD"
        elif OpenAiHelper().get_state() \
                and not input_str.startswith("搜索") \
                and not input_str.startswith("下载"):
            # 开启ChatGPT时，不以订阅、搜索、下载开头的均为聊天模式
            SEARCH_MEDIA_TYPE[user_id] = "ASK"
        else:
            # 搜索
            input_str = re.sub(r"(搜索|下载)[:：\s]*", "", input_str)
            SEARCH_MEDIA_TYPE[user_id] = "SEARCH"

        # 下载链接
        if SEARCH_MEDIA_TYPE[user_id] == "DOWNLOAD":
            # 检查是不是有这个站点
            site_info = Sites().get_sites(siteurl=input_str)
            # 偿试下载种子文件
            filepath, content, retmsg = Torrent().save_torrent_file(
                url=input_str,
                cookie=site_info.get("cookie"),
                ua=site_info.get("ua"),
                proxy=site_info.get("proxy")
            )
            # 下载种子出错
            if (not content or not filepath) and retmsg:
                Message().send_channel_msg(channel=in_from,
                                           title=retmsg,
                                           user_id=user_id)
                return
            # 识别文件名
            filename = os.path.basename(filepath)
            # 识别
            meta_info = Media().get_media_info(title=filename)
            if not meta_info:
                Message().send_channel_msg(channel=in_from,
                                           title="无法识别种子文件名！",
                                           user_id=user_id)
                return
            # 开始下载
            meta_info.set_torrent_info(enclosure=input_str)
            Downloader().download(media_info=meta_info,
                                  torrent_file=filepath,
                                  in_from=in_from,
                                  user_name=user_name)
        # 聊天
        elif SEARCH_MEDIA_TYPE[user_id] == "ASK":
            # 调用ChatGPT Api
            answer = OpenAiHelper().get_answer(text=input_str,
                                               userid=user_id)
            if not answer:
                answer = "ChatGTP出错了，请检查OpenAI API Key是否正确，如需搜索电影/电视剧，请发送 搜索或下载 + 名称"
            # 发送消息
            Message().send_channel_msg(channel=in_from,
                                       title="",
                                       text=str(answer).strip(),
                                       user_id=user_id)
        # 搜索或订阅
        else:
            # 获取字符串中可能的RSS站点列表
            rss_sites, content = StringUtils.get_idlist_from_string(input_str,
                                                                    [{
                                                                        "id": site.get("name"),
                                                                        "name": site.get("name")
                                                                    } for site in Sites().get_sites(rss=True)])

            # 索引器类型
            indexer_type = Indexer().get_client_type()
            indexers = Indexer().get_indexers()

            # 获取字符串中可能的搜索站点列表
            if indexer_type == IndexerType.BUILTIN:
                content = input_str
                search_sites, _ = StringUtils.get_idlist_from_string(input_str, [{
                    "id": indexer.name,
                    "name": indexer.name
                } for indexer in indexers])
            else:
                search_sites, content = StringUtils.get_idlist_from_string(content, [{
                    "id": indexer.name,
                    "name": indexer.name
                } for indexer in indexers])

            # 获取字符串中可能的下载设置
            download_setting, content = StringUtils.get_idlist_from_string(content, [{
                "id": dl.get("id"),
                "name": dl.get("name")
            } for dl in Downloader().get_download_setting().values()])
            if download_setting:
                download_setting = download_setting[0]

            # 识别媒体信息，列出匹配到的所有媒体
            log.info("【Web】正在识别 %s 的媒体信息..." % content)
            if not content:
                Message().send_channel_msg(channel=in_from,
                                           title="无法识别搜索内容！",
                                           user_id=user_id)
                return

            # 搜索名称
            medias = WebUtils.search_media_infos(
                keyword=content
            )
            if not medias:
                # 查询不到媒体信息
                Message().send_channel_msg(channel=in_from,
                                           title="%s 查询不到媒体信息！" % content,
                                           user_id=user_id)
                return

            # 保存识别信息到临时结果中，由于消息长度限制只取前8条
            SEARCH_MEDIA_CACHE[user_id] = []
            for meta_info in medias[:8]:
                # 合并站点和下载设置信息
                meta_info.rss_sites = rss_sites
                meta_info.search_sites = search_sites
                meta_info.set_download_info(download_setting=download_setting)
                SEARCH_MEDIA_CACHE[user_id].append(meta_info)

            if 1 == len(SEARCH_MEDIA_CACHE[user_id]):
                # 只有一条数据，直接开始搜索
                media_info = SEARCH_MEDIA_CACHE[user_id][0]
                if not SEARCH_MEDIA_TYPE.get(user_id) \
                        or SEARCH_MEDIA_TYPE.get(user_id) == "SEARCH":
                    # 如果是豆瓣数据，需要重新查询TMDB的数据
                    if media_info.douban_id:
                        _title = media_info.get_title_string()
                        media_info = Media().get_media_info(title="%s %s" % (media_info.title, media_info.year),
                                                            mtype=media_info.type, strict=True)
                        if not media_info or not media_info.tmdb_info:
                            Message().send_channel_msg(channel=in_from,
                                                       title="%s 从TMDB查询不到媒体信息！" % _title,
                                                       user_id=user_id)
                            return
                    # 发送消息
                    Message().send_channel_msg(channel=in_from,
                                               title=media_info.get_title_vote_string(),
                                               text=media_info.get_overview_string(),
                                               image=media_info.get_message_image(),
                                               url=media_info.get_detail_url(),
                                               user_id=user_id)
                    # 开始搜索
                    __search_media(in_from=in_from,
                                   media_info=media_info,
                                   user_id=user_id,
                                   user_name=user_name)
                else:
                    # 添加订阅
                    __rss_media(in_from=in_from,
                                media_info=media_info,
                                user_id=user_id,
                                user_name=user_name)
            else:
                title = "共找到 {total_items} 条相关信息，请回复序号选择搜索".format(
                    total_items=len(SEARCH_MEDIA_CACHE[user_id])
                )
                if in_from != SearchType.WEB and len(SEARCH_MEDIA_CACHE[user_id]) > PAGE_SIZE:
                    total_pages = (len(SEARCH_MEDIA_CACHE[user_id]) + PAGE_SIZE - 1) // PAGE_SIZE
                    title += "\n（当前第 {current_page} 页, 共 {total_pages} 页；p: 上一页 n: 下一页）"
                    title = title.format(current_page="{current_page}", total_pages=total_pages)
                SELECT_TYPE[user_id]={"type":"search", "page":0, "title":title}
                # 发送消息通知选择
                Message().send_channel_list_msg(channel=in_from,
                                                title=title.format(current_page=SELECT_TYPE[user_id]["page"]+1),
                                                medias=SEARCH_MEDIA_CACHE[user_id],
                                                user_id=user_id,
                                                page=SELECT_TYPE[user_id]["page"],
                                                page_size=PAGE_SIZE)


def __search_media(in_from, media_info, user_id, user_name=None):
    """
    开始搜索和发送消息
    """
    # 检查是否存在，电视剧返回不存在的集清单
    exist_flag, no_exists, messages = Downloader().check_exists_medias(meta_info=media_info)
    if messages:
        Message().send_channel_msg(channel=in_from,
                                   title="\n".join(messages),
                                   user_id=user_id)
    # 已经存在
    if exist_flag:
        return

    # 开始搜索
    Message().send_channel_msg(channel=in_from,
                               title="开始搜索 %s ..." % media_info.title,
                               user_id=user_id)
    search_result, no_exists, search_count, download_count, media_list = Searcher().search_one_media(media_info=media_info,
                                                                                         in_from=in_from,
                                                                                         no_exists=no_exists,
                                                                                         sites=media_info.search_sites,
                                                                                         user_name=user_name)
    # 没有搜索到数据
    if not search_count:
        Message().send_channel_msg(channel=in_from,
                                   title="%s 未搜索到任何资源" % media_info.title,
                                   user_id=user_id)
    else:
        # 搜索到了但是没开自动下载
        if download_count is None:
            title = "{media_title} 共找到 {search_count} 个资源，请回复序号选择下载".format(
                media_title=media_info.title,
                search_count=search_count
            )
            pt = Config().get_config('pt')
            if pt:
                download_order = pt.get("download_order")
            media_list = Torrent.sort_media_list(media_list, download_order)
            SEARCH_MEDIA_CACHE[user_id] = media_list
            if in_from != SearchType.WEB and len(SEARCH_MEDIA_CACHE[user_id]) > PAGE_SIZE:
                total_pages = (len(SEARCH_MEDIA_CACHE[user_id]) + PAGE_SIZE - 1) // PAGE_SIZE
                title += "\n（当前第 {current_page} 页, 共 {total_pages} 页）\n 0: 自动选择\n p: 上一页\n n: 下一页\n f: 筛选\n q: 退出"
                title = title.format(current_page="{current_page}", total_pages=total_pages)
            else:
                title += "\n 0: 自动选择\n f: 筛选\n q: 退出"
            SELECT_TYPE[user_id]={"type":"download", "page":0, "title":title, "title2":title, "no_exists":no_exists}
            Message().send_channel_list_msg(channel=in_from,
                                            title=title.format(current_page=SELECT_TYPE[user_id]["page"]+1),
                                            medias=SEARCH_MEDIA_CACHE[user_id],
                                            user_id=user_id,
                                            page=SELECT_TYPE[user_id]["page"],
                                            page_size=PAGE_SIZE)
            return
        else:
            # 搜索到了但是没下载到数据
            if download_count == 0:
                Message().send_channel_msg(channel=in_from,
                                           title="%s 共搜索到 %s 个结果，但没有下载到任何资源" % (
                                               media_info.title, search_count),
                                           user_id=user_id)
    # 没有下载完成，且打开了自动添加订阅
    if not search_result and Config().get_config('pt').get('search_no_result_rss'):
        # 添加订阅
        __rss_media(in_from=in_from,
                    media_info=media_info,
                    user_id=user_id,
                    state='R',
                    user_name=user_name)


def __rss_media(in_from, media_info, user_id=None, state='D', user_name=None):
    """
    开始添加订阅和发送消息
    """
    # 添加订阅
    mediaid = f"DB:{media_info.douban_id}" if media_info.douban_id else media_info.tmdb_id
    code, msg, media_info = Subscribe().add_rss_subscribe(mtype=media_info.type,
                                                          name=media_info.title,
                                                          year=media_info.year,
                                                          channel=RssType.Auto,
                                                          season=media_info.begin_season,
                                                          mediaid=mediaid,
                                                          state=state,
                                                          rss_sites=media_info.rss_sites,
                                                          search_sites=media_info.search_sites,
                                                          download_setting=media_info.download_setting,
                                                          in_from=in_from,
                                                          user_name=user_name)
    if code == 0:
        log.info("【Web】%s %s 已添加订阅" % (media_info.type.value, media_info.get_title_string()))
    else:
        if in_from in Message().get_search_types():
            log.info("【Web】%s 添加订阅失败：%s" % (media_info.title, msg))
            Message().send_channel_msg(channel=in_from,
                                       title="%s 添加订阅失败：%s" % (media_info.title, msg),
                                       user_id=user_id)
