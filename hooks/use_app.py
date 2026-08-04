from utils import ConfigService, setup_logger
from .use_channels import ChannelManager


class AppController:
    """No auto-scan on launch, deliberately - see MainWindow. Scanning
    only ever happens from an explicit user click now."""

    def __init__(self):
        self.config = ConfigService()
        self.logger = setup_logger(self.config.get("log_folder", "logs"))
        self.channels = ChannelManager(self.config, self.logger)

    def shutdown(self):
        self.channels.save_all()
        self.channels.shutdown()
        self.config.save()
