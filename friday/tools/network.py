"""
Network tools — ping, IP info, port check, network diagnostics.
Uses only stdlib + httpx (already in dependencies) — no extra packages needed.
"""
import subprocess
import socket
import platform

from friday.subprocess_utils import run_powershell

OS = platform.system()


def register(mcp):

    @mcp.tool()
    def ping_host(host: str, count: int = 4) -> str:
        """
        Ping a host to check if it's reachable and measure latency.
        host: Hostname or IP address (e.g. 'google.com', '8.8.8.8').
        count: Number of ping packets to send (default 4).
        Use this when the user asks 'ping X', 'is X reachable?', 'check connectivity to X'.
        """
        count = min(max(1, count), 20)
        try:
            if OS == "Windows":
                cmd = ["ping", "-n", str(count), host]
            else:
                cmd = ["ping", "-c", str(count), host]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            output = result.stdout.strip() or result.stderr.strip()
            if len(output) > 2000:
                output = output[:2000] + "\n... [truncated]"
            return output if output else f"No response from {host}."
        except subprocess.TimeoutExpired:
            return f"Ping to '{host}' timed out."
        except Exception as e:
            return f"Error pinging host: {str(e)}"

    @mcp.tool()
    async def get_public_ip() -> str:
        """
        Get the public (external) IP address of this machine.
        Use this when the user asks 'what's my IP?', 'what's my public IP?', 'what IP am I on?'.
        """
        import httpx
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                # Try multiple services for reliability
                for url in [
                    "https://api.ipify.org?format=json",
                    "https://ipinfo.io/json",
                    "https://ifconfig.me/all.json",
                ]:
                    try:
                        r = await client.get(url)
                        if r.status_code == 200:
                            data = r.json()
                            ip = data.get("ip") or data.get("IP_ADDR") or "Unknown"
                            city = data.get("city", "")
                            region = data.get("region", "")
                            country = data.get("country", "")
                            org = data.get("org", "")
                            loc_str = ", ".join(filter(None, [city, region, country]))
                            result = f"Public IP: {ip}"
                            if loc_str:
                                result += f"\nLocation : {loc_str}"
                            if org:
                                result += f"\nISP/Org  : {org}"
                            return result
                    except Exception:
                        continue
            return "Could not determine public IP address."
        except Exception as e:
            return f"Error getting public IP: {str(e)}"

    @mcp.tool()
    def get_local_network_info() -> str:
        """
        Get local network information: hostname, local IP, default gateway.
        Use this when the user asks 'what's my local IP?', 'show network info', 'what's my hostname?'.
        """
        try:
            hostname = socket.gethostname()
            try:
                local_ip = socket.gethostbyname(hostname)
            except Exception:
                local_ip = "Unknown"
            lines = [
                f"Hostname  : {hostname}",
                f"Local IP  : {local_ip}",
                f"OS        : {OS}",
            ]

            # Try to get more detailed network info
            if OS == "Windows":
                result = run_powershell(
                    "Get-NetIPAddress -AddressFamily IPv4 | Select-Object IPAddress,InterfaceAlias | Format-Table -AutoSize | Out-String",
                    timeout=10,
                )
                if result.returncode == 0:
                    lines.append("\nNetwork Interfaces (IPv4):")
                    lines.append(result.stdout.strip())
                # Default gateway
                try:
                    gw_result = run_powershell(
                        "(Get-NetRoute -DestinationPrefix '0.0.0.0/0' | Select-Object -First 1).NextHop",
                        timeout=10,
                    )
                    if gw_result.returncode == 0 and gw_result.stdout.strip():
                        lines.append(f"Default GW: {gw_result.stdout.strip()}")
                except subprocess.TimeoutExpired:
                    lines.append("Default GW: lookup timed out")
            elif OS == "Darwin":
                result = subprocess.run(["ifconfig", "-a"], capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    lines.append("\nInterfaces:\n" + result.stdout[:1500])
            else:
                result = subprocess.run(["ip", "addr", "show"], capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    lines.append("\nInterfaces:\n" + result.stdout[:1500])

            return "\n".join(lines)
        except Exception as e:
            return f"Error getting network info: {str(e)}"

    @mcp.tool()
    def check_port(host: str, port: int, timeout: int = 5) -> str:
        """
        Check if a specific TCP port is open on a host.
        host: Hostname or IP address.
        port: Port number (e.g. 80 for HTTP, 443 for HTTPS, 22 for SSH, 3306 for MySQL).
        Use this when the user asks 'is port X open on Y?', 'check if server is running on port X'.
        """
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return f"Port {port} on {host} is OPEN."
        except socket.timeout:
            return f"Port {port} on {host} is CLOSED or FILTERED (connection timed out)."
        except ConnectionRefusedError:
            return f"Port {port} on {host} is CLOSED (connection refused)."
        except socket.gaierror:
            return f"Could not resolve hostname '{host}'."
        except Exception as e:
            return f"Error checking port: {str(e)}"

    @mcp.tool()
    def dns_lookup(hostname: str) -> str:
        """
        Perform a DNS lookup to resolve a hostname to its IP addresses.
        Use this when the user asks 'what IP is X?', 'resolve DNS for X', 'lookup X'.
        """
        try:
            results = socket.getaddrinfo(hostname, None)
            ips = list({r[4][0] for r in results})
            if not ips:
                return f"No DNS results for '{hostname}'."
            return f"DNS Lookup for '{hostname}':\n" + "\n".join(f"  {ip}" for ip in ips)
        except socket.gaierror:
            return f"DNS resolution failed for '{hostname}'. Check the hostname."
        except Exception as e:
            return f"Error performing DNS lookup: {str(e)}"

    @mcp.tool()
    async def traceroute(host: str) -> str:
        """
        Run a traceroute to a host to show the network path and hop latencies.
        Use this when the user asks 'trace route to X', 'show network path to X'.
        """
        try:
            if OS == "Windows":
                cmd = ["tracert", "-d", "-h", "20", host]
            else:
                cmd = ["traceroute", "-n", "-m", "20", host]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            output = result.stdout.strip() or result.stderr.strip()
            if len(output) > 3000:
                output = output[:3000] + "\n... [truncated]"
            return output if output else f"Traceroute to {host} returned no output."
        except subprocess.TimeoutExpired:
            return f"Traceroute to '{host}' timed out."
        except Exception as e:
            return f"Error running traceroute: {str(e)}"
