from utils import ConfigService, setup_logger
from .use_channels import ChannelManager
from .use_safety import SafetyController
from .use_sensor import SensorController


class AppController:

    def __init__(self):
        self.config = ConfigService()
        self.logger = setup_logger(self.config.get("log_folder", "logs"))
        self.channels = ChannelManager(self.config, self.logger)
        self.sensor = SensorController(self.logger)
        self.safety = SafetyController(self.channels, self.logger)
        self.sensor.changed.connect(self.safety.on_sensor_state)

    def shutdown(self):
        self.channels.save_all()
        self.channels.shutdown()
        self.sensor.disconnect()
        self.config.save()
