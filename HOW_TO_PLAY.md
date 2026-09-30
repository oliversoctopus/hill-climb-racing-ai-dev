# How to Play — Browser Game (you vs. the AI)

The full guide lives in **`web/HOW_TO_PLAY.md`** (modes, controls, the Bug-probe debug panel, etc.) — it's kept there because the whole site is self-contained in `web/`.

The only repo-root-specific note: to serve locally from the repo root, point the server at the `web/` folder (ONNX Runtime Web **cannot load over `file://`**):

```powershell
python\.venv\Scripts\python.exe -m http.server 8765 --directory web
```

Then open **http://localhost:8765/** and follow `web/HOW_TO_PLAY.md` from step 2.
