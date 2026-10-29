# Auto Retouch

Automatic portrait skin retouching (dodge & burn) for Windows. Everything runs locally; no photo is uploaded anywhere.

**Features**
- Automatic face detection for close-ups, half-body and full-body photos (Auto / Face / Half-body / Full-body)
- Skin mask that excludes eyes, eyebrows and lips; fix it by hand with Brush / Eraser / Invert / Undo. Soft brush (Hardness, Opacity) and adjustable Mask feather
- Views: Original, Preview (retouched), Mask
- Manual Dodge / Burn brushes (like Photoshop: size, hardness, flow, own Undo, optional "skin mask only")
- "Adjust (whole image)" panel in the style of Camera Raw: Light (Exposure, Contrast, Highlights, Shadows, Whites, Blacks), Color (Temperature, Tint, Hue, Vibrance, Saturation, Red, Green, Blue), Detail (Sharpen, Blur). Every slider is -100..+100 (Blur 0..100) with a number box you can type in; double-click a name to reset it; the (o) icon switches a whole section off/on; "only on skin mask" option
- "Mask light" slider: dodge / burn the whole masked area; Mask feather in pixels (default 20)
- Skin retouch sliders: Warmth, Blend, Strength, Texture (100 = keep skin texture exactly; above boosts, below softens), Reset (R)
- Zoom (+ / -, Fit, 100%, mouse wheel), pan (hold Space and drag, Move tool, or right-drag)
- Saves at full resolution, keeps colour profile and EXIF. "Save" never overwrites the original (adds `_retouched`).

**Shortcuts:** V move, B brush, E eraser, I invert, 1 dodge, 2 burn, [ ] brush size, R reset sliders, Space+drag pan, Ctrl+Z undo, 0 fit, Ctrl+1 100%. Ctrl+click with Brush fills the mask, with Eraser clears it.

**Download:** see the Releases page. If Windows SmartScreen warns, click More info -> Run anyway (the app is unsigned).

**Build:** push to GitHub; the workflow in `.github/workflows/build.yml` builds the exe and installer (Actions -> Artifacts).

Errors are written to `%TEMP%\AutoRetouch_error.log`.

**New in v7**
- Close image button (keeps the program open); contact line at the bottom-right (click the e-mail to write a message)
- Photoshop-style tool list with icons: Move, Brush, Quick Selection, Lasso (Add / Subtract), Eraser, History Brush, Dodge, Burn
- Mask view now shows the feathered mask that is really applied; Feather is in pixels
- Hair / beard protect slider (removes beard, stubble, hair and hairline from the skin mask)
- Spots slider: removes small moles, pimples and red blotches (never touches eyes, lips, nostrils; pores stay)
- Separate Dodge and Burn exposure sliders (used while painting) + a D&B layer % slider
- Brush size is in photo pixels (like Photoshop): it grows when you zoom in; zoom % is relative to the full-resolution photo
