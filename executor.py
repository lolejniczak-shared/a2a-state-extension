import logging
from typing import Any, Union

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

# Import your extension class for type hinting
from state_injection_a2a_ext import StateInjectionExtension
logger = logging.getLogger("a2a.executor.state_injection")
logging.basicConfig(level=logging.INFO)


class ADKA2AExecutorWithRunner(AgentExecutor):
    def __init__(self, agent: Any, state_ext: StateInjectionExtension):
        self.agent = agent
        self.state_ext = state_ext
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
            """
            Implementation of the abstract cancel method.
            For now, we log the request and raise an error or handle cleanup.
            """
            logger.info(f"Cancellation requested for task {context.task_id}")
            
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        self._init_adk()

        print("---------- RAW")
        print(context.call_context)
        print("---------- requested extensions")
        print(context.requested_extensions)
        print("---------- user input")
        print(context.get_user_input())
        if not context.message:
            logger.warning("Execution triggered without a message.")
            return

        # 1. Identity Management
        user_id = "a2a_user" ##context.message.metadata.get('user_id', 'a2a_user')
        
        # 2. State Extraction (Hydration)
        injected_state = {}

        print("Is extension requested: ")
        print(self.state_ext.is_requested(context))
        if self.state_ext.is_requested(context):
            print(f"state extension is requested")
            if self.state_ext.has_state(context.message):
                print(f"message includes state")
                if self.state_ext.is_valid(context.message):
                    print(f"provided state passed schema validation")
                    print(context.message)
                    injected_state = self.state_ext.get_state(context.message)
                    print(injected_state)
                    print(f"Hydrating session {context.context_id} with metadata state.")
                else:
                    logger.error("Metadata state failed schema validation.")

        ##https://github.com/a2aproject/a2a-python/blob/1.0-dev/src/a2a/server/agent_execution/context.py
        context.add_activated_extension(self.state_ext.URI)
        injected_state = self.state_ext.get_state(context.message)

        print("Injected state:")
        print(injected_state)
        # 3. Task Lifecycle Management
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        if not context.current_task:
            await updater.submit()
        await updater.start_work()

        # 4. Prepare ADK Input
        query = context.get_user_input()
        content = types.Content(role='user', parts=[types.Part(text=query)])

        try:
            # 5. Session Retrieval/Creation
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
                    session_id=context.context_id,
                    state=injected_state
                )
            elif injected_state:
                # If session exists but extension provides new state, update it
                # This ensures the 'state-on-the-wire' pattern works turn-by-turn
                session.state.update(injected_state)
                await self.runner.session_service.update_session(session)


            # 6. ADK Execution Loop
            final_event = None
            async for event in self.runner.run_async(
                session_id=session.id,
                user_id=user_id,
                new_message=content
            ):
                if event.is_final_response():
                    final_event = event

            # 7. Response Processing & State Round-Trip
            if final_event and final_event.content and final_event.content.parts:
                response_text = "".join(
                    part.text for part in final_event.content.parts if hasattr(part, 'text') and part.text
                )
                
                if response_text:
                    print(response_text)
                    # Capture updated state from the session service after the run
                    print(self.runner.app_name)
                    print(user_id)
                    print(context.context_id)
                    updated_session = await self.runner.session_service.get_session(
                        app_name = self.runner.app_name, 
                        user_id = user_id, 
                        session_id = context.context_id
                    )
                    
                    # Create the artifact and inject the UPDATED state into its metadata
                    # This allows the client to persist changes made by the agent
                    resp_metadata = {}
                    if updated_session: ##and self.state_ext.is_activated(context):
                        resp_metadata[self.state_ext.STATE_FIELD] = updated_session.state
                    
                    await updater.add_artifact(
                        [Part(text=response_text)],
                        name='result',
                        metadata=resp_metadata
                    )
                    await updater.complete()
                    return

            # Fallback if no response generated
            await updater.update_status(
                TaskState.TASK_STATE_FAILED,
                message="Agent failed to produce a final response."
            )

        except Exception as e:
            logger.exception(f"Critical error in ADK Execution: {e}")
            await updater.update_status(
                TaskState.TASK_STATE_FAILED,
                message=f"Internal Server Error: {str(e)}"
            )