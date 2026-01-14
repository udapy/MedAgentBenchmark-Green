import asyncio
import json
import os
import signal
import subprocess
import sys
import time
import uuid

import uvicorn
from fastapi import FastAPI, Request

# --- Mock Purple Agent (FastAPI) ---
purple_app = FastAPI()

@purple_app.post("/")
async def purple_endpoint(request: Request):
    data = await request.json()
    print(f"\n[MockPurple] Received request: {json.dumps(data)}")
    
    # Verify basic structure
    request_id = data.get("id", 1)
    
    # Respond with valid JSON-RPC/A2A Message
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "kind": "message",
            "role": "agent",
            "messageId": str(uuid.uuid4()),
            "contextId": data.get("params", {}).get("message", {}).get("contextId", str(uuid.uuid4())),
            "parts": [{
                "kind": "text",
                "text": "FINISH([\"S6534835\"])"
            }]
        }
    }

# Global config for advertised URL
purple_advertised_url = "http://127.0.0.1:9010/"

@purple_app.get("/.well-known/agent-card.json")
async def purple_card():
    global purple_advertised_url
    return {
        "name": "Mock Purple Agent",
        "description": "Mock agent for E2E testing",
        "version": "1.0.0",
        "skills": [],
        "url": purple_advertised_url,
        "capabilities": {
            "push_notifications": True,
            "history_management": True
        },
        "default_input_modes": ["text"],
        "default_output_modes": ["text", "data"]
    }

async def start_purple_agent(port=9010):
    global purple_server_instance
    # Bind to 0.0.0.0 so it's accessible from Docker via host.docker.internal
    config = uvicorn.Config(purple_app, host="0.0.0.0", port=port, log_level="error")
    server = uvicorn.Server(config)
    purple_server_instance = server
    await server.serve()

# --- Main Verification Logic ---

async def verify_flow():
    # 1. Start Mock Purple Agent in Background
    print("--- Starting Mock Purple Agent on 9010 ---")
    purple_task = asyncio.create_task(start_purple_agent(9010))
    await asyncio.sleep(2) # Warmup

    # 2. Start Green Agent (or use external)
    external_url = os.getenv("EXTERNAL_GREEN_AGENT_URL", "http://localhost:9009")
    green_process = None
    
    # Determine the callback URL for the Purple Agent
    # If using external agent (likely Docker), we need to be reachable from inside Docker
    if external_url:
        print(f"--- Using External Green Agent at {external_url} ---")
        green_url = external_url
        # For Mac/Windows Docker Desktop, host is accessible via host.docker.internal
        # For Linux, it might need --add-host, but we assume Mac based on user info.
        purple_callback_url = "http://host.docker.internal:9010/"
        
        # IMPORTANT: The Agent Card must also advertise this reachable URL
        # because the Green Agent will use the card's 'url' field for the POST request.
        global purple_advertised_url
        purple_advertised_url = purple_callback_url
    else:
        print("--- Starting Green Agent on 9009 ---")
        
        env = os.environ.copy()
        env["PYTHONPATH"] = os.getcwd() # Ensure root is in path
        env["SKIP_FHIR_CHECK"] = "true" 
        
        green_process = subprocess.Popen(
            [sys.executable, "-m", "src.a2a_adapter.server", "--port", "9009"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        green_url = "http://127.0.0.1:9009"
        purple_callback_url = "http://127.0.0.1:9010/"
        
        print("Waiting for Green Agent to be ready...")
        await asyncio.sleep(5)
    
    try:
        # 3. Send Assessment Request
        import aiohttp
        
        # Check Health
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(f"{green_url}/.well-known/agent-card.json") as resp:
                    if resp.status != 200:
                        print(f"[FAIL] Green Agent unhealthy: {resp.status}")
                        return
                    print("[PASS] Green Agent Health Check OK")
            except Exception as e:
                print(f"[FAIL] Green Agent unreachable: {e}")
                return

            # Construct Payload
            # A2A Message/Send Request
            payload = {
                "jsonrpc": "2.0",
                "method": "message/send",
                "params": {
                    "message": {
                        "kind": "message",
                        "role": "user",
                        "messageId": str(uuid.uuid4()),
                        "parts": [{
                            "kind": "text",
                            "text": json.dumps({
                                "participants": {
                                    "purple_agent": purple_callback_url
                                },
                                "config": {
                                    "force_task_id": "task1_1" # Use a known ID if possible, or omit
                                }
                            })
                        }]
                    }
                },
                "id": 1
            }
            
            print("--- Sending Assessment Request ---")
            async with session.post(green_url, json=payload) as resp:
                print(f"Request sent. Status: {resp.status}")
                # We don't necessarily get the result immediately in the HTTP response if async,
                # but A2A often returns 200 OK for acceptance.
                
            # 4. Monitor Output
            # We need to verify:
            # 1. Purple Agent got hit (We log it)
            # 2. Green Agent produced logs/artifacts (We read stdout)
            
            print("--- Monitoring Logs for 10 seconds ---")
            start_time = time.time()
            success_criteria = {
                "purple_hit": False,
                "grading_started": False,
                "artifact_created": False
            }
            
            # Non-blocking read of stdout is tricky in python slightly.
            # We'll simple poll or just wait.
            # Let's verify via the mock agent's print (which goes to this stdout).
            # Wait... subprocess stdout is piped. We need to read it.
            # For this simple script, we just sleep.
            await asyncio.sleep(10)
            
    finally:
        # Clean up
        print("\n--- Teardown ---")
        if green_process:
            green_process.terminate()
            # Read whatever logs existing
            outs, errs = green_process.communicate(timeout=5)
            print("GREEN AGENT LOGS:\n", outs)
            if errs:
                 print("GREEN AGENT ERRORS:\n", errs)
            
            # Check success in logs
            combined_logs = (outs or "") + (errs or "")
            
            if "Grading response..." in combined_logs:
                print("\n[PASS] Green Agent started grading")
            else:
                 print("\n[FAIL] Grading log not found. Logs checked.")
                 
            if "Score: 1.0" in combined_logs:
                print("\n[PASS] Score: 1.0 Achieved")
            else:
                print("\n[FAIL] Score 1.0 not found in logs.")
        else:
            print("External Mock Agent used. Check container logs manually for details if needed.")
            # For external agent, we can't check logs automatically unless we fetch them via docker API (too complex).
            # We assume if the HTTP Request succeeded (Status 200) and we got here, it's mostly good, 
            # BUT we can't verifying grading started/Result Score 1.0 easily without log access.
            pass

        # Graceful shutdown of Purple Agent
        if purple_server_instance:
            purple_server_instance.should_exit = True
            await purple_task
        if green_process and outs and "MedAgentBench Assessment" in outs: 
             # Rough check for artifact content or logging of it
             # The server usually implies artifact creation if task succeeds.
             # We can assume if "Grading response..." appeared and no exception followed, it worked.
             pass

if __name__ == "__main__":
    try:
        asyncio.run(verify_flow())
    except KeyboardInterrupt:
        pass
