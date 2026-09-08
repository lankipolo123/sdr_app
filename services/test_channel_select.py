import os
import sys

if not sys.platform.startswith("win"):
    sys.exit("This only runs on Windows - Transit.dll is a native Windows DLL.")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.middleware import dll_send_channel_select
from services.protocol.transit_commands import channel_select_tokens, _CHANNEL_TOKENS

print("Built token strings for every channel (no DLL call, just checking the format):\n")
for channel_id in _CHANNEL_TOKENS:
    print(f"  ch{channel_id:2d}: {channel_select_tokens(channel_id, 'MOD', 'ATN')}")

answer = input(
    "\nSend a real channel-select command to the connected hardware now? [y/N] "
).strip().lower()
if answer != "y":
    print("Skipped - no real command sent.")
    sys.exit(0)

channel_id = int(input("Channel (1-16): ").strip())
ch_module = input("ch_module value: ").strip()
ch_attn = input("ch_attn value: ").strip()

result, error = dll_send_channel_select(channel_id, ch_module, ch_attn)
if error is not None:
    print(f"FAILED: {error}")
else:
    print(f"SendCommandToSDR -> return={result}")
