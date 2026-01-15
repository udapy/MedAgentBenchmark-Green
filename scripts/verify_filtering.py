
import asyncio
import sys
import os
from unittest.mock import MagicMock, AsyncMock

# Add src to path
# Add project root to path so 'src' module can be found
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from src.agent import Agent, EvalRequest
from a2a.types import Message, TaskState, Part, TextPart

# Mock Tasks
MOCK_TASKS = [
    {"id": "task1", "instruction": "Task 1", "context": "Context 1"},
    {"id": "task2", "instruction": "Task 2", "context": "Context 2"},
    {"id": "task3", "instruction": "Task 3", "context": "Context 3"},
]

async def test_filtering():
    print("Testing Task Filtering...")
    
    # Initialize Agent
    agent = Agent()
    agent.tasks = MOCK_TASKS # Inject mock tasks
    agent.messenger = MagicMock()
    agent.messenger.talk_to_agent = AsyncMock(return_value="FINISH([\"answer\"])")
    agent._ensure_fhir_ready = AsyncMock() # Skip FHIR check
    
    # Mock Updater
    updater = MagicMock()
    updater.reject = AsyncMock()
    updater.update_status = AsyncMock()
    updater.add_artifact = AsyncMock()

    # Case 1: No filter (should pick any)
    print("\nCase 1: No filter")
    req_no_filter = EvalRequest(
        participants={"purple_agent": "http://mock-url"}, 
        config={}
    )
    msg_no_filter = Message(
        kind="message", role="user", 
        parts=[Part(root=TextPart(kind="text", text=req_no_filter.model_dump_json()))],
        message_id="1", context_id="1"
    )
    
    await agent.run(msg_no_filter, updater)
    print("Case 1 run complete")

    # Case 2: Filter task1
    print("\nCase 2: Filter ['task1']")
    req_filter_t1 = EvalRequest(
        participants={"purple_agent": "http://mock-url"}, 
        config={"task_ids": ["task1"]}
    )
    msg_filter_t1 = Message(
        kind="message", role="user", 
        parts=[Part(root=TextPart(kind="text", text=req_filter_t1.model_dump_json()))],
        message_id="2", context_id="2"
    )
    
    await agent.run(msg_filter_t1, updater)
    
    # Verify the payload sent had task1
    call_args = agent.messenger.talk_to_agent.call_args
    if call_args:
        payload_str = call_args[0][0]
        if "Task 1" in payload_str:
             print("SUCCESS: Picked Task 1")
        else:
             print(f"FAILURE: Picked wrong task? Payload: {payload_str}")
    else:
        print("FAILURE: Did not call agent")

    # Case 3: Invalid Filter
    print("\nCase 3: Filter ['invalid']")
    req_invalid = EvalRequest(
        participants={"purple_agent": "http://mock-url"}, 
        config={"task_ids": ["invalid"]}
    )
    msg_invalid = Message(
        kind="message", role="user", 
        parts=[Part(root=TextPart(kind="text", text=req_invalid.model_dump_json()))],
        message_id="3", context_id="3"
    )
    
    await agent.run(msg_invalid, updater)
    
    # Should have called reject
    if updater.reject.called:
        print("SUCCESS: Rejected invalid filter")
        # Check args
        print(f"Reject message: {updater.reject.call_args[0][0]}")
    else:
        print("FAILURE: Did not reject invalid filter")

    # Case 4: Multiple tasks
    print("\nCase 4: Filter ['task1', 'task3']")
    agent.messenger.talk_to_agent.reset_mock() # Reset mock
    
    req_multi = EvalRequest(
        participants={"purple_agent": "http://mock-url"}, 
        config={"task_ids": ["task1", "task3"]}
    )
    msg_multi = Message(
        kind="message", role="user", 
        parts=[Part(root=TextPart(kind="text", text=req_multi.model_dump_json()))],
        message_id="4", context_id="4"
    )
    
    await agent.run(msg_multi, updater)
    
    # Needs to see 2 calls
    call_count = agent.messenger.talk_to_agent.call_count
    if call_count == 2:
        print(f"SUCCESS: Executed {call_count} tasks")
        # Check payload contents
        payloads = [c[0][0] for c in agent.messenger.talk_to_agent.call_args_list]
        has_task1 = any("Task 1" in p for p in payloads)
        has_task3 = any("Task 3" in p for p in payloads)
        
        if has_task1 and has_task3:
             print("SUCCESS: Picked both Task 1 and Task 3")
        else:
             print(f"FAILURE: Did not match expected tasks. Payloads: {payloads}")
    else:
        print(f"FAILURE: Expected 2 calls, got {call_count}")

if __name__ == "__main__":
    asyncio.run(test_filtering())
