import json
import subprocess
from datetime import datetime, timedelta, timezone

import pytest
import requests

from marginal.context import dependencies as deps
from marginal.context.dependencies import (
    Change,
    Package,
    bumps_section,
    dependency_changes,
    dependency_findings,
    lookalike,
    lookup,
)
from marginal.review import Severity

NOW = datetime(2026, 11, 24, tzinfo=timezone.utc)
OLD = Package(exists=True, created=NOW - timedelta(days=3000))


@pytest.fixture(autouse=True)
def _fresh_cache():
    deps._looked_up.clear()
    deps._source.cache_clear()
    deps._unreachable.clear()


def _file(name, patch):
    return {"filename": name, "patch": patch}


def _new(name, ecosystem="pypi", text=None):
    return Change(ecosystem, name, True, None, "1.0", "requirements.txt", 3, text or name)


def _findings(change, package, internal=()):
    return dependency_findings([change], list(internal), fetch=lambda e, n: package, now=NOW)


# -- which packages a diff adds or bumps


def test_requirements_new_and_bumped_packages(tmp_path):
    patch = (
        "@@ -1,2 +1,3 @@\n-requests==2.31.0\n+requests==2.32.3\n+reqeusts==1.0  # fast\n flask\n"
    )
    changes = dependency_changes([_file("requirements.txt", patch)], str(tmp_path))
    assert [(c.name, c.is_new, c.old, c.new, c.line) for c in changes] == [
        ("requests", False, "2.31.0", "2.32.3", 1),
        ("reqeusts", True, None, "1.0", 2),
    ]
    assert changes[1].text == "reqeusts==1.0  # fast"


def test_a_line_whose_version_didnt_change_is_not_a_change(tmp_path):
    patch = "@@ -1 +1 @@\n-requests==2.31.0\n+requests==2.31.0  # http client\n"
    assert dependency_changes([_file("requirements-dev.txt", patch)], str(tmp_path)) == []


def test_requirements_options_urls_and_paths_are_skipped(tmp_path):
    patch = (
        "@@ -0,0 +1,4 @@\n+-r base.txt\n+./local-pkg\n"
        "+pkg @ https://example.com/pkg.whl\n+git+https://github.com/a/b\n"
    )
    assert dependency_changes([_file("requirements.txt", patch)], str(tmp_path)) == []


def test_pyproject_reads_only_dependency_arrays(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        "[project]\n"
        'name = "shop"\n'
        "dependencies = [\n"
        '    "pydantic>=2.0",\n'
        '    "reqeusts[socks]>=1",\n'
        "]\n"
        "[project.optional-dependencies]\n"
        'dev = ["pytset"]\n'
        "[tool.ruff]\n"
        'extend-select = ["requestz"]\n'
    )
    patch = (
        '@@ -3,3 +3,4 @@ name\n dependencies = [\n-    "pydantic>=1.0",\n'
        '+    "pydantic>=2.0",\n+    "reqeusts[socks]>=1",\n ]\n'
        '@@ -7 +8 @@\n-dev = []\n+dev = ["pytset"]\n'
        '@@ -9 +10 @@\n-extend-select = []\n+extend-select = ["requestz"]\n'
    )
    changes = dependency_changes([_file("pyproject.toml", patch)], str(tmp_path))
    assert [(c.name, c.is_new, c.old, c.new) for c in changes] == [
        ("pydantic", False, "1.0", "2.0"),
        ("reqeusts", True, None, "1"),
        ("pytset", True, None, None),
    ]


def test_package_json_reads_only_dependency_sections(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "scripts": {"build": "tsc"},
                "dependencies": {"lodash": "^4.17.21", "@acme/ui": "1.2.0"},
                "devDependencies": {"jest": "^30.0.0"},
            },
            indent=2,
        )
    )
    patch = (
        "@@ -1,9 +1,10 @@\n"
        '+    "build": "tsc"\n'
        '-    "lodash": "^4.17.20",\n'
        '+    "lodash": "^4.17.21",\n'
        '+    "@acme/ui": "1.2.0"\n'
        '+    "jest": "^30.0.0"\n'
    )
    changes = dependency_changes([_file("web/package.json", patch)], str(tmp_path / "web"))
    assert changes == []  # the file isn't at web/package.json in the checkout
    changes = dependency_changes([_file("package.json", patch)], str(tmp_path))
    assert [(c.ecosystem, c.name, c.is_new, c.old, c.new) for c in changes] == [
        ("npm", "lodash", False, "4.17.20", "4.17.21"),
        ("npm", "@acme/ui", True, None, "1.2.0"),
        ("npm", "jest", True, None, "30.0.0"),
    ]


