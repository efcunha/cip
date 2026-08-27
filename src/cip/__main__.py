"""Entrypoint `python -m cip` — lança o MCP Server (stdio).

Invocação preferencial explícita: `python -m cip.mcp_server`
Este arquivo é apenas um atalho de conveniência.
"""

from cip.mcp_server import main

if __name__ == "__main__":
    main()
