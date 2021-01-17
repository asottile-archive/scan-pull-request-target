import collections
import json
import os.path
import time
import urllib.parse
import urllib.request
import tempfile
import subprocess
from typing import Any, Dict, NamedTuple, Optional, List, Generator, Tuple


class Response(NamedTuple):
    json: Any
    links: Dict[str, str]


def _parse_link(lnk: Optional[str]) -> Dict[str, str]:
    if lnk is None:
        return {}

    ret = {}
    parts = lnk.split(',')
    for part in parts:
        link, _, rel = part.partition(';')
        link, rel = link.strip(), rel.strip()
        assert link.startswith('<') and link.endswith('>'), link
        assert rel.startswith('rel="') and rel.endswith('"'), rel
        link, rel = link[1:-1], rel[len('rel="'):-1]
        ret[rel] = link
    return ret


def req(url: str, **kwargs: Any) -> Response:
    resp = urllib.request.urlopen(urllib.request.Request(url, **kwargs))
    return Response(json.load(resp), _parse_link(resp.headers['link']))


def get_all(url: str, **kwargs: Any) -> List[Dict[str, Any]]:
    ret: List[Dict[str, Any]] = []
    resp = req(url, **kwargs)
    ret.extend(resp.json)
    while 'next' in resp.links:
        time.sleep(3)  # search api rate limit
        resp = req(resp.links['next'], **kwargs)
        ret.extend(resp.json)
    return ret


QUERY = (
    'pull_request_target secrets ref github.event.pull_request '
    'extension:yml path:.github/workflows'
)


def _repos(token: str) -> Generator[str, None, None]:
    headers = {'Authorization': f'token {token}'}
    query = urllib.parse.urlencode({'q': QUERY})
    url = f'https://api.github.com/search/code?q={query}'

    resp = req(url, headers=headers)
    for result in resp.json['items']:
        yield result['repository']['full_name']

    while 'next' in resp.links:
        resp = req(resp.links['next'], headers=headers)
        for result in resp.json['items']:
            yield result['repository']['full_name']


class RepoInfo(NamedTuple):
    repo: str
    rev: str
    filenames: Tuple[str, ...]

    @property
    def url(self) -> str:
        return f'https://github.com/{self.repo}'

    def file_url(self, filename: str) -> str:
        return f'https://github.com/{self.repo}/blob/{self.rev}/{filename}'


def zsplit(bts: bytes) -> List[bytes]:
    bts = bts.strip(b'\0')
    if not bts:
        return []
    else:
        return bts.split(b'\0')


PATTERNS = (
    r'\bpull_request_target\b',
    r'\bref\b',
    r'\bsecrets\.',
    r'\bgithub\.event\.pull_request\b',
    r'\bcheckout\b',
)


def _get_repo_info(repo: str) -> RepoInfo:
    with tempfile.TemporaryDirectory() as tmpdir:
        git = ('git', '-c', 'protocol.version=2', '-C', tmpdir)
        subprocess.check_call((
            *git, 'clone', '--quiet', '--depth=1',
            f'https://github.com/{repo}', '.',
        ))

        filenames_out = subprocess.check_output((
            *git, 'ls-files', '-z', '--', '.github/workflows',
        ))
        filenames = set(zsplit(filenames_out))

        for pattern in PATTERNS:
            grep_res = subprocess.run(
                (*git, 'grep', '-E', '-l', '-z', pattern, '--', *filenames),
                stdout=subprocess.PIPE,
            )
            filenames &= set(zsplit(grep_res.stdout))

        rev = subprocess.check_output((*git, 'rev-parse', 'HEAD')).strip()

    return RepoInfo(
        repo=repo,
        rev=rev.decode(),
        filenames=tuple(sorted(filename.decode() for filename in filenames)),
    )


def main() -> int:
    with open(os.path.expanduser('~/.github-auth.json')) as f:
        contents = json.load(f)

    seen = set()

    by_org: Dict[str, List[RepoInfo]] = collections.defaultdict(list)

    for repo_s in _repos(contents['token']):
        if repo_s in seen:
            continue
        else:
            seen.add(repo_s)

        org, _ = repo_s.split('/')
        by_org[org].append(_get_repo_info(repo_s))

    by_org = {k: [r for r in v if r.filenames] for k, v in by_org.items()}
    by_org = {k: v for k, v in sorted(by_org.items()) if v}

    print('<style>td { border: 1px solid black; }</style>')
    print('<table>')
    for org, repos in by_org.items():
        org_rowspan = sum(1 for repo in repos for filename in repo.filenames)
        first_repo = True
        for repo in repos:
            first_filename = True
            for filename in repo.filenames:
                print('<tr>')
                if first_repo:
                    print(f'<td rowspan="{org_rowspan}"><b>{org}</b></td>')
                    first_repo = False
                if first_filename:
                    print(f'<td rowspan="{len(repo.filenames)}">')
                    print(f'<a href="{repo.url}">{repo.repo}</a>')
                    print('</td>')
                    first_filename = False

                print('<td>')
                print(f'<a href="{repo.file_url(filename)}">{filename}</a>')
                print('</td>')
                print('</tr>')

    print('</table>')
    return 0


if __name__ == '__main__':
    exit(main())
