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

    def test_disable(self):
        engine = RealtimeEngine()
        engine.enable()
        engine.disable()
        assert engine.state == RealtimeState.OFF

    def test_disable_clears_candidate(self):
        engine = RealtimeEngine()
        engine.enable()
        from processing.models import CandidateEvent
        engine._active_candidate = CandidateEvent()
        engine.disable()
        assert engine._active_candidate is None
        assert engine.state == RealtimeState.OFF

    def test_update_settings_enables(self):
        engine = RealtimeEngine()
        engine.update_settings(enabled=True)
        assert engine.state == RealtimeState.MONITORING

    def test_update_settings_disables(self):
        engine = RealtimeEngine()
        engine.update_settings(enabled=True)
        engine.update_settings(enabled=False)
        assert engine.state == RealtimeState.OFF

    def test_update_settings_sensitivity(self):
        engine = RealtimeEngine()
        engine.update_settings(sensitivity=0.8)
        assert engine.watcher.frame_diff_threshold < 10.0

    def test_update_settings_cooldown(self):
        engine = RealtimeEngine()
        engine.update_settings(cooldown_sec=5.0)
        assert engine.cooldown_sec == 5.0

    def test_update_settings_verbosity(self):
        engine = RealtimeEngine()
        engine.update_settings(verbosity="detailed")
        assert engine.verbosity == "detailed"

    def test_update_settings_auto_pause(self):
        engine = RealtimeEngine()
        engine.update_settings(auto_pause=True)
        assert engine.helper.auto_pause is True

    def test_debug_info(self):
        engine = RealtimeEngine()
        info = engine.get_debug_info()
        assert info["state"] == "off"
        assert info["timeline_ts"] == 0.0

    def test_debug_mode_records_events(self):
        engine = RealtimeEngine()
        engine.debug_mode = True
        engine._record_debug("test_event", {"key": "value"})
        assert len(engine._debug_log) == 1
        assert engine._debug_log[0]["event"] == "test_event"

    def test_debug_mode_off_no_recording(self):
        engine = RealtimeEngine()
        engine.debug_mode = False
        engine._record_debug("test_event", {"key": "value"})
        assert len(engine._debug_log) == 0

    def test_timeline_starts_at_zero(self):
        engine = RealtimeEngine()
        assert engine.timeline.timeline_ts == 0.0
        assert engine.timeline.last_fingerprints == []

    def test_timeline_resets_on_enable(self):
        engine = RealtimeEngine()
        engine.timeline.advance(100.0, "old_fp")
        engine.enable()
        assert engine.timeline.timeline_ts == 0.0
