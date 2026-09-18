import io
import zipfile
from pathlib import Path
from urllib.request import urlopen

import pandas as pd

from ml_platform.core.io import digest
from ml_platform.data.validation import validate_frame

SOURCE_URL = "https://archive.ics.uci.edu/static/public/350/default+of+credit+card+clients.zip"
SOURCE_PAGE = "https://archive.ics.uci.edu/dataset/350/default+of+credit+card+clients"
MAX_DOWNLOAD_BYTES = 20_000_000


def download(destination: Path, expected_sha256: str | None = None) -> Path:
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Fixed trusted source URL; no arbitrary URL or archive extraction supported.
        with urlopen(SOURCE_URL, timeout=60) as response:
            content = response.read(MAX_DOWNLOAD_BYTES + 1)
        if len(content) > MAX_DOWNLOAD_BYTES:
            raise ValueError("Download exceeds size limit")
        temporary = destination.with_suffix(".download")
        temporary.write_bytes(content)
        if expected_sha256 and digest(temporary) != expected_sha256:
            temporary.unlink()
            raise ValueError("Source checksum mismatch")
        temporary.replace(destination)
    if expected_sha256 and digest(destination) != expected_sha256:
        raise ValueError("Source checksum mismatch")
    return destination


def read_source(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        # Explicit canonical import route for new data; no synthetic fallback.
        frame = pd.read_csv(path)
    elif path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            members = [i for i in archive.infolist() if i.filename.lower().endswith(".xls")]
            if len(members) != 1 or members[0].file_size > MAX_DOWNLOAD_BYTES:
                raise ValueError("Expected one bounded UCI XLS workbook")
            frame = pd.read_excel(io.BytesIO(archive.read(members[0])), header=1, engine="xlrd")
        frame.columns = [str(c).strip().lower() for c in frame.columns]
        frame = frame.rename(columns={"id": "customer_id", "default payment next month": "default"})
    else:
        raise ValueError("Expected canonical CSV or UCI ZIP")
    validate_frame(frame)
    return frame.sort_values("customer_id").reset_index(drop=True)
