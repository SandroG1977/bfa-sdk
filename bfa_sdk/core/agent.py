import abc
from typing import List, Dict, Any
from starlette.applications import Starlette
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.types import AgentCapabilities, AgentCard, AgentSkill, AgentInterface
from a2a.server.agent_execution import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.helpers import new_text_message
from a2a.types import Role

class BFAAgentExecutor(AgentExecutor):
    """
    Internal executor that maps standard A2A execution to BFAAgent's run method.
    """
    def __init__(self, agent_instance):
        super().__init__()
        self.agent_instance = agent_instance

    async def execute(self, context: RequestContext, event_queue: EventQueue):
        try:
            user_input = context.get_user_input()
            # Run the concrete agent logic
            response_text = await self.agent_instance.run(user_input, context=context)
            # Enqueue response as a text message
            await event_queue.enqueue_event(
                new_text_message(str(response_text), role=Role.ROLE_AGENT)
            )
        except Exception as e:
            await event_queue.enqueue_event(
                new_text_message(f"Error in Agent execution: {str(e)}", role=Role.ROLE_AGENT)
            )

    async def cancel(self, context: RequestContext, event_queue: EventQueue):
        pass


class BFAAgent(abc.ABC):
    """
    Abstract Base Class for BFA Agents.
    Inheriting from this class automatically configures an A2A server.
    Developers only need to implement the async run() method.
    """
    def __init__(
        self,
        agent_id: str,
        name: str,
        description: str,
        tags: List[str],
        examples: List[str],
        url: str,
        version: str = "1.0.0"
    ):
        self.agent_id = agent_id
        self.name = name
        self.description = description
        self.tags = tags
        self.examples = examples
        self.url = url
        self.version = version

        # Create default A2A skill representing this agent
        self.skill = AgentSkill(
            id=self.agent_id,
            name=self.name,
            description=self.description,
            tags=self.tags,
            examples=self.examples
        )

        # Create AgentCard representation for BFA Discovery
        self.agent_card = AgentCard(
            name=self.name,
            description=self.description,
            default_input_modes=["text"],
            default_output_modes=["text"],
            skills=[self.skill],
            version=self.version,
            capabilities=AgentCapabilities(streaming=True),
            supported_interfaces=[
                AgentInterface(
                    protocol_binding="JSONRPC",
                    url=self.url,
                )
            ]
        )

        self.task_store = InMemoryTaskStore()
        self.executor = BFAAgentExecutor(self)
        self.http_handler = DefaultRequestHandler(
            agent_executor=self.executor,
            task_store=self.task_store,
            agent_card=self.agent_card
        )

        # Setup standard routes
        routes = []
        routes.extend(create_agent_card_routes(self.agent_card))
        routes.extend(create_jsonrpc_routes(request_handler=self.http_handler, rpc_url="/"))
        self.app = Starlette(routes=routes)

    @abc.abstractmethod
    async def run(self, user_message: str, context: RequestContext) -> str:
        """
        Process the user message and return the agent's response.
        Must be implemented by subclasses.
        """
        pass

    async def register_with_gateway(self, gateway_url: str) -> bool:
        """
        Dynamically register this agent with the BFA Gateway at runtime.
        """
        import httpx
        url = f"{gateway_url.rstrip('/')}/register/agent"
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, params={"url": self.url})
                if response.status_code == 200:
                    print(f"BFAAgent: Successfully registered agent '{self.agent_id}' at {gateway_url}")
                    return True
                else:
                    print(f"BFAAgent Error: Registration failed with status {response.status_code}: {response.text}")
                    return False
        except Exception as e:
            print(f"BFAAgent Error: Failed to connect to Gateway at {gateway_url}: {e}")
            return False

