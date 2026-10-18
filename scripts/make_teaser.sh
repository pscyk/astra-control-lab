#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
ffmpeg -hide_banner -loglevel error -y \
  -i docs/media/514006-zero.mp4 -i docs/media/514006-astra_RL.mp4 \
  -filter_complex "[0:v]fps=8[left];[1:v]fps=8,tpad=stop_mode=clone:stop_duration=2.4[right];[left][right]hstack=shortest=1,pad=iw:ih+94:0:54:color=0x16362d,drawtext=text='ASTRA / ZERO-SHOT':x=18:y=17:fontsize=19:fontcolor=0xf4f1e7,drawtext=text='ASTRA / + RESIDUAL':x=466:y=17:fontsize=19:fontcolor=0xd9ed8d,drawtext=text='RECORDED SIMULATION  /  ONE SELECTED SCENE  /  MODEL WAIT OMITTED':x=18:y=h-26:fontsize=13:fontcolor=0xf4f1e7,split[frames][palette_input];[palette_input]palettegen=max_colors=128[palette];[frames][palette]paletteuse=dither=bayer" \
  -loop 0 docs/media/teaser.gif
