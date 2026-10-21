#!/usr/bin/env python3
"""Flash AVRs with the zhifengsoft "USBHID" ISP stick (USB 03eb:c8b4) on Linux, macOS or Windows.

The protocol was taken from ProgISP 1.72's HID traffic. Every transfer is a HID feature report:
  report 1 (8 B)   01 <cmd> <args...>       0d=connect 0e=SPI 4-byte xfer 08=read 128 B flash 0b=release
  report 2 (136 B) 02 <addr lo,hi,ext> <page mask> 80 00 01 <128 data bytes>   write flash
  report 3 (128 B) reply to cmd 08

Run without arguments for the GUI, or see --help for the CLI.
"""
import argparse, glob, json, os, shutil, subprocess, sys, threading, time, queue

try:
    import hid
except ImportError:
    sys.exit('hidapi is missing: pip install hidapi')

VID, PID = 0x03EB, 0xC8B4
BLOCK = 128
HERE = os.path.dirname(os.path.abspath(__file__))
CHIPS = json.load(open(os.path.join(HERE, 'chips.json')))
BY_NAME = {c['name']: c for c in CHIPS}
SETTINGS = os.path.join(os.path.expanduser('~'), '.usbisp.json')


class IspError(Exception):
    pass


class UsbIsp:
    def __init__(self):
        self.dev = hid.device()
        try:
            self.dev.open(VID, PID)
        except (IOError, OSError):
            hint = ' (on Linux, install the udev rule from README.md)' if sys.platform.startswith('linux') else ''
            raise IspError('USB ISP stick 03eb:c8b4 not found' + hint)

    def close(self):
        try:
            self._cmd(0x0B, 1)  # release target from reset
        finally:
            self.dev.close()

    def _cmd(self, *b):
        self.dev.send_feature_report(bytes([1, *b]).ljust(8, b'\0'))

    def spi(self, a, b=0, c=0, d=0):
        self._cmd(0x0E, a, b, c, d, 0, 4)
        return bytes(self.dev.get_feature_report(1, 8)[:4])

    def spi_word(self, word, value=None, pos=3):
        """Send a 32-bit ISP command from chips.json, optionally with a value byte at `pos`."""
        b = bytearray(word.to_bytes(4, 'big'))
        if value is not None:
            b[pos] = value
        return self.spi(*b)

    def connect(self):
        for speed in range(1, 7):  # ProgISP retries with the next speed setting on failure
            for reset in (1, 0):
                self._cmd(0x0D, reset, speed, 0x20, 0xA0, 0x40, 0xC0)  # AVR read/write opcodes
                time.sleep(0.1)
            if self.spi(0xAC, 0x53)[2] == 0x53:
                return speed
        raise IspError('target not responding - check wiring, power and that the board is plugged in')

    def signature(self):
        return [self.spi(0x30, 0, i)[3] for i in range(3)]

    def erase(self, chip):
        self.spi(0xAC, 0x80)
        time.sleep(chip['wd_erase'] / 1000)
        self.connect()  # ProgISP re-enters programming mode after an erase

    def read_flash(self, addr):
        self._cmd(0x08, addr & 0xFF, addr >> 8 & 0xFF, addr >> 16 & 0xFF)
        return bytes(self.dev.get_feature_report(3, BLOCK)[:BLOCK])

    def write_flash(self, addr, data, page):
        hdr = bytes([2, addr & 0xFF, addr >> 8 & 0xFF, addr >> 16 & 0xFF, (page - 1) & 0xFF, BLOCK, 0, 1])
        self.dev.send_feature_report(hdr + data)

    def fuses(self, chip):
        return [self.spi_word(w)[chip['fuse_rpos']] for w in chip['fuse_r']]

    def write_fuses(self, chip, values):
        for w, v in zip(chip['fuse_w'], values):
            self.spi_word(w, v, chip['fuse_wpos'])
            time.sleep(chip['wd_fuse'] / 1000)


# ---------- Intel HEX ----------

