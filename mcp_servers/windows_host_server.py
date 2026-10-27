
"""Read-only MCP tools for Windows host observability."""

from fastmcp import FastMCP
from scripts.windows_host_probe import collect_windows_host_metrics

mcp = FastMCP("Windows Host Observability")


@mcp.tool
def get_windows_host_metrics() -> dict:
    """
    Collect real Windows host CPU, memory and top-process metrics.

    Data source: the Windows host running this MCP server.
    Read-only; does not modify processes or system settings.
    Do not treat these metrics as Docker container metrics.
    """
    return collect_windows_host_metrics()



if __name__ == "__main__":
    import os

    transport = os.getenv(
        "WINDOWS_MCP_TRANSPORT", "stdio"
    ).lower()

    if transport == "http":
        mcp.run(
            transport="http",
            host="127.0.0.1",
            port=8015,
        )
    else:
        mcp.run(transport="stdio")