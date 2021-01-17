import base64
import os.path
import time
import urllib.error

from util import db_connect
from util import get_token
from util import req


def main() -> int:
    headers = {'Authorization': f'token {get_token()}'}

    with db_connect() as db:
        for repo, filename, rev in db.execute('SELECT * FROM data'):
            dest = os.path.join('files', repo, rev, filename)
            if os.path.exists(dest):
                continue

            try:
                resp = req(
                    f'https://api.github.com/repos/{repo}/contents/{filename}'
                    f'?ref={rev}',
                    headers=headers,
                )
            except urllib.error.URLError as e:
                print()
                print(f'error? {repo} {filename} {rev} {e}')
                continue

            assert resp.json['encoding'] == 'base64', resp.json['encoding']

            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, 'wb') as f:
                f.write(base64.b64decode(resp.json['content']))
            time.sleep(.25)
            print('.', end='', flush=True)
    print()
    return 0


if __name__ == '__main__':
    exit(main())
