"""Push captured CAM_F0 frames through every VaVAM input stage and save each as an image.
Runs inside alpasim-e2e-vavam-driver:local (has torch, vam, tokenizer).  Usage:
  python visualize_stages.py <capture_session_dir> <out_dir> [max_frames]
"""
import sys, os, json, math
from pathlib import Path
import numpy as np, torch
from PIL import Image, ImageDraw

sys.path.insert(0, "/app")
from vavam_challenge.vavam_policy import VavamPolicy, _format_trajectory
from vam.datalib.transforms import NeuroNCAPTransform

sess = Path(sys.argv[1]); out = Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
max_frames = int(sys.argv[3]) if len(sys.argv) > 3 else 4
dev = "cuda"

policy = VavamPolicy(checkpoint_path=os.environ["VAVAM_CHECKPOINT_PATH"],
                     tokenizer_path=os.environ["VAVAM_TOKENIZER_PATH"], device=dev)
decoder = torch.jit.load(os.environ["VAVAM_DECODER_PATH"], map_location=dev).eval()
pre = NeuroNCAPTransform()

# route -> command, same rule as the sample driver
routes = [json.loads(l) for l in open(sess / "routes.jsonl")] if (sess / "routes.jsonl").exists() else []
def command_at(t_us):
    if not routes: return 2
    r = min(routes, key=lambda r: abs(r["timestamp_us"] - t_us))
    wps = [w for w in r["waypoints"] if w[0] >= 20.0] or r["waypoints"][-1:]
    if not wps: return 2
    y = wps[0][1]
    return 1 if y > 3.0 else (0 if y < -3.0 else 2)   # 0=right 1=left 2=straight (rig y = left)

frames = sorted(p for p in (sess / "images").glob("*_CAM_F0.jpg"))
print(f"{len(frames)} CAM_F0 frames captured; visualising first {max_frames}")
def denorm(t):  # [-1,1] CHW -> uint8 HWC
    return ((t.clamp(-1, 1) + 1) * 127.5).permute(1, 2, 0).byte().cpu().numpy()

summary = []
for p in frames[:max_frames]:
    t_us = int(p.name.split("_")[0]); tag = f"t{t_us//1000:06d}ms"
    raw = np.array(Image.open(p).convert("RGB"))                      # stage 0: 1920x1080
    crop = policy._resize_and_center_crop(raw, 900, 1600)             # stage 1: 1600x900
    x = pre(crop)                                                     # stage 2: 3x288x512 in [-1,1]
    with torch.no_grad():
        xt = x.unsqueeze(0).to(dev)
        toks = policy._tokenizer(xt)                                   # stage 3: tokens
        toks_grid = toks[0].cpu().numpy()                             # encoder returns (1, 18, 32) int64
        recon = decoder(toks)                                          # decoder wants (B, 18, 32)                              # stage 4: what the tokens encode
        if isinstance(recon, (tuple, list)): recon = recon[0]
        cmd = command_at(t_us)
        with torch.amp.autocast("cuda", dtype=torch.float16):
            traj = policy._vam(toks.unsqueeze(1), torch.tensor([[cmd]], device=dev), torch.float16)  # stage 5
        wps = _format_trajectory(traj)                                 # 6x2 metres, rig frame

    Image.fromarray(raw).save(out / f"{tag}_0_raw_1920x1080.jpg", quality=92)
    Image.fromarray(crop).save(out / f"{tag}_1_crop_1600x900.jpg", quality=92)
    Image.fromarray(denorm(x)).save(out / f"{tag}_2_input_288x512.png")
    # token map: each of the 576 codebook ids -> a colour (hash), upscaled x16 to 288x512
    rng = np.random.RandomState(0); palette = rng.randint(0, 255, (16385, 3)).astype(np.uint8)
    tok_img = palette[toks_grid]; Image.fromarray(tok_img).resize((512, 288), Image.NEAREST).save(out / f"{tag}_3_tokens_18x32.png")
    np.savetxt(out / f"{tag}_3_tokens_18x32.txt", toks_grid, fmt="%5d")
    Image.fromarray(denorm(recon[0])).save(out / f"{tag}_4_vq_reconstruction_288x512.png")
    # stage 5: waypoints, top-down (x forward = up)
    W = 400; img = Image.new("RGB", (W, W), "white"); d = ImageDraw.Draw(img)
    sc = W / 40.0; cx, cy = W // 2, W - 40
    for k in range(0, 41, 5): d.line([(0, cy - k * sc), (W, cy - k * sc)], fill=(230, 230, 230))
    d.polygon([(cx - 8, cy), (cx + 8, cy), (cx, cy - 18)], fill=(0, 160, 0))
    pts = [(cx - y * sc, cy - x * sc) for x, y in wps]
    d.line([(cx, cy)] + pts, fill=(255, 140, 0), width=3)
    for q in pts: d.ellipse([q[0] - 4, q[1] - 4, q[0] + 4, q[1] + 4], fill=(255, 100, 0))
    d.text((8, 8), f"{tag} cmd={['right','left','straight'][cmd]}  6 wps @0.5s, metres", fill="black")
    img.save(out / f"{tag}_5_waypoints_topdown.png")
    # strip: crop | 288x512 | tokens | recon
    tiles = [Image.fromarray(crop).resize((512, 288)), Image.fromarray(denorm(x)),
             Image.fromarray(tok_img).resize((512, 288), Image.NEAREST), Image.fromarray(denorm(recon[0])), img.resize((288, 288))]
    strip = Image.new("RGB", (512 * 4 + 288, 288 + 24), "white"); dd = ImageDraw.Draw(strip)
    for i, (im, lab) in enumerate(zip(tiles, ["1: crop 1600x900", "2: 288x512 input", "3: 576 VQ tokens", "4: VQ reconstruction", "5: output"])):
        strip.paste(im, (i * 512, 24)); dd.text((i * 512 + 6, 4), lab, fill="black")
    strip.save(out / f"{tag}_STAGES.png")
    summary.append({"t_us": t_us, "command": cmd, "waypoints_xy_m": wps.tolist(), "n_unique_tokens": int(len(np.unique(toks_grid)))})
    print(tag, "cmd", cmd, "wps[-1]=", np.round(wps[-1], 2), "unique tokens", len(np.unique(toks_grid)))

# all 8 cameras at the first timestep
first_t = frames[0].name.split("_")[0]
cams = sorted((sess / "images").glob(f"{first_t}_*.jpg"))
if cams:
    ims = [Image.open(c).convert("RGB").resize((480, 270)) for c in cams]
    grid = Image.new("RGB", (480 * 4, (270 + 20) * math.ceil(len(ims) / 4)), "white"); g = ImageDraw.Draw(grid)
    for i, (im, c) in enumerate(zip(ims, cams)):
        x0, y0 = (i % 4) * 480, (i // 4) * 290; grid.paste(im, (x0, y0 + 20)); g.text((x0 + 6, y0 + 3), c.name.split("_", 1)[1][:-4], fill="black")
    grid.save(out / f"ALL_8_CAMERAS_t{int(first_t)//1000:06d}ms.png")
json.dump(summary, open(out / "summary.json", "w"), indent=1)
print("done ->", out)
