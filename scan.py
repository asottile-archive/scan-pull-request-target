import argparse
import collections
import hashlib
import os.path
import shutil
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
from typing import Any
from typing import Dict
from typing import Generator
from typing import List
from typing import NamedTuple
from typing import Optional
from typing import Set
from typing import Tuple

import ruamel.yaml

from util import db_connect
from util import get_token
from util import req

yaml_load = ruamel.yaml.YAML(typ='safe').load


QUERY = (
    'pull_request_target actions/checkout github.event.pull_request '
    'extension:yml path:.github/workflows'
)


def _repos(token: str) -> Generator[str, None, None]:
    headers = {'Authorization': f'token {token}'}
    query = urllib.parse.urlencode({'q': QUERY})
    url = f'https://api.github.com/search/code?q={query}'

    resp = req(url, headers=headers)
    for result in resp.json['items']:
        if not result['repository']['fork']:
            yield result['repository']['full_name']

    while 'next' in resp.links:
        time.sleep(3)  # search api limit
        resp = req(resp.links['next'], headers=headers)
        for result in resp.json['items']:
            if not result['repository']['fork']:
                yield result['repository']['full_name']


class File(NamedTuple):
    name: str
    checksum: str

    def css_class(self, vulnerable: Dict[str, Optional[bool]]) -> str:
        return {
            None: 'file-unknown',
            True: 'file-bad',
            False: 'file-ok',
        }[vulnerable[self.checksum]]


class Repo(NamedTuple):
    repo: str
    rev: str
    account_type: str
    star_count: int
    files: Tuple[File, ...]

    @property
    def repo1(self) -> str:
        repo1, _, _ = self.repo.partition('/')
        return repo1

    @property
    def repo2(self) -> str:
        _, _, repo2 = self.repo.partition('/')
        return repo2

    def css_class(
            self,
            vulnerable: Dict[str, Optional[bool]],
            done: Set[str],
    ) -> str:
        if self.repo in done:
            return 'repo-done'
        elif all(vulnerable[file.checksum] is False for file in self.files):
            return 'repo-ok'
        elif any(vulnerable[file.checksum] is True for file in self.files):
            return 'repo-bad'
        else:
            return 'repo-unknown'

    @property
    def url(self) -> str:
        return f'https://github.com/{self.repo}'

    def file_url(self, filename: str) -> str:
        return f'https://github.com/{self.repo}/blob/{self.rev}/{filename}'


def _vulnerable_on(contents: Any) -> bool:
    if not isinstance(contents, dict) or 'on' not in contents:
        return False
    on = contents['on']
    if isinstance(on, list) and 'pull_request_target' in on:
        return True
    elif on == 'pull_request_target':
        return True
    elif not isinstance(on, dict) or 'pull_request_target' not in on:
        return False

    cfg = on['pull_request_target']
    if cfg is None:
        return True
    elif 'types' not in cfg:
        return True
    elif isinstance(cfg['types'], str):
        return cfg['types'] in {'opened', 'synchronize', 'reopened'}

    return bool(set(cfg['types']) & {'opened', 'synchronize', 'reopened'})


def _vulnerable_jobs(contents: Dict[str, Any]) -> bool:
    if not isinstance(contents, dict):
        return False
    elif 'jobs' not in contents or not isinstance(contents['jobs'], dict):
        return False
    for _, job in contents['jobs'].items():
        if not isinstance(job, dict):
            continue
        elif 'steps' not in job or not isinstance(job['steps'], list):
            continue

        for step in job['steps']:
            if not isinstance(step, dict):
                continue
            elif 'with' not in step or 'uses' not in step:
                continue
            elif not step['uses'].startswith('actions/checkout'):
                continue
            elif not isinstance(step['with'], dict):
                continue
            elif 'ref' not in step['with']:
                continue
            elif not isinstance(step['with']['ref'], str):
                continue
            else:
                return 'event.pull_request.base' not in step['with']['ref']
    else:
        return False


def _get_repo_info(repo: str, token: str) -> Repo:
    resp = req(
        f'https://api.github.com/repos/{repo}',
        headers={'Authorization': f'token {token}'},
    )
    account_type = resp.json['owner']['type']
    star_count = resp.json['stargazers_count']

    with tempfile.TemporaryDirectory() as tmpdir:
        git = ('git', '-c', 'protocol.version=2', '-C', tmpdir)
        subprocess.check_call((
            *git, 'clone', '--no-checkout', '--quiet', '--depth=1',
            f'https://github.com/{repo}', '.',
        ))
        subprocess.check_call((*git, 'reset', '-q', '--', '.github/workflows'))
        subprocess.check_call((*git, 'checkout', '--', '.github/workflows'))
        rev = subprocess.check_output((*git, 'rev-parse', 'HEAD')).strip()

        files = []
        for filename in os.listdir(os.path.join(tmpdir, '.github/workflows')):
            filename = os.path.join('.github/workflows', filename)
            if not filename.endswith('.yml'):
                continue

            tmp_filename = os.path.join(tmpdir, filename)
            with open(tmp_filename) as f:
                try:
                    contents = yaml_load(f)
                except ruamel.yaml.YAMLError:
                    continue

            if _vulnerable_on(contents) and _vulnerable_jobs(contents):
                with open(tmp_filename, 'rb') as f_b:
                    checksum = hashlib.sha256(f_b.read()).hexdigest()

                files.append(File(filename, checksum))

                dest = os.path.join('files', repo, rev.decode(), filename)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copy(tmp_filename, dest)

    return Repo(
        repo=repo,
        rev=rev.decode(),
        account_type=account_type,
        star_count=star_count,
        files=tuple(sorted(files)),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--full-refresh', action='store_true')
    args = parser.parse_args()

    token = get_token()

    if not args.full_refresh:
        with db_connect() as db:
            res = db.execute('SELECT DISTINCT repo FROM data').fetchall()
            seen = {repo for repo, in res}
            res = db.execute('SELECT repo FROM seen').fetchall()
            seen.update(repo for repo, in res)
    else:
        seen = set()

    by_org: Dict[str, List[Repo]] = collections.defaultdict(list)

    for repo_s in _repos(token):
        if repo_s in seen:
            continue
        else:
            seen.add(repo_s)

        org, _ = repo_s.split('/')
        by_org[org].append(_get_repo_info(repo_s, token))

    by_org = {k: [r for r in v if r.files] for k, v in by_org.items()}
    by_org = {k: v for k, v in sorted(by_org.items()) if v}

    for org, repos in by_org.items():
        for repo in repos:
            print(repo.repo)
            for filename, _ in repo.files:
                print(f'- {repo.file_url(filename)}')
            print()

    rows = [
        (
            repo.repo,
            filename,
            repo.rev,
            repo.account_type,
            repo.star_count,
            checksum,
        )
        for repos in by_org.values()
        for repo in repos
        for filename, checksum in repo.files
    ]
    seen_rows = [(repo,) for repo in seen]
    with db_connect() as db:
        query = 'INSERT OR REPLACE INTO data VALUES (?, ?, ?, ?, ?, ?)'
        db.executemany(query, rows)
        db.executemany('INSERT OR REPLACE INTO seen VALUES (?)', seen_rows)

    return 0


if __name__ == '__main__':
    exit(main())
