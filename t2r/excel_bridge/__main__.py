from urllib.parse import urlparse

import uvicorn

from t2r.config import get_settings

if __name__ == "__main__":
    url = urlparse(get_settings().excel_bridge_url)
    uvicorn.run("t2r.excel_bridge.app:app", host="127.0.0.1", port=url.port or 8765)
