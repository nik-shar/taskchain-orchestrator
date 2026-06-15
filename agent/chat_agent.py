# Backward compatibility shim — all imports redirect to onboarding_agent.py
#
# This file exists so that any stale imports (e.g., from cached modules,
# external scripts, or test utilities) continue to work after the rename.
# New code should import from agent.onboarding_agent directly.

from agent.onboarding_agent import OnboardingAgent as CompiledGraphStub
from agent.onboarding_agent import get_onboarding_agent as get_chat_agent
from agent.onboarding_agent import (
    prune_old_tool_results,
    parse_all_tool_calls,
    has_final_answer,
    compress_conversation_for_loop,
    run_tools_parallel,
    classify_intent,
)
