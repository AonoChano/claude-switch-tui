import base64
import atexit
import ctypes
import ctypes.wintypes
import json
import locale
import os
import random
import re
import signal
import shutil
import tempfile
import time
import urllib.error
import urllib.request
try:
    import msvcrt
    HAS_MSVCRT = True
except ImportError:
    msvcrt = None
    HAS_MSVCRT = False
import sys
import subprocess
import threading
import unicodedata
import uuid
import webbrowser
import zipfile
from pathlib import Path
from rich.console import Console, Group
from rich.table import Table
from rich.live import Live
from rich.panel import Panel
from rich.text import Text
from rich.markup import escape
from rich.padding import Padding
from rich import box

try:
    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.keys import Keys
    from prompt_toolkit.layout import Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.mouse_events import MouseEventType
    from prompt_toolkit.styles import Style
    HAS_PROMPT_TOOLKIT = True
except ImportError:
    HAS_PROMPT_TOOLKIT = False

try:
    from wcwidth import wcwidth, wcswidth
except ImportError:
    wcwidth = None
    wcswidth = None

# 路径配置
SCRIPT_DIR = Path(__file__).resolve().parent


def resolve_claude_root(script_dir):
    if script_dir.parent.name.lower() == "scripts" and script_dir.parent.parent.name.lower() == ".claude":
        return script_dir.parent.parent
    if script_dir.name.lower() == "scripts":
        return script_dir.parent
    return script_dir.parent


CLAUDE_ROOT = resolve_claude_root(SCRIPT_DIR)
CLAUDE_SETTINGS = CLAUDE_ROOT / "settings.json"
MY_PROFILES = CLAUDE_ROOT / "custom_profiles.json"
CLAUDE_SWITCH_CONFIG = CLAUDE_ROOT / "claude_switch_config.json"
DEFAULT_LANGUAGE = "zh-CN"
AUTO_LANGUAGE = "auto"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

console = Console()

VERSION_FILE = SCRIPT_DIR / "VERSION"
try:
    APP_VERSION = VERSION_FILE.read_text(encoding="utf-8").strip() or "0.1.1"
except OSError:
    APP_VERSION = "0.1.1"
AUTHOR_LINK = "https://github.com/AonoChano"
AUTHOR_NAME = "AonoChano"
GITHUB_ICON = "\uf09b"
PROJECT_REPO = "AonoChano/claude-switch-tui"
PROJECT_GITHUB_LINK = f"https://github.com/{PROJECT_REPO}"
PROJECT_GITHUB_LABEL = "\uf09b GitHubLink"
PROJECT_RELEASE_API = f"https://api.github.com/repos/{PROJECT_REPO}/releases/latest"
PROJECT_RELEASES_URL = f"{PROJECT_GITHUB_LINK}/releases/latest"
CANONICAL_INSTALL_DIR_NAME = "claude-switch-tui"
TITLE_ENV = "CLAUDE_SWITCH_SET_TITLE"
NO_UPDATE_CHECK_ENV = "CLAUDE_SWITCH_NO_UPDATE_CHECK"
UPDATE_CHECK_INTERVAL_SECONDS = 24 * 60 * 60
UPDATE_CHECK_TIMEOUT_SECONDS = 4
UPDATE_DOWNLOAD_TIMEOUT_SECONDS = 90


def terminal_cell_width(char):
    if not char or unicodedata.combining(char):
        return 0
    if char in ("\u200b", "\ufe0e", "\ufe0f"):
        return 0
    if wcwidth:
        width = wcwidth(char)
        return max(0, width)
    return 2 if unicodedata.east_asian_width(char) in ("F", "W") else 1


def terminal_text_width(value):
    text = str(value or "")
    if not text:
        return 0
    if wcswidth:
        width = wcswidth(text)
        if width >= 0:
            return width
    return sum(terminal_cell_width(char) for char in text)


def terminal_title_enabled():
    value = os.environ.get(TITLE_ENV, "1").strip().lower()
    return value not in ("0", "false", "no", "off")


def set_terminal_title(title):
    if not terminal_title_enabled() or not sys.stdout.isatty():
        return
    safe_title = re.sub(r"[\x00-\x1f\x7f]", " ", str(title or "")).strip()
    if not safe_title:
        return
    try:
        sys.stdout.write(f"\x1b]0;{safe_title}\x07")
        sys.stdout.flush()
    except Exception:
        pass


def is_grapheme_extender(char):
    if not char:
        return False
    codepoint = ord(char)
    return (
        unicodedata.combining(char)
        or unicodedata.category(char) in ("Mn", "Mc", "Me")
        or codepoint in (0x200C, 0x200D, 0xFE0E, 0xFE0F)
    )


def grapheme_clusters(value):
    text = str(value or "")
    clusters = []
    for char in text:
        if not clusters or not is_grapheme_extender(char):
            clusters.append(char)
        else:
            clusters[-1] += char
    return clusters


def has_complex_tip_script(value):
    for char in str(value or ""):
        codepoint = ord(char)
        if (
            0x0900 <= codepoint <= 0x097F
            or 0x0E00 <= codepoint <= 0x0E7F
            or 0x1780 <= codepoint <= 0x17FF
            or 0x1000 <= codepoint <= 0x109F
            or 0x0E80 <= codepoint <= 0x0EFF
        ):
            return True
    return False


DPAPI_SECRET_PREFIX = "dpapi:"
KEYRING_SECRET_PREFIX = "keyring:"
SECRET_PREFIX = DPAPI_SECRET_PREFIX
TOKEN_ENV_KEYS = ("ANTHROPIC_API_TOKEN", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY")
MODEL_ENV_KEYS = (
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "ANTHROPIC_MODEL",
)
MENU_TEXT = "[cyan]↑↓:切换 | Enter:启用模型 | C:启动Claude | A:新增 | E:编辑 | D:删除 | M:模型详情 | L:语言设定[/cyan]"
TEMP_STATUS_SECONDS = 2.5
DOUBLE_PRESS_SECONDS = 0.85
MOUSE_MOVE_THROTTLE_SECONDS = 0.06
TIP_HOLD_SECONDS = 10.0
TIP_DELETE_SECONDS = 0.8
TIP_TYPE_SECONDS = 1.1
SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
PLAINTEXT_TOKEN_ENV = "CLAUDE_SWITCH_WRITE_PLAINTEXT_TOKEN"
UNSAFE_PROFILE_TOKEN_ENV = "CLAUDE_SWITCH_ALLOW_UNSAFE_PROFILE_TOKEN"
DEFAULT_LAUNCH_COMMAND = ["claude"]
LAUNCH_REQUEST_EXIT_CODE = 42
TERMINAL_RESET_SEQUENCE = (
    "\x1b[0m"
    "\x1b[?25h"
    "\x1b[?1l"
    "\x1b[?7h"
    "\x1b[?47l"
    "\x1b[?1048l"
    "\x1b[?1049l"
    "\x1b[?1000l"
    "\x1b[?1002l"
    "\x1b[?1003l"
    "\x1b[?1006l"
    "\x1b[?1015l"
    "\x1b[?2004l"
)
TERMINAL_MOUSE_ENABLE_SEQUENCE = "\x1b[?1003h\x1b[?1006h"
MOUSE_ROW_OFFSET = 6
MOUSE_EVENT_PREFIX = "\x1b[<"
STD_INPUT_HANDLE = -10
ENABLE_MOUSE_INPUT = 0x0010
ENABLE_QUICK_EDIT_MODE = 0x0040
ENABLE_EXTENDED_FLAGS = 0x0080
ENABLE_VIRTUAL_TERMINAL_INPUT = 0x0200


def capture_console_modes():
    if sys.platform != "win32":
        return {}

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetStdHandle.argtypes = [ctypes.wintypes.DWORD]
    kernel32.GetStdHandle.restype = ctypes.wintypes.HANDLE
    kernel32.GetConsoleMode.argtypes = [ctypes.wintypes.HANDLE, ctypes.POINTER(ctypes.wintypes.DWORD)]
    kernel32.GetConsoleMode.restype = ctypes.wintypes.BOOL
    modes = {}
    for name, handle_id in {
        "stdin": -10,
        "stdout": -11,
        "stderr": -12,
    }.items():
        handle = kernel32.GetStdHandle(handle_id)
        mode = ctypes.wintypes.DWORD()
        if handle and kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            modes[name] = (handle, mode.value)
    return modes


ORIGINAL_CONSOLE_MODES = capture_console_modes()


class DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _win_error():
    return ctypes.WinError(ctypes.get_last_error())


def _dpapi_handles():
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(DataBlob),
        ctypes.wintypes.LPCWSTR,
        ctypes.POINTER(DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.wintypes.DWORD,
        ctypes.POINTER(DataBlob),
    ]
    crypt32.CryptProtectData.restype = ctypes.wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(DataBlob),
        ctypes.POINTER(ctypes.wintypes.LPWSTR),
        ctypes.POINTER(DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.wintypes.DWORD,
        ctypes.POINTER(DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = ctypes.wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    return crypt32, kernel32


def _crypt_protect(data):
    if sys.platform != "win32":
        raise RuntimeError("DPAPI 仅支持 Windows")

    crypt32, kernel32 = _dpapi_handles()
    buffer = ctypes.create_string_buffer(data)
    in_blob = DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    out_blob = DataBlob()

    if not crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    ):
        raise _win_error()

    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out_blob.pbData, ctypes.c_void_p))


def _crypt_unprotect(data):
    if sys.platform != "win32":
        raise RuntimeError("DPAPI 仅支持 Windows")

    crypt32, kernel32 = _dpapi_handles()
    buffer = ctypes.create_string_buffer(data)
    in_blob = DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    out_blob = DataBlob()

    if not crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    ):
        raise _win_error()

    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out_blob.pbData, ctypes.c_void_p))


class SecretStoreUnavailable(RuntimeError):
    pass


class NoSecretStore:
    name = "none"
    label = "无可用安全存储"

    def is_available(self):
        return False

    def protect(self, secret, ref_hint=None):
        raise SecretStoreUnavailable(
            "当前系统没有可用的安全密钥存储。请安装/启用系统 Keychain、Secret Service、KWallet，"
            f"或设置 {UNSAFE_PROFILE_TOKEN_ENV}=1 明确允许不安全明文保存。"
        )

    def unprotect(self, value):
        raise SecretStoreUnavailable("当前系统没有可用的安全密钥存储，无法读取此 Token。")


class DpapiSecretStore:
    name = "dpapi"
    label = "Windows DPAPI"

    def is_available(self):
        return sys.platform == "win32"

    def protect(self, secret, ref_hint=None):
        if not secret:
            return ""
        encrypted = _crypt_protect(secret.encode("utf-8"))
        return DPAPI_SECRET_PREFIX + base64.b64encode(encrypted).decode("ascii")

    def unprotect(self, value):
        if not value:
            return ""
        if not value.startswith(DPAPI_SECRET_PREFIX):
            return value
        encrypted = base64.b64decode(value[len(DPAPI_SECRET_PREFIX):])
        return _crypt_unprotect(encrypted).decode("utf-8")


class KeyringSecretStore:
    name = "keyring"
    label = "系统密钥环"
    service_name = "ClaudeSwitch"

    def __init__(self):
        self._keyring = None

    def _load_keyring(self):
        if self._keyring is not None:
            return self._keyring
        try:
            import keyring
        except ImportError:
            return None

        try:
            backend = keyring.get_keyring()
            module = backend.__class__.__module__.lower()
            if module.startswith("keyring.backends.fail"):
                return None
        except Exception:
            return None

        self._keyring = keyring
        return self._keyring

    def is_available(self):
        return self._load_keyring() is not None

    def protect(self, secret, ref_hint=None):
        if not secret:
            return ""
        keyring = self._load_keyring()
        if keyring is None:
            raise SecretStoreUnavailable("系统密钥环不可用。")
        account = ref_hint or f"profile:{uuid.uuid4().hex}"
        keyring.set_password(self.service_name, account, secret)
        return KEYRING_SECRET_PREFIX + account

    def unprotect(self, value):
        if not value:
            return ""
        if not value.startswith(KEYRING_SECRET_PREFIX):
            return value
        keyring = self._load_keyring()
        if keyring is None:
            raise SecretStoreUnavailable("系统密钥环不可用，无法读取 Token。")
        account = value[len(KEYRING_SECRET_PREFIX):]
        secret = keyring.get_password(self.service_name, account)
        if secret is None:
            raise SecretStoreUnavailable("系统密钥环中找不到对应 Token。")
        return secret


_SECRET_STORE = None


def detect_secret_store():
    if sys.platform == "win32":
        store = DpapiSecretStore()
        if store.is_available():
            return store

    keyring_store = KeyringSecretStore()
    if keyring_store.is_available():
        return keyring_store
    return NoSecretStore()


def current_secret_store():
    global _SECRET_STORE
    if _SECRET_STORE is None:
        _SECRET_STORE = detect_secret_store()
    return _SECRET_STORE


def secret_store_for_value(value):
    if value.startswith(DPAPI_SECRET_PREFIX):
        return DpapiSecretStore()
    if value.startswith(KEYRING_SECRET_PREFIX):
        return KeyringSecretStore()
    return current_secret_store()


def protect_secret(secret, ref_hint=None):
    return current_secret_store().protect(secret, ref_hint=ref_hint)


def unprotect_secret(value):
    if not value:
        return ""
    return secret_store_for_value(value).unprotect(value)

def load_json(path, default):
    if not path.exists(): 
        return default
    try:
        with open(path, 'r', encoding='utf-8') as f: 
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"无法读取 {path.name}: {exc}") from exc

def save_json(path, data):
    tmp_path = path.with_name(path.name + ".tmp")
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    tmp_path.replace(path)


def locale_directories():
    candidates = [
        SCRIPT_DIR / "locales",
        SCRIPT_DIR / CANONICAL_INSTALL_DIR_NAME / "locales",
        SCRIPT_DIR / "ClaudeSwitch" / "locales",
        CLAUDE_ROOT / "scripts" / CANONICAL_INSTALL_DIR_NAME / "locales",
        CLAUDE_ROOT / "scripts" / "ClaudeSwitch" / "locales",
    ]
    seen = set()
    result = []
    for path in candidates:
        key = str(path).lower()
        if key not in seen:
            seen.add(key)
            result.append(path)
    return result


def load_json_safely(path, default):
    try:
        return load_json(path, default)
    except RuntimeError:
        return default


def load_app_config():
    data = load_json_safely(CLAUDE_SWITCH_CONFIG, {})
    return data if isinstance(data, dict) else {}


def save_app_config(config):
    save_json(CLAUDE_SWITCH_CONFIG, config if isinstance(config, dict) else {})


def update_app_config(values):
    config = load_app_config()
    for key, value in values.items():
        config[key] = value
    save_app_config(config)
    return config


class SafeFormatDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def normalize_locale_code(value):
    if not value:
        return ""
    raw = str(value).strip().split(".", 1)[0].replace("_", "-")
    if not raw:
        return ""

    lowered = raw.lower()
    if lowered in ("c", "posix"):
        return ""
    if lowered.startswith("zh"):
        if any(marker in lowered for marker in ("tw", "hk", "mo", "hant", "traditional")):
            return "zh-TW"
        return "zh-CN"

    parts = [part for part in raw.split("-") if part]
    if not parts:
        return ""

    normalized = [parts[0].lower()]
    for part in parts[1:]:
        if len(part) == 2 and part.isalpha():
            normalized.append(part.upper())
        elif len(part) == 4 and part.isalpha():
            normalized.append(part.title())
        elif len(part) == 3 and part.isdigit():
            normalized.append(part)
        else:
            normalized.append(part)
    return "-".join(normalized)


def detect_system_language():
    candidates = []
    if os.name == "nt":
        try:
            buffer = ctypes.create_unicode_buffer(85)
            if ctypes.windll.kernel32.GetUserDefaultLocaleName(buffer, len(buffer)):
                candidates.append(buffer.value)
        except Exception:
            pass

    for env_name in ("LC_ALL", "LC_MESSAGES", "LANGUAGE", "LANG"):
        value = os.environ.get(env_name)
        if value:
            candidates.append(value.split(":", 1)[0])

    for getter in (
        lambda: locale.getlocale()[0],
    ):
        try:
            candidates.append(getter())
        except Exception:
            pass

    for candidate in candidates:
        normalized = normalize_locale_code(candidate)
        if normalized:
            return normalized
    return ""


def flatten_translation_keys(data, prefix=""):
    keys = set()
    if isinstance(data, dict):
        for key, value in data.items():
            if key == "meta":
                continue
            child_prefix = f"{prefix}.{key}" if prefix else key
            keys.update(flatten_translation_keys(value, child_prefix))
    elif isinstance(data, list):
        for index, item in enumerate(data):
            child_prefix = f"{prefix}.{index}" if prefix else str(index)
            keys.update(flatten_translation_keys(item, child_prefix))
    elif isinstance(data, str) and prefix:
        keys.add(prefix)
    return keys


class I18n:
    def __init__(self):
        self.fallback_language = DEFAULT_LANGUAGE
        self.language_preference = AUTO_LANGUAGE
        self.language = DEFAULT_LANGUAGE
        self.fallback = self.load_locale(DEFAULT_LANGUAGE)
        self.locale = self.fallback
        config = load_app_config()
        requested = config.get("language", AUTO_LANGUAGE) if isinstance(config, dict) else AUTO_LANGUAGE
        self.set_language(requested, persist=False)

    def locale_path(self, code):
        filename = f"{code}.json"
        for directory in locale_directories():
            path = directory / filename
            if path.exists():
                return path
        return None

    def load_locale(self, code):
        path = self.locale_path(code)
        if not path:
            return {}
        data = load_json_safely(path, {})
        return data if isinstance(data, dict) else {}

    def resolve_available_language(self, code):
        if code == AUTO_LANGUAGE:
            code = detect_system_language()
        normalized = normalize_locale_code(code)
        if not normalized:
            return DEFAULT_LANGUAGE
        if self.locale_path(normalized):
            return normalized

        base = normalized.split("-", 1)[0].lower()
        for option in self.available_languages(include_auto=False):
            option_base = option["code"].split("-", 1)[0].lower()
            if option_base == base:
                return option["code"]
        return DEFAULT_LANGUAGE

    def translation_completion(self, code):
        resolved = self.resolve_available_language(code)
        required = flatten_translation_keys(self.fallback)
        if not required:
            return {"translated": 0, "total": 0, "percent": 100}

        data = self.fallback if resolved == DEFAULT_LANGUAGE else self.load_locale(resolved)
        present = flatten_translation_keys(data)
        translated = len(required.intersection(present))
        percent = int(round((translated / len(required)) * 100))
        return {
            "translated": translated,
            "total": len(required),
            "percent": max(0, min(100, percent)),
        }

    def available_languages(self, include_auto=True):
        languages = {}
        for directory in locale_directories():
            if not directory.exists():
                continue
            for path in directory.glob("*.json"):
                data = load_json_safely(path, {})
                meta = data.get("meta", {}) if isinstance(data, dict) else {}
                code = meta.get("code") or path.stem
                if not code or code in languages:
                    continue
                order = meta.get("order")
                if not isinstance(order, (int, float)):
                    order = 0 if code == DEFAULT_LANGUAGE else 1000
                languages[code] = {
                    "code": code,
                    "name": meta.get("name") or code,
                    "native_name": meta.get("native_name") or meta.get("name") or code,
                    "order": order,
                }
        if DEFAULT_LANGUAGE not in languages:
            languages[DEFAULT_LANGUAGE] = {
                "code": DEFAULT_LANGUAGE,
                "name": "简体中文",
                "native_name": "简体中文",
            }
        if DEFAULT_LANGUAGE in languages:
            languages[DEFAULT_LANGUAGE].setdefault("order", 0)
        result = sorted(
            languages.values(),
            key=lambda item: (
                item.get("order", 1000),
                item["code"] != DEFAULT_LANGUAGE,
                str(item.get("native_name") or item.get("name") or item["code"]).casefold(),
                item["code"].casefold(),
            ),
        )
        if include_auto:
            detected = self.resolve_available_language(detect_system_language())
            result.insert(0, {
                "code": AUTO_LANGUAGE,
                "name": "System language",
                "native_name": self.t("language.auto", "跟随系统"),
                "effective_code": detected,
                "order": -1000,
            })
            for option in result:
                completion_code = option.get("effective_code") if option["code"] == AUTO_LANGUAGE else option["code"]
                option["completion"] = self.translation_completion(completion_code)
        return result

    def get_nested(self, data, key):
        current = data
        for part in key.split("."):
            if not isinstance(current, dict) or part not in current:
                return None
            current = current[part]
        return current

    def t(self, key, default="", **kwargs):
        value = self.get_nested(self.locale, key)
        if value is None:
            value = self.get_nested(self.fallback, key)
        if not isinstance(value, str):
            value = default
        if kwargs:
            try:
                return value.format_map(SafeFormatDict(kwargs))
            except (KeyError, ValueError):
                return default
        return value

    def items(self, key, default):
        value = self.get_nested(self.locale, key)
        if value is None:
            value = self.get_nested(self.fallback, key)
        if not isinstance(value, list):
            return default
        normalized = []
        for item in value:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                normalized.append({"text": item["text"]})
            elif isinstance(item, str):
                normalized.append({"text": item})
        return normalized or default

    def set_language(self, code, persist=True):
        preference = code if isinstance(code, str) and code.strip() else AUTO_LANGUAGE
        if preference == AUTO_LANGUAGE:
            resolved = self.resolve_available_language(AUTO_LANGUAGE)
        else:
            resolved = self.resolve_available_language(preference)

        data = self.load_locale(resolved)
        if resolved != DEFAULT_LANGUAGE and not data:
            resolved = DEFAULT_LANGUAGE
            data = self.fallback

        self.language_preference = preference if preference == AUTO_LANGUAGE else resolved
        self.language = resolved
        self.locale = data or self.fallback
        if persist:
            update_app_config({"language": self.language_preference})
        return self.language


def get_profile_secret(profile):
    if profile.get("key_secret"):
        return unprotect_secret(profile.get("key_secret", ""))
    if profile.get("key_dpapi"):
        return unprotect_secret(profile.get("key_dpapi", ""))
    return profile.get("key", "")


def profile_has_secret(profile):
    return bool(profile.get("key_secret") or profile.get("key_dpapi") or profile.get("key"))


def key_preview(profile):
    if profile.get("key_secret"):
        value = profile.get("key_secret", "")
        if value.startswith(KEYRING_SECRET_PREFIX):
            return "Keyring"
        if value.startswith(DPAPI_SECRET_PREFIX):
            return "DPAPI"
        return "已加密"
    if profile.get("key_dpapi"):
        return "DPAPI" if sys.platform == "win32" else "DPAPI不可用"
    if profile.get("key"):
        return "待迁移"
    return "未设置"


def localized_key_preview(profile, i18n):
    def label(key, fallback):
        return i18n.t(f"table.token_state.{key}", fallback)

    if profile.get("key_secret"):
        value = profile.get("key_secret", "")
        if value.startswith(KEYRING_SECRET_PREFIX):
            return label("keyring", "Keyring")
        if value.startswith(DPAPI_SECRET_PREFIX):
            return label("dpapi", "DPAPI")
        return label("encrypted", "Encrypted")
    if profile.get("key_dpapi"):
        if sys.platform == "win32":
            return label("dpapi", "DPAPI")
        return label("dpapi_unavailable", "DPAPI N/A")
    if profile.get("key"):
        return label("legacy", "Migrate")
    return label("unset", "Unset")


def unsafe_profile_tokens_enabled():
    return os.environ.get(UNSAFE_PROFILE_TOKEN_ENV) == "1"


def secret_ref_hint(profile):
    name = str(profile.get("name") or "profile").strip() or "profile"
    safe_name = "".join(char if char.isalnum() else "-" for char in name).strip("-").lower()
    return f"profile:{safe_name or 'profile'}:{uuid.uuid4().hex}"


def store_profile_secret(profile, secret):
    profile.pop("key", None)
    profile.pop("key_dpapi", None)
    profile.pop("key_secret", None)
    if not secret:
        return profile

    store = current_secret_store()
    if not store.is_available():
        if unsafe_profile_tokens_enabled():
            profile["key"] = secret
            return profile
        raise SecretStoreUnavailable(
            f"{store.label}。无法安全保存 Token；如需强制明文保存，请设置 {UNSAFE_PROFILE_TOKEN_ENV}=1。"
        )

    stored = store.protect(secret, ref_hint=secret_ref_hint(profile))
    if stored.startswith(DPAPI_SECRET_PREFIX):
        profile["key_dpapi"] = stored
    else:
        profile["key_secret"] = stored
    profile["secret_backend"] = store.name
    return profile


def preserve_existing_profile_secret(profile, existing):
    for field in ("key_secret", "key_dpapi", "key"):
        if existing and existing.get(field):
            profile[field] = existing.get(field)
            break
    if existing and existing.get("secret_backend"):
        profile["secret_backend"] = existing.get("secret_backend")
    return profile


def secure_profile(profile, strict=False):
    secured = dict(profile)
    plaintext = secured.pop("key", "")
    if plaintext and not secured.get("key_secret") and not secured.get("key_dpapi"):
        try:
            store_profile_secret(secured, plaintext)
        except Exception:
            # Preserve legacy plaintext instead of destroying unreadable profiles.
            # New UI saves still fail earlier when no secure store is available.
            secured["key"] = plaintext
    return secured


def load_profiles():
    profiles = load_json(MY_PROFILES, [])
    if not isinstance(profiles, list):
        return []

    secured_profiles = [secure_profile(p, strict=False) for p in profiles if isinstance(p, dict)]
    if secured_profiles != profiles:
        save_json(MY_PROFILES, secured_profiles)
    return secured_profiles


def save_profiles(profiles):
    save_json(MY_PROFILES, [secure_profile(p, strict=True) for p in profiles if isinstance(p, dict)])


def plaintext_tokens_enabled():
    return os.environ.get(PLAINTEXT_TOKEN_ENV) == "1"


def strip_token_settings(settings):
    env = settings.setdefault("env", {})
    for key in TOKEN_ENV_KEYS:
        env.pop(key, None)


def sanitize_settings_tokens():
    if plaintext_tokens_enabled() or not CLAUDE_SETTINGS.exists():
        return False

    settings = load_json(CLAUDE_SETTINGS, {})
    env = settings.get("env")
    if not isinstance(env, dict):
        return False

    had_token = any(key in env for key in TOKEN_ENV_KEYS)
    if had_token:
        strip_token_settings(settings)
        save_json(CLAUDE_SETTINGS, settings)
    return had_token


def build_runtime_env(profile):
    env = os.environ.copy()
    profile_env = build_profile_env(profile)
    managed_keys = ("ANTHROPIC_BASE_URL",) + TOKEN_ENV_KEYS + MODEL_ENV_KEYS
    for key in managed_keys:
        if key in profile_env:
            env[key] = profile_env[key]
        else:
            env.pop(key, None)
    return env


def build_profile_env(profile):
    env = {}
    token = get_profile_secret(profile)
    if profile.get("url"):
        env["ANTHROPIC_BASE_URL"] = profile.get("url", "")
    for key in TOKEN_ENV_KEYS:
        if token:
            env[key] = token

    models = profile.get("models", {}) or {}
    model_values = {
        "ANTHROPIC_DEFAULT_OPUS_MODEL": models.get("opus", ""),
        "ANTHROPIC_DEFAULT_SONNET_MODEL": models.get("sonnet", ""),
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": models.get("haiku", ""),
        "ANTHROPIC_MODEL": models.get("anthropic") or models.get("opus", ""),
    }
    for key, value in model_values.items():
        if value:
            env[key] = value
    return env


def find_profile(name):
    profiles = load_profiles()
    return next((p for p in profiles if p.get("name") == name), None)


def run_profile_command(name, command):
    target = find_profile(name)
    if not target:
        print(f"错误：找不到名为 {name} 的配置", file=sys.stderr)
        return 2
    if not command:
        print("错误：--run 需要提供要启动的命令", file=sys.stderr)
        return 2

    apply_config(name)
    reset_terminal_modes()
    set_terminal_title(f"Claude Code - {name}")
    try:
        completed = subprocess.run(command, env=build_runtime_env(target))
        return completed.returncode
    finally:
        reset_terminal_modes()


def parse_semver(value):
    match = re.match(r"^v?(\d+)\.(\d+)\.(\d+)$", str(value or "").strip())
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def is_newer_version(latest, current):
    latest_version = parse_semver(latest)
    current_version = parse_semver(current)
    if latest_version is None or current_version is None:
        return False
    return latest_version > current_version


def update_check_disabled():
    value = os.environ.get(NO_UPDATE_CHECK_ENV, "").strip().lower()
    return value in ("1", "true", "yes", "on")


def github_json(url, timeout=UPDATE_CHECK_TIMEOUT_SECONDS):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "ClaudeSwitch",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    return json.loads(body)


def latest_release_info(timeout=UPDATE_CHECK_TIMEOUT_SECONDS):
    data = github_json(PROJECT_RELEASE_API, timeout=timeout)
    if not isinstance(data, dict):
        raise RuntimeError("GitHub release response was not an object.")

    tag = str(data.get("tag_name") or "").strip()
    if parse_semver(tag) is None:
        return {
            "available": False,
            "reason": "invalid_tag",
            "tag_name": tag,
            "latest_version": "",
            "latest_url": str(data.get("html_url") or PROJECT_RELEASES_URL),
            "zipball_url": str(data.get("zipball_url") or ""),
        }

    latest_version = tag[1:] if tag.lower().startswith("v") else tag
    return {
        "available": is_newer_version(latest_version, APP_VERSION),
        "reason": "",
        "tag_name": tag,
        "latest_version": latest_version,
        "latest_url": str(data.get("html_url") or PROJECT_RELEASES_URL),
        "zipball_url": str(data.get("zipball_url") or ""),
    }


