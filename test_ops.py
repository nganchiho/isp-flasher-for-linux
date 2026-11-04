# Runs the operations against a fake stick holding a fake ATmega328P (no hardware): python test_ops.py
import os, tempfile, time
import usbisp

time.sleep = lambda s: None
SIG = usbisp.BY_NAME['ATmega328P']['sig']


class FakeDev:
    flash = bytearray(b'\xff') * 0x8000
    ee = bytearray(b'\xff') * 1024
    lock = 0xFF

    def open(self, *a): pass
    def close(self): pass

    def send_feature_report(self, r):
        r = bytes(r)
        if r[0] == 2:  # page write
            a = r[1] | r[2] << 8
            self.flash[a:a + 128] = r[8:136]
        elif r[1] == 0x08:
            self.addr = r[2] | r[3] << 8
        elif r[1] == 0x0E:
            a, b, c, d = r[2:6]
            out = [0, 0, 0, 0]
            if a == 0xAC and b == 0x53: out[2] = 0x53
            elif a == 0x30: out[3] = SIG[c]
            elif a == 0xAC and b == 0x80: self.flash[:] = b'\xff' * len(self.flash); FakeDev.lock = 0xFF
            elif a == 0xAC and b == 0xE0: FakeDev.lock &= d  # lock bits only clear
            elif a == 0x58: out[3] = self.lock
            elif a == 0xC0: self.ee[b << 8 | c] = d
            elif a == 0xA0: out[3] = self.ee[b << 8 | c]
            self.reply = out

    def get_feature_report(self, n, size):
        return list(self.reply) + [0] * 4 if n == 1 else list(self.flash[self.addr:self.addr + 128])


usbisp.hid.device = FakeDev
quiet = lambda *a: None
d = tempfile.mkdtemp()
fw, ee = os.path.join(d, 'fw.hex'), os.path.join(d, 'fw.eep')
usbisp.save_hex(fw, bytes(range(256)) * 20)
usbisp.save_hex(ee, b'\x01\x02\x03')

usbisp.op_blank(None, quiet, quiet)
usbisp.op_write(None, quiet, quiet, flash=fw, eeprom=ee, lock=0x3C)
usbisp.op_verify(None, quiet, quiet, flash=fw, eeprom=ee)
assert usbisp.op_lock(None, quiet, quiet) == 0x3C


def fails(fn, **kw):
    try:
        fn(None, quiet, quiet, **kw)
    except usbisp.IspError:
        return True


assert fails(usbisp.op_blank)
FakeDev.flash[5] ^= 1
assert fails(usbisp.op_verify, flash=fw)
FakeDev.flash[5] ^= 1
assert fails(usbisp.op_lock, value=0xFF)  # can't set bits back to 1 without erase
usbisp.op_erase(None, quiet, quiet)
usbisp.op_blank(None, quiet, quiet)
print('ok')
