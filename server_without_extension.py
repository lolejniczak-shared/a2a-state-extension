import uvicorn
import logging
from fastapi import FastAPI

from executor_without_extension import ADKA2AExecutorWithRunner

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.types import AgentCard, AgentCapabilities, AgentInterface, AgentSkill
from agent import root_agent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("a2a.executor.noextension")

agent_executor = ADKA2AExecutorWithRunner(agent=root_agent)

# 5. Define the Agent Card
agent_card = AgentCard(
    name='ADK Specialist Agent',
    description='Professional Agent with State Injection',
    supported_interfaces=[
        AgentInterface(
            url="http://localhost:9999/a2a/jsonrpc", 
            protocol_binding="JSONRPC"
        )
    ],
    capabilities=AgentCapabilities(
        extensions=[]
    ),
    skills=[AgentSkill(id='specialist', name='AI Specialist Support')],
    version="1.0.0",
)

# 6. Setup Request Handler
request_handler = DefaultRequestHandler(
    agent_card=agent_card,
    agent_executor=agent_executor,
    task_store=InMemoryTaskStore(),
)

# 7. Initialize FastAPI and mount routes
app = FastAPI(title="A2A ADK Specialist Server")

app.routes.extend(create_agent_card_routes(agent_card))
app.routes.extend(create_jsonrpc_routes(request_handler, '/a2a/jsonrpc'))

if __name__ == "__main__":
    logger.info("Starting A2A Server on port 9999...")
    uvicorn.run(app, host="0.0.0.0", port=9999)