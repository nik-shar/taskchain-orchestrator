"""Schema-enforcing tool execution gateway with timeout/retry telemetry."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from typing import Any

from agent_orchestrator.tools.registry import ToolSpec, build_registry


class ToolExecutor:
    """Execute registered tools with strict validation and retry/timeout controls."""

    def __init__(
        self,
        *,
        registry: dict[str, ToolSpec] | None = None,
        tool_timeout_s: float = 2.0,
        max_retries: int = 0,
        backoff_s: float = 0.0,
    ) -> None:
        self.registry = registry or build_registry()
        self.tool_timeout_s = tool_timeout_s
        self.max_retries = max_retries
        self.backoff_s = backoff_s

    def execute(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        started_at = time.perf_counter()
        attempts = 0
        final_error = "unknown error"
        implementation = (
            self.registry.get(tool_name).implementation if tool_name in self.registry else "unknown"
        )

        for attempt in range(self.max_retries + 1):
            attempts = attempt + 1
            try:
                output = self._execute_once(tool_name, args)
                return {
                    "tool": tool_name,
                    "status": "ok",
                    "output": output,
                    "implementation": implementation,
                    "attempts": attempts,
                    "duration_ms": _duration_ms(started_at),
                }
            except Exception as exc:  # noqa: BLE001
                final_error = str(exc)
                if attempt < self.max_retries and self.backoff_s > 0:
                    time.sleep(self.backoff_s)

        return {
            "tool": tool_name,
            "status": "failed",
            "error": final_error,
            "implementation": implementation,
            "attempts": attempts,
            "duration_ms": _duration_ms(started_at),
        }

    def _execute_once(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        spec = self.registry.get(tool_name)
        if spec is None:
            raise ValueError(f"Unknown tool: {tool_name}")

        payload = spec.input_model.model_validate(args)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(spec.fn, payload)
            try:
                raw_output = future.result(timeout=self.tool_timeout_s)
            except TimeoutError as exc:
                raise TimeoutError(
                    f"Tool '{tool_name}' timed out after {self.tool_timeout_s:.2f}s"
                ) from exc

        validated_output = spec.output_model.model_validate(raw_output)
        return validated_output.model_dump(mode="json")


def _duration_ms(started_at: float) -> float:
    return round((time.perf_counter() - started_at) * 1000.0, 2)
