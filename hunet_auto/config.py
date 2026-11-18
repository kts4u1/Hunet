"""아이디/비밀번호 저장 및 불러오기.

- 아이디와 '자동 로그인' 설정은 설정 파일(JSON)에 저장합니다.
- 비밀번호는 Windows 자격 증명 관리자(keyring)에 암호화되어 저장됩니다.
  keyring 을 쓸 수 없는 환경에서만 사용자 폴더의 파일에 저장합니다.
"""

from __future__ import annotations

import base64
import json
import os
import sys
from dataclasses import asdict, dataclass

APP_NAME = "HunetAutoStudy"
KEYRING_SERVICE = "HunetAutoStudy"


def config_dir() -> str:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    path = os.path.join(base, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def _settings_path() -> str:
    return os.path.join(config_dir(), "settings.json")


def _fallback_path() -> str:
    return os.path.join(config_dir(), "pw.dat")


@dataclass
class Settings:
    user_id: str = ""
    auto_login: bool = False


def load_settings() -> Settings:
    try:
        with open(_settings_path(), encoding="utf-8") as f:
            data = json.load(f)
        return Settings(user_id=str(data.get("user_id", "")), auto_login=bool(data.get("auto_login", False)))
    except (OSError, ValueError):
        return Settings()


def save_settings(settings: Settings) -> None:
    with open(_settings_path(), "w", encoding="utf-8") as f:
        json.dump(asdict(settings), f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- 비밀번호 ---

def _keyring():
    import keyring

    if sys.platform == "win32":
        # PyInstaller 로 만든 exe 에서도 확실히 동작하도록 Windows 백엔드를 직접 지정
        from keyring.backends import Windows

        keyring.set_keyring(Windows.WinVaultKeyring())
    return keyring


def save_password(user_id: str, password: str) -> None:
    try:
        _keyring().set_password(KEYRING_SERVICE, user_id, password)
        _remove_fallback()
        return
    except Exception:
        pass
    # keyring 을 쓸 수 없는 경우(일부 리눅스 환경 등)에만 사용
    with open(_fallback_path(), "w", encoding="utf-8") as f:
        json.dump({"user_id": user_id, "pw": base64.b64encode(password.encode()).decode()}, f)
    try:
        os.chmod(_fallback_path(), 0o600)
    except OSError:
        pass


def load_password(user_id: str) -> str:
    if not user_id:
        return ""
    try:
        pw = _keyring().get_password(KEYRING_SERVICE, user_id)
        if pw:
            return pw
    except Exception:
        pass
    try:
        with open(_fallback_path(), encoding="utf-8") as f:
            data = json.load(f)
        if data.get("user_id") == user_id:
            return base64.b64decode(data.get("pw", "")).decode()
    except (OSError, ValueError):
        pass
    return ""


def delete_password(user_id: str) -> None:
    if user_id:
        try:
            _keyring().delete_password(KEYRING_SERVICE, user_id)
        except Exception:
            pass
    _remove_fallback()


def _remove_fallback() -> None:
    try:
        os.remove(_fallback_path())
    except OSError:
        pass
