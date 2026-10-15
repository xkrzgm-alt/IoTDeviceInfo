"""Read-only key and permission audit; never print values or secret-derived hashes."""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]  # workspace containing HWProgM and IoTdeviceInfo
schema = json.loads((HERE / 'schema.json').read_text(encoding='utf-8'))
paths = {
    'local shared': ROOT / '.env.vendera',
    'HWProgM local': ROOT / 'HWProgM/dashboard/.env',
    'IoT local': ROOT / 'IoTdeviceInfo/.env',
    'obsolete Docker env': ROOT / 'IoTdeviceInfo/.env.deploy',
}
for label, path in paths.items():
    if not path.exists():
        print(f'{label}: absent')
        continue
    keys = {line.split('=', 1)[0].strip() for line in path.read_text(encoding='utf-8').splitlines()
            if '=' in line and not line.lstrip().startswith('#')}
    groups = {group: sorted(keys & (set(fields['required']) | set(fields['optional'])))
              for group, fields in schema.items()}
    print(f'{label}: ' + ', '.join(f'{group}={len(found)}' for group, found in groups.items()))
for group, fields in schema.items():
    required = set(fields['required'])
    sources = {key: [label for label, path in paths.items() if path.exists() and any(
        line.split('=', 1)[0].strip() == key for line in path.read_text(encoding='utf-8').splitlines()
        if '=' in line and not line.lstrip().startswith('#'))] for key in required}
    print(f'{group}: duplicate required keys: ' + ', '.join(sorted(k for k, v in sources.items() if len(v) > 1)))
