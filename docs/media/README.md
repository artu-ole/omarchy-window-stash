# Documentation captures

Recorded on 14 November 2026 with Window Stash 1.36.1 on Omarchy 4.5.
The desktop uses Tokyo Night, a plain background from its dark palette,
JetBrainsMono Nerd Font, and a 1280 × 800 output at scale 1.

The captures show the running plugin and real Brave, Ghostty, Files and Evince
windows. All application content comes from offline example projects and
documents in a separate desktop, home directory and browser profile.

| Asset | Dimensions | Duration | Size |
|---|---|---|---|
| [static-dock.png](static-dock.png) | 1280 × 800 | Still | 81 KiB |
| [floating-dock.gif](floating-dock.gif) | 400 × 320 | 5.48 s | 679 KiB |
| [floating-icons-gravity.gif](floating-icons-gravity.gif) | 960 × 600 | 5.40 s | 167 KiB |
| [floating-previews.png](floating-previews.png) | 1280 × 800 | Still | 87 KiB |
| [interactive-preview.gif](interactive-preview.gif) | 960 × 624 | 6.83 s | 2791 KiB |

## Settings shown

All examples use Full animations at Normal speed and global stash visibility.
A badge of 2 groups two stashed Ghostty windows.

| Example | Relevant choices |
|---|---|
| Static dock | Bottom edge; app grouping; 150% icons; squircle frames; dock background; custom corners; live hover preview |
| Floating dock | Horizontal; Arc; free placement; 150% icons; icon and dock backgrounds |
| Floating icons | App grouping; 150%; no icon frames; physics; snap to edges |
| Floating previews | App grouping; direct resizing and free placement; independent sizes; hidden titles and frames; live updates |
| Interaction | One window; mouse input; hidden title/frame; Responsive resize updates; **Resize while interacting → On** |

The interaction clip completes a task, resizes the miniature, scrolls its content
and stops interaction. The application remains stashed throughout. Interactive
resizing is optional and Off by default.

## Refreshing the media

Use an isolated capture profile and offline sample files. Register a desktop entry
for an app-mode browser window so the shell can resolve its icon. Clear startup
notices before recording. Capture the actual output or a region around the feature:

```sh
wf-recorder -o OUTPUT -r 60 -D --no-dmabuf -c libx264 \
  -p crf=16 -p preset=veryfast -f capture.mp4
```

Stop the owned recorder with SIGINT. Crop and downscale for the documentation;
keep the original timing. The dock and gravity GIFs export at 50 FPS, the
interaction clip at 30 FPS. A basic palette-based export is:

```sh
ffmpeg -i capture.mp4 -filter_complex \
  'fps=50,split[a][b];[a]palettegen[p];[b][p]paletteuse=diff_mode=rectangle' \
  -loop 0 -map_metadata -1 capture.gif
```

Keep optimized PNG/GIF exports in this directory. Private capture profiles, raw
recordings, logs and temporary application files stay outside the repository.
