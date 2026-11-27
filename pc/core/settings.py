"""设置读写：接口地址、模型名、API Key。

API Key 落盘前用 Windows 的 DPAPI 加密，**不写明文**。

为什么用 DPAPI 而不是「自己异或一下」：
  - 异或的密钥必然要写在程序里，等于没加密，只是让用户看不出明文。
  - DPAPI（`CryptProtectData`）的密钥由 Windows 按当前用户账户派生并存
    在系统里，我们拿不到也不需要拿到。别的用户账户或另一台机器拿到这个
    文件也解不开。
  - 调用它只需要 ctypes，不引入任何第三方依赖。

局限（要诚实地说）：
  - 同一账户下运行的其他程序**可以**调用 `CryptUnprotectData` 解开它。
    所以它防的是「文件被拷走」「别的用户读到」，不防「本机同账户的恶意软件」。
    真正的凭据管理应该用 Windows 凭据管理器（`CredWrite`），但那套 API 的
    ctypes 封装更长，且对这个应用属于过度设计。

设置在 `%APPDATA%\\PdfReviewPC\\settings.json`。文件里除 API Key 外都是明文，
因为那些不是秘密（接口地址、模型名用户自己也会想看一眼）。
"""

from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

APP_DIR_NAME = "PdfReviewPC"
SETTINGS_FILE_NAME = "settings.json"

#: DPAPI 加密后的密文前缀，用来区分「已加密」与「旧版本留下的明文」。
#: 看见没有这个前缀的值，就当成明文读一次、下次保存时自动升级成密文。
ENCRYPTED_PREFIX = "dpapi:"


def app_data_dir() -> Path:
    """`%APPDATA%\\PdfReviewPC`。

    这里**只算路径，不创建目录**。创建放在真要写文件的时候：读设置时目录
    不存在本来就应该拿到默认值，不该因为「建不了目录」把程序拦在启动画面
    之外。真写不进去时由 `save_settings` 报一句人话。
    """
    base = os.environ.get("APPDATA")
    if not base:
        # 理论上 Windows 上一定有 APPDATA；真没有就退到用户主目录，
        # 总比直接崩掉好。
        base = str(Path.home())
    return Path(base) / APP_DIR_NAME


def settings_path() -> Path:
    return app_data_dir() / SETTINGS_FILE_NAME


# ---------------------------------------------------------------------------
# DPAPI
# ---------------------------------------------------------------------------


class _DataBlob(ctypes.Structure):
    """对应 Win32 的 `DATA_BLOB`。

    字段名不能改：ctypes 按顺序布局，名字只是给 Python 看的，
    但保持与 SDK 一致便于对照文档。
    """

    _fields_ = [
        ("cbData", ctypes.wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _blob_from_bytes(data: bytes) -> tuple[_DataBlob, ctypes.Array]:
    """把 bytes 包成 DATA_BLOB。

    返回 (blob, buffer) 两个值：`buffer` 必须被调用方持有到 API 调用结束，
    否则 Python 可能提前回收它，`pbData` 就成了野指针。
    """
    buffer = ctypes.create_string_buffer(data, len(data))
    blob = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    return blob, buffer


def _blob_to_bytes(blob: _DataBlob) -> bytes:
    return ctypes.string_at(blob.pbData, blob.cbData)


def dpapi_encrypt(plain: str) -> str:
    """加密并返回 `dpapi:<base64>`。失败抛 OSError。"""
    if not plain:
        return ""

    data = plain.encode("utf-8")
    in_blob, _in_buffer = _blob_from_bytes(data)
    out_blob = _DataBlob()

    # CRYPTPROTECT_UI_FORBIDDEN = 0x1：禁止弹任何系统对话框。
    # 没有这个标志时，如果 DPAPI 需要交互（正常情况不需要），
    # 程序会卡住等一个没人能点的窗口。
    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        0x1,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise OSError(f"DPAPI 加密失败，Windows 错误码 {ctypes.GetLastError()}")

    try:
        encrypted = _blob_to_bytes(out_blob)
    finally:
        # 必须释放，否则每次保存设置都漏一块内存
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)

    return ENCRYPTED_PREFIX + base64.b64encode(encrypted).decode("ascii")


def dpapi_decrypt(token: str) -> str:
    """解密 `dpapi:<base64>`。不是这个格式就当成明文原样返回。"""
    if not token:
        return ""
    if not token.startswith(ENCRYPTED_PREFIX):
        # 旧版本或手工写的明文，兼容一下
        return token

    try:
        raw = base64.b64decode(token[len(ENCRYPTED_PREFIX) :], validate=True)
    except Exception as exc:  # noqa: BLE001 - 坏数据统一当解密失败
        raise OSError(f"API Key 密文不是合法的 base64：{exc}") from exc

    in_blob, _in_buffer = _blob_from_bytes(raw)
    out_blob = _DataBlob()

    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        0x1,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise OSError(
            f"API Key 解密失败（Windows 错误码 {ctypes.GetLastError()}）。"
            "通常是因为设置文件是从别的电脑或别的账户拷来的。"
        )

    try:
        plain = _blob_to_bytes(out_blob)
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)

    return plain.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# 设置对象
