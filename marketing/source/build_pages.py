"""Generate the promo pages (1920x1080 unless noted) for screenshotting."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PAGES = os.path.join(HERE, "pages")
os.makedirs(PAGES, exist_ok=True)

ROW = os.environ.get("ROW", "../renders/row.png")
S5 = os.environ.get("S5", "../renders/stage5.png")
S2 = os.environ.get("S2", "../renders/stage2.png")
PED = [0.1171, 0.3085, 0.5, 0.6915, 0.8829]   # pedestal centres (studio.py)

CSS = """
:root {
  --bg: #0b0d11; --surface: #14171d; --surface-2: #1b1f27; --line: #2a2f3a;
  --ink: #eef0f4; --ink-2: #a7adba; --ink-3: #6c7382;
  --accent: #ff7a1a; --accent-soft: rgba(255,122,26,.16); --cool: #5aa9ff;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { width: WIDTHpx; height: HEIGHTpx; overflow: hidden; }
body { background: var(--bg); color: var(--ink); font-family: Inter, sans-serif;
       -webkit-font-smoothing: antialiased; position: relative; }
svg.i { width: 1em; height: 1em; fill: none; stroke: currentColor; stroke-width: 1.8;
        stroke-linecap: round; stroke-linejoin: round; }
.brand { display: flex; align-items: center; gap: 14px; font-weight: 600; font-size: 24px;
         letter-spacing: -.01em; }
.brand .mark { width: 44px; height: 44px; border-radius: 12px; background: var(--surface-2);
               border: 1px solid var(--line); display: grid; place-items: center; }
.brand .mark svg { width: 30px; height: 30px; }
.brand small { font-weight: 500; font-size: 15px; color: var(--ink-3); margin-left: 6px;
               padding: 4px 10px; border: 1px solid var(--line); border-radius: 999px; }
h1 { font-weight: 650; letter-spacing: -.035em; line-height: 1.02; }
.lead { color: var(--ink-2); font-size: 26px; line-height: 1.45; letter-spacing: -.005em; }
.chip { width: 64px; height: 64px; border-radius: 16px; display: grid; place-items: center;
        background: rgba(22,25,32,.88); border: 1px solid #333946; color: #cdd2dd;
        font-size: 28px; backdrop-filter: blur(8px); position: relative; }
.chip.now { border-color: var(--accent); color: #fff; background: #2a1a0e;
            box-shadow: 0 0 0 4px var(--accent-soft), 0 0 36px rgba(255,122,26,.45); }
.chip.past { opacity: .38; }
.dot { width: 8px; height: 8px; border-radius: 50%; background: #3a404d; }
.dot.past { opacity: .45; }
"""

# Line icons, 24x24 (drawn for this add-on, not Blender's icon set).
ICONS = {
    "logo": '<path d="M3 16h18" stroke="#6c7382"/><circle cx="6" cy="16" r="2" fill="#6c7382" stroke="none"/>'
            '<circle cx="11" cy="16" r="2" fill="#6c7382" stroke="none"/>'
            '<circle cx="17" cy="16" r="3" stroke="#ff7a1a"/>'
            '<path d="M17 9a5 5 0 0 0-9.3-2.5M7.2 3.8l.5 2.7 2.7-.5" stroke="#ff7a1a"/>',
    "cube": '<path d="M12 3 20 7.5v9L12 21 4 16.5v-9z"/><path d="M4 7.5 12 12l8-4.5M12 12v9"/>',
    "add": '<path d="M12 5v14M5 12h14"/>',
    "subd": '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M12 4v16M4 12h16"/>',
    "material": '<circle cx="12" cy="12" r="8"/><path d="M8.3 10a4.2 4.2 0 0 1 3.7-3.2"/>',
    "polish": '<path d="M12 3.5 13.9 10 20.5 12l-6.6 2L12 20.5 10.1 14 3.5 12l6.6-2z"/>',
    "move": '<path d="M12 3v18M3 12h18M9 6l3-3 3 3M9 18l3 3 3-3M6 9l-3 3 3 3M18 9l3 3-3 3"/>',
    "bookmark": '<path d="M7 3.5h10v17l-5-3.6-5 3.6z"/>',
    "file": '<path d="M6.5 3h7.5l4 4v14h-11.5z"/><path d="M14 3v4h4"/>',
    "trash": '<path d="M4.5 7h15M9.5 7V4.5h5V7M6.5 7l1 13h9l1-13"/>',
    "modifier": '<path d="M14.8 5.2a4 4 0 0 0-5.3 5.3L4 16l4 4 5.5-5.5a4 4 0 0 0 5.3-5.3l-2.6 2.6-2.9-.5-.5-2.9z"/>',
    "first": '<path d="M7 5v14M18 6l-6 6 6 6"/>',
    "prev": '<path d="M15 6l-6 6 6 6"/>',
    "next": '<path d="M9 6l6 6-6 6"/>',
    "last": '<path d="M17 5v14M6 6l6 6-6 6"/>',
    "restore": '<path d="M4 12a8 8 0 1 0 2.4-5.7M4 4v4h4"/>',
    "pin": '<path d="M9 4h6l-1 6 3 3H7l3-3zM12 13v7"/>',
    "search": '<circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/>',
    "folder": '<path d="M3.5 7.5a2 2 0 0 1 2-2h4l2 2h7a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "clock": '<circle cx="12" cy="12" r="8"/><path d="M12 8v4.5l3 2"/>',
    "arrow": '<path d="M4 12h15M13 6l6 6-6 6"/>',
    "disk": '<ellipse cx="12" cy="6" rx="7.5" ry="2.8"/><path d="M4.5 6v12c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8V6M4.5 12c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8"/>',
}


def icon(name, cls="i"):
    return '<svg class="%s" viewBox="0 0 24 24">%s</svg>' % (cls, ICONS[name])


def page(name, body, extra_css="", width=1920, height=1080):
    html = """<!doctype html><html><head><meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;650;700&display=block" rel="stylesheet">
<style>%s%s</style></head><body>%s</body></html>""" % (
        CSS.replace("WIDTH", str(width)).replace("HEIGHT", str(height)), extra_css, body)
    with open(os.path.join(PAGES, name + ".html"), "w") as fh:
        fh.write(html)
    return {"name": name, "width": width, "height": height}


def brand(sub="for Blender"):
    return ('<div class="brand"><div class="mark">%s</div>History Timeline<small>%s</small></div>'
            % (icon("logo"), sub))


built = []

# ---------------------------------------------------------------- 01 hero
STAGES = [("cube", "Add Cube"), ("add", "Add Monkey"), ("subd", "Subdivide"),
          ("material", "Material"), ("polish", "Final polish")]
strip = []
for i, (ic, label) in enumerate(STAGES):
    x = PED[i] * 1920
    cls = "chip now" if i == len(STAGES) - 1 else "chip"
    strip.append('<div class="stop" style="left:%.0fpx"><div class="%s">%s</div><span>%s</span></div>'
                 % (x, cls, icon(ic), label))
    if i < len(STAGES) - 1:   # smaller intermediate steps between milestones
        for k in range(1, 6):
            xx = x + (PED[i + 1] - PED[i]) * 1920 * k / 6
            strip.append('<div class="dot" style="position:absolute;left:%.0fpx;top:28px"></div>' % (xx - 4))
built.append(page("01-hero", """
<img class="render" src="%s">
<div class="fade"></div>
<header>
  %s
  <h1>Undo that survives<br>closing Blender.</h1>
  <p class="lead">Every change becomes a step on a visual timeline, saved to disk.<br>
  Click any step to go back or forward, today or next week.</p>
</header>
<div class="track"><div class="line"></div><div class="line lit"></div>%s
  <div class="marker" style="left:%.0fpx"></div></div>
""" % (ROW, brand(), "".join(strip), PED[-1] * 1920 + 52), """
.render { position: absolute; left: 0; top: 280px; width: 1920px; height: 800px; }
.fade { position: absolute; left: 0; top: 280px; width: 1920px; height: 260px;
        background: linear-gradient(var(--bg), rgba(11,13,17,0)); }
header { position: absolute; left: 120px; top: 92px; width: 1300px; }
header h1 { font-size: 84px; margin-top: 44px; }
header .lead { margin-top: 26px; }
.track { position: absolute; left: 0; top: 890px; width: 1920px; height: 120px; }
.track .line { position: absolute; top: 31px; height: 2px; left: %.0fpx; width: %.0fpx;
               background: #2f3542; }
.track .line.lit { background: linear-gradient(90deg, rgba(255,122,26,.15), var(--accent)); height: 2px; }
.stop { position: absolute; top: 0; transform: translateX(-50%%); display: flex; flex-direction: column;
        align-items: center; gap: 14px; }
.stop span { color: var(--ink-2); font-size: 18px; font-weight: 500; white-space: nowrap; }
.stop .chip.now + span { color: var(--ink); }
.marker { position: absolute; top: -6px; width: 3px; height: 76px; border-radius: 2px;
          background: var(--accent); box-shadow: 0 0 16px rgba(255,122,26,.8); }
""" % (PED[0] * 1920, (PED[-1] - PED[0]) * 1920)))

# ------------------------------------------------------------ 02 interface
steps = [
    ("file", "Opened blockout.blend", ""), ("cube", "Add Cube", "Cube"), ("trash", "Delete", ""),
    ("add", "Add Monkey", "Suzanne"), ("move", "Move", "Suzanne"), ("move", "Rotate", "Suzanne"),
    ("modifier", "Add Modifier", "Suzanne"), ("subd", "Subdivision Set", "Suzanne"),
    ("polish", "Shade Smooth", "Suzanne"), ("bookmark", "Blockout done", ""),
    ("material", "New Material", "Suzanne"), ("material", "Edit Suzanne", "Suzanne"),
    ("move", "Scale", "Suzanne"), ("material", "Edit Suzanne", "Suzanne"),
]
strip_cells = []
for n, (ic, _, _) in enumerate(steps, start=1):
    cls = "cell"
    if n == len(steps):
        cls += " now"
    if n == 12:
        cls += " hover"
    strip_cells.append('<div class="%s">%s</div>' % (cls, icon(ic)))
    if n == 3:
        strip_cells.append('<div class="gap"></div>')
rows = []
for n in range(len(steps), len(steps) - 9, -1):
    ic, label, detail = steps[n - 1]
    tags = ""
    if n == 10:
        tags += '<em>%s</em>' % icon("pin")
    if n == len(steps):
        tags += '<em class="cur">%s</em>' % icon("prev")
    rows.append('<div class="row%s">%s<b>#%d</b> %s%s<span class="tags">%s</span></div>' % (
        " sel" if n == 12 else "", icon(ic), n, label,
        ' <i>(%s)</i>' % detail if detail else "", tags))
built.append(page("02-interface", """
<div class="app">
  <div class="topbar"><span class="logo-dot"></span>File&nbsp;&nbsp;&nbsp;Edit&nbsp;&nbsp;&nbsp;Render&nbsp;&nbsp;&nbsp;Window&nbsp;&nbsp;&nbsp;Help
    <span class="ws"><b>Layout</b>&nbsp;&nbsp;Modeling&nbsp;&nbsp;Sculpting&nbsp;&nbsp;Shading</span></div>
  <div class="main">
    <div class="viewport"><img src="%s"><div class="vp-label">User Perspective<br><span>(1) Collection | Suzanne</span></div></div>
    <aside class="npanel">
      <div class="tabs"><span>Item</span><span>Tool</span><span>View</span><span class="on">History</span></div>
      <div class="panel">
        <div class="ph">%s History Timeline</div>
        <div class="mini">%s</div>
        <div class="btns"><div class="btn wide">%s Checkpoint</div><div class="btn">%s</div><div class="btn">%s</div></div>
        <div class="search">%s Search steps</div>
        <div class="list">%s</div>
        <div class="pager">%s <span>Page 1 / 2</span> %s</div>
        <div class="detail"><div class="when">%s 2026-09-28 14:32:05</div>
          <div class="btns"><div class="btn wide primary">%s Restore</div><div class="btn">%s</div><div class="btn">%s</div></div></div>
      </div>
    </aside>
  </div>
  <div class="statusbar">
    <span class="hint">Select&nbsp;&nbsp;&nbsp;&nbsp;Pan View&nbsp;&nbsp;&nbsp;&nbsp;Context Menu</span>
    <div class="strip">
      <div class="nav">%s%s</div>%s<div class="nav">%s%s</div><span class="count">14/14</span>
    </div>
  </div>
  <div class="tooltip">
    <div class="tt-title">#12&nbsp;&nbsp;Edit Suzanne</div>
    <div>Active: Suzanne</div><div>2026-09-28 14:31:47</div>
    <div>Took 12.4 KB on disk (file is 10.6 MB)</div>
    <div class="tt-hint">Click to restore this state</div>
  </div>
</div>
<div class="caption">%s<div><h1>Your history, one click away.</h1>
<p class="lead">A strip of steps in the status bar, and a searchable list in the sidebar.</p></div></div>
""" % (S5, icon("clock"), "".join('<i class="m%s"></i>' % (" now" if k == 13 else "") for k in range(14)),
       icon("bookmark"), icon("folder"), icon("trash"), icon("search"), "".join(rows),
       icon("prev"), icon("next"), icon("clock"), icon("restore"), icon("pin"), icon("trash"),
       icon("first"), icon("prev"), "".join(strip_cells), icon("next"), icon("last"), brand()), """
body { background: radial-gradient(1400px 700px at 30% 0%, #1a1d25, var(--bg)); }
.app { position: absolute; left: 90px; top: 250px; width: 1740px; height: 790px; border-radius: 14px;
       overflow: hidden; background: #1d1d1d; border: 1px solid #333;
       box-shadow: 0 40px 120px rgba(0,0,0,.6); font-size: 15px; color: #d4d4d4; }
.topbar { height: 36px; background: #232323; border-bottom: 1px solid #111; display: flex; align-items: center;
          padding: 0 14px; gap: 0; color: #cfcfcf; }
.logo-dot { width: 16px; height: 16px; border-radius: 50%; background: var(--accent); margin-right: 18px; }
.ws { margin-left: 40px; color: #9a9a9a; } .ws b { color: #fff; background: #3a3a3a; padding: 5px 10px; border-radius: 5px; font-weight: 500; }
.main { position: absolute; top: 36px; bottom: 40px; left: 0; right: 0; display: flex; }
.viewport { flex: 1; position: relative; background: #111; overflow: hidden; }
.viewport img { width: 100%; height: 100%; object-fit: cover; object-position: 50% 45%; }
.vp-label { position: absolute; left: 18px; top: 14px; color: #e6e6e6; font-size: 14px; line-height: 1.5; }
.vp-label span { color: #aaa; }
.npanel { width: 430px; background: #2b2b2b; border-left: 1px solid #111; display: flex; }
.tabs { width: 30px; background: #232323; display: flex; flex-direction: column; padding-top: 10px; }
.tabs span { writing-mode: vertical-rl; transform: rotate(180deg); padding: 12px 6px; color: #9a9a9a; font-size: 13px; }
.tabs span.on { background: #3d3d3d; color: #fff; border-left: 2px solid var(--accent); }
.panel { flex: 1; padding: 12px 14px; display: flex; flex-direction: column; gap: 10px; }
.ph { color: #fff; font-weight: 600; display: flex; gap: 8px; align-items: center; }
.ph svg { color: var(--accent); }
.mini { height: 26px; background: #232323; border-radius: 6px; display: flex; gap: 3px; align-items: center; padding: 0 8px; }
.mini i { flex: 1; height: 12px; border-radius: 3px; background: #4a4a4a; }
.mini i.now { background: var(--accent); }
.btns { display: flex; gap: 4px; }
.btn { height: 30px; min-width: 34px; background: #3d3d3d; border-radius: 5px; display: flex; align-items: center;
       justify-content: center; gap: 8px; color: #e6e6e6; font-size: 14px; padding: 0 10px; }
.btn.wide { flex: 1; } .btn.primary { background: #4772b3; color: #fff; }
.search { height: 30px; background: #1d1d1d; border-radius: 5px; color: #7d7d7d; display: flex; align-items: center; gap: 8px; padding: 0 10px; font-size: 14px; }
.list { background: #232323; border-radius: 6px; padding: 4px; }
.row { height: 34px; display: flex; align-items: center; gap: 10px; padding: 0 10px; border-radius: 4px; color: #d6d6d6; font-size: 14.5px; white-space: nowrap; }
.row b { color: #8e8e8e; font-weight: 500; width: 30px; } .row i { color: #8a8a8a; font-style: normal; }
.row svg { color: #bdbdbd; font-size: 17px; }
.row.sel { background: #4772b3; color: #fff; } .row.sel b, .row.sel i, .row.sel svg { color: #e8efff; }
.row .tags { margin-left: auto; display: flex; gap: 6px; } .row .tags em { color: #9a9a9a; font-style: normal; }
.row .tags em.cur { color: var(--accent); }
.pager { display: flex; justify-content: space-between; align-items: center; color: #9a9a9a; font-size: 13px; padding: 0 6px; }
.detail { display: flex; flex-direction: column; gap: 8px; } .when { color: #bdbdbd; display: flex; gap: 8px; align-items: center; font-size: 14px; }
.foot { color: #8a8a8a; font-size: 13px; margin-top: auto; }
.statusbar { position: absolute; bottom: 0; left: 0; right: 0; height: 40px; background: #232323; border-top: 1px solid #111;
             display: flex; align-items: center; padding: 0 14px; color: #a9a9a9; font-size: 13.5px; }
.strip { margin-left: auto; display: flex; align-items: center; gap: 2px; }
.nav { display: flex; gap: 2px; margin: 0 6px; }
.nav svg, .cell svg { width: 17px; height: 17px; }
.nav svg { background: #3a3a3a; border-radius: 4px; padding: 3px; width: 24px; height: 24px; color: #cfcfcf; }
.cell { width: 30px; height: 28px; border-radius: 5px; background: #3a3a3a; display: grid; place-items: center; color: #d0d0d0; }
.cell.now { background: #5a3a1c; color: #fff; box-shadow: inset 0 0 0 1.5px var(--accent); }
.cell.hover { background: #555; color: #fff; }
.gap { width: 8px; }
.count { margin-left: 10px; color: #bdbdbd; }
.tooltip { position: absolute; right: 250px; bottom: 50px; background: #181818; border: 1px solid #3a3a3a;
           border-radius: 7px; padding: 12px 14px; font-size: 14px; line-height: 1.6; color: #cfcfcf;
           box-shadow: 0 12px 30px rgba(0,0,0,.5); }
.tt-title { color: #fff; font-weight: 600; } .tt-hint { color: #8d8d8d; margin-top: 4px; }
.caption { position: absolute; left: 120px; top: 70px; display: flex; flex-direction: column; gap: 22px; }
.caption h1 { font-size: 56px; } .caption .lead { font-size: 24px; margin-top: 10px; }
.caption { flex-direction: row; align-items: flex-end; gap: 0; justify-content: space-between; width: 1680px; }
.caption .brand { order: 2; }
"""))

# ------------------------------------------------------------- 03 rollback
def mini_strip(current, total=14, past_dim=True):
    out = []
    for n in range(1, total + 1):
        cls = "sc"
        if n == current:
            cls += " now"
        elif n > current:
            cls += " rb"
        out.append('<i class="%s"></i>' % cls)
    return '<div class="ms">%s</div>' % "".join(out)


built.append(page("03-rollback", """
<header>%s<h1>Roll back. Roll forward.<br>Nothing is lost.</h1></header>
<div class="cards">
  <div class="card"><img src="%s"><div class="meta"><div class="k">Step 14 · current</div>
    <div class="v">Final polish</div>%s<div class="note">Marker at the latest step</div></div></div>
  <div class="mid"><div class="pill">%s one click</div></div>
  <div class="card"><img src="%s"><div class="meta"><div class="k">Step 4 · restored</div>
    <div class="v">Add Monkey</div>%s<div class="note"><b>Steps 5–14 are kept</b>, greyed out. Click one to roll forward again.</div></div></div>
</div>
""" % (brand(), S5, mini_strip(14), icon("restore"), S2, mini_strip(4)), """
header { position: absolute; left: 120px; top: 80px; }
header h1 { font-size: 72px; margin-top: 40px; }
.cards { position: absolute; left: 120px; right: 120px; top: 390px; display: flex; align-items: center; gap: 36px; }
.card { flex: 1; background: var(--surface); border: 1px solid var(--line); border-radius: 22px; overflow: hidden; }
.card img { display: block; width: 100%; height: 420px; object-fit: cover; object-position: 50% 42%; }
.meta { padding: 22px 28px 26px; }
.k { color: var(--ink-3); font-size: 17px; font-weight: 500; letter-spacing: .01em; }
.v { font-size: 30px; font-weight: 600; margin-top: 4px; letter-spacing: -.02em; }
.ms { display: flex; gap: 6px; margin-top: 20px; }
.sc { flex: 1; height: 18px; border-radius: 5px; background: #3a404d; }
.sc.now { background: var(--accent); box-shadow: 0 0 14px rgba(255,122,26,.6); }
.sc.rb { background: #3a404d; opacity: .35; }
.note { color: var(--ink-2); font-size: 18px; margin-top: 16px; } .note b { color: var(--ink); font-weight: 600; }
.mid { width: 150px; display: grid; place-items: center; }
.pill { display: flex; gap: 10px; align-items: center; padding: 12px 18px; border-radius: 999px; font-size: 18px;
        border: 1px solid var(--accent); color: var(--ink); background: var(--accent-soft); white-space: nowrap; }
.pill svg { color: var(--accent); font-size: 22px; }
"""))

# -------------------------------------------------------------- 04 storage
# Deduplication diagram: each row is a step, each cell a stored piece.
rng_new = {1: [3, 9], 2: [9], 3: [14, 15], 4: [6], 5: [9, 21]}
grid = []
for r in range(6):
    cells = []
    for c in range(24):
        if r == 0:
            cls = "base"
        elif c in rng_new.get(r, []):
            cls = "new"
        else:
            cls = "shared"
        cells.append('<i class="%s"></i>' % cls)
    grid.append('<div class="gr"><span>Step %d</span>%s</div>' % (r + 1, "".join(cells)))
built.append(page("04-storage", """
<header>%s<h1>Only what changed<br>is stored.</h1>
<p class="lead">Steps are deduplicated at Blender's own data-block level,<br>so a long history stays small.</p></header>
<div class="hero"><div class="label">10,000 steps of a 10.6 MB scene</div><div class="fig">305 MB</div>
  <div class="sub">on disk. Keeping a full copy of every step would take <b>106 GB</b>.</div></div>
<div class="diagram"><div class="dh">How steps share data</div>%s
  <div class="legend"><span><i class="base"></i>Stored once (first step)</span><span><i class="shared"></i>Reused from earlier steps</span><span><i class="new"></i>New data</span></div></div>
<div class="tiles">
  <div class="tile"><div class="tl">Move an object</div><div class="tv">0.13 MB</div></div>
  <div class="tile"><div class="tl">Edit one vertex</div><div class="tv">0.19 MB</div></div>
  <div class="tile"><div class="tl">Add a cube</div><div class="tv">0.03 MB</div></div>
  <div class="tile"><div class="tl">First step, whole file</div><div class="tv">108 MB</div></div>
  <div class="tcap">Added per step on a 317 MB scene</div>
</div>
<div class="fn">Measured with Blender 4.2 on test scenes. Your numbers depend on how much each step changes.</div>
""" % (brand(), "".join(grid)), """
header { position: absolute; left: 120px; top: 80px; }
header h1 { font-size: 72px; margin-top: 40px; } header .lead { margin-top: 24px; }
.hero { position: absolute; left: 120px; top: 610px; width: 760px; }
.label { color: var(--ink-2); font-size: 22px; font-weight: 500; }
.fig { font-size: 150px; font-weight: 650; letter-spacing: -.045em; line-height: 1; margin-top: 12px; }
.sub { color: var(--ink-2); font-size: 22px; margin-top: 18px; line-height: 1.5; } .sub b { color: var(--ink); font-weight: 600; }
.diagram { position: absolute; right: 120px; top: 110px; width: 860px; background: var(--surface);
           border: 1px solid var(--line); border-radius: 22px; padding: 30px 32px; }
.dh { font-size: 20px; font-weight: 600; margin-bottom: 18px; }
.gr { display: flex; align-items: center; gap: 4px; margin: 7px 0; }
.gr span { width: 78px; color: var(--ink-3); font-size: 15px; font-weight: 500; }
.gr i, .legend i { width: 26px; height: 26px; border-radius: 5px; display: inline-block; }
.base { background: #4a5263; } .shared { background: transparent; box-shadow: inset 0 0 0 1.5px #353b48; }
.new { background: var(--accent); }
.legend { display: flex; gap: 26px; margin-top: 20px; color: var(--ink-2); font-size: 15px; }
.legend span { display: flex; align-items: center; gap: 9px; } .legend i { width: 16px; height: 16px; border-radius: 4px; }
.tiles { position: absolute; right: 120px; top: 660px; width: 860px; display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; }
.tile { background: var(--surface); border: 1px solid var(--line); border-radius: 16px; padding: 20px 20px 22px; }
.tl { color: var(--ink-2); font-size: 16px; font-weight: 500; } .tv { font-size: 36px; font-weight: 600; margin-top: 8px; letter-spacing: -.02em; }
.tcap { grid-column: 1 / -1; color: var(--ink-3); font-size: 15px; }
.fn { position: absolute; left: 120px; bottom: 56px; color: var(--ink-3); font-size: 15px; }
"""))

# ---------------------------------------------------------- 05 Ctrl+Z
UNDO_STEPS = ["cube", "add", "move", "subd", "polish", "bookmark", "material", "move", "material", "polish"]
xs = [230 + i * 162 for i in range(len(UNDO_STEPS))]
chips = []
for i, (ic, x) in enumerate(zip(UNDO_STEPS, xs)):
    cls = "chip now" if i == len(UNDO_STEPS) - 1 else "chip"
    chips.append('<div class="c" style="left:%dpx"><div class="%s">%s</div></div>' % (x, cls, icon(ic)))
divider_x = (xs[5] + xs[6]) // 2
built.append(page("05-undo", """
<header>%s<h1>Ctrl+Z keeps going,<br>even after reopening.</h1>
<p class="lead">Blender's undo history is gone once the file is closed.<br>History Timeline picks up where it ends.</p></header>
<div class="lane">
  <div class="seg-label" style="left:%dpx; width:%dpx">Earlier session · saved on the timeline</div>
  <div class="seg-label" style="left:%dpx; width:%dpx">This session</div>
  <div class="line"></div>%s
  <div class="divider" style="left:%dpx"><span>File closed &amp; reopened</span></div>
  <div class="arrow cool" style="left:%dpx; width:%dpx"><em>Ctrl+Z · Blender's undo</em></div>
  <div class="arrow warm" style="left:%dpx; width:%dpx"><em>Ctrl+Z · continues on the timeline</em></div>
</div>
<div class="keys"><kbd>Ctrl</kbd><b>+</b><kbd>Z</kbd><span>Same shortcut the whole way. Ctrl+Shift+Z goes forward again.</span></div>
<div class="fn">Optional: turn it off in the add-on preferences and Ctrl+Z is Blender's standard undo.</div>
""" % (brand(), xs[0] - 32, divider_x - xs[0], divider_x + 20, xs[-1] + 32 - divider_x - 20, "".join(chips),
       divider_x, divider_x, xs[-1] - divider_x, xs[1], divider_x - xs[1]), """
header { position: absolute; left: 120px; top: 80px; }
header h1 { font-size: 72px; margin-top: 40px; } header .lead { margin-top: 24px; }
.lane { position: absolute; left: 0; top: 560px; width: 1920px; height: 260px; }
.lane .line { position: absolute; left: %dpx; width: %dpx; top: 72px; height: 2px; background: #2f3542; }
.c { position: absolute; top: 40px; transform: translateX(-50%%); }
.seg-label { position: absolute; top: 0; color: var(--ink-2); font-size: 18px; font-weight: 500; text-align: center; }
.divider { position: absolute; top: 22px; height: 100px; border-left: 2px dashed #4a5263; }
.divider span { position: absolute; top: 106px; left: 50%%; transform: translateX(-50%%); white-space: nowrap;
                color: var(--ink-3); font-size: 15px; }
.arrow { position: absolute; top: 180px; height: 4px; border-radius: 2px; }
.arrow::before { content: ""; position: absolute; left: -2px; top: -8px; border: 10px solid transparent;
                 border-left: 0; border-right-width: 14px; }
.arrow em { position: absolute; top: 18px; left: 50%%; transform: translateX(-50%%); font-style: normal;
            font-size: 18px; font-weight: 500; color: var(--ink); white-space: nowrap; }
.arrow.cool { background: var(--cool); } .arrow.cool::before { border-right-color: var(--cool); }
.arrow.warm { background: var(--accent); } .arrow.warm::before { border-right-color: var(--accent); }
.keys { position: absolute; left: 120px; top: 900px; display: flex; align-items: center; gap: 12px; color: var(--ink-2); font-size: 20px; }
kbd { font-family: Inter, sans-serif; font-size: 20px; font-weight: 600; color: var(--ink); padding: 8px 16px;
      border-radius: 10px; background: var(--surface-2); border: 1px solid var(--line); box-shadow: 0 3px 0 #06070a; }
.keys b { color: var(--ink-3); font-weight: 500; } .keys span { margin-left: 18px; }
.fn { position: absolute; left: 120px; bottom: 56px; color: var(--ink-3); font-size: 15px; }
""" % (xs[0], xs[-1] - xs[0])))

# ------------------------------------------------------------- thumbnail
built.append(page("thumbnail", """
<img class="bg" src="%s"><div class="shade"></div>
<div class="t">%s<h1>Undo that survives<br>closing Blender.</h1>
<div class="ms">%s</div></div>
""" % (S5, brand(), "".join('<i class="%s"></i>' % ("now" if k == 9 else "") for k in range(10))), """
.bg { position: absolute; left: 0; top: 0; width: 1200px; height: 860px; object-fit: cover; object-position: 50% 40%; }
.shade { position: absolute; inset: 0; background: linear-gradient(rgba(11,13,17,0) 40%, rgba(11,13,17,.85) 60%, var(--bg) 71%); }
.t { position: absolute; left: 90px; right: 90px; bottom: 90px; }
.t .brand { font-size: 30px; } .t .brand .mark { width: 54px; height: 54px; } .t .brand .mark svg { width: 36px; height: 36px; }
.t h1 { font-size: 92px; margin-top: 30px; }
.ms { display: flex; gap: 8px; margin-top: 40px; }
.ms i { flex: 1; height: 22px; border-radius: 6px; background: #3a404d; }
.ms i.now { background: var(--accent); box-shadow: 0 0 18px rgba(255,122,26,.7); }
""", width=1200, height=1200))

# ------------------------------------------------------------------ icon
built.append(page("icon", """<div class="ic"><svg viewBox="0 0 24 24">%s</svg></div>""" % ICONS["logo"], """
body { background: transparent; }
.ic { position: absolute; inset: 16px; border-radius: 108px; display: grid; place-items: center;
      background: radial-gradient(circle at 30% 20%, #262b36, #11141a 70%); border: 4px solid #2c3240; }
.ic svg { width: 360px; height: 360px; fill: none; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }
""", width=512, height=512))

with open(os.path.join(PAGES, "pages.json"), "w") as fh:
    json.dump(built, fh)
print("built", [b["name"] for b in built])