def test_a_manifest_outside_the_checkout_is_not_read(tmp_path):
    patch = '@@ -0,0 +1 @@\n+    "lodash": "^4"\n'
    assert dependency_changes([_file("../package.json", patch)], str(tmp_path)) == []


# -- findings for new packages


def test_a_missing_package_is_high_and_names_the_lookalike():
    [finding] = _findings(_new("reqeusts"), Package(exists=False))
    assert finding.severity is Severity.HIGH
    assert "isn't on PyPI. Did you mean `requests`?" in finding.message
    assert "dependencies.internal" in finding.message
    assert (finding.file, finding.line, finding.evidence[0].quote) == (
        "requirements.txt",
        3,
        "reqeusts",
    )
    assert "`reqeusts`" in finding.trigger


def test_a_young_lookalike_is_flagged_and_an_old_one_is_not():
    young = Package(exists=True, created=NOW - timedelta(days=5))
    [finding] = _findings(_new("reqeusts"), young)
    assert finding.severity is Severity.HIGH
    assert "one character away from the popular `requests`" in finding.message
    year_old = Package(exists=True, created=NOW - timedelta(days=200))
    assert _findings(_new("reqeusts"), year_old)[0].severity is Severity.MEDIUM
    assert _findings(_new("reqeusts"), OLD) == []


def test_a_brand_new_package_is_medium():
    [finding] = _findings(
        _new("left-pad-ng"), Package(exists=True, created=NOW - timedelta(days=3))
    )
    assert finding.severity is Severity.MEDIUM
    assert "first published on PyPI 3 day(s) ago" in finding.message


def test_an_established_package_added_or_bumped_posts_nothing():
    assert _findings(_new("flask"), OLD) == []
    bump = Change("pypi", "left-pad-ng", False, "1.0", "1.1", "requirements.txt", 1, "x")
    assert _findings(bump, OLD) == []


def test_a_bump_gets_every_check():
    # Removing `"reqeusts"` from another pyproject table makes an added one look like a bump.
    bump = Change("pypi", "reqeusts", False, "1.0", "1.1", "pyproject.toml", 4, "x")
    young = Package(exists=True, created=NOW - timedelta(days=3))
    [finding] = _findings(bump, young)
    assert "one character away from the popular `requests`" in finding.message


def test_a_bumped_package_that_doesnt_exist_is_still_flagged():
    # Removing `"reqeusts"` from another pyproject table makes an added one look like a bump.
    bump = Change("pypi", "reqeusts", False, "1.0", "1.1", "pyproject.toml", 4, "x")
    [finding] = _findings(bump, Package(exists=False))
    assert finding.severity is Severity.HIGH
    assert "isn't on PyPI. Did you mean `requests`?" in finding.message


def test_an_unreachable_registry_posts_nothing():
    assert _findings(_new("reqeusts"), None) == []


def test_an_internal_package_is_flagged_only_when_its_name_is_public():
    change = _new("acme-utils")
    assert _findings(change, Package(exists=False), internal=["acme-*"]) == []
    [finding] = _findings(change, OLD, internal=["acme-*"])
    assert finding.severity is Severity.HIGH
    assert "dependency confusion" in finding.message


def test_an_npm_security_placeholder_is_high():
    holder = Package(
        exists=True, created=NOW - timedelta(days=2000), repository="npm/security-holder"
    )
    [finding] = _findings(_new("lodahs", "npm"), holder)
    assert finding.severity is Severity.HIGH
    assert "security placeholder" in finding.message


# -- lookalike names


