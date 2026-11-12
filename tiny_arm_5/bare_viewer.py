from pathlib import Path
import time

import mujoco
import mujoco.viewer
import numpy as np

# The URDF has joints but no actuators, so add one PD position actuator per joint.
spec = mujoco.MjSpec.from_file(str(Path(__file__).parent / "tiny_arm_5.urdf"))
spec.option.timestep = 0.0005
spec.option.integrator = mujoco.mjtIntegrator.mjINT_IMPLICITFAST
# The URDF's approximate collision boxes overlap at startup.
spec.option.disableflags |= int(mujoco.mjtDisableBit.mjDSBL_CONTACT)
for joint in spec.joints:
    actuator = spec.add_actuator(name=f"position_{joint.name}", target=joint.name,
                                 trntype=mujoco.mjtTrn.mjTRN_JOINT,
                                 ctrllimited=1, ctrlrange=joint.range,
                                 forcelimited=1, forcerange=[-0.52, 0.52])
    actuator.set_to_position(kp=20.0, kv=0.5)

# Place the IK point near the end of the gripper.
spec.body("rotor_4").add_site(name="tip", pos=[0, -0.01, 0.09], size=[0.004])
model = spec.compile()
data = mujoco.MjData(model)

with mujoco.viewer.launch_passive(model, data) as viewer:
    viewer.opt.geomgroup[0] = 0  # Hide collision boxes.
    viewer.cam.lookat[:] = [0, -0.12, 0.08]
    viewer.cam.distance = 0.5
    viewer.cam.elevation = -25
    
    while viewer.is_running():
        viewer.sync()
        for _ in range(40):
            mujoco.mj_step(model, data)
        time.sleep(0.02)
