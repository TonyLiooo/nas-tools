import os
import socket
import signal
import subprocess

import log
from app.utils import SystemUtils

_DEFAULT_PORT = 6379


class RedisHelper:

    _actual_port = None

    @staticmethod
    def get_port():
        """
        获取当前 Redis 端口：优先使用运行时确定的端口，否则从配置读取
        """
        if RedisHelper._actual_port:
            return RedisHelper._actual_port
        try:
            from config import Config
            port = Config().get_config('app').get('redis_port')
            if port and str(port).isdigit():
                return int(port)
        except Exception:
            pass
        return _DEFAULT_PORT

    @staticmethod
    def is_port_available(port, exclude_redis=True):
        """
        检测端口是否可用
        :param port: 端口号
        :param exclude_redis: 为True时，如果端口被自身redis-server占用则视为可用
        """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                result = s.connect_ex(('127.0.0.1', port))
                if result != 0:
                    return True
                if exclude_redis and RedisHelper._is_redis_on_port(port):
                    return True
                return False
        except Exception:
            return True

    @staticmethod
    def _is_redis_on_port(port):
        """
        检查指定端口上运行的是否是自身的 redis-server
        """
        try:
            import psutil
            for conn in psutil.net_connections(kind='tcp'):
                if conn.laddr.port == port and conn.status == 'LISTEN':
                    try:
                        proc = psutil.Process(conn.pid)
                        if 'redis-server' in proc.name().lower():
                            return True
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
            return False
        except Exception:
            return False

    @staticmethod
    def find_free_port(preferred=_DEFAULT_PORT):
        """
        找到可用端口：优先使用 preferred，若被占用则由操作系统分配随机空闲端口
        """
        if RedisHelper.is_port_available(preferred, exclude_redis=False):
            return preferred
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('127.0.0.1', 0))
                port = s.getsockname()[1]
                return port
        except Exception:
            return preferred

    @staticmethod
    def _save_port_to_config(port):
        """
        将实际端口写回 config.yaml
        """
        try:
            from config import Config
            cfg = Config().get_config()
            if not cfg.get('app'):
                cfg['app'] = {}
            cfg['app']['redis_port'] = port
            Config().save_config(cfg)
        except Exception as e:
            log.error(f"保存 Redis 端口到配置失败: {e}")

    @staticmethod
    def _kill_redis():
        """
        终止当前运行的 redis-server 进程
        """
        try:
            import psutil
            for proc in psutil.process_iter(['pid', 'name']):
                if 'redis-server' in (proc.info.get('name') or '').lower():
                    try:
                        proc.terminate()
                        proc.wait(timeout=5)
                    except psutil.TimeoutExpired:
                        proc.kill()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
        except Exception:
            try:
                os.system("pkill -f redis-server")
            except Exception:
                pass

    @staticmethod
    def restart_redis(port):
        """
        在指定端口重启 Redis
        Docker 环境下杀掉进程后 s6 自动重启（s6 会从 config 读取新端口）
        非 Docker 环境下用 subprocess 启动
        """
        RedisHelper._kill_redis()

        if SystemUtils.is_docker():
            # Docker 中 s6 会自动重启 svc-redis，run 脚本会从 config 读取端口
            pass
        else:
            redis_bin = SystemUtils.execute("which redis-server")
            if redis_bin:
                redis_bin = redis_bin.strip()
                try:
                    subprocess.Popen(
                        [redis_bin, '--port', str(port), '--daemonize', 'yes'],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                except Exception as e:
                    log.error(f"启动 redis-server 失败: {e}")

    @staticmethod
    def validate_and_apply(port):
        """
        校验端口并应用：冲突时自动切换到空闲端口，重启 Redis，更新配置
        :param port: 用户期望的端口
        :return: (actual_port, message) actual_port为实际使用的端口，message为提示信息（无问题时为空）
        """
        if not str(port).isdigit():
            port = _DEFAULT_PORT
        port = int(port)

        if port < 1024 or port > 65535:
            port = _DEFAULT_PORT

        current_port = RedisHelper.get_port()
        msg = ""

        if RedisHelper.is_port_available(port, exclude_redis=True):
            actual_port = port
        else:
            actual_port = RedisHelper.find_free_port(port)
            if actual_port != port:
                msg = f"Redis端口 {port} 被占用，已自动切换到 {actual_port}"
                log.warn(f"【Redis】{msg}")

        RedisHelper._actual_port = actual_port
        RedisHelper._save_port_to_config(actual_port)

        if actual_port != current_port:
            RedisHelper.restart_redis(actual_port)

        return actual_port, msg

    @staticmethod
    def ensure_redis():
        """
        确保 Redis 正在运行，启动时调用
        如果配置端口冲突则自动切换
        """
        port = RedisHelper.get_port()

        if RedisHelper._is_redis_on_port(port):
            RedisHelper._actual_port = port
            return port

        if not RedisHelper.is_port_available(port, exclude_redis=False):
            old_port = port
            port = RedisHelper.find_free_port(port)
            if port != old_port:
                log.warn(f"【Redis】配置端口 {old_port} 被占用，自动切换到 {port}")
                RedisHelper._save_port_to_config(port)

        RedisHelper._actual_port = port
        return port

    @staticmethod
    def is_valid():
        """
        判断 Redis 是否可用
        """
        if SystemUtils.is_docker():
            if not SystemUtils.execute("which redis-server"):
                return False
            port = RedisHelper.get_port()
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(2)
                    return s.connect_ex(('127.0.0.1', port)) == 0
            except Exception:
                return False
        else:
            return False