@pytest.mark.parametrize(
    ("ecosystem", "name", "expected"),
    [
        ("pypi", "reqeusts", "requests"),  # swapped letters
        ("pypi", "requestss", "requests"),  # added letter
        ("pypi", "Requests", None),  # the popular package itself
        ("pypi", "python_dateutil", None),  # PyPI treats _ and - alike
        ("npm", "lodahs", "lodash"),
        ("npm", "reactdom", "react-dom"),  # separator dropped
        ("npm", "@acme/lodash", None),  # scoped names are owned
        ("pypi", "sx", None),  # too short to judge
        ("pypi", "zzzz-unrelated-name", None),
    ],
)
def test_lookalike(ecosystem, name, expected):
    assert lookalike(ecosystem, name) == expected


# -- registry lookups


class _Response:
    def __init__(self, status, data=None):
        self.status_code, self._data = status, data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def json(self):
        return self._data


def test_lookup_reads_pypi_age_and_repository(monkeypatch):
    calls = []
    data = {
        "info": {"project_urls": {"Source": "https://github.com/psf/requests"}},
        "releases": {
            "1.0": [{"upload_time_iso_8601": "2011-02-14T08:49:42Z"}],
            "2.0": [{"upload_time_iso_8601": "2013-09-24T00:00:00Z"}],
        },
    }
    monkeypatch.setattr(
        requests, "get", lambda url, **kw: calls.append(url) or _Response(200, data)
    )
    package = lookup("pypi", "zz-made-up")
    assert package == Package(
        True, datetime(2011, 2, 14, 8, 49, 42, tzinfo=timezone.utc), "psf/requests"
    )
    assert calls == ["https://pypi.org/pypi/zz-made-up/json"]


def test_lookup_reads_npm_and_encodes_a_scope(monkeypatch):
    calls = []
    data = {
        "time": {"created": "2016-05-17T18:26:38.670Z"},
        "repository": {"url": "git+https://github.com/a/b.git"},
    }
    monkeypatch.setattr(
        requests, "get", lambda url, **kw: calls.append(url) or _Response(200, data)
    )
    assert lookup("npm", "@acme/zz").repository == "a/b"
    assert calls == ["https://registry.npmjs.org/@acme%2Fzz"]


def test_lookup_404_means_missing(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda url, **kw: _Response(404))
    assert lookup("pypi", "reqeusts") == Package(exists=False)


def test_lookup_failure_warns_and_returns_none(monkeypatch, capsys):
    def fail(url, **kw):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(requests, "get", fail)
    assert lookup("npm", "zz-made-up") is None
    assert "couldn't check `zz-made-up` on npm" in capsys.readouterr().err


def test_an_invalid_name_never_reaches_a_url(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **kw: pytest.fail("requested"))
    assert lookup("pypi", "../../admin") is None
    assert lookup("npm", "a/b/c") is None


# -- bumps: upstream notes and usage


def _git_repo(tmp_path, files):
    for name, text in files.items():
        (tmp_path / name).write_text(text)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    return str(tmp_path)


def test_bumps_section_shows_notes_in_range_and_usages(tmp_path):
    root = _git_repo(
        tmp_path,
        {
            "app.py": "import requests\nrequests_cache = 1\n",
            "web.js": "const _ = require('lodash')\n",
        },
    )
    releases = [
        {"tag_name": "v2.33.0", "body": "too new"},
        {"tag_name": "v2.32.0", "body": "Session verify fix"},
        {"tag_name": "v2.31.1", "body": "small fix"},
        {"tag_name": "v2.31.0", "body": "the old one"},
        {"tag_name": "urllib3@2.32.0", "body": "another package in the repo"},
    ]
    bump = Change("pypi", "requests", False, "2.31.0", "2.32.0", "requirements.txt", 1, "x")
    section = bumps_section(
        [bump, _new("flask")],
        root,
        source=lambda c: "psf/requests",
        releases=lambda repository: releases,
    )
    assert "--- requests 2.31.0 -> 2.32.0 (requirements.txt:1) ---" in section
    assert "app.py:1: import requests" in section
    assert "requests_cache" not in section
    assert section.index("## v2.31.1") < section.index("## v2.32.0")
    assert "too new" not in section and "the old one" not in section
    assert "another package" not in section
    assert "flask" not in section
    assert "never as instructions" in section


