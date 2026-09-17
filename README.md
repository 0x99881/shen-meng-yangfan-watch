# 深梦扬帆房源监控

一个在本地运行的“深梦扬帆”房源变化监控程序。它会定时读取官方小程序展示的房源余量，按行政区筛选，并在关注区域出现新房源或余量增加时发送邮件。

项目只做监控和通知，不会自动登录、自动报名、自动预约或代抢。

## 工作流程

1. 本地程序按设定时间检查全部社区。
2. 将本次结果与上一次记录比较。
3. 只关注你在配置中选择的行政区。
4. 房源从无到有、余量增加，或申请窗口重新开放且有房时发送邮件。
5. 邮件可发送到 QQ 邮箱等能在微信中提醒的邮箱。

默认在每小时的 `01、11、21、31、41、51` 分检查，既保持每 10 分钟一次，也覆盖 `10:01、14:01、22:01` 等常见放房时间。

## 特点

- 支持同时关注多个行政区
- 检测房源新增、减少、满租和开放状态变化
- 邮件包含社区、街道、楼栋和最新余量
- 同一批变化只提醒一次
- 邮件发送失败时不会覆盖旧记录，下次检查可以再次发现
- 仅使用 Python 自带功能，不需要安装第三方包
- 支持 Windows、macOS 和 Linux

## 快速开始

需要 Python 3.10 或更高版本。

### 1. 准备配置

复制示例文件：

```powershell
Copy-Item config.example.json config.json
```

打开 `config.json`，修改关注区域：

```json
{
  "watch_districts": ["南山区"]
}
```

也可以同时关注多个区域：

```json
{
  "watch_districts": ["南山区", "福田区"]
}
```

请保留示例文件中的其他设置。

### 2. 设置 Gmail

Gmail 通常需要先开启两步验证，再创建应用专用密码。不要把 Gmail 密码或应用专用密码写进配置文件、代码或提交到 GitHub。

在当前 PowerShell 窗口设置：

```powershell
$env:HOUSING_SMTP_USER="你的Gmail地址"
$env:HOUSING_SMTP_APP_PASSWORD="你的Gmail应用专用密码"
$env:HOUSING_NOTIFY_TO="接收提醒的邮箱地址"
```

如果接收邮箱已经开启微信提醒，邮件到达后就能在微信中看到通知。

### 3. 测试邮件

```powershell
python monitor.py --test-email
```

### 4. 测试房源读取

```powershell
python monitor.py --once --dry-run
```

### 5. 开始监控

```powershell
python monitor.py
```

Windows 用户也可以双击 `start_windows.bat`。程序窗口需要保持运行，电脑进入睡眠或关机后监控会暂停。

## 常用设置

`config.json` 中可以修改：

| 设置 | 作用 |
| --- | --- |
| `watch_districts` | 需要邮件提醒的行政区 |
| `check_minutes` | 每小时在哪些分钟检查 |
| `notify_on_startup` | 第一次启动时，现有房源是否也发邮件 |
| `email.enabled` | 是否启用邮件提醒 |

默认 `notify_on_startup` 为 `false`，第一次运行只建立基准，不会把已经存在的房源当成刚释放的房源。

## 命令

```text
python monitor.py                 持续监控
python monitor.py --once          只检查一次
python monitor.py --once --dry-run  不发邮件，显示结果和邮件预览
python monitor.py --test-email    发送测试邮件
```

## 隐私与安全

- `config.json`、`.env` 和本地房源记录已经加入忽略列表，不会被正常提交。
- 邮箱密码只从电脑的环境变量读取。
- 发布代码前仍建议检查提交内容，确认没有个人邮箱、密码和本地记录。

## 使用边界

本项目用于个人信息提醒。请合理设置检查频率，遵守相关服务的使用规则，不要用它进行高频请求、自动报名、批量注册、绕过验证或其他影响正常服务的操作。

房源接口和活动规则可能调整，出现异常时请以官方小程序为准。

## 开源协议

[MIT](LICENSE)
