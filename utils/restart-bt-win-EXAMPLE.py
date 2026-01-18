# restart_usb_device.py
import ctypes
import subprocess
import tempfile
import os
import sys
import time

DEVICE_NAME = "TP-Link Bluetooth 5.4 USB Adapter" # вписать имя bluetooth-адаптера из Диспетчера устройств

def is_admin():
    """Check admin priviledges (Windows)."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False

def rescan_with_pnputil():
    if not is_admin():
        print("Admin rights is needed.")
        sys.exit(1)
    subprocess.run(["pnputil", "/scan-devices"], check=True)
    print("pnputil: /scan-devices completed.")

def restart_device_by_friendly_name(friendly_name: str, wait_seconds: int = 60, verbose: bool = True) -> int:
    """
    Restart device (Disable -> Enable) by FriendlyName with PowerShell.
    Returned code: 0 — success, >0 — error.
    """
    if not is_admin():
        raise PermissionError("Admin rights is needed.")

    # PowerShell: search by FriendlyName, do Disable, wait, then Enable.
    ps_script = f"""
$name = '{friendly_name}'
$dev = Get-PnpDevice -FriendlyName $name -ErrorAction SilentlyContinue
if ($null -eq $dev) {{
    Write-Output 'DEVICE_NOT_FOUND'
    exit 3
}}

# Disable
$dev | ForEach-Object {{
    try {{
        Disable-PnpDevice -InstanceId $_.InstanceId -Confirm:$false -ErrorAction Stop
        Write-Output ('DISABLED:' + $_.InstanceId)
    }} catch {{
        Write-Output ('DISABLE_ERROR:' + $_.InstanceId + ' - ' + $_.Exception.Message)
        exit 4
    }}
}}

Start-Sleep -Seconds {wait_seconds}

# Enable
$dev | ForEach-Object {{
    try {{
        Enable-PnpDevice -InstanceId $_.InstanceId -Confirm:$false -ErrorAction Stop
        Write-Output ('ENABLED:' + $_.InstanceId)
    }} catch {{
        Write-Output ('ENABLE_ERROR:' + $_.InstanceId + ' - ' + $_.Exception.Message)
        exit 5
    }}
}}

Write-Output 'DONE'
exit 0
"""

    # Do temporary .ps1 file
    fd, path = tempfile.mkstemp(suffix=".ps1", text=True)
    os.close(fd)
    with open(path, "w", encoding="utf-8") as f:
        f.write(ps_script)

    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", path],
            capture_output=True, text=True
        )
        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()

        if verbose:
            if stdout:
                print("PowerShell stdout:")
                print(stdout)
            if stderr:
                print("PowerShell stderr:")
                print(stderr, file=sys.stderr)

        return proc.returncode
    finally:
        try:
            os.remove(path)
        except OSError:
            pass

if __name__ == "__main__":
    try:
        WAIT_SECONDS = 30
        print(f"Sended request to reconnect BT, waiting {WAIT_SECONDS}s...", file=sys.stderr)
        rc = restart_device_by_friendly_name(DEVICE_NAME, WAIT_SECONDS, verbose=True)
        rescan_with_pnputil()
        rc = restart_device_by_friendly_name(DEVICE_NAME, WAIT_SECONDS, verbose=True) # it works only with 2 retries
        time.sleep(15)
    except PermissionError as e:
        print("Error:", e, file=sys.stderr)
        print("Admin rights is needed.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print("Unexpectable error:", e, file=sys.stderr)
        sys.exit(2)

    if rc == 0:
        print("Device successfully restarted")
        sys.exit(0)
    elif rc == 3:
        print(f"Device named '{DEVICE_NAME}' not found. Check exact FriendlyName in Windows devices manager.", file=sys.stderr)
        sys.exit(3)
    else:
        print(f"PowerShell returned code {rc}. Check out.", file=sys.stderr)
        sys.exit(rc)
