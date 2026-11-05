#!/usr/bin/env bash
# Keep signed Ubuntu repositories, avoiding the slow Azure mirror observed in run 42048478123.
set -euo pipefail
sudo python3 - <<'PYTHON'
from pathlib import Path
paths = [Path('/etc/apt/apt-mirrors.txt'), Path('/etc/apt/apt-security-mirrors.txt'), Path('/etc/apt/sources.list')]
paths += list(Path('/etc/apt/sources.list.d').glob('*.sources'))
paths += list(Path('/etc/apt/sources.list.d').glob('*.list'))
for path in paths:
    if not path.is_file():
        continue
    text = path.read_text()
    updated = text.replace('http://azure.archive.ubuntu.com/ubuntu', 'https://archive.ubuntu.com/ubuntu')
    updated = updated.replace('http://archive.ubuntu.com/ubuntu', 'https://archive.ubuntu.com/ubuntu')
    updated = updated.replace('http://security.ubuntu.com/ubuntu', 'https://security.ubuntu.com/ubuntu')
    if updated != text:
        path.write_text(updated)
Path('/etc/apt/apt.conf.d/80genflow-retries').write_text('Acquire::Retries "2";\nAcquire::http::Timeout "30";\nAcquire::https::Timeout "30";\n')
PYTHON
