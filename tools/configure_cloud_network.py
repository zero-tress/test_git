"""Configuration maintenance only: install the user-authorized cloud_wj network switch."""

import shutil
import time
from pathlib import Path

target = Path("/home/wj/.local/share/codex-cloud-mcp/server.py")
text = target.read_text(encoding="utf-8")
if "'network_enabled':" in text or "network_enabled = args.get" in text:
    raise SystemExit("Network switch already installed; inspect before changing again.")
changes = [
    (
        "    cmd = ['/usr/bin/bwrap', '--unshare-all', '--die-with-parent', '--new-session',",
        """    network_enabled = args.get('network', False)
    if not isinstance(network_enabled, bool):
        raise ValueError('network must be a boolean')
    cmd = ['/usr/bin/bwrap', '--unshare-all', '--die-with-parent', '--new-session',""",
    ),
    (
        "           '--cap-drop', 'ALL', '--clearenv']",
        """           '--cap-drop', 'ALL', '--clearenv']
    if network_enabled:
        cmd += ['--share-net']""",
    ),
    (
        "    cmd += ['--ro-bind', str(CONDA), str(CONDA), '--bind', str(ROOT), str(ROOT),",
        """    # Runtime libraries use these two alternatives symlinks. Bind only their
    # resolved library files; do not expose all of /etc/alternatives.
    for filename in ['/etc/alternatives/libblas.so.3-x86_64-linux-gnu',
                     '/etc/alternatives/liblapack.so.3-x86_64-linux-gnu']:
        source = Path(filename)
        if source.exists():
            resolved = source.resolve()
            if not (resolved.is_relative_to('/usr/lib') or resolved.is_relative_to('/lib')):
                raise ValueError('Unexpected library alternative target')
            cmd += ['--ro-bind', str(resolved), filename]
    if network_enabled:
        for filename in ['/etc/resolv.conf', '/etc/hosts', '/etc/nsswitch.conf']:
            if Path(filename).exists():
                cmd += ['--ro-bind', filename, filename]
    cmd += ['--ro-bind', str(CONDA), str(CONDA), '--bind', str(ROOT), str(ROOT),""",
    ),
    (
        "    return dict(exit_code=process.returncode, timed_out=timed_out,",
        "    return dict(exit_code=process.returncode, timed_out=timed_out, network_enabled=network_enabled,",
    ),
    (
        "                    network=False, gpu=False, memory_gib=4, cpu_cores=1,",
        """                    network=False, network_switch='run(network=true) enables host networking including loopback and DNS',
                    network_default=False, gpu=False, memory_gib=4, cpu_cores=1,""",
    ),
    (
        "Only the dedicated workspace is writable. No network, host processes, GPU, sudo, Docker or home secrets.",
        "Only the dedicated workspace is writable. Network is off by default; network=true enables host networking after user authorization. No host processes, GPU, sudo, Docker or home secrets.",
    ),
    (
        "          'cwd': dict(type='string', default='.'), 'timeout_seconds': dict(type='integer', minimum=1, maximum=120)}, ['argv'])",
        """          'cwd': dict(type='string', default='.'),
          'network': dict(type='boolean', default=False, description='Enable host networking, including localhost services and DNS. Use only with user authorization.'),
          'timeout_seconds': dict(type='integer', minimum=1, maximum=120)}, ['argv'])""",
    ),
    ("serverInfo=dict(name='cloud-wj', version='1.0.0')", "serverInfo=dict(name='cloud-wj', version='1.1.0')"),
    (
        "Sandbox has no network or GPU; report limits instead of bypassing them.",
        "Network is disabled by default; use run(network=true) only with user authorization. GPU is not exposed. Report other limits instead of bypassing them.",
    ),
    ("openWorldHint=False))", "openWorldHint=(name == 'run')))"),
]
for old, new in changes:
    if old not in text:
        raise ValueError("Configuration anchor not found: " + old[:100])
    text = text.replace(old, new)
compile(text, str(target), "exec")
backup = target.with_name("server.py.before-network-" + time.strftime("%Y%m%d-%H%M%S"))
shutil.copy2(target, backup)
staged = target.with_name("server.py.network-staged")
staged.write_text(text, encoding="utf-8")
staged.chmod(target.stat().st_mode)
staged.replace(target)
print("Updated:", target)
print("Backup:", backup)
print("Network default remains OFF. Existing services were not restarted.")
