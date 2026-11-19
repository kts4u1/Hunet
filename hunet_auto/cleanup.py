"""자동화용 Edge 프로필이 만든 웹앱 바로가기 정리.

회사 PC 의 Edge 정책이 새 브라우저 프로필마다 웹앱(예: Yammer)을 강제로 설치하면서
바탕화면/시작 메뉴에 바로가기를 만듭니다. 다음 바로가기만 골라서 지웁니다.
  1. 이 프로그램이 쓰는 브라우저 프로필을 가리키는 바로가기
  2. Playwright 임시 프로필을 가리키는 바로가기 (예전 버전이 실행할 때마다 생성)
  3. 이미 지워진 임시(Temp) 폴더 프로필을 가리키는 웹앱 바로가기 (눌러도 동작하지 않는 바로가기)
일반 Edge 바로가기, 사용자가 직접 만든 바로가기는 건드리지 않습니다.
"""

from __future__ import annotations

import os
import re
import stat
import sys
from dataclasses import dataclass, field
from typing import Iterable, List, Optional

PROFILE_DIR_NAME = "hunet_auto_browser_profile"  # 이 프로그램 전용 브라우저 프로필 폴더 이름
MARKERS = [
    "playwright_chromiumdev_profile",
    PROFILE_DIR_NAME,
]

_USER_DATA_DIR_RE = re.compile(r'--user-data-dir=(?:"([^"]+)"|(\S+))', re.I)


@dataclass
class ShortcutInfo:
    path: str
    is_web_app: bool = False
    user_data_dir: str = ""
    reason: str = ""  # 지울 이유 (없으면 유지)
    action: str = ""  # 정리함 / 정리 실패: ... / 유지


@dataclass
class FolderReport:
    folder: str
    exists: bool
    lnk_count: int = 0
    web_apps: List[ShortcutInfo] = field(default_factory=list)


@dataclass
class CleanReport:
    folders: List[FolderReport] = field(default_factory=list)

    @property
    def removed(self) -> List[ShortcutInfo]:
        return [s for f in self.folders for s in f.web_apps if s.action == "정리함"]

    @property
    def failed(self) -> List[ShortcutInfo]:
        return [s for f in self.folders for s in f.web_apps if s.action.startswith("정리 실패")]

    def lines(self) -> List[str]:
        out = []
        for f in self.folders:
            if not f.exists:
                out.append(f"[바로가기 검사] {f.folder} — 폴더 없음")
                continue
            out.append(f"[바로가기 검사] {f.folder} — 바로가기 {f.lnk_count}개, 웹앱 {len(f.web_apps)}개")
            for s in f.web_apps:
                profile = s.user_data_dir or "(기본 Edge 프로필)"
                why = f" ({s.reason})" if s.reason else ""
                out.append(f"    - {os.path.basename(s.path)} | 프로필: {profile} | {s.action}{why}")
        return out


def _decode_utf16(data: bytes) -> str:
    # .lnk 안의 문자열은 UTF-16LE. 짝/홀 바이트 위치 모두 시도
    return data.decode("utf-16-le", errors="ignore") + "\n" + data[1:].decode("utf-16-le", errors="ignore")


def inspect_shortcut(path: str) -> Optional[ShortcutInfo]:
    try:
        with open(path, "rb") as f:
            data = f.read(256 * 1024)
    except OSError:
        return None
    text = _decode_utf16(data)
    lower = text.lower()
    info = ShortcutInfo(path=path, is_web_app="--app-id=" in lower)
    m = _USER_DATA_DIR_RE.search(text)
    if m:
        info.user_data_dir = (m.group(1) or m.group(2) or "").strip()

    raw = data.lower()
    for marker in MARKERS:
        mk = marker.lower()
        if mk in lower or mk.encode("ascii") in raw:
            info.reason = f"자동화 프로필({marker})"
            return info
    udd = info.user_data_dir.lower()
    if info.is_web_app and udd and ("\\temp\\" in udd or "/tmp/" in udd) and not os.path.isdir(info.user_data_dir):
        info.reason = "이미 지워진 임시 프로필"
    return info


