from datetime import datetime

class TimeUtils:
    @staticmethod
    def time_difference(last_seen_str):
        """
        计算给定时间与当前时间的差异，并以“x天x时x分前”的形式返回。
        如果时间差较短，返回“刚刚”或“几秒前”。
        """
        try:
            if not last_seen_str or not isinstance(last_seen_str, str):
                return ""

            # 将时间字符串解析为 datetime 对象
            last_seen = datetime.strptime(last_seen_str, "%Y-%m-%d %H:%M:%S")
            current_time = datetime.now()

            # 计算时间差
            time_diff = current_time - last_seen

            # 获取时间差的秒数
            total_seconds = time_diff.total_seconds()

            # 根据秒数返回更友好的时间格式
            if total_seconds < 60:
                return "刚刚" if total_seconds < 10 else f"{int(total_seconds)}秒前"
            elif total_seconds < 3600:
                minutes = int(total_seconds // 60)
                return f"{minutes}分前"
            elif total_seconds < 86400:
                hours = int(total_seconds // 3600)
                minutes = int((total_seconds % 3600) // 60)
                return f"{hours}时{minutes}分前" if minutes > 0 else f"{hours}时前"
            else:
                days = time_diff.days
                hours = int((total_seconds % 86400) // 3600)
                return f"{days}天{hours}时前" if hours > 0 else f"{days}天前"
        except:
            return ''

    @staticmethod
    def less_than_days(date_str, target_days):
        """
        小于三十天
        """
        try:
            if not date_str or not isinstance(date_str, str):
                return False
                
            # 将时间字符串解析为 datetime 对象
            last_seen = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
            current_time = datetime.now()

            # 计算时间差
            time_diff = current_time - last_seen

            # 获取天、小时和分钟
            days = time_diff.days

            if days > target_days:
                return False
            else:
                return True
        except:
            return False
