"""프로그램 첫 화면 (아이디/비밀번호 입력, 자동 로그인, 진행 로그)."""

from __future__ import annotations

import datetime
import os
import queue
import re
import sys
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, simpledialog, ttk

from . import config
from .bot import HunetBot, LoginError, RunResult

ID_PREFIX = "philips-"
ID_PATTERN = re.compile(r"^philips-\d+$")
AUTO_LOGIN_DELAY_SEC = 3


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.queue: "queue.Queue[tuple]" = queue.Queue()
        self.worker: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.countdown_job = None
        self.countdown_left = 0
        self.running_credentials: tuple[str, str, bool] | None = None
        self.closing = False
        self.log_path = os.path.join(config.config_dir(), "last_run.log")

        root.title("휴넷 자동 학습 - 필립스")
        root.geometry("680x600")
        root.minsize(560, 480)
        self._build()
        self._load_saved()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.poll_job = root.after(100, self._poll_queue)

    # ---------------------------------------------------------------- UI ---
    def _build(self) -> None:
        base_font = ("맑은 고딕", 10) if sys.platform == "win32" else None
        style = ttk.Style(self.root)
        if base_font:
            style.configure(".", font=base_font)
        style.configure("Title.TLabel", font=(base_font[0] if base_font else "TkDefaultFont", 15, "bold"),
                        foreground="#0b5ed7")
        style.configure("Status.TLabel", foreground="#c0392b")

        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="PHILIPS 휴넷 자동 학습", style="Title.TLabel").pack(anchor="w")
        ttk.Label(outer, text="philips.hunet.co.kr 로그인 → 나의 강의실 → 미완료 과정 학습창 열기").pack(anchor="w", pady=(2, 12))

        form = ttk.Frame(outer)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)

        ttk.Label(form, text="아이디").grid(row=0, column=0, sticky="w", padx=(0, 10), pady=4)
        self.id_var = tk.StringVar()
        self.id_entry = ttk.Entry(form, textvariable=self.id_var)
        self.id_entry.grid(row=0, column=1, sticky="ew", pady=4)

        ttk.Label(form, text="비밀번호").grid(row=1, column=0, sticky="w", padx=(0, 10), pady=4)
        self.pw_var = tk.StringVar()
        self.pw_entry = ttk.Entry(form, textvariable=self.pw_var, show="●")
        self.pw_entry.grid(row=1, column=1, sticky="ew", pady=4)
        self.pw_entry.bind("<Return>", lambda e: self.start())
        self.id_entry.bind("<Return>", lambda e: self.pw_entry.focus_set())

        self.remember_var = tk.BooleanVar(value=True)
        self.remember_chk = ttk.Checkbutton(
            form, text="아이디/비밀번호 저장 (다음 실행부터 자동 로그인)", variable=self.remember_var
        )
        self.remember_chk.grid(row=2, column=1, sticky="w", pady=(4, 0))

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=12)
        self.start_btn = ttk.Button(buttons, text="로그인 / 학습 시작", command=self.start)
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(buttons, text="중지", command=self.stop, state="disabled")
        self.stop_btn.pack(side="left", padx=6)
        self.clear_btn = ttk.Button(buttons, text="저장 정보 삭제", command=self.clear_saved)
        self.clear_btn.pack(side="right")

        self.status_var = tk.StringVar(value="아이디와 비밀번호를 입력하고 [로그인 / 학습 시작]을 누르세요.")
        ttk.Label(outer, textvariable=self.status_var, style="Status.TLabel", wraplength=620).pack(anchor="w")

        self.log_box = scrolledtext.ScrolledText(outer, height=16, state="disabled", wrap="word")
        self.log_box.pack(fill="both", expand=True, pady=(8, 0))

    def _set_running(self, running: bool) -> None:
        state = "disabled" if running else "normal"
        for w in (self.id_entry, self.pw_entry, self.remember_chk, self.start_btn, self.clear_btn):
            w.configure(state=state)
        self.stop_btn.configure(state="normal" if running else "disabled")

    def log(self, msg: str) -> None:
        line = f"[{datetime.datetime.now():%H:%M:%S}] {msg}\n"
        self.log_box.configure(state="normal")
        self.log_box.insert("end", line)
        self.log_box.see("end")
        self.log_box.configure(state="disabled")
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line)
        except OSError:
            pass

    # ----------------------------------------------------------- 저장 정보 ---
    def _load_saved(self) -> None:
        settings = config.load_settings()
        self.id_var.set(settings.user_id or ID_PREFIX)
        password = config.load_password(settings.user_id) if settings.user_id else ""
        if password:
            self.pw_var.set(password)
        if settings.user_id and password and settings.auto_login:
            self.log("저장된 아이디/비밀번호를 불러왔습니다.")
            self._start_countdown()
        else:
            self.id_entry.focus_set()
            self.id_entry.icursor("end")

    def _save_credentials(self) -> None:
        if not self.running_credentials:
            return
        user_id, password, remember = self.running_credentials
        try:
            if remember:
                config.save_password(user_id, password)
                config.save_settings(config.Settings(user_id=user_id, auto_login=True))
                self.log("로그인 정보를 저장했습니다. 다음 실행부터 자동으로 로그인합니다.")
            else:
                config.delete_password(user_id)
                config.save_settings(config.Settings(user_id=user_id, auto_login=False))
        except Exception as e:  # 저장 실패해도 진행은 계속
            self.log(f"로그인 정보 저장 실패: {e}")

    def clear_saved(self) -> None:
        if not messagebox.askyesno("저장 정보 삭제", "저장된 아이디/비밀번호와 자동 로그인 설정을 삭제할까요?"):
            return
        self._cancel_countdown()
        settings = config.load_settings()
        config.delete_password(settings.user_id)
        config.delete_password(self.id_var.get().strip())
        config.save_settings(config.Settings())
        self.pw_var.set("")
        self.id_var.set(ID_PREFIX)
        self.log("저장된 로그인 정보를 삭제했습니다.")
        self.status_var.set("저장 정보가 삭제되었습니다.")

    # ----------------------------------------------------------- 자동 로그인 ---
    def _start_countdown(self) -> None:
        self.countdown_left = AUTO_LOGIN_DELAY_SEC
        self.stop_btn.configure(state="normal")
        self._tick_countdown()

    def _tick_countdown(self) -> None:
        if self.countdown_left <= 0:
            self.countdown_job = None
            self.start()
            return
        self.status_var.set(f"{self.countdown_left}초 후 자동 로그인합니다... (취소하려면 [중지])")
        self.countdown_left -= 1
        self.countdown_job = self.root.after(1000, self._tick_countdown)

    def _cancel_countdown(self) -> bool:
        if self.countdown_job is None:
            return False
        self.root.after_cancel(self.countdown_job)
        self.countdown_job = None
        self.stop_btn.configure(state="disabled")
        return True

    # ---------------------------------------------------------------- 실행 ---
    def start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        self._cancel_countdown()

        user_id = re.sub(r"\s+", "", self.id_var.get())
        if user_id.isdigit():
            user_id = ID_PREFIX + user_id
        if not ID_PATTERN.match(user_id):
            if not messagebox.askyesno(
                "아이디 확인",
                f"아이디는 보통 'philips-숫자' 형식입니다.\n입력한 아이디: {user_id}\n\n이대로 진행할까요?",
            ):
                return
        password = self.pw_var.get()
        if not password:
            messagebox.showwarning("입력 필요", "비밀번호를 입력하세요.")
            self.pw_entry.focus_set()
            return
        self.id_var.set(user_id)

        self.running_credentials = (user_id, password, self.remember_var.get())
        self.stop_event = threading.Event()
        self._set_running(True)
        self.status_var.set("실행 중... (브라우저 창이 열립니다)")
        try:
            with open(self.log_path, "w", encoding="utf-8") as f:
                f.write("")
        except OSError:
            pass

        headless = os.environ.get("HUNET_HEADLESS") == "1"
        self.worker = threading.Thread(target=self._run_bot, args=(user_id, password, headless), daemon=True)
        self.worker.start()

    def stop(self) -> None:
        if self._cancel_countdown():
            self.status_var.set("자동 로그인을 취소했습니다.")
            self.log("자동 로그인을 취소했습니다.")
            return
        if self.worker and self.worker.is_alive():
            self.stop_event.set()
            self.status_var.set("중지하는 중...")

    # ---- 작업 스레드 (브라우저 조작) ----
    def _run_bot(self, user_id: str, password: str, headless: bool) -> None:
        bot = HunetBot(
            user_id,
            password,
            log=lambda m: self.queue.put(("log", m)),
            ask_2fa=self._ask_2fa_from_worker,
            on_login_success=lambda: self.queue.put(("login_ok", None)),
            stop_event=self.stop_event,
            headless=headless,
        )
        try:
            self.queue.put(("done", bot.run()))
        except LoginError as e:
            self.queue.put(("login_failed", str(e)))
        except Exception as e:
            self.queue.put(("error", str(e)))

    def _ask_2fa_from_worker(self, retry: bool) -> str | None:
        answered = threading.Event()
        holder: dict = {}
        self.queue.put(("ask_2fa", (answered, holder, retry)))
        while not answered.wait(0.2):
            if self.stop_event.is_set():
                return None
        return holder.get("code")

    # ---- 화면 스레드에서 처리 ----
    def _poll_queue(self) -> None:
        try:
            while True:
                kind, data = self.queue.get_nowait()
                self._handle(kind, data)
        except queue.Empty:
            pass
        self.poll_job = self.root.after(100, self._poll_queue)

    def _handle(self, kind: str, data) -> None:
        if kind == "log":
            self.log(data)
            for prefix, status in (
                ("학습창이 열렸습니다", "학습창을 열었습니다. 브라우저를 닫거나 [중지]를 누르면 종료됩니다."),
                ("모든 과정의 현황이 100%", "모든 과정이 100% 완료되어 있습니다."),
                ("진행중인 교육", "진행중인 교육이 없습니다."),
                ("오류:", data),
            ):
                if data.startswith(prefix):
                    self.status_var.set(status)
        elif kind == "login_ok":
            self.status_var.set("로그인 성공. 학습 화면으로 이동 중...")
            self._save_credentials()
        elif kind == "ask_2fa":
            answered, holder, retry = data
            prompt = "등록된 휴대폰/이메일로 받은 인증번호를 입력하세요."
            if retry:
                prompt = "인증번호가 맞지 않습니다. 다시 입력하세요."
            holder["code"] = simpledialog.askstring("본인인증", prompt, parent=self.root)
            answered.set()
        elif kind == "login_failed":
            self._set_running(False)
            self.status_var.set(f"로그인 실패: {data}")
            self.log(f"로그인 실패: {data}")
            # 비밀번호가 틀린 채로 자동 로그인이 반복되면 계정이 잠길 수 있으므로 자동 로그인을 끈다
            settings = config.load_settings()
            if settings.auto_login:
                settings.auto_login = False
                config.save_settings(settings)
                self.log("계정 잠김 방지를 위해 자동 로그인을 해제했습니다. 비밀번호를 확인 후 다시 시작하세요.")
            if not self.closing:
                messagebox.showerror("로그인 실패", f"{data}\n\n아이디/비밀번호를 확인한 뒤 다시 시도하세요.")
                self.pw_entry.focus_set()
                self.pw_entry.select_range(0, "end")
        elif kind == "error":
            self._set_running(False)
            self.status_var.set(f"오류: {data}")
            self.log(f"오류: {data}")
            if not self.closing:
                messagebox.showerror("오류", data)
        elif kind == "done":
            self._set_running(False)
            result: RunResult = data
            if result.error:
                self.status_var.set(f"오류로 종료: {result.error}")
            elif result.opened:
                self.status_var.set(f"학습창을 열었던 과정: {result.opened.title}")
            elif result.courses:
                self.status_var.set("모든 과정이 100% 완료되어 있습니다.")
            else:
                self.status_var.set("종료되었습니다.")
            self.log("브라우저가 종료되었습니다.")

    # ---------------------------------------------------------------- 종료 ---
    def on_close(self) -> None:
        self._cancel_countdown()
        if self.worker and self.worker.is_alive():
            self.closing = True
            self.stop_event.set()
            self.status_var.set("브라우저를 닫는 중...")
            self._wait_worker_then_destroy(50)
        else:
            self._destroy()

    def _wait_worker_then_destroy(self, tries_left: int) -> None:
        if self.worker and self.worker.is_alive() and tries_left > 0:
            self.root.after(200, self._wait_worker_then_destroy, tries_left - 1)
        else:
            self._destroy()

    def _destroy(self) -> None:
        try:
            self.root.after_cancel(self.poll_job)
        except tk.TclError:
            pass
        self.root.destroy()


def main() -> None:
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # 고해상도 화면에서 글자가 흐리지 않게
        except Exception:
            pass
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
