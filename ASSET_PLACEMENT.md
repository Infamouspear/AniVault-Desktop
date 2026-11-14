# AniVault supplied-art placement map

This map is defined before integration. Original uploaded artwork stays untouched; runtime sizing preserves aspect ratio. Asset filenames below are internal copies.

| Supplied asset | Internal asset | Intended screens | Scope | Maximum display | Cropping | Transparency | Small-window fallback |
|---|---|---|---|---|---|---|---|
| Splash Screen.png | splash.png | Startup only | Startup branding | 640 × 360, capped to 70% of available screen | No | Preserve source; supplied image is opaque | Contain at available size; skip if missing |
| Normal Vee.png | vee.png | Decorative sidebar/footer; sparse Home/setup | Normal only | Sidebar 190 × 240; empty Home 150 × 170 | No | Preserve supplied alpha | Reduce proportionally; hide below safe navigation area |
| Restricted Vee(1).png | restricted_vee.png | Restricted sidebar/footer or small secondary accent only | Restricted only | Sidebar 190 × 240 | No face/body cropping | Preserve supplied alpha | Contain below navigation; hide only when safe sidebar height is unavailable |
| restricted banner.png | restricted_banner.png | Restricted Home hero | Restricted only | Full available content width, 300–320 px height | Keep vertical face/body extent; crop only horizontal edges at narrow sizes | Source opaque; gradient overlay | Right-anchor focal artwork; text wraps |
| Icon(1).png | anivault_icon.png / anivault.ico | App, title bar, taskbar, dialogs; future shortcut/installer resource | Shared branding | UI 28 × 28; ICO sizes 16–256 | No | Preserve supplied alpha | Use appropriate icon resolution |
| Nohting Here Yet Vee.png | empty_vee.png | Empty Favorites, Collections, Downloads, local library | Shared non-adult empty-state art | 150 × 170 | No | Preserve supplied alpha | Compact 64 px or text only; one illustration per page |
| No Results Vee.png | no_results_vee.png | Search/filter/Discover valid zero results | Shared non-adult empty-state art | 150 × 170 | No | Preserve supplied alpha | Compact 64 px or text only; never use for network errors |
| All Caught Up Vee.png | caught_up_vee.png | Empty Continue Watching/Reading, completed queue | Shared non-adult empty-state art | 150 × 170 | No | Keep source unchanged; supplied alpha is fully opaque | Compact 64 px or text only |

## Composition rules

- Sidebar, hero and empty-state visibility are independent. A page may show one main illustration; the persistent sidebar mascot may coexist with it. Small-height sidebar safety still keeps navigation and Rescan accessible.
- Dense cards/details use media artwork; no mascot replaces a missing poster.
- Restricted Home uses restricted_banner.png as a wide cinematic hero. It scales to hero height and anchors right, preserving the complete vertical image and face/body; a cropped scenic-only backdrop from the same banner extends the left text area at wide widths, with a fade at the foreground seam. The cutout remains sidebar-only.
- Splash never becomes a page background. Normal Home uses a contained little fox only when the library is empty.
- Scope changes select the correct sidebar art and reset decoration ownership; locking never exposes Restricted cutout art.
- The app icon is copied without pixel edits. The ICO is a format/resolution derivative for Windows; packaging can point at this same resource. The clean Windows EXE/installer definitions use this same resource.
- Missing files degrade to text/neutral artwork, never to an asset from the wrong scope.

The uploaded restricted banner.png is copied byte-for-byte to restricted_banner.png and is the active Restricted hero. Splash is startup-only, with configurable minimum durations of 1 / 2.75 / 5 seconds; Off bypasses it. Empty states reserve distinct image/text/action rows and shrink artwork first.
