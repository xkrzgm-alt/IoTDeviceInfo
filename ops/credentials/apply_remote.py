"""Remote half of sync_aliyun.py. Receives secrets on stdin, never in argv."""
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path('/etc/vendera')
DROPINS = {
    'hwprogm.service': ('common', 'hwprogm'),
    'hwprogm-monitor.service': ('common', 'hwprogm'),
    'iot-backend.service': ('common', 'iotdeviceinfo'),
}
HEALTH = {
    'hwprogm.service': 'http://127.0.0.1:8000/login',
    'iot-backend.service': 'http://127.0.0.1:8080/health',
}


def run(*args):
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL)


def atomic(path, contents):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.pending-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            out.write(contents)
            out.flush()
            os.fsync(out.fileno())
        os.chmod(name, 0o600 if path.suffix == '.env' else 0o644)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def env_text(values):
    # Systemd EnvironmentFile double quotes: escape backslash and quote; no shell evaluation.
    for key, value in values.items():
        if not key.isidentifier() or not isinstance(value, str) or any(c in value for c in '\r\n\0'):
            raise ValueError('Invalid environment key or value')
    return ''.join(f'{key}="{value.replace(chr(92), chr(92)*2).replace(chr(34), chr(92)+chr(34))}"\n'
                   for key, value in sorted(values.items()))


def main():
    if os.geteuid() != 0:
        raise RuntimeError('Root privileges required')
    payload = json.load(sys.stdin)
    groups = payload['groups']
    if set(groups) != set(('common', 'iotdeviceinfo', 'hwprogm')):
        raise ValueError('Invalid groups')
    rendered = {group: env_text(values) for group, values in groups.items()}
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    ROOT.chmod(0o700)
    backup = ROOT / 'backups' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup.mkdir(mode=0o700, parents=True)
    originals = {}
    changed = set()
    try:
        for group, text in rendered.items():
            path = ROOT / (group + '.env')
            originals[path] = path.read_bytes() if path.exists() else None
            if originals[path] != text.encode() or (path.stat().st_mode & 0o777 if path.exists() else 0) != 0o600:
                if originals[path] is not None:
                    (backup / path.name).write_bytes(originals[path])
                    (backup / path.name).chmod(0o600)
                atomic(path, text)
                changed.add(group)
        for unit, dependencies in DROPINS.items():
            path = Path('/etc/systemd/system') / (unit + '.d') / '50-vendera-credentials.conf'
            text = '[Service]\n' + ''.join(f'EnvironmentFile={ROOT / (group + ".env")}\n' for group in dependencies)
            originals[path] = path.read_bytes() if path.exists() else None
            if originals[path] != text.encode():
                atomic(path, text)
                changed.update(dependencies)
        run('systemctl', 'daemon-reload')
        units = [unit for unit, dependencies in DROPINS.items() if changed.intersection(dependencies)]
        for unit in units:
            if unit == 'hwprogm-monitor.service':
                continue  # Next timer run picks up the new environment.
            run('systemctl', 'restart', unit)
            run('systemctl', 'is-active', '--quiet', unit)
            if unit in HEALTH:
                run('curl', '-fsS', '--retry', '10', '--retry-delay', '2', '--retry-connrefused',
                    '--max-time', '5', '-o', '/dev/null', HEALTH[unit])
        print('Updated groups: ' + (', '.join(sorted(changed)) if changed else 'none'))
        print('Rollback backup directory: ' + str(backup))
    except Exception:
        for path, content in originals.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                atomic(path, content.decode('utf-8'))
        run('systemctl', 'daemon-reload')
        for unit in ('iot-backend.service', 'hwprogm.service'):
            try:
                run('systemctl', 'restart', unit)
            except subprocess.CalledProcessError:
                pass
        raise


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'Credential sync failed ({type(exc).__name__}); rollback attempted. Check systemd status.', file=sys.stderr)
        sys.exit(1)
