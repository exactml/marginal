"""Refresh the most-downloaded package names that dependency checks compare
new packages against (a name one typo away from one of these is flagged).

Run before cutting a release: `python scripts/refresh_popular_packages.py`.
"""

from __future__ import annotations

import re
from pathlib import Path

import requests

TOP = 5000
OUT = Path(__file__).resolve().parents[1] / "marginal" / "context" / "popular"
# Downloads over the last 30 days, from PyPI's BigQuery dataset.
PYPI = "https://hugovk.dev/top-pypi-packages/top-pypi-packages.min.json"
# The npm-high-impact package (MIT): npm packages ranked by downloads and dependents.
NPM = "https://unpkg.com/npm-high-impact/lib/top.js"


def main() -> None:
    pypi = [row["project"] for row in _get(PYPI).json()["rows"]]
    npm = re.findall(r"'([^']+)'", _get(NPM).text)
    for name, names in (("pypi", pypi), ("npm", npm)):
        if len(names) < TOP:
            raise SystemExit(f"{name}: only {len(names)} names, expected {TOP}")
        (OUT / f"{name}.txt").write_text("\n".join(names[:TOP]) + "\n")
        print(f"{name}: wrote {TOP} names, most downloaded first")


def _get(url: str) -> requests.Response:
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    return response


if __name__ == "__main__":
    main()
