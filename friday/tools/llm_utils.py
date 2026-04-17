"""
Internal LLM Utilities — provides a shared interface for tools to call the AI for reasoning,
without the overhead of spawning a full subagent.
Implements SOTA Multi-LLM provider fallback for maximum reliability.
"""
import os
import json
import httpx
import logging
import re
import asyncio

# Set up logging for internal reasoning
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("friday.llm_utils")

async def call_llm_gemini(prompt: str, system_prompt: str, json_mode: bool) -> str:
    """Primary provider: Google Gemini."""
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key: return "SKIP"
    
    model = os.environ.get("GEMINI_LLM_MODEL", "gemini-1.5-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    
    generation_config = {}
    if json_mode:
        generation_config["response_mime_type"] = "application/json"

    payload = {
        "contents": [{"role": "user", "parts": [{"text": f"SYSTEM: {system_prompt}\n\nUSER_REQUEST: {prompt}"}]}],
        "generationConfig": generation_config,
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ]
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        
        text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
        return text.strip()

async def call_llm_openai(prompt: str, system_prompt: str, json_mode: bool) -> str:
    """Secondary provider: OpenAI (Reliability fallback)."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key: return "SKIP"

    model = "gpt-4o" # High reliability SOTA fallback
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        return data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()

async def call_llm(prompt: str, system_prompt: str = "You are F.R.I.D.A.Y.'s internal reasoning engine.", json_mode: bool = False) -> str:
    """
    Call the SOTA Reasoning Hub.
    Automatically handles provider fallbacks if one is unreachable or fails.
    """
    # 1. Try Gemini
    try:
        res = await call_llm_gemini(prompt, system_prompt, json_mode)
        if res != "SKIP":
            return _cleanup_json(res) if json_mode else res
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.HTTPStatusError) as e:
        logger.warning(f"Gemini reasoning failed ({type(e).__name__}). Falling back to OpenAI...")

    # 2. Try OpenAI
    try:
        res = await call_llm_openai(prompt, system_prompt, json_mode)
        if res != "SKIP":
            return _cleanup_json(res) if json_mode else res
    except Exception as e:
        logger.error(f"Reasoning Hub: Persistence failure. All providers offline. Last error: {str(e)}")
        return f"Error: All reasoning providers unreachable. {str(e)}"

    return "Error: No LLM providers configured in .env"

def _cleanup_json(text: str) -> str:
    """Robustly extract JSON from potential markdown wrapping."""
    if text.startswith("```"):
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            text = match.group(1).strip()
    return text
