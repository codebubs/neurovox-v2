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

addonHandler.initTranslation()

class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    scriptCategory = "Neurovox"
    
    config.conf.spec["neurovox"] = {
        "api_key": "string(default='')",
        "model": "string(default='gemini-1.5-flash')"
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.server_url = "http://127.0.0.1:8000"
        
        self.api_key = config.conf["neurovox"]["api_key"]
        self.model = config.conf["neurovox"]["model"]
        
        self.createMenu()
        
        if self.api_key or self.model:
            self.pushSettings()

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
        
        buttonSizer = dialog.CreateButtonSizer(wx.OK | wx.CANCEL)
        mainSizer.Add(buttonSizer, 0, wx.ALL | wx.ALIGN_RIGHT, 5)
        
        dialog.SetSizerAndFit(mainSizer)
        
        if dialog.ShowModal() == wx.ID_OK:
            new_key = self.keyText.GetValue()
            new_model = self.modelText.GetValue()
            
            self.api_key = new_key
            self.model = new_model
            
            config.conf["neurovox"]["api_key"] = new_key
            config.conf["neurovox"]["model"] = new_model
            
            self.pushSettings()
            
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

    __gestures = {
        "kb:NVDA+n": "narrateScene",
        "kb:NVDA+shift+n": "narrateDetailed",
        "kb:NVDA+control+n": "narrateOCR",
    }
