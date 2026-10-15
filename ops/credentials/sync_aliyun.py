"""Decrypt an encrypted inventory locally and synchronize Aliyun systemd env fragments."""
import argparse
import base64
import json
import shlex
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent


def load_inventory(path):
    schema = json.loads((HERE / 'schema.json').read_text(encoding='utf-8'))
    if not path.is_file():
        raise ValueError('Encrypted inventory missing; see README.md')
    # Refuse plaintext even when the file name ends in .sops.json.
    if 'sops' not in json.loads(path.read_text(encoding='utf-8')):
        raise ValueError('Inventory is not SOPS-encrypted')
    result = subprocess.run(['sops', 'decrypt', '--output-type', 'json', str(path)],
                            capture_output=True, check=True)
    inventory = json.loads(result.stdout)
    if set(inventory) != set(schema):
        raise ValueError('Missing/unknown inventory group')
    seen = set()
    for group, config in schema.items():
        values = inventory[group]
        required = set(config['required'])
        allowed = required | set(config['optional'])
        if not isinstance(values, dict) or set(values) - allowed or required - set(values):
            raise ValueError('Invalid or missing keys in ' + group)
        if seen.intersection(values):
            raise ValueError('Key defined in multiple groups')
        seen.update(values)
        for key, value in values.items():
            if not isinstance(value, str) or any(c in value for c in '\r\n\0') or (key in required and not value):
                raise ValueError('Invalid or empty value for ' + key)
    if inventory['hwprogm']['DASHBOARD_USERNAME'] == 'admin' and inventory['hwprogm']['DASHBOARD_PASSWORD'] == 'admin':
        raise ValueError('Insecure dashboard login')
    return inventory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', type=Path, default=HERE / 'secrets.sops.json')
    parser.add_argument('--host', default='root@118.31.49.14')
    parser.add_argument('--check', action='store_true', help='Validate inventory without connecting')
    parser.add_argument('--confirm', choices=['SYNC'], help='Explicitly authorize noninteractive deployment')
    args = parser.parse_args()
    data = load_inventory(args.inventory)
    if args.check:
        print('Encrypted inventory schema valid (values withheld).')
        return
    if args.confirm != 'SYNC':
        if not sys.stdin.isatty():
            raise ValueError('Interactive confirmation or --confirm SYNC required')
        if input(f'Synchronize encrypted credentials to {args.host}? Type SYNC: ') != 'SYNC':
            raise ValueError('Cancelled')
    code = base64.b64encode((HERE / 'apply_remote.py').read_bytes()).decode('ascii')
    # Only static Python source (not secrets) goes into remote argv. Secrets travel on stdin.
    remote = "import base64;exec(compile(base64.b64decode('" + code + "'),'<remote-sync>','exec'))"
    subprocess.run(['ssh', '-T', args.host, 'python3 -c ' + shlex.quote(remote)],
                   input=json.dumps({'groups': data}).encode(), check=True)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, subprocess.CalledProcessError, FileNotFoundError) as exc:
        print('Sync failed: ' + (str(exc) if isinstance(exc, ValueError) else type(exc).__name__), file=sys.stderr)
        sys.exit(1)