def cache_update_check(info=None):
    payload = {"last_update_check": int(time.time())}
    if isinstance(info, dict):
        payload["latest_version"] = info.get("latest_version", "")
        payload["latest_url"] = info.get("latest_url", "")
    update_app_config(payload)


def check_for_update(timeout=UPDATE_CHECK_TIMEOUT_SECONDS, write_cache=True):
    info = latest_release_info(timeout=timeout)
    if write_cache:
        cache_update_check(info)
    return info


def should_check_for_update():
    if update_check_disabled():
        return False
    config = load_app_config()
    last_check = config.get("last_update_check", 0)
    try:
        last_check = float(last_check)
    except (TypeError, ValueError):
        last_check = 0
    return time.time() - last_check >= UPDATE_CHECK_INTERVAL_SECONDS


def canonical_install_dir():
    if os.name == "nt":
        home = Path(os.environ.get("USERPROFILE") or str(Path.home()))
    else:
        home = Path.home()
    return home / ".claude" / "scripts" / CANONICAL_INSTALL_DIR_NAME


def self_update_install_dir():
    if (
        SCRIPT_DIR.name.lower() == CANONICAL_INSTALL_DIR_NAME
        and SCRIPT_DIR.parent.name.lower() == "scripts"
        and SCRIPT_DIR.parent.parent.name.lower() == ".claude"
    ):
        return SCRIPT_DIR
    return canonical_install_dir()


