"""Run the Urbanium machine API with Uvicorn."""

import os

import uvicorn

from urbanium.api.server import create_runtime_app


def main() -> None:
    host = os.environ.get("URBANIUM_HOST", "127.0.0.1")
    port = int(os.environ.get("URBANIUM_PORT", "8000"))
    uvicorn.run(create_runtime_app(), host=host, port=port)


if __name__ == "__main__":
    main()
