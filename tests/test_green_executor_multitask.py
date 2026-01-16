
import pytest
import asyncio
import sys
import os
sys.path.append(os.path.abspath("."))

from unittest.mock import MagicMock, AsyncMock, patch
from a2a.types import Message, TextPart, Part
from a2a.server.tasks import TaskUpdater
from src.a2a_adapter.green_executor import GreenExecutor
from src.a2a_adapter.models import EvalResult

@pytest.mark.asyncio
async def test_execute_multiple_tasks():
    # Mocks
    mock_updater = AsyncMock(spec=TaskUpdater)
    mock_message = MagicMock(spec=Message)
    
    # Mocking get_message_text to return valid JSON request
    with patch("src.a2a_adapter.green_executor.get_message_text") as mock_get_text:
        mock_get_text.return_value = '''
        {
            "participants": {"purple_agent": "http://purple:9000"},
            "config": {
                "task_ids": ["task_a", "task_b"],
                "max_iterations": 5
            }
        }
        '''
        
        executor = GreenExecutor()
        
        # Mock Agent methods
        executor.agent.initialize = AsyncMock()
        
        # Mock select_task to return a dummy task for each ID
        def side_effect_select_task(task_id=None):
            if task_id in ["task_a", "task_b"]:
                return {"id": task_id, "instruction": f"Do {task_id}", "context": "ctx"}
            return None
        
        executor.agent.select_task = MagicMock(side_effect=side_effect_select_task)
        
        # Mock run_assessment to handle multiple calls
        executor.agent.run_assessment = AsyncMock(return_value=EvalResult(
            score=1.0, 
            feedback="Good", 
            task_id="mock_id", 
            metadata={}
        ))
        
        # Action
        await executor.execute(mock_message, mock_updater)
        
        # Verification
        
        # 1. Verify tasks selection
        assert executor.agent.select_task.call_count == 2
        executor.agent.select_task.assert_any_call(task_id="task_a")
        executor.agent.select_task.assert_any_call(task_id="task_b")
        
        # 2. Verify execution calls
        assert executor.agent.run_assessment.call_count == 2
        # Verify call args for first task
        call_args = executor.agent.run_assessment.call_args_list
        assert call_args[0].kwargs['interaction_limit'] == 5
        assert call_args[0].args[0]['id'] == 'task_a'
        
        assert call_args[1].kwargs['interaction_limit'] == 5
        assert call_args[1].args[0]['id'] == 'task_b'
        
        # 3. Verify artifacts
        assert mock_updater.add_artifact.call_count == 3
