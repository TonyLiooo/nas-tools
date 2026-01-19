# -*- coding: utf-8 -*-
"""
feapder TailThread 卡死问题修复补丁
在不修改 feapder 源码的前提下，通过 monkey patch 修复 TailThread.start() 的阻塞问题
"""
import sys
import threading


def patch_tail_thread():
    """
    修复 feapder.utils.tail_thread.TailThread.start() 的阻塞问题
    
    问题：TailThread.start() 会 join 所有非守护线程，导致与 selenium/渲染线程互等卡死
    方案：移除全局线程 join，仅保留父类 threading.Thread.start() 的正常行为
    """
    try:
        # 延迟导入，确保 feapder 已加载
        from feapder.utils import tail_thread
        
        if hasattr(tail_thread, 'TailThread'):
            # 检查是否已经 patch 过（避免重复 patch）
            if hasattr(tail_thread.TailThread.start, '_feapder_patched'):
                return True
            
            original_start = tail_thread.TailThread.start
            
            def patched_start(self):
                """
                修复后的 start 方法：不执行全局线程 join，避免卡死
                原逻辑会在 Python 3.12+ 时 join 所有非守护线程，导致卡死
                """
                # 仅调用父类 threading.Thread.start()，不执行全局 join
                super(tail_thread.TailThread, self).start()
                # 移除原逻辑中的全局线程 join，避免阻塞
            
            # 标记已 patch
            patched_start._feapder_patched = True
            tail_thread.TailThread.start = patched_start
            return True
    except (ImportError, AttributeError):
        # feapder 未安装或版本不匹配，忽略
        return False


def apply_feapder_patches():
    """
    应用所有 feapder 相关补丁
    注意：此函数应在导入 feapder 相关模块之前调用，或在首次使用 feapder 前调用
    """
    patched = patch_tail_thread()
    return patched


