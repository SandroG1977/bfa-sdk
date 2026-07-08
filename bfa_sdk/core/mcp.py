import inspect
from typing import Dict, Any, List, Callable
from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

class BFAMCP:
    """
    Wrapper around FastMCP to automatically expose a standard metadata /tools route.
    Tracks custom tags and examples to allow semantic routing of tools in the BFA.
    """
    def __init__(self, name: str, **kwargs):
        self.name = name
        self.mcp = FastMCP(name, **kwargs)
        self.tool_metadata: Dict[str, Dict[str, Any]] = {}
        
        # Register the standard BFA discovery route
        @self.mcp.custom_route("/tools", methods=["GET"])
        async def list_tools_endpoint(request: Request) -> JSONResponse:
            return await self._list_tools_handler()

    @property
    def app(self):
        """
        Exposes the Starlette/ASGI application for uvicorn deployment.
        """
        return self.mcp.http_app()

    def tool(self, name: str = None, description: str = None, tags: List[str] = None, examples: List[str] = None):
        """
        Decorator to register a tool on the MCP instance.
        Stores tags and examples metadata for vector search indexing.
        """
        def decorator(func: Callable):
            tool_name = name or func.__name__
            self.tool_metadata[tool_name] = {
                "tags": tags or [],
                "examples": examples or []
            }
            
            # Register with underlying FastMCP
            mcp_decorator = self.mcp.tool(name=name, description=description)
            mcp_decorator(func)
            return func
        return decorator

    def resource(self, uri: str):
        """
        Exposes the standard FastMCP resource decorator.
        """
        return self.mcp.resource(uri)

    def prompt(self, func: Callable):
        """
        Exposes the standard FastMCP prompt decorator.
        """
        return self.mcp.prompt(func)

    async def _list_tools_handler(self) -> JSONResponse:
        try:
            mcp_tools = await self.mcp.list_tools()
            tools_list = []
            
            for tool in mcp_tools:
                # Extract JSON Schema from the Pydantic input model
                input_schema = {}
                if hasattr(tool, "input_model") and tool.input_model:
                    input_schema = tool.input_model.model_json_schema()
                
                meta = self.tool_metadata.get(tool.name, {"tags": [], "examples": []})
                
                tools_list.append({
                    "name": tool.name,
                    "description": tool.description or "",
                    "inputSchema": input_schema,
                    "annotations": {
                        "tags": meta.get("tags", []),
                        "examples": meta.get("examples", [])
                    }
                })
            return JSONResponse(tools_list)
        except Exception as e:
            return JSONResponse(
                {"error": "Failed to list tools", "details": str(e)}, 
                status_code=500
            )

    async def register_with_gateway(self, gateway_url: str, mcp_url: str) -> bool:
        """
        Dynamically register this MCP server with the BFA Gateway at runtime.
        """
        import httpx
        url = f"{gateway_url.rstrip('/')}/register/mcp"
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, params={"url": mcp_url})
                if response.status_code == 200:
                    print(f"BFAMCP: Successfully registered MCP server '{self.name}' at {gateway_url}")
                    return True
                else:
                    print(f"BFAMCP Error: Registration failed with status {response.status_code}: {response.text}")
                    return False
        except Exception as e:
            print(f"BFAMCP Error: Failed to connect to Gateway at {gateway_url}: {e}")
            return False

