import time

from util import db_connect
from util import get_token
from util import req


def main() -> int:
    headers = {'Authorization': f'token {get_token()}'}

    with db_connect() as db:
        query = 'SELECT repo FROM data GROUP BY repo'
        for repo, in db.execute(query).fetchall():
            resp = req(f'https://api.github.com/repos/{repo}', headers=headers)
            db.execute(
                'UPDATE data SET account_type = ?, star_count = ?'
                'WHERE repo = ?',
                (
                    resp.json['owner']['type'],
                    resp.json['stargazers_count'],
                    repo,
                ),
            )
            time.sleep(.25)
            print('.', end='', flush=True)
    print()
    return 0


if __name__ == '__main__':
    exit(main())
