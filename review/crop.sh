#!/bin/bash
# crop.sh IMG y0% y1% [x0% x1%] -> scratchpad crop
S=/tmp/claude-0/-home-claude/ebc54a55-54d2-5da0-af01-30eb81d6449e/scratchpad
f=photos/$1.jpg; W=$(identify -format %w $f); H=$(identify -format %h $f)
x0=${4:-0}; x1=${5:-100}
convert $f -crop $(( W*(x1-x0)/100 ))x$(( H*($3-$2)/100 ))+$(( W*x0/100 ))+$(( H*$2/100 )) -resize 1500x1500 $S/c_$1_$2.jpg
echo $S/c_$1_$2.jpg
