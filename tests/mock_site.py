"""테스트용 가짜 휴넷 사이트 (실제 화면 구조를 흉내 냄).

계정
  philips-123456789 / pass   → 바로 로그인
  philips-123456789 / 2fa    → 본인인증 팝업 (인증번호 111111)
그 외                        → "아이디 또는 비밀번호가 일치하지 않습니다." 알림

나의 강의실 목록은 MockState.courses 로 바꿀 수 있습니다.
"""

from __future__ import annotations

import html
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

LOGIN_HTML = """<!doctype html><html><head><meta charset="utf-8"><title>로그인</title>
<style>
 article.popup{position:fixed;left:0;top:0;width:100%;height:100%;background:#fff;}
</style></head>
<body>
<form action="/Login/LoginProcess" method="POST" id="loginForm" onsubmit="return onSubmit();">
  <input type="hidden" name="twoFactorNumber" id="twoFactorNumber" />
  <ul class="input-field">
    <li><label for="ID">아이디</label><input type="text" id="ID" name="ID" /></li>
    <li><label for="PW">비밀번호</label><input type="password" id="PW" name="PW" /></li>
  </ul>
  <button type="submit" class="btn-login">로그인</button>
  <input type="checkbox" id="cbxRememberId" /><label for="cbxRememberId">아이디기억</label>
  <article class="popup" id="twoFactorPopup" style="display:none;">
    <h3>본인인증</h3>
    <input type="text" name="userTwoFactorNumber" id="userTwoFactorNumber" />
    <button type="submit" class="btn primary big">인증 확인</button>
  </article>
</form>
<script>
  setTimeout(function(){ document.getElementById('ID').value = 'philips-'; }, 200);
  function onSubmit() {
    var id = document.getElementById('ID').value, pw = document.getElementById('PW').value;
    var pop = document.getElementById('twoFactorPopup');
    if (pop.style.display !== 'none') {
      if (document.getElementById('userTwoFactorNumber').value === '111111') { location.href = '/Edu/Home'; }
      else { alert('인증번호를 다시 확인해 주세요.'); }
      return false;
    }
    if (id === 'philips-123456789' && pw === 'pass') { location.href = '/Login/LoginProcess'; return false; }
    if (id === 'philips-123456789' && pw === '2fa') { pop.style.display = 'block'; return false; }
    alert('아이디 또는 비밀번호가 일치하지 않습니다.');
    return false;
  }
</script></body></html>"""

HOME_HTML = """<!doctype html><html><head><meta charset="utf-8"><title>Home</title>
<style>
 article.popup{position:fixed;left:100px;top:100px;width:900px;height:700px;background:#eee;z-index:10;}
</style></head><body>
<aside><a href="/Edu/ClassroomOnline/Ing">교육과정 학습현황</a></aside>
<section class="study-status">
  <h3>김태수님 학습현황</h3>
  <div>온라인교육</div>
  <p>[2026 법정필수교육] 성희롱 예방+개인정보보호+…</p>
  <div>진도율 : 100% (12일 남았습니다.)</div>
  <a href="/Edu/ClassroomOnline/Ing" class="btn">학습하기</a>
</section>
<article class="popup" data-popup-content="popup_1">
  <p>공지사항 팝업</p>
  <button class="btn-close" onclick="this.parentNode.style.display='none'"><div class="hide">닫기</div></button>
</article>
</body></html>"""

ROW_TEMPLATE = """
<li class="item">
  <div class="tit-area">
    <span class="badge">온라인</span> <span class="badge line">모바일 연동</span>
    <p class="tit"><a href="#">{title}</a></p>
    <ul class="info"><li>과정분류 : {category}</li><li>학습기간 : {period}</li></ul>
  </div>
  <div class="state"><span>{state}</span><br><strong>{pct}%</strong></div>
  <div class="manage"><a href="javascript:void(0)" class="btn red" onclick="fnStudyWindow({idx})"><span>학습하기</span> <i class="ico"></i></a></div>
</li>"""

CLASSROOM_HTML = """<!doctype html><html><head><meta charset="utf-8"><title>나의 강의실</title></head><body>
<aside><h2>나의 강의실</h2><ul><li>온라인교육 학습현황</li><li>교육이력</li></ul></aside>
<div class="tabs"><a>진행중 교육</a><a>대기중 교육</a><a>복습가능 교육</a></div>
<div class="list-head"><span>과정명</span><span>현황</span><span>관리</span></div>
<ul class="course-list" id="list"></ul>
<div class="floating"><a href="#">원격지원</a></div>
<script>
  var titles = {titles};
  function fnStudyWindow(idx) {{
    window.open('/Home/Index_2584.aspx?c=' + idx, 'studyWin', 'width=1010,height=676');
  }}
  // 실제 사이트처럼 목록을 조금 늦게 그림
  setTimeout(function(){{ document.getElementById('list').innerHTML = {rows}; }}, 700);
</script></body></html>"""

STUDY_HTML = """<!doctype html><html><head><meta charset="utf-8"><title>{title} - 회사</title></head>
<body><h1>{title}</h1><div>학습기간 : 2026-10-19(월) ~ 2026-11-30(월)</div><a class="btn">학습하기</a></body></html>"""


class MockState:
    courses = [
        {"title": "[2026 법정필수교육] 성희롱 예방+개인정보보호+직장 내 장애인 인식개선+직장 내 괴롭힘 예방",
         "category": "필수종합", "period": "2026-10-19 ~ 2026-11-30", "state": "수료", "pct": 100},
        {"title": "2026 안전보건교육 하반기(현장근로자_기타사업)_무재해",
         "category": "산업안전", "period": "2026-10-29 ~ 2026-12-17", "state": "학습중", "pct": 35},
    ]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # 조용히
        pass

    def _send(self, body: str, status: int = 200, location: str | None = None):
        data = body.encode("utf-8")
        self.send_response(status)
        if location:
            self.send_header("Location", location)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        path = url.path.lower()
        if path == "/edu/login/logingate":
            self._send(LOGIN_HTML)
        elif path == "/login/loginprocess":
            self._send("", 302, "/Edu/Home")
        elif path == "/edu/home":
            self._send(HOME_HTML)
        elif path == "/edu/classroomonline/ing":
            import json

            rows = "".join(
                ROW_TEMPLATE.format(idx=i, **{k: html.escape(str(v)) for k, v in c.items()})
                for i, c in enumerate(MockState.courses)
            )
            titles = [c["title"] for c in MockState.courses]
            self._send(CLASSROOM_HTML.format(rows=json.dumps(rows), titles=json.dumps(titles, ensure_ascii=False)))
        elif path == "/home/index_2584.aspx":
            idx = int(parse_qs(url.query).get("c", ["0"])[0])
            self._send(STUDY_HTML.format(title=html.escape(MockState.courses[idx]["title"])))
        else:
            self._send("not found", 404)


def start_server(port: int = 0) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


if __name__ == "__main__":
    srv = start_server(8765)
    print("mock site: http://127.0.0.1:8765/edu/Login/LoginGate")
    threading.Event().wait()