def load_image(path, size):
    img = bytearray(b'\xff') * size
    if not path.lower().endswith(('.hex', '.eep', '.ihx')):
        data = open(path, 'rb').read()
        if len(data) > size:
            raise IspError(f'{os.path.basename(path)} is {len(data)} bytes, chip holds {size}')
        img[:len(data)] = data
        return img
    base = 0
    for n, line in enumerate(open(path), 1):
        line = line.strip()
        if not line.startswith(':'):
            continue
        rec = bytes.fromhex(line[1:])
        if sum(rec) & 0xFF:
            raise IspError(f'{os.path.basename(path)} line {n}: bad checksum')
        count, addr, typ, data = rec[0], rec[1] << 8 | rec[2], rec[3], rec[4:4 + rec[0]]
        if typ == 0:
            a = base + addr
            if a + count > size:
                raise IspError(f'{os.path.basename(path)}: data at 0x{a:X} is beyond the chip size ({size} bytes)')
            img[a:a + count] = data
        elif typ == 1:
            break
        elif typ == 2:
            base = (data[0] << 8 | data[1]) << 4
        elif typ == 4:
            base = (data[0] << 8 | data[1]) << 16
    return img


def save_hex(path, data):
    data = bytes(data).rstrip(b'\xff')
    rec = lambda typ, addr, d: ':%s%02X' % ((bytes([len(d), addr >> 8, addr & 0xFF, typ]) + d).hex().upper(),
                                            -sum(bytes([len(d), addr >> 8, addr & 0xFF, typ]) + d) & 0xFF)
    with open(path, 'w') as f:
        for a in range(0, len(data), 16):
            if a and a % 0x10000 == 0:
                f.write(rec(4, 0, (a >> 16).to_bytes(2, 'big')) + '\n')
            f.write(rec(0, a & 0xFFFF, data[a:a + 16]) + '\n')
        f.write(':00000001FF\n')


# ---------- operations (shared by CLI and GUI) ----------

class Session:
    """Open the stick, enter programming mode, identify the chip. `chip_name=None` auto-detects."""

    def __init__(self, chip_name, log):
        self.isp = UsbIsp()
        try:
            self.isp.connect()
            sig = self.isp.signature()
            sig_s = ' '.join('%02X' % b for b in sig)
            if chip_name:
                self.chip = BY_NAME[chip_name]
                if self.chip['sig'] != sig:
                    raise IspError(f'signature {sig_s} does not match {chip_name} - wrong chip selected?')
            else:
                found = [c['name'] for c in CHIPS if c['sig'] == sig]
                if not found:
                    raise IspError(f'unknown chip signature {sig_s}')
                self.chip = BY_NAME[found[0]]
            log(f'{self.chip["name"]}  (signature {sig_s})')
        except BaseException:
            self.isp.close()
            raise

    def __enter__(self):
        return self.isp, self.chip

    def __exit__(self, *exc):
        self.isp.close()


def op_detect(chip, log, prog, **_):
    with Session(chip, log) as (isp, c):
        return c['name']


def op_write(chip, log, prog, flash, eeprom=None, **_):
    with Session(chip, log) as (isp, c):
        img = load_image(flash, c['flash'])
        unit = max(BLOCK, c['page'])  # never skip half a page: the stick commits at page end
        units = [a for a in range(0, c['flash'], unit) if img[a:a + unit].strip(b'\xff')]
        if c['flash'] > 0x10000 and units and units[-1] >= 0x10000:
            log('note: writes above 64 KB use an untested addressing guess - verify will catch problems')
        log('erasing…')
        isp.erase(c)
        total = len(units) * 2
        log(f'writing {len(units) * unit} bytes…')
        for i, a in enumerate(units):
            for b in range(a, a + unit, BLOCK):
                isp.write_flash(b, bytes(img[b:b + BLOCK]), c['page'])
            prog(i + 1, total)
        log('verifying…')
        for i, a in enumerate(units):
            for b in range(a, a + unit, BLOCK):
                got = isp.read_flash(b)
                if got != img[b:b + BLOCK]:
                    off = next(k for k in range(BLOCK) if got[k] != img[b + k])
                    raise IspError(f'verify failed at 0x{b + off:X}: read {got[off]:02X}, expected {img[b + off]:02X}')
            prog(len(units) + i + 1, total)
        log('flash OK')
        if eeprom:
            write_eeprom(isp, c, eeprom, log, prog)


def op_read(chip, log, prog, flash, **_):
    with Session(chip, log) as (isp, c):
        data = bytearray()
        for a in range(0, c['flash'], BLOCK):
            data += isp.read_flash(a)
            prog(a + BLOCK, c['flash'])
        save_hex(flash, data)
        log(f'saved {c["flash"]} bytes to {flash}')


def op_erase(chip, log, prog, **_):
    with Session(chip, log) as (isp, c):
        isp.erase(c)
        log('chip erased')


