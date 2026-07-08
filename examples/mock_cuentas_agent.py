import uvicorn
from a2a.server.agent_execution.context import RequestContext
from bfa_sdk.core.agent import BFAAgent

class MockCuentasAgent(BFAAgent):
    """
    Mock Accounts Agent subclassing BFAAgent representing cuentas microservice.
    """
    def __init__(self, url: str):
        super().__init__(
            agent_id="cuentas_agent",
            name="Agente de Cuentas",
            description="Expert banking agent for checking, opening, and managing bank accounts and savings accounts.",
            tags=["cuenta", "abrir cuenta", "caja de ahorro", "cuenta corriente", "registro"],
            examples=[
                "quiero abrir una cuenta bancaria", 
                "como abro una caja de ahorro?", 
                "crear cuenta corriente",
                "consultar mi cuenta"
            ],
            url=url
        )

    async def run(self, user_message: str, context: RequestContext) -> str:
        return f"[Cuentas Agent] Recibido pedido sobre cuentas bancarias: '{user_message}'."


# Initialize on port 8002
agent_url = "http://127.0.0.1:8002"
agent = MockCuentasAgent(url=agent_url)
app = agent.app

if __name__ == "__main__":
    print("Starting mock Cuentas Agent server on port 8002...")
    uvicorn.run(app, host="127.0.0.1", port=8002, log_level="info")
