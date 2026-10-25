from importlib.metadata import version

from fastapi import FastAPI

# Read the version from the installed package metadata (which comes from
# pyproject.toml), so the version number lives in exactly one place
APP_VERSION = version("inferx")

app = FastAPI(
    title="InferX",
    description=(
        "LLM inference gateway with cost-aware routing, "
        "fault tolerance, and reproducible benchmarks"
    ),
    version=APP_VERSION,
)


@app.get("/health")
def health() -> dict[str, str]:
    """Report that the service is running.

    Load balancers, Docker, and monitoring tools call this endpoint
    to check whether the service is alive.
    """
    return {"status": "ok", "version": APP_VERSION}