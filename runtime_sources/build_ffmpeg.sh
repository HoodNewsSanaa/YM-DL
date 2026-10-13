#!/usr/bin/env bash
# Rebuild the distributed music-only FFmpeg. Requires a Linux host and MinGW-w64
# for Windows output; no source patches are applied. The archives are alongside
# this script. Cross-compiler GCC 13.2.0 / MinGW-w64 11.0.1 was used for the build.
set -euo pipefail
recipe_dir="$(cd "$(dirname "$0")" && pwd)"
target="${1:-windows}"
build_root="${YM_DL_RUNTIME_BUILD_DIR:-$recipe_dir/build-$target}"
jobs="${YM_DL_BUILD_JOBS:-4}"
mkdir -p "$build_root/src" "$build_root/prefix"
prefix="$build_root/prefix"
if [[ "$target" == windows ]]; then
    cross="${YM_DL_CROSS_PREFIX:-x86_64-w64-mingw32-}"
    export CC="${cross}gcc" AR="${cross}ar" RANLIB="${cross}ranlib"
    host_flags=(--host=x86_64-w64-mingw32)
    ff_target=(--target-os=mingw32 --arch=x86_64 --enable-cross-compile --cross-prefix="$cross" --enable-schannel --disable-pthreads --enable-w32threads)
    extra_ld=-static
elif [[ "$target" == linux ]]; then
    export CC="${CC:-gcc}" AR="${AR:-ar}" RANLIB="${RANLIB:-ranlib}"
    host_flags=()
    ff_target=()
    extra_ld=
else
    echo "Usage: build_ffmpeg.sh windows|linux" >&2
    exit 2
fi
export CFLAGS="-O2" LDFLAGS="$extra_ld"
export PKG_CONFIG_PATH="$prefix/lib/pkgconfig"
export PKG_CONFIG_LIBDIR="$prefix/lib/pkgconfig"
for archive in ffmpeg-9.0.2.tar.xz opus-1.5.2.tar.gz lame-3.100.tar.gz; do
    tar --no-same-owner -xf "$recipe_dir/$archive" -C "$build_root/src"
done
(
    cd "$build_root/src/opus-1.5.2"
    ./configure "${host_flags[@]}" --prefix="$prefix" --disable-shared --enable-static --disable-extra-programs --disable-doc
    make -j"$jobs"
    make install
)
(
    cd "$build_root/src/lame-3.100"
    ./configure "${host_flags[@]}" --prefix="$prefix" --disable-shared --enable-static --disable-frontend
    make -j"$jobs"
    make install
)
(
    cd "$build_root/src/ffmpeg-9.0.2"
    ./configure "${ff_target[@]}" --prefix="$prefix" --disable-autodetect --disable-everything \
        --disable-doc --disable-debug --disable-ffplay --disable-ffprobe --disable-x86asm \
        --enable-static --disable-shared --enable-ffmpeg --enable-version3 \
        --enable-libopus --enable-libmp3lame --pkg-config="${PKG_CONFIG:-pkg-config}" --pkg-config-flags=--static \
        --extra-cflags="-I$prefix/include" --extra-ldflags="-L$prefix/lib $extra_ld" \
        --enable-protocol=file,pipe,http,https,tcp,tls,crypto,data \
        --enable-demuxer=aac,mp3,mov,matroska,ogg,flac,wav,hls,concat,pcm_s16le \
        --enable-muxer=mp3,mp4,ipod,mov,ogg,opus,flac,wav,matroska,webm,pcm_s16le \
        --enable-decoder=aac,aac_latm,mp3,mp3float,opus,vorbis,flac,alac,pcm_s16le,pcm_s24le,pcm_s32le,pcm_f32le,pcm_f64le \
        --enable-encoder=aac,libopus,libmp3lame,flac,pcm_s16le \
        --enable-parser=aac,aac_latm,mpegaudio,opus,vorbis,flac \
        --enable-filter=aresample,anull,aformat,sine,abuffer,abuffersink --enable-indev=lavfi
    make -j"$jobs"
    make install
)
echo "Built runtime in $prefix/bin. Sources are unmodified; full configure/build logs should accompany distributed binaries."
