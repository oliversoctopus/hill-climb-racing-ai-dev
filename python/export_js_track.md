# Exporting a JS track to JSON

To compare the Python port side-by-side with the JS version on the **same**
terrain, copy a track from the JS game and load it in `play.py`.

## How to do it

1. Open `index.html` in a browser. Open the developer console (F12).
2. Paste this snippet:

```js
copy(JSON.stringify({
  vectors: groundTemplate.vectors.map(v => ({ x: v.x * SCALE, y: v.y * SCALE })),
  grass: groundTemplate.grassPositions,
  distance: groundTemplate.distance
}));
```

   That puts a JSON string on your clipboard. (`vectors` are stored in meters
   in the JS object after `randomizeGround`, so we multiply by `SCALE` to get
   pixel space — matching what `ground.py` expects.)

3. Save it to `python/tracks/sample_001.json`.
4. Run `python play.py tracks/sample_001.json` — same terrain as the JS run.

For visual side-by-side, refresh the JS page (so the terrain stays as
exported), then drive both versions and compare:
- Acceleration on the flat at spawn
- Climb speed on the first hill
- Wheelie/flip behavior
- Suspension bounce on the bumpy section
