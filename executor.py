import logging
from typing import Any, Union

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import Part, TaskState, Message, Artifact
from uuid import uuid4
from a2a.types import Message, Part, Role, Task, TaskStatus
from a2a.helpers import new_task

from google.adk.runners import Runner
from google.adk.artifacts import InMemoryArtifactService
from google.adk.sessions import InMemorySessionService
from google.adk.memory import InMemoryMemoryService
from google.genai import types
import sys
import json
from a2a.helpers.proto_helpers import new_task_from_user_message

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

        logger.info("Checking if client requested state injection extension")
        if self.state_ext.is_requested(context):
            logger.info(f"Checking if message includes state")
            if self.state_ext.has_state(context.message):
                    logger.info(f"Checking if state JSON has valid schema")
                    if self.state_ext.is_valid_schema(context.message):
                        injected_state = self.state_ext.get_state(context.message)
                    else:
                        logger.error("Metadata state failed schema validation.")


        print("Injected state:")
        print(injected_state)
        # 3. Task Lifecycle Management

        task = new_task_from_user_message(context.message)
        await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        working_message = updater.new_agent_message(
            parts=[Part(text='Processing your question...')]
        )
        await updater.start_work(message=working_message)
        print(f"Current task: {context.current_task}")



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
                        metadata=resp_metadata,
                        extensions = [self.state_ext.URI],
                        last_chunk = True
                    )   ##extension usage is not communicated via response headers, but rather individually on message and artifact (handled by agent executor)
                    await updater.complete()
                    return

                    ##await event_queue.enqueue_event(
                    ##    TaskArtifactUpdateEvent(
                    ##        task_id=context.task_id,
                    ##        context_id=context.context_id,
                    ##        artifact=raw_artifact
                    ##    )
                    ##)

                    ##await event_queue.enqueue_event(
                    ##    TaskStatusUpdateEvent(
                    ##        task_id=context.task_id,
                    ##        context_id=context.context_id,
                    ##        status=TaskStatus(state=TaskState.TASK_STATE_COMPLETED),
                    ##    )
                    ##)
                    ##return

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

            #3await event_queue.enqueue_event(
            ##    TaskStatusUpdateEvent(
            ##        task_id=context.task_id,
            ##       context_id=context.context_id,
            ##        status=TaskStatus(
            ##            state=TaskState.TASK_STATE_FAILED,
            ##            message=Message(role=Role.ROLE_AGENT,
            ##            parts=[Part(text="No response produced.")])
            ##3        ),
            ##    )
            ##)

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
            ##await event_queue.enqueue_event(
            ##    TaskStatusUpdateEvent(
            ##        task_id=context.task_id,
            ##        context_id=context.context_id,
            ##        status=TaskStatus(
            ##            state=TaskState.TASK_STATE_FAILED,
            ##            message=Message(role=Role.ROLE_AGENT, parts=[Part(text=f"Error: {e}")])
            ##        ),
            ##    )
            ##)