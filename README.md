# Zephyr-Alif (Work in Progress)

This repository contains an example CMSIS solution that builds three basic Zephyr examples for Alif development boards.
It can be easily adapted to other boards or examples. It uses Zephyr's `west` build system to create the application
image and the [Arm CMSIS Debugger](https://marketplace.visualstudio.com/items?itemName=Arm.vscode-cmsis-debugger) to
download the image to flash memory and run it on the target hardware.

## Quick start

The example setup uses an Arm [ULINKplus debug adapter](https://www.arm.com/products/development-tools/debug-probes/ulink-plus) connected to the
[Alif Semiconductor DevKit-E7](https://www.keil.arm.com/boards/alif-semiconductor-devkit-e7-d1-cd88670/guide/).

- Install the [Arm Keil Studio Pack for VS Code](https://marketplace.visualstudio.com/items?itemName=Arm.keil-studio-pack),
  then clone this repository and open its folder in VS Code.
- [Install Alif Zephyr SDK 2.3](#zephyr-installation) and [configure its environment variables](#configure-vs-code).
- Restart VS Code, then select **CMSIS > ... > Open Solution in Workspace** and open the example's
  `*-gcc.csolution.yml` or `*-ac6.csolution.yml` file for the compiler you want to use.
- Use **Manage Solution Settings** to select the board and application, then **Build solution**.
- Connect the board and select **Load & Debug application**. See [Work with the example](#work-with-the-example) for
  dual-core projects.

> [!NOTE]
> Ensure that the **Arm CMSIS Solution** extension is version 1.72.0 or later.

> [!TIP]
> If configuration or build errors occur, use **Clean All 'out' and 'tmp' directories** from the CMSIS view menu to
> remove stale CMake cache files before rebuilding.

## Zephyr installation

The following instructions apply to Linux, macOS, and Windows. Install a supported version of Python 3 and Git before
continuing.

> [!WARNING]
> On Windows, use Python 3.13 or earlier because the `windows-curses` package is not yet available for Python 3.14.

### Create the workspace

- Open a terminal as a regular user. On Windows, use `cmd.exe` for the commands below.

- In any suitable working directory, create an `sdk-alif` directory and change into it:

  ```console
  mkdir sdk-alif
  cd sdk-alif
  ```

- Create a virtual environment. Use the command for your operating system:

  Linux and macOS:

  ```sh
  python3 -m venv .venv
  ```

  Windows:

  ```bat
  python -m venv .venv
  ```

- Activate the virtual environment.

  Linux and macOS:

  ```sh
  source .venv/bin/activate
  ```

  Windows (`cmd.exe`):

  ```bat
  .venv\Scripts\activate.bat
  ```

  Once activated, the shell prompt is prefixed with `(.venv)`. Activate the environment again whenever you open a
  new terminal. Run `deactivate` to leave it.

- Install `west`. After activation, `python` refers to the virtual environment on every supported operating system:

  ```console
  python -m pip install west
  ```

- Get the Zephyr source code using the Alif SDK:

  ```console
  west init -m https://github.com/alifsemi/sdk-alif.git --mr v2.3.0
  west update
  ```

- Apply the Arm Compiler linker compatibility patch required by Alif SDK 2.3. Replace `/path/to/Zephyr-Alif-1` with
  the absolute path to this repository:

  ```console
  git -C zephyr apply /path/to/Zephyr-Alif-1/.github/patches/sdk-alif-v2.3.0-armclang-linker.patch
  ```

  The patch is harmless for GCC builds and is also applied by this repository's CI workflow.

- Install the Python dependencies required by Zephyr:

  ```console
  python -m pip install -r zephyr/scripts/requirements.txt
  ```

### Configure VS Code

The CMSIS Solution extension needs the Zephyr workspace and virtual environment paths when it runs `west`.

1. In VS Code, open **Settings** and search for **Cmsis-Csolution: Environment Variables**.
2. Select the **User** or **Workspace** setting and choose **Add Item** for each variable below. Replace `<work-dir>`
   with the directory in which you created your `sdk-alif` workspace.

   | Variable | Linux and macOS | Windows |
   |---|---|---|
   | `ZEPHYR_BASE` | `/<work-dir>/sdk-alif/zephyr` | `C:\<work-dir>\sdk-alif\zephyr` |
   | `PATH` | `/<work-dir>/sdk-alif/.venv/bin` | `C:\<work-dir>\sdk-alif\.venv\Scripts` |
   | `VIRTUAL_ENV` | `/<work-dir>/sdk-alif/.venv` | `C:\<work-dir>\sdk-alif\.venv` |

3. Fully restart VS Code so that the extension uses the new environment.

For more information, see [Work with Zephyr applications](https://mdk-packs.github.io/vscode-cmsis-solution-docs/zephyr.html#set-environment-variables).

### C library selection

Each example has a separate CMSIS solution for each compiler and explicitly selects that compiler's default C
library:

| Solution filename | Compiler | C library |
|---|---|---|
| `*-gcc.csolution.yml` | GCC | Full Newlib |
| `*-ac6.csolution.yml` | Arm Compiler 6 | Arm Compiler C library |

GCC solutions select full Newlib:

```yml
west-defs:
  - CONFIG_NEWLIB_LIBC: y
  - CONFIG_NEWLIB_LIBC_NANO: n
```

AC6 projects use the Arm Compiler C library:

```yml
west-defs:
  - CONFIG_ARMCLANG_STD_LIBC: y
```

These definitions are passed to Zephyr by `west build`. The selection is explicit because
`CONFIG_REQUIRES_FULL_LIBC` only requests any complete C library and may select Picolibc instead of the library
provided by the compiler toolchain.

## SETOOLS

Before flashing an example to the DevKit-E7 board, program the device's ATOC using Alif SETOOLS. This process only has
to be performed once for each single- or dual-core project.

Refer to the section [Usage](https://github.com/alifsemi/alif_ensemble-cmsis-dfp/blob/main/docs/Overview.md#usage)
on the Alif Semiconductor Ensemble DFP/BSP overview page for information about how to set up these tools.

In VS Code, select **Terminal > Run Task** and run:

- **Alif: Install M55_HE and M55_HP debug stubs (dual core configuration)**

## DevKit-E7 UART console

The DevKit-E7 routes one application UART at a time to the second channel of the on-board USB-to-UART bridge. Connect
the **PRG USB** port and configure header **J26** for the core whose `printk` output you want to monitor:

| Core | Console UART | J26 jumpers |
|---|---|---|
| M55_HE (RTSS-HE) | UART4 | Pins 3-5 and 4-6 (factory default) |
| M55_HP (RTSS-HP) | UART2 | Pins 1-3 and 2-4 |

Open the application UART serial port at **115200 baud, 8 data bits, no parity, and 1 stop bit (8-N-1)**. Do not use
the other USB serial channel, which is the SEUART used by SETOOLS for programming. Power off the board before moving
the J26 jumpers.

J26 cannot connect UART2 and UART4 to the on-board bridge simultaneously. To monitor output from both cores in the
`IPM_ARM_MHUv2` example, connect a separate **1.8 V-compatible** USB-to-UART adapter and a common ground to the UART
that is not selected by J26.

## Example descriptions

| Example name                              | Description   |
|---                                        |---            |
| [HelloWorld](./Examples/HelloWorld/) | The simplest Zephyr application: prints `Hello World! <board>` on the UART console of the M55_HE core. A good first build to check that the toolchain and Zephyr environment work. Copied unchanged from [Zephyr's hello_world sample](https://github.com/zephyrproject-rtos/zephyr/tree/main/samples/hello_world). |
| [IPM_ARM_MHUv2](./Examples/IPM_ARM_MHUv2/) | This example demonstrates dual-core debugging and inter-core communication between two Cortex-M55 cores using Arm's Message Handling Unit v2 (MHUv2). It uses Zephyr's Inter-Processor Mailbox (IPM) API to exchange messages and trigger interrupts between the cores. More details in [Alif-Zephyr-SDK/ipm_arm_mhuv2](https://github.com/alifsemi/sdk-alif/tree/v2.3.0/samples/drivers/ipm/ipm_arm_mhuv2). |
| [LPI2C](./Examples/LPI2C/) | LPI2C (Low Power Inter-Integrated Circuit) is a low-power version of the standard I2C bus controller. This example uses two threads to emulate an I2C master and slave communicating through the LPI2C driver. All data transfers occur internally via hardware loopback. More details in [Alif-Zephyr-SDK/lpi2c](https://github.com/alifsemi/sdk-alif/tree/v2.3.0/samples/drivers/lpi2c). |

## Work with the example

When working on a dual-core project:

- Start the **M55_HP CMSIS_DAP@pyOCD (launch)** debug session first, followed by **M55_HE CMSIS_DAP@pyOCD (attach)**.
- After starting the second debug session, the program will halt at `cpu_idle.S`. This occurs because the second core
  remains in its idle loop until it receives a valid entry point. To resolve this, add the following commands to the
  **M55_HE CMSIS_DAP@pyOCD (attach)** section in `launch.json`:

  ```bash
  "initCommands": [
     "monitor reset halt",
     "tbreak main"
  ]
  ```

- Set `updateConfiguration` to `manual` to prevent your settings from being overwritten.
