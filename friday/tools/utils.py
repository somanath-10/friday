"""
Utility tools — text processing, formatting, calculations, etc.
"""

import json
import subprocess
import tempfile
import os
import base64
import uuid
import glob
import fnmatch

BACKGROUND_TASKS = {}



def register(mcp):

    @mcp.tool()
    def format_json(data: str) -> str:
        """Pretty-print a JSON string."""
        try:
            parsed = json.loads(data)
            return json.dumps(parsed, indent=2)
        except json.JSONDecodeError as e:
            return f"Invalid JSON: {e}"

    @mcp.tool()
    def word_count(text: str) -> dict:
        """Count words, characters, and lines in a block of text."""
        lines = text.splitlines()
        words = text.split()
        return {
            "characters": len(text),
            "words": len(words),
            "lines": len(lines),
        }

    @mcp.tool()
    def execute_python_code(code: str) -> str:
        """Execute Python code and return the output."""
        try:
            # Create a temporary file to execute the code
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write(code)
                temp_file = f.name

            # Execute the code with a timeout
            result = subprocess.run(
                ['python3', temp_file],
                capture_output=True,
                text=True,
                timeout=10  # 10 second timeout
            )

            # Clean up the temporary file
            os.unlink(temp_file)

            # Return the result
            if result.returncode == 0:
                output = result.stdout.strip()
                if result.stderr:
                    output += f"\nWarnings: {result.stderr.strip()}"
                return output if output else "Code executed successfully with no output."
            else:
                return f"Error executing code:\n{result.stderr.strip()}"

        except subprocess.TimeoutExpired:
            return "Error: Code execution timed out (10 second limit)."
        except Exception as e:
            return f"Error executing code: {str(e)}"

    @mcp.tool()
    def get_file_contents(file_path: str) -> str:
        """Get the contents of a file."""
        try:
            with open(file_path, 'r') as f:
                return f.read()
        except FileNotFoundError:
            return f"File not found: {file_path}"
        except Exception as e:
            return f"Error reading file: {str(e)}"

    @mcp.tool()
    def write_file(file_path: str, content: str) -> str:
        """Write content to a file."""
        try:
            # Ensure directory exists
            directory = os.path.dirname(file_path)
            if directory and not os.path.exists(directory):
                os.makedirs(directory)

            with open(file_path, 'w') as f:
                f.write(content)
            return f"Successfully wrote to {file_path}"
        except Exception as e:
            return f"Error writing file: {str(e)}"

    @mcp.tool()
    def install_package(package_name: str) -> str:
        """Install a Python package using pip."""
        try:
            result = subprocess.run(
                ['pip', 'install', package_name],
                capture_output=True,
                text=True,
                timeout=30  # 30 second timeout for installation
            )

            if result.returncode == 0:
                return f"Successfully installed {package_name}"
            else:
                return f"Failed to install {package_name}: {result.stderr.strip()}"
        except subprocess.TimeoutExpired:
            return f"Error: Installation of {package_name} timed out (30 second limit)."
        except Exception as e:
            return f"Error installing package: {str(e)}"

    @mcp.tool()
    def run_shell_command(command: str) -> str:
        """Run a shell command and return the output."""
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=15  # 15 second timeout
            )

            if result.returncode == 0:
                output = result.stdout.strip()
                if result.stderr:
                    output += f"\nStderr: {result.stderr.strip()}"
                return output if output else "Command executed successfully with no output."
            else:
                return f"Command failed with exit code {result.returncode}:\n{result.stderr.strip()}"
        except subprocess.TimeoutExpired:
            return "Error: Command execution timed out (15 second limit)."
        except Exception as e:
            return f"Error running command: {str(e)}"

    @mcp.tool()
    def encode_base64(data: str) -> str:
        """Encode a string to base64."""
        try:
            encoded = base64.b64encode(data.encode('utf-8')).decode('utf-8')
            return encoded
        except Exception as e:
            return f"Error encoding to base64: {str(e)}"

    @mcp.tool()
    def decode_base64(data: str) -> str:
        """Decode a base64 string."""
        try:
            decoded = base64.b64decode(data).decode('utf-8')
            return decoded
        except Exception as e:
            return f"Error decoding from base64: {str(e)}"

    @mcp.tool()
    def start_background_process(command: str) -> str:
        """Start a long-running shell command in the background. Returns a task ID."""
        try:
            task_id = str(uuid.uuid4())
            # Run in shell, detach process as much as possible simply
            process = subprocess.Popen(
                command, 
                shell=True, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE,
                text=True
            )
            BACKGROUND_TASKS[task_id] = process
            return f"Task started in background with ID: {task_id}"
        except Exception as e:
            return f"Failed to start task: {str(e)}"

    @mcp.tool()
    def check_process_status(task_id: str) -> str:
        """Check the status of a background process by ID and fetch output if done."""
        if task_id not in BACKGROUND_TASKS:
            return f"No task found with ID: {task_id}"
        
        process = BACKGROUND_TASKS[task_id]
        retcode = process.poll()
        
        if retcode is None:
            return f"Task {task_id} is still running."
        
        stdout, stderr = process.communicate()
        BACKGROUND_TASKS.pop(task_id, None)
        
        return (f"Task {task_id} completed with code {retcode}.\n"
                f"STDOUT:\n{stdout}\n\nSTDERR:\n{stderr}")

    @mcp.tool()
    def read_file_snippet(file_path: str, start_line: int, end_line: int) -> str:
        """Read a specific range of lines from a file. (1-indexed)"""
        try:
            with open(file_path, 'r') as f:
                lines = f.readlines()
            
            if start_line < 1: start_line = 1
            if end_line > len(lines): end_line = len(lines)
            
            snippet = "".join(lines[start_line-1:end_line])
            return f"--- {file_path} (Lines {start_line}-{end_line}) ---\n{snippet}"
        except Exception as e:
            return f"Error reading snippet: {str(e)}"

    @mcp.tool()
    def list_directory_tree(path: str, max_depth: int = 2) -> str:
        """List the directory structure to a given max depth. Useful to understand project structure."""
        try:
            if not os.path.exists(path):
                return f"Path does not exist: {path}"
            
            tree_str = []
            start_depth = path.rstrip(os.path.sep).count(os.path.sep)
            
            for root, dirs, files in os.walk(path):
                # Standard exclusion of dot directories
                dirs[:] = [d for d in dirs if not d.startswith('.')]
                
                curr_depth = root.rstrip(os.path.sep).count(os.path.sep)
                depth = curr_depth - start_depth
                
                if depth > max_depth:
                    continue
                
                indent = '  ' * depth
                tree_str.append(f"{indent}{os.path.basename(root)}/")
                sub_indent = '  ' * (depth + 1)
                for f in files:
                    if not f.startswith('.'):
                        tree_str.append(f"{sub_indent}{f}")
            
            return "\n".join(tree_str)
        except Exception as e:
            return f"Error listing directory: {str(e)}"

    @mcp.tool()
    def search_in_files(directory: str, keyword: str) -> str:
        """Search for a keyword in files within a directory using basic text matching."""
        try:
            if not os.path.exists(directory):
                return f"Directory does not exist: {directory}"
                
            results = []
            for root, dirs, files in os.walk(directory):
                dirs[:] = [d for d in dirs if not d.startswith('.')]
                for file_name in files:
                    if file_name.startswith('.'):
                        continue
                    file_path = os.path.join(root, file_name)
                    # Simple text match, ignore binary files
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            for idx, line in enumerate(f):
                                if keyword in line:
                                    results.append(f"{file_path}:{idx+1}: {line.strip()}")
                                    if len(results) > 50:
                                        results.append("... [More results truncated] ...")
                                        return "\n".join(results)
                    except UnicodeDecodeError:
                        pass # Ignore binary files
            
            if not results:
                return f"Keyword '{keyword}' not found in {directory}."
            return "\n".join(results)
        except Exception as e:
            return f"Error searching files: {str(e)}"
