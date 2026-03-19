import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from processing.models import RealtimeState
from processing.realtime import RealtimeEngine


class TestRealtimeEngine:
    def test_initial_state_off(self):
        engine = RealtimeEngine()
        assert engine.state == RealtimeState.OFF

    def test_enable(self):
        engine = RealtimeEngine()
        engine.enable()
        assert engine.state == RealtimeState.MONITORING
        assert engine._timer_start > 0

    def test_disable(self):
        engine = RealtimeEngine()
        engine.enable()
        engine.disable()
        assert engine.state == RealtimeState.OFF

    def test_disable_clears_llm_state(self):
        engine = RealtimeEngine()
        engine.enable()
        engine.disable()
        assert engine._llm_task is None
        assert engine._llm_result is None
        assert engine._llm_segment is None

    def test_update_settings_enable(self):
        engine = RealtimeEngine()
        engine.update_settings(enabled=True)
        assert engine.state == RealtimeState.MONITORING

    def test_update_settings_disable(self):
        engine = RealtimeEngine()
        engine.update_settings(enabled=True)
        engine.update_settings(enabled=False)
        assert engine.state == RealtimeState.OFF

    def test_narration_interval_from_cooldown(self):
        engine = RealtimeEngine()
        engine.update_settings(cooldown_sec=20.0)
        assert engine.narration_interval == 20.0

    def test_debug_info(self):
        engine = RealtimeEngine()
        engine.enable()
        info = engine.get_debug_info()
        assert info["state"] == "monitoring"
        assert "timer_elapsed" in info
        assert "narration_interval" in info
        assert "llm_pending" in info

    def test_reset_timer(self):
        engine = RealtimeEngine()
        engine._timer_start = 100.0
        engine._reset_timer()
        assert engine._timer_start > 100.0
