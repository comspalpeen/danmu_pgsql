# 项目环境与运行说明

## 1. 运行环境设置 (Virtual Environment)
该项目使用了独立的 Python 虚拟环境，以避免和系统全局包产生冲突。
虚拟环境绝对路径为：

```
/www/server/pyporject_evn/danmu_pgsql_venv
```

**请勿使用全局 `python3` 或 `pip` 命令执行项目或者安装包。** 每次执行脚本或安装包时，必须使用当前虚拟环境。

## 2. 如何启动项目
如果你要在终端手动启动项目，请先激活虚拟环境：
```bash
# 1. 激活虚拟环境
source /www/server/pyporject_evn/danmu_pgsql_venv/bin/activate

# 2. 运行主程序
cd /www/danmu_pgsql/
python main.py
```
或者直接使用绝对路径执行：
```bash
/www/server/pyporject_evn/danmu_pgsql_venv/bin/python /www/danmu_pgsql/main.py
```

## 3. 如何安装新依赖
如果项目后续需要增加新的依赖包：
正确执行方式：
```bash
/www/server/pyporject_evn/danmu_pgsql_venv/bin/pip install 包名
```
*切记不要直接使用 `pip install` 导致装错位置！*

## 4. 给 AI 助手的特别声明
如果是 AI 助手/Agent 需要使用包管理器或执行 Python 测试，**必须读取本文件**作为前置条件！
**CRITICAL FOR AI:** DO NOT use global `python3` or `pip`. Always use `/www/server/pyporject_evn/danmu_pgsql_venv/bin/python` or `/www/server/pyporject_evn/danmu_pgsql_venv/bin/pip` when executing code.
