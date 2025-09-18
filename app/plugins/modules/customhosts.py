from datetime import datetime, timedelta
from threading import Event

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from python_hosts import Hosts, HostsEntry

from app.plugins import EventHandler
from app.plugins.modules._base import _IPluginModule
from app.utils import SystemUtils, IpUtils, RequestUtils
from app.utils.types import EventType
from config import Config


class CustomHosts(_IPluginModule):
    # 插件名称
    module_name = "自定义Hosts"
    # 插件描述
    module_desc = "修改系统hosts文件，加速网络访问。"
    # 插件图标
    module_icon = "hosts.png"
    # 主题色
    module_color = "#02C4E0"
    # 插件版本
    module_version = "2.0"
    # 插件作者
    module_author = "TonyLiooo"
    # 作者主页
    author_url = "https://github.com/TonyLiooo"
    # 插件配置项ID前缀
    module_config_prefix = "customhosts_"
    # 加载顺序
    module_order = 11
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _hosts = None
    _enable = False
    _subscriptions = None
    _subscribe_enabled = False
    _scheduler = None
    _scheduler_cron = None
    _onlyonce = False
    _notify = False
    _event = None

    @staticmethod
    def get_fields():
        return [
            {
                'type': 'div',
                'content': [
                    [
                        {
                            'title': 'hosts',
                            'required': False,
                            'tooltip': 'hosts配置，会追加到系统hosts文件中生效',
                            'type': 'textarea',
                            'content':
                                {
                                    'id': 'hosts',
                                    'placeholder': '每行一个配置，格式为：ip host1 host2 ...',
                                    'rows': 10,
                                }
                        }
                    ],
                    [
                        {
                            'title': '错误hosts',
                            'required': False,
                            'tooltip': '错误的hosts配置会展示在此处，请修改上方hosts重新提交（错误的hosts不会写入系统hosts文件）',
                            'type': 'textarea',
                            'readonly': True,
                            'content':
                                {
                                    'id': 'err_hosts',
                                    'placeholder': '',
                                    'rows': 2,
                                }
                        }
                    ],
                    [
                        {
                            'title': '开启hosts同步',
                            'required': "",
                            'tooltip': '将自定义hosts更新到系统中生效，如因权限问题等无法更新到系统时此开关将自动关闭，此时需查看日志',
                            'type': 'switch',
                            'id': 'enable',
                        },
                        {
                            'title': '开启订阅',
                            'required': "",
                            'tooltip': '启用hosts订阅功能，定期从外部URL获取hosts配置',
                            'type': 'switch',
                            'id': 'subscribe_enabled',
                        },
                        {
                            'title': '立即订阅一次',
                            'required': "",
                            'tooltip': '立即执行一次订阅更新',
                            'type': 'switch',
                            'id': 'onlyonce',
                        },
                        {
                            'title': '发送通知',
                            'required': "",
                            'tooltip': '订阅更新完成后发送通知',
                            'type': 'switch',
                            'id': 'notify',
                        }
                    ]
                ]
            },
            {
                'type': 'details',
                'summary': '订阅设置',
                'tooltip': '配置hosts订阅源，支持多个订阅地址',
                'content': [
                    [
                        {
                            'title': '订阅周期',
                            'required': False,
                            'tooltip': '设置自动更新订阅的时间周期，支持5位cron表达式，留空则使用默认值（每天8点）',
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'scheduler_cron',
                                    'placeholder': '默认: 0 8 * * * (每天8点更新)',
                                }
                            ]
                        }
                    ],
                    [
                        {
                            'title': '订阅列表',
                            'required': False,
                            'tooltip': '订阅配置，每行一个订阅，支持|、,、空格分隔，格式：订阅名称 订阅URL 启用状态(enable/disable/留空默认enable)',
                            'type': 'textarea',
                            'content':
                                {
                                    'id': 'subscriptions',
                                    'placeholder': '示例：\nKekylin源 https://raw.githubusercontent.com/kekylin/hosts/main/hosts enable\n自定义源|https://example.com/hosts.txt|disable\n,GitHub加速,https://example.com/hosts2.txt,\n默认启用 https://example.com/hosts3.txt',
                                    'rows': 6,
                                }
                        }
                    ]
                ]
            }
        ]

    def get_page(self):
        """
        插件的额外页面，显示当前系统hosts列表
        """
        template = """
          <div class="table-responsive table-modal-body">
            <div class="mb-3">
              <div class="row g-2">
                <div class="col-md-6">
                  <div class="card">
                    <div class="card-header bg-primary text-white py-2">
                      <h6 class="card-title mb-0">
                        <i class="fa fa-chart-bar me-1"></i>Hosts统计信息
                      </h6>
                    </div>
                    <div class="card-body py-2">
                      <div class="row text-center">
                        <div class="col-4">
                          <div class="py-1">
                            <div class="h6 mb-0 text-secondary">{{ SystemCount }}</div>
                            <small class="text-muted">系统原有</small>
                          </div>
                        </div>
                        <div class="col-4">
                          <div class="py-1">
                            <div class="h6 mb-0 text-primary">{{ CustomCount }}</div>
                            <small class="text-muted">自定义</small>
                          </div>
                        </div>
                        <div class="col-4">
                          <div class="py-1">
                            <div class="h6 mb-0 text-info">{{ SubscribeCount }}</div>
                            <small class="text-muted">订阅</small>
                          </div>
                        </div>
                      </div>
                      <hr class="my-2">
                      <div class="row text-center">
                        <div class="col-6">
                          <div class="py-1">
                            <div class="h6 mb-0 text-warning">{{ EnabledSubs }}/{{ TotalSubs }}</div>
                            <small class="text-muted">启用订阅</small>
                          </div>
                        </div>
                        <div class="col-6">
                          <div class="py-1">
                            <div class="h5 mb-0 text-success">{{ TotalCount }}</div>
                            <small class="text-muted">总计</small>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
                <div class="col-md-6">
                  <div class="card">
                    <div class="card-header bg-success text-white py-2">
                      <h6 class="card-title mb-0">
                        <i class="fa fa-cogs me-1"></i>系统状态
                      </h6>
                    </div>
                    <div class="card-body py-2">
                      <div class="d-flex justify-content-between align-items-center mb-2">
                        <span class="fw-bold">Hosts同步:</span>
                        {% if HostsEnabled %}
                          <span class="badge bg-success">已启用</span>
                        {% else %}
                          <span class="badge bg-danger">已禁用</span>
                        {% endif %}
                      </div>
                      <div class="d-flex justify-content-between align-items-center mb-2">
                        <span class="fw-bold">订阅功能:</span>
                        {% if SubscribeEnabled %}
                          <span class="badge bg-success">已启用</span>
                        {% else %}
                          <span class="badge bg-warning">已禁用</span>
                        {% endif %}
                      </div>
                      <hr class="my-2">
                      <div class="text-center">
                        <div class="small text-muted mb-1">更新周期</div>
                        <code class="small">{{ Cron }}</code>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
            
            <table class="table table-vcenter card-table table-hover table-striped">
              <thead>
              <tr>
                <th>IP地址</th>
                <th>域名</th>
                <th>来源</th>
                <th>类型</th>
              </tr>
              </thead>
              <tbody>
              {% if HostsCount > 0 %}
                {% for Host in Hosts %}
                  <tr>
                    <td><code>{{ Host.ip }}</code></td>
                    <td>{{ Host.names }}</td>
                    <td>
                      {% if Host.source == "系统原有" %}
                        <span class="badge bg-secondary">{{ Host.source }}</span>
                      {% elif Host.source == "自定义" %}
                        <span class="badge bg-primary">{{ Host.source }}</span>
                      {% else %}
                        <span class="badge bg-info">{{ Host.source }}</span>
                      {% endif %}
                    </td>
                    <td>
                      {% if Host.type == "ipv4" %}
                        <span class="badge bg-success">IPv4</span>
                      {% else %}
                        <span class="badge bg-warning">IPv6</span>
                      {% endif %}
                    </td>
                  </tr>
                {% endfor %}
              {% else %}
                <tr>
                  <td colspan="4" class="text-center">暂无hosts配置</td>
                </tr>
              {% endif %}
              </tbody>
            </table>
          </div>
        """
        from jinja2 import Template
        
        hosts_info = self.__get_current_hosts_info()
        
        return "当前Hosts列表", Template(template).render(**hosts_info), None

    def init_config(self, config=None):
        # 初始化实例属性
        if self._hosts is None:
            self._hosts = []
        if self._subscriptions is None:
            self._subscriptions = []
        if self._event is None:
            self._event = Event()

        # 初始化状态变量
        hosts_enabled = False
        old_enable = getattr(self, '_enable', None)  # 保存旧的启用状态

        # 读取配置
        if config:
            self._enable = config.get("enable", False)
            self._hosts = config.get("hosts", [])
            self._subscribe_enabled = config.get("subscribe_enabled", False)
            self._scheduler_cron = config.get("scheduler_cron", "0 8 * * *") or "0 8 * * *"
            self._onlyonce = config.get("onlyonce", False)
            self._notify = config.get("notify", False)
            
            # 处理订阅列表
            subscriptions_str = config.get("subscriptions", "")
            self._subscriptions = self.__parse_subscriptions(subscriptions_str)
            
            # 恢复订阅内容
            self.__restore_subscriptions_content()
            
            # 处理hosts格式
            if isinstance(self._hosts, str):
                self._hosts = str(self._hosts).split('\n')
            
            # 测试hosts功能
            if self._enable and (self._hosts or self._subscriptions):
                # 排除空的host
                new_hosts = []
                if self._hosts:
                    for host in self._hosts:
                        if host and host != '\n':
                            new_hosts.append(host.replace("\n", "") + "\n")
                    self._hosts = new_hosts

                # 合并订阅hosts
                all_hosts = self.__merge_all_hosts()

                # 测试添加到系统
                error_flag, error_hosts = self.__add_hosts_to_system(all_hosts)
                if not error_flag:
                    hosts_enabled = True
                    total_hosts = len([h for h in all_hosts if h.strip() and not h.strip().startswith('#')])
                    self.info(f"插件初始化成功，共{total_hosts}条hosts")
                else:
                    self._enable = False
                    self.error("插件初始化失败，请检查权限")
                    # 更新错误Hosts配置
                    self.__update_config_with_errors(error_hosts)

        # 检查是否需要清理hosts
        if self._enable is False and old_enable is True:
            # 从启用变为禁用，清理插件hosts
            if self.__clean_plugin_hosts():
                self.info("已清理插件添加的hosts（功能已关闭）")
            else:
                self.error("清理插件hosts失败")

        # 停止现有任务
        self.stop_service()

        # 启动服务
        if hosts_enabled or self._subscribe_enabled:
            self._scheduler = BackgroundScheduler(timezone=Config().get_timezone())
            
            # 立即运行一次
            if self._onlyonce:
                if self._subscribe_enabled and self._subscriptions:
                    self.info("订阅服务启动，立即运行一次")
                    self._scheduler.add_job(self.__run_subscribe_task, 'date',
                                            run_date=datetime.now(tz=Config().get_timezone()) + timedelta(seconds=3))
                elif not self._subscribe_enabled:
                    self.warn("订阅功能未启用，立即订阅操作已忽略")
                # 重置开关
                self._onlyonce = False
                self.update_config({
                    "enable": self._enable,
                    "hosts": self._hosts,
                    "subscribe_enabled": self._subscribe_enabled,
                    "scheduler_cron": self._scheduler_cron,
                    "onlyonce": self._onlyonce,
                    "notify": self._notify,
                    "subscriptions": self.__build_subscriptions_str()
                })

            # 周期运行
            if self._subscribe_enabled and self._subscriptions and self._scheduler_cron:
                self.info(f"订阅服务启动，周期：{self._scheduler_cron}")
                self._scheduler.add_job(self.__run_subscribe_task,
                                        CronTrigger.from_crontab(self._scheduler_cron))

            # 启动任务
            if self._scheduler.get_jobs():
                self._scheduler.print_jobs()
                self._scheduler.start()

    @EventHandler.register(EventType.PluginReload)
    def reload(self, event):
        """
        响应插件重载事件
        """
        plugin_id = event.event_data.get("plugin_id")
        if not plugin_id:
            return
        if plugin_id != self.__class__.__name__:
            return
        return self.init_config(self.get_config())

    @staticmethod
    def __read_system_hosts():
        """
        读取系统hosts对象
        """
        if SystemUtils.is_windows():
            hosts_path = r"c:\windows\system32\drivers\etc\hosts"
        else:
            hosts_path = '/etc/hosts'
        return Hosts(path=hosts_path)

    def __clean_plugin_hosts(self):
        """
        清理插件添加的hosts
        """
        try:
            system_hosts = self.__read_system_hosts()
            orgin_entries = []
            for entry in system_hosts.entries:
                if entry.entry_type == "comment" and entry.comment == "# CustomHostsPlugin":
                    break
                orgin_entries.append(entry)
            system_hosts.entries = orgin_entries
            system_hosts.write()
            self.info("清理插件hosts成功")
            return True
        except Exception as err:
            self.error(f"清理插件hosts失败：{str(err)}")
            return False

    def __add_hosts_to_system(self, hosts):
        """
        添加hosts到系统
        """
        # 系统hosts对象
        system_hosts = self.__read_system_hosts()
        # 过滤掉插件添加的hosts
        orgin_entries = []
        for entry in system_hosts.entries:
            if entry.entry_type == "comment" and entry.comment == "# CustomHostsPlugin":
                break
            orgin_entries.append(entry)
        system_hosts.entries = orgin_entries
        # 新的有效hosts
        new_entrys = []
        # 新的错误的hosts
        err_hosts = []
        err_flag = False
        for host in hosts:
            if host is None:
                continue
            host_str = str(host).strip()
            if not host_str or host_str.startswith('#'):
                # 跳过空行与注释
                continue
            host_arr = host_str.split()
            # 基本格式与IP合法性校验
            if len(host_arr) < 2 or not IpUtils.is_ip(host_arr[0]):
                err_hosts.append(host if str(host).endswith('\n') else str(host) + '\n')
                self.error(f"{host_str} 格式错误或IP无效")
                continue
            try:
                host_entry = HostsEntry(
                    entry_type='ipv4' if IpUtils.is_ipv4(host_arr[0]) else 'ipv6',
                    address=host_arr[0],
                    names=host_arr[1:]
                )
                new_entrys.append(host_entry)
            except Exception as err:
                err_hosts.append(host if str(host).endswith('\n') else str(host) + '\n')
                self.error(f"{host_str} 格式转换错误：{str(err)}")

        # 写入系统hosts
        if new_entrys:
            try:
                # 添加分隔标识
                system_hosts.add([HostsEntry(entry_type='comment', comment="# CustomHostsPlugin")])
                # 添加新的Hosts
                system_hosts.add(new_entrys)
                system_hosts.write()
                self.info("更新系统hosts文件成功")
            except Exception as err:
                err_flag = True
                self.error(f"更新系统hosts文件失败：{str(err) or '请检查权限'}")
        return err_flag, err_hosts

    def get_state(self):
        # 必须开启hosts同步
        if not self._enable:
            return False
        
        # 检查是否有有效的自定义hosts
        has_valid_hosts = (self._hosts and 
                          isinstance(self._hosts, list) and 
                          len(self._hosts) > 0 and 
                          any(h and str(h).strip() for h in self._hosts))
        
        # 检查是否有有效的订阅（开启订阅且有启用的订阅项）
        has_valid_subscriptions = (self._subscribe_enabled and 
                                  self._subscriptions and 
                                  isinstance(self._subscriptions, list) and
                                  any(s.get('enabled') for s in self._subscriptions))
        
        # 只有当有有效hosts或有效订阅时才返回True
        return has_valid_hosts or has_valid_subscriptions

    def stop_service(self):
        """
        退出插件
        """
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._event.set()
                    self._scheduler.shutdown()
                    self._event.clear()
                self._scheduler = None
        except Exception as e:
            self.debug(f"停止调度器时发生异常：{str(e)}")
        finally:
            self._event.set()
    
    def cleanup_on_disable(self):
        """
        插件禁用时的清理操作
        """
        try:
            if self.__clean_plugin_hosts():
                self.info("插件禁用，已清理所有hosts")
            else:
                self.warn("插件禁用时清理hosts失败")
        except Exception as e:
            self.error(f"插件禁用清理时发生异常：{str(e)}")
        finally:
            self.stop_service()
    
    def __parse_subscriptions(self, subscriptions_str):
        """
        解析订阅配置，支持多种分隔符
        """
        subscriptions = []
        if not subscriptions_str:
            return subscriptions
        
        lines = subscriptions_str.strip().split('\n')
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # 尝试不同的分隔符
            parts = None
            if '|' in line:
                parts = line.split('|')
            elif ',' in line:
                parts = line.split(',')
            else:
                # 空格分隔
                temp_parts = line.split()
                if len(temp_parts) >= 2:
                    # 查找URL
                    url_index = -1
                    for i, part in enumerate(temp_parts):
                        if part.startswith('http'):
                            url_index = i
                            break
                    
                    if url_index > 0:
                        name = ' '.join(temp_parts[:url_index])
                        url = temp_parts[url_index]
                        status = temp_parts[url_index + 1] if len(temp_parts) > url_index + 1 else ''
                        parts = [name, url, status]
                    else:
                        parts = temp_parts
            
            if parts and len(parts) >= 2:
                name = parts[0].strip()
                url = parts[1].strip()
                enabled = True  # 默认启用
                
                if len(parts) > 2:
                    status = parts[2].strip().lower()
                    if status == 'disable' or status == '0':
                        enabled = False
                    # 其他值默认启用
                
                subscriptions.append({
                    'name': name,
                    'url': url,
                    'enabled': enabled
                })
        return subscriptions
    
    def __run_subscribe_task(self):
        """
        执行订阅任务
        """
        self.info("开始执行hosts订阅任务...")
        
        # 下载所有启用的订阅
        success_count = 0
        total_count = 0
        
        if not self._subscriptions or not isinstance(self._subscriptions, list):
            self.warn("订阅列表为空或格式错误")
            return
            
        for subscription in self._subscriptions:
            if not subscription.get('enabled'):
                continue
            
            total_count += 1
            name = subscription.get('name')
            url = subscription.get('url')
            
            try:
                self.info(f"正在下载订阅：{name} - {url}")
                content = self.__download_hosts(url)
                if content:
                    subscription['content'] = content
                    # 统计hosts数量
                    host_count = len([line for line in content.split('\n') 
                                    if line.strip() and not line.strip().startswith('#')])
                    self.info(f"订阅 {name} 下载成功，获取{host_count}条hosts")
                    success_count += 1
                else:
                    self.error(f"订阅 {name} 下载失败")
            except Exception as e:
                self.error(f"订阅 {name} 下载出错：{str(e)}")
        
        # 合并并更新系统hosts
        if self._enable:
            all_hosts = self.__merge_all_hosts()
            total_hosts = len([h for h in all_hosts if h.strip() and not h.strip().startswith('#')])
            error_flag, error_hosts = self.__add_hosts_to_system(all_hosts)
            
            if not error_flag:
                self.info(f"hosts订阅更新成功，共{total_hosts}条")
                # 保存订阅内容
                self.__save_subscriptions_content()
                if self._notify:
                    self.send_message(
                        title="【CustomHosts】",
                        text=f"hosts订阅更新成功，成功{success_count}/{total_count}个订阅"
                    )
            else:
                self.error("hosts订阅更新失败，请检查权限")
                if self._notify:
                    self.send_message(
                        title="【CustomHosts】",
                        text="hosts订阅更新失败，请查看日志"
                    )
        else:
            # hosts同步已关闭，清理插件hosts并保存订阅内容
            if self.__clean_plugin_hosts():
                self.info("已清理插件添加的hosts（hosts同步已关闭）")
            # 仍然保存订阅内容供将来使用
            self.__save_subscriptions_content()
    
    def __download_hosts(self, url):
        """
        下载hosts文件内容，失败时尝试使用代理
        """
        try:
            # 首次尝试直接下载
            res = RequestUtils(timeout=30).get_res(url)
            if res and res.status_code == 200:
                return res.text
            else:
                self.warn(f"直接下载失败，状态码：{res.status_code if res else 'None'}，尝试使用代理...")
                
        except Exception as e:
            self.warn(f"直接下载出错：{str(e)}，尝试使用代理...")
        
        # 尝试使用系统代理
        try:
            config = Config()
            
            proxies = None
            if hasattr(config, 'get_proxies') and config.get_proxies():
                proxies = config.get_proxies()
                self.info(f"检测到系统代理配置，使用代理下载：{url}")
            elif hasattr(config, 'get_proxy') and config.get_proxy():
                proxy_url = config.get_proxy()
                proxies = {
                    'http': proxy_url,
                    'https': proxy_url
                }
                self.info(f"检测到系统代理配置，使用代理下载：{url}")
            
            if proxies:
                res = RequestUtils(timeout=30, proxies=proxies).get_res(url)
                if res and res.status_code == 200:
                    self.info("使用代理下载成功")
                    return res.text
                else:
                    self.error(f"使用代理下载失败，状态码：{res.status_code if res else 'None'}")
            else:
                self.warn("未检测到系统代理配置")
                
        except Exception as e:
            self.error(f"使用代理下载出错：{str(e)}")
        
        return None
    
    def __merge_all_hosts(self):
        """
        合并所有hosts（自定义 + 订阅）
        """
        all_hosts = []
        
        # 添加自定义hosts
        if self._hosts and isinstance(self._hosts, list):
            all_hosts.extend(self._hosts)
        
        # 添加订阅hosts
        if self._subscribe_enabled and self._subscriptions and isinstance(self._subscriptions, list):
            for subscription in self._subscriptions:
                if not subscription.get('enabled'):
                    continue
                
                content = subscription.get('content', '')
                if not content:
                    continue
                
                # 添加订阅来源注释
                all_hosts.append(f"# === {subscription.get('name')} ===\n")
                
                # 处理订阅内容
                lines = content.strip().split('\n')
                for line in lines:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    # 验证基本格式
                    parts = line.split()
                    if len(parts) >= 2 and IpUtils.is_ip(parts[0]):
                        all_hosts.append(line + '\n')
        
        return all_hosts
    
    def __build_subscriptions_str(self):
        """
        构建订阅字符串
        """
        if not self._subscriptions or not isinstance(self._subscriptions, list):
            return ""
        
        lines = []
        for subscription in self._subscriptions:
            name = subscription.get('name', '')
            url = subscription.get('url', '')
            enabled = 'enable' if subscription.get('enabled', True) else 'disable'
            if name and url:
                lines.append(f"{name}|{url}|{enabled}")
        return '\n'.join(lines)
    
    def __update_config(self, extra_config=None):
        """
        更新插件配置
        """
        config = {
            "enable": self._enable,
            "hosts": self._hosts,
            "subscribe_enabled": self._subscribe_enabled,
            "scheduler_cron": self._scheduler_cron,
            "onlyonce": self._onlyonce,
            "notify": self._notify,
            "subscriptions": self.__build_subscriptions_str()
        }
        
        # 添加额外的配置项
        if extra_config:
            config.update(extra_config)
        
        self.update_config(config)
    
    def __update_config_with_errors(self, error_hosts):
        """
        更新插件配置（包含错误hosts）
        """
        self.__update_config({"err_hosts": error_hosts})
    
    def __save_subscriptions_content(self):
        """
        保存订阅内容到历史记录（持久化）
        """
        if not self._subscriptions or not isinstance(self._subscriptions, list):
            return
            
        subscriptions_content = {}
        for subscription in self._subscriptions:
            sub_name = subscription.get('name')
            content = subscription.get('content')
            if sub_name and content:
                subscriptions_content[sub_name] = content
        
        if subscriptions_content:
            existing_content = self.get_history("subscriptions_content")
            if existing_content:
                self.update_history("subscriptions_content", subscriptions_content)
            else:
                self.history("subscriptions_content", subscriptions_content)
    
    def __restore_subscriptions_content(self):
        """
        从历史记录恢复订阅内容
        """
        if not self._subscriptions or not isinstance(self._subscriptions, list):
            return
            
        subscriptions_content = self.get_history("subscriptions_content") or {}
        for subscription in self._subscriptions:
            sub_name = subscription.get('name')
            if sub_name and sub_name in subscriptions_content:
                subscription['content'] = subscriptions_content[sub_name]
    
    def __get_current_hosts_info(self):
        """
        获取当前hosts信息用于页面显示
        """
        hosts_list = []
        system_count = 0
        custom_count = 0
        subscribe_count = 0
        
        # 读取系统hosts文件
        try:
            system_hosts = self.__read_system_hosts()
            plugin_section_found = False
            current_subscription_name = None
            
            for entry in system_hosts.entries:
                # 检查是否到达插件标记
                if entry.entry_type == "comment" and entry.comment == "# CustomHostsPlugin":
                    plugin_section_found = True
                    continue
                
                # 处理有效的hosts条目
                if entry.entry_type in ['ipv4', 'ipv6'] and entry.address and entry.names:
                    ip = entry.address
                    names = ' '.join(entry.names)
                    host_type = entry.entry_type
                    
                    if not plugin_section_found:
                        # 插件标记之前的hosts为系统原有
                        hosts_list.append({
                            'ip': ip,
                            'names': names,
                            'source': '系统原有',
                            'type': host_type
                        })
                        system_count += 1
                    else:
                        # 插件标记之后的hosts需要判断来源
                        source = self.__determine_host_source(ip, names, current_subscription_name)
                        hosts_list.append({
                            'ip': ip,
                            'names': names,
                            'source': source,
                            'type': host_type
                        })
                        
                        if source == '自定义':
                            custom_count += 1
                        elif source != '系统原有':
                            subscribe_count += 1
                
                # 检查订阅来源注释
                elif plugin_section_found and entry.entry_type == "comment":
                    comment = entry.comment or ""
                    if comment.startswith("# === ") and comment.endswith(" ==="):
                        # 提取订阅名称
                        current_subscription_name = comment[6:-4].strip()
                    else:
                        # 其他注释则清除当前订阅名称
                        current_subscription_name = None
                        
        except Exception as e:
            self.debug(f"读取系统hosts文件失败：{str(e)}")
        
        # 统计订阅信息
        total_subs = len(self._subscriptions) if self._subscriptions else 0
        enabled_subs = sum(1 for s in self._subscriptions if s.get('enabled', True)) if self._subscriptions else 0
        
        return {
            'Hosts': hosts_list,
            'HostsCount': len(hosts_list),
            'SystemCount': system_count,
            'CustomCount': custom_count,
            'SubscribeCount': subscribe_count,
            'TotalCount': system_count + custom_count + subscribe_count,
            'TotalSubs': total_subs,
            'EnabledSubs': enabled_subs,
            'HostsEnabled': self._enable,
            'SubscribeEnabled': self._subscribe_enabled,
            'Cron': self._scheduler_cron or '0 8 * * * (默认)'
        }
    
    def __determine_host_source(self, ip, names, current_subscription_name):
        """
        判断hosts条目的来源
        """
        # 首先检查是否匹配自定义hosts
        if self._hosts and isinstance(self._hosts, list):
            for host_line in self._hosts:
                host_line = str(host_line).strip()
                if not host_line or host_line.startswith('#'):
                    continue
                
                parts = host_line.split()
                if len(parts) >= 2:
                    # 比较IP和域名
                    if parts[0] == ip:
                        host_names = ' '.join(parts[1:])
                        if host_names == names:
                            return '自定义'
        
        # 检查是否匹配订阅hosts
        if self._subscriptions and isinstance(self._subscriptions, list):
            for subscription in self._subscriptions:
                content = subscription.get('content', '')
                if not content:
                    continue
                    
                lines = content.strip().split('\n')
                for line in lines:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                        
                    parts = line.split()
                    if len(parts) >= 2 and parts[0] == ip:
                        host_names = ' '.join(parts[1:])
                        if host_names == names:
                            return subscription.get('name', '未知订阅')
        
        # 如果有当前订阅名称但不匹配内容，仍然尝试归属（可能是注释后的hosts）
        if current_subscription_name:
            # 验证当前订阅名称是否存在于配置中
            if self._subscriptions:
                for subscription in self._subscriptions:
                    if subscription.get('name') == current_subscription_name:
                        return current_subscription_name
        
        # 无法确定来源，标记为未知
        return '未知来源'
