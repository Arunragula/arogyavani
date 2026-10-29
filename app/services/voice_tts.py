# app/services/voice_tts.py
import os
import uuid
import edge_tts

AUDIO_DIR = "generated_audio"
os.makedirs(AUDIO_DIR, exist_ok=True)

# Warm, natural Neural Voices for India, Middle East & Europe
LANGUAGE_VOICE_MAP = {
    "english": "en-IN-NeerjaNeural",      # Warm Indian-English female voice
    "hinglish": "hi-IN-SwaraNeural",      # Natural Hindi/Hinglish voice
    "hindi": "hi-IN-SwaraNeural",         # Natural Hindi female voice
    "telugu": "te-IN-ShrutiNeural",       # Natural Telugu female voice
    "tamil": "ta-IN-PallaviNeural",       # Natural Tamil female voice
    "kannada": "kn-IN-SapnaNeural",       # Natural Kannada female voice
    "malayalam": "ml-IN-SobhanaNeural",   # Natural Malayalam female voice
    "bengali": "bn-IN-TanishaaNeural",    # Natural Bengali female voice
    "marathi": "mr-IN-AarohiNeural",      # Natural Marathi female voice
    "gujarati": "gu-IN-DhwaniNeural",     # Natural Gujarati female voice
    "urdu": "ur-PK-UzmaNeural",           # Natural Urdu female voice
    "arabic": "ar-SA-ZariyahNeural",      # Natural Arabic female voice
    "spanish": "es-ES-ElviraNeural",      # Natural Spanish female voice
    "french": "fr-FR-DeniseNeural",       # Natural French female voice
    "german": "de-DE-KatjaNeural",        # Natural German female voice
}


def get_voice_for_language(language: str) -> str:
    lang_key = language.strip().lower()
    for key, voice in LANGUAGE_VOICE_MAP.items():
        if key in lang_key:
            return voice
    return "en-IN-NeerjaNeural"  # Default warm voice


async def generate_voice_mp3(script_text: str, language: str = "English") -> dict:
    """
    Converts the AI doctor's spoken summary script into an MP3 file for $0 using edge-tts.
    """
    voice_name = get_voice_for_language(language)
    filename = f"summary_{uuid.uuid4().hex[:8]}.mp3"
    filepath = os.path.join(AUDIO_DIR, filename)

    # Slightly slower rate (-5%) makes medical explanations clearer for elders
    communicate = edge_tts.Communicate(text=script_text, voice=voice_name, rate="-5%")
    await communicate.save(filepath)

    return {
        "audio_filename": filename,
        "filepath": filepath,
        "voice_used": voice_name,
    }