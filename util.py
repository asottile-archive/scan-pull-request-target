import contextlib
import json
import os.path
import sqlite3
import urllib.request
from typing import Any
from typing import Dict
from typing import Generator
from typing import NamedTuple
from typing import Optional


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


@contextlib.contextmanager
def db_connect() -> Generator[sqlite3.Connection, None, None]:
    data_table = '''\
        CREATE TABLE IF NOT EXISTS data (
            repo, filename, rev, account_type, star_count,
            PRIMARY KEY (repo, filename)
        )
    '''

    with contextlib.closing(sqlite3.connect('db.db')) as ctx, ctx as db:
        db.execute(data_table)
        yield db


def get_token() -> str:
    with open(os.path.expanduser('~/.github-auth.json')) as f:
        return json.load(f)['token']