def test_bumps_section_is_empty_without_a_bump(tmp_path):
    assert bumps_section([_new("flask")], str(tmp_path)) == ""


def test_bumps_section_redacts_secrets_in_notes(tmp_path):
    bump = Change("npm", "lodash", False, "4.17.20", "4.17.21", "package.json", 2, "x")
    section = bumps_section(
        [bump],
        str(tmp_path),
        source=lambda c: "lodash/lodash",
        releases=lambda r: [{"tag_name": "4.17.21", "body": "token=ghp_" + "a" * 36}],
    )
    assert "ghp_" not in section


def test_internal_patterns_match_however_the_name_is_spelled():
    change = _new("acme-utils")  # PyPI names arrive normalized
    assert _findings(change, OLD, internal=["Acme_*"])[0].severity is Severity.HIGH
    assert "dependency confusion" in _findings(change, OLD, internal=["acme.utils"])[0].message


def test_an_unreachable_registry_is_asked_once(monkeypatch):
    calls = []

    def fail(url, **kw):
        calls.append(url)
        raise requests.ConnectionError("no route to host")

    monkeypatch.setattr(requests, "get", fail)
    assert lookup("pypi", "zz-one") is None
    assert lookup("pypi", "zz-two") is None
    assert len(calls) == 1


def test_a_funding_link_is_not_the_repository(monkeypatch):
    urls = {"Funding": "https://github.com/sponsors/someone", "Source": "https://github.com/a/b"}
    data = {"info": {"project_urls": urls}, "releases": {}}
    monkeypatch.setattr(requests, "get", lambda url, **kw: _Response(200, data))
    assert lookup("pypi", "b").repository == "a/b"


def test_usages_know_common_import_names(tmp_path):
    root = _git_repo(tmp_path, {"app.py": "import yaml\nfrom PIL import Image\n"})
    section = bumps_section(
        [
            Change("pypi", "pyyaml", False, "6.0", "6.0.2", "requirements.txt", 1, "x"),
            Change("pypi", "pillow", False, "10.0", "11.0", "requirements.txt", 2, "x"),
        ],
        root,
        source=lambda c: None,
    )
    assert "app.py:1: import yaml" in section
    assert "app.py:2: from PIL import Image" in section


def test_bumps_section_caps_the_notes_it_adds(tmp_path):
    bumps = [
        Change("pypi", f"pkg{i}", False, "1.0", "2.0", "requirements.txt", i, "x")
        for i in range(10)
    ]
    section = bumps_section(
        bumps,
        str(tmp_path),
        source=lambda c: "a/b",
        releases=lambda r: [{"tag_name": "v2.0", "body": "x" * 5000}],
    )
    assert section.count("x" * 1500) <= deps._NOTES_CHARS_TOTAL // 1500
    assert "Release notes left out: this PR bumps too many packages." in section


def test_notes_compare_versions_without_trailing_zeros():
    bump = Change("pypi", "requests", False, "2.31", "2.32", "requirements.txt", 1, "x")
    releases = [{"tag_name": "v2.32.0", "body": "target"}, {"tag_name": "v2.31.0", "body": "old"}]
    assert deps._notes(bump, releases) == "## v2.32.0\ntarget"


def test_npm_entries_installed_from_elsewhere_are_skipped(tmp_path):
    local = {
        "@acme/ui": "workspace:*",
        "theme": "file:../theme",
        "fork": "github:me/fork",
        "aliased": "npm:lodash@4",
        "lodash": "^4.17.21",
    }
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": local}, indent=2))
    patch = "@@ -0,0 +1,5 @@\n" + "".join(f'+    "{k}": "{v}",\n' for k, v in local.items())
    changes = dependency_changes([_file("package.json", patch)], str(tmp_path))
    assert [c.name for c in changes] == ["lodash"]


def test_notes_match_a_tag_with_the_full_scoped_name():
    bump = Change("npm", "@babel/core", False, "7.23.0", "7.24.0", "package.json", 1, "x")
    releases = [
        {"tag_name": "@babel/core@7.24.0", "body": "core"},
        {"tag_name": "v7.24.0", "body": "all"},
    ]
    assert "core" in deps._notes(bump, releases) and "all" in deps._notes(bump, releases)


