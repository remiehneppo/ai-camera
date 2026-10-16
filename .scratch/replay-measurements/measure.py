import hashlib, importlib.util, json, os, resource, subprocess, sys, threading, time
from pathlib import Path
BASE = Path(__file__).resolve().parent
snapshot = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE / 'recorder_snapshot.py'
fixture = Path(sys.argv[2])
spec = importlib.util.spec_from_file_location('recorder_snapshot', snapshot)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
real_popen = subprocess.Popen
processes = []
frame_process = None
eof_at = None
first_at = None
first_running = None
first_eof_seen = None
start = time.monotonic()
class ObservedStdout:
    def __init__(self, wrapped): self.wrapped = wrapped
    def __iter__(self): return self
    def __next__(self):
        global eof_at
        line = self.wrapped.readline()
        if not line:
            eof_at = time.monotonic() - start
            raise StopIteration
        return line
    def __getattr__(self, name): return getattr(self.wrapped, name)
class ObservedPopen(real_popen):
    def __init__(self, args, *a, **kw):
        global frame_process
        super().__init__(args, *a, **kw)
        processes.append(self)
        if 'frame=pts,best_effort_timestamp' in args:
            frame_process = self
            self.stdout = ObservedStdout(self.stdout)
subprocess.Popen = ObservedPopen
real_os_read = os.read
def observed_os_read(fd, length):
    global eof_at
    chunk = real_os_read(fd, length)
    if frame_process is not None and frame_process.stdout is not None and fd == frame_process.stdout.fileno() and not chunk:
        eof_at = time.monotonic() - start
    return chunk
os.read = observed_os_read
peaks = {'python_rss_kib': 0, 'ffprobe_aggregate_rss_kib': 0, 'simultaneous_total_rss_kib': 0}
samples = 0
stop = threading.Event()
def rss(pid):
    try:
        for line in Path(f'/proc/{pid}/status').read_text().splitlines():
            if line.startswith('VmRSS:'): return int(line.split()[1])
    except (FileNotFoundError, ProcessLookupError): pass
    return 0
def monitor():
    global samples
    while not stop.is_set():
        py = rss(os.getpid())
        child = sum(rss(p.pid) for p in list(processes))
        peaks['python_rss_kib'] = max(peaks['python_rss_kib'], py)
        peaks['ffprobe_aggregate_rss_kib'] = max(peaks['ffprobe_aggregate_rss_kib'], child)
        peaks['simultaneous_total_rss_kib'] = max(peaks['simultaneous_total_rss_kib'], py + child)
        samples += 1
        stop.wait(.001)
thread = threading.Thread(target=monitor)
thread.start()
count = 0
def consumer(frame):
    global first_at, first_running, first_eof_seen, count
    if first_at is None:
        first_at = time.monotonic() - start
        first_running = frame_process.poll() is None
        first_eof_seen = eof_at is not None
    count += 1
recorder = module.FileRecorder(BASE / f'ring-{os.getpid()}')
delivered = recorder.replay(fixture, 'synthetic', consumer, sample_fps=30, mode='fast')
end = time.monotonic() - start
stop.set()
thread.join()
print(json.dumps({'snapshot': str(snapshot), 'sha256': hashlib.sha256(snapshot.read_bytes()).hexdigest(), 'fixture': fixture.name, 'sample_fps': 30, 'mode': 'fast', 'callbacks': count, 'delivered': delivered, 'first_callback_s': first_at, 'ffprobe_csv_eof_s': eof_at, 'first_callback_ffprobe_running': first_running, 'first_callback_eof_seen': first_eof_seen, 'elapsed_s': end, 'sample_period_s': .001, 'samples': samples, **peaks, 'python_ru_maxrss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, 'children_ru_maxrss_kib': resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss, 'probe_commands': [p.args for p in processes]}, sort_keys=True))
