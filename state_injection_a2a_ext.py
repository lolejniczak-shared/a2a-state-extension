import json
import jsonschema
from typing import Any, Tuple
from typing import Union
from a2a.types import AgentExtension
from a2a.types import AgentCapabilities, AgentCard, AgentSkill, AgentInterface
from a2a.extensions.common import find_extension_by_uri
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.types import AgentExtension, AgentCard, Message, Artifact
import logging
from a2a.client.interceptors import ClientCallInterceptor, BeforeArgs, AfterArgs
from a2a.extensions.common import HTTP_EXTENSION_HEADER
from a2a.types import SendMessageRequest
from google.protobuf.json_format import MessageToDict
from google.protobuf.struct_pb2 import Struct
import sys
from google.protobuf.json_format import MessageToDict
from a2a.client.service_parameters import (
    ServiceParametersFactory,
    with_a2a_extensions,
)
from a2a.client.client import ClientCallContext
logger = logging.getLogger("a2a.extension.state_injection")

class StateInjectionExtension:
        def __init__(self, state_schema: str | dict | None = None):
            self.CORE_PATH = 'github.com/lolejniczak-shared/a2a-samples/extensions/state_injection/v1'
            self.URI = f'https://{self.CORE_PATH}'
            self.STATE_FIELD = f'{self.CORE_PATH}/state'

            # Store as dict for internal validation speed, but accept string for flexibility
            if isinstance(state_schema, str):
                try:
                    self.state_schema = json.loads(state_schema)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse state_schema JSON: {e}")
                    self.state_schema = None
            else:
                self.state_schema = state_schema

        ## 1. we need to make sure A2A agent adds this extensions its AgentCard
        def agent_extension(self) -> AgentExtension:
                """Get the AgentExtension representing this extension."""
                return AgentExtension(
                            uri=self.URI,
                            description='Injects state into message metadata for ADK state synchronization.',
                            params={"state_schema": self.state_schema} if self.state_schema else {},
                            required=True 
                        )

        def add_to_card(self, card: AgentCard) -> AgentCard:
            """Add this extension to an AgentCard."""
            if not card.capabilities.extensions:
               card.capabilities.extensions = []

            if not self.is_supported(card):
                card.capabilities.extensions.append(self.agent_extension(self.state_schema))
                logger.info(f"Extension {self.URI} successfully added to AgentCard.")
            return card

        def is_supported(self, card: AgentCard | None) -> bool:
            """Returns whether this extension is supported by the AgentCard."""
            return find_extension_by_uri(card, self.URI) is not None if card else False
        

        ## 2. we need some helper that will check if extension is acrivated by A2A Client 
        def is_requested(self, context: RequestContext) -> bool:
            requested = self.URI in context.requested_extensions
            if requested:
                print(f"Extension {self.URI} requested for request {getattr(context, 'request_id', 'N/A')}")
            else:
                print(f"There is no {self.URI} on the list")
            return requested


        
        ## 3. the core of this extension is function that adds state object to Message or Artifact metadata
        def has_state(self, o: Message | Artifact) -> bool:
            """Returns whether a message or artifact has state."""
            return bool(o.metadata and self.STATE_FIELD in o.metadata)
        
        def is_valid_schema(self, o: Message | Artifact) -> bool:
            """
            Validates the state object within metadata against the extension's schema.
            """
            if not self.has_state(o):
                return False
            
            if not self.state_schema:
                logger.warning(f"Validation skipped for {self.URI}: No schema defined in extension.")
                return True
                
            try:
                raw_state = o.metadata[self.STATE_FIELD]
                state_data = MessageToDict(raw_state)
                jsonschema.validate(instance=state_data, schema=self.state_schema)
                return True
            except jsonschema.ValidationError as e:
                logger.error(f"Schema validation failed for {self.URI}: {e.message} at {list(e.path)}")
                return False
            except Exception as e:
                logger.exception(f"Unexpected error during schema validation: {e}")
                return False
        
        def add_state(self, o: Message | Artifact, state_dict = {}) -> None:
            """Injects the state into the metadata field."""
            if o.metadata is None:
                o.metadata = {}
            if self.has_state(o): 
                logger.debug(f"State already exists on {type(o).__name__}, skipping injection.")
                return
            o.metadata[self.STATE_FIELD] = state_dict if state_dict is not None else {}
            logger.info(f"Successfully injected state into {type(o).__name__} metadata.")
        
        def get_state(self, o: Union[Message, Artifact]) -> dict :
            """Helper to extract the state if it exists."""
            if self.has_state(o):
                val = o.metadata[self.STATE_FIELD]
                m = MessageToDict(val)
                if isinstance(m, dict):
                    return m
                logger.warning(f"Expected dict in {self.STATE_FIELD}, found {type(val).__name__}.")
            return {}
        


class StateInjectionClientInterceptor(ClientCallInterceptor):
    def __init__(self, extension: Any, state_data: dict):
        self.extension = extension
        self.state_data = state_data

    async def before(self, args: BeforeArgs) -> Tuple[Any, Any]:
        uri = self.extension.URI
        field = self.extension.STATE_FIELD
    
        logger.info(f"Interceptor activating extension via context: {uri}")

        ## Adding service parameters
        extensions = [uri]
        service_params = ServiceParametersFactory.create(
            [with_a2a_extensions(extensions)]
        )
        ctx = ClientCallContext(service_parameters=service_params) 
        args.context = ctx


        request = None
        if isinstance(args.input, dict):
            request = args.input.get('request')
        elif hasattr(args.input, 'message'):
            request = args.input
        
        if request and hasattr(request, 'message') and request.message:
            msg = request.message
            if msg.metadata is None:
                msg.metadata = {}
            ## Adding metadata 
            msg.metadata[field] = self.state_data
            logger.debug(f"Injected state into message metadata: {field}")
        else:
            logger.warning("Interceptor could not find message in args.input to inject state.")

        # Return the modified input and early_return per 1.0-dev dataclass
        return args.input, args.context

    async def after(self, args: AfterArgs) -> Tuple[Any, bool]:
        """Satisfy abstract method."""
        return args.result, args.context