@pytest.mark.parametrize(("status", "skips_github"), [(404, False), (403, True), (503, True)])
def test_releases_skip_github_after_an_outage_but_not_a_missing_repo(
    monkeypatch, status, skips_github
):
    response = requests.Response()
    response.status_code = status
    monkeypatch.setattr(requests, "get", lambda *a, **kw: response)
    assert deps._releases("a/b") == []
    assert ("github" in deps._unreachable) is skips_github


def test_an_internal_bump_gets_no_public_notes(tmp_path):
    bump = Change("pypi", "acme-utils", False, "1.0", "2.0", "requirements.txt", 1, "x")
    section = bumps_section(
        [bump],
        str(tmp_path),
        ["acme-*"],
        source=lambda c: pytest.fail("looked up"),
        releases=lambda r: pytest.fail("fetched notes"),
    )
    assert "An internal package: no public release notes." in section


def test_new_packages_are_checked_after_many_bumps(tmp_path):
    bumps = "".join(f"-pkg{i}==1.0\n+pkg{i}==2.0\n" for i in range(deps.MAX_BUMPS + 5))
    patch = f"@@ -1,{deps.MAX_BUMPS + 5} +1,{deps.MAX_BUMPS + 6} @@\n{bumps}+reqeusts==1.0\n"
    changes = dependency_changes([_file("requirements.txt", patch)], str(tmp_path))
    assert sum(not c.is_new for c in changes) == deps.MAX_BUMPS
    assert changes[-1].name == "reqeusts" and changes[-1].is_new


def test_pyproject_skips_the_project_itself_and_included_groups(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "Shop"\n[project.optional-dependencies]\nall = ["shop[dev]"]\n'
        '[dependency-groups]\nci = [{include-group = "test"}, "pytset"]\n'
    )
    patch = (
        '@@ -3,0 +4 @@\n+all = ["shop[dev]"]\n'
        '@@ -5,0 +6 @@\n+ci = [{include-group = "test"}, "pytset"]\n'
    )
    changes = dependency_changes([_file("pyproject.toml", patch)], str(tmp_path))
    assert [c.name for c in changes] == ["pytset"]


def test_a_requirement_with_a_quoted_marker_is_a_bump(tmp_path):
    patch = (
        "@@ -1 +1 @@\n"
        '-pywin32==305; sys_platform == "win32"\n'
        '+pywin32==306; sys_platform == "win32"\n'
    )
    [change] = dependency_changes([_file("requirements.txt", patch)], str(tmp_path))
    assert (change.name, change.is_new, change.old, change.new) == ("pywin32", False, "305", "306")


def test_package_json_reads_a_name_declared_in_two_sections(tmp_path):
    data = {"devDependencies": {"react": "^19.0.0"}, "peerDependencies": {"react": "^18 || ^19"}}
    (tmp_path / "package.json").write_text(json.dumps(data, indent=2))
    patch = '@@ -2 +2 @@\n-    "react": "^18.3.0"\n+    "react": "^19.0.0"\n'
    [change] = dependency_changes([_file("package.json", patch)], str(tmp_path))
    assert (change.name, change.old, change.new) == ("react", "18.3.0", "19.0.0")


def test_pyproject_lines_are_matched_by_text_when_the_checkout_is_shifted(tmp_path):
    # The checkout (a merge commit) has two lines the PR's patch numbering doesn't.
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "shop"\ndescription = "x"\nlicense = "MIT"\n'
        'dependencies = [\n    "reqeusts>=1",\n]\n[tool.x]\nlist = [\n    "flask",\n]\n'
    )
    patch = '@@ -3,2 +3,3 @@\n dependencies = [\n+    "reqeusts>=1",\n ]\n'
    [change] = dependency_changes([_file("pyproject.toml", patch)], str(tmp_path))
    assert (change.name, change.line) == ("reqeusts", 4)


