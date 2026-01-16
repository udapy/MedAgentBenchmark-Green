
import os
import uvicorn
import logging
import asyncio
from fastapi import FastAPI
from typing import Any

from a2a.server.apps.jsonrpc import A2AFastAPIApplication
from a2a.server.request_handlers.default_request_handler import DefaultRequestHandler
from a2a.server.tasks.inmemory_task_store import InMemoryTaskStore
from a2a.server.events.in_memory_queue_manager import InMemoryQueueManager
from a2a.server.agent_execution.agent_executor import AgentExecutor
from a2a.server.agent_execution.simple_request_context_builder import SimpleRequestContextBuilder
from a2a.server.tasks.task_updater import TaskUpdater
from a2a.types import AgentCard, TaskState
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events.event_queue import EventQueue

from src.a2a_adapter.green_executor import GreenExecutor

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("a2a_server")

class GreenAgentExecutorAdapter(AgentExecutor):
    """Adapts GreenExecutor to A2A AgentExecutor interface."""
    def __init__(self, green_executor: GreenExecutor):
        self.green_executor = green_executor

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        message = context.message
        if not message:
            logger.error("No message in context")
            return

        updater = TaskUpdater(
            event_queue=event_queue,
            task_id=context.task_id,
            context_id=context.context_id
        )
        
        # Determine strict or normal start?
        # A2A SDK handles initial task creation via DefaultRequestHandler
        # We just run logic.
        try:
            await self.green_executor.execute(message, updater)
        except Exception as e:
            logger.exception("Execution failed")
            await updater.failed()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        logger.info(f"Cancellation requested for task {context.task_id}")
        updater = TaskUpdater(
            event_queue=event_queue,
            task_id=context.task_id,
            context_id=context.context_id
        )
        await updater.cancel()

def create_server(host="0.0.0.0", port=8000, card_url=None):
    executor = GreenExecutor()
    adapter = GreenAgentExecutorAdapter(executor)
    
    task_store = InMemoryTaskStore()
    queue_manager = InMemoryQueueManager()
    context_builder = SimpleRequestContextBuilder()
    
    request_handler = DefaultRequestHandler(
        task_store=task_store,
        queue_manager=queue_manager,
        agent_executor=adapter,
        request_context_builder=context_builder
    )
    
    from a2a.types import AgentCapabilities, AgentSkill
    
    skill = AgentSkill(
        id="medagent-assessor",
        name="MedAgentBench Assessment",
        description="Evaluates agents on clinical tasks using FHIR server",
        tags=["medical", "fhir", "assessment"],
        examples=[]
    )

    agent_card = AgentCard(
        name="MedAgentBench-Green",
        description="A2A Green Agent for Medical Agent Benchmark",
        version="0.1.0",
        url=card_url or f"http://{host}:{port}/",
        capabilities=AgentCapabilities(
            push_notifications=True,
            history_management=True,
            streaming=True # ENABLED STREAMING FOR TIMEOUT FIX
        ),
        default_input_modes=["text"],
        default_output_modes=["text", "data"],
        skills=[skill]
    )
    
    app_builder = A2AFastAPIApplication(
        agent_card=agent_card,
        http_handler=request_handler
    )
    
    return app_builder.build()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--card-url", default=None)
    
    args = parser.parse_args()
    
    # Allow env var override
    host = os.getenv("HOST", args.host)
    port = int(os.getenv("PORT", args.port))
    card_url = os.getenv("CARD_URL", args.card_url)
    
    logger.info(f"Starting A2A Server on {host}:{port}")
    uvicorn.run(
        create_server(host, port, card_url), 
        host=host, 
        port=port
    )
