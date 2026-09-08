# agent/__main__.py - Entrypoint when running `python -m agent.main`

from agent.config import config

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "agent.main:app",
        host=config.app.host,
        port=config.app.port,
        reload=config.app.reload,
    )
