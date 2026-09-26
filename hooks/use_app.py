import time

from PySide6.QtCore import QObject, QTimer, Signal

from utils import ConfigService, setup_logger
from .use_channels import ChannelManager
from .use_sensor import SensorController
from .use_safety import SafetyController
from .use_selection import SelectionManager

UPTIME_TICK_MS = 1000
# How many 1s ticks between persisting uptime to config.json while the app
# is running - so a crash/power loss only loses a few seconds of credit
# instead of the whole session (which only saved on a clean shutdown()).
UPTIME_SAVE_EVERY_TICKS = 30


class AppController(QObject):

    uptime_changed = Signal(int)  # total accumulated uptime, in seconds

    def __init__(self, config: ConfigService | None = None, logger=None):
        # config/logger are injectable (rather than always constructed
        # here) so tests can point them at a temp dir instead of the real
        # ConfigService.CONFIG_PATH/log folder - see
        # tests/dry_run.py's make_app_controller().
        super().__init__()
        self.config = config or ConfigService()
        self.logger = logger or setup_logger(self.config.get("log_folder", "logs"))
        self.channels = ChannelManager(self.config, self.logger)

        # Amplifier temperature/humidity sensors - a real, separate raw
        # serial (Modbus RTU) connection, unrelated to the RS-422/
        # Transit.dll bus above. The kill switch listens to it directly
        # and forces every channel off the moment the rack-wide average
        # reading crosses KILL_SWITCH_THRESHOLD_C (use_safety.py).
        self.sensor = SensorController()
        self.safety = SafetyController(self.channels)
        self.sensor.changed.connect(self._on_sensor_changed)
        self.selection = SelectionManager()

        self._uptime_base = self.config.get("total_uptime_seconds", 0) or 0
        self._session_start = time.monotonic()
        self._uptime_ticks_since_save = 0
        self._uptime_timer = QTimer(self)
        self._uptime_timer.timeout.connect(self._on_uptime_tick)
        self._uptime_timer.start(UPTIME_TICK_MS)

    def current_uptime_seconds(self) -> int:
        return int(self._uptime_base + (time.monotonic() - self._session_start))

    def _on_sensor_changed(self):
        self.safety.on_sensor_reading(self.sensor.average_temperature())

    def _on_uptime_tick(self):
        seconds = self.current_uptime_seconds()
        self.uptime_changed.emit(seconds)
        self._uptime_ticks_since_save += 1
        if self._uptime_ticks_since_save >= UPTIME_SAVE_EVERY_TICKS:
            self._uptime_ticks_since_save = 0
            self._save_uptime(seconds)

    def _save_uptime(self, seconds: int | None = None):
        if seconds is None:
            seconds = self.current_uptime_seconds()
        self.config.set("total_uptime_seconds", seconds)
        self.config.save()

    def shutdown(self):
        self._uptime_timer.stop()
        self.sensor.disconnect()
        self.channels.save_all()
        self.channels.shutdown()
        self._save_uptime()
        self.config.save()
