import globalPluginHandler
import ui
import wx
import gui
import addonHandler
from logHandler import log
import urllib.request
import urllib.error
import json
import threading
import config
import speech

addonHandler.initTranslation()

class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    scriptCategory = "Neurovox"
    
    config.conf.spec["neurovox"] = {
        "api_key": "string(default='')",
        "model": "string(default='gemini-1.5-flash')",
        "realtime_auto_pause": "boolean(default=False)",
        "realtime_auto_unpause": "boolean(default=True)",
        "realtime_cooldown_sec": "integer(default=15)",
        "realtime_verbosity": "string(default='concise')"
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.server_url = "http://127.0.0.1:8000"
        
        self.api_key = config.conf["neurovox"]["api_key"]
        self.model = config.conf["neurovox"]["model"]
        
        self.realtime_enabled = False
        self.realtime_auto_pause = config.conf["neurovox"]["realtime_auto_pause"]
        self.realtime_auto_unpause = config.conf["neurovox"]["realtime_auto_unpause"]
        self.realtime_cooldown_sec = config.conf["neurovox"]["realtime_cooldown_sec"]
        self.realtime_verbosity = config.conf["neurovox"]["realtime_verbosity"]
        
        self.realtime_thread_active = False
        
        self.createMenu()
        
        if self.api_key or self.model:
            self.pushSettings()
        
        self._pushRealtimeState()
        
        if self.realtime_enabled:
            self.startRealtimePoller()

    def createMenu(self):
        self.prefsMenu = gui.mainFrame.sysTrayIcon.preferencesMenu
        self.settingsMenuItem = self.prefsMenu.Append(wx.ID_ANY, "Neurovox API Settings")
        gui.mainFrame.sysTrayIcon.Bind(wx.EVT_MENU, self.onSettingsDialog, self.settingsMenuItem)

    def onSettingsDialog(self, evt):
        dialog = wx.Dialog(gui.mainFrame, title="Neurovox Settings")
        mainSizer = wx.BoxSizer(wx.VERTICAL)
        
        keySizer = wx.BoxSizer(wx.HORIZONTAL)
        keyLabel = wx.StaticText(dialog, label="Gemini API Key:")
        self.keyText = wx.TextCtrl(dialog, value=self.api_key, size=(300, -1))
        keySizer.Add(keyLabel, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
        keySizer.Add(self.keyText, 1, wx.ALL | wx.EXPAND, 5)
        mainSizer.Add(keySizer, 0, wx.EXPAND)
        
        modelSizer = wx.BoxSizer(wx.HORIZONTAL)
        modelLabel = wx.StaticText(dialog, label="Gemini Model:")
        self.modelText = wx.TextCtrl(dialog, value=self.model, size=(300, -1))
        modelSizer.Add(modelLabel, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
        modelSizer.Add(self.modelText, 1, wx.ALL | wx.EXPAND, 5)
        mainSizer.Add(modelSizer, 0, wx.EXPAND)
        
        self.rtAutoPauseCb = wx.CheckBox(dialog, label="Auto-pause media")
        self.rtAutoPauseCb.SetValue(self.realtime_auto_pause)
        mainSizer.Add(self.rtAutoPauseCb, 0, wx.ALL, 5)
        
        self.rtAutoUnpauseCb = wx.CheckBox(dialog, label="Auto-unpause media")
        self.rtAutoUnpauseCb.SetValue(self.realtime_auto_unpause)
        mainSizer.Add(self.rtAutoUnpauseCb, 0, wx.ALL, 5)
        
        cdSizer = wx.BoxSizer(wx.HORIZONTAL)
        cdLabel = wx.StaticText(dialog, label="Realtime Cooldown (sec):")
        self.rtCooldownText = wx.TextCtrl(dialog, value=str(self.realtime_cooldown_sec), size=(100, -1))
        cdSizer.Add(cdLabel, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
        cdSizer.Add(self.rtCooldownText, 1, wx.ALL, 5)
        mainSizer.Add(cdSizer, 0, wx.EXPAND)
        
        buttonSizer = dialog.CreateButtonSizer(wx.OK | wx.CANCEL)
        mainSizer.Add(buttonSizer, 0, wx.ALL | wx.ALIGN_RIGHT, 5)
        
        dialog.SetSizerAndFit(mainSizer)
        
        if dialog.ShowModal() == wx.ID_OK:
            new_key = self.keyText.GetValue()
            new_model = self.modelText.GetValue()
            new_rt_auto_pause = self.rtAutoPauseCb.GetValue()
            new_rt_auto_unpause = self.rtAutoUnpauseCb.GetValue()
            try:
                new_rt_cooldown = int(self.rtCooldownText.GetValue())
            except ValueError:
                new_rt_cooldown = 15
            
            self.api_key = new_key
            self.model = new_model
            
            config.conf["neurovox"]["api_key"] = new_key
            config.conf["neurovox"]["model"] = new_model
            
            self.pushSettings()
            
            if new_rt_auto_pause != self.realtime_auto_pause or new_rt_auto_unpause != self.realtime_auto_unpause or new_rt_cooldown != self.realtime_cooldown_sec:
                self.realtime_auto_pause = new_rt_auto_pause
                self.realtime_auto_unpause = new_rt_auto_unpause
                self.realtime_cooldown_sec = new_rt_cooldown
                
                config.conf["neurovox"]["realtime_auto_pause"] = new_rt_auto_pause
                config.conf["neurovox"]["realtime_auto_unpause"] = new_rt_auto_unpause
                config.conf["neurovox"]["realtime_cooldown_sec"] = new_rt_cooldown
                
                self._pushRealtimeState()
            
        dialog.Destroy()

    def pushSettings(self):
        def worker():
            try:
                data = json.dumps({"api_key": self.api_key, "model": self.model}).encode("utf-8")
                req = urllib.request.Request(f"{self.server_url}/settings", data=data, headers={'Content-Type': 'application/json'})
                urllib.request.urlopen(req, timeout=5)
            except Exception as e:
                log.error(f"Neurovox: Error pushing settings - {e}")
        threading.Thread(target=worker).start()

    def _pushRealtimeState(self):
        def worker():
            try:
                data = json.dumps({
                    "enabled": self.realtime_enabled,
                    "auto_pause": self.realtime_auto_pause,
                    "auto_unpause": self.realtime_auto_unpause,
                    "cooldown_sec": float(self.realtime_cooldown_sec),
                    "verbosity": self.realtime_verbosity
                }).encode("utf-8")
                req = urllib.request.Request(f"{self.server_url}/realtime/state", data=data, headers={'Content-Type': 'application/json'})
                urllib.request.urlopen(req, timeout=5)
            except Exception as e:
                log.error(f"Neurovox: Error pushing realtime state - {e}")
        threading.Thread(target=worker).start()

    def startRealtimePoller(self):
        if self.realtime_thread_active: return
        self.realtime_thread_active = True
        
        def poller():
            log.info("Neurovox: Started Realtime event poller")
            while self.realtime_enabled:
                try:
                    req = urllib.request.Request(f"{self.server_url}/realtime/events")
                    resp = urllib.request.urlopen(req, timeout=12)
                    body = json.loads(resp.read().decode("utf-8"))
                    text = body.get("text")
                    event_type = body.get("type", "speak")
                    
                    if event_type == "cancel_speech":
                        speech.cancelSpeech()
                    elif text:
                        ui.message(text)
                except urllib.error.URLError as e:
                    import time
                    time.sleep(2.0)
                except Exception as e:
                    log.error(f"Neurovox: Error in realtime poller - {e}")
                    import time
                    time.sleep(2.0)
            self.realtime_thread_active = False
            log.info("Neurovox: Stopped Realtime event poller")
            
        threading.Thread(target=poller, daemon=True).start()

    def _request_narration(self, mode="concise"):
        def worker():
            try:
                data = json.dumps({"mode": mode, "api_key": self.api_key, "model": self.model}).encode("utf-8")
                req = urllib.request.Request(f"{self.server_url}/narrate", data=data, headers={"Content-Type": "application/json"})
                resp = urllib.request.urlopen(req, timeout=20)
                body = json.loads(resp.read().decode("utf-8"))
                text = body.get("text", "Error: No text returned.")
                ui.message(text)
            except urllib.error.URLError as e:
                if "Connection refused" in str(e.reason):
                    ui.message("Error: Neurovox server is not running. Please start the companion app.")
                else:
                    ui.message("Error communicating with Neurovox server.")
                log.error(f"Neurovox HTTP error: {e}")
            except Exception as e:
                ui.message("Neurovox error occurred.")
                log.error(f"Neurovox error: {e}")
        
        threading.Thread(target=worker).start()

    def script_narrateScene(self, gesture):
        ui.message("Processing...")
        self._request_narration(mode="concise")
    script_narrateScene.__doc__ = "Narrates the visually active scene and audio."

    def script_narrateDetailed(self, gesture):
        ui.message("Processing detailed...")
        self._request_narration(mode="detailed")
    script_narrateDetailed.__doc__ = "Provides a detailed multimodal description of the screen."
        
    def script_narrateOCR(self, gesture):
        ui.message("Extracting text...")
        self._request_narration(mode="ocr_only")
    script_narrateOCR.__doc__ = "Reads active on-screen text quickly using OCR."

    def script_toggleRealtimeMode(self, gesture):
        self.realtime_enabled = not self.realtime_enabled
        
        self._pushRealtimeState()
        
        if self.realtime_enabled:
            ui.message("Realtime mode on")
            self.startRealtimePoller()
        else:
            ui.message("Realtime mode off")
    script_toggleRealtimeMode.__doc__ = "Toggles the intelligent Realtime Clarification Mode."

    __gestures = {
        "kb:NVDA+e": "narrateScene",
        "kb:NVDA+shift+e": "narrateDetailed",
        "kb:NVDA+control+e": "narrateOCR",
        "kb:NVDA+shift+r": "toggleRealtimeMode",
    }
