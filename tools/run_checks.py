"""Run the published behavioral checks without requiring a platform shell."""
from pathlib import Path
import json
import os
import subprocess
import sys
import time


def main():
    root = Path(__file__).resolve().parents[1]
    qa = root / 'qa'
    qa.mkdir(exist_ok=True)
    runtime_temp = qa / 'runtime-temp'
    runtime_temp.mkdir(exist_ok=True)
    suites = [
        ('citation', [sys.executable, '-m', 'unittest', 'discover', '-s', 'skills/citation-evidence-check/tests', '-p', 'test_*.py', '-v']),
        ('offline', [sys.executable, '-m', 'unittest', 'discover', '-s', 'skills/offline-course-delivery/tests', '-p', 'test_*.py', '-v']),
        ('mobile-browser', ['node', '--test', 'skills/mobile-chat-regression/tests/test_chat.mjs']),
        ('offline-browser', ['node', '--test', 'tests/offline-browser.test.mjs']),
    ]
    results = []
    for name, command in suites:
        started = time.monotonic()
        try:
            result = subprocess.run(command, cwd=root, env={**os.environ, 'PYTHONUTF8': '1', 'PYTHONDONTWRITEBYTECODE': '1', 'TEMP': str(runtime_temp), 'TMP': str(runtime_temp), 'TMPDIR': str(runtime_temp)}, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=180)
            code, output = result.returncode, result.stdout + result.stderr
        except (OSError, subprocess.TimeoutExpired) as exc:
            code, output = 2, str(exc)
        (qa / f'{name}.log').write_text(output, encoding='utf-8')
        results.append({'suite': name, 'exitCode': code, 'seconds': round(time.monotonic() - started, 2), 'log': f'qa/{name}.log'})
        print(f'{name}: {"PASS" if code == 0 else "FAIL"} ({results[-1]["seconds"]}s)', flush=True)
        if code:
            print(output[-6000:], flush=True)
    report = {'status': 'passed' if all(row['exitCode'] == 0 for row in results) else 'failed', 'suites': results}
    (qa / 'checks.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
