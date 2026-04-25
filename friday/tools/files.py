"""
Advanced file tools — download files, read PDFs, create documents,
open in Finder, and manage the workspace directory.
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from friday.path_utils import (
    known_user_paths,
    resolve_user_path,
    safe_filename,
    workspace_dir,
    workspace_path,
)


def _workspace_dir() -> str:
    return str(workspace_dir())


def _normalize_search_name(name: str) -> str:
    return name.strip().lower()


def _depth_from_root(root: str, current: str) -> int:
    root_depth = root.rstrip(os.sep).count(os.sep)
    current_depth = current.rstrip(os.sep).count(os.sep)
    return max(0, current_depth - root_depth)


def _iter_search_roots(roots: str) -> list[Path]:
    requested = [part.strip() for part in roots.split(",") if part.strip()]
    if not requested:
        requested = ["desktop", "documents", "downloads", "workspace", "home"]

    known = known_user_paths()
    resolved: list[Path] = []
    seen: set[str] = set()
    for item in requested:
        candidate = known.get(item.lower())
        if candidate is None:
            candidate = resolve_user_path(item)

        try:
            resolved_path = candidate.resolve()
        except Exception:
            continue

        cache_key = str(resolved_path).lower()
        if cache_key in seen or not resolved_path.exists():
            continue

        seen.add(cache_key)
        resolved.append(resolved_path)
    return resolved


def _should_skip_search_dir(name: str) -> bool:
    lowered = name.strip().lower()
    return lowered.startswith(".") or lowered in {
        "__pycache__",
        ".git",
        ".venv",
        "node_modules",
        "appdata",
        "programdata",
        "$recycle.bin",
        "system volume information",
        ".idea",
        ".vscode",
    }


def _open_path_default(path: str) -> str:
    if not path:
        path = _workspace_dir()
    else:
        path = str(resolve_user_path(path))

    if not os.path.exists(path):
        return f"Path does not exist: {path}"

    if os.name == "nt":
        os.startfile(path)
        return f"Opened path: {path}"
    if sys.platform == "darwin":
        result = subprocess.run(["open", path], capture_output=True, text=True, timeout=10)
    else:
        result = subprocess.run(["xdg-open", path], capture_output=True, text=True, timeout=10)

    if result.returncode == 0:
        return f"Opened path: {path}"
    return f"Could not open path: {result.stderr.strip()}"


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
    def create_folder(folder_path: str) -> str:
        """
        Create a folder at any path. Relative paths default to the workspace, and
        special roots like Desktop/Documents/Downloads are supported.
        Examples: 'reports', 'Desktop/demo', 'Documents/Notes/Archive'.
        """
        try:
            resolved_path = resolve_user_path(folder_path)
            resolved_path.mkdir(parents=True, exist_ok=True)
            return f"Folder ready: {resolved_path}"
        except Exception as e:
            return f"Error creating folder: {str(e)}"

    @mcp.tool()
    def get_special_paths() -> str:
        """
        Return the important user folders that FRIDAY can target directly.
        Use this before desktop/documents/downloads tasks when the exact path matters.
        """
        try:
            return "\n".join(f"{name}: {path}" for name, path in known_user_paths().items())
        except Exception as e:
            return f"Error getting special paths: {str(e)}"

    @mcp.tool()
    def search_paths_by_name(
        name: str,
        roots: str = "desktop,documents,downloads,workspace,home",
        max_results: int = 20,
        max_depth: int = 8,
        exact: bool = False,
        directories_only: bool = True,
    ) -> str:
        """
        Search common user folders for a file or folder by name.
        Use this when the user mentions a project/folder/file name but not the full path.
        roots supports built-in names like desktop, documents, downloads, workspace, and home.
        """
        try:
            target = _normalize_search_name(name)
            if not target:
                return "Provide a file or folder name to search for."

            search_roots = _iter_search_roots(roots)
            if not search_roots:
                return "No valid search roots were available."

            result_limit = max(1, min(int(max_results), 100))
            depth_limit = max(1, min(int(max_depth), 20))
            matches: list[str] = []

            for root in search_roots:
                for current_root, dirs, files in os.walk(root):
                    dirs[:] = [d for d in dirs if not _should_skip_search_dir(d)]
                    if _depth_from_root(str(root), current_root) >= depth_limit:
                        dirs[:] = []

                    candidate_names = dirs if directories_only else dirs + files
                    for candidate_name in candidate_names:
                        candidate_lower = candidate_name.lower()
                        matched = candidate_lower == target if exact else target in candidate_lower
                        if not matched:
                            continue

                        full_path = str(Path(current_root) / candidate_name)
                        matches.append(full_path)
                        if len(matches) >= result_limit:
                            break

                    if len(matches) >= result_limit:
                        break
                if len(matches) >= result_limit:
                    break

            searched = ", ".join(str(path) for path in search_roots)
            if not matches:
                noun = "folders" if directories_only else "paths"
                mode = "exactly named" if exact else "matching"
                return (
                    f"No {noun} {mode} '{name.strip()}' were found.\n"
                    f"Searched roots: {searched}\n"
                    f"Max depth: {depth_limit}"
                )

            label = "folder" if directories_only else "path"
            suffix = "s" if len(matches) != 1 else ""
            return (
                f"Found {len(matches)} matching {label}{suffix} for '{name.strip()}':\n"
                + "\n".join(f"- {match}" for match in matches)
            )
        except Exception as e:
            return f"Error searching paths: {str(e)}"

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
    def open_path(path: str = "") -> str:
        """
        Open any file or folder using the system default app.
        If path is empty, opens the workspace folder.
        Use this when the user says 'open this file', 'open this folder', or
        wants a document/site folder launched directly.
        """
        try:
            return _open_path_default(path)
        except Exception as e:
            return f"Error opening path: {str(e)}"

    @mcp.tool()
    def open_in_finder(path: str = "") -> str:
        """
        Open a file or folder in the system file manager.
        If path is empty, opens the workspace folder.
        Use this when the user says 'show me the folder', 'open Desktop', 'open my workspace'.
        """
        try:
            result = _open_path_default(path)
            if result.startswith("Opened path:"):
                return result.replace("Opened path:", "Opened folder view:", 1)
            return result
        except Exception as e:
            return f"Error opening path: {str(e)}"

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
    def copy_path(source_path: str, destination_path: str, overwrite: bool = False) -> str:
        """
        Copy a file or folder to another location on the machine.
        Relative paths default to the workspace, while absolute and special roots
        like Desktop/Documents/Downloads are also supported.
        """
        try:
            source = resolve_user_path(source_path)
            destination = resolve_user_path(destination_path)

            if not source.exists():
                return f"Source path does not exist: {source}"
            if destination.exists() and not overwrite:
                return f"Destination already exists: {destination}. Set overwrite=true to replace it."

            if destination.exists():
                if destination.is_dir():
                    shutil.rmtree(destination)
                else:
                    destination.unlink()

            destination.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, destination)
                return f"Copied folder to {destination}"

            shutil.copy2(source, destination)
            return f"Copied file to {destination}"
        except Exception as e:
            return f"Error copying path: {str(e)}"

    @mcp.tool()
    def move_path(source_path: str, destination_path: str, overwrite: bool = False) -> str:
        """
        Move or rename a file or folder anywhere the host user account can access.
        Relative paths default to the workspace; absolute and special roots are supported.
        """
        try:
            source = resolve_user_path(source_path)
            destination = resolve_user_path(destination_path)

            if not source.exists():
                return f"Source path does not exist: {source}"
            if destination.exists() and not overwrite:
                return f"Destination already exists: {destination}. Set overwrite=true to replace it."

            if destination.exists():
                if destination.is_dir():
                    shutil.rmtree(destination)
                else:
                    destination.unlink()

            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
            return f"Moved path to {destination}"
        except Exception as e:
            return f"Error moving path: {str(e)}"

    @mcp.tool()
    def delete_path(path: str, recursive: bool = False) -> str:
        """
        Delete a file or folder anywhere the host user account can access.
        Set recursive=true when deleting a non-empty folder.
        """
        try:
            target = resolve_user_path(path)
            if not target.exists():
                return f"Path does not exist: {target}"

            if target.is_dir():
                if any(target.iterdir()) and not recursive:
                    return f"Folder is not empty: {target}. Set recursive=true to remove it."
                if recursive:
                    shutil.rmtree(target)
                else:
                    target.rmdir()
                return f"Deleted folder: {target}"

            target.unlink()
            return f"Deleted file: {target}"
        except Exception as e:
            return f"Error deleting path: {str(e)}"

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
