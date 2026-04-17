"""
Compression tools — zip, unzip, and inspect archives.
Uses Python's built-in zipfile and tarfile — no dependencies required.
"""
import os
import zipfile
import tarfile
import time
from pathlib import Path

from friday.path_utils import resolve_user_path, workspace_dir, workspace_path


def register(mcp):

    @mcp.tool()
    def zip_files(paths: str, output_name: str = "") -> str:
        """
        Compress one or more files or folders into a zip archive, saved in the workspace.
        paths: Comma-separated list of file or folder paths to include.
        output_name: Name of the output zip file (auto-generated if not provided).
        Use this when the user says 'zip this', 'compress this', 'archive these files'.
        """
        try:
            path_list = [p.strip() for p in paths.split(",") if p.strip()]
            if not path_list:
                return "No paths provided to zip."

            if not output_name:
                output_name = f"archive_{time.strftime('%Y%m%d_%H%M%S')}.zip"
            if not output_name.endswith(".zip"):
                output_name += ".zip"

            save_path = workspace_dir() / output_name
            total_files = 0

            with zipfile.ZipFile(save_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for raw_path in path_list:
                    resolved = resolve_user_path(raw_path)
                    if not resolved.exists():
                        return f"Path not found: {resolved}"
                    if resolved.is_file():
                        zf.write(resolved, resolved.name)
                        total_files += 1
                    elif resolved.is_dir():
                        for file in resolved.rglob("*"):
                            if file.is_file():
                                zf.write(file, file.relative_to(resolved.parent))
                                total_files += 1

            size_kb = save_path.stat().st_size / 1024
            return f"Zipped {total_files} file(s) → {save_path} ({size_kb:.1f} KB)"
        except Exception as e:
            return f"Error zipping files: {str(e)}"

    @mcp.tool()
    def unzip_file(archive_path: str, destination: str = "") -> str:
        """
        Extract a zip or tar archive to a destination folder.
        archive_path: Path to the .zip, .tar.gz, or .tar file.
        destination: Folder to extract into (defaults to workspace folder with archive name).
        Use this when the user says 'unzip', 'extract', 'decompress this file'.
        """
        try:
            archive = resolve_user_path(archive_path)
            if not archive.exists():
                return f"Archive not found: {archive}"

            if not destination:
                dest_name = archive.stem
                if dest_name.endswith(".tar"):
                    dest_name = Path(dest_name).stem
                destination = str(workspace_dir() / dest_name)

            dest_path = Path(destination)
            dest_path.mkdir(parents=True, exist_ok=True)
            fname = archive.name.lower()

            if fname.endswith(".zip"):
                with zipfile.ZipFile(archive, "r") as zf:
                    zf.extractall(dest_path)
                    count = len(zf.namelist())
            elif fname.endswith((".tar.gz", ".tgz", ".tar.bz2", ".tar")):
                with tarfile.open(archive, "r:*") as tf:
                    tf.extractall(dest_path)
                    count = len(tf.getnames())
            else:
                return f"Unsupported archive format: {archive.suffix}. Supported: .zip, .tar.gz, .tar, .tgz"

            return f"Extracted {count} item(s) → {dest_path}"
        except Exception as e:
            return f"Error extracting archive: {str(e)}"

    @mcp.tool()
    def list_zip_contents(archive_path: str) -> str:
        """
        List the files inside a zip or tar archive without extracting it.
        Use this when the user asks 'what's in this zip?', 'show archive contents'.
        """
        try:
            archive = resolve_user_path(archive_path)
            if not archive.exists():
                return f"Archive not found: {archive}"

            fname = archive.name.lower()
            items = []

            if fname.endswith(".zip"):
                with zipfile.ZipFile(archive, "r") as zf:
                    for info in zf.infolist():
                        size_str = f"{info.file_size / 1024:.1f} KB" if info.file_size > 1024 else f"{info.file_size} B"
                        items.append(f"  {info.filename}  ({size_str})")
            elif fname.endswith((".tar.gz", ".tgz", ".tar.bz2", ".tar")):
                with tarfile.open(archive, "r:*") as tf:
                    for member in tf.getmembers():
                        size_str = f"{member.size / 1024:.1f} KB" if member.size > 1024 else f"{member.size} B"
                        items.append(f"  {member.name}  ({size_str})")
            else:
                return f"Unsupported archive format: {archive.suffix}"

            if not items:
                return "Archive is empty."
            return f"Archive: {archive}\nContents ({len(items)} items):\n" + "\n".join(items[:100])
        except Exception as e:
            return f"Error reading archive: {str(e)}"
