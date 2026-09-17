from __future__ import annotations

import argparse
import json
import os
import smtplib
import ssl
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any


VILLAGE_API = "https://www.szajyy.com/app-api/sail-activity/village-list"
BUILDING_API = "https://www.szajyy.com/app-api/sail-village/building-list"
SHANGHAI_TZ = timezone(timedelta(hours=8))
ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "config.json"
DEFAULT_STATE = ROOT / "data" / "state.json"
DEFAULT_ENV = ROOT / ".env"


def now_shanghai() -> datetime:
    return datetime.now(SHANGHAI_TZ)


def request_json(url: str, params: dict[str, Any], timeout: int) -> dict[str, Any]:
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{url}?{query}",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "tenant-id": "1",
            "User-Agent": "shen-meng-yangfan-watch/1.0",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("code") != 0:
        raise RuntimeError(f"接口返回异常：{payload.get('msg') or payload}")
    return payload


def fetch_villages(timeout: int) -> list[dict[str, Any]]:
    payload = request_json(
        VILLAGE_API,
        {"pageNo": 1, "pageSize": 100},
        timeout,
    )
    data = payload.get("data") or {}
    rows = data.get("list")
    total = int(data.get("total") or 0)
    if not isinstance(rows, list):
        raise RuntimeError("房源列表格式异常")
    if total and len(rows) < total:
        raise RuntimeError(f"房源列表不完整：返回 {len(rows)} 条，应有 {total} 条")
    return rows


def fetch_buildings(village_id: str, timeout: int) -> list[dict[str, Any]]:
    payload = request_json(BUILDING_API, {"villageId": village_id}, timeout)
    rows = payload.get("data") or []
    if not isinstance(rows, list):
        raise RuntimeError(f"社区 {village_id} 的楼栋列表格式异常")
    return rows


