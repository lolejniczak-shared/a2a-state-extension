import logging
from typing import Any, Union
from uuid import uuid4
from a2a.types import Message, Part, Role

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import Part, TaskState, Message, Artifact

from google.adk.runners import Runner
from google.adk.artifacts import InMemoryArtifactService
from google.adk.sessions import InMemorySessionService
from google.adk.memory import InMemoryMemoryService
from google.genai import types
import sys
import json
from a2a.helpers.proto_helpers import new_task_from_user_message


logger = logging.getLogger("a2a.executor.noextension")
logging.basicConfig(level=logging.INFO)

class ADKA2AExecutorWithRunner(AgentExecutor):
    def __init__(self, agent: Any):
        self.agent = agent
        self.runner = None

    def _init_adk(self):
        """Standard ADK Runner initialization."""
        if not self.runner:
            self.runner = Runner(
                app_name=self.agent.name,
                agent=self.agent,
                artifact_service=InMemoryArtifactService(),
                session_service=InMemorySessionService(),
                memory_service=InMemoryMemoryService(),
            )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
            logger.info(f"Cancellation requested for task {context.task_id}")
            
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        self._init_adk()

        # 1. Identity Management
        user_id = "a2a_user" 
        
        # 2. Task Lifecycle Management
        task = new_task_from_user_message(context.message)
        await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        working_message = updater.new_agent_message(
            parts=[Part(text='Processing your question...')]
        )
        await updater.start_work(message=working_message)
        print(f"Current task: {context.current_task}")

        # 3. Prepare ADK Input
        query = context.get_user_input()
        content = types.Content(role='user', parts=[types.Part(text=query)])

        try:
            # 4. Session Retrieval/Creation
            session = await self.runner.session_service.get_session(
                app_name=self.runner.app_name,
                user_id=user_id,
                session_id=context.context_id
            )
            
            if not session:
                logger.info(f"Creating fresh session for {user_id}")
                session = await self.runner.session_service.create_session(
                    app_name=self.runner.app_name,
                    user_id=user_id,
                    session_id=context.context_id
                )

            # 5. ADK Execution Loop
            final_event = None
            async for event in self.runner.run_async(
                session_id=session.id,
                user_id=user_id,
                new_message=content
            ):
                if event.is_final_response():
                    final_event = event

            # 6. Response Processing
            if final_event and final_event.content and final_event.content.parts:
                response_text = "".join(
                    part.text for part in final_event.content.parts if hasattr(part, 'text') and part.text
                )
                
                if response_text:
                    updated_session = await self.runner.session_service.get_session(
                        app_name = self.runner.app_name, 
                        user_id = user_id, 
                        session_id = context.context_id
                    )
                    
                    await updater.add_artifact(
                        [Part(text=response_text)],
                        name='result'
                    )   
                    await updater.complete()
                    return

            # Fallback if no response generated
            msg = Message(
                role=Role.ROLE_AGENT, 
                message_id=str(uuid4()), 
                parts=[Part(text="Agent failed to produce a final response.")]
            )
            await updater.update_status(
                TaskState.TASK_STATE_FAILED,
                message=msg
            )

        except Exception as e:
            logger.exception(f"Critical error in ADK Execution: {e}")
            msg = Message(
                role=Role.ROLE_AGENT, 
                message_id=str(uuid4()), 
                parts=[Part(text=f"Critical error in ADK Execution: {e}")]
            )
            await updater.update_status(
                TaskState.TASK_STATE_FAILED,
                message=msg
            )