"""Simulation-only model and bounded, position-only damped least-squares IK."""
from pathlib import Path
import mujoco
import numpy as np

MODEL = Path(__file__).resolve().parents[1] / 'tiny_arm_5' / 'tiny_arm_5.urdf'


def load_robot():
    spec = mujoco.MjSpec.from_file(str(MODEL))
    spec.option.timestep = 0.0005
    spec.option.integrator = mujoco.mjtIntegrator.mjINT_IMPLICITFAST
    # Same approximation as the supplied viewer. Not collision-safe for hardware.
    spec.option.disableflags |= int(mujoco.mjtDisableBit.mjDSBL_CONTACT)
    for joint in spec.joints:
        actuator = spec.add_actuator(name=f'position_{joint.name}', target=joint.name,
            trntype=mujoco.mjtTrn.mjTRN_JOINT, ctrllimited=1, ctrlrange=joint.range,
            forcelimited=1, forcerange=[-0.52, 0.52])
        actuator.set_to_position(kp=20, kv=0.5)
    spec.body('rotor_4').add_site(name='tip', pos=[0, -0.01, 0.09], size=[0.004])
    model = spec.compile()
    return model


class IK:
    def __init__(self, model):
        self.model = model
        self.data = mujoco.MjData(model)
        self.tip = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SITE, 'tip')
        self.jac = np.zeros((3, model.nv))

    def position(self, q):
        self.data.qpos[:] = q
        mujoco.mj_forward(self.model, self.data)
        return self.data.site_xpos[self.tip].copy()

    def solve(self, target, seed, tolerance=0.0015):
        # Prefer continuity. A joint-limit local minimum can otherwise make a
        # previously reachable target (including Unity's reset) stay rejected.
        result = self._solve_local(target, seed, tolerance)
        if result[2]:
            return result
        fallback = self._solve_local(target, np.zeros(self.model.nq), tolerance)
        return fallback if fallback[1] < result[1] else result

    def _solve_local(self, target, seed, tolerance=0.0015):
        target = np.asarray(target, dtype=float)
        if target.shape != (3,) or not np.all(np.isfinite(target)):
            raise ValueError('Target must contain three finite metres')
        q = np.clip(np.asarray(seed).copy(), *self.model.jnt_range.T)
        best, best_error = q.copy(), float('inf')
        for _ in range(100):
            error = target - self.position(q)
            distance = np.linalg.norm(error)
            if distance < best_error:
                best, best_error = q.copy(), float(distance)
            if distance <= tolerance:
                break
            mujoco.mj_jacSite(self.model, self.data, self.jac, None, self.tip)
            dq = self.jac.T @ np.linalg.solve(self.jac @ self.jac.T + 0.003**2 * np.eye(3), error)
            # Bounded steps and backtracking avoid large singularity jumps.
            dq *= min(1, 0.12 / max(np.max(np.abs(dq)), 1e-12))
            for scale in (1, 0.5, 0.25, 0.1):
                candidate = np.clip(q + scale * dq, *self.model.jnt_range.T)
                if np.linalg.norm(target - self.position(candidate)) < distance:
                    q = candidate
                    break
            else:
                break
        return best, best_error, best_error <= tolerance
