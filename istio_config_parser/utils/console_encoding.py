# -*- coding: utf-8 -*-
"""
控制台输出编码修复
解决 Windows 下中文乱码问题，强制 stdout/stderr 使用 UTF-8
"""
import sys


def fix_console_encoding() -> None:
    """
    在 Windows 下将 stdout/stderr 设置为 UTF-8，避免中文乱码
    应在程序入口最早调用
    """
    if sys.platform != 'win32':
        return
    try:
        # Python 3.7+
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        if hasattr(sys.stderr, 'reconfigure'):
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
