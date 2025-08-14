import hashlib
import json
import random
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List, Optional

import log
from app.mediaserver.client._base import _IMediaClient
from app.utils import RequestUtils
from app.utils.types import MediaServerType, MediaType
from config import Config


@dataclass
class FeiNiuUser:
    """飞牛影视用户信息"""
    guid: str
    username: str
    is_admin: int = 0


class FeiNiuCategory(Enum):
    """飞牛影视媒体库分类"""
    MOVIE = "Movie"
    TV = "TV"
    MIX = "Mix"
    OTHERS = "Others"

    @classmethod
    def _missing_(cls, value):
        return cls.OTHERS


class FeiNiuType(Enum):
    """飞牛影视媒体类型"""
    MOVIE = "Movie"
    TV = "TV"
    SEASON = "Season"
    EPISODE = "Episode"
    VIDEO = "Video"
    DIRECTORY = "Directory"

    @classmethod
    def _missing_(cls, value):
        return cls.VIDEO


@dataclass
class FeiNiuMediaDb:
    """飞牛影视媒体库信息"""
    guid: str
    category: FeiNiuCategory
    name: Optional[str] = None
    posters: Optional[list[str]] = None
    dir_list: Optional[list[str]] = None


@dataclass
class FeiNiuMediaDbSummary:
    """飞牛影视媒体库统计信息"""
    favorite: int = 0
    movie: int = 0
    tv: int = 0
    video: int = 0
    total: int = 0


@dataclass
class FeiNiuVersion:
    """飞牛影视版本信息"""
    frontend: Optional[str] = None
    backend: Optional[str] = None


@dataclass
class FeiNiuItem:
    """飞牛影视媒体项目"""
    guid: str
    ancestor_guid: str = ""
    type: Optional[FeiNiuType] = None
    tv_title: Optional[str] = None
    parent_title: Optional[str] = None
    title: Optional[str] = None
    original_title: Optional[str] = None
    overview: Optional[str] = None
    poster: Optional[str] = None
    backdrops: Optional[str] = None
    posters: Optional[str] = None
    douban_id: Optional[int] = None
    imdb_id: Optional[str] = None
    trim_id: Optional[str] = None
    release_date: Optional[str] = None
    air_date: Optional[str] = None
    vote_average: Optional[str] = None
    season_number: Optional[int] = None
    episode_number: Optional[int] = None
    duration: Optional[int] = None  # 片长(秒)
    ts: Optional[int] = None  # 已播放(秒)
    watched: Optional[int] = None  # 1:已看完

    @property
    def tmdb_id(self) -> Optional[int]:
        """获取TMDB ID"""
        if self.trim_id is None:
            return None
        if self.trim_id.startswith("tt") or self.trim_id.startswith("tm"):
            # 飞牛给tmdbid加了前缀用以区分tv或movie
            return int(self.trim_id[2:])
        return None


