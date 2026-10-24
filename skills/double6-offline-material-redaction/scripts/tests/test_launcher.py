"""启动包生命周期；真实平台启动和下载另有集成实测。"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
sys.path.insert(0,str(Path(__file__).parents[1]))
import desktop_launch

class LaunchTests(unittest.TestCase):
    def test_default_schedules_local_browser_and_closes(self):
        server=MagicMock();server.base='http://127.0.0.1:12345';server.nonce='test'
        with patch.object(sys,'argv',['LocalRedaction']),patch.object(desktop_launch,'LocalServer',return_value=server),patch.object(desktop_launch.threading,'Timer') as timer,patch.object(desktop_launch.webbrowser,'open') as browser:
            desktop_launch.main();timer.call_args.args[1]();browser.assert_called_once_with('http://127.0.0.1:12345/test/');server.serve_forever.assert_called_once();server.server_close.assert_called_once();server.jobs.clear.assert_called_once()
    def test_automated_probe_uses_same_server_without_browser(self):
        server=MagicMock();server.base='http://127.0.0.1:12345';server.nonce='test'
        with patch.object(sys,'argv',['LocalRedaction','--no-browser']),patch.object(desktop_launch,'LocalServer',return_value=server),patch.object(desktop_launch.threading,'Timer') as timer:
            desktop_launch.main();timer.assert_not_called()
if __name__=='__main__':unittest.main()
