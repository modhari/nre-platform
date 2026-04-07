from __future__ import annotations

import os

import uvicorn


def main() -> None:
    lattice_root = os.environ.get("LATTICE_ROOT", "").strip()
    if not lattice_root:
        raise RuntimeError("LATTICE_ROOT must be set before starting the EVPN analysis service")

    uvicorn.run(
        "internal.knowledge.api.evpn_analysis_api:app",
        host="0.0.0.0",
        port=8090,
        reload=False,
    )


if __name__ == "__main__":
    main()
