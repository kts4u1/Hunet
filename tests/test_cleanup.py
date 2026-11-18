"""웹앱 바로가기 정리 기능 검사: 이 프로그램용 프로필을 가리키는 바로가기만 지워야 함."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hunet_auto.cleanup import PROFILE_DIR_NAME, clean_folders  # noqa: E402


def fake_lnk(path, args):
    # 실제 .lnk 처럼 바이너리 헤더 + UTF-16LE 문자열
    with open(path, "wb") as f:
        f.write(b"L\x00\x00\x00\x01\x14\x02\x00" + b"\x00" * 64 + args.encode("utf-16-le") + b"\x00\x00")


root = tempfile.mkdtemp()
desktop = os.path.join(root, "Desktop")
programs = os.path.join(root, "Programs", "Edge Apps")
os.makedirs(desktop)
os.makedirs(programs)

old_temp = os.path.join(desktop, "https___web.yammer.com.lnk")
fake_lnk(old_temp, r'--user-data-dir="C:\Users\u\AppData\Local\Temp\playwright_chromiumdev_profile-AZXufE" --app-url=https://web.yammer.com/')
ours = os.path.join(programs, "Viva Engage.lnk")
fake_lnk(ours, rf'--user-data-dir="C:\Users\u\AppData\Local\HunetAutoStudy\{PROFILE_DIR_NAME}_msedge" --app-id=abc')
user_exe = os.path.join(desktop, "HunetAutoStudy.exe - 바로 가기.lnk")
fake_lnk(user_exe, r"C:\Users\u\Downloads\HunetAutoStudy.exe")
normal_edge = os.path.join(desktop, "Microsoft Edge.lnk")
fake_lnk(normal_edge, r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")

removed = clean_folders([desktop, os.path.join(root, "Programs")])
ok = (
    sorted(removed) == sorted([old_temp, ours])
    and os.path.exists(user_exe)
    and os.path.exists(normal_edge)
)
print("PASS 바로가기 정리" if ok else f"FAIL 바로가기 정리: {removed}")
sys.exit(0 if ok else 1)