def normalize_villages(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        village_id = str(row.get("villageId") or "").strip()
        if not village_id:
            continue
        result[village_id] = {
            "name": str(row.get("villageName") or ""),
            "district": str(row.get("districtName") or ""),
            "street": str(row.get("streetName") or ""),
            "remaining": int(row.get("totalRemainingQuota") or 0),
            "full_rented": bool(row.get("fullRented")),
            "window_active": bool(row.get("windowActive")),
        }
    return result


def compare_villages(
    old: dict[str, dict[str, Any]], new: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for village_id in sorted(new.keys() - old.keys()):
        changes.append(
            {
                "type": "community_added",
                "village_id": village_id,
                "name": new[village_id]["name"],
                "new": new[village_id],
            }
        )
    for village_id in sorted(old.keys() - new.keys()):
        changes.append(
            {
                "type": "community_removed",
                "village_id": village_id,
                "name": old[village_id]["name"],
                "old": old[village_id],
            }
        )
    for village_id in sorted(old.keys() & new.keys()):
        before = old[village_id]
        after = new[village_id]
        if before["remaining"] != after["remaining"]:
            delta = after["remaining"] - before["remaining"]
            changes.append(
                {
                    "type": "inventory_increased" if delta > 0 else "inventory_decreased",
                    "village_id": village_id,
                    "name": after["name"],
                    "district": after["district"],
                    "street": after["street"],
                    "old_remaining": before["remaining"],
                    "new_remaining": after["remaining"],
                    "delta": delta,
                }
            )
        if before["full_rented"] != after["full_rented"]:
            changes.append(
                {
                    "type": "full_rented_changed",
                    "village_id": village_id,
                    "name": after["name"],
                    "old": before["full_rented"],
                    "new": after["full_rented"],
                }
            )
        if before["window_active"] != after["window_active"]:
            changes.append(
                {
                    "type": "window_active_changed",
                    "village_id": village_id,
                    "name": after["name"],
                    "old": before["window_active"],
                    "new": after["window_active"],
                }
            )
    return changes


def watched_alert_ids(
    changes: list[dict[str, Any]],
    villages: dict[str, dict[str, Any]],
    watched_districts: set[str],
) -> list[str]:
    matched: set[str] = set()
    for change in changes:
        village_id = str(change.get("village_id") or "")
        current = villages.get(village_id)
        if not current or current["district"] not in watched_districts:
            continue
        change_type = change.get("type")
        if change_type == "inventory_increased" and current["remaining"] > 0:
            matched.add(village_id)
        elif change_type == "community_added" and current["remaining"] > 0:
            matched.add(village_id)
        elif (
            change_type == "window_active_changed"
            and change.get("new") is True
            and current["remaining"] > 0
        ):
            matched.add(village_id)
    return sorted(matched)


def startup_alert_ids(
    villages: dict[str, dict[str, Any]], watched_districts: set[str]
) -> list[str]:
    return sorted(
        village_id
        for village_id, item in villages.items()
        if item["district"] in watched_districts and item["remaining"] > 0
    )


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, villages: dict[str, dict[str, Any]], checked_at: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(
            {"version": 1, "updated_at": checked_at, "villages": villages},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    temp.replace(path)


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            f"找不到配置文件：{path}\n请复制 config.example.json 为 config.json 后再填写。"
        )
    config = json.loads(path.read_text(encoding="utf-8"))
    districts = config.get("watch_districts")
    if not isinstance(districts, list) or not districts:
        raise ValueError("watch_districts 至少需要填写一个行政区")
    minutes = config.get("check_minutes", [1, 11, 21, 31, 41, 51])
    if not isinstance(minutes, list) or not minutes:
        raise ValueError("check_minutes 不能为空")
    clean_minutes = sorted({int(value) for value in minutes})
    if any(value < 0 or value > 59 for value in clean_minutes):
        raise ValueError("check_minutes 只能填写 0 到 59")
    config["check_minutes"] = clean_minutes
    return config


def load_env_file(path: Path = DEFAULT_ENV) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def email_settings(config: dict[str, Any]) -> dict[str, Any]:
    load_env_file()
    email = config.get("email") or {}
    return {
        "enabled": bool(email.get("enabled", True)),
        "smtp_host": str(email.get("smtp_host") or "smtp.gmail.com"),
        "smtp_port": int(email.get("smtp_port") or 465),
        "sender": os.getenv("HOUSING_SMTP_USER") or str(email.get("sender") or ""),
        "password": (os.getenv("HOUSING_SMTP_APP_PASSWORD") or "").replace(" ", ""),
        "recipient": os.getenv("HOUSING_NOTIFY_TO")
        or str(email.get("recipient") or ""),
        "subject_prefix": str(email.get("subject_prefix") or "【深梦扬帆】"),
    }


def validate_email_settings(settings: dict[str, Any]) -> None:
    missing = []
    if not settings["sender"]:
        missing.append("HOUSING_SMTP_USER")
    if not settings["password"]:
        missing.append("HOUSING_SMTP_APP_PASSWORD")
    if not settings["recipient"]:
        missing.append("HOUSING_NOTIFY_TO")
    if missing:
        raise RuntimeError("缺少邮件设置：" + "、".join(missing))


def build_email(
    checked_at: str,
    alert_ids: list[str],
    villages: dict[str, dict[str, Any]],
    buildings: dict[str, list[dict[str, Any]]],
    subject_prefix: str,
) -> tuple[str, str]:
    names = "、".join(villages[village_id]["name"] for village_id in alert_ids)
    total = sum(villages[village_id]["remaining"] for village_id in alert_ids)
    subject = f"{subject_prefix}{names}有房｜共{total}个"
    lines = [f"发现时间：{checked_at}", "", "关注区域出现可申请房源：", ""]
    for village_id in alert_ids:
        item = villages[village_id]
        lines.append(
            f"{item['name']}｜{item['district']} / {item['street']}｜剩余 {item['remaining']}"
        )
        for building in buildings.get(village_id, []):
            building_name = str(building.get("buildingName") or "未命名楼栋").strip()
            remaining = int(building.get("remainingQuota") or 0)
            lines.append(f"  - {building_name}：{remaining}")
        lines.append("")
    lines.extend(
        [
            "房源变化较快，请立即打开官方小程序确认并报名。",
            "本程序仅监控和通知，不会自动报名或代抢。",
        ]
    )
    return subject, "\n".join(lines)


def send_email(settings: dict[str, Any], subject: str, body: str) -> None:
    validate_email_settings(settings)
    message = EmailMessage()
    message["From"] = settings["sender"]
    message["To"] = settings["recipient"]
    message["Subject"] = subject
    message.set_content(body)
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(
        settings["smtp_host"], settings["smtp_port"], context=context, timeout=30
    ) as client:
        client.login(settings["sender"], settings["password"])
        client.send_message(message)


def next_run_time(after: datetime, minutes: list[int]) -> datetime:
    cursor = after.replace(second=0, microsecond=0)
    for hour_offset in range(25):
        hour = cursor.replace(minute=0) + timedelta(hours=hour_offset)
        for minute in minutes:
            candidate = hour.replace(minute=minute)
            if candidate > after:
                return candidate
    raise RuntimeError("无法计算下一次检查时间")


def run_once(
    config: dict[str, Any], state_path: Path, dry_run: bool = False
) -> dict[str, Any]:
    timeout = int(config.get("request_timeout_seconds") or 20)
    checked_at = now_shanghai().isoformat(timespec="seconds")
    villages = normalize_villages(fetch_villages(timeout))
    previous = load_json(state_path)
    initialized = previous is None
    old_villages = (previous or {}).get("villages") or {}
    changes = [] if initialized else compare_villages(old_villages, villages)
    watched_districts = {str(value) for value in config["watch_districts"]}
    if initialized and bool(config.get("notify_on_startup", False)):
        alert_ids = startup_alert_ids(villages, watched_districts)
    else:
        alert_ids = watched_alert_ids(changes, villages, watched_districts)

    details: dict[str, list[dict[str, Any]]] = {}
    for village_id in alert_ids:
        details[village_id] = fetch_buildings(village_id, timeout)

    settings = email_settings(config)
    email_sent = False
    if alert_ids and settings["enabled"]:
        subject, body = build_email(
            checked_at, alert_ids, villages, details, settings["subject_prefix"]
        )
        if dry_run:
            print("\n--- 邮件预览 ---")
            print(subject)
            print(body)
            print("--- 预览结束 ---\n")
        else:
            send_email(settings, subject, body)
            email_sent = True

    save_state(state_path, villages, checked_at)
    available = [
        {"village_id": village_id, **item}
        for village_id, item in villages.items()
        if item["remaining"] > 0
    ]
    result = {
        "ok": True,
        "checked_at": checked_at,
        "initialized": initialized,
        "community_count": len(villages),
        "total_remaining": sum(item["remaining"] for item in villages.values()),
        "watched_districts": sorted(watched_districts),
        "alert_village_ids": alert_ids,
        "email_sent": email_sent,
        "available": sorted(available, key=lambda item: (-item["remaining"], item["name"])),
        "changes": changes,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def send_test_message(config: dict[str, Any]) -> None:
    settings = email_settings(config)
    subject = f"{settings['subject_prefix']}房源监控测试邮件"
    body = (
        "这是一封房源监控测试邮件。\n\n"
        "如果你能在邮箱或微信提醒中看到它，说明邮件通道已经配置成功。"
    )
    send_email(settings, subject, body)
    print(f"测试邮件已发送到 {settings['recipient']}")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="深梦扬帆房源监控与邮件提醒")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--once", action="store_true", help="只检查一次")
    parser.add_argument("--dry-run", action="store_true", help="不发邮件，只显示预览")
    parser.add_argument("--test-email", action="store_true", help="发送测试邮件")
    args = parser.parse_args()

    try:
        load_env_file()
        config = load_config(args.config)
        if args.test_email:
            send_test_message(config)
            return 0
        if args.once:
            run_once(config, args.state, args.dry_run)
            return 0

        print("监控已启动。按 Ctrl+C 可停止。")
        run_once(config, args.state, args.dry_run)
        while True:
            next_time = next_run_time(now_shanghai(), config["check_minutes"])
            wait_seconds = max(1.0, (next_time - now_shanghai()).total_seconds())
            print(f"下一次检查：{next_time.isoformat(timespec='seconds')}")
            time.sleep(wait_seconds)
            try:
                run_once(config, args.state, args.dry_run)
            except Exception as error:
                print(f"检查失败：{error}", file=sys.stderr)
    except KeyboardInterrupt:
        print("\n监控已停止。")
        return 0
    except Exception as error:
        print(f"错误：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