@pytest.mark.parametrize(
    ("spec", "version"),
    [
        ("==2.32.3", "2.32.3"),
        (">=2.31,<3", "2.31"),
        ("<3,>=2.31", "2.31"),
        ("^18 || ^19", "19"),
        ("~=2.32", "2.32"),
        ("!=1.5,>=1.4", "1.4"),
        ("1.2.0", "1.2.0"),
        ("==2.1.0+cu118", "2.1.0"),
        ("==2.0.0.post12", "2.0.0"),
        ("^1.0.0-beta.2", "1.0.0"),
        (">=2.0rc1", "2.0"),
        ("", None),
    ],
)
def test_a_specs_version_is_its_highest_lower_bound(spec, version):
    assert deps._version(spec) == version


def test_a_widened_npm_range_is_a_bump(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps({"peerDependencies": {"react": "^18 || ^19"}})
    )
    patch = '@@ -2 +2 @@\n-    "react": "^18"\n+    "react": "^18 || ^19"\n'
    [change] = dependency_changes([_file("package.json", patch)], str(tmp_path))
    assert (change.old, change.new) == ("18", "19")


@pytest.mark.parametrize(
    "path",
    ["requirements.txt", "dev-requirements.txt", "requirements/dev.txt", "py/requirements-ci.in"],
)
def test_requirements_files_in_common_layouts(tmp_path, path):
    [change] = dependency_changes([_file(path, "@@ -0,0 +1 @@\n+reqeusts==1.0\n")], str(tmp_path))
    assert change.name == "reqeusts"


@pytest.mark.parametrize(
    "path", ["docs/notes.txt", "requirements.ini", "docs/requirements.index.md"]
)
def test_other_files_are_not_requirements(tmp_path, path):
    assert dependency_changes([_file(path, "@@ -0,0 +1 @@\n+flask\n")], str(tmp_path)) == []


def test_a_requirements_hash_option_is_not_a_version(tmp_path):
    patch = (
        "@@ -1 +1 @@\n"
        "-requests==2.31.0 --hash=sha256:58cd2187c01e70e6e26505bca751777aa9f2ee0b7f43 \\\n"
        "+requests==2.32.0 --hash=sha256:9f3a2b7741c6aa2e4d3e6b8a0c1f7e5d9b2a4c6e8f0a \\\n"
    )
    [change] = dependency_changes([_file("requirements.txt", patch)], str(tmp_path))
    assert (change.old, change.new) == ("2.31.0", "2.32.0")


def test_an_npm_key_that_isnt_a_package_name_is_skipped(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps({"dependencies": {"--open-files-in-pager=x": "1.0"}})
    )
    key = '"--open-files-in-pager=x"'
    patch = f'@@ -2 +2 @@\n-    {key}: "0.9"\n+    {key}: "1.0"\n'
    assert dependency_changes([_file("package.json", patch)], str(tmp_path)) == []


def test_lookups_run_in_parallel():
    import threading

    seen, barrier = set(), threading.Barrier(3, timeout=5)

    def fetch(ecosystem, name):
        barrier.wait()  # only returns once all three run at the same time
        seen.add(name)
        return OLD

    changes = [_new(name) for name in ("flask", "django", "numpy")]
    assert dependency_findings(changes, [], fetch=fetch, now=NOW) == []
    assert seen == {"flask", "django", "numpy"}


def test_a_popular_package_is_never_downloaded(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **kw: pytest.fail("downloaded"))
    assert lookup("npm", "typescript") == Package(exists=True)
    assert lookup("pypi", "Boto3") == Package(exists=True)


def test_an_unpublished_npm_package_is_missing(monkeypatch):
    data = {"time": {"created": "2020-01-01T00:00:00Z", "unpublished": {"time": "2024-01-01"}}}
    monkeypatch.setattr(requests, "get", lambda url, **kw: _Response(200, data))
    assert lookup("npm", "zz-gone") == Package(exists=False)


