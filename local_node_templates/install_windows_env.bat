@echo off
chcp 65001 >nul
title 量化系统本地节点环境部署工具
echo ==========================================
echo 正在为您安装本地 Python 依赖...
echo ⚠️ 提示: xtquant 库目前最高仅支持 Python 3.11 版本，请确保您的 Python 版本符合要求。
echo ==========================================
pip install redis easytrader pywinauto xtquant -i https://pypi.tuna.tsinghua.edu.cn/simple
echo.
echo ✅ 依赖安装尝试完成！
echo 若 xtquant 安装失败，请降低您的 Python 版本至 3.11 并重试。
pause
