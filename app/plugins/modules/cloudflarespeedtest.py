import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.plugins import EventManager, EventHandler
from app.plugins.modules._base import _IPluginModule
from app.utils import SystemUtils, RequestUtils, IpUtils
from app.utils.types import EventType
from config import Config
from jinja2 import Template


class CloudflareSpeedTestResult:
    """
    优选记录结果
    """
    def __init__(self, date, ip_type, old_ip, new_ip, status, msg):
        self.date = date
        self.ip_type = ip_type
        self.old_ip = old_ip
        self.new_ip = new_ip
        self.status = status
        self.msg = msg


class CloudflareSpeedTest(_IPluginModule):
    # 插件名称
    module_name = "Cloudflare IP优选"
    # 插件描述
    module_desc = "🌩 测试 Cloudflare CDN 延迟和速度，自动优选IP。"
    # 插件图标
    module_icon = "cloudflare.jpg"
    # 主题色
    module_color = "#F6821F"
    # 插件版本
    module_version = "2.0"
    # 插件作者
    module_author = "TonyLiooo"  # V1.0 thsrite
    # 作者主页
    author_url = "https://github.com/TonyLiooo"
    # 插件配置项ID前缀
    module_config_prefix = "cloudflarespeedtest_"
    # 加载顺序
    module_order = 12
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    eventmanager = None
    _customhosts = False
    _cf_ip = None
    _scheduler = None
    _cron = None
    _onlyonce = False
    _ipv4 = False
    _ipv6 = False
    _version = None
    _additional_args = None
    _re_install = False
    _notify = False
    _check = False
    _cf_path = None
    _cf_ipv4 = None
    _cf_ipv6 = None
    _result_file = None
    _release_prefix = 'https://github.com/XIU2/CloudflareSpeedTest/releases/download'
    _binary_name = 'cfst'
    _test_url = None
    _httping = False
    _delay_limit = None
    _speed_limit = None
    # 更新记录列表
    _last_run_results_list = None

    # 退出事件
    _event = Event()

    @staticmethod
    def get_fields():
        return [
            # 基础配置
            {
                'type': 'div',
                'content': [
                    # 第一行：基础配置
                    [
                        {
                            'title': '优选IP',
                            'required': "required",
                            'tooltip': '需搭配[自定义Hosts]插件使用，第一次使用请先统一设置一个IP',
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'cf_ip',
                                    'placeholder': '121.121.121.121',
                                }
                            ]
                        },
                        {
                            'title': '优选周期',
                            'required': "required",
                            'tooltip': '支持5位cron表达式，如：0 2 * * *（每天凌晨2点）',
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'cron',
                                    'placeholder': '0 2 * * *',
                                }
                            ]
                        },
                        {
                            'title': 'CloudflareSpeedTest版本',
                            'required': "",
                            'tooltip': '当前版本信息，如需更新可开启重装选项',
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'version',
                                    'placeholder': '暂未安装',
                                }
                            ]
                        }
                    ],
                    # 第二行：测试参数
                    [
                        {
                            'title': '测速地址',
                            'required': "",
                            'tooltip': '自定义测速地址，留空使用默认地址',
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'test_url',
                                    'placeholder': 'https://cf.xiu2.xyz/url',
                                }
                            ]
                        },
                        {
                            'title': '延迟上限(ms)',
                            'required': "",
                            'tooltip': '只输出低于指定延迟的IP。IPv4建议500ms，IPv6建议800ms',
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'delay_limit',
                                    'placeholder': '500',
                                }
                            ]
                        },
                        {
                            'title': '速度下限(MB/s)',
                            'required': "",
                            'tooltip': '只输出高于指定下载速度的IP，留空不限制',
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'speed_limit',
                                    'placeholder': '5',
                                }
                            ]
                        }
                    ],
                    # 第三行：IP类型选择
                    [
                        {
                            'title': 'IPv4',
                            'required': "",
                            'tooltip': '优选IPv4地址，推荐选择',
                            'type': 'switch',
                            'id': 'ipv4',
                        },
                        {
                            'title': 'IPv6',
                            'required': "",
                            'tooltip': '优选IPv6地址，需网络支持IPv6，测试时间较长',
                            'type': 'switch',
                            'id': 'ipv6',
                        },
                        {
                            'title': 'HTTPing模式',
                            'required': "",
                            'tooltip': '使用HTTP协议测速，可显示地区码但耗时更长',
                            'type': 'switch',
                            'id': 'httping',
                        },
                    ],
                    # 第四行：功能选项
                    [
                        {
                            'title': '自动校准',
                            'required': "",
                            'tooltip': '自动从自定义hosts插件中获取最常用的IP作为优选IP',
                            'type': 'switch',
                            'id': 'check',
                        },
                        {
                            'title': '立即运行一次',
                            'required': "",
                            'tooltip': '保存配置后立即执行一次优选任务',
                            'type': 'switch',
                            'id': 'onlyonce',
                        },
                        {
                            'title': '运行时通知',
                            'required': "",
                            'tooltip': '优选完成后发送通知',
                            'type': 'switch',
                            'id': 'notify',
                        },
                    ],
                    # 第五行：高级选项
                    [
                        {
                            'title': '重装后运行',
                            'required': "",
                            'tooltip': '每次重新下载CloudflareSpeedTest，网络不好慎选',
                            'type': 'switch',
                            'id': 're_install',
                        }
                    ]
                ]
            },
            {
                'type': 'details',
                'summary': '高级参数',
                'tooltip': 'CloudflareSpeedTest的高级参数，请勿随意修改',
                'content': [
                    [
                        {
                            'title': '额外参数',
                            'required': "",
                            'tooltip': '额外的命令行参数，请勿添加-f -o参数',
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'additional_args',
                                    'placeholder': '-dd'
                                }
                            ]
                        }
                    ]
                ]
            }
        ]

    @staticmethod
    def get_script():
        """
        返回插件额外的JS代码
        """
        return """
        $(document).ready(function () {
          $('#cloudflarespeedtest_version').prop('disabled', true);
        });
         """

    def get_page(self):
        """
        插件的额外页面，返回页面标题和页面内容
        """
        template = """
          <div class="table-responsive table-modal-body">
            <table class="table table-vcenter card-table table-hover table-striped">
              <thead>
              {% if ResultsCount > 0 %}
              <tr>
                <th>优选时间</th>
                <th>IP类型</th>
                <th>原IP</th>
                <th>新IP</th>
                <th>状态</th>
                <th>说明</th>
              </tr>
              {% endif %}
              </thead>
              <tbody>
              {% if ResultsCount > 0 %}
                {% for Item in Results %}
                  <tr>
                    <td>{{ Item.date }}</td>
                    <td>{{ Item.ip_type }}</td>
                    <td>{{ Item.old_ip }}</td>
                    <td>{{ Item.new_ip }}</td>
                    <td>{{ Item.status }}</td>
                    <td>{{ Item.msg }}</td>
                  </tr>
                {% endfor %}
              {% else %}
                <tr>
                  <td colspan="6" class="text-center">暂无优选记录</td>
                </tr>
              {% endif %}
              </tbody>
            </table>
          </div>
        """
        results_count = len(self._last_run_results_list) if self._last_run_results_list else 0
        return "优选记录", Template(template).render(
            ResultsCount=results_count,
            Results=self._last_run_results_list or []
        ), None

    def init_config(self, config=None):
        self.eventmanager = EventManager()

        # 初始化更新记录列表
        self._last_run_results_list = []

        # 读取配置
        if config:
            self._onlyonce = config.get("onlyonce")
            self._cron = config.get("cron")
            self._cf_ip = config.get("cf_ip")
            self._version = config.get("version")
            self._ipv4 = config.get("ipv4")
            self._ipv6 = config.get("ipv6")
            self._re_install = config.get("re_install")
            self._additional_args = config.get("additional_args")
            self._notify = config.get("notify")
            self._check = config.get("check")
            self._httping = config.get("httping")
            self._test_url = config.get("test_url")
            self._delay_limit = config.get("delay_limit")
            self._speed_limit = config.get("speed_limit")

        # 停止现有任务
        self.stop_service()

        # 启动定时任务 & 立即运行一次
        if self.get_state() or self._onlyonce:
            timezone = Config().get_timezone()
            if timezone:
                self._scheduler = BackgroundScheduler(timezone=timezone)
            else:
                self._scheduler = BackgroundScheduler()

            # 添加定时任务
            if self._cron:
                try:
                    # 验证cron表达式格式
                    if self._cron.count(' ') == 4:  # 5位cron表达式
                        self.info(f"Cloudflare CDN优选服务启动，周期：{self._cron}")
                        self._scheduler.add_job(self.__cloudflareSpeedTest, CronTrigger.from_crontab(self._cron))
                    else:
                        self.error(f"cron表达式格式错误：{self._cron}，应为5位表达式，如：0 2 * * *")
                        return
                except Exception as e:
                    self.error(f"cron表达式解析失败：{self._cron}，错误：{str(e)}")
                    return

            # 立即运行一次
            if self._onlyonce:
                self.info(f"Cloudflare CDN优选服务启动，立即运行一次")
                if timezone:
                    run_date = datetime.now(tz=pytz.timezone(timezone)) + timedelta(seconds=3)
                else:
                    run_date = datetime.now() + timedelta(seconds=3)
                self._scheduler.add_job(self.__cloudflareSpeedTest, 'date', run_date=run_date)
                # 关闭一次性开关
                self._onlyonce = False
                self.__update_config()

            # 启动调度器
            if self._scheduler.get_jobs():
                self._scheduler.print_jobs()
                self._scheduler.start()
                self.info("Cloudflare CDN优选调度器已启动")
            else:
                self.warn("没有添加任何任务到调度器")

    def __cloudflareSpeedTest(self):
        """
        CloudflareSpeedTest优选
        """
        self.info("开始执行Cloudflare CDN优选任务")

        # 初始化路径
        self._cf_path = self.get_data_path()
        self._result_file = os.path.join(self._cf_path, "result.csv")
        self.info(f"数据路径: {self._cf_path}")

        # 检查优选IP配置
        if not self._cf_ip:
            self.error("需要配置优选IP")
            return

        # 获取自定义Hosts插件配置
        customHosts = self.get_config("CustomHosts")
        self._customhosts = customHosts and customHosts.get("enable") if customHosts else False

        if not self._customhosts:
            self.warn("自定义Hosts插件未启用，优选结果无法自动应用")

        # ipv4和ipv6必须其一
        if not self._ipv4 and not self._ipv6:
            self._ipv4 = True
            self.__update_config()
            self.warn("未指定IP类型，默认使用IPv4")

        # 环境检查
        success, release_version = self.__check_envirment()
        if not success:
            self.error("环境检查失败，停止执行")
            return

        if release_version:
            self._version = release_version
            self.__update_config()

        # 处理hosts配置
        hosts = customHosts.get("hosts") if customHosts else None
        if isinstance(hosts, str):
            hosts = str(hosts).split('\n')

        # 校正优选ip
        if self._check and hosts:
            self.__check_cf_if(hosts=hosts)

        # 开始优选
        ip_type = "IPv6" if self._ipv6 and not self._ipv4 else "IPv4"
        self.info(f"开始Cloudflare {ip_type}优选，当前IP: {self._cf_ip}")

        # 构建并执行优选命令
        cf_command = self.__build_command()
        if not cf_command:
            self.error("构建优选命令失败")
            return

        self.info("正在执行CloudflareSpeedTest，进度将每2秒更新...")
        result = self.__execute_speedtest(cf_command)
        if result != 0:
            self.error(f"CloudflareSpeedTest执行失败，返回码: {result}")
            return

        # 获取并处理优选结果
        best_ip = self.__get_best_ip()

        if best_ip and (IpUtils.is_ipv4(best_ip) or IpUtils.is_ipv6(best_ip)):
            if best_ip == self._cf_ip:
                self.info("优选完成，IP未变化")
                self.__add_update_record(self._cf_ip, best_ip, "无变化", "优选完成，IP未变化")
            else:
                self.info(f"发现更优IP: {best_ip}")
                self.__update_hosts(customHosts, hosts, best_ip)
        else:
            self.__handle_no_result()

    def __update_hosts(self, customHosts, hosts, best_ip):
        """
        更新hosts配置
        """
        # 替换优选ip
        err_hosts = customHosts.get("err_hosts") if customHosts else None
        enable = customHosts.get("enable") if customHosts else None

        # 处理ip
        new_hosts = []
        if hosts:
            for host in hosts:
                if host and host != '\n':
                    host_arr = str(host).split()
                    if len(host_arr) > 0 and host_arr[0] == self._cf_ip:
                        new_hosts.append(host.replace(self._cf_ip, best_ip))
                    else:
                        new_hosts.append(host)

        # 更新自定义Hosts（智能保留所有其他配置项）
        if customHosts:
            # 基于现有配置进行更新，保留所有其他字段
            current_config = customHosts.copy()  # 复制完整配置
            # 只更新需要修改的字段
            current_config["hosts"] = new_hosts
            current_config["err_hosts"] = err_hosts
            current_config["enable"] = enable
        else:
            # 如果没有现有配置，创建基础配置
            current_config = {
                "hosts": new_hosts,
                "err_hosts": err_hosts,
                "enable": enable
            }
        
        self.update_config(current_config, "CustomHosts")

        # 更新优选ip
        old_ip = self._cf_ip
        self._cf_ip = best_ip
        self.__update_config()
        self.info(f"优选IP已更新: {old_ip} → {best_ip}")

        # 添加更新记录
        self.__add_update_record(old_ip, best_ip, "成功", f"优选IP已更新: {old_ip} → {best_ip}")

        # 触发自定义hosts插件重载
        if self.eventmanager:
            self.eventmanager.send_event(EventType.PluginReload, {"plugin_id": "CustomHosts"})

        if self._notify:
            self.send_message(
                title="【Cloudflare优选完成】",
                text=f"原IP：{old_ip}\n新IP：{best_ip}"
            )

    def __handle_no_result(self):
        """
        处理没有找到合适IP的情况
        """
        self.error("没有找到合适的优选IP")

        # 添加失败记录
        if self._ipv6 and not self._ipv4:
            msg = "IPv6优选失败，建议检查网络环境或调整延迟上限"
            self.warn("1. IPv6延迟上限建议设置为800ms以上")
            self.warn("2. 确认网络环境支持IPv6连接")
            self.warn("3. 可以尝试关闭速度限制")
            self.warn("4. 如果IPv6不可用，建议切换到IPv4")
        else:
            msg = "IPv4优选失败，建议检查网络环境或调整延迟上限"
            self.warn("1. 延迟上限是否设置过低（建议500ms以上）")
            self.warn("2. 网络环境是否正常")
            self.warn("3. 可以尝试关闭速度限制")

        self.__add_update_record(self._cf_ip, None, "失败", msg)
        self.info(f"保持当前优选IP不变: {self._cf_ip}")

    def __build_command(self):
        """
        构建CloudflareSpeedTest命令
        """
        if not self._cf_path or not self._result_file:
            return ""

        command_parts = [f'cd {self._cf_path}', '&&', f'./{self._binary_name}']

        # 添加输出文件参数
        command_parts.extend(['-o', self._result_file])

        # 添加IP文件参数 - 简化逻辑，优先IPv4，其次IPv6
        if self._ipv4:
            command_parts.extend(['-f', 'ip.txt'])
            if self._ipv6:
                self.warn("同时启用IPv4和IPv6，优先使用IPv4")
        elif self._ipv6:
            command_parts.extend(['-f', 'ipv6.txt'])

        # 添加HTTPing模式
        if self._httping:
            command_parts.append('-httping')

        # 添加测速地址
        if self._test_url:
            command_parts.extend(['-url', self._test_url])

        # 添加延迟限制 - IPv6通常延迟更高，需要更宽松的限制
        delay_limit = None
        if self._delay_limit:
            try:
                delay_limit = int(self._delay_limit)
                # IPv6延迟通常比IPv4高，给出更合理的建议
                if self._ipv6 and not self._ipv4 and delay_limit < 300:
                    self.warn(f"IPv6延迟上限 {delay_limit}ms 可能过低，建议500ms以上")
                elif delay_limit < 100:
                    self.warn(f"延迟上限 {delay_limit}ms 过低，建议200ms以上")
                command_parts.extend(['-tl', str(delay_limit)])
            except ValueError:
                self.warn(f"延迟上限参数格式错误: {self._delay_limit}")
        else:
            # IPv6使用更宽松的默认延迟限制
            if self._ipv6 and not self._ipv4:
                default_delay = 800  # IPv6默认800ms
            else:
                default_delay = 500  # IPv4默认500ms
            command_parts.extend(['-tl', str(default_delay)])

        # 添加速度限制
        if self._speed_limit:
            try:
                speed = float(self._speed_limit)
                command_parts.extend(['-sl', str(speed)])
            except ValueError:
                self.warn(f"速度下限参数格式错误: {self._speed_limit}")

        # 添加额外参数
        if self._additional_args:
            command_parts.append(self._additional_args)

        return ' '.join(command_parts)

    def __add_update_record(self, old_ip, new_ip, status, msg):
        """
        添加优选记录
        """
        if not self._last_run_results_list:
            self._last_run_results_list = []

        # 最多保存50条记录
        if len(self._last_run_results_list) >= 50:
            self._last_run_results_list = self._last_run_results_list[:49]

        # 获取当前时间
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # 确定IP类型
        ip_type = "IPv6" if self._ipv6 and not self._ipv4 else "IPv4"

        # 创建记录
        record = CloudflareSpeedTestResult(
            date=current_time,
            ip_type=ip_type,
            old_ip=old_ip or "未知",
            new_ip=new_ip or "未知",
            status=status,
            msg=msg
        )

        # 插入到列表开头
        self._last_run_results_list.insert(0, record)

    def __execute_speedtest(self, command):
        """
        执行CloudflareSpeedTest命令，保持原生输出
        """
        try:
            self.info("开始执行CloudflareSpeedTest，输出原生进度信息...")

            # 使用subprocess执行命令，实时显示输出
            process = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1  # 行缓冲
            )

            output_lines = []
            # 实时读取并显示输出
            while True:
                if process.stdout is None:
                    break
                output = process.stdout.readline()
                if output == '' and process.poll() is not None:
                    break
                if output:
                    line = output.strip()
                    if line:
                        output_lines.append(line)
                        # 直接显示CloudflareSpeedTest的原生输出
                        self.info(f"CloudflareSpeedTest: {line}")

            # 等待进程完成
            return_code = process.wait()

            # 如果有错误，显示最后几行输出用于调试
            if return_code != 0:
                self.error("CloudflareSpeedTest执行失败，最后几行输出：")
                for line in output_lines[-5:]:
                    if line.strip():
                        self.error(f"  {line}")

            return return_code

        except Exception as e:
            self.error(f"执行CloudflareSpeedTest时发生错误: {str(e)}")
            return 1

    def __get_best_ip(self):
        """
        从结果文件中获取最优IP
        """
        if not self._result_file:
            return None

        try:
            if not os.path.exists(self._result_file):
                self.error(f"结果文件不存在: {self._result_file}")
                # 如果没有结果文件，说明没有找到符合条件的IP
                if self._ipv6 and not self._ipv4:
                    self.warn("没有找到符合条件的IPv6地址，建议：1) 提高延迟上限到800ms以上 2) 检查IPv6网络连接")
                else:
                    self.warn("没有找到符合延迟条件的IP，建议调整延迟上限或检查网络环境")
                return None

            with open(self._result_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            if len(lines) < 2:
                self.warn("结果文件内容不足，没有找到有效的IP")
                if self._ipv6 and not self._ipv4:
                    self.warn("可能原因：1) IPv6延迟上限设置过低（建议800ms以上）2) 网络不支持IPv6 3) IPv6地址池问题")
                else:
                    self.warn("可能原因：1) 延迟上限设置过低 2) 网络环境问题 3) 速度限制过高")
                return None

            # 跳过标题行，获取第一个结果
            best_line = lines[1].strip()
            if best_line:
                # CSV格式：IP地址,已发送,已接收,丢包率,平均延迟,下载速度(MB/s),地区码
                best_ip = best_line.split(',')[0]
                return best_ip.strip()

        except Exception as e:
            self.error(f"解析结果文件失败: {str(e)}")

        return None

    def __check_cf_if(self, hosts):
        """
        校正cf优选ip
        防止特殊情况下cf优选ip和自定义hosts插件中ip不一致
        """
        # 统计每个IP地址出现的次数
        ip_count = {}
        for host in hosts:
            if not host or not host.strip():
                continue
            
            host_parts = host.split()
            if not host_parts:
                continue
                
            ip = host_parts[0]
            if not ip or ip.startswith('#'):
                continue
                
            if ip in ip_count:
                ip_count[ip] += 1
            else:
                ip_count[ip] = 1

        # 如果没有有效的IP数据，直接返回
        if not ip_count:
            self.debug("没有找到有效的hosts数据，跳过CF IP校正")
            return
        
        # 找出出现次数最多的IP地址
        max_ips = []  # 保存最多出现的IP地址
        max_count = 0
        for ip, count in ip_count.items():
            if count > max_count:
                max_ips = [ip]  # 更新最多的IP地址
                max_count = count
            elif count == max_count:
                max_ips.append(ip)

        # 如果出现次数最多的ip不止一个，则不做兼容处理
        if len(max_ips) != 1:
            return

        if max_ips[0] != self._cf_ip:
            self._cf_ip = max_ips[0]
            self.info(f"自动校正优选IP为: {max_ips[0]}")

    def __check_envirment(self):
        """
        环境检查
        """
        # 是否安装标识
        install_flag = False

        # 确保路径已初始化
        if not self._cf_path:
            self._cf_path = self.get_data_path()
            self._cf_ipv4 = os.path.join(self._cf_path, "ip.txt")
            self._cf_ipv6 = os.path.join(self._cf_path, "ipv6.txt")
            self._result_file = os.path.join(self._cf_path, "result.csv")

        # 是否重新安装
        if self._re_install:
            install_flag = True
            self.info(f'重新安装CloudflareSpeedTest，将先下载新版本再替换现有版本')

        # 判断目录是否存在
        cf_path = Path(self._cf_path)
        if not cf_path.exists():
            os.mkdir(self._cf_path)

        # 首先检查本地版本
        local_version = self.__get_local_version()
        if local_version and not install_flag:
            self.info(f"检查版本更新中...")
            # 获取远程版本进行比较
            release_version = self.__get_release_version()
            if release_version and release_version != local_version:
                self.info(f"发现新版本 {release_version}，当前版本 {local_version}")
                install_flag = True
            elif release_version:
                self.info(f"当前为最新版本 [{local_version}]！")
                return True, local_version
            else:
                self.warn("无法获取远程版本信息，使用本地版本")
                return True, local_version

        # 获取CloudflareSpeedTest最新版本
        if not local_version or install_flag:
            if not local_version:
                self.info(f"检查版本更新中...")
            release_version = self.__get_release_version()
            if not release_version:
                # 如果无法获取远程版本
                if local_version:
                    self.warn("无法获取远程版本信息，使用本地版本")
                    return True, local_version
                elif self._version:
                    self.warn("无法获取远程版本信息，使用配置中的版本")
                    release_version = self._version  # 使用上次的版本号
                    install_flag = True
                else:
                    self.warn("无法获取远程版本信息，使用默认版本 v2.3.4")
                    release_version = "v2.3.4"
                    install_flag = True

        # 确保有有效的版本号
        if not release_version:
            self.error("无法获取有效的版本号，停止安装")
            return False, None

        # 检查是否需要更新
        if not install_flag:
            if local_version and release_version != local_version:
                self.info(f"发现新版本 {release_version}，开始更新")
                install_flag = True
            elif release_version != self._version:
                install_flag = True

        # 重装后数据库有版本数据，但是本地没有则重装
        if not install_flag and not Path(f'{self._cf_path}/{self._binary_name}').exists():
            install_flag = True

        if not install_flag:
            return True, local_version or release_version

        # 检查环境、安装
        if SystemUtils.is_windows():
            # todo
            self.error(f"CloudflareSpeedTest暂不支持windows平台")
            return False, None
        elif SystemUtils.is_macos():
            # mac
            uname = SystemUtils.execute('uname -m')
            arch = 'amd64' if uname == 'x86_64' else 'arm64'
            cf_file_name = f'cfst_darwin_{arch}.zip'
            download_url = f'{self._release_prefix}/{release_version}/{cf_file_name}'
            return self.__os_install(download_url, cf_file_name, release_version,
                                     f"ditto -V -x -k --sequesterRsrc {self._cf_path}/{cf_file_name} {self._cf_path}",
                                     install_flag)
        else:
            # docker
            uname = SystemUtils.execute('uname -m')
            arch = 'amd64' if uname == 'x86_64' else 'arm64'
            cf_file_name = f'cfst_linux_{arch}.tar.gz'
            download_url = f'{self._release_prefix}/{release_version}/{cf_file_name}'
            return self.__os_install(download_url, cf_file_name, release_version,
                                     f"tar -zxf {self._cf_path}/{cf_file_name} -C {self._cf_path}",
                                     install_flag)

    def __os_install(self, download_url, cf_file_name, release_version, unzip_command, force_download=False):
        """
        macos docker安装cloudflare
        """
        # 下载安装包
        temp_file_path = f'{self._cf_path}/{cf_file_name}.tmp'
        final_file_path = f'{self._cf_path}/{cf_file_name}'

        if not Path(final_file_path).exists() or force_download:
            self.info(f"开始下载CloudflareSpeedTest {release_version}")

            # 多个下载源
            download_sources = [
                download_url,  # 原始GitHub
                f'https://gh-proxy.com/{download_url}',
                f'https://gh.con.sh/{download_url}',
                f'https://cors.isteed.cc/{download_url}',
                f'https://github.abskoop.workers.dev/{download_url}',
                f'https://hub.gitmirror.com/{download_url}',
                f'https://pd.zwc365.com/{download_url}',
            ]

            # 获取代理配置
            proxies = Config().get_proxies()
            https_proxy = proxies.get("https") if proxies and proxies.get("https") else None

            download_success = False
            for i, source in enumerate(download_sources, 1):
                self.info(f"尝试下载源 {i}/{len(download_sources)}: {source.split('/')[-1]}")

                # 构建wget命令，限制重试次数和超时，下载到临时文件
                base_wget_args = [
                    'wget',
                    '-O', temp_file_path,     # 输出到临时文件
                    '--no-check-certificate',
                    '--timeout=30',           # 连接超时30秒
                    '--dns-timeout=10',       # DNS解析超时10秒
                    '--connect-timeout=15',   # 连接超时15秒
                    '--read-timeout=60',      # 读取超时60秒
                    '--tries=2',              # 最多重试2次
                    '--waitretry=5',          # 重试间隔5秒
                    '--progress=dot:mega',    # 简化进度显示
                    '--no-verbose'            # 减少输出
                ]

                if https_proxy and source == download_url:
                    wget_cmd = base_wget_args + [
                        '-e', 'use_proxy=yes',
                        '-e', f'https_proxy={https_proxy}',
                        source
                    ]
                else:
                    wget_cmd = base_wget_args + [source]

                try:
                    import subprocess
                    result = subprocess.run(
                        wget_cmd,
                        capture_output=True,
                        text=True,
                        timeout=120
                    )

                    file_valid = self.__validate_download(temp_file_path)
                    wget_success = result.returncode == 0

                    if file_valid or (wget_success and os.path.exists(temp_file_path) and os.path.getsize(temp_file_path) > 2000000):
                        import shutil
                        shutil.move(temp_file_path, final_file_path)
                        download_success = True
                        self.info(f"下载成功: {source.split('/')[-1]}")
                        break
                    else:
                        if not file_valid and os.path.exists(temp_file_path):
                            file_size = os.path.getsize(temp_file_path)
                            if file_size < 1000000:
                                self.warn(f"下载文件异常，大小仅{file_size} bytes")
                        elif result.stderr:
                            self.warn(f"下载失败: {result.stderr.strip()}")

                    if os.path.exists(temp_file_path):
                        os.system(f'rm -f "{temp_file_path}"')

                except subprocess.TimeoutExpired:
                    if os.path.exists(temp_file_path):
                        os.system(f'rm -f "{temp_file_path}"')
                except Exception:
                    if os.path.exists(temp_file_path):
                        os.system(f'rm -f "{temp_file_path}"')

            if not download_success:
                self.error(f"所有下载源均失败，无法下载CloudflareSpeedTest {release_version}")
                if Path(f'{self._cf_path}/{self._binary_name}').exists():
                    self.warn("使用现有版本继续运行")
                    return True, release_version
                else:
                    self.error("没有可用的CloudflareSpeedTest版本，停止运行")
                    return False, None

        if Path(final_file_path).exists():
            try:
                backup_binary = None
                if Path(f'{self._cf_path}/{self._binary_name}').exists():
                    backup_binary = f'{self._cf_path}/{self._binary_name}.backup'
                    import shutil
                    shutil.copy2(f'{self._cf_path}/{self._binary_name}', backup_binary)

                extract_result = os.system(f'{unzip_command}')
                if extract_result != 0:
                    if backup_binary and os.path.exists(backup_binary):
                        shutil.move(backup_binary, f'{self._cf_path}/{self._binary_name}')
                    return False, None

                os.system(f'chmod +x {self._cf_path}/{self._binary_name}')

                if Path(f'{self._cf_path}/{self._binary_name}').exists():
                    self.info(f"CloudflareSpeedTest安装成功：{release_version}")
                    os.system(f'rm -f "{final_file_path}"')
                    if backup_binary and os.path.exists(backup_binary):
                        os.system(f'rm -f "{backup_binary}"')
                    return True, release_version
                else:
                    if backup_binary and os.path.exists(backup_binary):
                        shutil.move(backup_binary, f'{self._cf_path}/{self._binary_name}')
                    return False, None
            except Exception:
                if Path(f'{self._cf_path}/{self._binary_name}').exists():
                    return True, None
                else:
                    if self._cf_path:
                        os.system(f'rm -rf {self._cf_path}')
                    return False, None
        else:
            if Path(f'{self._cf_path}/{self._binary_name}').exists():
                return True, None
            else:
                if self._cf_path:
                    os.system(f'rm -rf {self._cf_path}')
                return False, None

    @EventHandler.register(EventType.PluginReload)
    def reload(self, event):
        """
        触发cf优选
        """
        plugin_id = event.event_data.get("plugin_id")
        if not plugin_id:
            return
        if plugin_id != self.__class__.__name__:
            return
        self.__cloudflareSpeedTest()

    def __update_config(self):
        """
        更新优选插件配置
        """
        self.update_config({
            "onlyonce": False,
            "cron": self._cron,
            "cf_ip": self._cf_ip,
            "version": self._version,
            "ipv4": self._ipv4,
            "ipv6": self._ipv6,
            "re_install": self._re_install,
            "additional_args": self._additional_args,
            "notify": self._notify,
            "check": self._check,
            "httping": self._httping,
            "test_url": self._test_url,
            "delay_limit": self._delay_limit,
            "speed_limit": self._speed_limit
        })

    def __get_local_version(self):
        """
        获取本地CloudflareSpeedTest版本
        """
        if not self._cf_path:
            return None

        binary_path = os.path.join(self._cf_path, self._binary_name)
        if not os.path.exists(binary_path):
            return None

        try:
            # 使用-v参数获取版本信息
            result = subprocess.run(
                [binary_path, '-v'],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0:
                output = result.stdout.strip()
                # 从输出中提取版本号，支持多种格式
                import re
                # 匹配版本号格式：v数字.数字.数字
                version_match = re.search(r'v\d+\.\d+\.\d+', output)
                if version_match:
                    return version_match.group()

                # 如果正则匹配失败，尝试分割方式
                parts = output.split()
                for part in parts:
                    if part.startswith('v') and '.' in part:
                        # 清理可能的特殊字符
                        clean_version = re.sub(r'[^\w\.]', '', part)
                        if re.match(r'v\d+\.\d+\.\d+', clean_version):
                            return clean_version

                # 如果都没找到，返回None而不是整个输出
                return None

        except (subprocess.TimeoutExpired, subprocess.SubprocessError, FileNotFoundError):
            pass

        return None

    @staticmethod
    def __get_release_version():
        """
        获取CloudflareSpeedTest最新版本
        """
        base_api = "https://api.github.com/repos/XIU2/CloudflareSpeedTest/releases/latest"
        api_sources = [
            base_api,
            f'https://gh-proxy.com/{base_api}',
            f'https://cors.isteed.cc/{base_api}',
            f'https://pd.zwc365.com/{base_api}',
            f'https://gh.noki.icu/{base_api}',
        ]

        proxies = Config().get_proxies()
        use_proxy = proxies and (proxies.get("https") or proxies.get("http"))

        for i, api_url in enumerate(api_sources, 1):
            try:
                if i == 1:
                    version_res = RequestUtils(timeout=8).get_res(api_url)
                    if not version_res or version_res.status_code != 200:
                        if use_proxy:
                            version_res = RequestUtils(proxies=True, timeout=8).get_res(api_url)
                else:
                    version_res = RequestUtils(timeout=8).get_res(api_url)

                if version_res and version_res.status_code == 200:
                    try:
                        ver_json = version_res.json()
                        if 'tag_name' in ver_json:
                            return f"{ver_json['tag_name']}"
                    except Exception:
                        continue
            except Exception:
                continue

        return None

    def __validate_download(self, file_path):
        """
        验证下载的文件是否有效
        """
        try:
            if not os.path.exists(file_path):
                return False

            file_size = os.path.getsize(file_path)
            if file_size < 1000000:
                self.warn(f"下载文件异常，大小仅{file_size} bytes")
                return False

            with open(file_path, 'rb') as f:
                header = f.read(512)
                if b'<html' in header.lower() or b'<!doctype' in header.lower():
                    return False

            if file_path.endswith('.tar.gz'):
                with open(file_path, 'rb') as f:
                    if f.read(2) != b'\x1f\x8b':
                        return False

                import subprocess
                try:
                    result = subprocess.run(
                        ['tar', '-tf', file_path],
                        capture_output=True,
                        text=True,
                        timeout=10,
                        stderr=subprocess.DEVNULL
                    )
                    return result.returncode == 0 and len(result.stdout.strip()) > 0
                except Exception:
                    return file_size > 2000000
            else:
                with open(file_path, 'rb') as f:
                    if f.read(4)[:2] != b'PK':
                        return False

                import subprocess
                try:
                    result = subprocess.run(
                        ['unzip', '-l', file_path],
                        capture_output=True,
                        text=True,
                        timeout=10,
                        stderr=subprocess.DEVNULL
                    )
                    return result.returncode == 0 and len(result.stdout.strip()) > 0
                except Exception:
                    return file_size > 2000000

        except Exception:
            return False

    def get_state(self):
        return self._cf_ip and True if self._cron else False

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
            self.error(f"停止服务时发生错误: {str(e)}")