"""휴넷(필립스) 사이트 자동 조작.

진행 순서
  1. 로그인 페이지에서 아이디/비밀번호 입력 후 로그인 (본인인증 번호를 요구하면 사용자에게 입력받음)
  2. 메인 화면의 '학습하기' 클릭 → '나의 강의실(진행중 교육)' 이동
  3. 과정 목록에서 현황이 100% 가 아닌 과정을 찾아 관리의 '학습하기' 클릭
  4. 학습창(새 창)이 열리면 그 창을 앞으로 띄우고 대기
"""

from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

BASE_URL = os.environ.get("HUNET_BASE_URL", "https://philips.hunet.co.kr").rstrip("/")
LOGIN_URL = BASE_URL + "/edu/Login/LoginGate"
CLASSROOM_URL = BASE_URL + "/Edu/ClassroomOnline/Ing"

LOGIN_TIMEOUT_SEC = 40
LIST_TIMEOUT_SEC = 20
STUDY_POPUP_TIMEOUT_SEC = 30


class LoginError(Exception):
    """아이디/비밀번호 오류 등 로그인 실패."""


class BotStopped(Exception):
    """사용자가 중지함."""


@dataclass
class Course:
    index: int
    title: str
    percent: Optional[float]
    status: str
    row_text: str = ""

    @property
    def complete(self) -> bool:
        if self.percent is not None:
            return self.percent >= 100
        text = self.status or self.row_text
        return "수료" in text and "미수료" not in text

    def describe(self) -> str:
        pct = f"{self.percent:g}%" if self.percent is not None else "현황 미확인"
        return f"{self.title or '(과정명 미확인)'} [{pct}]"


@dataclass
class RunResult:
    courses: List[Course] = field(default_factory=list)
    opened: Optional[Course] = None
    study_title: str = ""
    study_url: str = ""
    error: str = ""


# 페이지 안의 '학습하기' 버튼을 모두 찾아 번호(data-hunet-auto)를 붙이고,
# 각 버튼이 속한 줄(과정)의 과정명 / 현황(%) 을 읽어 온다.
SCAN_STUDY_BUTTONS_JS = r"""
() => {
  const norm = s => (s || '').replace(/\s+/g, '');
  const visible = el => {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return false;
    const st = getComputedStyle(el);
    return st.visibility !== 'hidden' && st.display !== 'none';
  };
  const sel = 'a, button, input[type=button], input[type=submit], [onclick], [role=button]';
  let btns = Array.from(document.querySelectorAll(sel)).filter(el => {
    const t = norm(el.innerText || el.value);
    return t.length > 0 && t.length <= 12 && t.includes('학습하기') && visible(el);
  });
  // a 안에 span[onclick] 처럼 겹친 경우 바깥 요소 하나만 남김
  btns = btns.filter(el => !btns.some(o => o !== el && o.contains(el)));

  document.querySelectorAll('[data-hunet-auto]').forEach(e => e.removeAttribute('data-hunet-auto'));
  const countIn = el => btns.filter(b => el.contains(b)).length;
  const pctRe = /(\d{1,3}(?:\.\d+)?)\s*%/g;
  const lastPct = text => {
    const m = [...(text || '').matchAll(pctRe)];
    return m.length ? parseFloat(m[m.length - 1][1]) : null;
  };
  const skipLine = /^(온라인|오프라인|모바일\s*연동|학습하기|복습하기|수료|미수료|진행중|학습중|대기|과정분류|학습기간|[•·\-]|\d{1,3}(\.\d+)?\s*%)/;

  return btns.map((btn, i) => {
    btn.setAttribute('data-hunet-auto', String(i));

    // 현황: 버튼에서 위로 올라가며 % 가 처음 나오는 영역 (다른 학습하기 버튼은 포함하지 않아야 함)
    let pctBox = null;
    for (let el = btn.parentElement, d = 0; el && el !== document.body && d < 10 && countIn(el) === 1; el = el.parentElement, d++) {
      if (/\d\s*%/.test(el.innerText || '')) { pctBox = el; break; }
    }

    // 과정 한 줄 전체: 이 버튼 하나만 포함하는 가장 큰 영역
    let row = btn;
    while (true) {
      if (row.tagName === 'TR' || (row.tagName === 'LI' && (row.innerText || '').length > 20)) break;
      const p = row.parentElement;
      if (!p || p === document.body || p === document.documentElement) break;
      if (countIn(p) !== 1) break;
      const pText = p.innerText || '';
      if (pText.length > 1500) break;
      if (pText.includes('과정명') && !(row.innerText || '').includes('과정명')) break;
      row = p;
    }

    const rowText = row.innerText || '';
    const lines = rowText.split('\n').map(s => s.trim()).filter(Boolean);
    const titleCands = lines.filter(l => !skipLine.test(l) && !/[:：]/.test(l.slice(0, 8)));
    const title = titleCands.sort((a, b) => b.length - a.length)[0] || '';

    let percent = pctBox ? lastPct(pctBox.innerText) : null;
    if (percent === null) percent = lastPct(rowText);

    let status = '';
    for (let k = lines.length - 1; k >= 0; k--) {
      if (/\d\s*%/.test(lines[k])) {
        status = (k > 0 && lines[k - 1].length <= 6 ? lines[k - 1] + ' ' : '') + lines[k];
        break;
      }
    }
    if (!status) status = lines.filter(l => /수료|진행|학습중|미학습/.test(l) && l.length <= 10).join(' ');

    return { index: i, title, percent, status, rowText: rowText.slice(0, 400) };
  });
}
"""

