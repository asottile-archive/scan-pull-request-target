import hashlib
import os.path

from util import db_connect


def main() -> int:
    with db_connect() as db:
        query = 'SELECT repo, filename, rev FROM data'
        for repo, filename, rev in db.execute(query):
            with open(os.path.join('files', repo, rev, filename), 'rb') as f:
                checksum = hashlib.sha256(f.read()).hexdigest()

            db.execute(
                'UPDATE data SET checksum = ? WHERE repo = ? AND filename = ?',
                (checksum, repo, filename),
            )
            print('.', end='', flush=True)
    print()
    return 0


if __name__ == '__main__':
    exit(main())