def write_eeprom(isp, c, path, log, prog):
    img = load_image(path, c['eeprom'])
    cur = read_eeprom(isp, c, lambda *a: None)
    todo = [a for a in range(c['eeprom']) if img[a] != cur[a]]
    log(f'writing {len(todo)} changed EEPROM bytes…')
    for i, a in enumerate(todo):
        isp.spi(0xC0, a >> 8, a & 0xFF, img[a])
        time.sleep(c['wd_eeprom'] / 1000)
        prog(i + 1, len(todo))
    if read_eeprom(isp, c, prog) != img:
        raise IspError('EEPROM verify failed')
    log('EEPROM OK')


def read_eeprom(isp, c, prog):
    out = bytearray()
    for a in range(c['eeprom']):
        out.append(isp.spi(0xA0, a >> 8, a & 0xFF)[3])
        if a % 64 == 63:
            prog(a + 1, c['eeprom'])
    return out


def op_eeprom_write(chip, log, prog, eeprom, **_):
    with Session(chip, log) as (isp, c):
        write_eeprom(isp, c, eeprom, log, prog)


def op_eeprom_read(chip, log, prog, eeprom, **_):
    with Session(chip, log) as (isp, c):
        save_hex(eeprom, read_eeprom(isp, c, prog))
        log(f'saved {c["eeprom"]} EEPROM bytes to {eeprom}')


def find_pio():
    for p in (shutil.which('pio'), shutil.which('platformio'),
              os.path.expanduser('~/.platformio/penv/bin/pio')):
        if p and os.access(p, os.X_OK):
            return p
    raise IspError('PlatformIO not found (install it, or the VS Code PlatformIO extension)')


def op_build(chip, log, prog, project, **_):
    """Run `pio run` in a PlatformIO project and return the newest firmware.hex it produced."""
    project = os.path.abspath(project)
    if not os.path.isfile(os.path.join(project, 'platformio.ini')):
        raise IspError(f'{project} has no platformio.ini')
    log(f'building {project}…')
    p = subprocess.Popen([find_pio(), 'run', '-d', project], stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True)
    tail = []
    for line in p.stdout:
        line = line.rstrip()
        tail = (tail + [line])[-15:]
        if line.startswith(('Building ', 'Linking ', 'RAM:', 'Flash:')) or 'error' in line.lower():
            log(line)
    if p.wait():
        log('\n'.join(tail))
        raise IspError('build failed')
    hexes = glob.glob(os.path.join(project, '.pio', 'build', '*', 'firmware.hex'))
    if not hexes:
        raise IspError('build succeeded but no firmware.hex was produced')
    hx = max(hexes, key=os.path.getmtime)
    log(f'built {hx}')
    return hx


def op_build_write(chip, log, prog, project, **_):
    hx = op_build(chip, log, prog, project)
    op_write(chip, log, prog, hx)
    return hx


FUSE_NAMES = ['low', 'high', 'ext']


def op_fuses(chip, log, prog, values=None, **_):
    with Session(chip, log) as (isp, c):
        if values:
            if len(values) != len(c['fuse_w']):
                raise IspError(f'{c["name"]} has {len(c["fuse_w"])} fuse bytes, got {len(values)}')
            isp.write_fuses(c, values)
            if isp.fuses(c) != values:
                raise IspError('fuse verify failed')
            log('fuses written')
        f = isp.fuses(c)
        log('fuses: ' + '  '.join(f'{n}=0x{v:02X}' for n, v in zip(FUSE_NAMES, f)))
        return f


# ---------- GUI ----------

