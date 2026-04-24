"""
Image tools — generate, resize, convert, and inspect images.
Image generation: Pollinations.ai (free, no API key).
Image processing: Pillow (PIL) — installed into .venv if needed.
"""
import importlib.util

import httpx
import time

from friday.path_utils import workspace_dir, resolve_user_path


def _pillow_available() -> bool:
    return importlib.util.find_spec("PIL") is not None


def register(mcp):

    @mcp.tool()
    async def generate_image(prompt: str, filename: str = "", width: int = 1024, height: int = 1024) -> str:
        """
        Generate an AI image from a text description and save it to the workspace.
        prompt: Describe the image you want (e.g. 'a futuristic city at night with neon lights').
        filename: Optional output filename (auto-generated if empty). Should end with .png.
        width/height: Image dimensions (default 1024x1024). Supported: 512, 768, 1024.
        Use this when the user says 'generate an image', 'create a picture of', 'draw', 'make an image of'.
        """
        try:
            if not filename:
                safe = "".join(c for c in prompt[:30] if c.isalnum() or c in " -_").strip().replace(" ", "_")
                filename = f"img_{safe}_{time.strftime('%H%M%S')}.png"
            if not filename.endswith(".png"):
                filename += ".png"

            save_path = workspace_dir() / filename

            import urllib.parse
            encoded_prompt = urllib.parse.quote(prompt)
            url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width={width}&height={height}&nologo=true"

            async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
                r = await client.get(url)
                if r.status_code != 200:
                    return f"Image generation failed (HTTP {r.status_code}). Try a different prompt."
                content_type = r.headers.get("content-type", "")
                if "image" not in content_type:
                    return f"Expected image but got {content_type}. Try again."
                save_path.write_bytes(r.content)

            size_kb = save_path.stat().st_size / 1024
            return f"Image generated and saved: {save_path} ({size_kb:.1f} KB)\nPrompt: '{prompt}'"
        except Exception as e:
            return f"Error generating image: {str(e)}"

    @mcp.tool()
    def resize_image(file_path: str, width: int, height: int, output_name: str = "") -> str:
        """
        Resize an image to specific dimensions and save the result.
        file_path: Path to the source image.
        width/height: Target dimensions in pixels.
        output_name: Optional output filename (saves next to original if not provided).
        Use this when the user asks to 'resize image', 'make this image smaller/larger'.
        """
        if not _pillow_available():
            return (
                "Pillow (PIL) is not installed. Run: install_package('Pillow')\n"
                "Then try again."
            )
        from PIL import Image
        try:
            src = resolve_user_path(file_path)
            if not src.exists():
                return f"Image not found: {src}"
            img = Image.open(src)
            original_size = img.size
            resized = img.resize((width, height), Image.LANCZOS)
            if not output_name:
                output_name = f"{src.stem}_resized_{width}x{height}{src.suffix}"
            dest = workspace_dir() / output_name
            resized.save(dest)
            return f"Resized {original_size[0]}x{original_size[1]} → {width}x{height}\nSaved: {dest}"
        except Exception as e:
            return f"Error resizing image: {str(e)}"

    @mcp.tool()
    def get_image_info(file_path: str) -> str:
        """
        Get metadata about an image: dimensions, format, color mode, file size.
        Use this when the user asks 'what are the dimensions of this image?', 'image info', 'image details'.
        """
        if not _pillow_available():
            return "Pillow (PIL) is not installed. Run: install_package('Pillow')"
        from PIL import Image
        try:
            src = resolve_user_path(file_path)
            if not src.exists():
                return f"Image not found: {src}"
            img = Image.open(src)
            file_size_kb = src.stat().st_size / 1024
            return (
                f"Image Info: {src.name}\n"
                f"Dimensions : {img.width} x {img.height} px\n"
                f"Format     : {img.format}\n"
                f"Mode       : {img.mode} (e.g. RGB, RGBA, L=grayscale)\n"
                f"File Size  : {file_size_kb:.1f} KB"
            )
        except Exception as e:
            return f"Error reading image info: {str(e)}"

    @mcp.tool()
    def convert_image_format(file_path: str, target_format: str, output_name: str = "") -> str:
        """
        Convert an image from one format to another (PNG↔JPG↔WEBP↔BMP↔GIF etc).
        file_path: Path to the source image.
        target_format: Target format extension (e.g. 'jpg', 'png', 'webp', 'bmp').
        Use this when the user says 'convert this image to PNG', 'save as JPEG', etc.
        """
        if not _pillow_available():
            return "Pillow (PIL) is not installed. Run: install_package('Pillow')"
        from PIL import Image
        try:
            src = resolve_user_path(file_path)
            if not src.exists():
                return f"Image not found: {src}"
            fmt = target_format.lower().strip().lstrip(".")
            fmt_map = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "webp": "WEBP",
                       "bmp": "BMP", "gif": "GIF", "tiff": "TIFF", "tif": "TIFF"}
            pil_fmt = fmt_map.get(fmt, fmt.upper())
            img = Image.open(src)
            # Convert RGBA to RGB for JPEG
            if pil_fmt == "JPEG" and img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            if not output_name:
                output_name = f"{src.stem}.{fmt}"
            dest = workspace_dir() / output_name
            img.save(dest, pil_fmt)
            size_kb = dest.stat().st_size / 1024
            return f"Converted {src.name} → {dest.name} ({pil_fmt}, {size_kb:.1f} KB)"
        except Exception as e:
            return f"Error converting image: {str(e)}"

    @mcp.tool()
    async def search_images(query: str, count: int = 3) -> str:
        """
        Search for and download images matching a query from the web to the workspace.
        query: Search term (e.g. 'sunset over mountains', 'python logo').
        count: Number of images to download (default 3, max 5).
        Use this when the user asks to 'find images of X', 'download pictures of X'.
        """
        count = min(max(1, count), 5)
        try:
            saved = []
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                for i in range(1, count + 1):
                    import urllib.parse
                    encoded = urllib.parse.quote(f"{query} {i}")
                    url = f"https://image.pollinations.ai/prompt/{encoded}?width=512&height=512&nologo=true&seed={i*42}"
                    r = await client.get(url)
                    if r.status_code == 200 and "image" in r.headers.get("content-type", ""):
                        safe_q = "".join(c for c in query[:20] if c.isalnum() or c in " _").strip().replace(" ", "_")
                        fname = f"search_{safe_q}_{i}.png"
                        dest = workspace_dir() / fname
                        dest.write_bytes(r.content)
                        saved.append(str(dest))

            if not saved:
                return f"Could not find images for '{query}'."
            return f"Downloaded {len(saved)} image(s) for '{query}':\n" + "\n".join(saved)
        except Exception as e:
            return f"Error searching images: {str(e)}"
