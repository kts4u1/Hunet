"""자동화용 Edge 프로필이 만든 웹앱 바로가기 정리.

회사 PC 의 Edge 정책이 새 브라우저 프로필마다 웹앱(예: Yammer)을 강제로 설치하면서
바탕화면/시작 메뉴에 바로가기를 만듭니다. 이 프로그램이 쓰는 프로필을 가리키는
바로가기만 골라서 지웁니다. (일반 Edge 나 다른 프로그램의 바로가기는 건드리지 않음)
"""

from __future__ import annotations

import os
import sys
from typing import Iterable, List

# 바로가기(.lnk) 안의 실행 인자에 이 문자열이 들어 있으면 이 프로그램이 만든 것으로 판단
PROFILE_DIR_NAME = "hunet_auto_browser_profile"  # 이 프로그램 전용 브라우저 프로필 폴더 이름
MARKERS = [
    "playwright_chromiumdev_profile",  # Playwright 임시 프로필 (예전 버전에서 매번 생성)
    PROFILE_DIR_NAME,
]


def _encoded_markers() -> List[bytes]:
    out = []
    for m in MARKERS:
        m = m.lower()
        out.append(m.encode("utf-16-le"))
        out.append(m.encode("ascii"))
    return out


def is_our_shortcut(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            data = f.read(256 * 1024).lower()
    except OSError:
        return False
    return any(m in data for m in _encoded_markers())


def clean_folders(folders: Iterable[str], max_depth: int = 3) -> List[str]:
    """폴더(하위 폴더 포함)에서 이 프로그램용 프로필을 가리키는 .lnk 를 지우고 지운 경로를 돌려줌."""
    removed = []
    for root in folders:
        if not root or not os.path.isdir(root):
            continue
        base_depth = root.rstrip("\\/").count(os.sep)
        for dirpath, dirnames, filenames in os.walk(root):
            if dirpath.count(os.sep) - base_depth >= max_depth:
                dirnames[:] = []
            for name in filenames:
                if not name.lower().endswith(".lnk"):
                    continue
                path = os.path.join(dirpath, name)
                if is_our_shortcut(path):
                    try:
                        os.remove(path)
                        removed.append(path)
                    except OSError:
                        pass
    return removed


def _shell_folder(csidl: int) -> str:
    import ctypes

    buf = ctypes.create_unicode_buffer(260)
    if ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf) == 0:
        return buf.value
    return ""


def shortcut_folders() -> List[str]:
    if sys.platform != "win32":
        return []
    folders = []
    for csidl in (0x0010, 0x0002):  # 바탕화면, 시작 메뉴\프로그램
        try:
            folders.append(_shell_folder(csidl))
        except Exception:
            pass
    home = os.environ.get("USERPROFILE", "")
    if home:
        folders.append(os.path.join(home, "Desktop"))
    seen, unique = set(), []
    for f in folders:
        key = os.path.normcase(os.path.abspath(f)) if f else ""
        if f and key not in seen:
            seen.add(key)
            unique.append(f)
    return unique


def _clean_uninstall_entries() -> int:
    """'설치된 앱' 목록에 남은, 이 프로그램용 프로필의 웹앱 항목 제거."""
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


def remove_browser_app_shortcuts() -> int:
    """바로가기와 설치된 앱 항목을 정리하고 정리한 개수를 돌려줌. 실패해도 예외를 내지 않음."""
    count = 0
    try:
        count += len(clean_folders(shortcut_folders()))
    except Exception:
        pass
    try:
        count += _clean_uninstall_entries()
    except Exception:
        pass
    return count
