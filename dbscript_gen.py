"""
生成数据库迁移脚本。使用前请确保数据库已更新到当前 head（先执行 alembic upgrade head）。
可交互输入版本号，或通过参数传入：python dbscript_gen.py 1_3_7
"""
import os
import sys
from config import Config
from alembic.config import Config as AlembicConfig
from alembic.command import revision as alembic_revision

db_version = sys.argv[1] if len(sys.argv) > 1 else input("请输入版本号：")
db_location = os.path.join(Config().get_config_path(), 'user.db').replace('\\', '/')
script_location = os.path.join(os.path.dirname(__file__), 'scripts').replace('\\', '/')
alembic_cfg = AlembicConfig()
alembic_cfg.set_main_option('script_location', script_location)
alembic_cfg.set_main_option('sqlalchemy.url', f"sqlite:///{db_location}")
alembic_revision(alembic_cfg, db_version, True)