# 화면을 가리는 공지 레이어 팝업 닫기
CLOSE_LAYER_POPUPS_JS = r"""
() => {
  let closed = 0;
  document.querySelectorAll('article.popup, .layer-popup, .layerPopup, .pop-layer').forEach(p => {
    if (p.id === 'twoFactorPopup') return;
    const st = getComputedStyle(p);
    if (st.display === 'none' || st.visibility === 'hidden') return;
    const r = p.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return;
    const btn = p.querySelector('.btn-close, .close, .btn_close, [onclick*="close" i], [onclick*="Close"]');
    if (btn) { btn.click(); closed++; }
  });
  return closed;
}
"""


class HunetBot:
    def __init__(
        self,
        user_id: str,
        password: str,
        log: Callable[[str], None] = print,
        ask_2fa: Optional[Callable[[bool], Optional[str]]] = None,
        on_login_success: Optional[Callable[[], None]] = None,
        on_step: Optional[Callable[[int, str, str], None]] = None,
        stop_event: Optional[threading.Event] = None,
        headless: bool = False,
        keep_open: bool = True,
    ):
        self.user_id = user_id
        self.password = password
        self.log = log
        self.ask_2fa = ask_2fa
        self.on_login_success = on_login_success
        self.on_step = on_step
        self._active_step: Optional[int] = None
        self.stop_event = stop_event or threading.Event()
        self.headless = headless
        self.keep_open = keep_open

        self.browser = None
        self.context = None
        self.page: Optional[Page] = None
        self.last_dialog: Optional[str] = None
        self._dialog_pages: list = []

    # ------------------------------------------------------------ 공통 ---
    def _step(self, index: int, state: str, detail: str = "") -> None:
        """진행 단계 알림. index: 0 로그인, 1 메인 화면, 2 나의 강의실, 3 학습창
        state: active / done / skip / error"""
        self._active_step = index if state == "active" else None
        if self.on_step:
            self.on_step(index, state, detail)

    def _fail_active_step(self, detail: str = "") -> None:
        if self._active_step is not None:
            self._step(self._active_step, "error", detail)

    def _check_stop(self) -> None:
        if self.stop_event.is_set():
            raise BotStopped()

    def _sleep(self, ms: int, page: Optional[Page] = None) -> None:
        """Playwright 이벤트(알림창 등)를 처리하면서 대기."""
        self._check_stop()
        (page or self.page).wait_for_timeout(ms)

    def _attach_dialog_handler(self, page: Page) -> None:
        if page in self._dialog_pages:
            return
        self._dialog_pages.append(page)
        page.on("dialog", self._on_dialog)

    def _on_dialog(self, dialog) -> None:
        msg = (dialog.message or "").strip()
        self.last_dialog = msg
        self.log(f"[사이트 알림] {msg}")
        try:
            dialog.accept()
        except PlaywrightError:
            pass

    def _is_visible(self, selector: str) -> bool:
        try:
            return self.page.locator(selector).first.is_visible()
        except PlaywrightError:
            return False

    def _close_layer_popups(self) -> None:
        try:
            n = self.page.evaluate(CLOSE_LAYER_POPUPS_JS)
            if n:
                self.log(f"공지 팝업 {n}개를 닫았습니다.")
                self._sleep(500)
        except PlaywrightError:
            pass

    def _wait_quiet(self, timeout_ms: int = 10000) -> None:
        try:
            self.page.wait_for_load_state("networkidle", timeout=timeout_ms)
        except PlaywrightTimeout:
            pass

    def _scan_study_buttons(self) -> List[Course]:
        raw = self.page.evaluate(SCAN_STUDY_BUTTONS_JS)
        return [
            Course(
                index=int(r["index"]),
                title=(r.get("title") or "").strip(),
                percent=r.get("percent"),
                status=(r.get("status") or "").strip(),
                row_text=r.get("rowText") or "",
            )
            for r in raw
        ]

    def _click_marked(self, index: int) -> None:
        loc = self.page.locator(f'[data-hunet-auto="{index}"]').first
        try:
            loc.scroll_into_view_if_needed(timeout=5000)
        except PlaywrightError:
            pass
        try:
            loc.click(timeout=8000)
        except PlaywrightError:
            self.log("버튼이 가려져 있어 스크립트로 다시 클릭합니다.")
            loc.evaluate("el => el.click()")

    # ------------------------------------------------------- 브라우저 ---
    def _launch_browser(self, pw):
        args = [] if self.headless else ["--start-maximized"]
        attempts = []
        custom = os.environ.get("HUNET_BROWSER_PATH")
        if custom:
            attempts.append(("지정한 브라우저", {"executable_path": custom}))
        attempts += [
            ("Microsoft Edge", {"channel": "msedge"}),
            ("Google Chrome", {"channel": "chrome"}),
            ("Chromium", {}),
        ]
        last_error = None
        for name, kwargs in attempts:
            try:
                browser = pw.chromium.launch(headless=self.headless, args=args, **kwargs)
                self.log(f"브라우저 실행: {name}")
                return browser
            except PlaywrightError as e:
                last_error = e
        raise RuntimeError(
            "브라우저를 실행할 수 없습니다. Microsoft Edge 또는 Chrome 이 설치되어 있는지 확인하세요.\n"
            f"({last_error})"
        )

    # ------------------------------------------------------- 1. 로그인 ---
    def login(self) -> None:
        page = self.page
        self._step(0, "active", self.user_id)
        self.log("로그인 페이지에 접속합니다...")
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_selector("#ID", state="visible", timeout=30000)
        self._sleep(500)  # 사이트 스크립트가 아이디 칸에 'philips-' 를 채우는 동작이 끝나도록 대기
        self._close_layer_popups()

        page.fill("#ID", self.user_id)
        page.fill("#PW", self.password)
        self.last_dialog = None
        self.log(f"로그인 시도: {self.user_id}")
        try:
            page.click("button.btn-login", timeout=5000)
        except PlaywrightError:
            page.press("#PW", "Enter")

        self._wait_login_result()
        self.log("로그인 성공!")
        self._step(0, "done", self.user_id)
        if self.on_login_success:
            self.on_login_success()

    def _wait_login_result(self) -> None:
        page = self.page
        deadline = time.time() + LOGIN_TIMEOUT_SEC
        twofa_tries = 0
        twofa_submitted = False
        while time.time() < deadline:
            self._check_stop()
            if "/login" not in page.url.lower():
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=30000)
                except PlaywrightTimeout:
                    pass
                return

            dialog = self.last_dialog
            twofa_visible = self._is_visible("#twoFactorPopup")
            if dialog and not twofa_visible:
                raise LoginError(dialog)

            if twofa_visible and (not twofa_submitted or dialog):
                if self.ask_2fa is None:
                    raise LoginError("본인인증(인증번호 입력)이 필요합니다.")
                if twofa_tries >= 3:
                    raise LoginError("본인인증 번호가 3회 틀렸습니다.")
                twofa_tries += 1
                self.last_dialog = None
                self.log("본인인증 번호 입력이 필요합니다. (휴대폰/이메일 확인)")
                code = self.ask_2fa(dialog is not None)
                self._check_stop()
                if not code:
                    raise LoginError("본인인증 번호 입력이 취소되었습니다.")
                page.fill("#userTwoFactorNumber", code.strip())
                page.click("#twoFactorPopup button[type=submit]")
                twofa_submitted = True
                deadline = time.time() + LOGIN_TIMEOUT_SEC

            self._sleep(300)
        raise LoginError("로그인 응답 시간이 초과되었습니다. 인터넷 연결을 확인하세요.")

    # --------------------------------------------- 2. 메인 → 나의 강의실 ---
    def open_classroom(self) -> None:
        self._step(1, "active")
        self._open_classroom()
        self._step(1, "done")

    def _open_classroom(self) -> None:
        page = self.page
        self.log("메인 화면을 불러오는 중...")
        self._wait_quiet(15000)
        self._close_layer_popups()
        if "classroomonline" in page.url.lower():
            return

        buttons = self._scan_study_buttons()
        if buttons:
            self.log("메인 화면의 '학습하기' 버튼을 클릭합니다.")
            popups: list = []

            def on_popup(p):
                popups.append(p)

            page.on("popup", on_popup)
            try:
                self._click_marked(buttons[0].index)
                try:
                    page.wait_for_url(re.compile(r"ClassroomOnline", re.I), timeout=15000)
                except PlaywrightTimeout:
                    pass
            finally:
                page.remove_listener("popup", on_popup)
            if "classroomonline" in page.url.lower():
                return
            for p in popups:
                try:
                    p.close()
                except PlaywrightError:
                    pass
            self.log("나의 강의실 화면이 열리지 않아 주소로 직접 이동합니다.")
        else:
            self.log("메인 화면에서 '학습하기' 버튼을 찾지 못해 나의 강의실로 직접 이동합니다.")
        page.goto(CLASSROOM_URL, wait_until="domcontentloaded", timeout=60000)

    # -------------------------------------------- 3. 과정 목록 / 현황 확인 ---
    def read_courses(self) -> List[Course]:
        self._step(2, "active")
        courses = self._read_courses()
        todo = sum(1 for c in courses if not c.complete)
        self._step(2, "done", f"진행중 {len(courses)}개 · 미완료 {todo}개" if courses else "진행중 교육 없음")
        return courses

    def _read_courses(self) -> List[Course]:
        self.log("나의 강의실(진행중 교육) 목록을 확인합니다...")
        self._wait_quiet(15000)
        self._close_layer_popups()
        deadline = time.time() + LIST_TIMEOUT_SEC
        courses: List[Course] = []
        while time.time() < deadline:
            courses = self._scan_study_buttons()
            if courses:
                break
            self._sleep(500)
        if not courses:
            self.log("진행중인 교육(학습하기 버튼)이 없습니다.")
            return []
        self.log(f"진행중 교육 {len(courses)}개:")
        for c in courses:
            mark = "완료" if c.complete else "미완료"
            self.log(f"  - [{mark}] {c.describe()}")
        return courses

    # --------------------------------------------------- 4. 학습창 열기 ---
    def open_study(self, course: Course) -> Page:
        page = self.page
        self._step(3, "active", course.title)
        self.log(f"'{course.title}' 과정의 학습하기를 클릭합니다.")
        popups: list = []

        def on_popup(p):
            popups.append(p)

        page.on("popup", on_popup)
        start_url = page.url
        self.last_dialog = None
        try:
            self._click_marked(course.index)
            deadline = time.time() + STUDY_POPUP_TIMEOUT_SEC
            while time.time() < deadline and not popups:
                if page.url != start_url and "classroomonline" not in page.url.lower():
                    break
                self._sleep(300)
        finally:
            page.remove_listener("popup", on_popup)

        if popups:
            study = popups[-1]
        elif page.url != start_url and "classroomonline" not in page.url.lower():
            study = page
        else:
            reason = f" (사이트 알림: {self.last_dialog})" if self.last_dialog else ""
            raise RuntimeError("학습창이 열리지 않았습니다." + reason)

        try:
            study.wait_for_load_state("domcontentloaded", timeout=30000)
        except PlaywrightTimeout:
            pass
        try:
            study.bring_to_front()
        except PlaywrightError:
            pass
        title = ""
        try:
            title = study.title()
        except PlaywrightError:
            pass
        self.log(f"학습창이 열렸습니다: {title or study.url}")
        self._step(3, "done", course.title)
        return study

    # ------------------------------------------------------- 대기 ---
    def hold(self) -> None:
        if self.browser is None or self.context is None:
            return
        self.log("여기까지 완료. 브라우저를 닫거나 [중지]를 누르면 종료됩니다.")
        while not self.stop_event.is_set():
            if not self.browser.is_connected():
                break
            pages = [p for p in self.context.pages if not p.is_closed()]
            if not pages:
                break
            try:
                pages[-1].wait_for_timeout(1000)
            except PlaywrightError:
                time.sleep(0.2)

    # ------------------------------------------------------- 실행 ---
    def run(self) -> RunResult:
        result = RunResult()
        with sync_playwright() as pw:
            self.browser = self._launch_browser(pw)
            try:
                if self.headless:
                    self.context = self.browser.new_context(locale="ko-KR", viewport={"width": 1600, "height": 1000})
                else:
                    self.context = self.browser.new_context(locale="ko-KR", no_viewport=True)
                self.context.on("page", self._attach_dialog_handler)
                self.page = self.context.new_page()
                self._attach_dialog_handler(self.page)

                self.login()
                self._check_stop()
                self.open_classroom()
                self._check_stop()
                result.courses = self.read_courses()

                todo = [c for c in result.courses if not c.complete]
                if not result.courses:
                    self._step(3, "skip", "진행중 교육 없음")
                elif not todo:
                    self.log("모든 과정의 현황이 100% 입니다. 진행할 학습이 없습니다.")
                    self._step(3, "skip", "모든 과정 100% 완료")
                elif todo:
                    if len(todo) > 1:
                        self.log(f"미완료 과정 {len(todo)}개 중 첫 번째 과정부터 진행합니다.")
                    target = todo[0]
                    study = self.open_study(target)
                    result.opened = target
                    result.study_url = study.url
                    try:
                        result.study_title = study.title()
                    except PlaywrightError:
                        pass

                if self.keep_open:
                    self.hold()
            except BotStopped:
                self._fail_active_step("중지됨")
                self.log("사용자가 중지했습니다.")
            except LoginError as e:
                self._fail_active_step(str(e))
                raise
            except Exception as e:  # 로그인 이후 단계 오류: 브라우저는 열어 두고 사용자가 직접 진행 가능
                if not self.keep_open:
                    raise
                result.error = str(e)
                self._fail_active_step(str(e))
                self.log(f"오류: {e}")
                self.log("브라우저는 열어 둡니다. 직접 진행하거나 [중지]를 눌러 종료하세요.")
                try:
                    self.hold()
                except BotStopped:
                    pass
            finally:
                try:
                    self.browser.close()
                except PlaywrightError:
                    pass
        return result

