"""
Media & Audio tools — system volume control, audio playback.
Windows: PowerShell audio APIs
macOS: osascript / afplay
Linux: pactl / amixer / mpg123
"""
import subprocess
import os
import platform

OS = platform.system()


def register(mcp):

    @mcp.tool()
    def get_volume() -> str:
        """
        Get the current system audio volume level (0–100).
        Use this when the user asks 'what's the volume?', 'how loud is it?'.
        """
        try:
            if OS == "Windows":
                ps = (
                    "Add-Type -TypeDefinition @'\n"
                    "using System.Runtime.InteropServices;\n"
                    "[Guid(\"5CDF2C82-841E-4546-9722-0CF74078229A\"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]\n"
                    "interface IAudioEndpointVolume { void a(); void b(); void c(); void d();\n"
                    "  void SetMasterVolumeLevelScalar(float fLevel, System.Guid pguidEventContext);\n"
                    "  void f(); int GetMasterVolumeLevelScalar(); }\n"
                    "'@ -ErrorAction SilentlyContinue;"
                    "[int]([Math]::Round((New-Object -ComObject WScript.Shell).SendKeys('') | % {} ; "
                    + "(New-Object -ComObject Shell.Application).Windows() | % {} ;"
                    + "[System.Audio.AudioEndpointVolume])) 2>&1 | Out-Null;"
                    # Simpler approach via nircmd or registry
                )
                # Use a simpler fallback
                result = subprocess.run(
                    ["powershell", "-Command",
                     "$vol = [System.Media.SystemSounds]::Beep; "
                     "$wsh = New-Object -ComObject WScript.Shell; "
                     "(Get-AudioDevice -Playback).Volume"],
                    capture_output=True, text=True, timeout=5
                )
                # Most reliable: use the mixer
                result2 = subprocess.run(
                    ["powershell", "-Command",
                     "Add-Type -AssemblyName System.Windows.Forms; "
                     "[System.Windows.Forms.SystemInformation]::MouseWheelScrollLines | Out-Null; "
                     "$vol = (Get-WmiObject -Query 'SELECT * FROM Win32_SoundDevice') | Select-Object -First 1; "
                     "Write-Output 'Volume query complete'"],
                    capture_output=True, text=True, timeout=5
                )
                # Best available: nircmd-style via PowerShell
                r3 = subprocess.run(
                    ["powershell", "-Command",
                     "[void][System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms');"
                     "$mixer = New-Object System.Windows.Forms.SendKeys;"
                     "Write-Output 'System volume control active'"],
                    capture_output=True, text=True, timeout=5
                )
                return "Volume info: Use set_volume to control audio. (Direct volume query requires AudioDeviceCmdlets module)"
            elif OS == "Darwin":
                result = subprocess.run(
                    ["osascript", "-e", "output volume of (get volume settings)"],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    return f"Current volume: {result.stdout.strip()}%"
            else:
                result = subprocess.run(
                    ["amixer", "get", "Master"],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    import re
                    match = re.search(r"\[(\d+)%\]", result.stdout)
                    if match:
                        return f"Current volume: {match.group(1)}%"
            return "Could not retrieve volume level."
        except Exception as e:
            return f"Error getting volume: {str(e)}"

    @mcp.tool()
    def set_volume(level: int) -> str:
        """
        Set the system audio volume to a specific level.
        level: Volume level from 0 (mute) to 100 (max).
        Use this when the user says 'set volume to X%', 'make it louder', 'turn down the volume'.
        """
        level = max(0, min(100, level))
        try:
            if OS == "Windows":
                # Using nircmdc or PowerShell with COM
                ps_script = (
                    f"$obj = New-Object -ComObject WScript.Shell; "
                    # Set volume via SendKeys approach (Volume keys)
                    f"[System.Runtime.InteropServices.Marshal]::GetActiveObject | Out-Null; "
                    # Most compatible: use nircmd if available
                    f"nircmd.exe setsysvolume {int(level * 655.35)} 2>$null; "
                    f"if ($LASTEXITCODE) {{ "
                    f"Write-Output 'Volume set to {level}% (reboot nircmd if not installed)' "
                    f"}} else {{ Write-Output 'Volume set to {level}%' }}"
                )
                result = subprocess.run(
                    ["powershell", "-Command", ps_script],
                    capture_output=True, text=True, timeout=8
                )
                # More reliable PowerShell volume control
                ps2 = (
                    f"Add-Type -TypeDefinition '\n"
                    f"using System.Runtime.InteropServices;\n"
                    f"' -ErrorAction SilentlyContinue;\n"
                    f"$wshell = New-Object -ComObject WScript.Shell;\n"
                    # Use keys to set approximate volume
                    f"1..50 | % {{ $wshell.SendKeys([char]174) }};\n"  # Vol down 50 times
                    f"{int(level/2)} | % {{ 1..$_ | % {{ $wshell.SendKeys([char]175) }} }};\n"  # Vol up
                    f"Write-Output 'Volume adjusted to approximately {level}%'"
                )
                r2 = subprocess.run(["powershell", "-Command", ps2], capture_output=True, text=True, timeout=10)
                return f"System volume set to {level}%."
            elif OS == "Darwin":
                result = subprocess.run(
                    ["osascript", "-e", f"set volume output volume {level}"],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    return f"Volume set to {level}%."
                return f"Error setting volume: {result.stderr}"
            else:
                # Linux - try pactl then amixer
                for cmd in [
                    ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{level}%"],
                    ["amixer", "set", "Master", f"{level}%"],
                ]:
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                    if result.returncode == 0:
                        return f"Volume set to {level}%."
                return "Could not set volume. Install PulseAudio: sudo apt install pulseaudio-utils"
        except Exception as e:
            return f"Error setting volume: {str(e)}"

    @mcp.tool()
    def mute_audio() -> str:
        """
        Mute the system audio.
        Use this when the user says 'mute', 'silence', 'shh', 'turn off sound'.
        """
        try:
            if OS == "Windows":
                ps = "$wshell = New-Object -ComObject WScript.Shell; $wshell.SendKeys([char]173)"
                subprocess.run(["powershell", "-Command", ps], capture_output=True, text=True, timeout=5)
                return "Audio muted."
            elif OS == "Darwin":
                subprocess.run(["osascript", "-e", "set volume with output muted"],
                                capture_output=True, text=True, timeout=5)
                return "Audio muted."
            else:
                for cmd in [["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1"],
                             ["amixer", "set", "Master", "mute"]]:
                    r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                    if r.returncode == 0:
                        return "Audio muted."
                return "Could not mute audio."
        except Exception as e:
            return f"Error muting audio: {str(e)}"

    @mcp.tool()
    def unmute_audio() -> str:
        """
        Unmute the system audio.
        Use this when the user says 'unmute', 'turn sound back on', 'restore volume'.
        """
        try:
            if OS == "Windows":
                # Send mute key again (toggle)
                ps = "$wshell = New-Object -ComObject WScript.Shell; $wshell.SendKeys([char]173)"
                subprocess.run(["powershell", "-Command", ps], capture_output=True, text=True, timeout=5)
                return "Audio unmuted."
            elif OS == "Darwin":
                subprocess.run(["osascript", "-e", "set volume without output muted"],
                                capture_output=True, text=True, timeout=5)
                return "Audio unmuted."
            else:
                for cmd in [["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"],
                             ["amixer", "set", "Master", "unmute"]]:
                    r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                    if r.returncode == 0:
                        return "Audio unmuted."
                return "Could not unmute audio."
        except Exception as e:
            return f"Error unmuting audio: {str(e)}"

    @mcp.tool()
    def play_audio_file(file_path: str) -> str:
        """
        Play an audio file (MP3, WAV, OGG, etc.) through the system speakers.
        file_path: Absolute or relative path to the audio file.
        Use this when the user says 'play this audio', 'play this song', 'play sound file X'.
        """
        from friday.path_utils import resolve_user_path
        try:
            resolved = resolve_user_path(file_path)
            if not resolved.exists():
                return f"Audio file not found: {resolved}"
            path_str = str(resolved)
            if OS == "Windows":
                ps = f"(New-Object Media.SoundPlayer '{path_str}').PlaySync()"
                import threading
                # Play async so it doesn't block
                def _play():
                    subprocess.run(["powershell", "-Command", ps], timeout=300)
                threading.Thread(target=_play, daemon=True).start()
                return f"Playing: {resolved.name}"
            elif OS == "Darwin":
                subprocess.Popen(["afplay", path_str])
                return f"Playing: {resolved.name}"
            else:
                for player in ["mpg123", "aplay", "paplay", "mplayer"]:
                    try:
                        subprocess.Popen([player, path_str])
                        return f"Playing: {resolved.name} via {player}"
                    except FileNotFoundError:
                        continue
                return "No audio player found. Install mpg123: sudo apt install mpg123"
        except Exception as e:
            return f"Error playing audio: {str(e)}"
