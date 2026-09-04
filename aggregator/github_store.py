"""
Читання й запис невеликих JSON-файлів прямо в GitHub-репозиторій через
REST API (Contents API) — так сервер (Render) може "запам'ятовувати"
щось назавжди, хоча сам він нічого не зберігає між перезапусками
(диск на безкоштовному тарифі — тимчасовий, скидається).

Використовується для профілів розсилки (profiles/<google-sub>.json):
сервер їх записує, коли людина зберігає налаштування розсилки на
дошці, а запланована перевірка (GitHub Actions) потім читає їх із
самого репозиторію — так само, як вона вже читає config.yaml.
"""

from __future__ import annotations

import base64
import json
from typing import Optional

import requests

_API_ROOT = "https://api.github.com"


class GitHubStoreError(Exception):
    """Не вдалося прочитати або записати файл через GitHub API."""


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def read_json(
    repo: str, token: str, path: str,
    timeout: float = 15.0, session: Optional[requests.Session] = None,
) -> tuple[Optional[dict], Optional[str]]:
    """
    Повертає (вміст файлу як dict, sha файлу). Якщо файлу немає —
    (None, None). Кидає GitHubStoreError на будь-яку іншу помилку
    (погані права токена, недоступний репозиторій тощо).
    """
    http = session or requests
    resp = http.get(
        f"{_API_ROOT}/repos/{repo}/contents/{path}",
        headers=_headers(token), timeout=timeout,
    )
    if resp.status_code == 404:
        return None, None
    if not resp.ok:
        raise GitHubStoreError(f"GitHub API {resp.status_code} (GET {path}): {resp.text[:300]}")

    body = resp.json()
    content = base64.b64decode(body["content"]).decode("utf-8")
    return json.loads(content), body["sha"]


def write_json(
    repo: str, token: str, path: str, data: dict, message: str,
    sha: Optional[str] = None, timeout: float = 15.0,
    session: Optional[requests.Session] = None,
) -> None:
    """
    Створює або оновлює файл. Якщо файл уже існує — потрібен його
    поточний `sha` (з read_json), інакше GitHub відмовить.
    """
    http = session or requests
    encoded = base64.b64encode(
        json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    ).decode("ascii")
    payload: dict = {"message": message, "content": encoded}
    if sha:
        payload["sha"] = sha

    resp = http.put(
        f"{_API_ROOT}/repos/{repo}/contents/{path}",
        headers=_headers(token), json=payload, timeout=timeout,
    )
    if not resp.ok:
        raise GitHubStoreError(f"GitHub API {resp.status_code} (PUT {path}): {resp.text[:300]}")


def trigger_workflow(
    repo: str, token: str, workflow_file: str, ref: str = "main",
    timeout: float = 15.0, session: Optional[requests.Session] = None,
) -> None:
    """
    Запускає workflow (напр. `.github/workflows/check.yml`) негайно —
    так само, як кнопка "Run workflow" на вкладці Actions. Токен
    повинен мати право **Actions: Read and write** — самого лише
    Contents (потрібного для profiles/*.json) для цього не досить,
    GitHub інакше відмовить 403/404.

    Використовується сервером AI-чату (server/app.py) одразу після
    збереження профілю розсилки, щоб перший лист прийшов негайно, а не
    чекав до наступного запланованого проходу (раз на годину).
    """
    http = session or requests
    resp = http.post(
        f"{_API_ROOT}/repos/{repo}/actions/workflows/{workflow_file}/dispatches",
        headers=_headers(token), json={"ref": ref}, timeout=timeout,
    )
    if not resp.ok:
        raise GitHubStoreError(
            f"GitHub API {resp.status_code} (dispatch {workflow_file}): {resp.text[:300]}"
        )


def delete_json(
    repo: str, token: str, path: str, sha: str, message: str,
    timeout: float = 15.0, session: Optional[requests.Session] = None,
) -> None:
    http = session or requests
    resp = http.delete(
        f"{_API_ROOT}/repos/{repo}/contents/{path}",
        headers=_headers(token), json={"message": message, "sha": sha}, timeout=timeout,
    )
    if not resp.ok:
        raise GitHubStoreError(f"GitHub API {resp.status_code} (DELETE {path}): {resp.text[:300]}")
