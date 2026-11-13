# Run this project on the Quest-connected laptop

## Intended network layout

```text
Quest Unity app (or Unity Editor on the Quest-connected laptop)
    -- target position/orientation as JSON UDP -->
Python IK + MuJoCo + goal preview on the simulation laptop, port 5006
    -- approved, calibrated five radians (+ optional raw gripper), binary UDP -->
Instructor receiver laptop at 192.168.1.244:5005 --> physical TinyARM-5
```

The destination **192.168.1.244:5005 is the physical binary receiver**, not the
Unity target server. Do not point Unity's JSON sender at that endpoint. Use
5006 for incoming Unity targets on the laptop to keep the two protocols separate,
even if Python and the receiver are eventually run on one computer.

Current state: the binary codec, mapping interface and confirmation gates exist,
but physical transport is intentionally locked. The sample sender establishes
the format and destination, not the model-to-motor calibration. This checkout
can test the full flow against a loopback mock without moving the physical arm.
Filling an IP address does not enable hardware execution.

## Get the repository and recreate Python

Install Git and Python 3.13 on the laptop if needed. In PowerShell, choose a
working folder and clone:

```powershell
git clone https://github.com/favour-appsprojects-code/tinyarm5-robot-teleoperation.git
cd tinyarm5-robot-teleoperation
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r python/requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s python -p "test*.py" -v
```

If you already cloned it, stop running project processes and run `git pull`
inside that checkout instead. Local environments, Unity caches, logs, build
artifacts and installed Editor modules are not transferred by Git.

## First run on that laptop: desktop + dry run

1. Install Unity **6000.4.8f1** through Unity Hub, with Android Build Support,
   Android SDK & NDK Tools and OpenJDK on this laptop too.
2. In Hub, add/open the repository's `unity` subfolder, not the repository root.
   Let Package Manager restore the committed manifest and lock file. The current
   manifest includes OpenXR 1.19.0 and Meta XR All-in-One 209.0.0 selected during
   setup. Do not copy the old computer's Library directory.
3. Start Python from the repository root:

```powershell
.\.venv\Scripts\python.exe python/server.py --port 5006 --output-profile python/config/mock.json
```

4. Open `Assets/Scenes/DesktopDemo.unity`. Select **Simulation UDP** and set
   **Server Address** to `127.0.0.1` and **Server Port** to `5006`, since Python
   and the Editor are on the same laptop. Save the scene if appropriate.
5. Press Play. Verify green feedback, target/rotation controls and amber goal
   preview. P requests a frozen packet preview; Enter confirms a **dry run**;
   G changes gripper intent. No binary command is transmitted in this mode.
6. For a deliberate binary loopback test, see docs/hardware.md's mock receiver
   procedure. The mock uses 127.0.0.1:15005, never the instructor's endpoint.

## Quest testing

Having the headset attached by USB does not itself make the current scene VR.
For PC Play-mode testing, Quest Link and a valid desktop OpenXR runtime/provider
must be configured. For standalone testing, finish the Meta Quest/Android build
profile and Android OpenXR provider setup, controller interaction profile, rig
and device authorization; then Build And Run. These are distinct paths.

The final project must use the standalone Quest app. Python may continue to run
on the laptop wirelessly; the final headset does not require a tethered PC VR app.
When Unity runs on the headset, `127.0.0.1` points at the headset, so change
**Server Address** to the Python laptop's actual Wi-Fi/LAN IPv4 address and keep
**Server Port** `5006`. In PowerShell on the Python laptop, run:

```powershell
# Replace the placeholder with the Python laptop's real LAN IP.
.\.venv\Scripts\python.exe python/server.py --bind <PYTHON-LAPTOP-LAN-IP> --port 5006 --output-profile python/config/mock.json
```

Do not enter the angle brackets literally. Both devices must be on a reachable
LAN; allow Python's incoming UDP 5006 on that local network when prompted.
Network isolation on a school/guest Wi-Fi can prevent device-to-device traffic.
Do not confuse the Python laptop's address with 192.168.1.244 unless they truly
are the same computer; even then the JSON port remains 5006.

Complete docs/quest3.md before expecting head/controller tracking or passthrough.
The prepared controller rig is opt-in under TinyARM's menu. It adds to the
existing project; no new project is needed.

## Physical receiver connection later

`python/config/hardware.unverified.json` already stores 192.168.1.244:5005.
The pending prerequisites are the instructor receiver's exact motor order,
joint zero/sign/offset/safe limits, gripper interface and motion/stop behavior.
After those are verified, a separate authorized implementation step can enable
the confirmed-pose binary path. Current code rejects enabling any physical
profile, even if its verified flag is manually changed.

See docs/hardware.md for the mapping table and questions to send the instructor.
