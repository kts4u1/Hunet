"""프로그램 첫 화면 (아이디/비밀번호 입력, 자동 로그인, 진행 단계, 진행 기록)."""

from __future__ import annotations

import datetime
import os
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox

import customtkinter as ctk

from . import __version__, cleanup, config
from .bot import HunetBot, LoginError, RunResult

ID_PREFIX = "philips-"
ID_PATTERN = re.compile(r"^philips-\d+$")
AUTO_LOGIN_DELAY_SEC = 3
ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

# ---- 색상 ----
BRAND = "#0B5ED7"
BRAND_HOVER = "#094DB1"
SIDEBAR = "#0B3A8A"
SIDEBAR_LINE = "#2A5BAE"
BG = "#F3F6FB"
CARD = "#FFFFFF"
CARD_BORDER = "#E3E9F2"
TEXT = "#0F172A"
MUTED = "#64748B"
FIELD = "#F8FAFC"
FIELD_BORDER = "#D5DDE8"
GREEN = "#16A34A"
RED = "#DC2626"
AMBER = "#D97706"

STEPS = [
    ("로그인", "아이디/비밀번호 자동 입력"),
    ("메인 화면", "학습하기 클릭"),
    ("나의 강의실", "과정별 현황 확인"),
    ("학습창 열기", "100% 미만 과정 학습 시작"),
]

STEP_STYLE = {
    #           원 배경      원 글자     기호     제목 색      설명 색
    "pending": ("#1E4D9C", "#8FB0E6", None, "#B9CCEE", "#7F9DD0"),
    "active": ("#FFFFFF", BRAND, None, "#FFFFFF", "#D6E4FF"),
    "done": ("#22C55E", "#FFFFFF", "✓", "#FFFFFF", "#A9C3EE"),
    "skip": ("#5B6B86", "#FFFFFF", "–", "#C9D6EE", "#A9C3EE"),
    "error": ("#EF4444", "#FFFFFF", "!", "#FFFFFF", "#FFC9C9"),
}


def _pick_font_family(root: tk.Misc) -> str:
    if sys.platform == "win32":
        return "Malgun Gothic"
    families = set(tkfont.families(root))
    for name in ("Apple SD Gothic Neo", "Noto Sans CJK KR", "NanumGothic", "WenQuanYi Zen Hei"):
        if name in families:
            return name
    return "TkDefaultFont"


