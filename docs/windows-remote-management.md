# Windows node — remote management (PowerShell 7 + OpenSSH Server)

Make a Windows fleet node fully remotely manageable from the puller host
(proximal today). Everything below runs in **one elevated PowerShell session at
the console** — the last time you need physical/RDP access. After this, all
management is `ssh <node>` and the fleet's `gpu_cmd` probe path works.

This is the standalone runbook for step 2a of
[adding-a-windows-node.md](adding-a-windows-node.md).

## 1. PowerShell 7 (pwsh)

```powershell
winget install --id Microsoft.PowerShell --source winget
```

(No winget on the box? Grab the `PowerShell-7.x-win-x64.msi` from
github.com/PowerShell/PowerShell/releases and run it — that is the only
download-and-click step in this doc.)

## 2. OpenSSH Server

Built-in Windows optional capability — no third-party sshd:

```powershell
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
Set-Service -Name sshd -StartupType Automatic
Start-Service sshd

# The capability install creates firewall rule 'OpenSSH-Server-In-TCP'; verify:
Get-NetFirewallRule -Name '*OpenSSH-Server*' | Enable-NetFirewallRule
```

## 3. Default SSH shell → pwsh

Incoming SSH sessions land in cmd.exe by default; make it PowerShell 7:

```powershell
New-ItemProperty -Path 'HKLM:\SOFTWARE\OpenSSH' -Name DefaultShell `
  -Value 'C:\Program Files\PowerShell\7\pwsh.exe' -PropertyType String -Force
```

## 4. Key auth

Two traps here, both Windows-specific:

- For a user in the **Administrators group**, sshd reads
  `C:\ProgramData\ssh\administrators_authorized_keys` — **not** the per-user
  `~\.ssh\authorized_keys`. (This routing comes from the `Match Group
  administrators` block at the bottom of the default
  `C:\ProgramData\ssh\sshd_config`; leave it in place.)
- That file must have a **locked-down ACL** (Administrators + SYSTEM only) or
  sshd silently ignores it and you get a password prompt despite a valid key.

```powershell
Add-Content -Path C:\ProgramData\ssh\administrators_authorized_keys `
  -Value '<puller host pubkey line, e.g. contents of proximal ~/.ssh/id_ed25519.pub>'
icacls.exe C:\ProgramData\ssh\administrators_authorized_keys `
  /inheritance:r /grant 'Administrators:F' /grant 'SYSTEM:F'
```

For a non-admin account the usual `%USERPROFILE%\.ssh\authorized_keys` works
with no ACL surgery.

## 5. Harden — key-only login

Once key login is verified working (test first — this locks out passwords):

```powershell
# in C:\ProgramData\ssh\sshd_config:
#   PasswordAuthentication no
Restart-Service sshd
```

## 6. Keep it awake

A fleet node that sleeps takes its sshd and its GPU with it:

```powershell
powercfg /change standby-timeout-ac 0
```

## 7. Verify from the puller host

```bash
ssh <node> '$PSVersionTable.PSVersion'          # lands in pwsh 7, key auth, no password
ssh -o BatchMode=yes <node> nvidia-smi          # the fleet acceptance test
```

The second command is exactly what the heartbeat driver runs as `gpu_cmd`
every 15 s tick. It must return with **no prompt of any kind** and comfortably
under the 10 s probe timeout (`GPU_TIMEOUT` in `heartbeat_all.py`), or the node
never goes live. `nvidia-smi` ships in `C:\Windows\System32` with modern
drivers, so it is on PATH for SSH sessions automatically.

## 8. pwsh-as-remote-shell gotchas

With pwsh as the default shell, remote commands are parsed by PowerShell, not
a POSIX sh (this is the "fragile peecee PowerShell path" RFC 0002 mentions):

- `2>/dev/null` fails — pwsh's null sink is `2>$null`.
- Quoting rules differ; single-quoted strings survive best.
- Keep any `gpu_cmd` a **bare command with no shell-isms**; the standard
  `ssh -o BatchMode=yes <node> nvidia-smi` is safe under either shell.

## 9. Troubleshooting

- **Key ignored, password prompt anyway** → it's the §4 ACL or the wrong file
  (admin user + per-user `authorized_keys`). Re-run the `icacls` line.
- **sshd logs** → Event Viewer, `Applications and Services Logs →
  OpenSSH → Operational`; or set `SyslogFacility LOCAL0` + `LogLevel DEBUG` in
  `sshd_config` to log to `C:\ProgramData\ssh\logs\sshd.log`, restart, retry.
- **Works interactively, fails in `BatchMode=yes`** → something is prompting
  (host-key change, passphrase-locked key without an agent). BatchMode fails
  closed on any prompt — which is what the fleet wants.

## Optional: Tailscale

For management off-LAN, install Tailscale on the node and use its tailnet name
in `~/.ssh/config` on the puller. The fleet itself only needs LAN reachability
from whichever Linux node holds the puller-lease.
