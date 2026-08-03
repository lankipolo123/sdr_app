from utils import ConfigService, setup_logger
from .use_connection import ConnectionController
from .use_channels import ChannelManager


class AppController:
    def __init__(self):
        self.config = ConfigService()
        self.logger = setup_logger(self.config.get("log_folder", "logs"))
        self.connection = ConnectionController()
        self.channels = ChannelManager(self.connection, self.config, self.logger)

        self._maybe_auto_connect()

    def _maybe_auto_connect(self):
        if not self.config.get("auto_connect", False):
            return
        port = self.config.get("com_port", "")
        if not port:
            self.logger.info("Auto-connect enabled but no COM port saved; skipping.")
            return
        available = self.connection.list_ports()
        if port not in available:
            self.logger.warning(f"Auto-connect: saved port {port} not found among {available}; skipping.")
            return
        baud = self.config.get("baud_rate", 115200)
        parity = self.config.get("parity", "N")
        data_bits = self.config.get("data_bits", 8)
        self.logger.info(f"Auto-connecting to {port} at {baud} baud, parity={parity}, data_bits={data_bits}.")
        self.connection.connect(port, baud, parity, data_bits)

    def shutdown(self):
        self.channels.save_all()
        if self.connection.is_connected():
            self.connection.disconnect()
        self.config.save()
