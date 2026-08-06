from . import packet_builder as pb
from . import constants as c


def output_on(addr: int) -> bytes:
    return pb.build_output_switch(addr, on=True)


def output_off(addr: int) -> bytes:
    return pb.build_output_switch(addr, on=False)


def set_signal(addr: int, mode: int, freq_mhz: int, bandwidth_mhz: int, power_code: int) -> bytes:
    return pb.build_signal_control(addr, mode, freq_mhz, bandwidth_mhz, power_code)


def query_status(addr: int = 0x00) -> bytes:
    return pb.build_status_query(addr)


def query_address() -> bytes:
    return pb.build_addr_query()


def set_address(new_addr: int) -> bytes:
    return pb.build_addr_set(new_addr)
