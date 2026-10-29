import queue
import threading
import unittest
from unittest.mock import Mock

from backend.native.contracts import WorkspaceError
from backend.v2.provider import CodexAppServer


class ProviderProtocolTests(unittest.TestCase):
    def runtime(self, events):
        runtime = CodexAppServer.__new__(CodexAppServer)
        runtime.thread_id = "fixture-thread"
        runtime.turn_id = None
        runtime.sequence = 0
        runtime.secret = "fixture-secret"
        runtime.pending_inputs = {}
        runtime.events = queue.Queue()
        for event in events:
            runtime.events.put(event)
        runtime.request = Mock(return_value={"turn": {"id": "fixture-turn"}})
        runtime.send = Mock()
        runtime.receive = Mock(
            side_effect=AssertionError("Unexpected extra protocol read")
        )
        return runtime

    def test_stream_forwards_visible_messages_and_ignores_reasoning(self):
        runtime = self.runtime(
            [
                {
                    "method": "item/reasoning/textDelta",
                    "params": {"delta": "private reasoning fixture"},
                },
                {
                    "method": "thread/tokenUsage/updated",
                    "params": {
                        "tokenUsage": {
                            "total": {
                                "inputTokens": 12,
                                "outputTokens": 3,
                                "totalTokens": 15,
                            }
                        }
                    },
                },
                {
                    "method": "account/rateLimits/updated",
                    "params": {
                        "rateLimits": {
                            "primary": {"usedPercent": 14, "windowDurationMins": 300}
                        }
                    },
                },
                {
                    "method": "item/agentMessage/delta",
                    "params": {"itemId": "message", "delta": "Inspected the plate."},
                },
                {
                    "method": "turn/completed",
                    "params": {"turn": {"status": "completed"}},
                },
            ]
        )
        events = []
        message = runtime.run(
            "inspect", "fixture-model", threading.Event(), events.append
        )
        self.assertEqual(message, "Inspected the plate.")
        self.assertNotIn("private reasoning", str(events))
        self.assertEqual(
            [e["kind"] for e in events if e["stage"] == "usage"],
            ["tokens", "allowance"],
        )

    def test_cancellation_interrupts_the_active_turn_and_rejects_completion(self):
        runtime = self.runtime(
            [{"method": "turn/completed", "params": {"turn": {"status": "completed"}}}]
        )
        cancelled = threading.Event()

        def on_progress(event):
            if event["stage"] == "agent_running":
                cancelled.set()

        with self.assertRaises(WorkspaceError) as stopped:
            runtime.run("change", "fixture-model", cancelled, on_progress)
        self.assertEqual(stopped.exception.code, "cancelled")
        runtime.send.assert_called_once()
        self.assertEqual(runtime.send.call_args.args[0]["method"], "turn/interrupt")

    def test_failed_stream_preserves_error_without_exposing_the_access_token(self):
        runtime = self.runtime(
            [
                {
                    "method": "turn/completed",
                    "params": {
                        "turn": {
                            "status": "failed",
                            "error": {"message": "Usage limit reached fixture-secret"},
                        }
                    },
                }
            ]
        )
        with self.assertRaises(WorkspaceError) as failed:
            runtime.run(
                "change", "fixture-model", threading.Event(), lambda event: None
            )
        self.assertIn("Usage limit", str(failed.exception))
        self.assertNotIn("fixture-secret", str(failed.exception))

    def test_foreign_thread_and_old_turn_events_cannot_complete_current_task(self):
        runtime = self.runtime(
            [
                {
                    "method": "item/agentMessage/delta",
                    "params": {"threadId": "other", "delta": "wrong conversation"},
                },
                {
                    "method": "turn/completed",
                    "params": {
                        "threadId": "fixture-thread",
                        "turn": {"id": "old-turn", "status": "failed"},
                    },
                },
                {
                    "method": "item/agentMessage/delta",
                    "params": {
                        "threadId": "fixture-thread",
                        "turnId": "fixture-turn",
                        "delta": "Current result",
                    },
                },
                {
                    "method": "turn/completed",
                    "params": {
                        "threadId": "fixture-thread",
                        "turn": {"id": "fixture-turn", "status": "completed"},
                    },
                },
            ]
        )
        self.assertEqual(
            runtime.run("inspect", "fixture-model", threading.Event(), lambda e: None),
            "Current result",
        )

    def test_structured_usage_limit_stops_without_inventing_geometry_success(self):
        runtime = self.runtime(
            [
                {
                    "method": "turn/completed",
                    "params": {
                        "turn": {
                            "status": "failed",
                            "error": {
                                "message": "provider diagnostic",
                                "codexErrorInfo": "usageLimitExceeded",
                            },
                        }
                    },
                }
            ]
        )
        with self.assertRaises(WorkspaceError) as failed:
            runtime.run("change", "fixture-model", threading.Event(), lambda e: None)
        self.assertEqual(failed.exception.code, "usage_limit")
        self.assertIn("Billing was not changed", str(failed.exception))

    def test_malformed_clarification_answer_does_not_consume_the_pending_question(self):
        runtime = self.runtime([])
        runtime.pending_inputs[7] = [{"id": "dimension", "question": "Thickness?"}]
        with self.assertRaises(WorkspaceError):
            runtime.respond(7, {"wrong": {"answers": ["4 mm"]}})
        self.assertIn(7, runtime.pending_inputs)
        self.assertTrue(
            runtime.respond(7, {"dimension": {"answers": ["4 mm"]}})["answered"]
        )
        self.assertNotIn(7, runtime.pending_inputs)


if __name__ == "__main__":
    unittest.main()
