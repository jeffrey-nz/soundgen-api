"""
final_render.py
  1. Dismiss any blocking REAPER dialogs (pyautogui click on OK)
  2. Re-enable reapy via Actions list
  3. Fix RENDER_BOUNDSFLAG to 1.0 (Entire project, not Custom)
  4. Fire-and-forget render, poll for WAV
"""
import sys, os, time, warnings, socket, ctypes, ctypes.wintypes as wt
sys.path.insert(0, r'C:\Users\Work\python312\Lib\site-packages')
import pyautogui
from PIL import ImageGrab
pyautogui.FAILSAFE = False

REAPER_HWND = 1574834
OUT_DIR  = r'C:\Users\Work\procmusic\dashboard~'
OUT_WAV  = os.path.join(OUT_DIR, 'orchestral_piece.wav')
OUT_STEM = 'orchestral_piece'

user32 = ctypes.windll.user32

def get_rect(hwnd):
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right - r.left, r.bottom - r.top

def ss(name):
    wx, wy, ww, wh = get_rect(REAPER_HWND)
    img = ImageGrab.grab(all_screens=True).crop((wx, wy, wx+ww, wy+wh))
    img.save(os.path.join(OUT_DIR, name))
    print(f'  [ss] {name}')

def focus_reaper():
    wx, wy, ww, wh = get_rect(REAPER_HWND)
    user32.ShowWindow(REAPER_HWND, 9)
    user32.SetForegroundWindow(REAPER_HWND)
    user32.BringWindowToTop(REAPER_HWND)
    time.sleep(0.4)
    return wx, wy, ww, wh

# ── Step 1: Dismiss all error dialogs ─────────────────────────────────────────
print('=== Step 1: Dismiss dialogs ===')
for _ in range(5):
    # Check for modal dialogs by enumerating child windows of REAPER
    dialogs = []
    def find_dialog_cb(h, _):
        n = user32.GetWindowTextLengthW(h)
        if n > 0:
            buf = ctypes.create_unicode_buffer(n+1)
            user32.GetWindowTextW(h, buf, n+1)
            t = buf.value
            if ('Render' in t or 'Error' in t or 'Nothing' in t) and user32.IsWindowVisible(h):
                r = wt.RECT()
                user32.GetWindowRect(h, ctypes.byref(r))
                dialogs.append((h, t, r.left, r.top, r.right-r.left, r.bottom-r.top))
        return True
    user32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)(find_dialog_cb), 0)

    if dialogs:
        for h, t, dx, dy, dw, dh in dialogs:
            print(f'  Dialog: {t!r} at ({dx},{dy}) {dw}x{dh}')
            # Click OK button (center bottom of dialog)
            ok_x = dx + dw // 2
            ok_y = dy + int(dh * 0.75)
            print(f'  Clicking OK at ({ok_x},{ok_y})')
            pyautogui.click(ok_x, ok_y)
            time.sleep(0.3)
    else:
        break
    time.sleep(0.5)

ss('fin_step1.png')

# ── Step 2: Re-enable reapy ────────────────────────────────────────────────────
print('\n=== Step 2: Re-enable reapy ===')
wx, wy, ww, wh = focus_reaper()

# Click in the REAPER track area (well below any toolbar/menu)
cx = wx + ww // 2
cy = wy + 300  # y=300 (track area, not toolbar)
print(f'  Clicking REAPER at ({cx},{cy})')
pyautogui.click(cx, cy)
time.sleep(0.5)
ss('fin_step2a.png')

# Open Actions list
print('  Pressing Shift+/')
pyautogui.hotkey('shift', '/')
time.sleep(2.0)
ss('fin_step2b_actions.png')

# Type reapy and run
print('  Typing reapy')
pyautogui.typewrite('reapy', interval=0.12)
time.sleep(1.0)
ss('fin_step2c_typed.png')

print('  Pressing Enter')
pyautogui.press('enter')
time.sleep(4.0)
ss('fin_step2d_done.png')

# ── Step 3: Connect to reapy ──────────────────────────────────────────────────
print('\n=== Step 3: Connect to reapy ===')
with warnings.catch_warnings():
    warnings.simplefilter('ignore')
    import reapy

def connect_reapy():
    from reapy.tools.network import machines as _m
    import importlib
    from reapy.tools.network.client import Client as _C
    _m.CLIENT = None; _m.CLIENTS.clear()
    socket.setdefaulttimeout(8.0)
    _port = reapy.config.REAPY_SERVER_PORT
    _c = _C(_port, 'localhost')
    # Reset: infinite timeout so render doesn't disconnect
    socket.setdefaulttimeout(None)
    _c._socket.settimeout(None)
    _m.CLIENT = _c; _m.CLIENTS['localhost'] = _c; _m.CLIENTS[None] = _c
    importlib.reload(reapy.reascript_api)
    return _c, reapy.Project()

connected = False
for attempt in range(15):
    try:
        _c, proj = connect_reapy()
        print(f'  Connected: {proj.name!r}')
        connected = True
        break
    except Exception as e:
        print(f'  Attempt {attempt+1}: {type(e).__name__}')
        if attempt % 5 == 4:
            # Retry the GUI actions
            print('  Re-trying GUI enable...')
            focus_reaper()
            pyautogui.click(cx, cy)
            time.sleep(0.4)
            pyautogui.hotkey('shift', '/')
            time.sleep(1.5)
            pyautogui.typewrite('reapy', interval=0.1)
            time.sleep(0.8)
            ss(f'fin_retry{attempt}.png')
            pyautogui.press('enter')
            time.sleep(4.0)
        else:
            time.sleep(2.0)

