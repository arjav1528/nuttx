# AGENTS.md

## Cursor Cloud specific instructions

### Project overview

Apache NuttX is a real-time operating system (RTOS) for microcontrollers. This is the OS kernel repository. The companion apps repository (`apache/nuttx-apps`) must be present at `../apps` (i.e. `/apps`) relative to the workspace.

### Key development commands

- **Configure**: `./tools/configure.sh -l sim:nsh` (use `-l` for Linux host)
- **Build**: `make -j$(nproc)`
- **Clean**: `make distclean` (full clean including config)
- **Run sim**: `./nuttx` (after building sim target; sends you into NuttShell)
- **Lint a file**: `./tools/checkpatch.sh -f path/to/file.c`
- **Lint a commit range**: `./tools/checkpatch.sh -g HEAD~1..HEAD`

### Non-obvious caveats

1. **Default compiler must be GCC, not Clang**: The sim target requires `cc` to resolve to `gcc`. If `cc` points to `clang` (default on this VM), the build will fail with a missing `libclang_rt.profile` error. Fix: `sudo update-alternatives --set cc /usr/bin/gcc` and `sudo update-alternatives --set c++ /usr/bin/g++`.

2. **`kconfig-tweak` wrapper**: NuttX's `tools/sethost.sh` calls `kconfig-tweak` which is part of kconfig-frontends (a C project). A Python wrapper at `/usr/local/bin/kconfig-tweak` emulates this using pure Python. If it's missing, rebuild it or install kconfig-frontends from source.

3. **nxstyle binary**: The lint tool `tools/checkpatch.sh` requires a compiled `tools/nxstyle` binary. Build it with: `gcc -o tools/nxstyle tools/nxstyle.c`.

4. **nuttx-apps companion repo**: Must be cloned at `/apps` (which is `../apps` relative to `/workspace`). Without it, `configure.sh` and `make` will fail.

5. **kconfiglib (Python)**: The build system auto-detects kconfiglib by checking if `menuconfig` is in PATH. Ensure `~/.local/bin` is on PATH.

6. **Simulator exit**: Pipe commands to `./nuttx` or type `exit` in NSH to quit. The sim process does not exit on its own.

7. **Build system**: See `tools/configure.sh -L` for all available board configurations. The `sim:nsh` config is the easiest to test without hardware.
