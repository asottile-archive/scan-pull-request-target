import collections
import os.path
from typing import Dict
from typing import Optional
from typing import Tuple

import flask

from scan import File
from scan import Repo
from util import db_connect

app = flask.Flask(__name__)


@app.route('/', methods=['GET'])
def index() -> str:
    with db_connect() as db:
        repos = []

        res = db.execute('SELECT * FROM data ORDER BY repo, filename')

        name, filename, rev, account_type, star_count, checksum = next(res)
        files: Tuple[File, ...] = (File(filename, checksum),)
        repo = Repo(name, rev, account_type, star_count, files)

        for name, filename, rev, account_type, star_count, checksum in res:
            if name == repo.repo:
                files = (*repo.files, File(filename, checksum))
                repo = repo._replace(files=files)
            else:
                repos.append(repo)
                files = (File(filename, checksum),)
                repo = Repo(name, rev, account_type, star_count, files)

        repos.append(repo)
        repos.sort(key=lambda repo: -repo.star_count)

        vulnerable_values: Dict[str, Optional[bool]] = {
            k: bool(v) for k, v in db.execute('SELECT * FROM status')
        }
        vulnerable = collections.defaultdict(lambda: None, vulnerable_values)
        done = {repo for repo, in db.execute('SELECT * FROM done')}

    return flask.render_template(
        'index.html',
        repos=repos,
        vulnerable=vulnerable,
        done=done,
    )


@app.route('/repo/<repo1>/<repo2>', methods=['GET'])
def repo(repo1: str, repo2: str) -> str:
    repo_s = f'{repo1}/{repo2}'

    with db_connect() as db:
        query = 'SELECT * FROM data WHERE repo = ? ORDER BY filename'
        res = db.execute(query, (repo_s,)).fetchall()
        files = tuple(
            File(filename, checksum)
            for _, filename, _, _, _, checksum in res
        )
        name, _, rev, account_type, star_count, _ = next(iter(res))
        repo = Repo(name, rev, account_type, star_count, files)

        vulnerable_values: Dict[str, Optional[bool]] = {
            k: bool(v) for k, v in db.execute('SELECT * FROM status')
        }
        vulnerable = collections.defaultdict(lambda: None, vulnerable_values)
        done = {repo for repo, in db.execute('SELECT * FROM done')}

    def _readfile(file: File) -> str:
        with open(os.path.join('files', repo.repo, repo.rev, file.name)) as f:
            return f.read()

    contents = {file.name: _readfile(file) for file in repo.files}

    return flask.render_template(
        'repo.html',
        repo=repo,
        vulnerable=vulnerable,
        done=done,
        contents=contents,
    )


@app.route('/make-bad/<checksum>', methods=['POST'])
def make_bad(checksum: str) -> Tuple[str, int]:
    with db_connect() as db:
        query = 'INSERT OR REPLACE INTO status VALUES (?, ?)'
        db.execute(query, (checksum, 1))
    return '', 204


@app.route('/make-good/<checksum>', methods=['POST'])
def make_good(checksum: str) -> Tuple[str, int]:
    with db_connect() as db:
        query = 'INSERT OR REPLACE INTO status VALUES (?, ?)'
        db.execute(query, (checksum, 0))
    return '', 204


@app.route('/clear-status/<checksum>', methods=['POST'])
def clear_status(checksum: str) -> Tuple[str, int]:
    with db_connect() as db:
        db.execute('DELETE FROM status WHERE checksum = ?', (checksum,))
    return '', 204


@app.route('/mark-done/<repo1>/<repo2>', methods=['POST'])
def mark_done(repo1: str, repo2: str) -> Tuple[str, int]:
    repo = f'{repo1}/{repo2}'
    with db_connect() as db:
        db.execute('INSERT OR REPLACE INTO done VALUES (?)', (repo,))
    return '', 204


def main() -> int:
    app.run(port=8000, threaded=False)
    return 0


if __name__ == '__main__':
    exit(main())
