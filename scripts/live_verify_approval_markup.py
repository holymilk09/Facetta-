"""Live end-to-end for the approval checklist + markup edits (real XAI key).

Run manually: uv run python scripts/live_verify_approval_markup.py
Exercises the REAL providers — never run in CI. Flow: design → linked render
→ checklist → NO + interpret → markup read/apply (Grok scoped spec edit +
localized image edit) → fresh checklist → all-YES auto-pin → factory sheet
lettering the updated spec + approval footer.
"""

import base64
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, "src")
sys.path.insert(0, "tests")

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from conftest import HALO_SPEC
from facetta.db import Base, get_db
from facetta.main import app

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else ".")

engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                       poolclass=StaticPool)
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine, autoflush=False)


def override():
    s = Session()
    try:
        yield s
    finally:
        s.close()


app.dependency_overrides[get_db] = override
client = TestClient(app)


def step(label, response, expect=(200, 201)):
    ok = response.status_code in expect
    print(f"{'OK ' if ok else 'FAIL'} {label} [{response.status_code}]",
          flush=True)
    if not ok:
        print(response.text[:800])
        sys.exit(1)
    return response.json()


# 1. design + linked render
design = step("create design", client.post(
    "/designs", json={"created_by": "usr_ana", "spec": HALO_SPEC}))
render = step("render linked to design", client.post(
    "/assets/render", json={
        "piece_description": "an oval diamond halo engagement ring, 1.5ct "
                             "oval center, round diamond halo, 18k white "
                             "gold band",
        "design_id": design["design_id"], "created_by": "usr_ana"}))
aid = render["asset_id"]
hero = base64.b64decode(render["image_b64"])
(OUT / "lv_hero.png").write_bytes(hero)

# 2. checklist resolves the spec through the link
cl = step("checklist from design link", client.post(
    f"/assets/{aid}/checklist", json={"mode": "auto_pin",
                                      "created_by": "usr_ana"}))
print("   items:", flush=True)
for i in cl["items"]:
    print(f"    [{i['key']:16}] {i['label']}: {i['fact']}", flush=True)

# 3. a NO with live interpretation
no = step("NO on band + live interpret", client.post(
    f"/assets/{aid}/checklist/respond", json={
        "item_key": "band", "approved": False,
        "note": "band feels heavy — take the width down to 1.8",
        "interpret": True, "created_by": "usr_ana"}))
print("   understood_as:", no["interpretation"]["understood_as"], flush=True)
print("   action:", no["interpretation"]["action"],
      "confidence:", no["interpretation"]["confidence"], flush=True)

# 4. markup: draw a canvas mark + handwriting-style note on the hero
im = Image.open(io.BytesIO(hero)).convert("RGB")
d = ImageDraw.Draw(im)
w, h = im.size
d.ellipse([w * 0.30, h * 0.55, w * 0.70, h * 0.85], outline=(255, 40, 40),
          width=max(4, w // 200))
d.text((w * 0.32, h * 0.87), "band width -> 1.8 mm", fill=(255, 40, 40),
       font_size=max(24, w // 30))
buf = io.BytesIO()
im.save(buf, format="PNG")
(OUT / "lv_marked.png").write_bytes(buf.getvalue())

read = step("markup/read (live vision)", client.post(
    f"/assets/{aid}/markup/read", json={
        "marked_image_base64": base64.b64encode(buf.getvalue()).decode(),
        "created_by": "usr_ana"}))
print("   understood_as:", read["understood_as"], flush=True)
for a in read["annotations"]:
    print(f"   - [{a.get('target_section')}] {a['region_description']}: "
          f"{a['change_instruction']} (conf {a['confidence']})", flush=True)

# 5. apply the confirmed annotation (live scoped spec edit + image edit)
annotation = read["annotations"][0]
annotation.setdefault("target_section", "band")
apply = step("markup/apply (live lockstep edit)", client.post(
    f"/assets/{aid}/markup/apply", json={
        "annotations": [{
            "region_description": annotation["region_description"],
            "change_instruction": annotation["change_instruction"],
            "target_section": annotation["target_section"] or "band"}],
        "markup_asset_id": read["markup_asset_id"],
        "created_by": "usr_ana"}))
s0 = apply["steps"][0]
print("   spec_synced:", s0.get("spec_synced"),
      "| new version:", s0.get("new_spec_version"),
      "| drift:", s0.get("drift"), flush=True)
print("   changes:", s0.get("changes_summary"), flush=True)
print("   consistency:", apply["consistency"].get("consistent"),
      apply["consistency"].get("differences"), flush=True)
final_id = apply["final_asset_id"]
(OUT / "lv_edited.png").write_bytes(base64.b64decode(apply["image_b64"]))

# 6. fresh checklist on the edited version → all YES → auto-pin
cl2 = step("checklist on the edited version", client.post(
    f"/assets/{final_id}/checklist", json={"mode": "auto_pin",
                                           "created_by": "usr_ana"}))
band_fact = next(i["fact"] for i in cl2["items"] if i["key"] == "band")
print("   band fact now:", band_fact, flush=True)
last = None
for item in cl2["items"]:
    last = client.post(f"/assets/{final_id}/checklist/respond",
                       json={"item_key": item["key"], "approved": True,
                             "created_by": "usr_ana"})
body = last.json()
print("   auto-pinned:", body.get("pinned"), "-", body.get("message"),
      flush=True)

# 7. the factory sheet letters the UPDATED spec + the approval line
sheet = step("technical drawing (live)", client.post(
    f"/assets/{final_id}/technical-drawing", json={
        "facetta_template": True, "house": "Maison Vérité",
        "signature": "Ana Vérité", "piece_name": "The Vérité Halo"}))
print("   spec_source:", sheet["spec_source"], flush=True)
print("   approval:", sheet["approval"], flush=True)
(OUT / "lv_factory_sheet.svg").write_text(sheet["framed_svg"])

# 8. negatives
r = client.post(f"/assets/{aid}/pin")
print(f"   explicit-pin gate on v1 (declined band): {r.status_code} "
      f"(expect 409 outstanding={r.json().get('outstanding')})", flush=True)

print(">> done", flush=True)