# ---------------------------------------------------------------------------


@dataclass
class Settings:
    """应用设置。字段名就是 JSON 里的键名，不做 camelCase 转换 ——
    这个文件只给本程序读写，没有跨语言兼容的压力。"""

    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    api_key: str = ""
    #: 每块请求几张卡片。iOS 侧会夹到 3...12，这里保持同样的语义。
    cards_per_chunk: int = 6
    #: 上一次选中的牌组目录，方便下次打开直接进去
    last_project: Optional[str] = None

    #: 读设置时 API Key 解密失败（文件来自别的电脑/别的账户）。
    #: 不落盘，只是让界面能提示「Key 解不开了，请重填」。
    key_error: bool = field(default=False, repr=False)

    # ------------------------------------------------------------------
    # 校验
    # ------------------------------------------------------------------

    def validate(self) -> list[str]:
        """返回问题列表，空表示可用。给界面在点「开始」前调用。"""
        problems: list[str] = []
        if not self.base_url.strip():
            problems.append("接口地址不能为空")
        elif not self.base_url.strip().startswith(("http://", "https://")):
            problems.append("接口地址要以 http:// 或 https:// 开头")
        if not self.model.strip():
            problems.append("模型名不能为空")
        if not self.api_key.strip():
            problems.append("还没填 API Key")
        if not (1 <= self.cards_per_chunk <= 12):
            problems.append("每块卡片数要在 1 到 12 之间")
        return problems

    @property
    def is_configured(self) -> bool:
        return not self.validate()


# ---------------------------------------------------------------------------
# 读写
# ---------------------------------------------------------------------------


def load_settings(path: Optional[Path] = None) -> Settings:
    """读设置。文件不存在或坏掉时返回默认值，不抛异常。

    坏掉时静默用默认值是刻意的：设置文件损坏不该让程序打不开，
    用户重新填一次就行。真正的错误（比如解密失败）会在 `api_key_error`
    里体现，界面可以提示。
    """
    target = path or settings_path()
    if not target.exists():
        return Settings()

    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return Settings()

    if not isinstance(data, dict):
        return Settings()

    settings = Settings()
    settings.base_url = str(data.get("baseUrl") or settings.base_url)
    settings.model = str(data.get("model") or settings.model)
    settings.cards_per_chunk = _safe_int(
        data.get("cardsPerChunk"), settings.cards_per_chunk
    )
    last = data.get("lastProject")
    settings.last_project = str(last) if last else None

    encrypted = data.get("apiKey")
    if isinstance(encrypted, str) and encrypted:
        try:
            settings.api_key = dpapi_decrypt(encrypted)
        except OSError:
            # 解密失败不阻断启动：用户重填一次 Key 就恢复了。
            settings.api_key = ""
            settings.key_error = True
    return settings


def save_settings(settings: Settings, path: Optional[Path] = None) -> None:
    """写设置。API Key 加密后落盘。

    先写临时文件再 `os.replace`：中途断电或磁盘满时，要么是旧文件，
    要么是新文件，不会留下半个 JSON 让下次启动读不出来。
    """
    target = path or settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "baseUrl": settings.base_url,
        "model": settings.model,
        "apiKey": dpapi_encrypt(settings.api_key) if settings.api_key else "",
        "cardsPerChunk": settings.cards_per_chunk,
        "lastProject": settings.last_project,
    }

    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, target)


def _safe_int(value: object, fallback: int) -> int:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return fallback
    return fallback