class FeiNiu(_IMediaClient):
    """飞牛影视媒体服务器客户端"""
    
    # 媒体服务器ID
    client_id = "feiniu"
    # 媒体服务器类型
    client_type = MediaServerType.FEINIU
    # 媒体服务器名称
    client_name = MediaServerType.FEINIU.value

    # 私有属性
    _client_config = {}
    _host = None
    _play_host = None
    _username = None
    _password = None
    _apikey = "16CCEB3D-AB42-077D-36A1-F355324E4237"
    _api_path = "/api/v1"
    _token = None
    _userinfo = None
    _libraries = {}
    _sync_libraries = []
    _version = None

    def __init__(self, config=None):
        if config:
            self._client_config = config
        else:
            self._client_config = Config().get_config('feiniu')
        self.init_config()

    def init_config(self):
        """初始化配置"""
        if self._client_config:
            self._host = self._client_config.get('host')
            if self._host:
                self._host = self.__standardize_url(self._host)
                # 如果地址不以/v结尾，尝试添加/v
                if not self._host.endswith("/v"):
                    # 先尝试带/v的地址
                    test_host = self._host.rstrip("/") + "/v"
                    if self.__test_connection(test_host):
                        self._host = test_host
                        log.debug(f"【{self.client_name}】使用地址：{self._host}")
                    elif self.__test_connection(self._host):
                        log.debug(f"【{self.client_name}】使用地址：{self._host}")
                    else:
                        # 如果都无法连接，仍然保存配置，在reconnect时再尝试
                        log.warn(f"【{self.client_name}】服务器地址暂时无法访问：{self._host}，将在连接时重试")

            self._play_host = self._client_config.get('play_host')
            if self._play_host:
                self._play_host = self.__standardize_url(self._play_host)
            else:
                self._play_host = self._host

            self._username = self._client_config.get('username')
            self._password = self._client_config.get('password')
            self._sync_libraries = self._client_config.get('sync_libraries') or []

            # 不在初始化时自动连接，避免阻塞启动过程
            # 连接将在第一次使用时进行

    @staticmethod
    def __standardize_url(url: str) -> str:
        """标准化URL格式"""
        if not url:
            return ""
        if not url.startswith('http'):
            url = "http://" + url
        return url.rstrip("/")

    def __test_connection(self, host: str) -> bool:
        """测试连接"""
        try:
            req_url = f"{host}{self._api_path}/sys/version"
            headers = {
                "User-Agent": "NAS-Tools",
                "authx": self.__get_authx("/sys/version", None)
            }
            request_utils = RequestUtils(headers=headers)
            res = request_utils.get_res(req_url)
            return res is not None and res.status_code == 200
        except Exception:
            return False

    @classmethod
    def match(cls, ctype):
        """匹配客户端类型"""
        return True if ctype in [cls.client_id, cls.client_type, cls.client_name] else False

    def get_type(self):
        """获取媒体服务器类型"""
        return self.client_type

    def get_status(self):
        """测试连通性"""
        if not self.is_configured():
            return False

        # 如果已经认证，直接返回True
        if self.is_authenticated():
            return True

        # 如果未认证，尝试连接
        try:
            return self.reconnect()
        except Exception as e:
            log.error(f"【{self.client_name}】连接测试失败：{str(e)}")
            return False

    def is_configured(self) -> bool:
        """检查是否已配置"""
        return self._host is not None and self._username is not None and self._password is not None

    def is_authenticated(self) -> bool:
        """检查是否已认证"""
        return self.is_configured() and self._token is not None

    def is_inactive(self) -> bool:
        """判断是否需要重连"""
        if not self.is_authenticated():
            return True
        self._userinfo = self.__get_user_info()
        return self._userinfo is None

    def reconnect(self):
        """重连飞牛影视"""
        if not self.is_configured():
            return False

        # 如果当前host无法访问，尝试不同的URL格式
        if not self.__test_connection(self._host):
            original_host = self._client_config.get('host', '')
            if original_host:
                # 尝试不同的URL格式
                test_urls = [
                    self.__standardize_url(original_host),
                    self.__standardize_url(original_host).rstrip('/') + '/v',
                ]

                for test_url in test_urls:
                    if self.__test_connection(test_url):
                        self._host = test_url
                        log.info(f"【{self.client_name}】找到可用地址：{self._host}")
                        break
                else:
                    log.error(f"【{self.client_name}】所有地址都无法访问")
                    return False

        # 获取版本信息
        version_info = self.__get_version()
        if not version_info:
            log.error(f"【{self.client_name}】无法获取版本信息")
            return False
        self._version = version_info
        log.debug(f"【{self.client_name}】版本号:{version_info.frontend}, 服务版本:{version_info.backend}")

        # 登录
        if not self.__login():
            log.error(f"【{self.client_name}】登录失败")
            return False

        # 获取用户信息
        self._userinfo = self.__get_user_info()
        if not self._userinfo:
            log.error(f"【{self.client_name}】获取用户信息失败")
            return False

        log.info(f"【{self.client_name}】{self._username} 成功登录飞牛影视")

        # 刷新媒体库列表
        self.__refresh_libraries()
        return True

    def disconnect(self):
        """断开连接"""
        if self.is_authenticated():
            self.__logout()
            self._token = None
            self._userinfo = None
            log.debug(f"【{self.client_name}】{self._username} 已断开飞牛影视")

    def __get_authx(self, api_path: str, body: Optional[str]) -> str:
        """计算消息签名"""
        if not api_path.startswith("/v"):
            api_path = "/v" + api_path
        nonce = str(random.randint(100000, 999999))
        ts = str(int(time.time() * 1000))
        md5 = hashlib.md5()
        md5.update((body or "").encode())
        data_hash = md5.hexdigest()
        md5 = hashlib.md5()
        md5.update(
            "_".join([
                "NDzZTVxnRKP8Z0jXg1VAMonaG8akvh",
                api_path,
                nonce,
                ts,
                data_hash,
                self._apikey,
            ]).encode()
        )
        sign = md5.hexdigest()
        return f"nonce={nonce}&timestamp={ts}&sign={sign}"

    def __request_api(self, api: str, method: Optional[str] = None, params: Optional[dict] = None,
                     data: Optional[dict] = None, suppress_log=False):
        """请求飞牛影视API"""
        if not self._host or not api:
            return None

        if not api.startswith("/"):
            api_path = f"{self._api_path}/{api}"
        else:
            api_path = self._api_path + api
        url = self._host + api_path

        if method is None:
            method = "get" if data is None else "post"

        if method != "get":
            json_body = json.dumps(data, allow_nan=False) if data else ""
        else:
            json_body = None

        if params:
            queries_unquoted = "&".join([f"{k}={v}" for k, v in params.items()])
        else:
            queries_unquoted = None

        # 构建headers
        headers = {
            "User-Agent": "NAS-Tools",
            "authx": self.__get_authx(api_path, json_body or queries_unquoted),
        }

        if self._token:
            headers["Authorization"] = self._token

        if json_body is not None:
            headers["Content-Type"] = "application/json"

        try:
            # 使用RequestUtils，需要在初始化时传入headers
            request_utils = RequestUtils(headers=headers)

            if method.lower() == "get":
                res = request_utils.get_res(url, params=params)
            else:
                res = request_utils.post_res(url, data=json_body)

            if res and res.status_code == 200:
                resp = res.json()
                code = int(resp.get("code", -1))
                msg = resp.get("msg")
                if code != 0:
                    if not suppress_log:
                        log.error(f"【{self.client_name}】请求接口 {url} 失败，错误码：{code} {msg}")
                    return None
                return resp.get("data")
            elif not suppress_log:
                log.error(f"【{self.client_name}】请求接口 {url} 失败，状态码：{res.status_code if res else 'None'}")
        except Exception as e:
            if not suppress_log:
                log.error(f"【{self.client_name}】请求接口 {url} 异常：{str(e)}")
        return None

    def __get_version(self) -> Optional[FeiNiuVersion]:
        """获取飞牛影视版本号"""
        data = self.__request_api("/sys/version")
        if data:
            return FeiNiuVersion(
                frontend=data.get("version"),
                backend=data.get("mediasrvVersion"),
            )
        return None

    def __login(self) -> bool:
        """登录飞牛影视"""
        data = self.__request_api("/login", data={
            "username": self._username,
            "password": self._password,
            "app_name": "nas-tools",
        })
        if data:
            self._token = data.get("token")
            return self._token is not None
        return False

    def __logout(self) -> bool:
        """退出账号"""
        data = self.__request_api("/user/logout", method="post")
        return data is not None

    def __get_user_info(self) -> Optional[FeiNiuUser]:
        """获取当前用户信息"""
        data = self.__request_api("/user/info")
        if data:
            return FeiNiuUser(
                guid=data.get("guid", ""),
                username=data.get("username", ""),
                is_admin=data.get("is_admin", 0)
            )
        return None

    def __refresh_libraries(self):
        """刷新媒体库列表"""
        if not self.is_authenticated():
            return

        if self._userinfo.is_admin == 1:
            mdb_list = self.__get_mdb_list() or []
        else:
            mdb_list = self.__get_mediadb_list() or []

        self._libraries = {lib.guid: lib for lib in mdb_list}

    def __get_mediadb_list(self) -> Optional[List[FeiNiuMediaDb]]:
        """获取媒体库列表(普通用户)"""
        data = self.__request_api("/mediadb/list")
        if data:
            items = []
            for info in data:
                mdb = FeiNiuMediaDb(
                    guid=info.get("guid"),
                    category=FeiNiuCategory(info.get("category")),
                    name=info.get("title", ""),
                    posters=[
                        self.__build_img_api_url(poster)
                        for poster in info.get("posters", [])
                    ],
                )
                items.append(mdb)
            return items
        return None

    def __get_mdb_list(self) -> Optional[List[FeiNiuMediaDb]]:
        """获取媒体库列表(管理员)"""
        data = self.__request_api("/mdb/list")
        if data:
            items = []
            for info in data:
                mdb = FeiNiuMediaDb(
                    guid=info.get("guid"),
                    category=FeiNiuCategory(info.get("category")),
                    name=info.get("name", ""),
                    posters=[
                        self.__build_img_api_url(poster)
                        for poster in info.get("posters", [])
                    ],
                    dir_list=info.get("dir_list"),
                )
                items.append(mdb)
            return items
        return None

    def __build_img_api_url(self, img_path: Optional[str]) -> Optional[str]:
        """构建图片API URL"""
        if not img_path:
            return None
        if img_path[0] != "/":
            img_path = "/" + img_path
        return f"{self._api_path}/sys/img{img_path}"

    def __build_item(self, info: dict) -> FeiNiuItem:
        """构造媒体Item"""
        item = FeiNiuItem(guid=info.get("guid", ""))
        item.__dict__.update(info)
        item.type = FeiNiuType(info.get("type"))
        # Item详情接口才有posters和backdrops
        item.posters = self.__build_img_api_url(item.posters)
        item.backdrops = self.__build_img_api_url(item.backdrops)
        item.poster = (
            self.__build_img_api_url(item.poster) if item.poster else item.posters
        )
        return item

    # 实现基类的抽象方法
    def get_user_count(self):
        """获取用户数量(非管理员不能调用)"""
        if not self.is_authenticated():
            return 0
        if not self._userinfo or self._userinfo.is_admin != 1:
            return 0
        data = self.__request_api("/manager/user/list")
        return len(data) if data else 0

    def get_activity_log(self, num):
        """获取活动记录"""
        # 飞牛影视暂不支持活动记录
        return []

    def get_medias_count(self):
        """获取媒体数量"""
        if not self.is_authenticated():
            # 尝试连接
            if not self.get_status():
                return {"MovieCount": 0, "SeriesCount": 0, "SongCount": 0}

        data = self.__request_api("/mediadb/sum")
        if data:
            return {
                "MovieCount": data.get("movie", 0),
                "SeriesCount": data.get("tv", 0),
                "SongCount": 0  # 飞牛影视不支持音乐
            }
        return {"MovieCount": 0, "SeriesCount": 0, "SongCount": 0}

    def get_movies(self, title, year=None):
        """根据标题和年份，检查电影是否存在"""
        if not self.is_authenticated():
            return []

        movies = []
        data = self.__request_api("/search/list", params={"q": title})
        if data:
            for info in data:
                item = self.__build_item(info)
                if item.type != FeiNiuType.MOVIE:
                    continue
                if title in [item.title, item.original_title]:
                    if not year or (item.release_date and item.release_date[:4] == year):
                        movies.append({
                            "id": item.guid,
                            "title": item.title,
                            "year": item.release_date[:4] if item.release_date else None,
                            "type": "Movie",
                            "overview": item.overview,
                            "tmdbid": item.tmdb_id,
                            "imdbid": item.imdb_id
                        })
        return movies

    def get_tv_episodes(self, item_id=None, title=None, year=None, tmdbid=None, season=None):
        """根据标题、年份、季查询电视剧所有集信息"""
        if not self.is_authenticated():
            return []

        if not item_id:
            # 通过搜索获取item_id
            data = self.__request_api("/search/list", params={"q": title})
            if data:
                for info in data:
                    item = self.__build_item(info)
                    if item.type != FeiNiuType.TV:
                        continue
                    if title in [item.title, item.original_title]:
                        if not year or (item.air_date and item.air_date[:4] == year):
                            item_id = item.guid
                            break
            if not item_id:
                return []

        # 获取季列表
        seasons_data = self.__request_api(f"/season/list/{item_id}")
        if not seasons_data:
            return []

        episodes = []
        for season_info in seasons_data:
            season_item = self.__build_item(season_info)
            if season is not None and season_item.season_number != season:
                continue

            # 获取集列表
            episodes_data = self.__request_api(f"/episode/list/{season_item.guid}")
            if episodes_data:
                for episode_info in episodes_data:
                    episode_item = self.__build_item(episode_info)
                    episodes.append({
                        "id": episode_item.guid,
                        "season": episode_item.season_number,
                        "episode": episode_item.episode_number,
                        "title": episode_item.title,
                        "overview": episode_item.overview
                    })
        return episodes

    def get_no_exists_episodes(self, meta_info, season, total_num):
        """根据标题、年份、季、总集数，查询缺少哪几集"""
        if not meta_info:
            return []

        # 获取现有集数
        episodes = self.get_tv_episodes(
            title=meta_info.get_name(),
            year=meta_info.year,
            season=season
        )

        # 计算缺失集数
        exists_episodes = [ep.get("episode") for ep in episodes if ep.get("season") == season]
        total_episodes = list(range(1, total_num + 1))
        return [ep for ep in total_episodes if ep not in exists_episodes]

    def get_remote_image_by_id(self, item_id, image_type):
        """根据ItemId查询远程图片地址"""
        if not self.is_authenticated():
            return None

        data = self.__request_api(f"/item/{item_id}")
        if data:
            item = self.__build_item(data)
            if image_type.lower() == "backdrop":
                return f"{self._host}{item.backdrops}" if item.backdrops else None
            else:
                return f"{self._host}{item.poster}" if item.poster else None
        return None

    def get_local_image_by_id(self, item_id):
        """根据ItemId查询本地图片地址"""
        return self.get_remote_image_by_id(item_id, "poster")

    def refresh_root_library(self):
        """刷新整个媒体库"""
        if not self.is_authenticated():
            return False
        if not self._userinfo or self._userinfo.is_admin != 1:
            log.error(f"【{self.client_name}】仅支持管理员账号刷新媒体库")
            return False

        # 必须调用 否则容易误报 -14 Task duplicate
        self.__request_api("/task/running")
        log.info(f"【{self.client_name}】刷新所有媒体库")
        data = self.__request_api("/mdb/scanall", method="post")
        return data is not None

    def refresh_library_by_items(self, items):
        """按类型、名称、年份来刷新媒体库"""
        if not self.is_authenticated():
            return False
        if not self._userinfo or self._userinfo.is_admin != 1:
            log.error(f"【{self.client_name}】仅支持管理员账号刷新媒体库")
            return False

        if not items:
            return True

        libraries = set()
        for item in items:
            lib = self.__match_library_by_path(Path(item.get("target_path", "")))
            if lib is None:
                # 如果有匹配失败的,刷新整个库
                return self.refresh_root_library()
            libraries.add(lib.guid)

        # 必须调用 否则容易误报 -14 Task duplicate
        self.__request_api("/task/running")
        for lib_guid in libraries:
            lib = self._libraries[lib_guid]
            log.info(f"【{self.client_name}】刷新媒体库：{lib.name}")
            data = self.__request_api(f"/mdb/scan/{lib.guid}", data={})
            if not data:
                # 如果失败，刷新整个库
                return self.refresh_root_library()
        return True

    def __match_library_by_path(self, path: Path) -> Optional[FeiNiuMediaDb]:
        """根据路径匹配媒体库"""
        def is_subpath(_path: Path, _parent: Path) -> bool:
            """判断_path是否是_parent的子目录下"""
            try:
                _path = _path.resolve()
                _parent = _parent.resolve()
                return _path.parts[: len(_parent.parts)] == _parent.parts
            except Exception:
                return False

        if not path:
            return None
        for lib in self._libraries.values():
            for d in lib.dir_list or []:
                if is_subpath(path, Path(d)):
                    return lib
        return None

    def get_libraries(self):
        """获取媒体服务器所有媒体库列表"""
        if not self.is_authenticated():
            # 尝试连接
            if not self.get_status():
                return []

        libraries = []
        for library in self._libraries.values():
            if self.__is_library_blocked(library.guid):
                continue

            if library.category == FeiNiuCategory.MOVIE:
                library_type = MediaType.MOVIE.value
            elif library.category == FeiNiuCategory.TV:
                library_type = MediaType.TV.value
            elif library.category == FeiNiuCategory.OTHERS:
                # 忽略这个库
                continue
            else:
                library_type = "Unknown"

            libraries.append({
                "id": library.guid,
                "name": library.name,
                "type": library_type,
                "path": library.dir_list or [],
                "image": f"{self._host}{library.posters[0]}" if library.posters else None,
                "link": f"{self._play_host or self._host}/library/{library.guid}"
            })
        return libraries

    def __is_library_blocked(self, library_guid: str) -> bool:
        """检查媒体库是否被屏蔽"""
        if library := self._libraries.get(library_guid):
            if library.category == FeiNiuCategory.OTHERS:
                # 忽略这个库
                return True
        return (
            True
            if (
                self._sync_libraries
                and "all" not in self._sync_libraries
                and library_guid not in self._sync_libraries
            )
            else False
        )

    def get_items(self, parent):
        """获取媒体库中的所有媒体"""
        if not self.is_authenticated():
            # 尝试连接
            if not self.get_status():
                return []

        items = []
        data = self.__request_api("/item/list", data={
            "ancestor_guid": parent,
            "tags": {"type": [FeiNiuType.MOVIE.value, FeiNiuType.TV.value, FeiNiuType.DIRECTORY.value]},
            "sort_type": "DESC",
            "sort_column": "create_time",
            "page": 1,
            "page_size": -1,  # 获取所有数据
            "exclude_grouped_video": 1
        })

        if data and data.get("list"):
            for info in data["list"]:
                item = self.__build_item(info)
                if item.type == FeiNiuType.DIRECTORY:
                    # 递归获取目录下的项目
                    items.extend(self.get_items(item.guid))
                elif item.type in [FeiNiuType.MOVIE, FeiNiuType.TV]:
                    items.append({
                        "id": item.guid,
                        "title": item.title,
                        "year": item.release_date[:4] if item.release_date else (
                            item.air_date[:4] if item.air_date else None
                        ),
                        "type": "Movie" if item.type == FeiNiuType.MOVIE else "Series",
                        "overview": item.overview,
                        "tmdbid": item.tmdb_id,
                        "imdbid": item.imdb_id,
                        "poster": f"{self._host}{item.poster}" if item.poster else None
                    })
        return items

    def get_play_url(self, item_id):
        """获取媒体播放链接"""
        if not self.is_authenticated():
            return None

        data = self.__request_api(f"/item/{item_id}")
        if data:
            item = self.__build_item(data)
            return self.__build_play_url(item)
        return None

    def __build_play_url(self, item: FeiNiuItem) -> str:
        """拼装播放链接"""
        host = self._play_host or self._host
        if item.type == FeiNiuType.EPISODE:
            return f"{host}/tv/episode/{item.guid}"
        elif item.type == FeiNiuType.SEASON:
            return f"{host}/tv/season/{item.guid}"
        elif item.type == FeiNiuType.MOVIE:
            return f"{host}/movie/{item.guid}"
        elif item.type == FeiNiuType.TV:
            return f"{host}/tv/{item.guid}"
        else:
            # 其它类型走通用页面，由飞牛来判断
            return f"{host}/other/{item.guid}"

    def get_playing_sessions(self):
        """获取正在播放的会话"""
        # 飞牛影视暂不支持播放会话
        return []

    def get_webhook_message(self, message):
        """解析Webhook报文，获取消息内容结构"""
        # 飞牛影视暂不支持Webhook
        return None

    def get_iteminfo(self, itemid):
        """根据ItemId查询项目详情"""
        if not self.is_authenticated():
            return {}

        data = self.__request_api(f"/item/{itemid}")
        if data:
            item = self.__build_item(data)
            return {
                'ProviderIds': {
                    'Tmdb': item.tmdb_id,
                    'Imdb': item.imdb_id
                },
                'Name': item.title,
                'OriginalTitle': item.original_title,
                'Overview': item.overview,
                'ProductionYear': item.release_date[:4] if item.release_date else (
                    item.air_date[:4] if item.air_date else None
                )
            }
        return {}

    def get_resume(self, num=12):
        """获取继续观看列表"""
        if not self.is_authenticated():
            return []

        ret_resume = []
        data = self.__request_api("/play/list")
        if data:
            for info in data:
                if len(ret_resume) >= num:
                    break
                item = self.__build_item(info)
                if self.__is_library_blocked(item.ancestor_guid):
                    continue

                if item.type == FeiNiuType.EPISODE:
                    title = item.tv_title
                    subtitle = f"S{item.season_number}:{item.episode_number} - {item.title}"
                else:
                    title = item.title
                    subtitle = "电影" if item.type == FeiNiuType.MOVIE else "视频"

                types = (
                    MediaType.MOVIE.value
                    if item.type in [FeiNiuType.MOVIE, FeiNiuType.VIDEO]
                    else MediaType.TV.value
                )

                ret_resume.append({
                    "id": item.guid,
                    "name": title,
                    "subtitle": subtitle,
                    "type": types,
                    "image": self.get_nt_image_url(f"{self._host}{item.poster}") if item.poster else None,
                    "link": self.__build_play_url(item),
                    "percent": (
                        item.ts / item.duration * 100.0
                        if item.duration and item.ts is not None
                        else 0
                    )
                })
        return ret_resume

    def get_latest(self, num=20):
        """获取最近添加列表"""
        if not self.is_authenticated():
            return []

        data = self.__request_api("/item/list", data={
            "tags": {"type": [FeiNiuType.MOVIE.value, FeiNiuType.TV.value]},
            "sort_type": "DESC",
            "sort_column": "create_time",
            "page": 1,
            "page_size": max(100, num * 5),
            "exclude_grouped_video": 1
        })

        latest = []
        if data and data.get("list"):
            for info in data["list"]:
                if len(latest) >= num:
                    break
                item = self.__build_item(info)
                if self.__is_library_blocked(item.ancestor_guid):
                    continue

                if item.type == FeiNiuType.EPISODE:
                    title = item.tv_title
                    subtitle = f"S{item.season_number}:{item.episode_number} - {item.title}"
                else:
                    title = item.title
                    subtitle = "电影" if item.type == FeiNiuType.MOVIE else "视频"

                types = (
                    MediaType.MOVIE.value
                    if item.type in [FeiNiuType.MOVIE, FeiNiuType.VIDEO]
                    else MediaType.TV.value
                )

                latest.append({
                    "id": item.guid,
                    "name": title,
                    "subtitle": subtitle,
                    "type": types,
                    "image": self.get_nt_image_url(f"{self._host}{item.poster}") if item.poster else None,
                    "link": self.__build_play_url(item)
                })
        return latest

    def get_host(self):
        """获取服务器地址"""
        return self._play_host or self._host
