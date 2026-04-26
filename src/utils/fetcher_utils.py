# fetcher_utils.py
import codecs
import hashlib
import random
import string
import subprocess
import urllib.parse
from unittest.mock import patch
from contextlib import contextmanager
import threading
from src.utils.ac_signature import get__ac_signature
import os
import py_mini_racer 
if hasattr(py_mini_racer, 'MiniRacer'):
    MiniRacer = py_mini_racer.MiniRacer
import logging

logger = logging.getLogger("Utils")

_thread_local = threading.local()

def get_js_context(abogus_file_path='js/a_bogus.js'):
    """获取当前线程专属的 V8 引擎上下文"""
    # 如果当前线程还没有引擎，就初始化一个
    if not hasattr(_thread_local, 'ctx'):
        ctx = py_mini_racer.MiniRacer()
        if os.path.exists(abogus_file_path):
            with open(abogus_file_path, 'r', encoding='utf-8') as f:
                ctx.eval(f.read())
        _thread_local.ctx = ctx
    
    return _thread_local.ctx
def get_global_js_context(abogus_file_path='js/a_bogus.js'):
    """获取全局单例的 JS 环境，避免每次重复拉起 V8 引擎"""
    global _GLOBAL_JS_CTX
    if _GLOBAL_JS_CTX is None:
        _GLOBAL_JS_CTX = py_mini_racer.MiniRacer()
        if os.path.exists(abogus_file_path):
            with open(abogus_file_path, 'r', encoding='utf-8') as f:
                _GLOBAL_JS_CTX.eval(f.read())
        else:
            # 如果文件不存在，给个提示但不让程序崩溃
            pass
    return _GLOBAL_JS_CTX


@contextmanager
def patched_popen_encoding(encoding='utf-8'):
    original_popen_init = subprocess.Popen.__init__
    def new_popen_init(self, *args, **kwargs):
        kwargs['encoding'] = encoding
        original_popen_init(self, *args, **kwargs)
    with patch.object(subprocess.Popen, '__init__', new_popen_init):
        yield

def generateSignature(wss, script_file='js/sign.js'):
    params = ("live_id,aid,version_code,webcast_sdk_version,"
              "room_id,sub_room_id,sub_channel_id,did_rule,"
              "user_unique_id,device_platform,device_type,ac,"
              "identity").split(',')
    wss_params = urllib.parse.urlparse(wss).query.split('&')
    wss_maps = {i.split('=')[0]: i.split("=")[-1] for i in wss_params}
    tpl_params = [f"{i}={wss_maps.get(i, '')}" for i in params]
    param = ','.join(tpl_params)
    
    md5 = hashlib.md5()
    md5.update(param.encode())
    md5_param = md5.hexdigest()
    
    with codecs.open(script_file, 'r', encoding='utf8') as f:
        script = f.read()
    
    # 注意: MiniRacer 是同步的，如果并发极高可能会轻微阻塞 EventLoop
    # 但签名生成频率低，通常可以接受。
    ctx = MiniRacer()
    ctx.eval(script)
    try:
        signature = ctx.call("get_sign", md5_param)
        return signature
    except Exception as e:
        logger.error(f"签名生成失败: {e}")
        return ""

def generateMsToken(length=182):
    random_str = ''
    base_str = string.ascii_letters + string.digits + '-_'
    _len = len(base_str) - 1
    for _ in range(length):
        random_str += base_str[random.randint(0, _len)]
    return random_str

def get_safe_url(icon_obj):
    try:
        # 兼容字典访问和对象属性访问
        if isinstance(icon_obj, dict):
            url_list = icon_obj.get('url_list_list') or icon_obj.get('url_list')
            if url_list: return url_list[0]
        else:
            if hasattr(icon_obj, 'url_list_list') and icon_obj.url_list_list:
                return icon_obj.url_list_list[0]
            elif hasattr(icon_obj, 'url_list') and icon_obj.url_list:
                 return icon_obj.url_list[0]
    except:
        pass
    return ""

def get_ac_signature(host_part, nonce, user_agent):
    """
    包装原始的 ac_signature 调用
    """
    try:
        return get__ac_signature(host_part, nonce, user_agent)
    except Exception as e:
        logger.error(f"ac_signature 计算错误: {e}")
        return ""
def extract_filename(url: str) -> str:
    """
    提取 URL 中的纯文件名，用于给数据库瘦身。
    例如: https://.../fansclub_new_badge.png~tplv-obj.image -> fansclub_new_badge.png
    """
    if not url:
        return ""
    try:
        # 1. 先去掉波浪号及后面的抖音图片处理参数，以及可能存在的问号查询参数
        base_url = url.split('~')[0].split('?')[0]
        # 2. 以斜杠分割，取最后一部分作为文件名
        filename = base_url.split('/')[-1]
        return filename
    except Exception:
        return ""