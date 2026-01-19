import datetime
import random
import re
from apscheduler.triggers.cron import CronTrigger
from apscheduler.util import undefined

import math

import log


class SchedulerUtils:

    @staticmethod
    def start_job(scheduler, func, func_desc, cron, next_run_time=undefined):
        """
        解析任务的定时规则,启动定时服务
        :param func: 可调用的一个函数,在指定时间运行
        :param func_desc: 函数的描述,在日志中提现
        :param cron 时间表达式 三种配置方法：
        :param next_run_time: 下次运行时间
          1、配置cron表达式，只支持5位的cron表达式
          2、配置时间范围，如08:00-09:00，表示在该时间范围内随机执行一次；
          3、配置固定时间，如08:00；
          4、配置间隔，单位小时，比如23.5；
        """
        if not cron:
            return
            
        cron = cron.strip()
        
        # 1. 配置cron表达式
        if cron.count(" ") == 4:
            try:
                scheduler.add_job(func=func,
                                  trigger=CronTrigger.from_crontab(cron),
                                  next_run_time=next_run_time)
                log.info("%s时间cron表达式配置成功：%s" % (func_desc, cron))
            except Exception as e:
                log.info("%s时间cron表达式配置格式错误：%s %s" % (func_desc, cron, str(e)))
        
        # 2. 配置时间范围（随机执行模式，链式调度）
        elif '-' in cron:
            try:
                time_range = cron.split("-")
                start_time_range_array = time_range[0].split(":")
                end_time_range_array = time_range[1].split(":")
                
                start_hour = int(start_time_range_array[0])
                start_minute = int(start_time_range_array[1])
                end_hour = int(end_time_range_array[0])
                end_minute = int(end_time_range_array[1])
                
                # 生成任务ID（用于去重）
                job_id_base = re.sub(r'[^\w]', '_', func_desc)
                
                log.info("%s 服务时间范围随机模式启动（%s:%s-%s:%s）" % (
                    func_desc, 
                    str(start_hour).zfill(2), str(start_minute).zfill(2),
                    str(end_hour).zfill(2), str(end_minute).zfill(2)))

                # 启动时根据当前时间安排任务
                tz = getattr(scheduler, 'timezone', None)
                now = datetime.datetime.now(tz) if tz else datetime.datetime.now()
                start_dt = now.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
                end_dt = now.replace(hour=end_hour, minute=end_minute, second=59, microsecond=0)

                # 如果当前时间在范围内，安排今天的任务（从现在到结束时间内随机）
                if start_dt <= now <= end_dt:
                    now_minutes = now.hour * 60 + now.minute
                    end_minutes = end_hour * 60 + end_minute
                    if now_minutes <= end_minutes:
                        task_time_count = random.randint(now_minutes, end_minutes)
                        SchedulerUtils._schedule_task(
                            scheduler, func, func_desc,
                            now, math.floor(task_time_count / 60), task_time_count % 60,
                            start_hour, start_minute, end_hour, end_minute, job_id_base, tz)
                
                # 如果今天时间已过，安排明天的任务
                elif now > end_dt:
                    SchedulerUtils._schedule_next_day_task(
                        scheduler, func, func_desc,
                        start_hour, start_minute, end_hour, end_minute, job_id_base, tz)
                
                # 如果当前时间在范围开始之前，安排今天的任务
                else:
                    task_time_count = random.randint(start_hour * 60 + start_minute, end_hour * 60 + end_minute)
                    SchedulerUtils._schedule_task(
                        scheduler, func, func_desc,
                        now, math.floor(task_time_count / 60), task_time_count % 60,
                        start_hour, start_minute, end_hour, end_minute, job_id_base, tz)

            except Exception as e:
                log.info("%s时间 时间范围随机模式 配置格式错误：%s %s" % (func_desc, cron, str(e)))

        # 3. 配置固定时间
        elif cron.find(':') != -1:
            try:
                hour = int(cron.split(":")[0])
                minute = int(cron.split(":")[1])
                scheduler.add_job(func,
                                  "cron",
                                  hour=hour,
                                  minute=minute,
                                  next_run_time=next_run_time)
                log.info("%s服务启动" % func_desc)
            except Exception as e:
                log.info("%s时间 配置格式错误：%s" % (func_desc, str(e)))

        # 4. 配置间隔
        else:
            try:
                hours = float(cron)
                if hours:
                    scheduler.add_job(func,
                                      "interval",
                                      hours=hours,
                                      next_run_time=next_run_time)
                    log.info("%s服务启动" % func_desc)
            except Exception as e:
                log.info("%s时间 配置格式错误：%s" % (func_desc, str(e)))
                
    @staticmethod
    def _schedule_task(scheduler, func, func_desc, base_date, hour, minute,
                       start_hour, start_minute, end_hour, end_minute, job_id_base, tz):
        """
        安排指定日期的任务，并在任务执行后自动安排明天的任务
        """
        second = random.randint(1, 59)
        
        # 边界检查
        if hour < 0 or hour >= 24:
            hour = 0
        if minute < 0 or minute >= 60:
            minute = 0
        
        now = datetime.datetime.now(tz) if tz else datetime.datetime.now()
        run_date = base_date.replace(hour=int(hour), minute=int(minute), second=second, microsecond=0)
        if tz and run_date.tzinfo is None:
            run_date = run_date.replace(tzinfo=tz)
        
        # 如果时间已过，立即执行
        if run_date <= now:
            run_date = now + datetime.timedelta(seconds=5)
        
        # 生成唯一任务ID（基于日期），相同日期的任务会被替换
        job_id = f"{job_id_base}_{run_date.strftime('%Y%m%d')}"
        
        # 创建包装函数：执行原任务后安排明天的任务
        def wrapped_func():
            try:
                func()
            finally:
                try:
                    SchedulerUtils._schedule_next_day_task(
                        scheduler, func, func_desc,
                        start_hour, start_minute, end_hour, end_minute, job_id_base, tz)
                except Exception as e:
                    log.debug("%s 安排明日任务失败：%s" % (func_desc, str(e)))
        
        try:
            scheduler.add_job(wrapped_func, "date", run_date=run_date, 
                              id=job_id, replace_existing=True)
            log.info("%s 已安排执行：%s" % (func_desc, run_date.strftime('%Y-%m-%d %H:%M:%S')))
        except Exception as e:
            log.info("%s 安排任务出错：%s" % (func_desc, str(e)))
    
    @staticmethod
    def _schedule_next_day_task(scheduler, func, func_desc, 
                                start_hour, start_minute, end_hour, end_minute, job_id_base, tz):
        """
        安排明天的随机任务
        """
        now = datetime.datetime.now(tz) if tz else datetime.datetime.now()
        tomorrow = now + datetime.timedelta(days=1)
        
        task_time_count = random.randint(start_hour * 60 + start_minute, end_hour * 60 + end_minute)
        hour = math.floor(task_time_count / 60)
        minute = task_time_count % 60
        
        SchedulerUtils._schedule_task(
            scheduler, func, func_desc,
            tomorrow, hour, minute,
            start_hour, start_minute, end_hour, end_minute, job_id_base, tz)

    @staticmethod
    def start_range_job(scheduler, func, func_desc, hour, minute):
        """
        安排一个具体时间点的一次性任务（保留兼容性）
        """
        tz = getattr(scheduler, 'timezone', None)
        now = datetime.datetime.now(tz) if tz else datetime.datetime.now()
        
        second = random.randint(1, 59)
        
        # 边界检查
        if hour < 0 or hour >= 24:
            hour = 0
        if minute < 0 or minute >= 60:
            minute = 0
            
        try:
            run_date = datetime.datetime(now.year, now.month, now.day, int(hour), int(minute), int(second))
            if tz and run_date.tzinfo is None:
                run_date = run_date.replace(tzinfo=tz)
            
            if run_date <= now:
                run_date = now + datetime.timedelta(seconds=5)
            
            log.info("%s 已安排执行时间：%s" % (func_desc, run_date.strftime('%Y-%m-%d %H:%M:%S')))
            scheduler.add_job(func, "date", run_date=run_date)
        except Exception as e:
            log.info("%s 安排随机执行时间出错：%s" % (func_desc, str(e)))
