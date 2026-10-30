# app/services/crypto_vault.py
import io
import os
import json
import base64
import secrets
import hashlib
from PIL import Image
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from dotenv import load_dotenv

load_dotenv()

SALT = os.getenv("SECRET_SALT", "arogyavani-zero-knowledge-salt-2026").encode("utf-8")


def hash_invite_code(code: str) -> str:
    """One-way SHA-256 hash stored in DB. The raw code is NEVER stored in the database!"""
    clean = code.strip()
    return hashlib.sha256(SALT + clean.encode("utf-8")).hexdigest()


def derive_fernet_key_from_code(code: str) -> bytes:
    """Derives a 256-bit AES/Fernet key in memory from the user's secret code."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=SALT,
        iterations=100_000,
    )
    return base64.urlsafe_b64encode(kdf.derive(code.strip().encode("utf-8")))


def generate_new_vault_master_key() -> bytes:
    """Generates a random 256-bit master key for a household vault."""
    return Fernet.generate_key()


def wrap_vault_key_for_role_code(vault_master_key: bytes, member_role_code: str) -> str:
    """
    Envelope Encryption: Encrypts the household's master key using a family member's
    assigned role code ('owner', 'editor', or 'viewer').
    """
    kek = derive_fernet_key_from_code(member_role_code)
    return Fernet(kek).encrypt(vault_master_key).decode("utf-8")


def unwrap_vault_key_with_role_code(wrapped_key_str: str, member_role_code: str) -> bytes:
    """Unlocks the household master key in memory using the user's secret code."""
    kek = derive_fernet_key_from_code(member_role_code)
    return Fernet(kek).decrypt(wrapped_key_str.encode("utf-8"))


# =========================================================
# ZERO-KNOWLEDGE ENCRYPTION FOR DB JSON & UPLOADED FILES
# =========================================================

def encrypt_json_with_key(data: dict | list, vault_key: bytes) -> str:
    """Encrypts medical JSON so neither DB admins nor developers can read it."""
    if data is None:
        return ""
    raw_bytes = json.dumps(data, ensure_ascii=False).encode("utf-8")
    return Fernet(vault_key).encrypt(raw_bytes).decode("utf-8")


def decrypt_json_with_key(ciphertext: str | dict | list, vault_key: bytes):
    """Decrypts medical JSON in memory only for the authenticated user."""
    if not ciphertext:
        return {}
    if isinstance(ciphertext, (dict, list)):
        return ciphertext
    try:
        decrypted_bytes = Fernet(vault_key).decrypt(ciphertext.encode("utf-8"))
        return json.loads(decrypted_bytes.decode("utf-8"))
    except (InvalidToken, Exception):
        return {}


def encrypt_bytes_with_key(raw_bytes: bytes, vault_key: bytes) -> bytes:
    """Encrypts compressed image/PDF bytes before saving to storage."""
    return Fernet(vault_key).encrypt(raw_bytes)


def decrypt_bytes_with_key(encrypted_bytes: bytes, vault_key: bytes) -> bytes:
    """Decrypts stored image/PDF bytes on the fly when the user views their report."""
    return Fernet(vault_key).decrypt(encrypted_bytes)


# =========================================================
# SMART IMAGE COMPRESSOR (6 MB -> ~120 KB WebP)
# =========================================================

def compress_image_for_free_storage(file_bytes: bytes, filename: str, max_dim: int = 1600) -> tuple[bytes, str]:
    """
    Shrinks large 5-10 MB phone camera photos down to ~120 KB WebP
    while keeping small medical print sharp for doctors!
    Leaves PDFs untouched (PDF size/pages are capped separately).
    """
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