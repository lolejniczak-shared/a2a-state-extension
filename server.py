import uvicorn
import logging
from fastapi import FastAPI

# Your custom files
from state_injection_a2a_ext import StateInjectionExtension
from executor import ADKA2AExecutorWithRunner

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.types import AgentCard, AgentCapabilities, AgentInterface, AgentSkill
from agent import root_agent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("a2a.server")

# 1. Define the Strict JSON Schema
USER_INFO_SCHEMA = {
    "type": "object",
    "properties": {
        "user_info": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "role": {"type": "string"},
                "email": {"type": "string", "format": "email"}
            },
            "required": ["name", "role", "email"],
            "additionalProperties": False
        }
    },
    "required": ["user_info"]
}

# 2. Initialize Extension with Schema
state_ext = StateInjectionExtension(state_schema=USER_INFO_SCHEMA)

# 4. Initialize the Executor from executor.py
# We pass the extension instance so the executor can call .get_state() and .is_activated()
agent_executor = ADKA2AExecutorWithRunner(agent=root_agent, state_ext=state_ext)

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
        extensions=[state_ext.agent_extension()]
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