def gui(initial_hex=None):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    try:
        saved = json.load(open(SETTINGS))
    except (OSError, ValueError):
        saved = {}

    root = tk.Tk()
    root.title('USB ISP Flasher')
    root.minsize(640, 440)
    AUTO = 'Auto-detect'
    chip = tk.StringVar(value=saved.get('chip', AUTO))
    flash = tk.StringVar(value=initial_hex or saved.get('flash', ''))
    project = tk.StringVar(value=saved.get('project', ''))
    eeprom = tk.StringVar(value=saved.get('eeprom', ''))
    fuse_vars = [tk.StringVar() for _ in FUSE_NAMES]
    events = queue.Queue()
    buttons = []

    frm = ttk.Frame(root, padding=10)
    frm.pack(fill='both', expand=True)
    frm.columnconfigure(1, weight=1)

    def row(r, label, var, types, actions):
        ttk.Label(frm, text=label).grid(row=r, column=0, sticky='w', pady=3)
        ttk.Entry(frm, textvariable=var).grid(row=r, column=1, sticky='ew', padx=4)
        ttk.Button(frm, text='Browse…', command=lambda: var.set(
            filedialog.askopenfilename(filetypes=types) or var.get())).grid(row=r, column=2)
        for i, (text, cmd) in enumerate(actions):
            b = ttk.Button(frm, text=text, command=cmd)
            b.grid(row=r, column=3 + i, padx=2)
            buttons.append(b)

    ttk.Label(frm, text='Chip').grid(row=0, column=0, sticky='w')
    ttk.Combobox(frm, textvariable=chip, state='readonly',
                 values=[AUTO] + sorted(BY_NAME, key=str.lower)).grid(row=0, column=1, sticky='ew', padx=4)

    def chip_arg():
        return None if chip.get() == AUTO else chip.get()

    def run(fn, **kw):
        for b in buttons:
            b.state(['disabled'])
        bar['value'] = 0
        json.dump({'chip': chip.get(), 'flash': flash.get(), 'eeprom': eeprom.get(), 'project': project.get()},
                  open(SETTINGS, 'w'))

        def work():
            try:
                res = fn(chip_arg(), lambda m: events.put(('log', m)), lambda i, n: events.put(('prog', 100 * i / n)), **kw)
                events.put(('done', (fn, res)))
            except IspError as e:
                events.put(('log', 'ERROR: ' + str(e)))
                events.put(('done', None))
            except Exception as e:  # USB unplugged mid-way etc.
                events.put(('log', f'ERROR: {type(e).__name__}: {e}'))
                events.put(('done', None))
        threading.Thread(target=work, daemon=True).start()

    def need(var, what):
        if not var.get() or not os.path.isfile(var.get()):
            messagebox.showerror('USB ISP Flasher', f'Choose a {what} file first.')
            return False
        return True

    def save_as(var, title):
        p = filedialog.asksaveasfilename(title=title, defaultextension='.hex', filetypes=[('Intel HEX', '*.hex *.eep')])
        if p:
            var.set(p)
        return p

    def detect():
        run(op_detect)

    def need_project():
        if not os.path.isfile(os.path.join(project.get(), 'platformio.ini')):
            messagebox.showerror('USB ISP Flasher', 'Choose a PlatformIO project folder (one with platformio.ini).')
            return False
        return True

    def build():
        if need_project():
            run(op_build, project=project.get())

    def build_write():
        if need_project():
            run(op_build_write, project=project.get())

    def write():
        if need(flash, 'flash'):
            run(op_write, flash=flash.get())

    def read():
        if save_as(flash, 'Save flash as'):
            run(op_read, flash=flash.get())

    def erase():
        if messagebox.askyesno('Erase chip', 'Erase flash (and EEPROM unless EESAVE is set)?'):
            run(op_erase)

    def ee_write():
        if need(eeprom, 'EEPROM'):
            run(op_eeprom_write, eeprom=eeprom.get())

    def ee_read():
        if save_as(eeprom, 'Save EEPROM as'):
            run(op_eeprom_read, eeprom=eeprom.get())

    def fuse_read():
        run(op_fuses)

    def fuse_write():
        try:
            vals = [int(v.get(), 16) for v in fuse_vars if v.get().strip()]
        except ValueError:
            return messagebox.showerror('Fuses', 'Fuse values must be hex, e.g. FF')
        if not vals or any(v > 0xFF for v in vals):
            return messagebox.showerror('Fuses', 'Read the fuses first, then edit them.')
        text = '  '.join(f'{n}=0x{v:02X}' for n, v in zip(FUSE_NAMES, vals))
        if messagebox.askyesno('Write fuses', f'Write {text}?\n\nWrong fuses can lock you out of ISP '
                               '(e.g. SPIEN off, RSTDISBL on, or a clock source you do not have).', icon='warning'):
            run(op_fuses, values=vals)

    b = ttk.Button(frm, text='Detect', command=detect)
    b.grid(row=0, column=3, padx=2)
    buttons.append(b)
    ttk.Label(frm, text='Project').grid(row=1, column=0, sticky='w', pady=3)
    ttk.Entry(frm, textvariable=project).grid(row=1, column=1, sticky='ew', padx=4)
    ttk.Button(frm, text='Browse…', command=lambda: project.set(
        filedialog.askdirectory(title='PlatformIO project folder') or project.get())).grid(row=1, column=2)
    for i, (text, cmd) in enumerate((('Build', build), ('Build & Write', build_write))):
        b = ttk.Button(frm, text=text, command=cmd)
        b.grid(row=1, column=3 + i, padx=2)
        buttons.append(b)
    row(2, 'Flash', flash, [('Intel HEX', '*.hex'), ('Binary', '*.bin'), ('All', '*')],
        [('Write', write), ('Read…', read)])
    row(3, 'EEPROM', eeprom, [('Intel HEX', '*.eep *.hex'), ('All', '*')],
        [('Write', ee_write), ('Read…', ee_read)])

    ff = ttk.Frame(frm)
    ff.grid(row=4, column=0, columnspan=6, sticky='w', pady=6)
    ttk.Label(ff, text='Fuses').pack(side='left')
    for n, v in zip(FUSE_NAMES, fuse_vars):
        ttk.Label(ff, text=f'  {n} 0x').pack(side='left')
        ttk.Entry(ff, textvariable=v, width=4).pack(side='left')
    for text, cmd in (('Read', fuse_read), ('Write…', fuse_write), ('Erase chip…', erase)):
        b = ttk.Button(ff, text=text, command=cmd)
        b.pack(side='left', padx=(8 if text == 'Read' else 2, 2))
        buttons.append(b)

    bar = ttk.Progressbar(frm, maximum=100)
    bar.grid(row=5, column=0, columnspan=6, sticky='ew', pady=4)
    logbox = tk.Text(frm, height=12, state='disabled', wrap='word')
    logbox.grid(row=6, column=0, columnspan=6, sticky='nsew')
    frm.rowconfigure(6, weight=1)

    def log(msg):
        logbox.configure(state='normal')
        logbox.insert('end', time.strftime('%H:%M:%S  ') + msg + '\n')
        logbox.see('end')
        logbox.configure(state='disabled')

    def pump():
        while not events.empty():
            kind, val = events.get()
            if kind == 'log':
                log(val)
            elif kind == 'prog':
                bar['value'] = val
            elif kind == 'done':
                for b in buttons:
                    b.state(['!disabled'])
                if val and val[0] in (op_build, op_build_write):
                    flash.set(val[1])
                if val and val[0] is op_fuses:
                    for var, f in zip(fuse_vars, val[1] + [None] * 3):
                        var.set('' if f is None else f'{f:02X}')
        root.after(50, pump)

    log(f'{len(CHIPS)} chips loaded. Plug in the stick and a board, then Detect or Write.')
    pump()
    root.mainloop()


