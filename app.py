from __future__ import annotations

import queue
import threading
from datetime import datetime
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable

import monitor


class MonitorApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("深梦扬帆房源监控")
        self.root.geometry("680x500")
        self.root.minsize(620, 440)
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.stop_event = threading.Event()
        self.monitor_thread: threading.Thread | None = None
        self.status = tk.StringVar(value="准备就绪")
        self.account = tk.StringVar(value="正在读取邮件设置…")
        self._build_ui()
        self._refresh_account_text()
        self.root.after(100, self._process_events)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        frame = ttk.Frame(self.root, padding=20)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="深梦扬帆房源监控", font=("Microsoft YaHei UI", 18, "bold")).pack(
            anchor="w"
        )
        ttk.Label(
            frame,
            text="本地运行 · 按行政区筛选 · Gmail 邮件提醒",
            foreground="#555555",
        ).pack(anchor="w", pady=(4, 18))

        info = ttk.LabelFrame(frame, text="邮件通道", padding=12)
        info.pack(fill="x")
        ttk.Label(info, textvariable=self.account, wraplength=600).pack(anchor="w")

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=16)
        self.test_button = ttk.Button(
            buttons, text="发送测试邮件", command=self._test_email
        )
        self.test_button.pack(side="left")
        self.check_button = ttk.Button(
            buttons, text="立即检查一次", command=self._check_once
        )
        self.check_button.pack(side="left", padx=(10, 0))
        self.start_button = ttk.Button(
            buttons, text="开始持续监控", command=self._start_monitoring
        )
        self.start_button.pack(side="left", padx=(10, 0))
        self.stop_button = ttk.Button(
            buttons, text="停止监控", command=self._stop_monitoring, state="disabled"
        )
        self.stop_button.pack(side="left", padx=(10, 0))

        ttk.Label(frame, textvariable=self.status, foreground="#0b57d0").pack(
            anchor="w", pady=(0, 10)
        )

        log_frame = ttk.LabelFrame(frame, text="运行记录", padding=8)
        log_frame.pack(fill="both", expand=True)
        self.log = tk.Text(log_frame, height=14, wrap="word", state="disabled")
        self.log.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        scrollbar.pack(side="right", fill="y")
        self.log.configure(yscrollcommand=scrollbar.set)
        self._append_log("首次使用请先准备 config.json 和 .env 文件。")

    def _append_log(self, text: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log.configure(state="normal")
        self.log.insert("end", f"[{stamp}] {text}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _load_config(self) -> dict[str, Any]:
        monitor.load_env_file()
        return monitor.load_config(monitor.DEFAULT_CONFIG)

    def _refresh_account_text(self) -> None:
        try:
            config = self._load_config()
            settings = monitor.email_settings(config)
            sender = settings["sender"] or "未设置"
            recipient = settings["recipient"] or "未设置"
            districts = "、".join(str(x) for x in config["watch_districts"])
            self.account.set(
                f"发件邮箱：{sender}\n接收邮箱：{recipient}\n关注区域：{districts}"
            )
        except Exception as error:
            self.account.set(str(error))

    def _run_background(
        self, name: str, action: Callable[[], Any], success_event: str
    ) -> None:
        def worker() -> None:
            try:
                result = action()
                self.events.put((success_event, result))
            except Exception as error:
                self.events.put(("error", f"{name}失败：{error}"))

        threading.Thread(target=worker, daemon=True).start()

    def _test_email(self) -> None:
        self.test_button.configure(state="disabled")
        self.status.set("正在发送测试邮件…")

        def action() -> str:
            config = self._load_config()
            settings = monitor.email_settings(config)
            monitor.send_test_message(config)
            return str(settings["recipient"])

        self._run_background("测试邮件", action, "test_email_ok")

    def _check_once(self) -> None:
        self.check_button.configure(state="disabled")
        self.status.set("正在检查房源…")

        def action() -> dict[str, Any]:
            return monitor.run_once(self._load_config(), monitor.DEFAULT_STATE)

        self._run_background("房源检查", action, "check_ok")

    def _start_monitoring(self) -> None:
        if self.monitor_thread and self.monitor_thread.is_alive():
            return
        self.stop_event.clear()
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.status.set("持续监控运行中")

        def worker() -> None:
            try:
                config = self._load_config()
                while not self.stop_event.is_set():
                    result = monitor.run_once(config, monitor.DEFAULT_STATE)
                    self.events.put(("monitor_check", result))
                    next_time = monitor.next_run_time(
                        monitor.now_shanghai(), config["check_minutes"]
                    )
                    wait_seconds = max(
                        1.0, (next_time - monitor.now_shanghai()).total_seconds()
                    )
                    self.events.put(("next_run", next_time.isoformat(timespec="minutes")))
                    if self.stop_event.wait(wait_seconds):
                        break
            except Exception as error:
                self.events.put(("monitor_error", str(error)))
            finally:
                self.events.put(("monitor_stopped", None))

        self.monitor_thread = threading.Thread(target=worker, daemon=True)
        self.monitor_thread.start()
        self._append_log("持续监控已启动。")

    def _stop_monitoring(self) -> None:
        self.stop_event.set()
        self.status.set("正在停止监控…")

    def _process_events(self) -> None:
        while True:
            try:
                event, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if event == "test_email_ok":
                self.test_button.configure(state="normal")
                self.status.set("测试邮件发送成功")
                self._append_log(f"测试邮件已发送到 {payload}")
                messagebox.showinfo(
                    "发送成功",
                    f"测试邮件已发送到：\n{payload}\n\n请检查邮箱或微信提醒。",
                )
            elif event == "check_ok":
                self.check_button.configure(state="normal")
                self.status.set("检查完成")
                self._append_log(
                    f"检查完成：共 {payload['community_count']} 个社区，当前余量 {payload['total_remaining']}。"
                )
            elif event == "monitor_check":
                self._append_log(
                    f"定时检查完成：当前余量 {payload['total_remaining']}，本次变化 {len(payload['changes'])} 项。"
                )
            elif event == "next_run":
                self.status.set(f"持续监控运行中，下次检查：{payload}")
            elif event == "monitor_error":
                self._append_log(f"持续监控出错：{payload}")
                messagebox.showerror("监控出错", payload)
            elif event == "monitor_stopped":
                self.start_button.configure(state="normal")
                self.stop_button.configure(state="disabled")
                self.status.set("监控已停止")
                self._append_log("持续监控已停止。")
            elif event == "error":
                self.test_button.configure(state="normal")
                self.check_button.configure(state="normal")
                self.status.set("操作失败")
                self._append_log(payload)
                messagebox.showerror("操作失败", payload)
        self.root.after(100, self._process_events)

    def _on_close(self) -> None:
        self.stop_event.set()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    MonitorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
