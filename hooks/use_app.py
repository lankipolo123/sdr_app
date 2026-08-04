from utils import ConfigService, setup_logger
from .use_channels import ChannelManager


class AppController:
    def __init__(self):
        self.config = ConfigService()
        self.logger = setup_logger(self.config.get("log_folder", "logs"))
        self.channels = ChannelManager(self.config, self.logger)

        if self.config.get("auto_connect", False):
            self.logger.info("Auto-connect enabled - scanning for modules on launch.")
            self.channels.start_discovery()

    def shutdown(self):
        self.channels.save_all()
        self.channels.shutdown()
        self.config.save()
