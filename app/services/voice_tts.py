# app/services/voice_tts.py
import hashlib
from collections import OrderedDict
import edge_tts

# Small in-memory LRU cache (max 25 audio clips) so re-clicking a card is instant with 0 disk usage
MEMORY_AUDIO_CACHE: OrderedDict[str, bytes] = OrderedDict()
MAX_CACHE_ITEMS = 25

LANGUAGE_VOICE_MAP = {
    "english": "en-IN-NeerjaNeural",
    "hinglish": "hi-IN-SwaraNeural",
    "hindi": "hi-IN-SwaraNeural",
    "telugu": "te-IN-ShrutiNeural",
    "tamil": "ta-IN-PallaviNeural",
    "kannada": "kn-IN-SapnaNeural",
    "malayalam": "ml-IN-SobhanaNeural",
    "bengali": "bn-IN-TanishaaNeural",
    "marathi": "mr-IN-AarohiNeural",
    "gujarati": "gu-IN-DhwaniNeural",
    "urdu": "ur-PK-UzmaNeural",
    "arabic": "ar-SA-ZariyahNeural",
    "spanish": "es-ES-ElviraNeural",
    "french": "fr-FR-DeniseNeural",
    "german": "de-DE-KatjaNeural",
}


def get_voice_for_language(language: str) -> str:
    lang_key = language.strip().lower()
    for key, voice in LANGUAGE_VOICE_MAP.items():
        if key in lang_key:
            return voice
    return "en-IN-NeerjaNeural"


async def stream_voice_mp3_bytes(script_text: str, language: str = "English") -> bytes:
    """
    Streams TTS audio bytes directly into RAM without writing any files to disk!
    Protects ephemeral cloud servers (like Render) and keeps audio private.
    """
    voice_name = get_voice_for_language(language)
    cache_key = hashlib.md5(f"{voice_name}:{script_text}".encode("utf-8")).hexdigest()

    if cache_key in MEMORY_AUDIO_CACHE:
        MEMORY_AUDIO_CACHE.move_to_end(cache_key)
        return MEMORY_AUDIO_CACHE[cache_key]

    communicate = edge_tts.Communicate(text=script_text, voice=voice_name, rate="-5%")
    audio_chunks = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_chunks.extend(chunk["data"])

    audio_bytes = bytes(audio_chunks)
    MEMORY_AUDIO_CACHE[cache_key] = audio_bytes
    if len(MEMORY_AUDIO_CACHE) > MAX_CACHE_ITEMS:
        MEMORY_AUDIO_CACHE.popitem(last=False)

    return audio_bytes