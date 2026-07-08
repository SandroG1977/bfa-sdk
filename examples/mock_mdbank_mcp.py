import uvicorn
from bfa_sdk.core.mcp import BFAMCP

# Initialize BFA-managed MCP Server representing MDBank Resources
mcp_server = BFAMCP("MDBank")

@mcp_server.tool(
    name="consultar_cuenta",
    description="Check if a client has an active bank account at MDBank using their CPF.",
    tags=["cuenta", "consultar", "saldo", "estado", "cpf"],
    examples=["verificar si tengo una cuenta activa", "buscar mi cuenta bancaria por CPF", "consultar conta do cliente"]
)
async def consultar_cuenta(cpf: str) -> str:
    # Mock data lookup
    return f"Cuenta activa para CPF: {cpf}. Saldo actual: 1200.50 BRL."


@mcp_server.tool(
    name="consultar_tarjeta",
    description="Query details and credit limits of client credit cards at MDBank using CPF.",
    tags=["tarjeta", "credito", "limite", "plastico", "consultar"],
    examples=["quiero ver mi tarjeta de credito", "consultar limite de tarjeta", "buscar cartao de credito"]
)
async def consultar_tarjeta(cpf: str) -> str:
    return f"Tarjeta de crédito MDBank para CPF: {cpf}. Límite aprobado: 5000.00 BRL."


@mcp_server.tool(
    name="crear_o_buscar_cuenta",
    description="Register a new bank account or retrieve it if the client already exists in MDBank database.",
    tags=["crear", "abrir", "cuenta", "registro", "cliente", "novo"],
    examples=["quiero abrir una cuenta bancaria", "registrarme como cliente nuevo", "abrir conta no banco"]
)
async def crear_o_buscar_cuenta(nombre: str, cpf: str) -> str:
    return f"Cuenta creada con éxito para {nombre} (CPF: {cpf}). Número: 987654."


@mcp_server.tool(
    name="solicitar_tarjeta",
    description="Process request and issuance of a new physical or digital credit card for MDBank accounts.",
    tags=["tarjeta", "solicitar", "emitir", "plastico", "nuevo"],
    examples=["quiero pedir una tarjeta de credito", "solicitar plastico para mi cuenta", "pedir cartao novo"]
)
async def solicitar_tarjeta(cpf: str, tipo: str) -> str:
    return f"Solicitud de tarjeta tipo '{tipo}' procesada correctamente para el CPF: {cpf}."


# Expose Starlette ASGI app for Uvicorn
app = mcp_server.app

if __name__ == "__main__":
    print("Starting mock MDBank MCP server on port 8001...")
    uvicorn.run(app, host="127.0.0.1", port=8001, log_level="info")
