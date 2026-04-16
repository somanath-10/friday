"""
Advanced file tools — download files, read PDFs, create documents,
open in Finder, and manage the workspace directory.
"""

import os
import subprocess
import time
from pathlib import Path

from friday.path_utils import resolve_user_path, safe_filename, workspace_dir, workspace_path


def _workspace_dir() -> str:
    return str(workspace_dir())


def register(mcp):

    @mcp.tool()
    async def download_file(url: str, filename: str = "") -> str:
        """
        Download any file from a URL and save it to the workspace folder.
        filename is optional — auto-detected from URL if not provided.
        Use this when the user asks to 'download', 'save', or 'fetch' a file from the internet.
        """
        import httpx
        try:
            if not filename:
                filename = url.split("/")[-1].split("?")[0] or f"download_{int(time.time())}"
            filename = safe_filename(filename, f"download_{int(time.time())}")

            save_path = workspace_path(filename)

            async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
                response = await client.get(url)
                response.raise_for_status()
                content = response.content

            with open(save_path, "wb") as f:
                f.write(content)

            size_kb = len(content) / 1024
            return f"Downloaded '{filename}' ({size_kb:.1f} KB) → {save_path}"
        except Exception as e:
            return f"Error downloading file: {str(e)}"

    @mcp.tool()
    def read_pdf(file_path: str) -> str:
        """
        Extract and return all the text content from a PDF file.
        Use this when the user asks to 'read a PDF', 'summarize a PDF', or 'what's in this PDF'.
        file_path: Absolute or relative path to the .pdf file.
        """
        try:
            resolved_path = resolve_user_path(file_path)
            if not os.path.exists(resolved_path):
                return f"File not found: {resolved_path}"

            if not str(resolved_path).lower().endswith(".pdf"):
                return "This tool only reads PDF files. Use get_file_contents for text files."

            # Try pypdf first (fast, pure Python)
            try:
                import pypdf
                reader = pypdf.PdfReader(str(resolved_path))
                text_parts = []
                for i, page in enumerate(reader.pages):
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(f"--- Page {i+1} ---\n{page_text}")

                full_text = "\n\n".join(text_parts)
                if not full_text.strip():
                    return "PDF appears to have no extractable text (may be scanned images)."

                # Limit output to avoid overwhelming the LLM
                if len(full_text) > 8000:
                    return full_text[:8000] + f"\n\n... [Truncated. PDF has {len(reader.pages)} pages total.] ..."
                return full_text
            except ImportError:
                pass

            # Fallback: use pdftotext (if available on macOS via Homebrew)
            try:
                result = subprocess.run(
                    ["pdftotext", str(resolved_path), "-"],
                    capture_output=True, text=True, timeout=30
                )
                if result.returncode == 0 and result.stdout.strip():
                    text = result.stdout
                    if len(text) > 8000:
                        text = text[:8000] + "\n\n... [Truncated] ..."
                    return text
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass

            return (
                "Could not extract text from PDF. "
                "Install 'pypdf' via: pip install pypdf\n"
                "Or install pdftotext via: brew install poppler"
            )

        except Exception as e:
            return f"Error reading PDF: {str(e)}"

    @mcp.tool()
    def create_document(filename: str, content: str, subdirectory: str = "") -> str:
        """
        Create a new text file (.txt, .md, .py, .html, .json, etc.) in the workspace folder.
        Use this to create reports, notes, scripts, drafts, or any text file the user requests.
        filename: Name of the file including extension (e.g., 'report.md', 'script.py').
        content: The text content to write into the file.
        subdirectory: Optional sub-folder inside the workspace.
        """
        try:
            workspace = workspace_dir()
            if subdirectory:
                target_dir = workspace_path(subdirectory)
                Path(target_dir).mkdir(parents=True, exist_ok=True)
            else:
                target_dir = workspace

            file_path = Path(target_dir) / safe_filename(filename, "document.txt")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)

            size_kb = len(content.encode("utf-8")) / 1024
            return f"Created '{filename}' ({size_kb:.2f} KB) → {file_path}"
        except Exception as e:
            return f"Error creating document: {str(e)}"

    @mcp.tool()
    def list_workspace_files() -> str:
        """
        List all files in the workspace folder — everything F.R.I.D.A.Y. has created or downloaded.
        Use this when the user asks 'what files do you have?', 'show me workspace', 'list my files'.
        """
        try:
            workspace = _workspace_dir()
            all_files = []
            for root, dirs, files in os.walk(workspace):
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                for fn in files:
                    if fn.startswith("."):
                        continue
                    full_path = os.path.join(root, fn)
                    rel_path = os.path.relpath(full_path, workspace)
                    size = os.path.getsize(full_path)
                    size_str = f"{size/1024:.1f} KB" if size > 1024 else f"{size} B"
                    all_files.append(f"  {rel_path}  ({size_str})")

            if not all_files:
                return f"Workspace is empty. Workspace location: {workspace}"

            return f"Workspace: {workspace}\n\nFiles ({len(all_files)}):\n" + "\n".join(all_files)
        except Exception as e:
            return f"Error listing workspace: {str(e)}"

    @mcp.tool()
    def open_in_finder(path: str = "") -> str:
        """
        Open a file or folder in macOS Finder.
        If path is empty, opens the workspace folder.
        Use this when the user says 'show me in Finder', 'open the folder', 'open my workspace'.
        """
        try:
            if not path:
                path = _workspace_dir()
            else:
                path = str(resolve_user_path(path))

            if not os.path.exists(path):
                return f"Path does not exist: {path}"

            result = subprocess.run(["open", path], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                return f"Opened in Finder: {path}"
            return f"Could not open in Finder: {result.stderr.strip()}"
        except Exception as e:
            return f"Error opening Finder: {str(e)}"

    @mcp.tool()
    def append_to_file(file_path: str, content: str) -> str:
        """
        Append text to the end of an existing file. Creates the file if it doesn't exist.
        Use this to add to a log, journal, notes file, or any document the user wants to extend.
        """
        try:
            resolved_path = resolve_user_path(file_path)
            resolved_path.parent.mkdir(parents=True, exist_ok=True)
            with open(resolved_path, "a", encoding="utf-8") as f:
                f.write(content)
            return f"Appended {len(content)} characters to {resolved_path}"
        except Exception as e:
            return f"Error appending to file: {str(e)}"

    @mcp.tool()
    def delete_workspace_file(filename: str) -> str:
        """
        Delete a file from the workspace folder by name.
        Use this when the user says 'delete this file', 'remove X from workspace', 'clean up X'.
        """
        try:
            file_path = workspace_path(filename)
            if not os.path.exists(file_path):
                return f"File not found in workspace: {filename}"
            os.remove(file_path)
            return f"Deleted '{filename}' from workspace."
        except Exception as e:
            return f"Error deleting file: {str(e)}"
