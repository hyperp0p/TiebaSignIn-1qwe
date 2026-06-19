#!/usr/bin/env python3
"""百度贴吧自动签到 - GitHub Actions 入口

用法:
    python run.py                          # 自动读取环境变量 BDUSS
    python run.py --bduss "your_bduss"     # 命令行传入 BDUSS
"""

import argparse
import logging
import os
import random
import time
from urllib.parse import quote

import requests as http_requests

from tieba_client import TiebaClient

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(asctime)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_args() -> str:
    parser = argparse.ArgumentParser(description="百度贴吧自动签到")
    parser.add_argument(
        "--bduss",
        default=None,
        help="贴吧 BDUSS Cookie 值（优先级高于环境变量）",
    )
    args = parser.parse_args()

    bduss = args.bduss or os.environ.get("BDUSS", "")
    if not bduss:
        parser.error("请通过 --bduss 参数或 BDUSS 环境变量提供 BDUSS")
    return bduss


def send_bark(
    title: str,
    body: str,
    level: str = "active",
    sound: str = "",
    group: str = "贴吧签到",
) -> None:
    """通过 Bark 推送签到结果到 iOS

    level:
        active        - 默认，跟随系统设置
        timeSensitive - 绕过静音模式
        critical      - 强制响铃（即使勿扰/静音）
    """
    bark_key = os.environ.get("BARK_KEY", "")
    if not bark_key:
        logger.info("未配置 BARK_KEY，跳过推送")
        return

    server = os.environ.get("BARK_SERVER", "https://api.day.app")
    if not server:
        server = "https://api.day.app"
    server = server.rstrip("/")
    if not server.startswith(("http://", "https://")):
        logger.error(f"BARK_SERVER 无效: {server}，跳过推送")
        return
    url = f"{server}/{bark_key.strip('/')}/{quote(title)}/{quote(body)}"

    params: dict = {"group": group, "level": level}
    if sound:
        params["sound"] = sound

    try:
        resp = http_requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") == 200:
            logger.info(f"Bark 推送成功 (level={level})")
        else:
            logger.warning(f"Bark 推送返回: {data}")
    except Exception as e:
        logger.error(f"Bark 推送失败: {e}")


def main() -> None:
    bduss = parse_args()
    client = TiebaClient(bduss)

    # 1. 获取 tbs
    logger.info("正在获取 tbs...")
    tbs = client.get_tbs()
    if tbs is None:
        logger.error("获取 tbs 失败，退出")
        send_bark("贴吧签到", "❌ 获取 tbs 失败，签到未执行", level="critical", sound="alarm")
        raise SystemExit(1)

    # 2. 获取关注的贴吧列表
    logger.info("正在获取关注的贴吧列表...")
    forums = client.get_favorites()
    if not forums:
        logger.warning("未获取到关注的贴吧，签到结束")
        send_bark("贴吧签到", "⚠️ 未获取到关注的贴吧", level="critical", sound="alarm")
        return

    # 3. 逐个签到 (带节流)
    total = len(forums)
    logger.info(f"开始签到 {total} 个贴吧")

    stats = {"success": 0, "exist": 0, "shield": 0, "error": 0}
    failed_forums = []
    for idx, forum in enumerate(forums):
        # 节流: 随机间隔 1.0-2.5 秒
        delay = random.uniform(1.0, 2.5)
        time.sleep(delay)

        # 每 10 个贴吧额外休息 5-10 秒
        if (idx + 1) % 10 == 0:
            extra = random.uniform(5, 10)
            logger.info(f"已签到 {idx + 1}/{total} 个，休息 {extra:.1f}s ...")
            time.sleep(extra)

        fid = forum.get("id", "")
        fname = forum.get("name", "")
        result = client.sign_forum(fid, fname, tbs)
        stats[result["status"]] += 1

        # 打印单条结果
        prefix = f"【{fname}】({idx + 1}/{total})"
        if result["status"] == "success":
            rank_str = f"，第 {result['rank']} 个签到" if result["rank"] else ""
            logger.info(f"{prefix} 签到成功{rank_str}")
        elif result["status"] == "exist":
            logger.info(f"{prefix} {result['message']}")
        elif result["status"] == "shield":
            logger.warning(f"{prefix} {result['message']}")
        else:
            logger.error(f"{prefix} 签到失败: {result['message']}")
            failed_forums.append(fname)

    # 4. 汇总
    summary = (
        f"\n========== 签到汇总 ==========\n"
        f"贴吧总数: {total}\n"
        f"签到成功: {stats['success']}\n"
        f"已经签到: {stats['exist']}\n"
        f"被屏蔽的: {stats['shield']}\n"
        f"签到失败: {stats['error']}\n"
        f"================================"
    )
    logger.info(summary)

    # 5. Bark 推送
    bark_title = "贴吧签到"
    if stats["error"] > 0:
        bark_body = (
            f"⚠️ 签到完成，有失败\n"
            f"成功:{stats['success']} 已签:{stats['exist']} "
            f"屏蔽:{stats['shield']} 失败:{stats['error']}"
        )
        if failed_forums:
            bark_body += f"\n失败贴吧: {'、'.join(failed_forums)}"
        send_bark(bark_title, bark_body, level="timeSensitive", sound="bell")
    else:
        bark_body = (
            f"✅ 全部完成\n"
            f"成功:{stats['success']} 已签:{stats['exist']} 屏蔽:{stats['shield']}"
        )
        send_bark(bark_title, bark_body, level="active")


if __name__ == "__main__":
    main()
