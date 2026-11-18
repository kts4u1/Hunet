"""가짜 사이트로 전체 흐름(로그인 → 나의 강의실 → 미완료 과정 학습창 열기)을 검사합니다.

실행:  python tests/test_flow.py
(브라우저 경로를 지정하려면 HUNET_BROWSER_PATH 환경변수 사용)
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import mock_site  # noqa: E402

server = mock_site.start_server()
os.environ["HUNET_BASE_URL"] = f"http://127.0.0.1:{server.server_address[1]}"

from hunet_auto.bot import HunetBot, LoginError  # noqa: E402

ORIGINAL = [dict(c) for c in mock_site.MockState.courses]
failures = []


def run_bot(password="pass", ask_2fa=None):
    logs = []
    bot = HunetBot("philips-123456789", password, log=logs.append, ask_2fa=ask_2fa, headless=True, keep_open=False)
    return bot.run(), logs


def check(name, cond, logs=None):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)
        for line in logs or []:
            print("    | " + line)


# 1. 정상: 두 번째(35%) 과정의 학습창이 열려야 함
mock_site.MockState.courses = [dict(c) for c in ORIGINAL]
res, logs = run_bot()
check("과정 2개 인식", len(res.courses) == 2, logs)
check("현황 % 인식", [c.percent for c in res.courses] == [100, 35], logs)
check("과정명 인식", res.courses and res.courses[1].title.startswith("2026 안전보건교육"), logs)
check("미완료 과정 학습창 열림", res.opened is not None and "안전보건" in res.study_title, logs)
check("공지 팝업 닫기", any("공지 팝업" in l for l in logs), logs)

# 2. 비밀번호 오류 → LoginError
try:
    run_bot(password="wrong")
    check("비밀번호 오류 감지", False)
except LoginError as e:
    check("비밀번호 오류 감지", "일치하지 않습니다" in str(e))

# 3. 본인인증: 처음엔 틀린 번호, 두 번째 맞는 번호
asked = []


def ask(retry):
    asked.append(retry)
    return "000000" if len(asked) == 1 else "111111"


res, logs = run_bot(password="2fa", ask_2fa=ask)
check("본인인증 재입력 후 로그인", asked == [False, True] and res.opened is not None, logs)

# 4. 모두 100% → 학습창 열지 않음
mock_site.MockState.courses = [dict(c, pct=100, state="수료") for c in ORIGINAL]
res, logs = run_bot()
check("모두 완료 시 학습창 안 열림", len(res.courses) == 2 and res.opened is None, logs)

# 5. 과정 1개(미완료)만 있는 경우
mock_site.MockState.courses = [dict(ORIGINAL[0], pct=0, state="미학습")]
res, logs = run_bot()
check("과정 1개 미완료 인식", len(res.courses) == 1 and res.courses[0].percent == 0 and res.opened is not None, logs)

server.shutdown()
print()
print("모든 테스트 통과" if not failures else f"실패 {len(failures)}건: {failures}")
sys.exit(1 if failures else 0)
