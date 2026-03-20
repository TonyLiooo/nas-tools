import os

from pyvirtualdisplay import Display

from app.utils.commons import singleton
from app.utils import ExceptionUtils
from config import XVFB_PATH


@singleton
class DisplayHelper(object):
    _display = None
    _owns_display = False
    _display_var = None

    def __init__(self):
        self.init_config()

    def init_config(self):
        self.stop_service()
        existing_display = os.environ.get("DISPLAY")
        if existing_display:
            self._display = None
            self._owns_display = False
            self._display_var = existing_display
            os.environ["NASTOOL_DISPLAY"] = "1"
            return
        if self.can_display():
            try:
                self._display = Display(visible=False, size=(1024, 768))
                self._display.start()
                self._owns_display = True
                self._display_var = getattr(self._display, "new_display_var", None) or os.environ.get("DISPLAY")
                os.environ["NASTOOL_DISPLAY"] = "1"
            except Exception as err:
                ExceptionUtils.exception_traceback(err)

    def get_display(self):
        return self._display

    def stop_service(self):
        os.environ.pop("NASTOOL_DISPLAY", None)
        if self._display:
            try:
                current_display = os.environ.get("DISPLAY")
                if self._owns_display and self._display_var and current_display == self._display_var:
                    os.environ.pop("DISPLAY", None)
                self._display.stop()
            finally:
                self._display = None
                self._owns_display = False
                self._display_var = None

    @staticmethod
    def can_display():
        for path in XVFB_PATH:
            if os.path.exists(path):
                return True
        return False

    def __del__(self):
        self.stop_service()
