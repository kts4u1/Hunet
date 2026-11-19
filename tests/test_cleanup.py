"""웹앱 바로가기 정리 기능 검사: 자동화 프로필이 만든 바로가기만 지워야 함."""

import os
import stat
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hunet_auto.cleanup import PROFILE_DIR_NAME, clean_folders  # noqa: E402


def fake_lnk(path, args, odd=False):
    # 실제 .lnk 처럼 바이너리 헤더 + UTF-16LE 문자열 (odd=True 면 홀수 바이트 위치에서 시작)
    with open(path, "wb") as f:
        f.write(b"L\x00\x00\x00\x01\x14\x02\x00" + b"\x00" * (65 if odd else 64) + args.encode("utf-16-le") + b"\x00\x00")


root = tempfile.mkdtemp()
desktop = os.path.join(root, "Desktop")
programs = os.path.join(root, "Programs", "Edge Apps")
os.makedirs(desktop)
os.makedirs(programs)
edge = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge_proxy.exe"

old_temp = os.path.join(desktop, "https   web.yammer.com.lnk")
fake_lnk(old_temp, edge + r' --user-data-dir="C:\Users\u\AppData\Local\Temp\playwright_chromiumdev_profile-AZXufE" '
                          r'--profile-directory=Default --app-id=jljg --app-url=https://web.yammer.com/', odd=True)
ours = os.path.join(programs, "Viva Engage.lnk")
fake_lnk(ours, edge + rf' --user-data-dir="C:\Users\u\AppData\Local\HunetAutoStudy\{PROFILE_DIR_NAME}_msedge" --app-id=abc')
os.chmod(ours, stat.S_IREAD)  # 읽기 전용이어도 지워야 함
dead_temp = os.path.join(desktop, "Some App.lnk")
fake_lnk(dead_temp, edge + r' --user-data-dir="C:\Users\u\AppData\Local\Temp\other_tool_profile_123" --app-id=zzz')
user_pwa = os.path.join(desktop, "Outlook (PWA).lnk")
fake_lnk(user_pwa, edge + " --profile-directory=Default --app-id=outlook")
user_exe = os.path.join(desktop, "HunetAutoStudy.exe - 바로 가기.lnk")
fake_lnk(user_exe, r"C:\Users\u\Downloads\HunetAutoStudy.exe")
normal_edge = os.path.join(desktop, "Microsoft Edge.lnk")
fake_lnk(normal_edge, r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")

report = clean_folders([desktop, os.path.join(root, "Programs"), os.path.join(root, "없는폴더")])
for line in report.lines():
    print("  " + line)
removed = sorted(s.path for s in report.removed)
checks = {
    "자동화 프로필 바로가기 정리": removed == sorted([old_temp, ours, dead_temp]),
    "실패 없음": not report.failed,
    "사용자 웹앱/바로가기 유지": all(os.path.exists(p) for p in (user_pwa, user_exe, normal_edge)),
    "검사 내역 기록": report.folders[0].lnk_count == 5 and not report.folders[2].exists,
}
for name, ok in checks.items():
    print(("PASS " if ok else "FAIL ") + name)
sys.exit(0 if all(checks.values()) else 1)
