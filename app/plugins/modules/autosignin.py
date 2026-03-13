import re
from datetime import datetime, timedelta
from multiprocessing.dummy import Pool as ThreadPool
from multiprocessing.pool import ThreadPool
from threading import Event

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
from lxml import etree

from app.helper import ChromeHelper, SubmoduleHelper, SiteHelper
from app.helper.cloudflare_helper import under_challenge
from app.message import Message
from app.plugins import EventHandler, EventManager
from app.plugins.modules._base import _IPluginModule
from app.sites.siteconf import SiteConf
from app.sites.sites import Sites
from app.utils import RequestUtils, ExceptionUtils, StringUtils, SchedulerUtils
from app.utils.types import EventType
from config import Config
from jinja2 import Template
import random

import asyncio
import inspect

class AutoSignIn(_IPluginModule):
    # 插件名称
    module_name = "站点自动签到"
    # 插件描述
    module_desc = "站点自动签到保号，支持重试。"
    # 插件图标
    module_icon = "signin.png"
    # 主题色
    module_color = "#4179F4"
    # 插件版本
    module_version = "1.1"
    # 插件作者
    module_author = "TonyLiooo"
    # 作者主页
    author_url = "https://github.com/TonyLiooo"
    # 插件配置项ID前缀
    module_config_prefix = "autosignin_"
    # 加载顺序
    module_order = 0
    # 可使用的用户级别
    auth_level = 2

    # 私有属性
    eventmanager = None
    siteconf = None
    _scheduler = None

    # 设置开关
    _enabled = False
    # 任务执行间隔
    _site_schema = []
    _cron = None
    _sign_sites = None
    _queue_cnt = None
    _retry_keyword = None
    _special_sites = None
    _onlyonce = False
    _notify = False
    _clean = False
    _auto_cf = None
    _missed_detection = False
    _missed_schedule = None
    # 退出事件
    _event = Event()

    @staticmethod
    def get_fields():
        sites = {site.get("id"): site for site in Sites().get_site_dict()}
        return [
            {
                'type': 'div',
                'content': [
                    # 同一行
                    [
                        {
                            'title': '开启定时签到',
                            'required': "",
                            'tooltip': '开启后会根据周期定时签到指定站点。',
                            'type': 'switch',
                            'id': 'enabled',
                        },
                        {
                            'title': '漏签检测',
                            'required': "",
                            'tooltip': '开启后会在指定时段内对未签到站点进行补签（每小时一次，时间随机）。',
                            'type': 'switch',
                            'id': 'missed_detection',
                        },
                        {
                            'title': '运行时通知',
                            'required': "",
                            'tooltip': '运行签到任务后会发送通知（需要打开插件消息通知）',
                            'type': 'switch',
                            'id': 'notify',
                        },
                        {
                            'title': '立即运行一次',
                            'required': "",
                            'tooltip': '打开后立即运行一次',
                            'type': 'switch',
                            'id': 'onlyonce',
                        },
                        {
                            'title': '清理缓存',
                            'required': "",
                            'tooltip': '清理本日已签到（开启后全部站点将会签到一次)',
                            'type': 'switch',
                            'id': 'clean',
                        }
                    ]
                ]
            },
            {
                'type': 'div',
                'content': [
                    # 同一行
                    [
                        {
                            'title': '签到周期',
                            'required': "",
                            'tooltip': '自动签到时间，四种配置方法：1、配置间隔，单位小时，比如23.5；2、配置固定时间，如08:00；3、配置时间范围，如08:00-09:00，表示在该时间范围内随机执行一次；4、配置5位cron表达式，如：0 */6 * * *；配置为空则不启用自动签到功能。',
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'cron',
                                    'placeholder': '0 0 0 ? *',
                                }
                            ]
                        },
                        {
                            'title': '漏签检测时段',
                            'required': "",
                            'tooltip': '配置时间范围，如08:00-23:59（每小时执行一次，执行时间随机）',
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'missed_schedule',
                                    'placeholder': '08:00-23:59',
                                    'default': '08:00-23:59'
                                }
                            ]
                        },
                        {
                            'title': '签到队列',
                            'required': "",
                            'tooltip': '同时并行签到的站点数量，默认10（根据机器性能，缩小队列数量会延长签到时间，但可以提升成功率）',
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'queue_cnt',
                                    'placeholder': '10',
                                }
                            ]
                        },
                        {
                            'title': '重试关键词',
                            'required': "",
                            'tooltip': '重新签到关键词，支持正则表达式；每天首次全签，后续如果设置了重试词则只签到命中重试词的站点，否则全签。',
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'retry_keyword',
                                    'placeholder': '失败|错误',
                                }
                            ]
                        },
                        {
                            'title': '自动优选',
                            'required': "",
                            'tooltip': '命中重试词数量达到设置数量后，自动优化IP（0为不开启，需要正确配置自定义Hosts插件和优选IP插件）',
                            'type': 'text',
                            'content': [
                                {
                                    'id': 'auto_cf',
                                    'placeholder': '0',
                                }
                            ]
                        },
                    ]
                ]
            },
            {
                'type': 'details',
                'summary': '签到站点',
                'tooltip': '只有选中的站点才会执行签到任务，不选则默认为全选',
                'content': [
                    # 同一行
                    [
                        {
                            'id': 'sign_sites',
                            'type': 'form-selectgroup',
                            'content': sites
                        },
                    ]
                ]
            },
            {
                'type': 'details',
                'summary': '特殊站点',
                'tooltip': '选中的站点无论是否匹配重试关键词都会进行重签（如无需要可不设置）',
                'content': [
                    # 同一行
                    [
                        {
                            'id': 'special_sites',
                            'type': 'form-selectgroup',
                            'content': sites
                        },
                    ]
                ]
            },
        ]

    def get_page(self):
        """
        插件的额外页面，返回页面标题和页面内容
        :return: 标题，页面内容，确定按钮响应函数
        """
        # 获取所有站点完整信息（包含signurl等）
        all_sites = Sites().get_sites()
        site_info_map = {str(s.get("id")): s for s in all_sites}
        
        # 获取今日签到统计
        today = datetime.today().strftime('%Y-%m-%d')
        today_history = self.get_history(key=today)
        today_signed_ids = set(str(s) for s in (today_history.get('sign', []) if today_history else []))
        today_retry_ids = set(str(s) for s in (today_history.get('retry', []) if today_history else []))
        
        # 获取历史签到记录
        all_history = self.get_history()
        site_last_signin = {}  # {site_id: {date, result, signurl}}
        results_list = []  # 保留原始历史记录列表
        if all_history:
            cutoff_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S')
            for hist in all_history:
                if isinstance(hist, dict) and hist.get("id") and hist.get("date"):
                    site_id = str(hist.get("id"))
                    # 更新站点最后签到记录
                    if site_id not in site_last_signin or hist.get("date") > site_last_signin[site_id].get("date", ""):
                        site_last_signin[site_id] = {
                            "date": hist.get("date"),
                            "result": hist.get("result", ""),
                            "signurl": hist.get("signurl", "")
                        }
                    # 收集历史记录列表
                    if hist.get("date") >= cutoff_date:
                        if not any(item.get("id") == hist.get("id") and item.get("date") == hist.get("date") for item in results_list):
                            results_list.append(hist)
        results_list.sort(key=lambda x: x.get("date", ""), reverse=True)
        results_list = results_list[:50]
        
        # 构建站点签到状态列表
        sign_site_ids = self._sign_sites if self._sign_sites else [str(s.get("id")) for s in all_sites]
        site_status_list = []
        for site_id in sign_site_ids:
            site_info = site_info_map.get(site_id, {})
            if not site_info:
                continue
            
            # 判断今日状态
            if site_id in today_signed_ids and site_id not in today_retry_ids:
                status = 'signed'
                status_text = '已签到'
                status_color = 'success'
            elif site_id in today_retry_ids:
                status = 'retry'
                status_text = '需重签'
                status_color = 'warning'
            else:
                status = 'pending'
                status_text = '待签到'
                status_color = 'secondary'
            
            last_signin = site_last_signin.get(site_id, {})
            # 获取站点地址：优先使用 signurl，其次 strict_url
            site_url = site_info.get("signurl") or site_info.get("strict_url") or ""
            # 提取域名部分用于显示
            if site_url:
                from urllib.parse import urlparse
                try:
                    parsed = urlparse(site_url)
                    display_url = parsed.netloc or site_url
                except:
                    display_url = site_url
            else:
                display_url = "-"
            
            site_status_list.append({
                'id': site_id,
                'name': site_info.get("name", "未知站点"),
                'signurl': display_url,
                'status': status,
                'status_text': status_text,
                'status_color': status_color,
                'last_signin_time': last_signin.get("date", "-"),
                'last_signin_result': last_signin.get("result", "-")
            })
        
        # 按状态和名称排序：需重签 > 待签到 > 已签到
        status_order = {'retry': 0, 'pending': 1, 'signed': 2}
        site_status_list.sort(key=lambda x: (status_order.get(x['status'], 9), x['name']))
        
        today_signed = len(today_signed_ids)
        today_retry = len(today_retry_ids)
        total_sites = len(sign_site_ids)

        # 获取未来任务列表
        future_tasks = []
        if self._scheduler:
            tz = pytz.timezone(Config().get_timezone())
            now = datetime.now(tz)
            for job in self._scheduler.get_jobs():
                if job.next_run_time and job.next_run_time > now:
                    # 判断任务类型
                    func_name = getattr(job.func, '__name__', str(job.func))
                    job_id = getattr(job, 'id', '') or ''
                    if 'sign_in' in func_name or '自动签到' in job_id:
                        task_type = '定时签到'
                        task_icon = 'fa-clock'
                        task_color = 'primary'
                    elif 'check_missed' in func_name or 'missed_check' in job_id:
                        task_type = '漏签检测'
                        task_icon = 'fa-search'
                        task_color = 'warning'
                    elif 'missed_signin' in job_id:
                        task_type = '补签任务'
                        task_icon = 'fa-redo'
                        task_color = 'success'
                    else:
                        task_type = '计划任务'
                        task_icon = 'fa-tasks'
                        task_color = 'secondary'
                    
                    future_tasks.append({
                        'job_id': job.id,
                        'time': job.next_run_time.strftime('%Y-%m-%d %H:%M:%S'),
                        'type': task_type,
                        'icon': task_icon,
                        'color': task_color,
                        'trigger': str(job.trigger)[:30]
                    })
            future_tasks.sort(key=lambda x: x['time'])

        # 下次签到时间
        next_signin_time = future_tasks[0]['time'] if future_tasks else '-'

        template = """
          <div class="table-responsive table-modal-body">
            <!-- 统计卡片 -->
            <div class="mb-3">
              <div class="row g-2">
                <div class="col-md-6">
                  <div class="card">
                    <div class="card-header bg-primary text-white py-2">
                      <h6 class="card-title mb-0">
                        <i class="fa fa-chart-bar me-1"></i>签到统计信息
                      </h6>
                    </div>
                    <div class="card-body py-2">
                      <div class="row text-center">
                        <div class="col-4">
                          <div class="py-1">
                            <div class="h5 mb-0 text-success">{{ TodaySigned }}</div>
                            <small class="text-muted">今日已签</small>
                          </div>
                        </div>
                        <div class="col-4">
                          <div class="py-1">
                            <div class="h5 mb-0 text-warning">{{ TodayRetry }}</div>
                            <small class="text-muted">待重签</small>
                          </div>
                        </div>
                        <div class="col-4">
                          <div class="py-1">
                            <div class="h5 mb-0 text-info">{{ TotalSites }}</div>
                            <small class="text-muted">总站点</small>
                          </div>
                        </div>
                      </div>
                      <hr class="my-2">
                      <div class="text-center">
                        <small class="text-muted">未签站点</small>
                        <div class="h6 mb-0 text-secondary">{{ TotalSites - TodaySigned }}</div>
                      </div>
                    </div>
                  </div>
                </div>
                <div class="col-md-6">
                  <div class="card">
                    <div class="card-header bg-success text-white py-2">
                      <h6 class="card-title mb-0">
                        <i class="fa fa-cogs me-1"></i>任务状态
                      </h6>
                    </div>
                    <div class="card-body py-2">
                      <div class="d-flex justify-content-between align-items-center mb-2">
                        <span class="fw-bold">定时签到:</span>
                        {% if Enabled %}
                          <span class="badge bg-success">已启用</span>
                        {% else %}
                          <span class="badge bg-danger">已禁用</span>
                        {% endif %}
                      </div>
                      <div class="d-flex justify-content-between align-items-center mb-2">
                        <span class="fw-bold">漏签检测:</span>
                        {% if MissedDetection %}
                          <span class="badge bg-success">已启用</span>
                        {% else %}
                          <span class="badge bg-warning">已禁用</span>
                        {% endif %}
                      </div>
                      <hr class="my-2">
                      <div class="text-center">
                        <small class="text-muted">下次执行</small>
                        <div class="small"><code>{{ NextSigninTime }}</code></div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <!-- 未来任务列表 -->
            {% if FutureTasksCount > 0 %}
            <div class="card mb-3">
              <div class="card-header bg-info text-white py-2">
                <h6 class="card-title mb-0">
                  <i class="fa fa-calendar-alt me-1"></i>未来签到任务 ({{ FutureTasksCount }})
                </h6>
              </div>
              <div class="card-body p-0">
                <table class="table table-vcenter card-table table-hover table-striped mb-0">
                  <thead>
                    <tr>
                      <th>执行时间</th>
                      <th>任务类型</th>
                      <th>触发器</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {% for Task in FutureTasks %}
                      <tr id="future_task_{{ loop.index }}">
                        <td><code>{{ Task.time }}</code></td>
                        <td><span class="badge bg-{{ Task.color }}"><i class="fa {{ Task.icon }} me-1"></i>{{ Task.type }}</span></td>
                        <td><small class="text-muted">{{ Task.trigger }}</small></td>
                        <td>
                          <a href="javascript:AutoSignIn_cancel_task('{{ Task.job_id }}', {{ loop.index }})" 
                             class="btn-action text-danger" title="取消任务">
                            <svg xmlns="http://www.w3.org/2000/svg" class="icon" width="24" height="24" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round">
                              <path stroke="none" d="M0 0h24v24H0z" fill="none"></path>
                              <line x1="18" y1="6" x2="6" y2="18"></line>
                              <line x1="6" y1="6" x2="18" y2="18"></line>
                            </svg>
                          </a>
                        </td>
                      </tr>
                    {% endfor %}
                  </tbody>
                </table>
              </div>
            </div>
            {% endif %}

            <!-- 站点签到状态 -->
            <div class="card mb-3">
              <div class="card-header bg-secondary text-white py-2">
                <h6 class="card-title mb-0">
                  <i class="fa fa-list-alt me-1"></i>站点签到状态
                </h6>
              </div>
              <div class="card-body p-0">
                <table class="table table-vcenter card-table table-hover table-striped mb-0">
                  <thead>
                  <tr>
                    <th style="width:120px">站点名称</th>
                    <th style="width:140px">站点地址</th>
                    <th style="width:70px">今日状态</th>
                    <th style="width:145px">最后签到</th>
                    <th>签到结果</th>
                    <th style="width:70px">操作</th>
                  </tr>
                  </thead>
                  <tbody>
                  {% if SiteStatusList|length > 0 %}
                    {% for Site in SiteStatusList %}
                      <tr id="site_row_{{ Site.id }}">
                        <td><strong>{{ Site.name }}</strong></td>
                        <td><small class="text-muted">{{ Site.signurl }}</small></td>
                        <td><span class="badge bg-{{ Site.status_color }}">{{ Site.status_text }}</span></td>
                        <td><code class="small">{{ Site.last_signin_time }}</code></td>
                        <td style="white-space:normal; word-break:break-word;">
                          {% if '成功' in Site.last_signin_result %}
                            <span class="badge bg-success" style="white-space:normal; line-height:1.4;">{{ Site.last_signin_result }}</span>
                          {% elif '已签' in Site.last_signin_result %}
                            <span class="badge bg-info" style="white-space:normal; line-height:1.4;">{{ Site.last_signin_result }}</span>
                          {% elif '失败' in Site.last_signin_result %}
                            <span class="badge bg-danger" style="white-space:normal; line-height:1.4;">{{ Site.last_signin_result }}</span>
                          {% elif Site.last_signin_result == '-' %}
                            <span class="text-muted">-</span>
                          {% else %}
                            <span class="badge bg-secondary" style="white-space:normal; line-height:1.4;">{{ Site.last_signin_result }}</span>
                          {% endif %}
                        </td>
                        <td>
                          <button class="btn btn-sm btn-outline-primary" id="signin_btn_{{ Site.id }}"
                                  onclick="AutoSignIn_signin_site('{{ Site.id }}', '{{ Site.name }}', this)">
                            签到
                          </button>
                        </td>
                      </tr>
                    {% endfor %}
                  {% else %}
                    <tr>
                      <td colspan="6" class="text-center text-muted py-3">暂无配置站点</td>
                    </tr>
                  {% endif %}
                  </tbody>
                </table>
              </div>
            </div>

            <!-- 签到历史记录 -->
            <div class="card">
              <div class="card-header bg-dark text-white py-2">
                <h6 class="card-title mb-0">
                  <i class="fa fa-history me-1"></i>签到历史记录 ({{ ResultsCount }})
                </h6>
              </div>
              <div class="card-body p-0">
                <table class="table table-vcenter card-table table-hover table-striped mb-0">
                  <thead>
                  {% if ResultsCount > 0 %}
                  <tr>
                    <th style="width:145px">签到时间</th>
                    <th style="width:120px">站点名称</th>
                    <th style="width:140px">站点地址</th>
                    <th>签到结果</th>
                    <th style="width:50px"></th>
                  </tr>
                  {% endif %}
                  </thead>
                  <tbody>
                  {% if ResultsCount > 0 %}
                    {% for Item in Results %}
                      <tr id="signin_history_{{ Item.id }}_{{ loop.index }}">
                        <td><code class="small">{{ Item.date }}</code></td>
                        <td><strong>{{ Item.name }}</strong></td>
                        <td><small class="text-muted">{{ Item.signurl }}</small></td>
                        <td style="white-space:normal; word-break:break-word;">
                          {% if '成功' in Item.result %}
                            <span class="badge bg-success" style="white-space:normal; line-height:1.4;">{{ Item.result }}</span>
                          {% elif '已签' in Item.result %}
                            <span class="badge bg-info" style="white-space:normal; line-height:1.4;">{{ Item.result }}</span>
                          {% elif '失败' in Item.result %}
                            <span class="badge bg-danger" style="white-space:normal; line-height:1.4;">{{ Item.result }}</span>
                          {% else %}
                            <span class="badge bg-secondary" style="white-space:normal; line-height:1.4;">{{ Item.result }}</span>
                          {% endif %}
                        </td>
                        <td>
                          <a href="javascript:AutoSignIn_delete_history('{{ Item.id }}', '{{ Item.date }}', {{ loop.index }})" 
                             class="btn-action text-danger" title="删除记录">
                            <svg xmlns="http://www.w3.org/2000/svg" class="icon" width="24" height="24" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round">
                              <path stroke="none" d="M0 0h24v24H0z" fill="none"></path>
                              <line x1="4" y1="7" x2="20" y2="7"></line>
                              <line x1="10" y1="11" x2="10" y2="17"></line>
                              <line x1="14" y1="11" x2="14" y2="17"></line>
                              <path d="M5 7l1 12a2 2 0 0 0 2 2h8a2 2 0 0 0 2 -2l1 -12"></path>
                              <path d="M9 7v-3a1 1 0 0 1 1 -1h4a1 1 0 0 1 1 1v3"></path>
                            </svg>
                          </a>
                        </td>
                      </tr>
                    {% endfor %}
                  {% else %}
                    <tr>
                      <td colspan="5" class="text-center text-muted py-3">暂无签到记录</td>
                    </tr>
                  {% endif %}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        """
        return "签到记录", Template(template).render(
            SiteStatusList=site_status_list,
            Results=results_list,
            ResultsCount=len(results_list),
            TodaySigned=today_signed,
            TodayRetry=today_retry,
            TotalSites=total_sites,
            Enabled=self._enabled,
            MissedDetection=self._missed_detection,
            NextSigninTime=next_signin_time,
            FutureTasks=future_tasks,
            FutureTasksCount=len(future_tasks)
        ), None

    @staticmethod
    def get_script():
        """
        返回插件额外的JS脚本
        """
        return """
          // 单站点签到
          function AutoSignIn_signin_site(site_id, site_name, btn) {
            var $btn = $(btn);
            var $row = $("#site_row_" + site_id);
            var originalHtml = $btn.html();
            
            // 禁用按钮并显示签到中状态
            $btn.html('<i class="fa fa-spinner fa-spin"></i> 签到中').prop('disabled', true).removeClass('btn-outline-primary').addClass('btn-secondary');
            
            ajax_post("run_plugin_method", {
              "plugin_id": "AutoSignIn",
              "method": "signin_single_site",
              "site_id": site_id
            }, function(ret) {
              // ret.result 是插件方法的返回值
              var data = ret.result || {};
              if (data.result) {
                var result = data.signin_result || '签到完成';
                var signinTime = data.signin_time || '-';
                var isSuccess = result.indexOf('成功') !== -1 || result.indexOf('已签') !== -1;
                
                // 更新按钮为完成状态
                $btn.html('<i class="fa fa-check"></i> 完成').removeClass('btn-secondary').addClass('btn-success');
                
                // 更新今日状态
                $row.find('td:eq(2)').html(isSuccess ? 
                  '<span class="badge bg-success">已签到</span>' : 
                  '<span class="badge bg-warning">需重签</span>');
                
                // 更新最后签到时间
                $row.find('td:eq(3)').html('<code class="small">' + signinTime + '</code>');
                
                // 更新签到结果
                var badgeStyle = 'style="white-space:normal; line-height:1.4;"';
                var resultBadge = isSuccess ? 
                  '<span class="badge bg-success" ' + badgeStyle + '>' + result + '</span>' :
                  '<span class="badge bg-danger" ' + badgeStyle + '>' + result + '</span>';
                $row.find('td:eq(4)').html(resultBadge);
                
                // 2秒后恢复按钮
                setTimeout(function() {
                  $btn.html(originalHtml).removeClass('btn-success').addClass('btn-outline-primary').prop('disabled', false);
                }, 2000);
              } else {
                // 签到失败
                $btn.html('<i class="fa fa-times"></i> 失败').removeClass('btn-secondary').addClass('btn-danger');
                show_fail_modal("签到失败", data.message || "未知错误");
                setTimeout(function() {
                  $btn.html(originalHtml).removeClass('btn-danger').addClass('btn-outline-primary').prop('disabled', false);
                }, 2000);
              }
            }, function() {
              // 请求超时
              $btn.html(originalHtml).removeClass('btn-secondary').addClass('btn-outline-primary').prop('disabled', false);
              show_fail_modal("签到失败", "请求超时");
            });
          }

          // 取消未来签到任务
          function AutoSignIn_cancel_task(job_id, row_index) {
            if (!confirm('确定要取消这个签到任务吗？')) {
              return;
            }
            ajax_post("run_plugin_method", {
              "plugin_id": "AutoSignIn",
              "method": "cancel_future_task",
              "job_id": job_id
            }, function(ret) {
              if (ret.result) {
                $("#future_task_" + row_index).fadeOut(300, function() {
                  $(this).remove();
                });
              } else {
                show_fail_modal("取消失败", ret.message || "未知错误");
              }
            });
          }

          // 删除签到历史记录
          function AutoSignIn_delete_history(site_id, date, row_index) {
            if (!confirm('确定要删除这条签到记录吗？')) {
              return;
            }
            ajax_post("run_plugin_method", {
              "plugin_id": "AutoSignIn",
              "method": "delete_signin_history",
              "site_id": site_id,
              "date": date
            }, function(ret) {
              if (ret.result) {
                $("#signin_history_" + site_id + "_" + row_index).fadeOut(300, function() {
                  $(this).remove();
                });
              } else {
                show_fail_modal("删除失败", ret.message || "未知错误");
              }
            });
          }
        """

    def delete_signin_history(self, site_id, date):
        """
        删除签到历史记录
        :param site_id: 站点ID
        :param date: 签到时间
        :return: 删除结果
        """
        try:
            # 删除单条历史记录
            history_key = f"{site_id}_{date}"
            self.delete_history(key=history_key)
            self.info(f"已删除签到记录: {site_id} - {date}")
            return {"result": True, "message": "删除成功"}
        except Exception as e:
            self.error(f"删除签到记录失败: {str(e)}")
            return {"result": False, "message": str(e)}

    def cancel_future_task(self, job_id):
        """
        取消未来签到任务
        :param job_id: 任务ID
        :return: 取消结果
        """
        try:
            if self._scheduler:
                job = self._scheduler.get_job(job_id)
                if job:
                    self._scheduler.remove_job(job_id)
                    self.info(f"已取消签到任务: {job_id}")
                    return {"result": True, "message": "取消成功"}
                else:
                    return {"result": False, "message": "任务不存在"}
            else:
                return {"result": False, "message": "调度器未启动"}
        except Exception as e:
            self.error(f"取消签到任务失败: {str(e)}")
            return {"result": False, "message": str(e)}

    def signin_single_site(self, site_id):
        """
        单站点签到
        :param site_id: 站点ID
        :return: 签到结果
        """
        try:
            site_id = str(site_id)
            site_info = Sites().get_sites(siteid=site_id)
            if not site_info:
                return {"result": False, "message": "站点不存在"}
            
            site_name = site_info.get("name", "未知站点")
            self.info(f"开始单站点签到: {site_name}")
            
            # 执行签到 - signin_site 返回 (msg, signinTime, home_url)
            msg, signin_time, home_url = self.signin_site(site_info)
            
            # 解析签到结果
            is_success = any(x in msg for x in ['签到成功', '已签到', '登录成功', '仿真签到成功'])
            
            # 提取结果文本 (去掉站点名称前缀)
            result_match = re.search(r'【.*?】(.*)', msg)
            result_text = result_match.group(1) if result_match else msg
            
            # 更新今日签到记录
            today = datetime.today().strftime('%Y-%m-%d')
            today_history = self.get_history(key=today) or {}
            sign_list = list(today_history.get('sign', []))
            retry_list = list(today_history.get('retry', []))
            
            if is_success:
                if site_id not in [str(s) for s in sign_list]:
                    sign_list.append(site_id)
                if site_id in [str(s) for s in retry_list]:
                    retry_list = [s for s in retry_list if str(s) != site_id]
            else:
                if site_id not in [str(s) for s in retry_list]:
                    retry_list.append(site_id)
            
            self.update_history(key=today, value={"sign": sign_list, "retry": retry_list})
            
            # 保存单条记录
            self.history(key=f"{site_id}_{signin_time}",
                         value={
                             "id": site_id,
                             "name": site_name,
                             "date": signin_time,
                             "result": result_text,
                             "signurl": site_info.get("signurl") or site_info.get("strict_url") or ""
                         })
            
            self.info(f"单站点签到完成: {site_name} - {result_text}")
            return {
                "result": True,
                "signin_result": result_text,
                "signin_time": signin_time,
                "message": f"{site_name}: {result_text}"
            }
        except Exception as e:
            self.error(f"单站点签到失败: {str(e)}")
            return {"result": False, "message": str(e)}

    def init_config(self, config=None):
        self.siteconf = SiteConf()
        self.eventmanager = EventManager()

        # 读取配置
        if config:
            self._enabled = config.get("enabled")
            self._cron = config.get("cron")
            self._retry_keyword = config.get("retry_keyword")
            self._sign_sites = config.get("sign_sites")
            self._special_sites = config.get("special_sites") or []
            self._notify = config.get("notify")
            self._queue_cnt = config.get("queue_cnt")
            self._onlyonce = config.get("onlyonce")
            self._clean = config.get("clean")
            self._auto_cf = config.get("auto_cf")
            self._missed_detection = config.get("missed_detection")
            self._missed_schedule = config.get("missed_schedule")
        
        if not self._sign_sites:
            self._sign_sites = [str(item.get("id")) for item in Sites().get_site_dict()]

        if self.is_valid_time_range(self._missed_schedule):
            self._missed_schedule = re.sub(r'\s', '', str(self._missed_schedule)).replace('24:00', '23:59')
        else:
            self._missed_detection = False
            self._missed_schedule = None

        # 遍历列表并删除日期超过7天的字典项

        # 停止现有任务
        self.stop_service()

        # 启动服务
        if self._enabled or self._onlyonce:
            # 加载模块
            self._site_schema = SubmoduleHelper.import_submodules('app.plugins.modules._autosignin',
                                                                  filter_func=lambda _, obj: hasattr(obj, 'match'))
            self.debug(f"加载站点签到：{self._site_schema}")

            # 定时服务
            self._scheduler = BackgroundScheduler(timezone=Config().get_timezone())

            # 清理缓存即今日历史
            if self._clean:
                self.delete_history(key=datetime.today().strftime('%Y-%m-%d'))

            # 运行一次
            if self._onlyonce:
                self.info(f"签到服务启动，立即运行一次")
                self._scheduler.add_job(self.sign_in, 'date',
                                        run_date=datetime.now(tz=pytz.timezone(Config().get_timezone())) + timedelta(
                                            seconds=3))
            # 漏签检测服务
            if self._missed_detection and self.is_valid_time_range(self._missed_schedule):
                self.info(f"漏签检测服务启动，检测时段：{self._missed_schedule}")
                self.check_missed_signs()

            if self._onlyonce or self._clean:
                # 关闭一次性开关|清理缓存开关
                self._clean = False
                self._onlyonce = False
                    
                self.update_config({
                    "enabled": self._enabled,
                    "cron": self._cron,
                    "retry_keyword": self._retry_keyword,
                    "sign_sites": self._sign_sites,
                    "special_sites": self._special_sites,
                    "notify": self._notify,
                    "onlyonce": self._onlyonce,
                    "queue_cnt": self._queue_cnt,
                    "clean": self._clean,
                    "auto_cf": self._auto_cf,
                    "missed_detection": self._missed_detection,
                    "missed_schedule": self._missed_schedule,
                })

            # 周期运行
            if self._cron:
                self.info(f"定时签到服务启动，周期：{self._cron}")
                SchedulerUtils.start_job(scheduler=self._scheduler,
                                         func=self.sign_in,
                                         func_desc="自动签到",
                                         cron=str(self._cron))

            # 启动任务
            if self._scheduler.get_jobs():
                self._scheduler.print_jobs()
                self._scheduler.start()

    @staticmethod
    def get_command():
        """
        定义远程控制命令
        :return: 命令关键字、事件、描述、附带数据
        """
        return {
            "cmd": "/pts",
            "event": EventType.SiteSignin,
            "desc": "站点签到",
            "data": {}
        }

    @staticmethod
    def is_valid_time_range(input_str):
        if not input_str:
            return False
        input_str = re.sub(r'\s', '', input_str).replace('24:00', '23:59')

        pattern = r'^\d{2}:\d{2}-\d{2}:\d{2}$'

        # 验证时间范围是否合理
        if re.match(pattern, input_str):
            start_time, end_time = input_str.split('-')
            start_hour, start_minute = map(int, start_time.split(':'))
            end_hour, end_minute = map(int, end_time.split(':'))
            
            if (0 <= start_hour <= 23 and 0 <= start_minute <= 59 and
                0 <= end_hour <= 23 and 0 <= end_minute <= 59 and
                (start_hour < end_hour or (start_hour == end_hour and start_minute < end_minute))):
                return True
        return False

    @staticmethod
    def calculate_time_range(time_range, current_time):
        # 解析时间范围字符串
        start_str, end_str = time_range.split('-')
        start_str = start_str.strip()
        end_str = end_str.strip()
        
        # 解析开始时间和结束时间
        start_hour, start_minute = map(int, start_str.split(':'))
        end_hour, end_minute = map(int, end_str.split(':'))

        start_time = datetime(current_time.year, current_time.month, current_time.day, start_hour, start_minute, 0)
        end_time = datetime(current_time.year, current_time.month, current_time.day, end_hour, end_minute, 59)

        if not isinstance(current_time, datetime):
            current_time = datetime.now()

        # 计算时间
        if  start_time <= current_time < end_time: # 时间段内
            start_time = current_time.replace(minute=0, second=0) + timedelta(hours=1)
            if start_time > end_time:
                next_day = current_time + timedelta(days=1)
                start_time = datetime(next_day.year, next_day.month, next_day.day, start_hour, start_minute, 0)
                end_time = datetime(next_day.year, next_day.month, next_day.day, start_hour, 59, 59)
                return '时段内', start_time, end_time
            if start_time + timedelta(minutes=59, seconds=59) < end_time:
                end_time = start_time + timedelta(minutes=59, seconds=59)
            return '时段内', start_time, end_time
        elif current_time >= end_time:  # 时间段后
            next_day = current_time + timedelta(days=1)
            start_time = datetime(next_day.year, next_day.month, next_day.day, start_hour, start_minute, 0)
            end_time = datetime(next_day.year, next_day.month, next_day.day, start_hour, 59, 59)
            return '时段后', start_time, end_time
        elif current_time < start_time:  # 时间段前
            start_time = datetime(current_time.year, current_time.month, current_time.day, start_hour, start_minute, 0)
            end_time = datetime(current_time.year, current_time.month, current_time.day, start_hour, 59, 59)
            return '时段前', start_time, end_time
        else:
            return None, None, None

    def _schedule_next_missed_check(self, start_time, end_time):
        """
        安排下一次漏签检测任务
        :param start_time: 时间范围起始
        :param end_time: 时间范围结束
        """
        min_minute = min(start_time.minute, end_time.minute)
        max_minute = max(start_time.minute, end_time.minute)
        random_minute = random.randint(min_minute, max_minute)
        random_second = random.randint(0, 59)
        run_time = start_time.replace(minute=random_minute, second=random_second)
        
        tz = pytz.timezone(Config().get_timezone())
        if run_time.tzinfo is None:
            run_time = run_time.replace(tzinfo=tz)
        
        now = datetime.now(tz)
        if run_time <= now:
            run_time = now + timedelta(seconds=5)
            self.info(f"检测时间已过，调整为：{run_time.strftime('%Y-%m-%d %H:%M:%S')}")
        else:
            self.info(f"下一次检测时间：{run_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # 使用任务ID去重，避免重复任务
        job_id = f"missed_check_{run_time.strftime('%Y%m%d_%H')}"
        self._scheduler.add_job(self.check_missed_signs, DateTrigger(run_date=run_time),
                                id=job_id, replace_existing=True)

    # 漏签检测服务
    def check_missed_signs(self):
        # 日期
        today = datetime.today()
        today_str = today.strftime('%Y-%m-%d')
        today_history = self.get_history(key=today_str)
        base_sites = self._sign_sites if self._sign_sites else [str(item.get("id")) for item in Sites().get_site_dict()]
        
        if not today_history:
            sign_sites = base_sites
        else:
            # 今天已签到需要重签站点
            retry_sites = [str(sid) for sid in (today_history.get('retry') or []) if str(sid) in base_sites]
            # 今天已签到站点
            already_sign_sites = today_history.get('sign') or []
            already_sign_sites_ids = set(str(s) for s in already_sign_sites)
            # 今日未签站点
            no_sign_sites = [site_id for site_id in base_sites if site_id not in already_sign_sites_ids]
            # 签到站点 = 需要重签+今日未签
            sign_sites = list(set(retry_sites + no_sign_sites))
        
        if sign_sites:
            status, start_time, end_time = self.calculate_time_range(self._missed_schedule, datetime.now())
            if status == '时段内' and not self._onlyonce:
                self.info(f"漏签检测：发现 {len(sign_sites)} 个站点需要补签")
                tz = pytz.timezone(Config().get_timezone())
                self._scheduler.add_job(self.sign_in, 'date',
                                        run_date=datetime.now(tz=tz) + timedelta(seconds=3),
                                        id=f"missed_signin_{today_str}", replace_existing=True)
            self._schedule_next_missed_check(start_time, end_time)
        else:
            # 今日已全部签到，安排明天的检测
            status, start_time, end_time = self.calculate_time_range(
                self._missed_schedule, 
                datetime.now().replace(hour=0, minute=0, second=0) + timedelta(days=1))
            self.info("今日已全部签到，安排明天的漏签检测")
            self._schedule_next_missed_check(start_time, end_time)


    @EventHandler.register(EventType.SiteSignin)
    def sign_in(self, event=None):
        """
        自动签到
        """
        # 日期
        today = datetime.today()
        yesterday = today - timedelta(days=1)
        yesterday_str = yesterday.strftime('%Y-%m-%d')
        # 删除昨天历史
        self.delete_history(yesterday_str)

        # 查看今天有没有签到历史
        today = today.strftime('%Y-%m-%d')
        today_history = self.get_history(key=today)
        # 今日没数据
        base_sites = self._sign_sites if self._sign_sites else [str(item.get("id")) for item in Sites().get_site_dict()]
        if not today_history:
            sign_sites = base_sites
            self.info(f"今日 {today} 未签到，开始签到已选站点")
        else:
            # 今天已签到需要重签站点
            retry_sites = [str(sid) for sid in (today_history.get('retry') or []) if str(sid) in base_sites]
            # 今天已签到站点
            already_sign_sites = today_history.get('sign') or []
            # 今日未签站点
            already_sign_sites_ids = set(str(s) for s in already_sign_sites)
            no_sign_sites = [site_id for site_id in base_sites if site_id not in already_sign_sites_ids]
            # 签到站点 = 需要重签+今日未签+特殊站点
            sign_sites = list(set(retry_sites + no_sign_sites + self._special_sites))
            if sign_sites:
                self.info(f"今日 {today} 已签到，开始重签重试站点、特殊站点、未签站点")
            else:
                self.info(f"今日 {today} 已签到，无重新签到站点，本次任务结束")
                return

        # 查询签到站点
        sign_sites = [str(x) for x in sign_sites]
        sign_sites = Sites().get_sites(siteids=sign_sites)
        if not sign_sites:
            self.info("没有可签到站点，停止运行")
            return

        # 签到前清理残留的僵尸浏览器进程
        try:
            ChromeHelper.prune_chrome_leftovers(max_age_minutes=10)
        except Exception as e:
            self.debug(f"清理残留浏览器进程时出错: {e}")

        # 执行签到
        self.info("开始执行签到任务")
        with ThreadPool(min(len(sign_sites), int(self._queue_cnt) if self._queue_cnt else 10)) as p:
            status = p.map(self.signin_site, sign_sites)

        if status:
            self.info("站点签到任务完成！")

            # 命中重试词的站点id
            retry_sites = []
            # 命中重试词的站点签到msg
            retry_msg = []
            # 登录成功
            login_success_msg = []
            # 签到成功
            sign_success_msg = []
            # 已签到
            already_sign_msg = []
            # 仿真签到成功
            fz_sign_msg = []
            # 失败｜错误
            failed_msg = []

            sites = {site.get('name'): site.get("id") for site in Sites().get_site_dict()}
            for s in status:
                site_names = re.findall(r'【(.*?)】', s[0])
                site_id = sites.get(site_names[0], None) if site_names else None
                # 记录本次命中重试关键词的站点
                if self._retry_keyword:
                    match = re.search(self._retry_keyword, s[0])
                    if match and site_id:
                        self.debug(f"站点 {site_names[0]} 命中重试关键词 {self._retry_keyword}")
                        retry_sites.append(str(site_id))
                        # 命中的站点
                        retry_msg.append(s[0])
                        continue

                if "登录成功" in s[0]:
                    login_success_msg.append(s[0])
                elif "仿真签到成功" in s[0]:
                    fz_sign_msg.append(s[0])
                elif "签到成功" in s[0]:
                    sign_success_msg.append(s[0])
                elif "已签到" in s[0]:
                    already_sign_msg.append(s[0])
                else:
                    failed_msg.append(s[0])
                    retry_sites.append(str(site_id))

                if site_id:
                    status = re.search(r'【.*】(.*)', s[0]).group(1) or None
                    _result = {'id': site_id, 'date': s[1], 'name': site_names[0], 'signurl': s[2], 'result': status }
                    self.history(key=f"{site_id}_{s[1]}", value=_result)

            if not self._retry_keyword:
                # 没设置重试关键词则重试已选站点
                retry_sites = self._sign_sites
            self.debug(f"下次签到重试站点 {retry_sites}")

            # 存入历史
            if not today_history:
                self.history(key=today,
                             value={
                                 "sign": self._sign_sites,
                                 "retry": retry_sites
                             })
            else:
                self.update_history(key=today,
                                    value={
                                        "sign": self._sign_sites,
                                        "retry": retry_sites
                                    })
            # 清理旧的历史记录（最多保留30天或50条）
            self.clean_old_history(days=30, max_count=50)

            # 触发CF优选
            if self._auto_cf and len(retry_sites) >= (int(self._auto_cf) or 0) > 0:
                # 获取自定义Hosts插件、CF优选插件，判断是否触发优选
                customHosts = self.get_config("CustomHosts")
                cloudflarespeedtest = self.get_config("CloudflareSpeedTest")
                if customHosts and customHosts.get("enable") and cloudflarespeedtest and cloudflarespeedtest.get(
                        "cf_ip"):
                    self.info(f"命中重试数量 {len(retry_sites)}，开始触发优选IP插件")
                    self.eventmanager.send_event(EventType.PluginReload,
                                                 {
                                                     "plugin_id": "CloudflareSpeedTest"
                                                 })
                else:
                    self.info(f"命中重试数量 {len(retry_sites)}，优选IP插件未正确配置，停止触发优选IP")
            # 发送通知
            if self._notify:
                # 签到详细信息 登录成功、签到成功、已签到、仿真签到成功、失败--命中重试
                signin_message = login_success_msg + sign_success_msg + already_sign_msg + fz_sign_msg + failed_msg
                if len(retry_msg) > 0:
                    signin_message.append("——————命中重试—————")
                    signin_message += retry_msg
                Message().send_site_signin_message(signin_message)

                jobs = self._scheduler.get_jobs() if self._scheduler else []
                tz = pytz.timezone(Config().get_timezone())
                now = datetime.now(tz)
                future_jobs = [j for j in jobs if getattr(j, 'next_run_time', None) and j.next_run_time > now]
                sign_jobs = [j for j in future_jobs if getattr(j, 'func', None) is self.sign_in]
                candidate = min(sign_jobs, key=lambda j: j.next_run_time) if sign_jobs else (min(future_jobs, key=lambda j: j.next_run_time) if future_jobs else None)
                next_run_time = candidate.next_run_time.strftime('%Y-%m-%d %H:%M:%S') if candidate else "-"
                # 签到汇总信息
                self.send_message(title="【自动签到任务完成】",
                                  text=f"本次签到数量: {len(sign_sites)} \n"
                                       f"命中重试数量: {len(retry_sites) if self._retry_keyword else 0} \n"
                                       f"强制签到数量: {len(self._special_sites)} \n"
                                       f"下次签到数量: {len(set(retry_sites + self._special_sites))} \n"
                                       f"下次签到时间: {next_run_time} \n"
                                       f"详见签到消息")
        else:
            self.error("站点签到任务失败！")

    def __build_class(self, url):
        for site_schema in self._site_schema:
            try:
                if site_schema.match(url):
                    return site_schema
            except Exception as e:
                ExceptionUtils.exception_traceback(e)
        return None
    
    async def __run_blocking(self, fn):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, fn)

    def signin_site(self, site_info):
        """
        签到一个站点
        """
        signurl = site_info.get("signurl")
        site_module = self.__build_class(signurl)
        home_url = StringUtils.get_base_url(signurl)
        signinTime = datetime.now(tz=pytz.timezone(Config().get_timezone())).strftime('%Y-%m-%d %H:%M:%S')

        if site_module and hasattr(site_module, "signin"):
            try:
                site_instance = site_module()
                if inspect.iscoroutinefunction(site_instance.signin):
                    status, msg = asyncio.run(asyncio.wait_for(site_instance.signin(site_info), timeout=300))
                else:
                    status, msg = asyncio.run(asyncio.wait_for(self.__run_blocking(lambda: site_instance.signin(site_info)), timeout=300))
                # 特殊站点直接返回签到信息，防止仿真签到、模拟登陆有歧义
                return msg, signinTime, home_url
            except asyncio.TimeoutError:
                return f"【{site_info.get('name')}】签到失败：超时", signinTime, home_url
            except Exception as e:
                return f"【{site_info.get('name')}】签到失败：{str(e)}", signinTime, home_url
        else:
            try:
                return asyncio.run(asyncio.wait_for(self.__signin_base(site_info), timeout=300)), signinTime, home_url
            except asyncio.TimeoutError:
                return f"【{site_info.get('name')}】签到失败：超时", signinTime, home_url

    async def __signin_base(self, site_info):
        """
        通用签到处理
        :param site_info: 站点信息
        :return: 签到结果信息
        """
        if not site_info:
            return ""
        site = site_info.get("name")
        chrome = None
        try:
            site_url = site_info.get("signurl")
            site_cookie = site_info.get("cookie")
            site_local_storage = site_info.get("local_storage")
            ua = site_info.get("ua")
            if not site_url or not site_cookie:
                self.warn("未配置 %s 的站点地址或Cookie，无法签到" % str(site))
                return ""
            chrome = ChromeHelper()
            if site_info.get("chrome") and chrome.get_status():
                # 首页
                self.info("开始站点仿真签到：%s" % site)
                home_url = StringUtils.get_base_url(site_url)
                if "1ptba" in home_url:
                    home_url = f"{home_url}/index.php"
                
                # 获取站点域名用于Profile管理
                from urllib.parse import urlparse
                site_domain = urlparse(home_url).netloc
                
                # 首先尝试使用已保存的浏览器数据（preserve_data=True）
                if not await chrome.visit(url=home_url, ua=ua, cookie=site_cookie, local_storage=site_local_storage, 
                                           proxy=site_info.get("proxy"), site_domain=site_domain, preserve_data=True):
                    self.warn("%s 无法打开网站" % site)
                    return f"【{site}】仿真签到失败，无法打开网站！"
                # 循环检测是否过cf
                cloudflare = await chrome.pass_cloudflare()
                if not cloudflare:
                    self.warn("%s 跳转站点失败" % site)
                    return f"【{site}】仿真签到失败，跳转站点失败！"
                logged_in = await SiteHelper.wait_for_logged_in(chrome._tab)
                
                # 如果登录失败，尝试注入新的cookie/localStorage
                if not logged_in:
                    self.debug(f"站点 {site} 使用缓存数据未登录，尝试注入新凭据")
                    if await chrome.inject_credentials(home_url, cookie=site_cookie, local_storage=site_local_storage):
                        logged_in = await SiteHelper.wait_for_logged_in(chrome._tab)
                
                if not logged_in:
                    self.warn("%s 站点未登录" % site)
                    return f"【{site}】仿真签到失败，站点未登录！"
                # 判断是否已签到
                html_text = await chrome.get_html()
                if not html_text:
                    self.warn("%s 获取站点源码失败" % site)
                    return f"【{site}】仿真签到失败，获取站点源码失败！"
                # 查找签到按钮
                html = etree.HTML(html_text)
                xpath_str = None
                for xpath in self.siteconf.get_checkin_conf():
                    if html.xpath(xpath):
                        xpath_str = xpath
                        break
                if re.search(r'已签|签到已得', html_text, re.IGNORECASE):
                    self.info("%s 今日已签到" % site)
                    return f"【{site}】今日已签到"
                if not xpath_str:
                    if SiteHelper.is_logged_in(html_text):
                        self.warn("%s 未找到签到按钮，模拟登录成功" % site)
                        return f"【{site}】模拟登录成功，已签到或无需签到"
                    else:
                        self.info("%s 未找到签到按钮，且模拟登录失败" % site)
                        return f"【{site}】模拟登录失败！"
                # 开始仿真
                try:
                    checkin_obj = await chrome._tab.find(text=xpath_str, timeout=6)
                    if checkin_obj:
                        await checkin_obj.click()
                        # 检测是否过cf
                        await asyncio.sleep(3)
                        try:
                            await asyncio.wait_for(ChromeHelper.check_document_ready(chrome._tab), 20)
                        except asyncio.TimeoutError:
                            self.debug("Timeout waiting for the page")
                        if under_challenge(await chrome.get_html()):
                            cloudflare = await chrome.pass_cloudflare()
                            if not cloudflare:
                                self.info("%s 仿真签到失败，无法通过Cloudflare" % site)
                                return f"【{site}】仿真签到失败，无法通过Cloudflare！"
                        logged_in = await SiteHelper.wait_for_logged_in(chrome._tab)
                        if not logged_in:
                            self.warn("%s 仿真签到失败：未能检测到登录信息" % (site))
                            return f"【{site}】签到失败！"
                        
                        # 二次确认按钮选择器列表
                        confirmation_selectors = [
                            "//input[@type='submit' and @value='立即签到']",
                        ]
                        
                        # 遍历选择器列表，尝试查找并点击存在的确认按钮
                        for selector in confirmation_selectors:
                            try:
                                found, coordinates = await ChromeHelper.find_and_click_element(
                                    tab=chrome._tab, 
                                    selector=selector,
                                    click_enabled=True,
                                    timeout=3
                                )
                                if found:
                                    self.debug(f"{site} 找到并点击了二次确认按钮: {selector}")
                                    # 等待页面响应
                                    await asyncio.sleep(1)
                                    try:
                                        await asyncio.wait_for(ChromeHelper.check_document_ready(chrome._tab), 20)
                                    except asyncio.TimeoutError:
                                        self.debug("Timeout waiting for the page")
                                    break
                            except Exception as e:
                                self.debug(f"{site} 尝试选择器 {selector} 失败: {str(e)}")
                                continue
                        # 判断是否已签到   [签到已得125, 补签卡: 0]
                        if re.search(r'已签|签到已得', await chrome.get_html(), re.IGNORECASE):
                            return f"【{site}】签到成功"
                        self.info("%s 仿真签到成功" % site)
                        return f"【{site}】仿真签到成功"
                except Exception as e:
                    ExceptionUtils.exception_traceback(e)
                    self.warn("%s 仿真签到失败：%s" % (site, str(e)))
                    return f"【{site}】签到失败！"
            # 模拟登录
            else:
                if site_url.find("attendance.php") != -1:
                    checkin_text = "签到"
                else:
                    checkin_text = "模拟登录"
                self.info(f"开始站点{checkin_text}：{site}")
                # 访问链接
                res = RequestUtils(cookies=site_cookie,
                                   headers=ua,
                                   proxies=Config().get_proxies() if site_info.get("proxy") else None
                                   ).get_res(url=site_url)
                if res and res.status_code in [200, 500, 403]:
                    if not SiteHelper.is_logged_in(res.text):
                        if under_challenge(res.text):
                            msg = "站点被Cloudflare防护，请开启浏览器仿真"
                        elif res.status_code == 200:
                            msg = "Cookie已失效"
                        else:
                            msg = f"状态码：{res.status_code}"
                        self.warn(f"{site} {checkin_text}失败，{msg}")
                        return f"【{site}】{checkin_text}失败，{msg}！"
                    else:
                        self.info(f"{site} {checkin_text}成功")
                        return f"【{site}】{checkin_text}成功"
                elif res is not None:
                    self.warn(f"{site} {checkin_text}失败，状态码：{res.status_code}")
                    return f"【{site}】{checkin_text}失败，状态码：{res.status_code}！"
                else:
                    self.warn(f"{site} {checkin_text}失败，无法打开网站")
                    return f"【{site}】{checkin_text}失败，无法打开网站！"
        except Exception as e:
            ExceptionUtils.exception_traceback(e)
            self.warn("%s 签到失败：%s" % (site, str(e)))
            return f"【{site}】签到失败：{str(e)}！"
        finally:
            try:
                if chrome:
                    await chrome.quit()
            except Exception:
                pass

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
            print(str(e))

    def get_state(self):
        return self._enabled and self._cron