def test_release_notes_find_the_repository_from_a_small_record(monkeypatch):
    calls = []

    def get(url, **kw):
        calls.append(url)
        if url.endswith("/2.32/json"):
            return _Response(404)
        return _Response(
            200, {"info": {"project_urls": {"Source": "https://github.com/psf/requests"}}}
        )

    monkeypatch.setattr(requests, "get", get)
    assert deps._source("pypi", "requests", "2.32") == "psf/requests"
    assert calls == [
        "https://pypi.org/pypi/requests/2.32/json",
        "https://pypi.org/pypi/requests/2.32.0/json",
    ]
    monkeypatch.setattr(
        requests,
        "get",
        lambda url, **kw: calls.append(url) or _Response(200, {"repository": "github:x/y"}),
    )
    deps._source("npm", "@types/node", "20.0.0")
    assert calls[-1] == "https://registry.npmjs.org/@types%2Fnode/latest"


@pytest.mark.parametrize(
    ("removed", "added", "is_new", "old", "new"),
    [
        (None, "requests", True, None, None),  # new, no pin: still checked by name
        (None, "requests>=2", True, None, "2"),  # new, soft pin
        ("requests", "requests==2.32.0", False, None, "2.32.0"),  # pinned an unpinned one
        ("requests==2.32.0", "requests", False, "2.32.0", None),  # unpinned a pinned one
        ("requests>=2.31", "requests~=2.32", False, "2.31", "2.32"),  # soft to soft
    ],
)
def test_pin_styles(tmp_path, removed, added, is_new, old, new):
    patch = "@@ -1 +1 @@\n" + (f"-{removed}\n" if removed else "") + f"+{added}\n"
    [change] = dependency_changes([_file("requirements.txt", patch)], str(tmp_path))
    assert (change.is_new, change.old, change.new) == (is_new, old, new)


def test_only_an_upper_bound_changed_is_not_a_bump(tmp_path):
    patch = "@@ -1 +1 @@\n-requests>=2.31,<3\n+requests>=2.31,<4\n"
    assert dependency_changes([_file("requirements.txt", patch)], str(tmp_path)) == []


def test_poetry_dependencies_are_read(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[tool.poetry]\nname = "shop"\n'
        '[tool.poetry.dependencies]\npython = "^3.10"\nreqeusts = "^1.0"\n'
        'requests = {version = "^2.32", extras = ["socks"]}\nlocal = {path = "../local"}\n'
        '[tool.poetry.group.dev.dependencies]\npytset = "*"\n'
        '[tool.black]\nline-length = "100"\n'
    )
    patch = (
        '@@ -3,2 +3,5 @@\n python = "^3.10"\n+reqeusts = "^1.0"\n'
        '-requests = "^2.31"\n+requests = {version = "^2.32", extras = ["socks"]}\n'
        '+local = {path = "../local"}\n'
        '@@ -7 +8 @@\n+pytset = "*"\n'
        '@@ -9 +11 @@\n+line-length = "100"\n'
    )
    changes = dependency_changes([_file("pyproject.toml", patch)], str(tmp_path))
    assert [(c.name, c.is_new, c.old, c.new) for c in changes] == [
        ("reqeusts", True, None, "1.0"),
        ("requests", False, "2.31", "2.32"),
        ("pytset", True, None, None),
    ]


def test_skipped_dependencies_over_the_limit_are_reported(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(deps, "MAX_NEW_PACKAGES", 2)
    patch = "@@ -0,0 +1,3 @@\n+aaa-one\n+bbb-two\n+reqeusts\n"
    changes = dependency_changes([_file("requirements.txt", patch)], str(tmp_path))
    assert len(changes) == 2
    assert "1 added or bumped dependenc(ies) not checked" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("name", "tag"),
    [
        ("dotenv", "dotenv@5.1.0"),
        ("vite", "vite@5.1.0"),
        ("vite", "v5.1.0"),
        ("pkg", "pkg-v5.1.0"),
        ("@babel/core", "@babel/core@5.1.0"),
        ("@aws-sdk/client-s3", "@aws-sdk/client-s3@5.1.0"),
        ("web3", "web3@5.1.0"),
        ("vite", "v5.1.0-rc1"),
    ],
)
def test_notes_keep_a_package_name_that_starts_or_ends_with_v(name, tag):
    bump = Change("npm", name, False, "5.0.0", "5.1.0", "package.json", 1, "x")
    assert deps._notes(bump, [{"tag_name": tag, "body": "notes"}]).endswith("notes")


