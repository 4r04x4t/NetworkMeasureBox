import pathlib
import os


def _get_uuid_file() -> pathlib.Path:
    candidates = [
        pathlib.Path("/var/lib/nmb/.rmbt_client_uuid"),
        pathlib.Path.home() / ".rmbt_client_uuid",
        pathlib.Path("/tmp/.rmbt_client_uuid"),
    ]
    for p in candidates:
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            if p.exists() or os.access(p.parent, os.W_OK):
                return p
        except Exception:
            continue
    return pathlib.Path("/tmp/.rmbt_client_uuid")


def load():
    try:
        f = _get_uuid_file()
        if f.exists():
            v = f.read_text().strip()
            return v if v else None
    except OSError:
        pass
    return None


def save(uuid):
    try:
        f = _get_uuid_file()
        f.write_text(uuid + '\n')
    except OSError:
        pass