def _delete(path: str) -> str:
    try:
        os.chmod(path, stat.S_IWRITE)  # 읽기 전용이면 해제
    except OSError:
        pass
    try:
        os.remove(path)
        return "정리함"
    except OSError as e:
        return f"정리 실패: {e}"


def clean_folders(folders: Iterable[str], max_depth: int = 3, dry_run: bool = False) -> CleanReport:
    report = CleanReport()
    for root in folders:
        fr = FolderReport(folder=root, exists=bool(root) and os.path.isdir(root))
        report.folders.append(fr)
        if not fr.exists:
            continue
        base_depth = root.rstrip("\\/").count(os.sep)
        for dirpath, dirnames, filenames in os.walk(root):
            if dirpath.count(os.sep) - base_depth >= max_depth:
                dirnames[:] = []
            for name in filenames:
                if not name.lower().endswith(".lnk"):
                    continue
                fr.lnk_count += 1
                info = inspect_shortcut(os.path.join(dirpath, name))
                if info is None or not (info.is_web_app or info.reason):
                    continue
                if info.reason:
                    info.action = "정리 대상" if dry_run else _delete(info.path)
                else:
                    info.action = "유지"
                fr.web_apps.append(info)
    return report


def _shell_folder(csidl: int) -> str:
    import ctypes

    buf = ctypes.create_unicode_buffer(1024)
    if ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf) == 0:
        return buf.value
    return ""


def shortcut_folders() -> List[str]:
    if sys.platform != "win32":
        return []
    folders = []
    # 바탕화면, 시작 메뉴\프로그램, 공용 바탕화면, 공용 시작 메뉴\프로그램
    for csidl in (0x0010, 0x0002, 0x0019, 0x0017):
        try:
            folders.append(_shell_folder(csidl))
        except Exception:
            pass
    home = os.environ.get("USERPROFILE", "")
    if home:
        folders.append(os.path.join(home, "Desktop"))
        try:  # OneDrive 로 옮겨진 바탕화면 (예: OneDrive - 회사명\Desktop)
            for name in os.listdir(home):
                if name.lower().startswith("onedrive"):
                    folders.append(os.path.join(home, name, "Desktop"))
                    folders.append(os.path.join(home, name, "바탕 화면"))
        except OSError:
            pass
    seen, unique = set(), []
    for f in folders:
        if not f:
            continue
        key = os.path.normcase(os.path.abspath(f))
        if key not in seen and os.path.isdir(f):
            seen.add(key)
            unique.append(f)
    return unique


def _clean_uninstall_entries() -> int:
    """'설치된 앱' 목록에 남은, 자동화 프로필의 웹앱 항목 제거."""
    if sys.platform != "win32":
        return 0
    import winreg

    markers = [m.lower() for m in MARKERS]
    path = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
    removed = 0
    try:
        root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ | winreg.KEY_WRITE)
    except OSError:
        return 0
    with root:
        names = []
        i = 0
        while True:
            try:
                names.append(winreg.EnumKey(root, i))
            except OSError:
                break
            i += 1
        for name in names:
            try:
                with winreg.OpenKey(root, name) as key:
                    values = []
                    for value_name in ("UninstallString", "DisplayIcon", "InstallLocation", "ModifyPath"):
                        try:
                            values.append(str(winreg.QueryValueEx(key, value_name)[0]).lower())
                        except OSError:
                            pass
                text = " ".join(values)
                if any(m in text for m in markers):
                    winreg.DeleteKey(root, name)
                    removed += 1
            except OSError:
                pass
    return removed


def clean_all() -> CleanReport:
    """바탕화면/시작 메뉴의 바로가기와 설치된 앱 항목 정리. 예외를 내지 않음."""
    try:
        report = clean_folders(shortcut_folders())
    except Exception as e:
        report = CleanReport(folders=[FolderReport(folder=f"(검사 오류: {e})", exists=False)])
    try:
        _clean_uninstall_entries()
    except Exception:
        pass
    return report
