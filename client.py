import httpx
import asyncio
import logging
from uuid import uuid4
from a2a.client.client import ClientCallContext
from state_injection_a2a_ext import StateInjectionExtension, StateInjectionClientInterceptor
from a2a.client.client_factory import ClientFactory, ClientConfig
from a2a.types import SendMessageRequest, Message, Role, Task, StreamResponse
import sys
from a2a.types import Message, Part, Role
from typing import Any
from a2a.client.service_parameters import (
    ServiceParametersFactory,
    with_a2a_extensions,
)

logging.basicConfig(level=logging.DEBUG)
from a2a.client.client import ClientCallContext
from a2a.client.interceptors import ClientCallInterceptor, BeforeArgs, AfterArgs

class DebugClientInterceptor(ClientCallInterceptor):
    async def before(
        self,
        args: BeforeArgs
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        print("interceptor before")
        print(args)
        print("**************************")
        print(input)
        print("**************************")

    async def after(
        self,
        args: AfterArgs
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        print("interceptor after")
        print(args)
        print("--------------------------")


async def run_client():
    async with httpx.AsyncClient() as httpx_client:
        # 1. Setup Data
        user_state = {"user_info": {"name": "Lukasz", "role": "AI Specialist", "email": "lolejniczak@google.com"}}
        
        # 2. Setup Extension and Interceptor
        ext = StateInjectionExtension() 
        state_interceptor = StateInjectionClientInterceptor(ext, user_state)
        debug_interceptor = DebugClientInterceptor()

        extensions = [ext.URI]

        service_params = ServiceParametersFactory.create(
            [with_a2a_extensions(extensions)]
        )
        context = ClientCallContext(service_parameters=service_params)
        print(context)
         
        # 3. Create Client
        client = await ClientFactory(
            ClientConfig(httpx_client=httpx_client)
        ).create_from_url(
            url='http://localhost:9999',
            interceptors=[state_interceptor]
        )

        # 4. Send Message
        msg = Message(
            role=Role.ROLE_USER, 
            message_id=str(uuid4()), 
            parts=[Part(text="Who am I and what is my email?")]
        )

        msg.metadata[ext.STATE_FIELD] = user_state
        
        events = [
            event async for event in client.send_message(request=SendMessageRequest(message=msg)) ##, context=context)
        ]
        response = events[0]

        print(response)

        print(response.task.artifacts[0].extensions)
        print(response.task.artifacts[0].parts[0].text)

if __name__ == "__main__":
    asyncio.run(run_client())