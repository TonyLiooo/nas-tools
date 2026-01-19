import os
import threading
import sqlite3
import time
from sqlalchemy import create_engine, text, inspect, event
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.pool import NullPool
from sqlalchemy.exc import OperationalError

from app.db.models import Base
from app.utils import ExceptionUtils, PathUtils
from config import Config

lock = threading.Lock()
_Engine = create_engine(
    f"sqlite:///{os.path.join(Config().get_config_path(), 'user.db')}",
    echo=False,
    poolclass=NullPool,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False, "timeout": 30}
)
_Session = scoped_session(sessionmaker(bind=_Engine,
                                       autoflush=True,
                                       autocommit=False,
                                       expire_on_commit=False))


@event.listens_for(_Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA synchronous=NORMAL;")
    cursor.execute("PRAGMA busy_timeout=30000;")
    cursor.execute("PRAGMA foreign_keys=ON;")
    cursor.close()


class MainDb:

    @property
    def session(self):
        return _Session()

    def init_db(self):
        with lock:
            Base.metadata.create_all(_Engine)
            self.init_db_version()

    def init_db_version(self):
        """
        初始化数据库版本
        """
        try:
            if self.table_exists("alembic_version"):
                self.excute("delete from alembic_version where 1")
                self.commit()
        except Exception as err:
            print(str(err))

    def init_data(self):
        """
        读取config目录下的sql文件，并初始化到数据库，只处理一次
        """
        config = Config().get_config()
        init_files = Config().get_config("app").get("init_files") or []
        config_dir = Config().get_script_path()
        sql_files = PathUtils.get_dir_level1_files(in_path=config_dir, exts=".sql")
        config_flag = False
        for sql_file in sql_files:
            if os.path.basename(sql_file) not in init_files:
                config_flag = True
                with open(sql_file, "r", encoding="utf-8") as f:
                    sql_list = f.read().split(';\n')
                    for sql in sql_list:
                        try:
                            self.excute(sql)
                            self.commit()
                        except Exception as err:
                            print(str(err))
                init_files.append(os.path.basename(sql_file))
        if config_flag:
            config['app']['init_files'] = init_files
            Config().save_config(config)

    def insert(self, data):
        """
        插入数据
        """
        if isinstance(data, list):
            self.session.add_all(data)
        else:
            self.session.add(data)

    def table_exists(self, table_name):
        """
        检查指定的表是否存在
        """
        inspector = inspect(_Engine)
        return inspector.has_table(table_name)

    def query(self, *obj):
        """
        查询对象
        """
        return self.session.query(*obj)

    def excute(self, sql):
        """
        执行SQL语句
        """
        self.session.execute(text(sql))

    def flush(self):
        """
        刷写
        """
        self.session.flush()

    def commit(self, retries=5, backoff=0.1):
        """
        提交事务（在数据库锁冲突时重试）
        """
        last_exc = None
        for i in range(retries):
            try:
                self.session.commit()
                return
            except OperationalError as e:
                msg = str(getattr(e, "orig", e))
                if "database is locked" in msg or "database is busy" in msg:
                    self.session.rollback()
                    time.sleep(backoff * (2 ** i))
                    last_exc = e
                    continue
                raise
        if last_exc:
            raise last_exc

    def rollback(self):
        """
        回滚事务
        """
        self.session.rollback()


class DbPersist(object):
    """
    数据库持久化装饰器
    """

    def __init__(self, db):
        self.db = db

    def __call__(self, f):
        def persist(*args, **kwargs):
            try:
                ret = f(*args, **kwargs)
                self.db.commit()
                return True if ret is None else ret
            except Exception as e:
                ExceptionUtils.exception_traceback(e)
                self.db.rollback()
                return False

        return persist


def remove_session():
    _Session.remove()
