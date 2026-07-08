import uvicorn
from a2a.server.agent_execution.context import RequestContext
from bfa_sdk.core.agent import BFAAgent

class MockTarjetasAgent(BFAAgent):
    """
    Mock Credit Cards Agent subclassing BFAAgent representing tarjetas microservice.
    """
    def __init__(self, url: str):
        super().__init__(
            agent_id="tarjetas_agent",
            name="Agente de Tarjetas",
            description="Expert banking agent that processes credit card issuance, limit checks, and physical plastic requests.",
            tags=["tarjeta", "credito", "plastico", "limite", "solicitar tarjeta"],
            examples=[
                "quiero pedir una tarjeta de credito", 
                "cual es mi limite de tarjeta?", 
                "solicitar un plastico",
                "quiero una de credito gold o black"
            ],
            url=url
        )

    async def run(self, user_message: str, context: RequestContext) -> str:
        return f"[Tarjetas Agent] Recibido pedido sobre tarjetas de crédito: '{user_message}'."


# Initialize on port 8003
agent_url = "http://127.0.0.1:8003"
agent = MockTarjetasAgent(url=agent_url)
app = agent.app

if __name__ == "__main__":
    print("Starting mock Tarjetas Agent server on port 8003...")
    uvicorn.run(app, host="127.0.0.1", port=8003, log_level="info")
