"""
Translation tools — translate text between any languages using the MyMemory free API.
No API key required. Supports all major world languages.
"""

import httpx
import urllib.parse


LANGUAGE_MAP = {
    # Common names → ISO 639-1 codes
    "hindi": "hi", "bengali": "bn", "tamil": "ta", "telugu": "te",
    "kannada": "kn", "malayalam": "ml", "marathi": "mr", "gujarati": "gu",
    "punjabi": "pa", "odia": "or", "urdu": "ur", "sanskrit": "sa",
    "english": "en", "french": "fr", "spanish": "es", "german": "de",
    "italian": "it", "portuguese": "pt", "russian": "ru", "japanese": "ja",
    "korean": "ko", "chinese": "zh", "arabic": "ar", "dutch": "nl",
    "swedish": "sv", "norwegian": "no", "danish": "da", "finnish": "fi",
    "polish": "pl", "turkish": "tr", "greek": "el", "hebrew": "he",
    "thai": "th", "vietnamese": "vi", "indonesian": "id", "malay": "ms",
    "persian": "fa", "swahili": "sw", "afrikaans": "af",
}


def _resolve_lang_code(lang: str) -> str:
    """Convert language name or code to ISO code."""
    lang_lower = lang.lower().strip()
    if lang_lower in LANGUAGE_MAP:
        return LANGUAGE_MAP[lang_lower]
    # If already a code (e.g., 'hi', 'en-US')
    if len(lang) <= 5 and lang.replace("-", "").isalpha():
        return lang
    return lang_lower


def register(mcp):

    @mcp.tool()
    async def translate_text(text: str, target_language: str, source_language: str = "auto") -> str:
        """
        Translate text from one language to another.
        target_language: Language name (e.g. 'Hindi', 'French', 'Spanish') or ISO code (e.g. 'hi', 'fr').
        source_language: Optional source language. Leave as 'auto' for automatic detection.
        Use this when the user says 'translate this', 'say this in Hindi', 'convert to French', etc.
        """
        try:
            target_code = _resolve_lang_code(target_language)
            source_code = "autodetect" if source_language == "auto" else _resolve_lang_code(source_language)

            lang_pair = f"{source_code}|{target_code}"
            encoded_text = urllib.parse.quote(text[:500])  # MyMemory limit ~500 chars per call

            url = f"https://api.mymemory.translated.net/get?q={encoded_text}&langpair={lang_pair}"

            async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
                response = await client.get(url)
                data = response.json()

            status = data.get("responseStatus", 0)
            if status != 200 and status != "200":
                error_msg = data.get("responseDetails", "Unknown error from translation API")
                return f"Translation failed (status {status}): {error_msg}"

            translated = data.get("responseData", {}).get("translatedText", "")

            if not translated:
                return f"Translation returned empty. The API may not support {target_language}."

            target_display = target_language.capitalize()
            result = f"Translation ({target_display}):\n{translated}"

            # For longer texts, handle in chunks
            if len(text) > 500:
                result += "\n\n[Note: Text was truncated to 500 characters for translation. For longer text, split it up.]"

            return result

        except Exception as e:
            return f"Error translating text: {str(e)}"

    @mcp.tool()
    async def detect_language(text: str) -> str:
        """
        Detect the language of a given text.
        Use this when the user asks 'what language is this?', 'can you identify this language?'.
        """
        try:
            encoded_text = urllib.parse.quote(text[:200])
            # Use MyMemory with English as target — detection comes back in response
            url = f"https://api.mymemory.translated.net/get?q={encoded_text}&langpair=autodetect|en"

            async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
                response = await client.get(url)
                data = response.json()

            detected = data.get("responseData", {}).get("detectedLanguage", None)

            # Reverse lookup the code to a name
            code_to_name = {v: k.capitalize() for k, v in LANGUAGE_MAP.items()}

            if detected:
                lang_name = code_to_name.get(detected.lower(), detected)
                return f"Detected language: {lang_name} (code: {detected})"

            return "Could not confidently detect the language."

        except Exception as e:
            return f"Error detecting language: {str(e)}"