class App:
    def __init__(self, root: ctk.CTk):
        self.root = root
        self.queue: "queue.Queue[tuple]" = queue.Queue()
        self.worker: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.countdown_job = None
        self.countdown_left = 0
        self.pulse_job = None
        self.pulse_on = False
        self.running_credentials: tuple[str, str, bool] | None = None
        self.closing = False
        self.step_states = ["pending"] * len(STEPS)
        self.log_path = os.path.join(config.config_dir(), "last_run.log")
        self.shortcut_thread: threading.Thread | None = None
        self.shortcut_watch_until = 0.0
        self.reported_failures: set = set()
        self._init_log_file()

        family = _pick_font_family(root)
        self.f = {
            "brand": ctk.CTkFont(family, 13, "bold"),
            "title": ctk.CTkFont(family, 26, "bold"),
            "sub": ctk.CTkFont(family, 13),
            "section": ctk.CTkFont(family, 12, "bold"),
            "step_num": ctk.CTkFont(family, 14, "bold"),
            "step_title": ctk.CTkFont(family, 14, "bold"),
            "step_detail": ctk.CTkFont(family, 12),
            "card_title": ctk.CTkFont(family, 18, "bold"),
            "label": ctk.CTkFont(family, 12, "bold"),
            "body": ctk.CTkFont(family, 13),
            "small": ctk.CTkFont(family, 12),
            "button": ctk.CTkFont(family, 15, "bold"),
            "log": ctk.CTkFont(family, 12),
        }

        root.title("휴넷 자동 학습")
        root.geometry("960x640")
        root.minsize(860, 600)
        root.configure(fg_color=BG)
        self._set_icon()
        self._build()
        self._load_saved()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.poll_job = root.after(100, self._poll_queue)
        self._watch_shortcuts(15)  # 예전 실행에서 남은 웹앱 바로가기 정리

    # ================================================================ UI ===
    def _set_icon(self) -> None:
        try:
            if sys.platform == "win32":
                ico = os.path.join(ASSETS, "app.ico")
                # customtkinter 가 기본 아이콘을 덮어쓰므로 조금 뒤에 설정
                self.root.after(250, lambda: self.root.iconbitmap(ico))
            else:
                self._icon_img = tk.PhotoImage(file=os.path.join(ASSETS, "app.png"))
                self.root.iconphoto(True, self._icon_img)
        except Exception:
            pass

    def _build(self) -> None:
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self._build_main()

    def _build_sidebar(self) -> None:
        f = self.f
        side = ctk.CTkFrame(self.root, width=320, corner_radius=0, fg_color=SIDEBAR)
        side.grid(row=0, column=0, sticky="nsw")
        side.grid_propagate(False)
        side.grid_columnconfigure(0, weight=1)
        side.grid_rowconfigure(10, weight=1)

        ctk.CTkLabel(side, text="PHILIPS  ·  HUNET", font=f["brand"], text_color="#8DB6FF").grid(
            row=0, column=0, sticky="w", padx=32, pady=(36, 0))
        ctk.CTkLabel(side, text="휴넷 자동 학습", font=f["title"], text_color="#FFFFFF").grid(
            row=1, column=0, sticky="w", padx=32, pady=(6, 0))
        ctk.CTkLabel(side, text="로그인부터 학습창 열기까지\n버튼 한 번으로 자동 진행합니다.", font=f["sub"],
                     text_color="#C3D5F5", justify="left").grid(row=2, column=0, sticky="w", padx=32, pady=(10, 0))

        ctk.CTkLabel(side, text="진행 단계", font=f["section"], text_color="#86A6DA").grid(
            row=3, column=0, sticky="w", padx=32, pady=(40, 12))

        steps_box = ctk.CTkFrame(side, fg_color="transparent")
        steps_box.grid(row=4, column=0, sticky="ew", padx=28)
        steps_box.grid_columnconfigure(1, weight=1)
        self.step_widgets = []
        for i, (title, detail) in enumerate(STEPS):
            circle = ctk.CTkFrame(steps_box, width=34, height=34, corner_radius=17)
            circle.grid(row=i * 2, column=0, sticky="n", padx=(0, 14))
            circle.grid_propagate(False)
            num = ctk.CTkLabel(circle, text=str(i + 1), width=20, height=20, font=f["step_num"],
                               fg_color="transparent")
            num.place(relx=0.5, rely=0.5, anchor="center")
            text_box = ctk.CTkFrame(steps_box, fg_color="transparent")
            text_box.grid(row=i * 2, column=1, sticky="w")
            t = ctk.CTkLabel(text_box, text=title, font=f["step_title"], anchor="w", height=18)
            t.pack(anchor="w")
            d = ctk.CTkLabel(text_box, text=detail, font=f["step_detail"], anchor="w", height=16,
                             wraplength=210, justify="left")
            d.pack(anchor="w")
            if i < len(STEPS) - 1:
                line = ctk.CTkFrame(steps_box, width=2, height=22, corner_radius=1, fg_color=SIDEBAR_LINE)
                line.grid(row=i * 2 + 1, column=0, pady=4)
            self.step_widgets.append((circle, num, t, d, detail))
            self._render_step(i, "pending")

        ctk.CTkLabel(side, text=f"v{__version__}  ·  학습지원 문의 1588-6559", font=f["small"], text_color="#7F9DD0").grid(
            row=11, column=0, sticky="w", padx=32, pady=(0, 28))

    def _build_main(self) -> None:
        f = self.f
        main = ctk.CTkFrame(self.root, fg_color="transparent")
        main.grid(row=0, column=1, sticky="nsew", padx=28, pady=24)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(2, weight=1)

        # ---- 로그인 카드 ----
        card = ctk.CTkFrame(main, fg_color=CARD, corner_radius=16, border_width=1, border_color=CARD_BORDER)
        card.grid(row=0, column=0, sticky="ew")
        card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(card, text="로그인", font=f["card_title"], text_color=TEXT).grid(
            row=0, column=0, sticky="w", padx=24, pady=(20, 0))
        ctk.CTkLabel(card, text="philips.hunet.co.kr 계정 정보를 입력하세요.", font=f["small"],
                     text_color=MUTED).grid(row=1, column=0, sticky="w", padx=24, pady=(2, 12))

        fields = ctk.CTkFrame(card, fg_color="transparent")
        fields.grid(row=2, column=0, sticky="ew", padx=24)
        fields.grid_columnconfigure((0, 1), weight=1, uniform="f")

        ctk.CTkLabel(fields, text="아이디", font=f["label"], text_color="#334155").grid(
            row=0, column=0, sticky="w", pady=(0, 4))
        ctk.CTkLabel(fields, text="비밀번호", font=f["label"], text_color="#334155").grid(
            row=0, column=1, sticky="w", padx=(12, 0), pady=(0, 4))

        self.id_var = tk.StringVar()
        self.id_entry = ctk.CTkEntry(fields, textvariable=self.id_var, height=42, corner_radius=10, font=f["body"],
                                     fg_color=FIELD, border_color=FIELD_BORDER, border_width=1, text_color=TEXT)
        self.id_entry.grid(row=1, column=0, sticky="ew")

        self.pw_var = tk.StringVar()
        self.pw_entry = ctk.CTkEntry(fields, textvariable=self.pw_var, show="●", height=42, corner_radius=10,
                                     font=f["body"], fg_color=FIELD, border_color=FIELD_BORDER, border_width=1,
                                     text_color=TEXT)
        self.pw_entry.grid(row=1, column=1, sticky="ew", padx=(12, 0))
        self.pw_toggle = ctk.CTkButton(fields, text="보기", width=44, height=28, corner_radius=8, font=f["small"],
                                       fg_color="transparent", hover_color="#E8EEF7", text_color=MUTED,
                                       command=self._toggle_pw)
        self.pw_toggle.place(in_=self.pw_entry, relx=1.0, x=-6, rely=0.5, anchor="e")

        self.id_entry.bind("<Return>", lambda e: self.pw_entry.focus_set())
        self.pw_entry.bind("<Return>", lambda e: self.start())
        for entry in (self.id_entry, self.pw_entry):
            entry.bind("<FocusIn>", lambda e, w=entry: w.configure(border_color=BRAND), add="+")
            entry.bind("<FocusOut>", lambda e, w=entry: w.configure(border_color=FIELD_BORDER), add="+")

        options = ctk.CTkFrame(card, fg_color="transparent")
        options.grid(row=3, column=0, sticky="ew", padx=24, pady=(14, 0))
        options.grid_columnconfigure(0, weight=1)
        self.remember_var = tk.BooleanVar(value=True)
        self.remember_switch = ctk.CTkSwitch(options, text="다음 실행부터 자동 로그인 (아이디/비밀번호 저장)",
                                             variable=self.remember_var, font=f["small"], text_color="#334155",
                                             progress_color=BRAND, switch_width=40, switch_height=20)
        self.remember_switch.grid(row=0, column=0, sticky="w")
        self.clear_btn = ctk.CTkButton(options, text="저장 정보 삭제", width=96, height=28, corner_radius=8,
                                       font=f["small"], fg_color="transparent", hover_color="#FDECEC",
                                       text_color=MUTED, command=self.clear_saved)
        self.clear_btn.grid(row=0, column=1, sticky="e")

        actions = ctk.CTkFrame(card, fg_color="transparent")
        actions.grid(row=4, column=0, sticky="ew", padx=24, pady=(16, 22))
        actions.grid_columnconfigure(0, weight=1)
        self.start_btn = ctk.CTkButton(actions, text="로그인하고 학습 시작", height=48, corner_radius=12,
                                       font=f["button"], fg_color=BRAND, hover_color=BRAND_HOVER,
                                       text_color_disabled="#E2E8F0", command=self.start)
        self.start_btn.grid(row=0, column=0, sticky="ew")
        self.stop_btn = ctk.CTkButton(actions, text="중지", width=100, height=48, corner_radius=12,
                                      font=f["button"], fg_color="transparent", border_width=1,
                                      border_color="#CBD5E1", hover_color="#F1F5F9", text_color="#334155",
                                      text_color_disabled="#B6C1D1", command=self.stop, state="disabled")
        self.stop_btn.grid(row=0, column=1, padx=(10, 0))

        # ---- 상태 표시 ----
        status = ctk.CTkFrame(main, fg_color="transparent")
        status.grid(row=1, column=0, sticky="ew", pady=(16, 10))
        status.grid_columnconfigure(1, weight=1)
        self.status_dot = ctk.CTkFrame(status, width=10, height=10, corner_radius=5, fg_color=MUTED)
        self.status_dot.grid(row=0, column=0, padx=(4, 8))
        self.status_var = tk.StringVar()
        self.status_label = ctk.CTkLabel(status, textvariable=self.status_var, font=f["body"], text_color=TEXT,
                                         anchor="w", wraplength=520, justify="left")
        self.status_label.grid(row=0, column=1, sticky="ew")
        self.progress = ctk.CTkProgressBar(status, height=4, corner_radius=2, progress_color=BRAND,
                                           fg_color="#E2E8F0", mode="determinate")
        self.progress.set(0)
        self.progress.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))

        # ---- 진행 기록 카드 ----
        log_card = ctk.CTkFrame(main, fg_color=CARD, corner_radius=16, border_width=1, border_color=CARD_BORDER)
        log_card.grid(row=2, column=0, sticky="nsew")
        log_card.grid_columnconfigure(0, weight=1)
        log_card.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(log_card, text="진행 기록", font=f["section"], text_color=TEXT).grid(
            row=0, column=0, sticky="w", padx=20, pady=(12, 4))
        ctk.CTkButton(log_card, text="기록 폴더 열기", width=90, height=26, corner_radius=8, font=f["small"],
                      fg_color="transparent", hover_color="#EEF2F8", text_color=BRAND,
                      command=self._open_log_folder).grid(row=0, column=1, sticky="e", padx=12, pady=(10, 4))
        self.log_box = ctk.CTkTextbox(log_card, font=f["log"], fg_color=FIELD, text_color="#1E293B",
                                      corner_radius=10, border_width=0, wrap="word", activate_scrollbars=True)
        self.log_box.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=12, pady=(0, 12))
        self.log_box.tag_config("time", foreground="#94A3B8")
        self.log_box.tag_config("ok", foreground=GREEN)
        self.log_box.tag_config("err", foreground=RED)
        self.log_box.tag_config("warn", foreground=AMBER)
        self.log_box.configure(state="disabled")

        self._set_status("아이디와 비밀번호를 입력하고 [로그인하고 학습 시작]을 누르세요.", "idle")

    # ---------------------------------------------------------- UI 도우미 ---
    def _toggle_pw(self) -> None:
        hidden = self.pw_entry.cget("show") != ""
        self.pw_entry.configure(show="" if hidden else "●")
        self.pw_toggle.configure(text="숨김" if hidden else "보기")

    def _set_status(self, text: str, kind: str = "idle") -> None:
        color = {"idle": MUTED, "run": BRAND, "ok": GREEN, "err": RED, "warn": AMBER}.get(kind, MUTED)
        self.status_var.set(text)
        self.status_dot.configure(fg_color=color)
        self.status_label.configure(text_color=RED if kind == "err" else TEXT)

    def _render_step(self, index: int, state: str, detail: str | None = None) -> None:
        circle, num, title, desc, default_detail = self.step_widgets[index]
        bg, fg, symbol, title_color, desc_color = STEP_STYLE[state]
        circle.configure(fg_color=bg)
        num.configure(text_color=fg, text=symbol or str(index + 1))
        title.configure(text_color=title_color)
        desc.configure(text_color=desc_color, text=self._short(detail) if detail else default_detail)
        self.step_states[index] = state

    @staticmethod
    def _short(text: str, limit: int = 30) -> str:
        return text if len(text) <= limit else text[: limit - 1] + "…"

    def _reset_steps(self) -> None:
        for i in range(len(STEPS)):
            self._render_step(i, "pending")

    def _fail_running_steps(self, detail: str) -> None:
        for i, state in enumerate(self.step_states):
            if state == "active":
                self._render_step(i, "error", detail)

    def _pulse(self) -> None:
        """진행 중인 단계의 원을 깜빡이게 표시."""
        self.pulse_on = not self.pulse_on
        for i, state in enumerate(self.step_states):
            if state == "active":
                self.step_widgets[i][0].configure(fg_color="#FFFFFF" if self.pulse_on else "#BFD5FF")
        self.pulse_job = self.root.after(550, self._pulse)

    def _set_running(self, running: bool) -> None:
        state = "disabled" if running else "normal"
        for w in (self.id_entry, self.pw_entry, self.pw_toggle, self.remember_switch, self.start_btn,
                  self.clear_btn):
            w.configure(state=state)
        self.stop_btn.configure(state="normal" if running else "disabled", text="중지")
        self.start_btn.configure(text="실행 중…" if running else "로그인하고 학습 시작")
        if running:
            self.progress.configure(mode="indeterminate")
            self.progress.start()
            if self.pulse_job is None:
                self._pulse()
        else:
            self.progress.stop()
            self.progress.configure(mode="determinate")
            self.progress.set(0)
            self._watch_shortcuts(120)  # 브라우저를 닫은 뒤 늦게 생기는 바로가기도 정리
            if self.pulse_job is not None:
                self.root.after_cancel(self.pulse_job)
                self.pulse_job = None

    def log(self, msg: str) -> None:
        now = f"{datetime.datetime.now():%H:%M:%S}"
        tag = None
        if msg.startswith("오류") or "실패" in msg:
            tag = "err"
        elif msg.startswith(("로그인 성공", "학습창이 열렸습니다", "로그인 정보를 저장", "웹앱 바로가기")):
            tag = "ok"
        elif msg.startswith("[사이트 알림]"):
            tag = "warn"
        self.log_box.configure(state="normal")
        self.log_box.insert("end", now + "  ", "time")
        self.log_box.insert("end", msg + "\n", tag)
        self.log_box.see("end")
        self.log_box.configure(state="disabled")
        self._log_file(msg)

    def _init_log_file(self) -> None:
        try:
            with open(self.log_path, "w", encoding="utf-8") as fp:
                fp.write(f"휴넷 자동 학습 v{__version__} — {datetime.datetime.now():%Y-%m-%d %H:%M:%S} 시작\n")
        except OSError:
            pass

    def _log_file(self, msg: str) -> None:
        """기록 파일(last_run.log)에만 남기는 자세한 기록."""
        try:
            with open(self.log_path, "a", encoding="utf-8") as fp:
                fp.write(f"[{datetime.datetime.now():%H:%M:%S}] {msg}\n")
        except OSError:
            pass

    # ---------------------------------------------------- 웹앱 바로가기 정리 ---
    def _watch_shortcuts(self, seconds: float) -> None:
        """지금부터 seconds 초 동안(브라우저 실행 중에는 계속) 3초마다 웹앱 바로가기를 검사해 정리."""
        self.shortcut_watch_until = max(self.shortcut_watch_until, time.time() + seconds)
        if self.shortcut_thread and self.shortcut_thread.is_alive():
            return
        self.shortcut_thread = threading.Thread(target=self._shortcut_loop, daemon=True)
        self.shortcut_thread.start()

    def _shortcut_loop(self) -> None:
        first = True
        last_summary = None
        while not self.closing:
            running = self.worker is not None and self.worker.is_alive()
            if not running and time.time() > self.shortcut_watch_until:
                break
            report = cleanup.clean_all()
            summary = [(f.folder, f.lnk_count, [(s.path, s.action) for s in f.web_apps]) for f in report.folders]
            if first or report.removed or report.failed or summary != last_summary:
                for line in report.lines():
                    self.queue.put(("detail", line))
            last_summary, first = summary, False
            if report.removed:
                names = ", ".join(os.path.basename(s.path) for s in report.removed)
                self.queue.put(("log", f"웹앱 바로가기 {len(report.removed)}개를 정리했습니다: {names}"))
            for s in report.failed:
                if s.path not in self.reported_failures:
                    self.reported_failures.add(s.path)
                    self.queue.put(("log", f"오류: 웹앱 바로가기를 지우지 못했습니다 ({os.path.basename(s.path)}) {s.action}"))
            time.sleep(3)

    def _open_log_folder(self) -> None:
        path = config.config_dir()
        try:
            if sys.platform == "win32":
                os.startfile(path)  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            messagebox.showinfo("기록 폴더", f"{path}\n({e})")

    # ========================================================== 저장 정보 ===
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
        self._set_status("저장 정보가 삭제되었습니다.", "idle")

    # ========================================================= 자동 로그인 ===
    def _start_countdown(self) -> None:
        self.countdown_left = AUTO_LOGIN_DELAY_SEC
        self.stop_btn.configure(state="normal", text="취소")
        self._tick_countdown()

    def _tick_countdown(self) -> None:
        if self.countdown_left <= 0:
            self.countdown_job = None
            self.start()
            return
        self._set_status(f"저장된 정보로 {self.countdown_left}초 후 자동 로그인합니다. 취소하려면 [취소]를 누르세요.", "run")
        self.start_btn.configure(text=f"{self.countdown_left}초 후 자동 로그인…")
        self.progress.set((AUTO_LOGIN_DELAY_SEC - self.countdown_left + 1) / AUTO_LOGIN_DELAY_SEC)
        self.countdown_left -= 1
        self.countdown_job = self.root.after(1000, self._tick_countdown)

    def _cancel_countdown(self) -> bool:
        if self.countdown_job is None:
            return False
        self.root.after_cancel(self.countdown_job)
        self.countdown_job = None
        self.stop_btn.configure(state="disabled", text="중지")
        self.start_btn.configure(text="로그인하고 학습 시작")
        self.progress.set(0)
        return True

    # ================================================================ 실행 ===
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

        self.running_credentials = (user_id, password, bool(self.remember_var.get()))
        self.stop_event = threading.Event()
        self._reset_steps()
        self._set_running(True)
        self._set_status("브라우저를 여는 중입니다...", "run")
        self._log_file("----- 로그인 / 학습 시작 -----")
        self._watch_shortcuts(180)

        headless = os.environ.get("HUNET_HEADLESS") == "1"
        self.worker = threading.Thread(target=self._run_bot, args=(user_id, password, headless), daemon=True)
        self.worker.start()

    def stop(self) -> None:
        if self._cancel_countdown():
            self._set_status("자동 로그인을 취소했습니다.", "idle")
            self.log("자동 로그인을 취소했습니다.")
            return
        if self.worker and self.worker.is_alive():
            self.stop_event.set()
            self._set_status("중지하는 중...", "warn")

    # ---- 작업 스레드 (브라우저 조작) ----
    def _run_bot(self, user_id: str, password: str, headless: bool) -> None:
        bot = HunetBot(
            user_id,
            password,
            log=lambda m: self.queue.put(("log", m)),
            ask_2fa=self._ask_2fa_from_worker,
            on_login_success=lambda: self.queue.put(("login_ok", None)),
            on_step=lambda i, s, d: self.queue.put(("step", (i, s, d))),
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

    STEP_STATUS = {
        (0, "active"): ("로그인 중입니다...", "run"),
        (1, "active"): ("메인 화면에서 학습하기를 누르는 중...", "run"),
        (2, "active"): ("나의 강의실에서 과정별 현황을 확인하는 중...", "run"),
        (3, "active"): ("학습창을 여는 중...", "run"),
        (3, "done"): ("학습창을 열었습니다. 브라우저를 닫거나 [중지]를 누르면 종료됩니다.", "ok"),
        (3, "skip"): ("진행할 학습이 없습니다.", "ok"),
    }

    def _handle(self, kind: str, data) -> None:
        if kind == "detail":
            self._log_file(data)
        elif kind == "log":
            self.log(data)
        elif kind == "step":
            index, state, detail = data
            self._render_step(index, state, detail or None)
            if (index, state) in self.STEP_STATUS:
                text, k = self.STEP_STATUS[(index, state)]
                if (index, state) == (3, "skip") and detail:
                    text = f"{detail} — 진행할 학습이 없습니다."
                self._set_status(text, k)
        elif kind == "login_ok":
            self._save_credentials()
        elif kind == "ask_2fa":
            answered, holder, retry = data
            prompt = "등록된 휴대폰/이메일로 받은 인증번호를 입력하세요."
            if retry:
                prompt = "인증번호가 맞지 않습니다. 다시 입력하세요."
            holder["code"] = ctk.CTkInputDialog(text=prompt, title="본인인증").get_input()
            answered.set()
        elif kind == "login_failed":
            self._set_running(False)
            self._fail_running_steps(data)
            self._set_status(f"로그인 실패: {data}", "err")
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
            self._fail_running_steps(data)
            self._set_status(f"오류: {data}", "err")
            self.log(f"오류: {data}")
            if not self.closing:
                messagebox.showerror("오류", data)
        elif kind == "done":
            self._set_running(False)
            result: RunResult = data
            self.progress.set(1 if result.opened or (result.courses and not result.error) else 0)
            if result.error:
                self._set_status(f"오류로 종료: {result.error}", "err")
            elif result.opened:
                self._set_status(f"완료 — 학습창을 열었던 과정: {result.opened.title}", "ok")
            elif result.courses:
                self._set_status("모든 과정이 100% 완료되어 있습니다.", "ok")
            elif self.stop_event.is_set():
                self._set_status("중지되었습니다.", "warn")
            else:
                self._set_status("종료되었습니다.", "idle")
            self.log("브라우저가 종료되었습니다.")

    # ================================================================ 종료 ===
    def on_close(self) -> None:
        self._cancel_countdown()
        if self.worker and self.worker.is_alive():
            self.closing = True
            self.stop_event.set()
            self._set_status("브라우저를 닫는 중...", "warn")
            self._wait_worker_then_destroy(50)
        else:
            self._destroy()

    def _wait_worker_then_destroy(self, tries_left: int) -> None:
        if self.worker and self.worker.is_alive() and tries_left > 0:
            self.root.after(200, self._wait_worker_then_destroy, tries_left - 1)
        else:
            self._destroy()

    def _destroy(self) -> None:
        self.closing = True
        try:
            for line in cleanup.clean_all().lines():
                self._log_file(line)
        except Exception:
            pass
        for job in (self.poll_job, self.pulse_job, self.countdown_job):
            if job is not None:
                try:
                    self.root.after_cancel(job)
                except tk.TclError:
                    pass
        self.progress.stop()
        self.root.destroy()


def main() -> None:
    if sys.platform == "win32":
        try:
            import ctypes

            # 작업 표시줄에 파이썬 아이콘 대신 프로그램 아이콘이 보이도록
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("HunetAutoStudy")
        except Exception:
            pass
    ctk.set_appearance_mode("light")
    root = ctk.CTk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
