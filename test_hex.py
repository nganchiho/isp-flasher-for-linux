# Round-trip check for the Intel HEX reader/writer (no hardware needed): python test_hex.py
import os, random, tempfile
import usbisp

data = bytearray(random.randbytes(0x20000))
data[0x100:0x200] = b'\xff' * 0x100           # hole
p = os.path.join(tempfile.mkdtemp(), 'x.hex')
usbisp.save_hex(p, data)
assert usbisp.load_image(p, len(data)) == data  # includes >64 KB extended-address records
try:
    usbisp.load_image(p, 0x8000)
    raise AssertionError('oversize image not rejected')
except usbisp.IspError:
    pass
print('ok')
