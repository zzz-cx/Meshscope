"""Fail-fast, same-host cross-process exclusion between complete traffic runs."""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit


@contextmanager
def execution_lease(*urls):
    identities = set()
    for url in urls:
        parsed = urlsplit(url)
        if not parsed.hostname:
            raise ValueError('execution endpoint must have a hostname')
        host = parsed.hostname.lower()
        if host == 'localhost':
            host = '127.0.0.1'
        identities.add('%s:%d' % (host, parsed.port or 80))
    directory = Path(tempfile.gettempdir())/'configpilot-execution-leases'
    directory.mkdir(exist_ok=True)
    opened = []
    try:
        for identity in sorted(identities):
            name = hashlib.sha256(identity.encode()).hexdigest()+'.lock'
            stream = open(directory/name, 'a+b')
            if stream.seek(0, os.SEEK_END) == 0:
                stream.write(b'0')
                stream.flush()
            stream.seek(0)
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                stream.close()
                raise RuntimeError('another local run holds the endpoint/backend; isolate resources or wait') from exc
            opened.append(stream)
        yield
    finally:
        for stream in reversed(opened):
            stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            stream.close()
