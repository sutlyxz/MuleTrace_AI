"""Private backend environment loading and public runtime settings."""
from __future__ import annotations

from dataclasses import dataclass
import math
import os
from pathlib import Path
from typing import Mapping

try:
    from dotenv import dotenv_values
except ImportError:
    def dotenv_values(dotenv_path: Path | str, encoding: str = 'utf-8-sig', interpolate: bool = False) -> dict[str, str]:
        parsed: dict[str, str] = {}
        target = Path(dotenv_path)
        if not target.is_file():
            return parsed
        for line in target.read_text(encoding=encoding).splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, val = line.split('=', 1)
            parsed[key.strip()] = val.strip().strip("'\"")
        return parsed


def load_environment(root: Path, base_environment: Mapping[str, str] | None = None) -> dict[str, str]:
    environment = dict(os.environ if base_environment is None else base_environment)
    path = root / '.env'
    if path.is_file():
        values = dotenv_values(path, encoding='utf-8-sig', interpolate=False)
        environment.update({key: value for key, value in values.items() if value is not None})
    environment['PYTHONUNBUFFERED'] = '1'
    return environment


@dataclass(frozen=True)
class RuntimeSettings:
    frontend_port: int = 8000
    scan_interval: float = 3.0

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> RuntimeSettings:
        try:
            port = int(environment.get('FRONTEND_PORT', '8000'))
        except ValueError:
            raise ValueError('FRONTEND_PORT must be an integer from 1 to 65535.') from None
        if not 1 <= port <= 65535:
            raise ValueError('FRONTEND_PORT must be an integer from 1 to 65535.')
        try:
            interval = float(environment.get('SCAN_INTERVAL', '3'))
        except ValueError:
            raise ValueError('SCAN_INTERVAL must be a positive finite number.') from None
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError('SCAN_INTERVAL must be a positive finite number.')
        return cls(frontend_port=port, scan_interval=interval)


@dataclass(frozen=True)
class BedrockSettings:
    region: str = "us-east-1"
    model_id: str = "amazon.nova-lite-v1:0"

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> BedrockSettings:
        region = environment.get("AWS_REGION") or environment.get("AWS_DEFAULT_REGION") or "us-east-1"
        model_id = environment.get("BEDROCK_MODEL_ID") or "amazon.nova-lite-v1:0"
        return cls(region=region.strip(), model_id=model_id.strip())


def frontend_environment(environment: Mapping[str, str]) -> dict[str, str]:
    allowed = {
        'PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'HOME', 'USERPROFILE',
        'LANG', 'LC_ALL', 'PYTHONUTF8', 'PYTHONIOENCODING', 'PYTHONDONTWRITEBYTECODE',
    }
    return {key: value for key, value in environment.items() if key.upper() in allowed}
