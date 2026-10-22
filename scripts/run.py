"""Start the local frontend and scanner using current private configuration."""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import time
import webbrowser


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def ensure_environment_file(root: Path) -> None:
    template = root / '.env.example'
    if (root / '.env').exists():
        return
    try:
        with (root / '.env').open('xb') as handle:
            handle.write(template.read_bytes())
    except FileExistsError:
        pass


def prepare_runtime(root: Path) -> Path:
    virtual_environment = root / '.venv'
    executable = virtual_environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if not executable.is_file():
        print('[SETUP] Creating the project virtual environment.', flush=True)
        subprocess.run([sys.executable, '-m', 'venv', str(virtual_environment)], cwd=root, check=True)
    requirements = root / 'requirements.txt'
    fingerprint = hashlib.sha256(requirements.read_bytes()).hexdigest()
    stamp = virtual_environment / '.requirements.sha256'
    synchronized = stamp.is_file() and stamp.read_text(encoding='utf-8') == fingerprint
    if synchronized:
        synchronized = subprocess.run(
            [str(executable), '-c', 'import pandas, dotenv'], cwd=root,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ).returncode == 0
    if not synchronized:
        print('[SETUP] Synchronizing requirements without a package cache.', flush=True)
        subprocess.run(
            [str(executable), '-m', 'pip', 'install', '--disable-pip-version-check',
             '--no-cache-dir', '-r', str(requirements)], cwd=root, check=True,
        )
        stamp.write_text(fingerprint, encoding='utf-8')
    return executable


def local_commands(root: Path, settings) -> tuple[list[str], list[str]]:
    frontend = [
        sys.executable, '-m', 'app.backend.server', str(settings.frontend_port),
        '--bind', '127.0.0.1', '--directory', str(root / 'app' / 'frontend'),
    ]
    scanner = [
        sys.executable, '-m', 'app.backend.workers.auto_scanner',
        '--interval', str(settings.scan_interval),
    ]
    return frontend, scanner


def stop_processes(processes) -> None:
    for process in reversed(processes):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def run_local(root: Path, settings, environment: dict[str, str], open_browser: bool = True) -> int:
    from app.backend.config import frontend_environment

    commands = local_commands(root, settings)
    processes = []
    url = f'http://localhost:{settings.frontend_port}'
    creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
    try:
        processes.append(subprocess.Popen(
            commands[0], cwd=root, env=frontend_environment(environment), creationflags=creation_flags,
        ))
        processes.append(subprocess.Popen(
            commands[1], cwd=root, env=environment, creationflags=creation_flags,
        ))
        print(f'[LOCAL] Frontend: {url}', flush=True)
        print('[LOCAL] Scanner is watching CSV data. Press Ctrl+C to stop both services.', flush=True)
        print('[CONFIG] Restart run.bat after changing backend code or .env.', flush=True)
        browser_pending = open_browser
        while True:
            for process in processes:
                status = process.poll()
                if status is not None:
                    print('[ERROR] A local service exited. Check its startup message above.', flush=True)
                    return status or 1
            time.sleep(0.5)
            if browser_pending and all(process.poll() is None for process in processes):
                webbrowser.open(url)
                browser_pending = False
    except KeyboardInterrupt:
        print('\n[STOP] Shutting down local services.', flush=True)
        return 0
    finally:
        stop_processes(processes)


def main() -> int:
    parser = argparse.ArgumentParser(description='Start MuleTrace locally with current .env and source files.')
    parser.add_argument('--no-browser', action='store_true', help='Do not open the browser automatically.')
    args = parser.parse_args()
    try:
        executable = prepare_runtime(PROJECT_ROOT)
        if Path(sys.prefix).resolve() != (PROJECT_ROOT / '.venv').resolve():
            return subprocess.call([str(executable), '-m', 'scripts.run', *sys.argv[1:]], cwd=PROJECT_ROOT)
        ensure_environment_file(PROJECT_ROOT)
        from app.backend.config import load_environment, RuntimeSettings

        environment = load_environment(PROJECT_ROOT)
        settings = RuntimeSettings.from_environment(environment)
        return run_local(PROJECT_ROOT, settings, environment, open_browser=not args.no_browser)
    except ValueError as error:
        print(f'[CONFIG ERROR] {error}', flush=True)
        return 1
    except (OSError, subprocess.SubprocessError):
        print('[ERROR] Setup or startup failed. Check Python, network, file permissions, and available disk space.', flush=True)
        return 1
    except KeyboardInterrupt:
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
