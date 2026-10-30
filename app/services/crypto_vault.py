# app/services/crypto_vault.py
import io
import os
import time
import json
import base64
import hashlib
from PIL import Image
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from dotenv import load_dotenv

load_dotenv()

_raw_salt = os.getenv("SECRET_SALT", "").strip()
if len(_raw_salt) < 16:
    raise RuntimeError(
        "CRITICAL CONFIG ERROR: SECRET_SALT environment variable must be set and at least 16 characters long."
    )
SALT = _raw_salt.encode("utf-8")

# In-memory 5-minute TTL cache so PBKDF2 (100k rounds) only runs once per login session
_KEY_CACHE: dict[str, tuple[bytes, float]] = {}
KEY_CACHE_TTL_SECONDS = 300


def hash_invite_code(code: str) -> str:
    clean = code.strip()
    return hashlib.sha256(SALT + clean.encode("utf-8")).hexdigest()


def derive_fernet_key_from_code(code: str) -> bytes:
    cache_id = f"derive:{hash_invite_code(code)}"
    now = time.time()
    if cache_id in _KEY_CACHE and _KEY_CACHE[cache_id][1] > now:
        return _KEY_CACHE[cache_id][0]

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=SALT,
        iterations=100_000,
    )
    derived = base64.urlsafe_b64encode(kdf.derive(code.strip().encode("utf-8")))
    _KEY_CACHE[cache_id] = (derived, now + KEY_CACHE_TTL_SECONDS)
    return derived


def wrap_vault_key_for_role_code(vault_master_key: bytes, member_role_code: str) -> str:
    kek = derive_fernet_key_from_code(member_role_code)
    return Fernet(kek).encrypt(vault_master_key).decode("utf-8")


def unwrap_vault_key_with_role_code(wrapped_key_str: str, member_role_code: str) -> bytes:
    cache_id = f"unwrap:{hash_invite_code(member_role_code)}:{wrapped_key_str[:16]}"
    now = time.time()
    if cache_id in _KEY_CACHE and _KEY_CACHE[cache_id][1] > now:
        return _KEY_CACHE[cache_id][0]

    kek = derive_fernet_key_from_code(member_role_code)
    try:
        unwrapped = Fernet(kek).decrypt(wrapped_key_str.encode("utf-8"))
    except InvalidToken as exc:
        raise ValueError("Failed to unwrap vault key: invalid code or corrupted key.") from exc

    _KEY_CACHE[cache_id] = (unwrapped, now + KEY_CACHE_TTL_SECONDS)
    return unwrapped


def encrypt_json_with_key(data: dict | list, vault_key: bytes) -> str:
    if data is None:
        return ""
    raw_bytes = json.dumps(data, ensure_ascii=False).encode("utf-8")
    return Fernet(vault_key).encrypt(raw_bytes).decode("utf-8")


def decrypt_json_with_key(ciphertext: str | dict | list, vault_key: bytes):
    """Raises ValueError on decryption error instead of silently returning {}."""
    if not ciphertext:
        return {}
    if isinstance(ciphertext, (dict, list)):
        return ciphertext
    try:
        decrypted_bytes = Fernet(vault_key).decrypt(ciphertext.encode("utf-8"))
        return json.loads(decrypted_bytes.decode("utf-8"))
    except Exception as exc:
        raise ValueError("Decryption error: SECRET_SALT changed or ciphertext is corrupted.") from exc


def encrypt_bytes_with_key(raw_bytes: bytes, vault_key: bytes) -> bytes:
    return Fernet(vault_key).encrypt(raw_bytes)


def decrypt_bytes_with_key(encrypted_bytes: bytes, vault_key: bytes) -> bytes:
    try:
        return Fernet(vault_key).decrypt(encrypted_bytes)
    except Exception as exc:
        raise ValueError("File decryption failed.") from exc


def compress_image_for_free_storage(file_bytes: bytes, filename: str, max_dim: int = 1600) -> tuple[bytes, str]:
    ext = filename.lower().split(".")[-1] if "." in filename else ""
    if ext == "pdf":
        return file_bytes, "application/pdf"

    img = Image.open(io.BytesIO(file_bytes)).convert("RGB")
    width, height = img.size

    if max(width, height) > max_dim:
        scale = max_dim / float(max(width, height))
        new_size = (int(width * scale), int(height * scale))
        img = img.resize(new_size, Image.Resampling.LANCZOS)

    out = io.BytesIO()
    img.save(out, format="WEBP", quality=75, method=4)
    return out.getvalue(), "image/webp"