def download_file(url, destination, timeout=UPDATE_DOWNLOAD_TIMEOUT_SECONDS):
    request = urllib.request.Request(url, headers={"User-Agent": "ClaudeSwitch"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        with open(destination, "wb") as handle:
            shutil.copyfileobj(response, handle)


def safe_extract_zip(zip_path, destination):
    destination = Path(destination).resolve()
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            if target != destination and not str(target).startswith(str(destination) + os.sep):
                raise RuntimeError(f"Refusing to extract unsafe archive member: {member.filename}")
        archive.extractall(destination)


def find_install_script_from_archive(destination):
    destination = Path(destination)
    for path in destination.rglob("install.ps1"):
        if path.is_file():
            return path
    return None


def print_update_check():
    try:
        info = check_for_update(timeout=10, write_cache=True)
    except (OSError, urllib.error.URLError, json.JSONDecodeError, RuntimeError) as exc:
        print(f"Update check failed: {exc}", file=sys.stderr)
        return 1

    latest = info.get("latest_version") or info.get("tag_name") or "unknown"
    if info.get("available"):
        print(f"New ClaudeSwitch version available: {latest}")
        print(info.get("latest_url") or PROJECT_RELEASES_URL)
    elif info.get("reason") == "invalid_tag":
        print(f"Latest GitHub release tag is not semver: {info.get('tag_name')}", file=sys.stderr)
        return 1
    else:
        print(f"ClaudeSwitch is up to date ({APP_VERSION}).")
    return 0


def run_self_update():
    if os.name != "nt":
        print("csw --update currently uses the Windows PowerShell installer.", file=sys.stderr)
        return 1

    try:
        info = check_for_update(timeout=10, write_cache=True)
    except (OSError, urllib.error.URLError, json.JSONDecodeError, RuntimeError) as exc:
        print(f"Update check failed: {exc}", file=sys.stderr)
        return 1

    if info.get("reason") == "invalid_tag":
        print(f"Latest GitHub release tag is not semver: {info.get('tag_name')}", file=sys.stderr)
        return 1
    if not info.get("available"):
        print(f"ClaudeSwitch is up to date ({APP_VERSION}).")
        return 0

    zip_url = info.get("zipball_url")
    if not zip_url:
        print("Latest GitHub release does not provide a source zip URL.", file=sys.stderr)
        return 1

    install_dir = self_update_install_dir()
    print(f"Updating ClaudeSwitch to {info.get('latest_version')}...")
    print(f"InstallDir: {install_dir}")

    with tempfile.TemporaryDirectory(prefix="claude-switch-tui-update-") as temp_dir:
        temp_path = Path(temp_dir)
        zip_path = temp_path / "source.zip"
        extract_dir = temp_path / "source"
        extract_dir.mkdir(parents=True, exist_ok=True)

        try:
            download_file(zip_url, zip_path)
            safe_extract_zip(zip_path, extract_dir)
        except (OSError, urllib.error.URLError, zipfile.BadZipFile, RuntimeError) as exc:
            print(f"Failed to download or extract release source: {exc}", file=sys.stderr)
            return 1

        install_script = find_install_script_from_archive(extract_dir)
        if not install_script:
            print("Release source did not contain install.ps1.", file=sys.stderr)
            return 1

        command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(install_script),
            "-InstallDir",
            str(install_dir),
        ]
        env = os.environ.copy()
        env["CLAUDE_SWITCH_RUNNING_DIR"] = str(SCRIPT_DIR)
        completed = subprocess.run(command, env=env)
        return completed.returncode


def get_active_url():
    s = load_json(CLAUDE_SETTINGS, {})
    return s.get("env", {}).get("ANTHROPIC_BASE_URL", "")

def apply_config(name):
    target = find_profile(name)
    if not target:
        return f"错误：找不到名为 {name} 的配置"

    settings = load_json(CLAUDE_SETTINGS, {})
    if "env" not in settings:
        settings["env"] = {}

    # 基础配置
    settings["env"]["ANTHROPIC_BASE_URL"] = target.get("url", "")
    if plaintext_tokens_enabled():
        token = get_profile_secret(target)
        for key in TOKEN_ENV_KEYS:
            settings["env"][key] = token
    else:
        strip_token_settings(settings)

    # 模型配置
    models = target.get("models", {}) or {}
    if any(models.values()):
        opus = models.get("opus", "")
        sonnet = models.get("sonnet", "")
        haiku = models.get("haiku", "")
        anthropic = models.get("anthropic") or opus

        settings["env"]["ANTHROPIC_DEFAULT_OPUS_MODEL"] = opus
        settings["env"]["ANTHROPIC_DEFAULT_SONNET_MODEL"] = sonnet
        settings["env"]["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = haiku
        settings["env"]["ANTHROPIC_MODEL"] = anthropic
    else:
        for k in MODEL_ENV_KEYS:
            settings["env"].pop(k, None)

    save_json(CLAUDE_SETTINGS, settings)
    suffix = "" if plaintext_tokens_enabled() else "（✔  安全检测通过：密钥未暴露）"
    return f"已成功切换至 {name}{suffix}"


def restore_console_modes():
    if sys.platform != "win32" or not ORIGINAL_CONSOLE_MODES:
        return

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.SetConsoleMode.argtypes = [ctypes.wintypes.HANDLE, ctypes.wintypes.DWORD]
    kernel32.SetConsoleMode.restype = ctypes.wintypes.BOOL
    for handle, mode in ORIGINAL_CONSOLE_MODES.values():
        kernel32.SetConsoleMode(handle, mode)


def reset_terminal_modes():
    try:
        restore_console_modes()
        sys.stdout.write(TERMINAL_RESET_SEQUENCE)
        sys.stdout.flush()
    except Exception:
        pass


def enable_mouse_tracking():
    try:
        if sys.platform == "win32":
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.GetStdHandle.argtypes = [ctypes.wintypes.DWORD]
            kernel32.GetStdHandle.restype = ctypes.wintypes.HANDLE
            kernel32.GetConsoleMode.argtypes = [ctypes.wintypes.HANDLE, ctypes.POINTER(ctypes.wintypes.DWORD)]
            kernel32.GetConsoleMode.restype = ctypes.wintypes.BOOL
            kernel32.SetConsoleMode.argtypes = [ctypes.wintypes.HANDLE, ctypes.wintypes.DWORD]
            kernel32.SetConsoleMode.restype = ctypes.wintypes.BOOL
            handle = kernel32.GetStdHandle(STD_INPUT_HANDLE)
            mode = ctypes.wintypes.DWORD()
            if handle and kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                new_mode = mode.value
                new_mode |= ENABLE_EXTENDED_FLAGS | ENABLE_MOUSE_INPUT | ENABLE_VIRTUAL_TERMINAL_INPUT
                new_mode &= ~ENABLE_QUICK_EDIT_MODE
                kernel32.SetConsoleMode(handle, new_mode)
        sys.stdout.write(TERMINAL_MOUSE_ENABLE_SEQUENCE)
        sys.stdout.flush()
    except Exception:
        pass


atexit.register(restore_console_modes)

def masked_input(prompt_text, default_val="", default_hint=None):
    console.print(f"[bold white]{prompt_text}[/bold white]", end="")
    if default_val:
        hint = default_hint or "已保存"
        console.print(f" [dim](当前: {hint}，回车保持不变)[/dim]", end="")
    console.print("\n> ", end="")

    chars = []
    while True:
        ch = msvcrt.getch()
        if ch in (b'\r', b'\n'):
            console.print()
            return "".join(chars) if chars else default_val
        elif ch == b'\x08' and chars:
            chars.pop()
            console.print("\b \b", end="", flush=True)
        elif ch == b'\x03':
            raise KeyboardInterrupt
        else:
            try:
                char = ch.decode('utf-8')
                if char.isprintable():
                    chars.append(char)
                    console.print("*", end="", flush=True)
            except:
                pass

def normal_input(prompt_text, default_val=""):
    console.print(f"[bold white]{prompt_text}[/bold white]", end="")
    if default_val:
        console.print(f" [dim](回车保持: {default_val})[/dim]", end="")
    console.print("\n> ", end="")

    line = sys.stdin.readline().strip()
    return line if line else default_val

class App:
    def __init__(self, selection_output=None):
        self.i18n = I18n()
        self.profiles = load_profiles()
        self.cleaned_settings_tokens = sanitize_settings_tokens()
        self.selection_output = Path(selection_output) if selection_output else None
        self.active_url = get_active_url()
        self.cwd = Path.cwd()
        self.index = 0
        self.show_models = False
        self.status_msg = MENU_TEXT
        self.status_until = 0
        self.spinner_index = 0
        self.busy = False
        self.last_ctrl_c = 0
        self.enter_launch_until = 0
        self.ctrl_c_requested = False
        self.launch_profile = None
        self.hover_action = None
        self.hover_index = None
        self.last_click = {"target": None, "time": 0}
        self.last_mouse_move = 0
        self.delete_confirm_until = 0
        self.delete_confirm_name = ""

        if self.cleaned_settings_tokens:
            self.set_temp_status("[bold yellow]已清理 settings.json 中的明文密钥[/bold yellow]")

    def set_temp_status(self, markup, seconds=TEMP_STATUS_SECONDS):
        self.status_msg = markup
        self.status_until = time.time() + seconds

    def clear_expired_status(self):
        if self.status_until and time.time() >= self.status_until and not self.busy:
            self.status_msg = MENU_TEXT
            self.status_until = 0

    def request_ctrl_c(self, signum, frame):
        self.ctrl_c_requested = True

    def handle_ctrl_c(self):
        now = time.time()
        if now - self.last_ctrl_c <= DOUBLE_PRESS_SECONDS:
            return True

        self.last_ctrl_c = now
        self.set_temp_status("[bold red]Press Ctrl-C again to exit.[/bold red]", DOUBLE_PRESS_SECONDS)
        return False

    def launch_selected(self, profile):
        self.launch_profile = profile
        self.set_temp_status(f"[bold green]正在启动 Claude：{escape(profile.get('name', ''))}[/bold green]")
        return True

    def get_active_profile(self):
        return next((p for p in self.profiles if p.get("url") == self.active_url), None)

    def update_terminal_title(self):
        active = self.get_active_profile()
        name = active.get("name", "") if active else ""
        set_terminal_title(f"ClaudeSwitch - {name}" if name else "ClaudeSwitch")

    def display_width(self, value):
        width = 0
        for char in value:
            width += 2 if unicodedata.east_asian_width(char) in ("F", "W") else 1
        return width

    def model_detail_height(self):
        if not (self.show_models and self.profiles):
            return 0
        models = self.profiles[self.index].get("models", {}) or {}
        return 4 if any(v for v in models.values() if v and v.strip()) else 1

    def table_body_height(self):
        return len(self.profiles) + self.model_detail_height()

    def footer_menu_y(self):
        return MOUSE_ROW_OFFSET + self.table_body_height() + 3

    def row_from_mouse_y(self, y):
        index = y - MOUSE_ROW_OFFSET
        return index if 0 <= index < len(self.profiles) else None

    def action_from_mouse(self, x, y):
        menu_y = self.footer_menu_y()
        content_left = 3

        row_index = self.row_from_mouse_y(y)
        if row_index is not None:
            return ("row", row_index)

        if y == menu_y:
            cursor = content_left
            for idx, (action, label) in enumerate(self.menu_segments()):
                if idx:
                    cursor += 3
                start = cursor
                end = start + self.display_width(label) - 1
                if start <= x <= end:
                    return (action, None)
                cursor = end + 1

        if y == menu_y + 1:
            launch_start = content_left + self.display_width("Tip: 双击Enter以")
            launch_end = launch_start + self.display_width("启动Claude") - 1
            if launch_start <= x <= launch_end:
                return ("launch", None)

        return (None, None)

    def read_escape_sequence(self):
        data = bytearray(b"\x1b")
        deadline = time.time() + 0.01
        while time.time() < deadline:
            while msvcrt.kbhit():
                data.extend(msvcrt.getch())
                if data.endswith((b"M", b"m")):
                    return data.decode("ascii", errors="ignore")
            time.sleep(0.001)
        return data.decode("ascii", errors="ignore")

    def parse_mouse_event(self, sequence):
        if not sequence.startswith(MOUSE_EVENT_PREFIX) or sequence[-1:] not in ("M", "m"):
            return None
        try:
            button, x, y = [int(part) for part in sequence[len(MOUSE_EVENT_PREFIX):-1].split(";")]
        except ValueError:
            return None

        return {
            "button": button,
            "x": x,
            "y": y,
            "is_press": sequence.endswith("M") and (button & 3) == 0,
            "is_move": bool(button & 32),
        }

    def handle_mouse_event(self, event, live):
        action, target = self.action_from_mouse(event["x"], event["y"])
        if event["is_move"]:
            now = time.time()
            if (
                action == self.hover_action
                and target == self.hover_index
                and now - self.last_mouse_move < MOUSE_MOVE_THROTTLE_SECONDS
            ):
                return False
            self.last_mouse_move = now

        self.hover_action = action if action != "row" else None
        self.hover_index = target if action == "row" else None

        if not event["is_press"]:
            return False

        now = time.time()
        click_target = (action, target)
        is_double = (
            self.last_click["target"] == click_target
            and now - self.last_click["time"] <= 0.45
        )
        self.last_click = {"target": click_target, "time": now}

        if action == "row" and is_double:
            self.index = target
            self.enable_selected_profile(live)
            return False
        if action and action != "row":
            return self.run_action(action, live)
        return False

    def enable_selected_profile(self, live):
        if not self.profiles:
            self.set_temp_status("[bold yellow]暂无可启用的供应商[/bold yellow]")
            return

        selected = self.profiles[self.index]
        result = self.switch_with_spinner(live, selected.get('name', ''))
        self.active_url = get_active_url()
        self.update_terminal_title()
        self.show_models = False
        style = "bold red" if result["error"] else "bold green"
        self.set_temp_status(f"[{style}]{escape(result['message'])}[/{style}]", TEMP_STATUS_SECONDS)

    def delete_selected_profile(self):
        if len(self.profiles) <= 1:
            self.set_temp_status("[bold yellow]至少保留一个供应商[/bold yellow]")
            return

        name = self.profiles[self.index].get("name", "")
        now = time.time()
        if self.delete_confirm_name != name or now > self.delete_confirm_until:
            self.delete_confirm_name = name
            self.delete_confirm_until = now + TEMP_STATUS_SECONDS
            self.set_temp_status(f"[bold red]再次删除确认移除 {escape(name)}[/bold red]")
            return

        removed = self.profiles[self.index].get("name", "")
        self.profiles.pop(self.index)
        save_profiles(self.profiles)
        self.index = max(0, self.index - 1)
        self.delete_confirm_name = ""
        self.delete_confirm_until = 0
        self.set_temp_status(f"[bold yellow]已删除 {escape(removed)}[/bold yellow]")

    def run_action(self, action, live):
        if action == "enable":
            self.enable_selected_profile(live)
        elif action == "launch":
            active = self.get_active_profile()
            if not active:
                self.set_temp_status("[bold yellow]请先按 Enter 启用模型[/bold yellow]")
            else:
                return self.launch_selected(active)
        elif action == "add":
            reset_terminal_modes()
            live.stop()
            self.profiles.append(self.run_editor())
            save_profiles(self.profiles)
            live.start()
            enable_mouse_tracking()
            self.set_temp_status("[bold green]已新增供应商，Token 已加密保存[/bold green]")
        elif action == "edit":
            if not self.profiles:
                self.set_temp_status("[bold yellow]暂无可编辑的供应商[/bold yellow]")
            else:
                reset_terminal_modes()
                live.stop()
                self.profiles[self.index] = self.run_editor(self.profiles[self.index])
                save_profiles(self.profiles)
                live.start()
                enable_mouse_tracking()
                self.set_temp_status("[bold green]已保存修改，Token 已加密保存[/bold green]")
        elif action == "delete":
            self.delete_selected_profile()
        elif action == "models":
            self.show_models = not self.show_models
        elif action == "language":
            self.set_temp_status("[bold yellow]语言设定模块待实现[/bold yellow]")
        return False

    def switch_with_spinner(self, live, name):
        result = {"message": "", "error": False}

        def worker():
            try:
                result["message"] = apply_config(name)
            except Exception as exc:
                result["message"] = f"错误：{exc}"
                result["error"] = True

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        self.busy = True

        while thread.is_alive():
            frame = SPINNER_FRAMES[self.spinner_index % len(SPINNER_FRAMES)]
            self.spinner_index += 1
            self.status_msg = f"[bold yellow]{frame} 正在切换至 {escape(name)}...[/bold yellow]"
            live.update(self.render())
            time.sleep(0.08)

        thread.join()
        self.busy = False
        return result

    def make_table(self):
        table = Table(
            box=box.SIMPLE_HEAVY, 
            expand=True, 
            border_style="blue", 
            padding=(0, 1),
            show_lines=False
        )
        
        # 统一固定列宽配置，无论是否显示模型详情，所有列宽比例始终固定，彻底杜绝任何布局乱跳！
        table.add_column("", justify="center", width=2, no_wrap=True)
        table.add_column("状态", justify="center", width=8, no_wrap=True)
        table.add_column("供应商名称", style="bold yellow", width=34, no_wrap=True)
        table.add_column("Base URL", style="green", ratio=1, no_wrap=False)
        table.add_column("Token", style="magenta", width=10, no_wrap=True)

        for i, p in enumerate(self.profiles):
            is_selected = i == self.index
            is_active = p.get('url') == self.active_url

            selector = "[bold cyan]▷[/bold cyan]" if is_selected else ""
            status = "[bold reverse green]已启用[/bold reverse green]" if is_active else ""
            row_style = "on #2c2c2c" if is_selected else ("on #242424" if i == self.hover_index else "")

            # ==================== 主行 ====================
            table.add_row(
                selector,
                status, 
                p.get('name', ''), 
                p.get('url', ''), 
                key_preview(p), 
                style=row_style
            )

            # ==================== 模型子行（独立树形图一行） ====================
            if is_selected and self.show_models:
                models = p.get("models", {}) or {}
                if any(v for v in models.values() if v and v.strip()):
                    opus = models.get("opus", "-")
                    sonnet = models.get("sonnet", "-")
                    haiku = models.get("haiku", "-")
                    anthropic = models.get("anthropic", "-")

                    # 使用 Text 对象并强制 no_wrap=True 防止多余折行，完美贴合固定列宽
                    model_text = Text.from_markup(
                        f"[dim]├── Opus      : {opus}[/dim]\n"
                        f"[dim]├── Sonnet    : {sonnet}[/dim]\n"
                        f"[dim]├── Haiku     : {haiku}[/dim]\n"
                        f"[dim]└── ANTHROPIC : {anthropic}[/dim]"
                    )
                    model_text.no_wrap = True

                    table.add_row(
                        "",
                        "",           # 状态列空
                        model_text,   # 模型树形详情，完美锁定在 46 宽度的供应商名称列中
                        "",           # Base URL 空
                        "",           # Token 空
                        style="dim on #1a1a1a"
                    )
                else:
                    no_model_text = Text("└── 暂无模型配置", style="dim")
                    no_model_text.no_wrap = True
                    table.add_row("", "", no_model_text, "", "", style="dim on #1a1a1a")

        return table


    def footer(self):
        path_text = Text()
        path_text.append(" CLI ", style="bold black on cyan")
        path_text.append(f" {self.cwd}", style="bold cyan")
        path_text.no_wrap = True

        menu = self.menu_text()
        menu.no_wrap = True

        tip = Text.from_markup("[dim]Tip: 双击Enter以[/dim]")
        tip.append("启动Claude", style="black on #E08A6D" if self.hover_action == "launch" else "black on #D77757")
        tip.append("，或点击高亮区域以已启用配置和当前路径启动。", style="dim")
        tip.no_wrap = True

        return Padding(Group(path_text, menu, tip), (1, 0, 0, 0))

    def menu_segments(self):
        return [
            ("nav", "↑↓:切换"),
            ("enable", "Enter:启用模型"),
            ("launch", "C:启动Claude"),
            ("add", "A:新增"),
            ("edit", "E:编辑"),
            ("delete", "D:删除"),
            ("models", "M:模型详情"),
            ("language", "L:语言设定"),
        ]

    def menu_text(self):
        if self.status_msg != MENU_TEXT:
            return Text.from_markup(self.status_msg)

        text = Text()
        for idx, (action, label) in enumerate(self.menu_segments()):
            if idx:
                text.append(" | ", style="cyan")
            style = "bright_cyan" if self.hover_action == action else "cyan"
            text.append(label, style=style)
        return text

    def render(self):
        return Panel(
            Group(self.make_table(), self.footer()),
            title="[bold cyan]Claude Code 环境切换中心[/bold cyan]",
            border_style="bright_blue",
            padding=(1, 1)
        )

    def run_model_editor(self, existing_models=None):
        existing = existing_models or {}
        console.print("\n[bold cyan]── 模型名称配置 ──[/bold cyan]")
        console.print("[dim]（直接回车跳过则不设置该模型）[/dim]\n")

        opus = normal_input("Opus 模型名", existing.get("opus", ""))
        sonnet = normal_input("Sonnet 模型名", existing.get("sonnet", ""))
        haiku = normal_input("Haiku 模型名", existing.get("haiku", ""))

        # ANTHROPIC_MODEL 选择
        options = []
        seen = []
        for label, val in [("Opus", opus), ("Sonnet", sonnet), ("Haiku", haiku)]:
            if val and val not in seen:
                options.append((label, val))
                seen.append(val)

        anthropic = ""
        if options:
            default_anthropic = opus or options[0][1]
            console.print(f"\n[bold white]ANTHROPIC_MODEL[/bold white] [dim](默认: {default_anthropic})[/dim]")
            for idx, (label, val) in enumerate(options, 1):
                console.print(f"  [cyan]{idx}.[/cyan] {val} [dim]({label})[/dim]")
            console.print("  [dim]直接回车 = 使用默认[/dim]")
            
            choice = normal_input("", "").strip()
            try:
                idx = int(choice) - 1
                anthropic = options[idx][1] if 0 <= idx < len(options) else default_anthropic
            except:
                anthropic = default_anthropic

        return {"opus": opus, "sonnet": sonnet, "haiku": haiku, "anthropic": anthropic}

    def run_editor(self, existing=None):
        console.clear()
        title = "编辑供应商" if existing else "新增供应商"
        console.print(Panel(f"[bold yellow]{title}[/bold yellow]", expand=False))

        existing_key = ""
        if existing:
            try:
                existing_key = get_profile_secret(existing)
            except Exception as exc:
                console.print(f"[bold red]无法解密现有 Token：{exc}[/bold red]")

        new_name = normal_input("供应商名称", existing.get('name', '') if existing else "")
        new_url = normal_input("Base URL", existing.get('url', '') if existing else "")
        new_key = masked_input("API Token", existing_key, "已加密" if existing_key else None)

        existing_models = existing.get("models", {}) if existing else {}
        use_models = normal_input("[bold]是否配置模型名称？[/bold] [dim](Y/n，默认Y)[/dim]", "Y")
        
        new_models = {}
        if use_models.strip().lower() in ('y', 'yes', ''):
            new_models = self.run_model_editor(existing_models)

        profile = {"name": new_name, "url": new_url, "models": new_models}
        if new_key:
            store_profile_secret(profile, new_key)
        return profile

    def run(self):
        self.update_terminal_title()
        old_handler = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, self.request_ctrl_c)
        try:
            with console.screen(hide_cursor=True):
                with Live(self.render(), auto_refresh=True, screen=True) as live:
                    enable_mouse_tracking()
                    while True:
                        if self.ctrl_c_requested:
                            self.ctrl_c_requested = False
                            if self.handle_ctrl_c():
                                break

                        if msvcrt.kbhit():
                            key = msvcrt.getch()

                            if key == b'\x03':  # Ctrl+C
                                if self.handle_ctrl_c():
                                    break
                                continue

                            if key == b'\x1b':
                                event = self.parse_mouse_event(self.read_escape_sequence())
                                if event and self.handle_mouse_event(event, live):
                                    break
                                continue

                            if key == b'\xe0':  # 方向键
                                direction = msvcrt.getch()
                                if direction == b'H':   # 上
                                    self.index = (self.index - 1) % max(1, len(self.profiles))
                                elif direction == b'P': # 下
                                    self.index = (self.index + 1) % max(1, len(self.profiles))

                            elif key in (b'a', b'A'):
                                if self.run_action("add", live):
                                    break

                            elif key in (b'e', b'E'):
                                if self.run_action("edit", live):
                                    break

                            elif key in (b'd', b'D'):
                                if self.run_action("delete", live):
                                    break

                            elif key in (b'm', b'M'):
                                if self.run_action("models", live):
                                    break

                            elif key in (b'l', b'L'):
                                if self.run_action("language", live):
                                    break

                            elif key in (b'c', b'C'):
                                if self.run_action("launch", live):
                                    break

                            elif key == b'\r':  # Enter
                                active = self.get_active_profile()
                                if active and time.time() <= self.enter_launch_until:
                                    if self.launch_selected(active):
                                        break
                                    continue
                                self.enable_selected_profile(live)
                                self.enter_launch_until = time.time() + DOUBLE_PRESS_SECONDS

                            elif key in (b'q', b'Q'):
                                break

                        self.clear_expired_status()
                        live.update(self.render())
                        time.sleep(0.03)
        finally:
            signal.signal(signal.SIGINT, old_handler)

        if self.launch_profile:
            name = self.launch_profile.get("name", "")
            set_terminal_title(f"Claude Code - {name}" if name else "Claude Code")
            if self.selection_output:
                self.selection_output.write_text(name, encoding="utf-8")
                reset_terminal_modes()
                return LAUNCH_REQUEST_EXIT_CODE

            reset_terminal_modes()
            console.print(f"[bold cyan]Claude 启动配置：{escape(name)}[/bold cyan]")
            console.print(f"[dim]工作目录：{self.cwd}[/dim]")
            try:
                completed = subprocess.run(
                    DEFAULT_LAUNCH_COMMAND,
                    env=build_runtime_env(self.launch_profile),
                    cwd=str(self.cwd),
                )
                return completed.returncode
            except FileNotFoundError:
                console.print("[bold red]错误：找不到 claude 命令[/bold red]")
                return 127
            finally:
                reset_terminal_modes()

        reset_terminal_modes()
        return 0


class PromptApp:
    STYLE = Style.from_dict({
        "screen": "bg:#101418 #d6dde8",
        "title": "#8bd5ff bold",
        "border": "#5fb3d8",
        "header": "#9fb2c8 bold",
        "dim": "#738096",
        "path.tag": "bg:#5fb3d8 #081018 bold",
        "path": "#5fb3d8 bold",
        "menu": "#60d6e8",
        "menu.hover": "#b6f3ff bold",
        "tip": "#8793a5",
        "launch": "bg:#D77757 #000000 bold",
        "launch.hover": "bg:#E08A6D #000000 bold",
        "row": "#d6dde8",
        "row.selected": "bg:#3a3f46 #e1e6ed",
        "row.hover": "bg:#273545 #d6dde8",
        "selector.selected": "bg:#3a3f46 #54d9ff bold",
        "selector.hover": "bg:#273545 #b6f3ff",
        "tip.cold": "#7f94a8 bold",
        "tip.ice": "#d8dce2 bold",
        "tip.hot": "#c58a63 bold",
        "tip.claude": "#b8b0a8 bold",
        "tip.author": "#8fa4b8 bold underline",
        "tip.author.hover": "#bfd0df bold underline",
        "meta": "#657184",
        "meta.link": "#8fa4b8 bold",
        "meta.link.hover": "#bfd0df bold",
        "active": "bg:#2f6f4e #ffffff bold",
        "selected": "#54d9ff bold",
        "name": "#ffd166 bold",
        "url": "#79d895",
        "token": "#e4a5ff",
        "model": "#8f9caf",
        "status.good": "#91e48f bold",
        "status.warn": "#ffd166 bold",
        "status.bad": "#ff8f8f bold",
        "status.busy": "#ffe08a bold",
        "field": "#d6dde8",
        "field.focus": "bg:#263647 #ffffff",
        "field.label": "#ffd166 bold",
        "field.hint": "#7f8a99",
        "error": "#ff8f8f bold",
        "button": "bg:#2b3a48 #d6dde8",
        "button.hover": "bg:#3a5063 #ffffff",
        "button.danger": "bg:#8b2d35 #ffffff bold",
        "button.danger.hover": "bg:#ad3a44 #ffffff bold",
        "modal": "bg:#1d2732 #ffffff",
    }) if HAS_PROMPT_TOOLKIT else None

    MENU_SEGMENTS = [
        ("nav", "↑↓:切换"),
        ("enable", "Enter:启用模型"),
        ("launch", "C:启动Claude"),
        ("add", "A:新增"),
        ("edit", "E:编辑"),
        ("delete", "D:删除"),
        ("models", "M:模型详情"),
        ("language", "L:语言设定"),
    ]
    MENU_SEGMENTS_COMPACT = [
        ("nav", "↑↓"),
        ("enable", "Enter:启用"),
        ("launch", "C:Claude"),
        ("add", "A:新增"),
        ("edit", "E:编辑"),
        ("delete", "D:删除"),
        ("models", "M:详情"),
        ("language", "L:语言"),
    ]
    MENU_SEGMENTS_MINIMAL = [
        ("enable", "Enter:启用"),
        ("launch", "C:Claude"),
        ("add", "A"),
        ("edit", "E"),
        ("delete", "D"),
        ("models", "M"),
        ("language", "L"),
    ]
    TIP_ITEMS = [
        {"text": "*Tip: 若果您使用鼠标，需要单击才能选中您设置的供应商"},
        {"text": "*Tip: 出于安全考虑，您只有在此窗口运行Claude Code才能生效您的设置，开一个终端直接输入`Claude`这条指令并不受本工具影响。"},
        {"text": "*Tip: 双击可以直接设置该供应商为激活状态；喜欢用键盘的话，Enter一次就行。"},
        {"text": "*Tip: 看到那个CLI所在的那一行了吗？那是您目前所在的工作路径，右边的「启动 Claude Code」会以此目录为工作路径开启Claude Code。"},
        {"text": "*Tip: 编辑提供商到一半突然想跑？您可以大胆Esc，软件会先问你是保存、放弃，或是您是否是手滑了……"},
        {"text": "*Tip: 热知识：您的`Key`会优先交给系统安全存储：Windows 用 DPAPI，macOS/Linux 用系统密钥环。"},
        {"text": "*Tip: 热知识：这是一个本地软件，您的密钥并不会被本工具上传到别处，它在这里安安心心的~"},
        {"text": "*Tip: 如果您要退出软件，需要连续按两次Ctrl-C ！至于为什么，作者也不知道……"},
        {"text": "*Tip: 如果您盯着这个界面超过了 60 秒，不如直接按 C 启动 Claude Code，它等很久了。"},
        {"text": "*Tip: 不用担心选错供应商，您只要重新在终端输入`csw`，随时切，随时换。"},
        {"text": "*Tip: 有人嫌弃旧的配置窗口像神秘仪式，所以改成了这版……"},
        {"text": "*Tip: 按 M 展开模型详情，你可能会发现一些自己也忘记写进去的隐藏配置。"},
        {"text": "*Tip: 冷知识：这个工具的开发者自己也在用，所以别怕，有 Bug 的话他第一个遭殃。"},
        {"text": "*Tip: 冷知识：开发者只是一个被换ClaudeCode的API的复杂操作搞烦了的大学生。"},
        {"text": "*Tip: 冰知识：直接敲 `csw --apply 供应商名字` 可以在不打开这个界面的情况下，直接让那个供应商生效，切完就能用。"},
        {"text": "*Tip: 冷知识：`csw --list` 会把你所有已保存的供应商名字和地址以 JSON 形式输出到终端，适合喂给脚本或你自己写的自动化流程。"},
        {"text": "*Tip: 冷知识：`csw --run 供应商名字 claude` 会临时使用那个供应商的环境变量启动一次 Claude，但不改变当前界面里已启用的供应商。"},
        {"text": "*Tip: 冷知识：`csw --env-json 供应商名字` 会把那个供应商对应的环境变量（Token 除外）以 JSON 形式打印出来，方便排查“模型名怎么不对”这类问题。"},
        {"text": "*Tip: 冷知识：`csw --sanitize-settings` 会清理 settings.json 中可能残留的明文密钥，只保留安全存储中的 Token。"},
        {"text": "*Tip: 冷知识：`csw --select-launch 文件路径` 会打开这个界面让你选，选完后把供应商名字写入你指定的文件并退出——适合别的脚本拿你的选择结果干别的事。"},
        {"text": "*Tip: 如果你觉得这些Tips写得还不错，那是用户的功劳；觉得烂，那是因为是作者写的。"},
        {"text": "*Tip: 双击Enter也可以启动 Claude Code"},
        {"text": "*Tip: 作者很讨厌吃沙拉 🚫🥗"},
    ]
    DEFAULT_TIP_TERMS = {
        "cold": [
            "冷知识", "冷知識", "Fun fact", "Fun Fact", "Trivia",
        ],
        "ice": [
            "冰知识", "冰知識", "Ice-cold fact",
        ],
        "hot": [
            "热知识", "熱知識", "Hot fact", "Hot tip",
        ],
        "author": [
            "作者", "author", "Author", "developer", "Developer", "Autor",
            "Autora", "Auteur", "autore", "autor",
        ],
    }

    FORM_FIELDS = [
        ("name", "供应商名称"),
        ("url", "Base URL"),
        ("token", "API Token"),
        ("opus", "Opus 模型"),
        ("sonnet", "Sonnet 模型"),
        ("haiku", "Haiku 模型"),
        ("anthropic", "ANTHROPIC_MODEL"),
    ]

    def __init__(self, selection_output=None):
        self.i18n = I18n()
        self.profiles = load_profiles()
        self.cleaned_settings_tokens = sanitize_settings_tokens()
        self.selection_output = Path(selection_output) if selection_output else None
        self.active_url = get_active_url()
        self.cwd = Path.cwd()
        self.index = 0
        self.show_models = False
        self.mode = "main"
        self.status_text = ""
        self.status_style = "class:status.good"
        self.status_until = 0
        self.spinner_index = 0
        self.busy = False
        self.last_ctrl_c = 0
        self.enter_launch_until = 0
        self.launch_profile = None
        self.hover_action = None
        self.hover_index = None
        self.hover_button = None
        self.last_click = {"target": None, "time": 0}
        self.form = None
        self.form_focus = 0
        self.form_error = ""
        self.form_confirm_choice = 2
        self.delete_choice = 1
        self.delete_target_index = None
        self.language_options = []
        self.language_index = 0
        self.pt_app = None
        self.tip_index = 0
        self.tip_queue = []
        self.tip_queue_signature = None
        self.last_tip_item = None
        self.tip_phase = "hold"
        self.tip_phase_started = time.time()
        self._menu_regions = {}
        self._tip_launch_region = None
        self._form_button_regions = {}
        self._confirm_button_regions = {}
        self._delete_button_regions = {}

        if self.cleaned_settings_tokens:
            self.set_status(self.i18n.t("status.settings_sanitized", "已清理 settings.json 中的明文密钥"), "class:status.warn")
        self.start_update_check()

    def set_status(self, text, style="class:status.good", seconds=TEMP_STATUS_SECONDS):
        self.status_text = text
        self.status_style = style
        self.status_until = time.time() + seconds if seconds else 0
        self.invalidate()

    def clear_expired_status(self):
        if self.status_until and time.time() >= self.status_until and not self.busy:
            self.status_text = ""
            self.status_until = 0

    def start_update_check(self):
        if self.selection_output or not should_check_for_update():
            return

        def worker():
            try:
                info = check_for_update(timeout=UPDATE_CHECK_TIMEOUT_SECONDS, write_cache=True)
            except Exception:
                try:
                    cache_update_check()
                except Exception:
                    pass
                return

            if info.get("available"):
                version = info.get("latest_version") or info.get("tag_name") or ""
                text = self.i18n.t(
                    "status.update_available",
                    "New ClaudeSwitch {version} is available. Run csw --update.",
                    version=version,
                )
                self.set_status(text, "class:status.warn", 8)

        threading.Thread(target=worker, daemon=True).start()

    def invalidate(self):
        if self.pt_app:
            self.pt_app.invalidate()

    def display_width(self, value):
        return terminal_text_width(value)

    def mouse_width(self, value):
        return self.display_width(value)

    def fit_text(self, value, width):
        value = str(value or "")
        if width <= 0:
            return ""
        result = []
        used = 0
        for cluster in grapheme_clusters(value):
            cluster_width = self.display_width(cluster)
            if used + cluster_width > width:
                break
            result.append(cluster)
            used += cluster_width
        fitted = "".join(result)
        return fitted + (" " * max(0, width - self.display_width(fitted)))

    def ellipsize(self, value, width):
        value = str(value or "")
        if self.display_width(value) <= width:
            return self.fit_text(value, width)
        if width <= 1:
            return "…"[:width]
        return self.fit_text(value, width - 1).rstrip() + "…"

    def truncate_text(self, value, width):
        value = str(value or "")
        if width <= 0:
            return ""
        if self.display_width(value) <= width:
            return value
        if width <= 1:
            return "…"

        result = []
        used = 0
        for cluster in grapheme_clusters(value):
            cluster_width = self.display_width(cluster)
            if used + cluster_width > width - 1:
                break
            result.append(cluster)
            used += cluster_width

        while result:
            candidate = "".join(result).rstrip() + "…"
            if self.display_width(candidate) <= width:
                return candidate
            result.pop()
        return "…"

    def terminal_width(self):
        columns = None
        if self.pt_app:
            try:
                columns = self.pt_app.output.get_size().columns
            except Exception:
                columns = None
        if not columns:
            columns = shutil.get_terminal_size(fallback=(120, 30)).columns
        return max(60, min(columns, 160))

    def localized_menu_segments(self, variant):
        defaults = {
            "full": self.MENU_SEGMENTS,
            "compact": self.MENU_SEGMENTS_COMPACT,
            "minimal": self.MENU_SEGMENTS_MINIMAL,
        }[variant]
        return [
            (action, self.i18n.t(f"menu.{variant}.{action}", label))
            for action, label in defaults
        ]

    def menu_segments_for_width(self, width):
        for segments in (
            self.localized_menu_segments("full"),
            self.localized_menu_segments("compact"),
            self.localized_menu_segments("minimal"),
        ):
            menu_width = sum(self.display_width(label) for _, label in segments)
            menu_width += max(0, len(segments) - 1) * self.display_width(" | ")
            if menu_width <= width:
                return segments
        return self.localized_menu_segments("minimal")

    def fit_menu_segments(self, width):
        if width <= 0:
            return []

        segments = self.menu_segments_for_width(width)
        fitted = []
        used = 0
        sep_width = self.display_width(" | ")
        for action, label in segments:
            prefix_width = sep_width if fitted else 0
            label_width = self.display_width(label)
            if used + prefix_width + label_width <= width:
                fitted.append((action, label))
                used += prefix_width + label_width
                continue

            remaining = width - used - prefix_width
            if remaining >= 3:
                fitted.append((action, self.ellipsize(label, remaining)))
            break
        return fitted

    def localized_tips(self):
        return self.i18n.items("tips", self.TIP_ITEMS)

    def form_fields(self):
        return [
            (key, self.i18n.t(f"form.fields.{key}", label))
            for key, label in self.FORM_FIELDS
        ]

    def add_line(self, fragments, line_fragments, width=None, fill_style="", fill_handler=None):
        width = width or self.terminal_width()
        used = 0
        for item in line_fragments:
            text = item[1]
            used += self.display_width(text)
            fragments.append(item)
        if used < width:
            if fill_handler:
                fragments.append((fill_style, " " * (width - used), fill_handler))
            else:
                fragments.append((fill_style, " " * (width - used)))
        fragments.append(("", "\n"))

    def fragment(self, style, text, handler=None):
        if handler:
            return (style, text, handler)
        return (style, text)

    def main_mouse_handler(self, action, payload=None):
        def handler(mouse_event):
            if self.mode != "main" or self.busy:
                return None

            if mouse_event.event_type == MouseEventType.MOUSE_MOVE:
                if action == "row":
                    self.set_hover(None, payload)
                else:
                    self.set_hover(action, None)
                return None

            if mouse_event.event_type == MouseEventType.SCROLL_UP:
                self.move_selection(-1)
                return None
            if mouse_event.event_type == MouseEventType.SCROLL_DOWN:
                self.move_selection(1)
                return None

            if mouse_event.event_type != MouseEventType.MOUSE_UP:
                return None

            if action == "row":
                self.click_row(payload)
            elif action == "menu":
                menu_action = self.menu_action_at(mouse_event.position.x)
                if menu_action:
                    self.run_main_action(menu_action)
            elif action == "tip":
                if self.tip_launch_at(mouse_event.position.x):
                    self.request_launch()
            else:
                self.run_main_action(action)
            return None

        return handler

    def menu_mouse_handler(self):
        def handler(mouse_event):
            if self.mode != "main" or self.busy:
                return None

            action = self.menu_action_at(mouse_event.position.x)
            if mouse_event.event_type == MouseEventType.MOUSE_MOVE:
                self.set_hover(action, None)
            elif mouse_event.event_type == MouseEventType.MOUSE_UP and action:
                self.run_main_action(action)
            return None

        return handler

    def menu_item_mouse_handler(self, action):
        def handler(mouse_event):
            if self.mode != "main" or self.busy:
                return None

            hover_action = None if action == "nav" else action
            if mouse_event.event_type == MouseEventType.MOUSE_MOVE:
                self.set_hover(hover_action, None)
            elif mouse_event.event_type == MouseEventType.MOUSE_UP and hover_action:
                self.run_main_action(hover_action)
            return None

        return handler

    def clear_hover_mouse_handler(self):
        def handler(mouse_event):
            if self.mode != "main" or self.busy:
                return None
            if mouse_event.event_type == MouseEventType.MOUSE_MOVE:
                self.set_hover(None, None)
            return None

        return handler

    def tip_mouse_handler(self):
        def handler(mouse_event):
            if self.mode != "main" or self.busy:
                return None

            if mouse_event.event_type == MouseEventType.MOUSE_MOVE:
                self.set_hover(None, None)
            return None

        return handler

    def tip_launch_mouse_handler(self):
        def handler(mouse_event):
            if self.mode != "main" or self.busy:
                return None

            if mouse_event.event_type == MouseEventType.MOUSE_MOVE:
                self.set_hover("launch", None)
            elif mouse_event.event_type == MouseEventType.MOUSE_UP:
                self.request_launch()
            return None

        return handler

    def author_link_mouse_handler(self):
        def handler(mouse_event):
            if self.mode != "main":
                return None

            if mouse_event.event_type == MouseEventType.MOUSE_MOVE:
                self.set_hover("author_link", None)
            elif mouse_event.event_type == MouseEventType.MOUSE_UP:
                webbrowser.open(AUTHOR_LINK, new=2)
                self.set_status(self.i18n.t("status.author_opened", "已打开作者主页"), "class:status.good")
            return None

        return handler

    def reset_tip_rotation(self):
        self.tip_index = 0
        self.tip_queue = []
        self.tip_queue_signature = None
        self.tip_phase = "hold"
        self.tip_phase_started = time.time()

    def ensure_tip_queue(self, tips):
        signature = tuple(item.get("text", "") for item in tips)
        if signature != self.tip_queue_signature:
            self.tip_queue_signature = signature
            self.tip_queue = []
            self.tip_index = 0

        if not tips:
            self.tip_queue = []
            self.tip_index = 0
            return

        if not self.tip_queue or self.tip_index >= len(self.tip_queue):
            queue = list(range(len(tips)))
            random.shuffle(queue)
            if len(queue) > 1 and queue[0] == self.last_tip_item:
                queue[0], queue[1] = queue[1], queue[0]
            self.tip_queue = queue
            self.tip_index = 0

    def current_tip_full_text(self, tips):
        self.ensure_tip_queue(tips)
        if not tips or not self.tip_queue:
            return ""
        tip_item = self.tip_queue[self.tip_index]
        return tips[tip_item].get("text", "")

    def advance_tip(self, tips):
        if self.tip_queue and self.tip_index < len(self.tip_queue):
            self.last_tip_item = self.tip_queue[self.tip_index]
        self.tip_index += 1
        self.ensure_tip_queue(tips)

    def current_tip_text(self):
        tips = self.localized_tips()
        full_text = self.current_tip_full_text(tips)
        elapsed = time.time() - self.tip_phase_started
        animate = not has_complex_tip_script(full_text)
        if not animate and self.tip_phase != "hold":
            self.tip_phase = "hold"
            self.tip_phase_started = time.time()
            return full_text

        if self.tip_phase == "hold":
            if elapsed >= TIP_HOLD_SECONDS:
                if not animate:
                    self.advance_tip(tips)
                    self.tip_phase = "hold"
                    self.tip_phase_started = time.time()
                    return self.current_tip_full_text(tips)
                self.tip_phase = "delete"
                self.tip_phase_started = time.time()
                elapsed = 0
            else:
                return full_text

        if self.tip_phase == "delete":
            clusters = grapheme_clusters(full_text)
            progress = min(1.0, elapsed / TIP_DELETE_SECONDS)
            visible = int(round(len(clusters) * (1.0 - progress)))
            if progress >= 1.0:
                self.advance_tip(tips)
                self.tip_phase = "type"
                self.tip_phase_started = time.time()
                return ""
            return "".join(clusters[:visible])

        if self.tip_phase == "type":
            tips = self.localized_tips()
            full_text = self.current_tip_full_text(tips)
            if has_complex_tip_script(full_text):
                self.tip_phase = "hold"
                self.tip_phase_started = time.time()
                return full_text
            clusters = grapheme_clusters(full_text)
            progress = min(1.0, elapsed / TIP_TYPE_SECONDS)
            visible = int(round(len(clusters) * progress))
            if progress >= 1.0:
                self.tip_phase = "hold"
                self.tip_phase_started = time.time()
                return full_text
            return "".join(clusters[:visible])

        self.tip_phase = "hold"
        self.tip_phase_started = time.time()
        return full_text

    def localized_tip_terms(self):
        terms = {key: [] for key in self.DEFAULT_TIP_TERMS}
        raw_terms = self.i18n.get_nested(self.i18n.locale, "tip_terms")
        fallback_terms = self.i18n.get_nested(self.i18n.fallback, "tip_terms")
        for source in (raw_terms, fallback_terms, self.DEFAULT_TIP_TERMS):
            if not isinstance(source, dict):
                continue
            for key in ("cold", "ice", "hot", "author"):
                value = source.get(key)
                if isinstance(value, str):
                    values = [value]
                elif isinstance(value, list):
                    values = [item for item in value if isinstance(item, str)]
                else:
                    values = []
                for item in values:
                    if item and item not in terms.setdefault(key, []):
                        terms[key].append(item)
        return terms

    def tip_keywords(self, author_handler):
        terms = self.localized_tip_terms()
        keywords = [
            ("Claude Code", "class:tip.claude", None),
            ("ClaudeCode", "class:tip.claude", None),
            ("Claude", "class:tip.claude", None),
        ]
        style_map = {
            "cold": "class:tip.cold",
            "ice": "class:tip.ice",
            "hot": "class:tip.hot",
            "author": "class:tip.author.hover" if self.hover_action == "author_link" else "class:tip.author",
        }
        handler_map = {"author": author_handler}
        for key, values in terms.items():
            for value in values:
                keywords.append((value, style_map[key], handler_map.get(key)))

        compiled = []
        seen = set()
        for word, style, word_handler in sorted(keywords, key=lambda item: len(item[0]), reverse=True):
            if not word or word in seen:
                continue
            seen.add(word)
            compiled.append((re.compile(re.escape(word), re.IGNORECASE), style, word_handler))
        return compiled

    def tip_fragments(self, text, handler):
        author_handler = self.author_link_mouse_handler()
        keywords = self.tip_keywords(author_handler)

        fragments = []
        index = 0
        while index < len(text):
            next_match = None
            for pattern, style, word_handler in keywords:
                match = pattern.search(text, index)
                if not match:
                    continue
                found = match.start()
                word = match.group(0)
                if (
                    next_match is None
                    or found < next_match[0]
                    or (found == next_match[0] and len(word) > len(next_match[1]))
                ):
                    next_match = (found, word, style, word_handler)

            if next_match is None:
                fragments.append(("class:tip", text[index:], handler))
                break

            found, word, style, word_handler = next_match
            if found > index:
                fragments.append(("class:tip", text[index:found], handler))
            fragments.append((style, word, word_handler or handler))
            index = found + len(word)

        return fragments

    def set_hover(self, action, index):
        changed = self.hover_action != action or self.hover_index != index
        self.hover_action = action
        self.hover_index = index
        if changed:
            self.invalidate()

    def move_selection(self, delta):
        if not self.profiles:
            return
        self.index = (self.index + delta) % len(self.profiles)
        self.hover_index = None
        self.invalidate()

    def click_row(self, row_index):
        if row_index is None or row_index >= len(self.profiles):
            return

        now = time.time()
        target = ("row", row_index)
        is_double = self.last_click["target"] == target and now - self.last_click["time"] <= 0.45
        self.last_click = {"target": target, "time": now}
        self.index = row_index
        self.invalidate()
        if is_double:
            self.enable_current_profile()

    def language_mouse_handler(self, index):
        def handler(mouse_event):
            if self.mode != "language" or not self.language_options:
                return None

            if mouse_event.event_type == MouseEventType.SCROLL_UP:
                self.language_index = (self.language_index - 1) % len(self.language_options)
                self.hover_index = self.language_index
                self.invalidate()
                return None
            if mouse_event.event_type == MouseEventType.SCROLL_DOWN:
                self.language_index = (self.language_index + 1) % len(self.language_options)
                self.hover_index = self.language_index
                self.invalidate()
                return None

            if mouse_event.event_type == MouseEventType.MOUSE_MOVE:
                self.hover_index = index
                self.invalidate()
                return None
            if mouse_event.event_type != MouseEventType.MOUSE_UP:
                return None
            if index is None or index >= len(self.language_options):
                return None

            now = time.time()
            target = ("language", index)
            is_double = self.last_click["target"] == target and now - self.last_click["time"] <= 0.45
            self.last_click = {"target": target, "time": now}
            self.language_index = index
            self.hover_index = index
            self.invalidate()
            if is_double:
                self.apply_language_selection()
            return None

        return handler

    def menu_action_at(self, x):
        for action, (start, end) in self._menu_regions.items():
            if start <= x < end:
                if action == "launch_button":
                    return "launch"
                return None if action == "nav" else action
        return None

    def tip_launch_at(self, x):
        if not self._tip_launch_region:
            return False
        start, end = self._tip_launch_region
        return start <= x < end

    def get_active_profile(self):
        return next((p for p in self.profiles if p.get("url") == self.active_url), None)

    def update_terminal_title(self):
        active = self.get_active_profile()
        name = active.get("name", "") if active else ""
        set_terminal_title(f"ClaudeSwitch - {name}" if name else "ClaudeSwitch")

    def run_main_action(self, action):
        if self.busy:
            return
        if action == "enable":
            self.enable_current_profile()
        elif action == "launch":
            self.request_launch()
        elif action == "add":
            self.open_form()
        elif action == "edit":
            if not self.profiles:
                self.set_status(self.i18n.t("status.no_editable_provider", "暂无可编辑的供应商"), "class:status.warn")
            else:
                self.open_form(self.index)
        elif action == "delete":
            self.open_delete_confirm()
        elif action == "models":
            self.show_models = not self.show_models
            self.invalidate()
        elif action == "language":
            self.open_language_selector()

    def open_language_selector(self):
        self.language_options = self.i18n.available_languages()
        self.language_index = 0
        for index, option in enumerate(self.language_options):
            if option["code"] == self.i18n.language_preference:
                self.language_index = index
                break
        self.mode = "language"
        self.hover_action = None
        self.hover_index = None
        self.invalidate()

    def apply_language_selection(self):
        if not self.language_options:
            self.mode = "main"
            self.invalidate()
            return
        option = self.language_options[self.language_index]
        language = self.i18n.set_language(option["code"], persist=True)
        self.reset_tip_rotation()
        self.mode = "main"
        self.hover_action = None
        self.hover_index = None
        label = option.get("native_name") or option.get("name") or language
        if option["code"] == AUTO_LANGUAGE:
            label = f"{label} ({language})"
        self.set_status(
            self.i18n.t("language.applied", "已切换语言：{name}", name=label),
            "class:status.good",
        )

    def enable_current_profile(self):
        if not self.profiles:
            self.set_status(self.i18n.t("status.no_enable_provider", "暂无可启用的供应商"), "class:status.warn")
            return

        profile = self.profiles[self.index]
        name = profile.get("name", "")
        self.busy = True
        self.status_until = 0

        def worker():
            result_text = ""
            result_style = "class:status.good"
            try:
                apply_config(name)
                result_key = "status.switched" if plaintext_tokens_enabled() else "status.switched_secure"
                result_default = "已成功切换至 {name}" if plaintext_tokens_enabled() else "已成功切换至 {name}（✔  安全检测通过：密钥未暴露）"
                result_text = self.i18n.t(result_key, result_default, name=name)
                self.active_url = get_active_url()
                self.update_terminal_title()
                self.show_models = False
                self.enter_launch_until = time.time() + DOUBLE_PRESS_SECONDS
            except Exception as exc:
                result_text = self.i18n.t("status.error", "错误：{message}", message=str(exc))
                result_style = "class:status.bad"
            finally:
                self.busy = False
                self.set_status(result_text, result_style)

        def spinner():
            while self.busy:
                frame = SPINNER_FRAMES[self.spinner_index % len(SPINNER_FRAMES)]
                self.spinner_index += 1
                self.status_text = frame + " " + self.i18n.t("status.switching", "正在切换至 {name}...", name=name)
                self.status_style = "class:status.busy"
                self.invalidate()
                time.sleep(0.08)

        threading.Thread(target=worker, daemon=True).start()
        threading.Thread(target=spinner, daemon=True).start()

    def request_launch(self):
        active = self.get_active_profile()
        if not active:
            self.set_status(self.i18n.t("status.enable_first", "请先按 Enter 启用模型"), "class:status.warn")
            return
        self.launch_profile = active
        if self.pt_app:
            self.pt_app.exit(result=LAUNCH_REQUEST_EXIT_CODE)

    def handle_enter(self):
        if self.mode == "main":
            active = self.get_active_profile()
            if active and time.time() <= self.enter_launch_until:
                self.request_launch()
            else:
                self.enable_current_profile()
        elif self.mode == "form":
            if self.form_focus == len(self.form["fields"]) - 1:
                self.save_form()
            else:
                self.form_focus += 1
                self.invalidate()
        elif self.mode == "form_confirm":
            self.run_form_confirm_choice()
        elif self.mode == "delete_confirm":
            self.run_delete_choice()
        elif self.mode == "language":
            self.apply_language_selection()

    def handle_ctrl_c(self):
        now = time.time()
        if now - self.last_ctrl_c <= DOUBLE_PRESS_SECONDS:
            if self.pt_app:
                self.pt_app.exit(result=0)
            return
        self.last_ctrl_c = now
        self.set_status(self.i18n.t("status.exit_prompt", "Press Ctrl-C again to exit."), "class:status.bad", DOUBLE_PRESS_SECONDS)

    def open_form(self, edit_index=None):
        existing = self.profiles[edit_index] if edit_index is not None else None
        models = (existing.get("models", {}) if existing else {}) or {}
        values = {
            "name": existing.get("name", "") if existing else "",
            "url": existing.get("url", "") if existing else "",
            "token": "",
            "opus": models.get("opus", ""),
            "sonnet": models.get("sonnet", ""),
            "haiku": models.get("haiku", ""),
            "anthropic": models.get("anthropic", ""),
        }
        fields = []
        for key, label in self.form_fields():
            fields.append({
                "key": key,
                "label": label,
                "value": values.get(key, ""),
                "initial": values.get(key, ""),
                "cursor": len(values.get(key, "")),
                "secret": key == "token",
            })
        self.form = {
            "edit_index": edit_index,
            "existing": dict(existing) if existing else None,
            "fields": fields,
            "token_hint": (
                self.i18n.t("form.token_hint.saved", "已加密；留空保持不变")
                if existing and profile_has_secret(existing)
                else self.i18n.t("form.token_hint.empty", "留空则不设置 Token")
            ),
        }
        self.form_focus = 0
        self.form_error = ""
        self.hover_action = None
        self.hover_button = None
        self.mode = "form"
        self.invalidate()

    def form_values(self):
        return {field["key"]: field["value"] for field in self.form["fields"]}

    def form_dirty(self):
        if not self.form:
            return False
        return any(field["value"] != field["initial"] for field in self.form["fields"])

    def request_form_close(self):
        if self.form_dirty():
            self.form_confirm_choice = 2
            self.mode = "form_confirm"
        else:
            self.close_form()
        self.invalidate()

    def close_form(self):
        self.form = None
        self.form_error = ""
        self.hover_button = None
        self.mode = "main"
        self.invalidate()

    def save_form(self):
        values = self.form_values()
        name = values.get("name", "").strip()
        if not name:
            self.form_error = self.i18n.t("form.errors.name_required", "供应商名称不能为空")
            self.mode = "form"
            self.invalidate()
            return False

        existing = self.form.get("existing")
        profile = dict(existing) if existing else {}
        profile["name"] = name
        profile["url"] = values.get("url", "").strip()
        profile["models"] = {
            "opus": values.get("opus", "").strip(),
            "sonnet": values.get("sonnet", "").strip(),
            "haiku": values.get("haiku", "").strip(),
            "anthropic": values.get("anthropic", "").strip(),
        }
        profile.pop("key", None)

        token = values.get("token", "").strip()
        try:
            if token:
                store_profile_secret(profile, token)
            elif existing and profile_has_secret(existing):
                preserve_existing_profile_secret(profile, existing)
            else:
                profile.pop("key_secret", None)
                profile.pop("key_dpapi", None)
                profile.pop("key", None)
                profile.pop("secret_backend", None)
        except Exception as exc:
            self.form_error = self.i18n.t("form.errors.token_encrypt_failed", "Token 加密失败：{message}", message=str(exc))
            self.mode = "form"
            self.invalidate()
            return False

        edit_index = self.form.get("edit_index")
        if edit_index is None:
            self.profiles.append(profile)
            self.index = len(self.profiles) - 1
            message = self.i18n.t("status.added_encrypted", "已新增供应商，Token 已加密保存")
        else:
            self.profiles[edit_index] = profile
            self.index = edit_index
            message = self.i18n.t("status.updated_encrypted", "已保存修改，Token 已加密保存")

        save_profiles(self.profiles)
        self.close_form()
        self.set_status(message, "class:status.good")
        return True

    def focused_field(self):
        if not self.form:
            return None
        return self.form["fields"][self.form_focus]

    def insert_text(self, text):
        field = self.focused_field()
        if not field or not text or not text.isprintable():
            return
        cursor = field["cursor"]
        field["value"] = field["value"][:cursor] + text + field["value"][cursor:]
        field["cursor"] = cursor + len(text)
        self.form_error = ""
        self.invalidate()

    def delete_before_cursor(self):
        field = self.focused_field()
        if not field:
            return
        cursor = field["cursor"]
        if cursor > 0:
            field["value"] = field["value"][:cursor - 1] + field["value"][cursor:]
            field["cursor"] = cursor - 1
            self.form_error = ""
            self.invalidate()

    def delete_at_cursor(self):
        field = self.focused_field()
        if not field:
            return
        cursor = field["cursor"]
        if cursor < len(field["value"]):
            field["value"] = field["value"][:cursor] + field["value"][cursor + 1:]
            self.form_error = ""
            self.invalidate()

    def move_field_cursor(self, delta):
        field = self.focused_field()
        if not field:
            return
        field["cursor"] = max(0, min(len(field["value"]), field["cursor"] + delta))
        self.invalidate()

    def focus_field_delta(self, delta):
        if not self.form:
            return
        self.form_focus = (self.form_focus + delta) % len(self.form["fields"])
        self.invalidate()

    def field_mouse_handler(self, index):
        def handler(mouse_event):
            if self.mode not in ("form", "form_confirm"):
                return None
            if mouse_event.event_type in (MouseEventType.MOUSE_MOVE, MouseEventType.MOUSE_UP):
                self.form_focus = index
                if mouse_event.event_type == MouseEventType.MOUSE_MOVE:
                    self.hover_button = None
                self.invalidate()
            return None

        return handler

    def form_button_handler(self):
        def handler(mouse_event):
            if self.mode != "form":
                return None
            action = self.form_button_at(mouse_event.position.x)
            if mouse_event.event_type == MouseEventType.MOUSE_MOVE:
                self.hover_button = action
                self.invalidate()
            elif mouse_event.event_type == MouseEventType.MOUSE_UP and action:
                if action == "save":
                    self.save_form()
                elif action == "back":
                    self.request_form_close()
            return None

        return handler

    def form_button_at(self, x):
        for action, (start, end) in self._form_button_regions.items():
            if start <= x < end:
                return action
        return None

    def run_form_confirm_choice(self):
        action = ("save", "discard", "cancel")[self.form_confirm_choice]
        if action == "save":
            self.save_form()
        elif action == "discard":
            self.close_form()
            self.set_status(self.i18n.t("status.unsaved_discarded", "已放弃未保存的修改"), "class:status.warn")
        else:
            self.mode = "form"
            self.invalidate()

    def confirm_mouse_handler(self, kind):
        def handler(mouse_event):
            if kind == "form" and self.mode != "form_confirm":
                return None
            if kind == "delete" and self.mode != "delete_confirm":
                return None

            regions = self._confirm_button_regions if kind == "form" else self._delete_button_regions
            action = None
            for name, (start, end) in regions.items():
                if start <= mouse_event.position.x < end:
                    action = name
                    break

            if mouse_event.event_type == MouseEventType.MOUSE_MOVE:
                self.hover_button = action
                self.invalidate()
            elif mouse_event.event_type == MouseEventType.MOUSE_UP and action:
                if kind == "form":
                    self.form_confirm_choice = {"save": 0, "discard": 1, "cancel": 2}[action]
                    self.run_form_confirm_choice()
                else:
                    self.delete_choice = {"delete": 0, "cancel": 1}[action]
                    self.run_delete_choice()
            return None

        return handler

    def confirm_button_mouse_handler(self, kind, action):
        def handler(mouse_event):
            if kind == "form" and self.mode != "form_confirm":
                return None
            if kind == "delete" and self.mode != "delete_confirm":
                return None

            if mouse_event.event_type == MouseEventType.MOUSE_MOVE:
                self.hover_button = action
                self.invalidate()
            elif mouse_event.event_type == MouseEventType.MOUSE_UP:
                if kind == "form":
                    self.form_confirm_choice = {"save": 0, "discard": 1, "cancel": 2}[action]
                    self.run_form_confirm_choice()
                else:
                    self.delete_choice = {"delete": 0, "cancel": 1}[action]
                    self.run_delete_choice()
            return None

        return handler

    def confirm_clear_mouse_handler(self, kind):
        def handler(mouse_event):
            if kind == "form" and self.mode != "form_confirm":
                return None
            if kind == "delete" and self.mode != "delete_confirm":
                return None

            if mouse_event.event_type == MouseEventType.MOUSE_MOVE and self.hover_button is not None:
                self.hover_button = None
                self.invalidate()
            return None

        return handler

    def open_delete_confirm(self):
        if len(self.profiles) <= 1:
            self.set_status(self.i18n.t("status.keep_one_provider", "至少保留一个供应商"), "class:status.warn")
            return
        self.delete_target_index = self.index
        self.delete_choice = 1
        self.hover_button = None
        self.mode = "delete_confirm"
        self.invalidate()

    def run_delete_choice(self):
        if self.delete_choice == 1:
            self.mode = "main"
            self.delete_target_index = None
            self.invalidate()
            return

        if self.delete_target_index is None or self.delete_target_index >= len(self.profiles):
            self.mode = "main"
            self.delete_target_index = None
            self.set_status(self.i18n.t("status.delete_target_changed", "删除目标已变化"), "class:status.warn")
            return

        removed = self.profiles[self.delete_target_index].get("name", "")
        self.profiles.pop(self.delete_target_index)
        save_profiles(self.profiles)
        self.index = min(self.index, max(0, len(self.profiles) - 1))
        self.mode = "main"
        self.delete_target_index = None
        self.set_status(self.i18n.t("status.deleted", "已删除 {name}", name=removed), "class:status.warn")

    def render(self):
        self.clear_expired_status()
        if self.mode in ("form", "form_confirm"):
            return self.render_form()
        if self.mode == "language":
            return self.render_language()
        return self.render_main()

    def render_main(self):
        width = self.terminal_width()
        fragments = []
        self._menu_regions = {}
        self._tip_launch_region = None

        title = " " + self.i18n.t("app.title", "Claude Code 环境切换中心") + " "
        self.add_line(fragments, [("class:title", self.fit_text(title, width))], width)
        self.add_line(fragments, [("class:border", "╭" + "─" * (width - 2) + "╮")], width)

        url_width = max(8, width - 52)
        header = (
            "│ "
            + self.fit_text(self.i18n.t("table.status", "状态"), 8)
            + " "
            + self.fit_text("", 2)
            + " "
            + self.fit_text(self.i18n.t("table.provider", "供应商名称"), 24)
            + " "
            + self.fit_text(self.i18n.t("table.base_url", "Base URL"), url_width)
            + " "
            + self.fit_text(self.i18n.t("table.token", "Token"), 10)
            + " │"
        )
        self.add_line(fragments, [("class:header", header)], width)
        self.add_line(fragments, [("class:border", "├" + "─" * (width - 2) + "┤")], width)

        if not self.profiles:
            empty = "│ " + self.fit_text(self.i18n.t("table.empty", "暂无供应商。按 A 新增。"), width - 4) + " │"
            self.add_line(fragments, [("class:dim", empty)], width)
        else:
            for row_index, profile in enumerate(self.profiles):
                self.render_profile_row(fragments, profile, row_index, width, url_width)
                if row_index == self.index and self.show_models:
                    self.render_model_rows(fragments, profile, width)

        self.add_line(fragments, [("class:border", "╰" + "─" * (width - 2) + "╯")], width)
        self.render_footer(fragments, width)

        if self.mode == "delete_confirm":
            self.render_delete_confirm(fragments, width)

        return fragments

    def render_language(self):
        width = self.terminal_width()
        fragments = []
        title = self.i18n.t("language.title", "Language")
        self.add_line(fragments, [("class:title", self.fit_text(f"Profiles / {title}", width))], width)
        self.add_line(fragments, [("class:border", "╭" + "─" * (width - 2) + "╮")], width)
        help_text = self.i18n.t("language.help", "↑↓:选择 | Enter:应用 | Esc:返回")
        self.add_line(fragments, [("class:dim", "│ " + self.fit_text(help_text, width - 4) + " │")], width)
        self.add_line(fragments, [("class:border", "├" + "─" * (width - 2) + "┤")], width)

        if not self.language_options:
            self.language_options = self.i18n.available_languages()

        for index, option in enumerate(self.language_options):
            row_handler = self.language_mouse_handler(index)
            selected = index == self.language_index
            current = option["code"] == self.i18n.language_preference
            if self.i18n.language_preference != AUTO_LANGUAGE and option["code"] == self.i18n.language:
                current = True
            row_style = "class:row.selected" if selected else ("class:row.hover" if index == self.hover_index else "class:row")
            selector = "▷ " if selected else "  "
            current_mark = self.i18n.t("language.current_mark", "当前") if current else ""
            display_name = option.get("native_name", option["code"])
            if option["code"] == AUTO_LANGUAGE and option.get("effective_code"):
                display_name = f"{display_name} ({option['effective_code']})"
            label = f"{selector}{display_name}  {option['code']}"
            if current_mark:
                label += f"  {current_mark}"
            completion = option.get("completion") or self.i18n.translation_completion(option["code"])
            percent = f"{completion.get('percent', 0):3d}%"
            content_width = max(0, width - 4)
            percent_width = self.display_width(percent)
            label_width = max(0, content_width - percent_width - 2)
            row_text = "│ " + self.ellipsize(label, label_width) + "  " + percent + " │"
            self.add_line(
                fragments,
                [(row_style, row_text, row_handler)],
                width,
                row_style,
                row_handler,
            )

        self.add_line(fragments, [("class:border", "╰" + "─" * (width - 2) + "╯")], width)
        return fragments

    def render_profile_row(self, fragments, profile, row_index, width, url_width):
        row_handler = self.main_mouse_handler("row", row_index)
        is_selected = row_index == self.index
        is_hover = row_index == self.hover_index
        is_active = profile.get("url") == self.active_url
        row_style = "class:row.selected" if is_selected else ("class:row.hover" if is_hover else "class:row")
        status = self.i18n.t("table.active", "已启用") if is_active else ""
        selector = "▷ " if is_selected else "  "
        selector_style = "class:selector.selected" if is_selected else row_style

        cells = [
            ("class:active" if is_active else row_style, self.fit_text(status, 8), row_handler),
            (row_style, " ", row_handler),
            (selector_style, selector, row_handler),
            (row_style, " ", row_handler),
            ("class:name " + row_style, self.ellipsize(profile.get("name", ""), 24), row_handler),
            (row_style, " ", row_handler),
            ("class:url " + row_style, self.ellipsize(profile.get("url", ""), url_width), row_handler),
            (row_style, " ", row_handler),
            ("class:token " + row_style, self.fit_text(localized_key_preview(profile, self.i18n), 10), row_handler),
        ]
        line = [(row_style, "│ ", row_handler)] + cells + [(row_style, " │", row_handler)]
        self.add_line(fragments, line, width, row_style, row_handler)

    def render_model_rows(self, fragments, profile, width):
        models = profile.get("models", {}) or {}
        model_lines = []
        if any(v for v in models.values() if v and str(v).strip()):
            model_lines = [
                f"├── Opus      : {models.get('opus', '-') or '-'}",
                f"├── Sonnet    : {models.get('sonnet', '-') or '-'}",
                f"├── Haiku     : {models.get('haiku', '-') or '-'}",
                f"└── ANTHROPIC : {models.get('anthropic', '-') or '-'}",
            ]
        else:
            model_lines = [self.i18n.t("table.no_models", "└── 暂无模型配置")]

        name_column_padding = 8 + 1 + 2 + 1
        for text in model_lines:
            line = "│ " + (" " * name_column_padding) + self.ellipsize(text, width - 4 - name_column_padding) + " │"
            self.add_line(fragments, [("class:model", line)], width)

    def render_footer(self, fragments, width):
        path_prefix = " CLI "
        path_value = f" {self.cwd}"
        self.add_line(
            fragments,
            [
                ("class:path.tag", path_prefix),
                ("class:path", self.ellipsize(path_value, width - self.display_width(path_prefix))),
            ],
            width,
        )

        if self.status_text:
            self.add_line(fragments, [(self.status_style, self.ellipsize(self.status_text, width))], width)
        else:
            self.render_menu_line(fragments, width)
        self.render_tip_line(fragments, width)
        self.render_author_line(fragments, width)

    def render_menu_line(self, fragments, width):
        handler = self.clear_hover_mouse_handler()
        launch_handler = self.tip_launch_mouse_handler()
        launch_button = self.i18n.t("footer.launch_button", " 启动 Claude Code ")
        launch_button = self.ellipsize(launch_button, max(14, min(28, width // 3)))
        launch_width = self.display_width(launch_button)
        available_menu_width = max(0, width - launch_width - 2)
        cursor = 0
        display_cursor = 0
        line = []
        self._menu_regions = {}
        segments = self.fit_menu_segments(available_menu_width)
        for idx, (action, label) in enumerate(segments):
            if idx:
                sep = " | "
                line.append(("class:menu", sep, handler))
                cursor += self.display_width(sep)
                display_cursor += self.display_width(sep)
            style = "class:menu.hover" if self.hover_action == action else "class:menu"
            start = cursor
            item_handler = self.menu_item_mouse_handler(action)
            line.append((style, label, item_handler))
            cursor += self.display_width(label)
            display_cursor += self.display_width(label)
            self._menu_regions[action] = (start, cursor)

        spacer_width = max(0, width - display_cursor - launch_width)
        spacer = " " * spacer_width
        line.append(("class:menu", spacer, handler))
        cursor += self.display_width(spacer)

        start = cursor
        cursor += self.display_width(launch_button)
        self._menu_regions["launch_button"] = (start, cursor)
        launch_style = "class:launch.hover" if self.hover_action == "launch" else "class:launch"
        line.append((launch_style, launch_button, launch_handler))
        self.add_line(fragments, line, width, "class:menu", handler)

    def render_tip_line(self, fragments, width):
        handler = self.tip_mouse_handler()
        self._tip_launch_region = None
        text = self.current_tip_text()
        cursor = "_" if int(time.time() * 2) % 2 == 0 else " "
        tip_width = max(0, width - self.display_width(cursor))
        visible_text = self.truncate_text(text, tip_width)
        line = self.tip_fragments(visible_text, handler)
        line.append(("class:tip", cursor, handler))
        self.add_line(
            fragments,
            line,
            width,
            "class:tip",
            handler,
        )

    def render_author_line(self, fragments, width):
        handler = self.author_link_mouse_handler()
        text = self.ellipsize(f"{GITHUB_ICON} {AUTHOR_NAME}  github.com/AonoChano", width)
        link_style = "class:meta.link.hover" if self.hover_action == "author_link" else "class:meta.link"
        text_width = self.display_width(text)
        padding = " " * max(0, width - text_width)
        line = [
            ("class:meta", padding),
            (link_style, text, handler),
        ]
        self.add_line(fragments, line, width, "class:meta")

    def render_form(self):
        width = self.terminal_width()
        fragments = []
        self._form_button_regions = {}
        title = (
            self.i18n.t("form.new_title", "新增供应商")
            if self.form and self.form.get("edit_index") is None
            else self.i18n.t("form.edit_title", "编辑供应商")
        )
        breadcrumb = f"Profiles / {title}"
        self.add_line(fragments, [("class:title", self.fit_text(breadcrumb, width))], width)
        self.add_line(fragments, [("class:border", "╭" + "─" * (width - 2) + "╮")], width)
        self.add_line(
            fragments,
            [("class:dim", "│ " + self.fit_text(self.i18n.t("form.help", "Tab/↑↓ 切换字段，Enter 前进，最后一项 Enter 保存，Esc 返回。"), width - 4) + " │")],
            width,
        )
        self.add_line(fragments, [("class:border", "├" + "─" * (width - 2) + "┤")], width)

        for index, field in enumerate(self.form["fields"]):
            self.render_form_field(fragments, field, index, width)

        self.add_line(fragments, [("class:border", "├" + "─" * (width - 2) + "┤")], width)
        if self.form_error:
            self.add_line(fragments, [("class:error", "│ " + self.fit_text(self.form_error, width - 4) + " │")], width)
        else:
            self.add_line(fragments, [("class:dim", "│ " + self.fit_text(self.i18n.t("form.token_note", "Token 不会明文写入 settings.json；保存到 profile 时使用当前系统安全存储。"), width - 4) + " │")], width)
        self.render_form_buttons(fragments, width)
        self.add_line(fragments, [("class:border", "╰" + "─" * (width - 2) + "╯")], width)

        if self.mode == "form_confirm":
            self.render_form_confirm(fragments, width)

        return fragments

    def render_form_field(self, fragments, field, index, width):
        handler = self.field_mouse_handler(index)
        focused = index == self.form_focus
        label_width = 18
        value_width = width - label_width - 6
        label = self.fit_text(field["label"], label_width)
        value = field["value"]

        if field["secret"]:
            hint = self.form.get("token_hint", "")
            if value:
                display = "•" * len(value)
            else:
                display = hint
        else:
            display = value

        if focused:
            cursor = field["cursor"]
            if field["secret"] and value:
                display = "•" * cursor + "▌" + "•" * (len(value) - cursor)
            elif field["secret"]:
                display = "▌" + ("" if value else f" {self.form.get('token_hint', '')}")
            else:
                display = value[:cursor] + "▌" + value[cursor:]

        field_style = "class:field.focus" if focused else "class:field"
        value_style = field_style if (value or focused) else "class:field.hint"
        marker = ">" if focused else " "
        line = [
            ("class:field.label", "│ " + marker + " " + label, handler),
            (value_style, self.ellipsize(display, value_width), handler),
            ("class:field", " │", handler),
        ]
        self.add_line(fragments, line, width, "class:field", handler)

    def render_form_buttons(self, fragments, width):
        handler = self.form_button_handler()
        buttons = [
            ("save", self.i18n.t("form.buttons.save", " 保存 ")),
            ("back", self.i18n.t("form.buttons.back", " 返回 ")),
        ]
        cursor = 2
        line = [("class:field", "│ ")]
        self._form_button_regions = {}
        for idx, (action, label) in enumerate(buttons):
            if idx:
                line.append(("class:field", "  "))
                cursor += self.mouse_width("  ")
            style = "class:button.hover" if self.hover_button == action else "class:button"
            self._form_button_regions[action] = (cursor, cursor + self.mouse_width(label))
            line.append((style, label, handler))
            cursor += self.mouse_width(label)
        display_cursor = 2
        for idx, (_, label) in enumerate(buttons):
            if idx:
                display_cursor += self.display_width("  ")
            display_cursor += self.display_width(label)
        line.append(("class:field", self.fit_text("", width - display_cursor - 2) + " │"))
        self.add_line(fragments, line, width, "class:field")

    def render_form_confirm(self, fragments, width):
        self.add_line(fragments, [("", "")], width)
        handler = self.confirm_clear_mouse_handler("form")
        self._confirm_button_regions = {}
        self.add_line(fragments, [("class:modal", self.fit_text(self.i18n.t("confirm.unsaved_title", " 未保存的修改 "), width))], width)
        self.add_line(fragments, [("class:modal", self.fit_text(self.i18n.t("confirm.unsaved_body", " 选择保存、放弃，或取消返回编辑。"), width))], width)
        buttons = [
            ("save", self.i18n.t("confirm.save", " 保存 ")),
            ("discard", self.i18n.t("confirm.discard", " 放弃 ")),
            ("cancel", self.i18n.t("confirm.cancel", " 取消 ")),
        ]
        labels = []
        cursor = 0
        for idx, (action, label) in enumerate(buttons):
            if idx:
                labels.append(("class:modal", "  ", handler))
                cursor += self.mouse_width("  ")
            selected = idx == self.form_confirm_choice or self.hover_button == action
            style = "class:button.hover" if selected else "class:button"
            item_handler = self.confirm_button_mouse_handler("form", action)
            self._confirm_button_regions[action] = (cursor, cursor + self.mouse_width(label))
            labels.append((style, label, item_handler))
            cursor += self.mouse_width(label)
        self.add_line(fragments, labels, width, "class:modal", handler)

    def render_delete_confirm(self, fragments, width):
        self.add_line(fragments, [("", "")], width)
        handler = self.confirm_clear_mouse_handler("delete")
        self._delete_button_regions = {}
        name = ""
        if self.delete_target_index is not None and self.delete_target_index < len(self.profiles):
            name = self.profiles[self.delete_target_index].get("name", "")
        self.add_line(fragments, [("class:modal", self.fit_text(self.i18n.t("confirm.delete_title", " 确认删除：{name}", name=name), width))], width)
        self.add_line(fragments, [("class:modal", self.fit_text(self.i18n.t("confirm.delete_body", " 删除后会立即写入 custom_profiles.json。"), width))], width)
        buttons = [
            ("delete", self.i18n.t("confirm.delete", " 确认删除 ")),
            ("cancel", self.i18n.t("confirm.cancel", " 取消 ")),
        ]
        labels = []
        cursor = 0
        for idx, (action, label) in enumerate(buttons):
            if idx:
                labels.append(("class:modal", "  ", handler))
                cursor += self.mouse_width("  ")
            selected = idx == self.delete_choice or self.hover_button == action
            if action == "delete":
                style = "class:button.danger.hover" if selected else "class:button.danger"
            else:
                style = "class:button.hover" if selected else "class:button"
            item_handler = self.confirm_button_mouse_handler("delete", action)
            self._delete_button_regions[action] = (cursor, cursor + self.mouse_width(label))
            labels.append((style, label, item_handler))
            cursor += self.mouse_width(label)
        self.add_line(fragments, labels, width, "class:modal", handler)

    def make_key_bindings(self):
        kb = KeyBindings()

        @kb.add("c-c", eager=True)
        def _(event):
            self.handle_ctrl_c()

        @kb.add("up")
        def _(event):
            if self.mode == "main":
                self.move_selection(-1)
            elif self.mode == "form":
                self.focus_field_delta(-1)
            elif self.mode == "delete_confirm":
                self.delete_choice = (self.delete_choice - 1) % 2
                self.invalidate()
            elif self.mode == "language" and self.language_options:
                self.language_index = (self.language_index - 1) % len(self.language_options)
                self.hover_index = None
                self.invalidate()

        @kb.add("down")
        def _(event):
            if self.mode == "main":
                self.move_selection(1)
            elif self.mode == "form":
                self.focus_field_delta(1)
            elif self.mode == "delete_confirm":
                self.delete_choice = (self.delete_choice + 1) % 2
                self.invalidate()
            elif self.mode == "language" and self.language_options:
                self.language_index = (self.language_index + 1) % len(self.language_options)
                self.hover_index = None
                self.invalidate()

        @kb.add("left")
        def _(event):
            if self.mode == "form":
                self.move_field_cursor(-1)
            elif self.mode == "form_confirm":
                self.form_confirm_choice = (self.form_confirm_choice - 1) % 3
                self.invalidate()
            elif self.mode == "delete_confirm":
                self.delete_choice = (self.delete_choice - 1) % 2
                self.invalidate()

        @kb.add("right")
        def _(event):
            if self.mode == "form":
                self.move_field_cursor(1)
            elif self.mode == "form_confirm":
                self.form_confirm_choice = (self.form_confirm_choice + 1) % 3
                self.invalidate()
            elif self.mode == "delete_confirm":
                self.delete_choice = (self.delete_choice + 1) % 2
                self.invalidate()

        @kb.add("home")
        def _(event):
            field = self.focused_field()
            if field:
                field["cursor"] = 0
                self.invalidate()

        @kb.add("end")
        def _(event):
            field = self.focused_field()
            if field:
                field["cursor"] = len(field["value"])
                self.invalidate()

        @kb.add("tab")
        def _(event):
            if self.mode == "form":
                self.focus_field_delta(1)

        @kb.add("s-tab")
        def _(event):
            if self.mode == "form":
                self.focus_field_delta(-1)

        @kb.add("enter")
        def _(event):
            if not self.busy:
                self.handle_enter()

        @kb.add("escape")
        def _(event):
            if self.mode == "form":
                self.request_form_close()
            elif self.mode == "form_confirm":
                self.mode = "form"
                self.invalidate()
            elif self.mode == "delete_confirm":
                self.mode = "main"
                self.delete_target_index = None
                self.invalidate()
            elif self.mode == "language":
                self.mode = "main"
                self.hover_index = None
                self.invalidate()

        @kb.add("backspace")
        def _(event):
            if self.mode == "form":
                self.delete_before_cursor()

        @kb.add("delete")
        def _(event):
            if self.mode == "form":
                self.delete_at_cursor()

        for key, action in [
            ("a", "add"),
            ("A", "add"),
            ("e", "edit"),
            ("E", "edit"),
            ("d", "delete"),
            ("D", "delete"),
            ("m", "models"),
            ("M", "models"),
            ("l", "language"),
            ("L", "language"),
            ("c", "launch"),
            ("C", "launch"),
        ]:
            kb.add(key)(self.key_action_handler(key, action))

        @kb.add("c-s")
        def _(event):
            if self.mode in ("form", "form_confirm"):
                self.save_form()

        @kb.add(Keys.Any)
        def _(event):
            if self.mode == "form" and event.data:
                self.insert_text(event.data)
            elif self.mode == "form_confirm" and event.data:
                key = event.data.lower()
                if key == "s":
                    self.form_confirm_choice = 0
                    self.run_form_confirm_choice()
                elif key == "d":
                    self.form_confirm_choice = 1
                    self.run_form_confirm_choice()
                elif key == "c":
                    self.form_confirm_choice = 2
                    self.run_form_confirm_choice()

        return kb

    def key_action_handler(self, key, action):
        def handler(event):
            if self.mode == "main":
                self.run_main_action(action)
            elif self.mode == "form":
                self.insert_text(key)
            elif self.mode == "form_confirm":
                mapped = {"s": 0, "d": 1, "c": 2}
                lower = key.lower()
                if lower in mapped:
                    self.form_confirm_choice = mapped[lower]
                    self.run_form_confirm_choice()
            elif self.mode == "delete_confirm":
                if key.lower() == "d":
                    self.delete_choice = 0
                    self.run_delete_choice()
                elif key.lower() == "c":
                    self.delete_choice = 1
                    self.run_delete_choice()

        return handler

    def run(self):
        self.update_terminal_title()
        control = FormattedTextControl(
            text=self.render,
            focusable=True,
            show_cursor=False,
        )
        window = Window(content=control, wrap_lines=False, style="class:screen")
        layout = Layout(window)
        self.pt_app = Application(
            layout=layout,
            key_bindings=self.make_key_bindings(),
            style=self.STYLE,
            full_screen=True,
            mouse_support=True,
            refresh_interval=0.1,
        )

        result = 0
        try:
            result = self.pt_app.run()
        finally:
            reset_terminal_modes()

        if self.launch_profile:
            name = self.launch_profile.get("name", "")
            set_terminal_title(f"Claude Code - {name}" if name else "Claude Code")
            if self.selection_output:
                self.selection_output.write_text(name, encoding="utf-8")
                reset_terminal_modes()
                return LAUNCH_REQUEST_EXIT_CODE

            reset_terminal_modes()
            console.print(f"[bold cyan]Claude 启动配置：{escape(name)}[/bold cyan]")
            console.print(f"[dim]工作目录：{self.cwd}[/dim]")
            try:
                completed = subprocess.run(
                    DEFAULT_LAUNCH_COMMAND,
                    env=build_runtime_env(self.launch_profile),
                    cwd=str(self.cwd),
                )
                return completed.returncode
            except FileNotFoundError:
                console.print("[bold red]错误：找不到 claude 命令[/bold red]")
                return 127
            finally:
                reset_terminal_modes()

        return result or 0


if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "--version":
            print(APP_VERSION)
        elif cmd == "--check-update":
            sys.exit(print_update_check())
        elif cmd == "--update":
            sys.exit(run_self_update())
        elif cmd == "--list":
            profiles = load_profiles()
            print(json.dumps([{"name": p.get('name', ''), "url": p.get('url', '')} for p in profiles]))
        elif cmd == "--apply" and len(sys.argv) > 2:
            print(apply_config(sys.argv[2]))
        elif cmd == "--run" and len(sys.argv) > 3:
            sys.exit(run_profile_command(sys.argv[2], sys.argv[3:]))
        elif cmd == "--select-launch" and len(sys.argv) > 2:
            ui_class = PromptApp if HAS_PROMPT_TOOLKIT else App
            sys.exit(ui_class(selection_output=sys.argv[2]).run())
        elif cmd == "--env-json" and len(sys.argv) > 2:
            target = find_profile(sys.argv[2])
            if not target:
                print(f"错误：找不到名为 {sys.argv[2]} 的配置", file=sys.stderr)
                sys.exit(2)
            print(json.dumps(build_profile_env(target), ensure_ascii=False))
        elif cmd == "--sanitize-settings":
            cleaned = sanitize_settings_tokens()
            print("已清理 settings.json 中的明文密钥" if cleaned else "settings.json 无需清理")
        sys.exit(0)

    try:
        ui_class = PromptApp if HAS_PROMPT_TOOLKIT else App
        sys.exit(ui_class().run())
    except KeyboardInterrupt:
        pass