if not connected:
    print('ERROR: Cannot connect')
    sys.exit(1)

# ── Step 4: Set up render and fire ───────────────────────────────────────────
print('\n=== Step 4: Render ===')
import reapy.reascript_api as RPR

# Check items
n_tracks = RPR.CountTracks(proj.id)
end_time = 0.0
for i in range(n_tracks):
    tr = RPR.GetTrack(proj.id, i)
    tname = str(RPR.GetSetMediaTrackInfo_String(tr, 'P_NAME', '', False)[3]).strip()
    n = RPR.CountTrackMediaItems(tr)
    for j in range(n):
        item = RPR.GetTrackMediaItem(tr, j)
        pos    = RPR.GetMediaItemInfo_Value(item, 'D_POSITION')
        length = RPR.GetMediaItemInfo_Value(item, 'D_LENGTH')
        end_time = max(end_time, pos + length)
    print(f'  Track {i} {tname!r}: {n} items')
print(f'  End time: {end_time:.2f}s')

# Ensure items are at bar 1 (position 0)
if end_time > 30.0 or end_time < 1.0:
    print(f'  WARNING: end_time={end_time:.2f}s is unexpected, fixing item positions...')
    for i in range(n_tracks):
        tr = RPR.GetTrack(proj.id, i)
        n = RPR.CountTrackMediaItems(tr)
        for j in range(n):
            item = RPR.GetTrackMediaItem(tr, j)
            pos = RPR.GetMediaItemInfo_Value(item, 'D_POSITION')
            if abs(pos) > 0.01:
                RPR.SetMediaItemInfo_Value(item, 'D_POSITION', 0.0)
                print(f'  Moved track {i} item {j} from {pos:.2f}s to 0')
    RPR.UpdateArrange()
    # Recalculate end time
    end_time = 0.0
    for i in range(n_tracks):
        tr = RPR.GetTrack(proj.id, i)
        for j in range(RPR.CountTrackMediaItems(tr)):
            item = RPR.GetTrackMediaItem(tr, j)
            pos    = RPR.GetMediaItemInfo_Value(item, 'D_POSITION')
            length = RPR.GetMediaItemInfo_Value(item, 'D_LENGTH')
            end_time = max(end_time, pos + length)
    print(f'  New end time: {end_time:.2f}s')

# Configure render settings
# CRITICAL: RENDER_BOUNDSFLAG = 1.0 = "Entire project" (NOT 0 = Custom)
RPR.GetSetProjectInfo_String(proj.id, 'RENDER_FILE',    OUT_DIR,  True)
RPR.GetSetProjectInfo_String(proj.id, 'RENDER_PATTERN', OUT_STEM, True)
RPR.GetSetProjectInfo(proj.id, 'RENDER_SRATE',    44100.0, True)
RPR.GetSetProjectInfo(proj.id, 'RENDER_CHANNELS',  2.0,    True)
RPR.GetSetProjectInfo(proj.id, 'RENDER_BOUNDSFLAG', 1.0,   True)  # 1 = entire project
RPR.SetEditCurPos(0.0, False, False)

# Set time selection to cover project just in case
RPR.GetSet_LoopTimeRange(True, True, 0.0, end_time + 1.0, False)
RPR.GetSet_LoopTimeRange(True, False, 0.0, end_time + 1.0, False)

RPR.Main_SaveProject(proj.id, False)
print('  Settings saved')

if os.path.exists(OUT_WAV):
    os.remove(OUT_WAV)
    print('  Removed old WAV')

ss('fin_step4_before.png')

# Fire render with short timeout (EXPECTED to timeout since render blocks reapy)
print(f'  Firing render command for {end_time:.1f}s project...')
try:
    _c._socket.settimeout(3.0)
    RPR.Main_OnCommand(41824, 0)
    print('  Render returned normally')
except Exception as e:
    print(f'  Got expected exception: {type(e).__name__} — render in progress')

# ── Step 5: Poll for output ───────────────────────────────────────────────────
print('\n=== Step 5: Polling for WAV ===')
MIN_SIZE = 44100 * 2 * 3 * 4   # ~4s

start = time.time()
for i in range(180):
    time.sleep(1.0)
    if os.path.exists(OUT_WAV):
        sz = os.path.getsize(OUT_WAV)
        dur = sz / (44100 * 2 * 3)
        if sz > MIN_SIZE:
            elapsed = time.time() - start
            print(f'\n=== SUCCESS ===')
            print(f'File:     {OUT_WAV}')
            print(f'Size:     {sz//1024} KB')
            print(f'Duration: ~{dur:.1f}s')
            print(f'Time:     {elapsed:.0f}s')
            ss('fin_success.png')
            sys.exit(0)
        else:
            print(f'  [{i+1}s] {sz}b (growing...)')
    elif (i+1) % 15 == 0:
        print(f'  [{i+1}s] waiting...')
        ss(f'fin_wait{i+1}.png')

print(f'\nTIMEOUT')
ss('fin_timeout.png')
sys.exit(1)
