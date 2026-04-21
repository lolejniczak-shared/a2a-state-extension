import httpx
import asyncio
import logging
from uuid import uuid4
from a2a.client.client import ClientCallContext
from a2a.client.client_factory import ClientFactory, ClientConfig
from a2a.types import SendMessageRequest, Message, Role, Task, StreamResponse
import sys
from a2a.types import Message, Part, Role
from typing import Any
from a2a.client.service_parameters import (
    ServiceParametersFactory,
    with_a2a_extensions,
)
logger = logging.getLogger("a2a.executor.noextension")
logging.basicConfig(level=logging.DEBUG)
from a2a.client.client import ClientCallContext
from a2a.client.interceptors import ClientCallInterceptor, BeforeArgs, AfterArgs


async def run_client():
    async with httpx.AsyncClient() as httpx_client:
        client = await ClientFactory(
            ClientConfig(httpx_client=httpx_client)
        ).create_from_url(
            url='http://localhost:9999',
            interceptors=[]
        )

        msg = Message(
            role=Role.ROLE_USER, 
            message_id=str(uuid4()), 
            parts=[Part(text="Who am I and what is my email?")]
        )
        
        ## send message
        events = [
            event async for event in client.send_message(request=SendMessageRequest(message=msg))
        ]
        response = events[0]
        print(response)

if __name__ == "__main__":
    asyncio.run(run_client())