

class FakeSDR:

    def __init__(self, present: bool = True, send_return_code: int = -2):
        self.present = present
        self.send_return_code = send_return_code
        self.sent_frames: list[bytes] = []
        self.connect_calls = 0
        self.send_calls = 0

    def auto_connect(self):
        self.connect_calls += 1
        if self.present:
            return 4, "Connected", None
        return -1, "DisConnected", None

    def check_connection(self):
        if self.present:
            return 40, "Connected", None
        return -1, "DisConnected", None

    def disconnect(self):
        return 1, "", None

    def send_command(self, data: bytes):
        self.send_calls += 1
        self.sent_frames.append(bytes(data))
        return self.send_return_code, None


def install_fake_dll(sdr: FakeSDR):
    import hooks.use_connection as uc

    uc.dll_auto_connect = sdr.auto_connect
    uc.dll_check_connection = sdr.check_connection
    uc.dll_disconnect = sdr.disconnect
    uc.dll_send_command = sdr.send_command