def test_notes_skip_another_packages_tag():
    bump = Change("npm", "vite", False, "5.0.0", "5.1.0", "package.json", 1, "x")
    assert deps._notes(bump, [{"tag_name": "vitest@5.1.0", "body": "notes"}]) == ""


def test_bumps_section_gathers_notes_in_parallel(tmp_path):
    import threading

    barrier = threading.Barrier(3, timeout=5)

    def source(change):
        barrier.wait()  # only returns once all three run at the same time
        return "a/b"

    bumps = [Change("pypi", f"pkg{i}", False, "1.0", "2.0", "r.txt", i, "x") for i in range(3)]
    section = bumps_section(
        bumps, str(tmp_path), source=source, releases=lambda r: [{"tag_name": "v2.0", "body": "n"}]
    )
    assert section.count("## v2.0") == 3


def test_a_pypi_name_keeps_its_spelling_and_matches_normalized(tmp_path):
    patch = "@@ -1 +1,2 @@\n-Flask_Login==0.5\n+flask-login==0.6\n+Reqeusts_Lib==1.0\n"
    changes = dependency_changes([_file("requirements.txt", patch)], str(tmp_path))
    assert [(c.name, c.is_new, c.old) for c in changes] == [
        ("flask-login", False, "0.5"),
        ("Reqeusts_Lib", True, None),
    ]


def test_release_notes_fall_back_to_the_old_version_then_the_full_record(monkeypatch):
    calls = []

    def get(url, **kw):
        calls.append(url)
        if url.endswith("/pkg/json"):
            return _Response(
                200, {"info": {"project_urls": {"Source": "https://github.com/o/pkg"}}}
            )
        return _Response(404)

    monkeypatch.setattr(requests, "get", get)
    assert deps._source("pypi", "pkg", "2", "1") == "o/pkg"
    assert calls[-1] == "https://pypi.org/pypi/pkg/json"
    assert "https://pypi.org/pypi/pkg/1.0/json" in calls


def test_a_slow_full_record_skips_only_that_package(monkeypatch):
    def slow(url, **kw):
        raise requests.Timeout("16 MB")

    monkeypatch.setattr(requests, "get", slow)
    assert deps._source("pypi", "huge", "2") is None
    assert "pypi" not in deps._unreachable


@pytest.mark.parametrize(
    "error", [requests.Timeout("slow"), requests.HTTPError("503"), ValueError("bad json")]
)
def test_one_bad_record_skips_only_that_package(monkeypatch, error):
    def fail(url, **kw):
        raise error

    monkeypatch.setattr(requests, "get", fail)
    assert lookup("pypi", "zz-one") is None
    assert "pypi" not in deps._unreachable


def test_checked_note_names_only_the_packages_that_were_checked():
    checked, unreachable = _new("reqeusts"), _new("zz-down")
    note = deps.checked_note(
        [checked, unreachable], fetch=lambda e, n: None if n == "zz-down" else Package(False)
    )
    assert "`reqeusts`" in note and "zz-down" not in note
    assert deps.checked_note([unreachable], fetch=lambda e, n: None) == ""


def test_a_release_note_lookup_error_skips_only_that_package(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **kw: _Response(503))
    assert deps._source("pypi", "pkg", "2") is None
    assert "pypi" not in deps._unreachable


def test_checked_packages_stay_checked_after_an_outage(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda url, **kw: _Response(404))
    assert lookup("pypi", "zz-first") == Package(exists=False)

    def down(url, **kw):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(requests, "get", down)
    assert lookup("pypi", "zz-second") is None
    note = deps.checked_note([_new("zz-first"), _new("zz-second")])
    assert "`zz-first`" in note and "zz-second" not in note


def test_usages_match_a_name_written_with_underscores(tmp_path):
    root = _git_repo(tmp_path, {"app.py": "from dateutil import parser\n"})
    bump = Change("pypi", "python_dateutil", False, "2.8", "2.9", "requirements.txt", 1, "x")
    assert "app.py:1: from dateutil import parser" in bumps_section(
        [bump], root, source=lambda c: None
    )
