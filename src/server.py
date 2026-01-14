import argparse
import uvicorn

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
)

from executor import Executor


import yaml
import os

def load_config():
    paths = ["config/agent.config.yaml", "../config/agent.config.yaml"]
    for p in paths:
        if os.path.exists(p):
            with open(p, 'r') as f:
                return yaml.safe_load(f)
    return {}

def main():
    config = load_config()
    server_conf = config.get("server", {})
    agent_conf = config.get("agent", {})

    parser = argparse.ArgumentParser(description="Run the A2A agent.")
    parser.add_argument("--host", type=str, default=server_conf.get("host", "127.0.0.1"), help="Host to bind the server")
    parser.add_argument("--port", type=int, default=server_conf.get("port", 9009), help="Port to bind the server")
    parser.add_argument("--card-url", type=str, help="URL to advertise in the agent card")
    args = parser.parse_args()

    # Fill in your agent card
    # See: https://a2a-protocol.org/latest/tutorials/python/3-agent-skills-and-card/
    
    skill = AgentSkill(
        id="medagent-assessor",
        name="MedAgentBench Assessment",
        description="Evaluates agents on clinical tasks using FHIR server",
        tags=["medical", "fhir", "assessment"],
        examples=[]
    )

    agent_card = AgentCard(
        name=agent_conf.get("name", "MedAgentBench Assessor"),
        description=agent_conf.get("description", "Realistic FHIR Environment with 300 Clinical Tasks. 700k+ Patient Records."),
        url=args.card_url or f"http://{args.host}:{args.port}/",
        version=agent_conf.get("version", '1.0.0'),
        default_input_modes=['text'],
        default_output_modes=['text'],
        capabilities=AgentCapabilities(streaming=True, output_schema={
            "score": {"type": "number", "min": 0.0, "max": 1.0},
            "feedback": {"type": "string"},
            "task_id": {"type": "string"}
        }),
        skills=[skill]
    )

    
    # --- Legacy Middleware (ASGI) ---
    import json
    import uuid

    class LegacyASGIMiddleware:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope["type"] == "http" and scope["path"] == "/" and scope["method"] == "POST":
                # Consume the entire body
                body_bytes = b""
                more_body = True
                
                # We need to buffer the original receive stream
                # Note: We must consume it all before processing
                original_receive = receive
                
                while more_body:
                    message = await original_receive()
                    body_bytes += message.get("body", b"")
                    more_body = message.get("more_body", False)
                
                # Check and Transform
                new_body = body_bytes
                try:
                    data = json.loads(body_bytes)
                    # Check if legacy
                    if "message" in data and "jsonrpc" not in data:
                        print(f"Legacy Middleware: Upgrading request to JSON-RPC 2.0")
                        new_payload = {
                            "jsonrpc": "2.0",
                            "method": "message/send",
                            "params": {
                                "message": {
                                    "kind": "message",
                                    "role": "user",
                                    "messageId": str(uuid.uuid4()),
                                    "parts": [{
                                        "kind": "text",
                                        "text": data["message"].get("text", "")
                                    }]
                                }
                            },
                            "id": 1
                        }
                        new_body = json.dumps(new_payload).encode("utf-8")
                except Exception as e:
                    print(f"Legacy Middleware Error: {e}")
                    pass
                
                # Define new receive
                async def new_receive():
                    if hasattr(new_receive, "called"):
                        # Starlette usually stops calling after more_body=False
                        # But if it calls again, we just wait or return disconnect
                        return {"type": "http.disconnect"}
                    
                    new_receive.called = True
                    return {
                        "type": "http.request",
                        "body": new_body,
                        "more_body": False
                    }
                
                await self.app(scope, new_receive, send)
            else:
                await self.app(scope, receive, send)

    request_handler = DefaultRequestHandler(
        agent_executor=Executor(),
        task_store=InMemoryTaskStore(),
    )
    
    app = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=request_handler,
    ).build()
    
    # Add Middleware (Wrap the app)
    app.add_middleware(LegacyASGIMiddleware)
    
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == '__main__':
    main()