# ---------- CLI ----------

def main():
    if len(sys.argv) == 1 or (len(sys.argv) == 2 and os.path.isfile(sys.argv[1])):
        return gui(sys.argv[1] if len(sys.argv) == 2 else None)
    p = argparse.ArgumentParser(description='zhifengsoft USB ISP (03eb:c8b4) AVR flasher')
    p.add_argument('-c', '--chip', help='chip name, e.g. ATmega328P (default: auto-detect)')
    sub = p.add_subparsers(dest='cmd', required=True)
    sub.add_parser('detect')
    sub.add_parser('erase')
    s = sub.add_parser('write', help='erase, write and verify flash')
    s.add_argument('flash')
    s.add_argument('--eeprom')
    sub.add_parser('read').add_argument('flash', help='output .hex')
    sub.add_parser('eeprom-read').add_argument('eeprom', help='output .hex')
    sub.add_parser('eeprom-write').add_argument('eeprom')
    s = sub.add_parser('fuses', help='read fuses, or write them: fuses 0xFF 0xD9 0xFF (low high ext)')
    s.add_argument('values', nargs='*', type=lambda v: int(v, 16))
    s = sub.add_parser('chips', help='list supported chips')
    a = p.parse_args()

    if a.cmd == 'chips':
        return print('\n'.join(sorted(BY_NAME, key=str.lower)))
    if a.chip and a.chip not in BY_NAME:
        sys.exit(f'unknown chip {a.chip!r}; see "usbisp.py chips"')

    def prog(i, n):
        print(f'\r{100 * i // n:3d}%', end='', file=sys.stderr, flush=True)
        if i >= n:
            print(file=sys.stderr)

    fn = {'detect': op_detect, 'erase': op_erase, 'write': op_write, 'read': op_read,
          'eeprom-read': op_eeprom_read, 'eeprom-write': op_eeprom_write, 'fuses': op_fuses}[a.cmd]
    try:
        fn(a.chip, print, prog, **{k: v for k, v in vars(a).items() if k not in ('chip', 'cmd')})
    except IspError as e:
        sys.exit('error: ' + str(e))


if __name__ == '__main__':
    main()
