"""Simulation-only model, bounded position IK, and secondary orientation IK."""
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
    for name, axis, color in [('x', [1, 0, 0], [1, 0, 0, 1]),
                              ('y', [0, 1, 0], [0, 1, 0, 1]),
                              ('z', [0, 0, 1], [0, 0.4, 1, 1])]:
        origin = np.array([0, -0.01, 0.09])
        spec.body('rotor_4').add_geom(name=f'tip_axis_{name}',
            type=mujoco.mjtGeom.mjGEOM_CAPSULE,
            fromto=[*origin, *(origin + 0.045 * np.array(axis))],
            size=[0.0015, 0, 0], rgba=color, group=1,
            contype=0, conaffinity=0, mass=0)
    model = spec.compile()
    return model


class IK:
    def __init__(self, model):
        self.model = model
        self.data = mujoco.MjData(model)
        self.tip = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SITE, 'tip')
        self.jac = np.zeros((3, model.nv))
        self.jacr = np.zeros((3, model.nv))

    def orientation(self, q):
        """Tip rotation in robot world coordinates, quaternion [w,x,y,z]."""
        self.position(q)
        quat = np.empty(4)
        mujoco.mju_mat2Quat(quat, self.data.site_xmat[self.tip])
        return quat

    def rotation_error(self, desired, q):
        """Shortest world-frame rotation vector; stable also near 180 degrees."""
        self.position(q)
        desired_matrix = np.empty(9)
        mujoco.mju_quat2Mat(desired_matrix, desired)
        difference = desired_matrix.reshape(3, 3) @ self.data.site_xmat[self.tip].reshape(3, 3).T
        quat = np.empty(4)
        mujoco.mju_mat2Quat(quat, difference.ravel())
        if quat[0] < 0:
            quat *= -1
        error = np.empty(3)
        mujoco.mju_quat2Vel(error, quat, 1)
        return error

    def solve_pose(self, target, seed, orientation=None, tolerance=0.0015):
        """Position is mandatory; orientation is best effort within that bound.

        Retain the position solution if orientation cannot improve. The exact
        position-Jacobian null space gives orientation only spare joint motion.
        Nonlinear candidates are position-corrected and checked before acceptance.
        """
        desired = None
        if orientation is not None:
            desired = np.asarray(orientation, dtype=float)
            if desired.shape != (4,) or not np.all(np.isfinite(desired)):
                raise ValueError('Orientation must be a finite wxyz quaternion')
            norm = np.linalg.norm(desired)
            if norm < 1e-8:
                raise ValueError('Zero quaternion')
            desired = desired / norm
        q, position_error, reachable = self.solve(target, seed, tolerance)
        if desired is None:
            return q, position_error, reachable, None
        angle = float(np.linalg.norm(self.rotation_error(desired, q)))
        if not reachable:
            return q, position_error, False, angle
        for _ in range(24):
            error = self.rotation_error(desired, q)
            if np.linalg.norm(error) < np.deg2rad(1):
                break
            mujoco.mj_jacSite(self.model, self.data, self.jac, self.jacr, self.tip)
            # Recompute the null space with outward-moving, saturated joints
            # locked. Clipping an unconstrained step afterwards destroys its
            # position cancellation and can stall the secondary objective.
            free = np.ones(self.model.nv)
            for _ in range(self.model.nv + 1):
                position_jac = self.jac * free
                null = np.diag(free) - np.linalg.pinv(position_jac, rcond=1e-5) @ position_jac
                secondary = self.jacr @ null
                dq = null @ secondary.T @ np.linalg.solve(
                    secondary @ secondary.T + 0.02**2 * np.eye(3), error)
                blocked = ((q >= self.model.jnt_range[:, 1]-1e-5) & (dq > 0)) | (
                    (q <= self.model.jnt_range[:, 0]+1e-5) & (dq < 0))
                blocked &= free > 0
                if not np.any(blocked):
                    break
                free[blocked] = 0
            dq *= min(1, 0.08 / max(np.max(np.abs(dq)), 1e-12))
            for scale in (1, 0.5, 0.25):
                candidate = np.clip(q + scale*dq, *self.model.jnt_range.T)
                # Use the existing position budget instead of overconstraining
                # correction to 0.5 mm and undoing feasible rotation motion.
                candidate, distance, ok = self._solve_local(target, candidate, tolerance * 0.8)
                candidate_angle = float(np.linalg.norm(self.rotation_error(desired, candidate)))
                if distance <= tolerance and candidate_angle < angle - 1e-6:
                    q, position_error, angle = candidate, distance, candidate_angle
                    break
            else:
                break
        return q, position_error, True, angle

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
